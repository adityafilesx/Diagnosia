// DischargeCare: the ward's plan, and the checklist the patient takes home.
import { act, api, ask, badge, form, h, section, table, when, show } from './ui.js';
import { taskList } from './overview.js';

const BASE = '/api/addons/dischargecare';

function board(rows, open) {
    return table(
        [
            { label: 'Patient', cell: (row) => [row.flagged ? '⚑ ' : '', `${row.first_name} ${row.last_name}`] },
            { label: 'Discharge', cell: (row) => when(row.discharge_date) },
            { label: 'To', cell: (row) => row.destination },
            { label: 'Barriers', number: true, cell: (row) => (row.barriers_overdue ? badge(`${row.barriers_open}, ${row.barriers_overdue} past target`, 'bad') : row.barriers_open) },
            { label: 'Open tasks', number: true, cell: (row) => row.tasks_open },
            { label: 'Overdue', number: true, cell: (row) => (row.tasks_overdue ? badge(String(row.tasks_overdue), 'bad') : 0) },
            { label: 'Results due', number: true, cell: (row) => row.results_pending },
            { label: 'Status', cell: (row) => (row.status === 'draft' ? h('mark', {}, 'Not approved') : badge(row.status)) },
            { label: '', cell: (row) => h('button', { type: 'button', class: 'quiet', onclick: () => open(row.id) }, 'Open') },
        ],
        rows,
        'No open discharges.',
    );
}

function episodeEditor(area, episode, context, open) {
    const url = `${BASE}/episodes/${episode.id}`;
    const reload = () => open(episode.id);
    const post = (path, body, message) => act(() => api(`${url}/${path}`, { method: 'POST', body }), context, message);
    const draft = episode.status === 'draft';
    const responsible = episode.responsible_clinician_id === context.me.id;
    const live = episode.status !== 'closed';

    const summary = draft ? form(
        [
            { name: 'problems', label: 'Problem list', type: 'textarea', value: episode.problems },
            { name: 'procedures', label: 'Procedures', type: 'textarea', value: episode.procedures },
            { name: 'emergency_contact', label: 'Who the patient calls if worried', value: episode.emergency_contact },
        ],
        'Save summary',
        async (values) => {
            await act(() => api(url, { method: 'PATCH', body: values }), context, 'Saved');
            reload();
        },
    ) : h('div', {}, h('p', {}, episode.problems), h('p', {}, episode.procedures), h('p', { class: 'muted' }, `Patient contact: ${episode.emergency_contact}`));

    const instruction = draft ? form(
        [
            { name: 'topic', label: 'Topic', required: true },
            { name: 'text', label: 'Instruction, as approved by you', type: 'textarea', required: true },
            { name: 'language', label: 'Language', type: 'select', options: [['en-IN', 'English'], ['hi-IN', 'Hindi']] },
        ],
        'Add instruction',
        async (values) => { await post('instructions', values, 'Added'); reload(); },
    ) : null;
    const barrier = live ? form(
        [
            { name: 'description', label: 'What is in the way', required: true },
            { name: 'owner', label: 'Who is on it' },
            { name: 'target_date', label: 'Sorted by', type: 'date' },
        ],
        'Add barrier',
        async (values) => { await post('barriers', values, 'Added'); reload(); },
        { inline: true },
    ) : null;
    const pending = live ? form(
        [
            { name: 'test_name', label: 'Test', required: true },
            { name: 'expected_by', label: 'Expected by', type: 'date' },
        ],
        'Add pending result',
        async (values) => { await post('pending-results', values, 'Added'); reload(); },
        { inline: true },
    ) : null;
    const task = live ? form(
        [
            { name: 'title', label: 'Task', required: true },
            { name: 'audience', label: 'For', type: 'select', options: [['patient', 'Patient or caregiver'], ['care_team', 'Care team']] },
            { name: 'priority', label: 'Priority', type: 'select', options: ['routine', 'high'] },
            { name: 'due_at', label: 'Due', type: 'datetime-local' },
            { name: 'required', label: 'Needed before closing', type: 'checkbox', value: true },
        ],
        'Add task',
        async (values) => {
            if (values.due_at) values.due_at = new Date(values.due_at).toISOString();
            await post('tasks', values, 'Added');
            reload();
        },
        { inline: true },
    ) : null;

    show(area, h('div', { class: 'sheet' },
        h('div', { class: 'row' },
            h('h2', { style: 'margin:0' }, `Discharge to ${episode.destination}`),
            draft ? h('mark', {}, 'Not approved. The patient sees nothing yet.') : badge(episode.status)),
        h('p', { class: 'muted' }, `${when(episode.discharge_date)}`),
        h('div', { class: 'row', style: 'margin:8px 0' },
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    await act(() => api(url, { method: 'PATCH', body: { flagged: !episode.flagged } }), context, 'Updated');
                    reload();
                },
            }, episode.flagged ? 'Remove flag' : 'Flag for attention')),
        ...section('Summary', summary),
        ...section('Instructions', instruction, table(
            [{ label: 'Topic', cell: (row) => row.topic }, { label: 'Text', cell: (row) => row.text }],
            episode.instructions,
            'Add at least one instruction before approving.',
        )),
        ...section('Barriers', barrier, table(
            [
                { label: 'Barrier', cell: (row) => row.description },
                { label: 'Owner', cell: (row) => row.owner },
                { label: 'Sorted by', cell: (row) => (row.target_date ? when(row.target_date) : 'No date') },
                {
                    label: '',
                    cell: (row) => (row.status === 'open' ? h('button', {
                        type: 'button',
                        class: 'quiet',
                        onclick: async () => {
                            await act(() => api(`${BASE}/barriers/${row.id}/resolve`, { method: 'POST' }), context);
                            reload();
                        },
                    }, 'Resolved') : badge('resolved', 'good')),
                },
            ],
            episode.barriers,
            'No barriers recorded.',
        )),
        ...section('Results still to come', pending, table(
            [
                { label: 'Test', cell: (row) => row.test_name },
                { label: 'Expected', cell: (row) => when(row.expected_by) },
                {
                    label: 'Status',
                    cell: (row) => (row.status === 'pending' ? h('button', {
                        type: 'button',
                        class: 'quiet',
                        onclick: async () => {
                            const note = await ask('Result summary');
                            if (!note) return;
                            await act(() => api(`${BASE}/pending-results/${row.id}/finalise`, { method: 'POST', body: { result_note: note } }), context);
                            reload();
                        },
                    }, 'Mark final') : `Final: ${row.result_note}`),
                },
            ],
            episode.pending_results,
            'None pending.',
        )),
        ...section('Tasks', task, h('div', { style: 'margin-top:8px' }, taskList(episode.tasks.filter((item) => item.status !== 'held'), context, reload)),
            episode.tasks.some((item) => item.status === 'held') ? h('p', { class: 'muted' }, `${episode.tasks.filter((item) => item.status === 'held').length} tasks start when you approve.`) : null),
        draft ? h('button', {
            type: 'button',
            style: 'margin-top:16px',
            onclick: async () => {
                const done = await post('approve', undefined, 'Discharge approved');
                if (done) reload();
            },
        }, 'Approve discharge plan') : null,
        episode.status === 'active' ? h('div', { class: 'sheet', style: 'margin-top:16px' },
            (episode.close_blockers || []).map((item) => h('div', { class: 'banner' }, item)),
            // The server refuses anyone else too. Saying so here saves a click that can only fail.
            responsible ? h('button', {
                type: 'button',
                onclick: async () => {
                    const needsReason = episode.close_blockers?.length;
                    const reason = needsReason ? await ask('Work is outstanding. Why close anyway?') : '';
                    if (needsReason && !reason) return;
                    const done = await post('close', { exception_reason: reason || '' }, 'Discharge closed');
                    if (done) context.refresh();
                },
            }, 'Close discharge') : h('p', { class: 'muted' }, 'Only the responsible clinician can close this discharge.')) : null,
        episode.status === 'closed' ? h('div', { class: 'sheet', style: 'margin-top:16px' },
            h('p', {}, `Closed ${when(episode.closed_at)}.${episode.close_exception ? ` Closed with work outstanding: ${episode.close_exception}` : ''}`),
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    const reason = await ask('Why does this discharge need reopening?');
                    if (!reason) return;
                    const done = await post('reopen', { reason }, 'Discharge reopened');
                    if (done) reload();
                },
            }, 'Reopen this discharge')) : null));
}

// The family's view. Plain words, the phone number first, one large button for each step.
function checklist(data, context, onChange) {
    const setStatus = async (step, status, note = '') => {
        await act(() => api(`/api/tasks/${step.id}/status`, { method: 'POST', body: { status, note } }), context);
        onChange();
    };
    const steps = data.tasks.map((step) => {
        const done = step.status === 'done';
        const stuck = step.status === 'blocked' || step.status === 'missed';
        return h('li', { class: `step ${done ? 'done' : ''}` },
            h('div', {},
                h('strong', {}, step.title),
                step.added_after_approval ? [' ', badge('New', 'bad')] : null,
                step.detail ? h('p', {}, step.detail) : null,
                step.due_at ? h('p', { class: 'muted' }, `${step.overdue && !done ? 'This was due by' : 'Do this by'} ${when(step.due_at)}`) : null,
                stuck ? h('p', {}, h('mark', {}, 'You told us you could not do this. Your care team has been told.')) : null),
            done
                ? h('div', { class: 'step-actions' }, h('span', { class: 'status good' }, 'Done'), h('button', { type: 'button', class: 'link-button', onclick: () => setStatus(step, 'open') }, 'Not done yet'))
                : h('div', { class: 'step-actions' },
                    h('button', { type: 'button', class: 'big-done', onclick: () => setStatus(step, 'done') }, 'Done'),
                    stuck ? null : h('button', {
                        type: 'button',
                        class: 'link-button',
                        onclick: async () => {
                            const why = await ask('What stopped you? Your care team will see this.');
                            if (why) setStatus(step, 'blocked', why);
                        },
                    }, "I couldn't do this")));
    });
    const waiting = data.pending_results.filter((row) => row.status !== 'final');
    return h('div', { class: 'family-checklist' },
        h('div', { class: 'banner danger who-to-call' },
            h('h2', {}, 'Who to call'),
            h('p', { class: 'call-line' }, data.emergency_contact),
            h('p', {}, 'Call them if you are worried. In an emergency, call 112.')),
        h('div', { class: 'sheet' },
            h('h2', {}, 'Your going-home plan'),
            h('p', {}, `Going home on ${when(data.discharge_date)}, to: ${data.destination}.`),
            data.approved_by ? h('p', { class: 'muted' }, `${data.approved_by} checked this plan on ${when(data.approved_at)}.`) : null),
        ...section('What to do', steps.length ? h('ul', { class: 'steps' }, steps) : h('p', { class: 'empty' }, 'Nothing to do right now.')),
        ...section('Your instructions', data.instructions.length
            ? data.instructions.map((item) => h('div', { class: 'sheet', lang: item.language.slice(0, 2) }, h('h3', {}, item.topic), h('p', {}, item.text)))
            : h('p', { class: 'empty' }, 'No instructions were written.')),
        data.pending_results.length ? h('div', {}, ...section('Test results still to come',
            h('ul', {}, data.pending_results.map((row) => h('li', {},
                h('strong', {}, row.test_name), ': ',
                row.status === 'final' ? 'Back. Your care team has it.' : `Not back yet${row.expected_by ? `. Expected by ${when(row.expected_by)}` : ''}.`))),
            waiting.length ? h('p', { class: 'muted' }, 'Your care team will tell you when these are back. You do not need to do anything.') : null)) : null);
}

export async function renderDischarge(container, context) {
    const { patient, isClinician, isStaff } = context;
    const area = h('div', {});
    const open = async (id) => {
        const episode = await api(`${BASE}/episodes/${id}`);
        episodeEditor(area, episode, context, open);
        area.scrollIntoView({ block: 'start' });
    };

    if (!isStaff) {
        if (!patient) {
            show(container, h('h1', {}, 'DischargeCare'), h('p', { class: 'empty' }, 'Open your record first.'));
            return undefined;
        }
        const episodes = await api(`${BASE}/patients/${patient.id}/episodes`);
        const latest = episodes[0];
        const loadChecklist = async () => {
            show(area, checklist(await api(`${BASE}/episodes/${latest.id}/checklist`), context, loadChecklist));
        };
        show(container, h('h1', {}, 'Going home'), latest ? area : h('p', { class: 'empty' }, 'Your checklist will appear here once your doctor approves your discharge.'));
        if (latest) await loadChecklist();
        return undefined;
    }

    const rows = await api(`${BASE}/board`);
    // The board holds open discharges only. Closed ones for the open patient are listed below it,
    // so a colleague can look one over and reopen it.
    const closed = isClinician ? (await api(`${BASE}/patients/${patient.id}/episodes`)).filter((item) => item.status === 'closed') : [];
    const start = isClinician ? form(
        [
            { name: 'discharge_date', label: 'Discharge date', type: 'date', required: true },
            { name: 'destination', label: 'Going to', required: true },
        ],
        `Start a discharge for ${patient.first_name}`,
        async (values) => {
            const made = await act(() => api(`${BASE}/episodes`, { method: 'POST', body: { ...values, patient_id: patient.id } }), context, 'Discharge started');
            if (made) open(made.id);
        },
        { inline: true },
    ) : null;
    show(container,
        h('h1', {}, 'DischargeCare'),
        h('p', { class: 'lede' }, 'Turns a discharge plan into tracked tasks. It coordinates the work and leaves the decision to discharge with you.'),
        start,
        area,
        ...section('Discharge board', board(rows, open)),
        ...(closed.length ? section(`Closed discharges for ${patient.first_name}`, table(
            [
                { label: 'Discharge', cell: (row) => when(row.discharge_date) },
                { label: 'To', cell: (row) => row.destination },
                { label: 'Closed', cell: (row) => when(row.closed_at) },
                { label: '', cell: (row) => h('button', { type: 'button', class: 'quiet', onclick: () => open(row.id) }, 'Open') },
            ],
            closed,
        )) : []),
    );
    return undefined;
}
