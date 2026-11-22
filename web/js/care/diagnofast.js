// DiagnoFast: reception sends a link for one interview, and the doctor reads the report.
import { act, api, form, h, show, when } from './ui.js';
import { packPanel } from './pack.js';
import { renderBookings } from './opd.js';
import { graphsPanel } from './graphs.js';
import { icon, initials } from './icons.js';

const STATUS_TEXT = {
    waiting: 'Not started',
    in_progress: 'Answering now',
    preparing_report: 'Preparing report',
    done: 'Report ready',
    report_failed: 'Answers ready',
    expired: 'Link expired',
};
const POLL_MS = 10000;
let poll = null;

function keepFresh(work) {
    clearInterval(poll);
    poll = setInterval(() => {
        if (!window.location.hash.startsWith('#/diagnofast')) clearInterval(poll);
        else work().catch(() => {});
    }, POLL_MS);
}

function row(label, value) {
    return h('p', {}, h('strong', {}, `${label}: `), value || 'Not stated');
}

function bullets(title, items) {
    return h('div', {}, h('strong', {}, title), h('ul', {}, (items.length ? items : ['None stated']).map((item) => h('li', {}, item))));
}

function reportTable(headers, rows) {
    return h('div', { class: 'requisition-table-wrap' }, h('table', { class: 'requisition-table' },
        h('thead', {}, h('tr', {}, headers.map((title) => h('th', { scope: 'col' }, title)))),
        h('tbody', {}, rows.map((cells) => h('tr', {}, cells.map((cell) => h('td', {}, cell)))))));
}

function barcode(id) {
    // Code 39, digits plus start/stop. Encodes only the local intake number, no patient data.
    const patterns = ['nnnwwnwnn', 'wnnwnnnnw', 'nnwwnnnnw', 'wnwwnnnnn', 'nnnwwnnnw',
        'wnnwwnnnn', 'nnwwwnnnn', 'nnnwnnwnw', 'wnnwnnwnn', 'nnwwnnwnn'];
    const digits = String(id).replace(/[^0-9]/g, '');
    const codes = ['nwnnwnwnn', ...[...digits].map((digit) => patterns[Number(digit)]), 'nwnnwnwnn'];
    const bars = h('div', { class: 'intake-barcode', 'aria-hidden': 'true' });
    codes.forEach((code) => {
        [...code].forEach((width, index) => bars.append(h('i', {
            class: `${index % 2 === 0 ? 'bar' : 'space'} ${width === 'w' ? 'wide' : ''}`,
        })));
        bars.append(h('i', { class: 'space' }));
    });
    return h('div', { class: 'barcode-label' }, bars, h('small', {}, `Intake #${digits}`));
}

// Until a doctor stamps it, the report is an AI draft. The stamp changes nothing in it.
function reviewBar(detail, context) {
    if (detail.reviewed || !['done', 'report_failed'].includes(detail.status)) return null;
    return h('div', { class: 'banner no-print' },
        'Not yet reviewed by a doctor. Read the report and the patient’s own answers, then mark it reviewed. ',
        h('button', {
            type: 'button',
            onclick: async () => {
                const done = await act(() => api(`/api/diagnofast/intakes/${detail.id}/review`, { method: 'POST' }), context, 'Marked as reviewed');
                if (done) context?.refresh?.();
            },
        }, 'Mark as reviewed'));
}

const PROBLEM_FIELD = { review_of_systems: 'Review of systems', suggested_investigations: 'Investigations to consider' };

// What the code's checks found in the AI's report. Nothing in the report was changed because of them.
function problemList(detail) {
    const report = detail.report;
    if (!report || !detail.report_problems?.length) return null;
    const label = (item) => {
        if (item.field === 'review_of_systems') {
            const entry = report.review_of_systems?.[item.index];
            return entry ? `${entry.system} / ${entry.parameter}` : `row ${item.index + 1}`;
        }
        return report.suggested_investigations?.[item.index] || `item ${item.index + 1}`;
    };
    return h('div', { class: 'banner danger' },
        h('strong', {}, 'Checks flagged parts of this AI draft. Verify them with the patient:'),
        h('ul', {}, detail.report_problems.map((item) => h('li', {}, `${PROBLEM_FIELD[item.field] || item.field}, ${label(item)}: ${item.problem}`))));
}

// Possible medicine and allergy conflicts across doctors, for staff only. Each is "check", never advice.
function conflictsPanel(found) {
    return h('section', { class: 'no-print conflicts-panel' },
        h('h3', {}, 'Medicine checks (staff only)'),
        found.flags.length
            ? h('ul', {}, found.flags.map((flag) => h('li', {}, h('strong', {}, flag.message),
                h('ul', {}, flag.records.map((entry) => h('li', { class: 'muted' }, `${entry.text} · ${entry.where}${entry.doctor ? ` · ${entry.doctor}` : ''}`))))))
            : h('p', { class: 'muted' }, `No possible conflicts in ${found.checked.medicines} confirmed medicine${found.checked.medicines === 1 ? '' : 's'} and ${found.checked.allergies} allerg${found.checked.allergies === 1 ? 'y' : 'ies'}.`),
        h('p', { class: 'muted' }, found.salt_check.reason));
}

// "Anything you wish had been asked?" It changes nothing in the report; it helps the questions improve.
function feedbackPanel(detail, context) {
    const done = ['done', 'report_failed'].includes(detail.status);
    const list = h('ul', {}, detail.feedback.answers.map((answer) => h('li', {}, answer.wished_asked,
        answer.good_question && h('span', { class: 'muted' }, ` · suggested: “${answer.good_question}”`))));
    const box = form(
        [
            { name: 'wished_asked', label: detail.feedback.question, type: 'textarea', required: true, maxlength: 1000 },
            { name: 'good_question', label: 'A question you would have asked (optional)', maxlength: 300 },
        ],
        'Save feedback',
        async (values, element) => {
            const saved = await act(() => api(`/api/diagnofast/intakes/${detail.id}/feedback`, {
                method: 'POST', body: { wished_asked: values.wished_asked, good_question: values.good_question || null },
            }), context, 'Thank you. This helps the questions improve.');
            if (!saved) return;
            list.append(h('li', {}, values.wished_asked, values.good_question && h('span', { class: 'muted' }, ` · suggested: “${values.good_question}”`)));
            element.reset();
        },
    );
    return h('section', { class: 'no-print feedback-panel' }, h('h3', {}, 'Your feedback on the questions'), list,
        done ? box : h('p', { class: 'muted' }, 'Feedback opens when the interview is finished.'));
}

export function reportView(detail, context) {
    const pack = h('div', { class: 'no-print' });
    const { report, patient, records } = detail;
    const age = patient.age === null || patient.age === undefined ? 'Age not stated' : `${patient.age} Y`;
    const history = [];
    if (report) {
        history.push(['Past history', report.past_history || 'Not stated', 'Interview / see provenance']);
        (report.current_medicines || []).forEach((item) => history.push(['Current medicine', item, 'Patient reported']));
        (report.allergies || []).forEach((item) => history.push(['Allergy', item, 'Patient reported · verify']));
    }
    if (records) {
        const source = 'ABHA record';
        (records.conditions || []).forEach((item) => history.push(['Condition', item, source]));
        (records.prescriptions || []).forEach((item) => history.push(['Prescription record', item, source]));
        (records.lab_reports || []).forEach((item) => history.push(['Past result', item, source]));
    }
    return h('article', { class: 'sheet requisition' },
        h('header', { class: 'requisition-header' },
            h('div', {}, h('p', { class: 'requisition-brand' }, 'CURAI / DIAGNOFAST'),
                h('h2', {}, 'Clinical intake requisition'),
                h('p', { class: 'muted' }, 'Pre-consultation history · For physician review')),
            barcode(detail.id)),
        h('div', { class: 'requisition-demographics' },
            row('Patient', patient.name), row('Age / sex', `${age} / ${patient.sex || 'Not stated'}`),
            row('UHID / chart ID', patient.record_id || 'Not linked'), row('Department', detail.form_title),
            row('Visit', detail.created_at ? when(detail.created_at) : 'Not recorded'),
            row('Status', detail.reviewed ? `Reviewed by ${detail.reviewed.by}, ${when(detail.reviewed.at)}`
                : report ? 'Intake complete · not yet reviewed by a doctor' : STATUS_TEXT[detail.status] || detail.status),
            records && patient.abha_id && row('ABHA ID', patient.abha_id)),
        detail.urgent.length > 0 && h('div', { class: 'banner danger requisition-alert' },
            h('strong', {}, 'URGENT SYMPTOMS — PATIENT DIRECTED TO RECEPTION: '), detail.urgent.join(', ')),
        detail.status === 'report_failed' && h('div', { class: 'banner no-print' }, "The summary couldn't be written. Review the original answers below. ",
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    const done = await act(() => api(`/api/diagnofast/intakes/${detail.id}/report/retry`, { method: 'POST' }), context, 'Writing the summary again');
                    if (done) context?.refresh?.();
                },
            }, 'Try writing the summary again')),
        !report && detail.status !== 'report_failed' && h('p', { class: 'muted' }, STATUS_TEXT[detail.status] || detail.status),
        reviewBar(detail, context),
        problemList(detail),
        report && [
            h('p', { class: 'requisition-disclaimer' }, 'AI draft from reported history. Confirm with the patient. This is not a diagnosis, laboratory result or test order.'),
            row('Chief complaint', report.chief_complaint),
            row('History of present illness', report.present_illness),
            report.highlights?.length > 0 && row('Highlights', report.highlights.join(' • ')),
            h('h3', {}, 'Systematic review of systems'),
            report.review_of_systems?.length
                ? reportTable(['System / parameter', 'Observed or reported finding', 'Flag', 'Reference / context'],
                    report.review_of_systems.map((item) => [
                        h('span', {}, h('strong', {}, item.system), h('br'), item.parameter), item.finding,
                        h('span', { class: `ros-flag ${['H*', 'L*', 'CRITICAL'].includes(item.flag) ? 'flag-alert' : ''}` },
                            item.flag === 'NOT_ASSESSED' ? 'Not assessed' : item.flag), item.norm,
                    ]))
                : h('p', {}, 'Structured review not available. See the original form answers.'),
            h('p', { class: 'requisition-legend' }, 'H*: above / L*: below a supplied measurement range. NORMAL: explicitly reported negative or normal finding. Not assessed: no objective classification. Unasked symptoms are not normal findings.'),
        ],
        h('h3', {}, 'Past history, medicines & ABHA records'),
        history.length ? reportTable(['Record type', 'Details / date if known', 'Source'], history)
            : h('p', {}, 'No history available. ABHA records were not included.'),
        report?.gaps?.length > 0 && row('Unclear or missing — verify', report.gaps.join(' • ')),
        report && 'suggested_investigations' in report && [h('h3', {}, 'Suggested initial investigations · Physician review only'),
            h('p', { class: 'requisition-legend' }, 'Suggestions are not orders. The physician decides whether any investigation is indicated.'),
            report.suggested_investigations?.length ? h('div', { class: 'investigation-checklist' },
                report.suggested_investigations.map((item) => h('label', {}, h('input', { type: 'checkbox' }), item)))
                : h('p', {}, 'No investigations suggested from the available history.')],
        h('section', { class: 'physician-workspace' }, h('h3', {}, "Examining physician’s workspace"),
            h('p', {}, 'Provisional / differential diagnosis: ', h('span', { class: 'writing-line' })),
            h('p', { class: 'plan-line' }, 'Prescription / plan: ', h('span', { class: 'writing-line' })),
            h('div', { class: 'signoff' }, h('p', {}, 'Doctor signature: ____________________'), h('p', {}, 'Date: ____________________'))),
        detail.graphs && graphsPanel(detail.graphs),
        detail.feedback && feedbackPanel(detail, context),
        detail.conflicts && conflictsPanel(detail.conflicts),
        h('details', { class: 'no-print requisition-original', open: !report },
            h('summary', {}, 'Original form answers & patient transcript'),
            h('h3', {}, `${detail.form_title} form`),
            detail.answers.map((answer) => row(answer.label, answer.value)),
            h('h3', {}, "The patient’s own words"),
            detail.transcript.map((turn, index) => h('div', { class: 'medicine-card' },
                h('p', {}, turn.question), h('strong', { lang: /[\u0900-\u097F]/.test(turn.answer) ? 'hi' : null }, turn.answer),
                turn.english && h('p', { class: 'translation-line' }, h('span', { class: 'status' }, turn.english_label), ' ', turn.english),
                turn.has_audio && h('audio', { class: 'no-print', controls: true, preload: 'none', src: `/api/diagnofast/intakes/${detail.id}/audio/${index}` })))),
        h('p', { class: 'requisition-legend' }, `DiagnoFast · Intake #${detail.id} · Clinical decisions and sign-off remain with the examining physician.`),
        h('div', { class: 'row no-print' },
            h('a', { class: 'button quiet', href: '#/diagnofast' }, 'Back to the queue'),
            h('button', { type: 'button', class: 'quiet', onclick: () => window.print() }, 'Print or save as PDF'),
            patient.record_id && h('button', { type: 'button', class: 'quiet', onclick: async () => show(pack, await packPanel(patient.record_id, context)) }, "Open the patient's pack")),
        pack);
}

// Build a separate A4 page from whole entries. Measure at print width before printing,
// so an oversized entry is never cut in half or silently lost.
export function preparePrintReport(container, detail) {
    const old = document.querySelector('.intake-print-page');
    if (old) old.remove();
    const { report, patient, records } = detail;
    const page = h('article', { class: 'intake-print-page' });
    const content = h('div', { class: 'intake-print-content' });
    const warning = h('p', { class: 'intake-print-warning' });
    const workspace = h('div', { class: 'intake-print-workspace' },
        h('strong', {}, 'PHYSICIAN WORKSPACE'),
        h('p', {}, 'Provisional / differential diagnosis: __________________________________________'),
        h('p', {}, 'Plan: ___________________________________________________________________'),
        h('p', {}, 'Signature: ______________________________    Date: __________________'));
    page.append(content, warning, workspace);
    document.body.append(page);
    const entries = [];
    const add = (label, value) => {
        if (value !== null && value !== undefined && String(value).trim())
            entries.push(h('p', {}, h('strong', {}, `${label}: `), String(value)));
    };
    const section = (title) => entries.push(h('h3', {}, title));
    entries.push(h('div', { class: 'intake-print-header' },
        h('div', {}, h('strong', {}, 'CURAI / DIAGNOFAST'), h('h2', {}, 'Clinical intake summary'),
            h('span', {}, 'AI-generated intake summary · clinician review required')), barcode(detail.id)));
    add('Patient', patient.name);
    add('Age / sex', `${patient.age ?? 'Not stated'} / ${patient.sex || 'Not stated'}`);
    add('Specialty / visit', `${detail.form_title} / ${detail.created_at ? when(detail.created_at) : 'Not recorded'}`);
    add('Chart ID', patient.record_id || 'Not linked');
    if (records && patient.abha_id) add('ABHA ID', patient.abha_id);
    if (detail.urgent?.length) entries.push(h('p', { class: 'intake-print-urgent' },
        h('strong', {}, 'URGENT — PATIENT DIRECTED TO RECEPTION: '), detail.urgent.join(' • ')));
    if (!report) add('Summary unavailable', detail.status === 'report_failed' ? 'Report generation failed. Review original answers and transcript on screen.' : 'Interview or report is not complete. Review original answers on screen.');
    if (report) {
        section('Chief complaint & history of present illness');
        add('Chief complaint', report.chief_complaint);
        add('HPI', report.present_illness);
        (report.highlights || []).forEach((x) => add('Important', x));
        section('Clinical findings · patient reported unless otherwise stated');
        (report.review_of_systems || []).forEach((x) => add(`${x.system} / ${x.parameter}`, `${x.finding} · ${x.flag === 'NOT_ASSESSED' ? 'Not assessed' : x.flag} · ${x.norm}`));
        section('History & medicines · patient reported');
        add('Past history', report.past_history);
        (report.current_medicines || []).forEach((x) => add('Medicine', x));
        (report.allergies || []).forEach((x) => add('Allergy', x));
    }
    if (records) {
        section('ABHA records');
        for (const [key, label] of [['conditions', 'Condition'], ['prescriptions', 'Prescription record'], ['lab_reports', 'Past result']])
            (records[key] || []).forEach((x) => add(label, x));
    }
    if (report?.gaps?.length) { section('Unclear or missing · verify'); report.gaps.forEach((x) => add('Verify', x)); }
    if (report && 'suggested_investigations' in report && report.suggested_investigations.length) {
        section('Suggested investigations · for physician review only · not orders');
        report.suggested_investigations.forEach((x) => add('Consider', x));
    }
    section('Specialty form answers · patient reported');
    (detail.answers || []).filter((x) => x.value?.trim()).forEach((x) => add(x.label, x.value));
    // Reserve room for the warning even when it is not needed. Stop at the first
    // omitted entry so the printed page never implies that later content is complete.
    let omitted = false;
    for (const entry of entries) {
        content.append(entry);
        if (content.scrollHeight > content.clientHeight) {
            entry.remove();
            if (content.lastElementChild?.tagName === 'H3') content.lastElementChild.remove();
            omitted = true;
            break;
        }
    }
    warning.textContent = omitted
        ? 'INCOMPLETE PRINT SUMMARY: additional intake information did not fit. Review the full report, original form answers and transcript on screen.'
        : 'Review the original form answers and patient transcript on screen; AI summaries may contain errors or omissions.';
    const screenNotice = h('p', { class: 'intake-fit-notice no-print' }, omitted
        ? 'The A4 printout is incomplete: additional intake information does not fit. Review the complete report, original answers and transcript below.'
        : 'The A4 printout fits. Review the original answers and transcript below for any AI omissions.');
    container.querySelector('.requisition').prepend(screenNotice);
}

async function renderReport(container, id, context) {
    const load = async () => {
        const detail = await api(`/api/diagnofast/intakes/${id}`);
        if (detail.status === 'done') detail.graphs = await api(`/api/diagnofast/intakes/${id}/graph`).catch(() => null);
        if (detail.patient.record_id && context.config?.addons?.['conflicts.medicine_checks']) {
            detail.conflicts = await api(`/api/conflicts/patients/${detail.patient.record_id}`).catch(() => null);
        }
        show(container, h('h1', { class: 'no-print' }, 'DiagnoFast'), reportView(detail, context));
        preparePrintReport(container, detail);
        return detail;
    };
    const detail = await load();
    if (['waiting', 'in_progress', 'preparing_report'].includes(detail.status)) keepFresh(load);
}

function ageFrom(birthDate) {
    if (!birthDate) return undefined;
    return Math.floor((Date.now() - new Date(birthDate).getTime()) / (365.25 * 24 * 60 * 60 * 1000));
}

// One queue row: who, when, and where the interview stands, in words as well as colour.
export function queueRow(intake) {
    const urgent = intake.urgent.length > 0;
    const review = ['done', 'report_failed'].includes(intake.status) && !intake.reviewed;
    const stateTag = intake.reviewed ? h('span', { class: 'status good' }, 'Reviewed')
        : review ? h('span', { class: 'status warn' }, 'To review')
            : h('span', { class: 'status' }, STATUS_TEXT[intake.status] || intake.status);
    return h('a', { class: `queue-item${urgent ? ' urgent' : ''}`, href: `#/diagnofast/${intake.id}` },
        h('span', { class: 'q-avatar', 'aria-hidden': 'true' }, urgent ? icon('alert', 'nav-icon') : initials(intake.patient_name)),
        h('span', { class: 'q-main' },
            h('span', { class: 'q-name' }, intake.patient_name),
            h('span', { class: 'q-when' }, when(intake.created_at))),
        h('span', { class: 'q-tags' },
            urgent && h('span', { class: 'status bad' }, `Urgent: ${intake.urgent.join(', ')}`),
            intake.needs_help && h('span', { class: 'status warn' }, 'Asked for help'),
            stateTag));
}

// The queue's filters, by route name: a label and the test. Home's counts use the same tests.
export const QUEUE_FILTERS = {
    waiting: ['Waiting or answering', (item) => ['waiting', 'in_progress'].includes(item.status)],
    urgent: ['Urgent', (item) => item.urgent.length > 0],
    urgent_open: ['Urgent, not reviewed', (item) => item.urgent.length > 0 && !item.reviewed],
    review: ['To review', (item) => ['done', 'report_failed'].includes(item.status) && !item.reviewed],
    reviewed: ['Reviewed', (item) => item.reviewed],
};

export async function renderDiagnoFast(container, context) {
    clearInterval(poll);
    const { patient, route } = context;
    if (!context.isStaff) {
        show(container, h('h1', {}, 'DiagnoFast'), h('p', { class: 'empty' }, 'Your clinic sends you a link for this interview. You need no account to answer it.'));
        return;
    }
    if (route === 'bookings') {
        await renderBookings(container, context);
        return;
    }
    // A filtered queue is a route of its own, so Home can link straight to it.
    const preset = QUEUE_FILTERS[route] !== undefined ? route : '';
    if (route && !preset) {
        await renderReport(container, route, context);
        return;
    }
    const forms = await api('/api/diagnofast/forms');
    const queue = h('div', {});
    const created = h('div', { 'aria-live': 'polite' });
    let intakes = [];
    const count = h('p', { class: 'queue-count', role: 'status' });
    const search = h('input', { type: 'search', placeholder: 'Search patient name', 'aria-label': 'Search queue', oninput: () => drawQueue() });
    const filter = h('select', { 'aria-label': 'Filter queue', onchange: () => drawQueue() },
        h('option', { value: '' }, 'All interviews'),
        Object.entries(QUEUE_FILTERS).map(([value, [label]]) => h('option', { value, selected: value === preset }, label)));
    const drawQueue = () => {
        const found = intakes.filter((item) => item.patient_name.toLowerCase().includes(search.value.trim().toLowerCase()))
            .filter((item) => !filter.value || QUEUE_FILTERS[filter.value][1](item));
        count.textContent = `${found.length} of ${intakes.length} interviews · ${intakes.filter((item) => item.urgent.length).length} urgent`;
        show(queue, found.length
            ? h('div', { class: 'queue-list' }, found.map(queueRow))
            : h('div', { class: 'empty' }, h('strong', {}, intakes.length ? 'No interviews match' : 'No interviews yet'),
                intakes.length ? 'Try another name or filter.' : 'Create an interview link and the patient answers by voice while they wait.'));
    };

    const loadQueue = async () => {
        // A filtered route (from Home's counts) shows the whole queue, which is what Home counted.
        const url = patient && !preset ? `/api/diagnofast/intakes?patient_id=${patient.id}` : '/api/diagnofast/intakes';
        intakes = await api(url);
        drawQueue();
    };

    const sendLink = form(
        [
            { name: 'form_id', label: 'Doctor form', type: 'select', options: forms.map((item) => [item.id, item.title]) },
            { name: 'patient_name', label: 'Patient name', required: true, value: patient ? `${patient.first_name} ${patient.last_name}` : '', maxlength: 120 },
            { name: 'patient_age', label: 'Age', type: 'number', min: 0, max: 130, value: ageFrom(patient?.date_of_birth) },
            { name: 'patient_sex', label: 'Sex', type: 'select', value: patient?.sex, options: [['', 'Not recorded'], ['female', 'Female'], ['male', 'Male'], ['other', 'Other']] },
            { name: 'abha_id', label: 'ABHA ID (optional)', maxlength: 32 },
        ],
        'Create interview link',
        async (values, element) => {
            const made = await act(() => api('/api/diagnofast/intakes', {
                method: 'POST',
                body: { ...values, patient_sex: values.patient_sex || null, patient_id: patient?.id ?? null },
            }), context);
            if (!made) return;
            const url = new URL(made.link, window.location.href).href;
            show(created, h('div', { class: 'banner' },
                h('p', {}, 'Open this link on the waiting-room tablet. It works for this patient only, stops when the interview ends, and expires if it is not used within a day.'),
                h('a', { class: 'link-box', href: url, target: '_blank', rel: 'noopener' }, url)));
            if (!patient) element.reset();
            await loadQueue();
        },
    );

    await loadQueue();
    show(container,
        h('h1', {}, 'DiagnoFast'),
        h('p', { class: 'lede' }, 'The patient answers by voice while they wait. You get a one-page report, and urgent symptoms come to the top.'),
        h('div', { class: 'queue-layout' },
            h('section', { class: 'sheet' }, h('h2', {}, patient && !preset ? `${patient.first_name}'s interviews` : 'Patient queue'),
                h('div', { class: 'queue-toolbar' }, search, filter), count, queue),
            h('section', { class: 'sheet' }, h('h2', {}, patient ? `New link for ${patient.first_name}` : 'New patient link'),
                h('p', { class: 'muted' }, 'Start a voice interview. The patient can open the link without an account.'), sendLink, created)),
        h('p', { class: 'muted' },
            context.config?.addons?.['diagnofast.bookings'] && [h('a', { href: '#/diagnofast/bookings' }, 'OPD bookings and queue'), ' · '],
            h('a', { href: 'intake.html', target: '_blank', rel: 'noopener' }, 'Open self-service kiosk'), ' · ', h('a', { href: 'diagnofast_hiw.html' }, 'How it works')));
    keepFresh(loadQueue);
}
