// LabLens: upload a report, compare with the original, confirm, see trends.
import { act, api, ask, badge, emptyState, form, h, listRow, loadingRows, plural, RANGE_WORDS, rowList, show, stateTrack, trendChart, when } from './ui.js';
import { icon } from './icons.js';
import { needPatient } from './overview.js';

const BASE = '/api/addons/lablens';
const POLL_MS = 1500;
const READ_BY = { 'pdf-text': 'Read from the text in the PDF', 'ai-vision': 'Read by AI', manual: 'Entered by hand', none: 'Not read yet' };

export function labTrends(trends) {
    if (!trends.series.length) return emptyState('No trends yet', 'Confirmed lab results will show here over time.');
    return [
        trends.notes.map((note) => h('div', { class: 'banner' }, note)),
        h('div', { class: 'columns' }, trends.series.map((line) => {
            const latest = line.points.at(-1);
            const range = latest.reference_text;
            return h('div', { class: 'sheet' }, trendChart({
                label: line.label,
                unit: line.unit,
                points: line.points,
                low: latest.reference_low,
                high: latest.reference_high,
                describe: (point) => `${RANGE_WORDS[point.range_status]}${point.laboratory ? `, ${point.laboratory}` : ''}`,
            }), h('p', { class: 'muted' }, range ? `Shaded: the printed range on the latest report, ${range}.` : ''));
        })),
    ];
}

// Where a result stands, in words and a shape. Pending is the highlighter: nobody has checked it yet.
const RESULT_STATE = {
    pending: ['To check', 'pending'],
    accepted: ['Accepted', 'good'],
    corrected: ['Fixed by hand', 'good'],
    rejected: ['Removed', 'bad'],
};

function reviewRow(result, report, context, reload) {
    const needsEye = result.confidence === 'review' && result.review_status === 'pending';
    const locked = report.status === 'confirmed';
    const set = (body) => async () => {
        const saved = await act(() => api(`${BASE}/results/${result.id}`, { method: 'PATCH', body }), context);
        if (saved) reload();
    };
    const correct = async () => {
        const value = await ask(`Correct value for ${result.original_name}`, result.value_text);
        if (value === null) return;
        const unit = await ask('Unit', result.unit);
        if (unit === null) return;
        set({ action: 'correct', value_text: value, unit })();
    };
    const [word, kind] = RESULT_STATE[result.review_status] || [result.review_status, ''];
    const stateTag = result.review_status === 'pending'
        ? (needsEye ? h('mark', {}, 'Check this') : h('span', { class: 'status warn' }, 'To check'))
        : badge(locked && result.review_status === 'accepted' ? 'Confirmed' : word, kind);
    return h('li', { class: `result-row ${result.review_status}${needsEye ? ' needs-eye' : ''}` },
        h('div', { class: 'result-name' },
            h('strong', {}, result.original_name),
            result.standard_name && result.standard_name.toLowerCase() !== result.original_name.toLowerCase()
                ? h('span', { class: 'muted' }, result.standard_name) : null),
        h('div', { class: 'result-value' },
            h('span', { class: 'value' }, needsEye ? h('mark', {}, `${result.value_text} ${result.unit}`) : `${result.value_text} ${result.unit}`),
            h('span', { class: 'muted' }, [result.reference_text && `Range ${result.reference_text}`, result.range_status !== 'no_range' ? RANGE_WORDS[result.range_status] : null].filter(Boolean).join(' · '))),
        h('div', { class: 'result-state' }, stateTag),
        result.issues.length ? h('ul', { class: 'reasons result-issues' }, result.issues.map((issue) => h('li', {}, issue))) : null,
        locked ? null : h('div', { class: 'result-actions', role: 'group', 'aria-label': `Check ${result.original_name}` },
            h('button', { type: 'button', class: `quiet${result.review_status === 'accepted' ? ' chosen' : ''}`, 'aria-pressed': String(result.review_status === 'accepted'), onclick: set({ action: 'accept' }) }, icon('check', 'button-icon'), 'Accept'),
            h('button', { type: 'button', class: `quiet${result.review_status === 'corrected' ? ' chosen' : ''}`, 'aria-pressed': String(result.review_status === 'corrected'), onclick: correct }, 'Fix'),
            h('button', { type: 'button', class: `quiet${result.review_status === 'rejected' ? ' chosen' : ''}`, 'aria-pressed': String(result.review_status === 'rejected'), onclick: set({ action: 'reject' }) }, 'Remove')));
}

function originalView(report) {
    const src = `/api/documents/${report.document_id}/file?inline=1`;
    return report.filename?.match(/\.(jpe?g|png)$/i)
        ? h('img', { class: 'original image', src, alt: 'The original report' })
        : h('iframe', { class: 'original', src, title: 'The original report' });
}

const STAGES = [['read', 'Read'], ['check', 'Check each result'], ['confirmed', 'Confirmed']];

async function renderReport(area, reportId, context) {
    const reload = () => renderReport(area, reportId, context);
    const report = await api(`${BASE}/reports/${reportId}/extraction`);
    if (report.status === 'processing') {
        show(area, stateTrack(STAGES, 'read', 'Where this report is'), h('p', { class: 'muted' }, 'Reading the report…'), loadingRows('Reading the report…'));
        setTimeout(() => { if (area.isConnected) reload(); }, POLL_MS);
        return;
    }
    const confirmed = report.status === 'confirmed';
    const collected = h('input', { type: 'date', value: report.collected_at || '', 'aria-label': 'Date collected' });
    const identity = h('input', { type: 'checkbox' });
    const compared = h('input', { type: 'checkbox' });
    const manual = form(
        [
            { name: 'test_name', label: 'Test', required: true },
            { name: 'value_text', label: 'Result', required: true },
            { name: 'unit', label: 'Unit' },
            { name: 'reference_text', label: "Lab's range" },
        ],
        'Add result',
        async (values) => {
            await act(() => api(`${BASE}/reports/${reportId}/results`, { method: 'POST', body: values }), context, 'Added');
            reload();
        },
        { inline: true },
    );
    manual.querySelector('button[type="submit"]').classList.add('quiet');
    const count = (state) => report.results.filter((row) => row.review_status === state).length;
    const pending = count('pending');
    const summary = confirmed
        ? `${plural(report.results.filter((row) => row.review_status !== 'rejected').length, 'result')} in the record`
        : [pending && `${pending} to check`, count('accepted') && `${count('accepted')} accepted`, count('corrected') && `${count('corrected')} fixed`, count('rejected') && `${count('rejected')} removed`].filter(Boolean).join(' · ');
    show(area,
        stateTrack(STAGES, confirmed ? 'confirmed' : 'check', 'Where this report is'),
        h('div', { class: 'section-head' },
            h('h2', {}, confirmed ? `Confirmed: ${report.filename}` : 'Check against the original'),
            h('p', { class: 'muted' }, [
                report.laboratory, report.name_on_report && `Name on report: ${report.name_on_report}`,
                READ_BY[report.extraction_method] || READ_BY.none,
            ].filter(Boolean).join(' · '))),
        report.failure_reason ? h('div', { class: 'banner danger' }, report.failure_reason) : null,
        report.identity_check === 'mismatch'
            ? h('div', { class: 'banner danger' }, `The name on this report is ${report.name_on_report}, which differs from the open patient.`)
            : null,
        // Lines that looked like results but weren't read. A prompt to look at the original, where
        // a missing result would otherwise go unnoticed.
        report.lines_not_read ? h('div', { class: 'banner danger', id: 'lines-not-read', role: 'status' },
            h('strong', {}, `${plural(report.lines_not_read, 'line')} not read. `),
            'Find them in the original report and add each result by hand if it belongs here.',
            report.unread_lines?.length ? h('ul', { class: 'reasons' }, report.unread_lines.map((line) => h('li', {}, line))) : null) : null,
        h('div', { class: 'compare' },
            h('section', { class: 'compare-original', 'aria-label': 'Original report' },
                h('h3', {}, icon('file', 'button-icon'), 'Original report'),
                originalView(report)),
            h('section', { class: 'compare-results', 'aria-label': 'Results read from it' },
                h('div', { class: 'compare-head' },
                    h('h3', {}, 'Results read from it'),
                    summary ? h('span', { class: 'muted' }, summary) : null),
                report.results.length
                    ? h('ol', { class: 'result-list' }, report.results.map((result) => reviewRow(result, report, context, reload)))
                    : emptyState('No results found', 'Add each result by hand from the original report.'),
                confirmed ? null : h('details', { class: 'quiet-details', open: !report.results.length }, h('summary', {}, 'Add a result by hand'), manual),
                report.status === 'failed' || report.status === 'needs_manual_entry' ? h('button', {
                    type: 'button',
                    class: 'quiet',
                    onclick: async () => {
                        await act(() => api(`${BASE}/reports/${reportId}/retry`, { method: 'POST' }), context);
                        reload();
                    },
                }, 'Try reading again') : null)),
        report.status === 'needs_review' ? h('div', { class: 'action-bar sticky confirm-bar' },
            h('div', { class: 'confirm-fields' },
                h('p', { class: 'action-note' }, report.to_review
                    ? `Still to check: ${plural(report.to_review, 'highlighted result')}.`
                    : 'Accept, fix or remove each result, or tick below once you have compared them all with the original report.'),
                h('label', { class: 'inline-label' }, 'Date the sample was collected', collected),
                report.identity_check === 'mismatch' ? h('label', { class: 'tick' }, identity, 'I confirm this report belongs to this patient') : null,
                report.results.some((row) => row.review_status === 'pending')
                    ? h('label', { class: 'tick' }, compared, 'I compared every result I have not accepted, fixed or removed with the original report')
                    : null),
            h('button', {
                type: 'button',
                class: 'primary-lg',
                onclick: async () => {
                    const done = await act(() => api(`${BASE}/reports/${reportId}/confirm`, {
                        method: 'POST',
                        body: { collected_at: collected.value || null, acknowledge_identity: identity.checked, compared_with_original: compared.checked },
                    }), context, 'Report confirmed');
                    if (done) context.refresh();
                },
            }, 'Confirm and add to the record')) : null,
    );
}

const REPORT_STATE = {
    processing: ['Reading', 'warn', 'clock'],
    needs_review: ['Needs review', 'pending', 'file'],
    needs_manual_entry: ['Enter by hand', 'warn', 'file'],
    failed: ['Could not read', 'bad', 'alert'],
    confirmed: ['Confirmed', 'good', 'check'],
};

function reportRows(reports, area, context) {
    return rowList(reports.map((row) => {
        const [word, kind, mark] = REPORT_STATE[row.status] || [row.status, '', 'file'];
        return listRow({
            leadIcon: mark,
            tone: kind === 'pending' ? 'warn' : kind === 'bad' ? 'urgent' : kind,
            title: row.filename,
            meta: [row.collected_at ? `Collected ${when(row.collected_at)}` : 'Collection date not set', plural(row.result_count, 'result')].join(' · '),
            tags: [kind === 'pending' ? h('mark', {}, word) : badge(word, kind)],
            onclick: async () => {
                await renderReport(area, row.id, context);
                area.scrollIntoView({ block: 'start', behavior: 'smooth' });
            },
            attrs: { 'aria-label': `Open ${row.filename}, ${word}` },
        });
    }), emptyState('No reports yet', 'Upload a lab report to read its results.'));
}

export async function renderLabLens(container, context) {
    const { patient } = context;
    if (!patient) return needPatient(container);
    const [reports, trends] = await Promise.all([
        api(`${BASE}/patients/${patient.id}/reports`),
        api(`${BASE}/patients/${patient.id}/trends`),
    ]);
    const area = h('div', { class: 'stage-area' });
    const list = h('div', {});
    const fillList = (rows) => show(list, reportRows(rows, area, context));
    fillList(reports);
    const upload = patient.relationship === 'caregiver' ? null : form(
        [{ name: 'file', label: 'Lab report (PDF, JPG or PNG)', type: 'file', required: true }],
        'Upload report',
        async ({ file }) => {
            const data = new FormData();
            data.append('patient_id', patient.id);
            data.append('file', file);
            const made = await act(() => api(`${BASE}/reports`, { method: 'POST', form: data }), context);
            if (!made) return;
            await renderReport(area, made.id, context);
            fillList(await api(`${BASE}/patients/${patient.id}/reports`));
        },
        { inline: true },
    );
    const waiting = reports.filter((row) => row.status === 'needs_review').length;
    show(container,
        h('h1', {}, 'LabLens'),
        h('p', { class: 'lede' }, 'Reads lab reports into results you can check and follow over time. It shows where a value sits against the lab\'s range and does not diagnose. Talk to your care team about what a result means.'),
        upload ? h('section', { class: 'sheet upload-panel' }, h('h2', {}, 'Add a report'), upload) : null,
        area,
        h('div', { class: 'section-head' }, h('h2', {}, 'Reports'), waiting ? h('p', { class: 'muted' }, `${waiting} waiting for a check`) : null),
        list,
        h('h2', {}, 'Trends'),
        labTrends(trends),
    );
    return undefined;
}
