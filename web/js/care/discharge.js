// DischargeCare: the ward's plan, and the checklist the patient takes home.
import { act, api, ask, badge, emptyState, form, h, listRow, plural, rowList, section, show, tabs, when } from './ui.js';
import { icon, initials } from './icons.js';
import { taskList } from './overview.js';

const BASE = '/api/addons/dischargecare';

function board(rows, open) {
    return rowList(rows.map((row) => {
        const late = row.barriers_overdue || row.tasks_overdue;
        return listRow({
            lead: row.flagged ? undefined : initials(`${row.first_name} ${row.last_name}`),
            leadIcon: row.flagged ? 'alert' : undefined,
            tone: late ? 'urgent' : row.status === 'draft' ? 'warn' : '',
            title: `${row.first_name} ${row.last_name}`,
            meta: `${when(row.discharge_date)} · to ${row.destination}${row.flagged ? ' · Flagged for attention' : ''}`,
            tags: [
                row.status === 'draft' ? h('mark', {}, 'Not approved') : badge(row.status === 'active' ? 'Approved' : row.status, row.status === 'active' ? 'good' : ''),
                row.barriers_open ? badge(row.barriers_overdue ? `${plural(row.barriers_open, 'barrier')}, ${row.barriers_overdue} past target` : plural(row.barriers_open, 'barrier'), row.barriers_overdue ? 'bad' : 'warn') : null,
                row.tasks_overdue ? badge(`${plural(row.tasks_overdue, 'task')} overdue`, 'bad') : row.tasks_open ? badge(`${plural(row.tasks_open, 'task')} open`) : null,
                row.results_pending ? badge(`${plural(row.results_pending, 'result')} to come`) : null,
            ],
            onclick: () => open(row.id),
            attrs: { 'aria-label': `Open the discharge for ${row.first_name} ${row.last_name}` },
        });
    }), emptyState('No open discharges', 'A discharge you start appears here until it is closed.'));
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

    const blockers = episode.close_blockers || [];
    const openBarriers = episode.barriers.filter((row) => row.status === 'open');
    const openTasks = episode.tasks.filter((item) => !['done', 'held'].includes(item.status));
    const waitingResults = episode.pending_results.filter((row) => row.status === 'pending');
    const readiness = h('section', { class: 'readiness', 'aria-label': 'Readiness' },
        h('div', { class: `readiness-line ${draft ? 'warn' : blockers.length ? 'bad' : 'good'}` },
            icon(draft ? 'clock' : blockers.length ? 'alert' : 'check', 'button-icon'),
            h('strong', {}, draft ? 'Not approved. The family sees nothing yet.' : episode.status === 'closed' ? 'Closed' : blockers.length ? `${plural(blockers.length, 'thing')} still in the way of closing` : 'Nothing in the way of closing')),
        blockers.length ? h('ul', { class: 'blocker-list' }, blockers.map((item) => h('li', {}, item))) : null,
        h('dl', { class: 'readiness-counts' },
            h('div', {}, h('dt', {}, 'Barriers open'), h('dd', {}, String(openBarriers.length))),
            h('div', {}, h('dt', {}, 'Tasks open'), h('dd', {}, String(openTasks.length))),
            h('div', {}, h('dt', {}, 'Results to come'), h('dd', {}, String(waitingResults.length))),
            h('div', {}, h('dt', {}, 'Instructions'), h('dd', {}, String(episode.instructions.length)))));

    const primary = draft ? h('button', {
        type: 'button',
        class: 'primary-lg',
        onclick: async () => {
            const done = await post('approve', undefined, 'Discharge approved');
            if (done) reload();
        },
    }, 'Approve discharge plan') : episode.status === 'active'
        // The server refuses anyone else too. Saying so here saves a click that can only fail.
        ? (responsible ? h('button', {
            type: 'button',
            class: 'primary-lg',
            onclick: async () => {
                const needsReason = episode.close_blockers?.length;
                const reason = needsReason ? await ask('Work is outstanding. Why close anyway?') : '';
                if (needsReason && !reason) return;
                const done = await post('close', { exception_reason: reason || '' }, 'Discharge closed');
                if (done) context.refresh();
            },
        }, 'Close discharge') : h('p', { class: 'muted' }, 'Only the responsible clinician can close this discharge.'))
        : h('button', {
            type: 'button',
            class: 'quiet',
            onclick: async () => {
                const reason = await ask('Why does this discharge need reopening?');
                if (!reason) return;
                const done = await post('reopen', { reason }, 'Discharge reopened');
                if (done) reload();
            },
        }, 'Reopen this discharge');

    const staffView = h('div', { class: 'tab-panel', role: 'tabpanel', 'aria-label': 'Readiness' },
        readiness,
        ...section('Barriers', openBarriers.length || episode.barriers.length ? rowList(episode.barriers.map((row) => listRow({
            leadIcon: row.status === 'open' ? 'alert' : 'check',
            tone: row.status === 'open' ? (row.target_date && row.target_date < new Date().toISOString().slice(0, 10) ? 'urgent' : 'warn') : 'good',
            title: row.description,
            meta: [row.owner ? `With ${row.owner}` : 'Nobody named', row.target_date ? `Sorted by ${when(row.target_date)}` : 'No date'].join(' · '),
            tags: [row.status === 'open' ? h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    await act(() => api(`${BASE}/barriers/${row.id}/resolve`, { method: 'POST' }), context);
                    reload();
                },
            }, 'Resolved') : badge('Resolved', 'good')],
        })), null) : emptyState('No barriers recorded', 'Anything in the way of going home goes here, with who is on it.'),
        barrier ? h('details', { class: 'quiet-details' }, h('summary', {}, 'Add a barrier'), barrier) : null),
        ...section('Tasks', h('div', {}, taskList(episode.tasks.filter((item) => item.status !== 'held'), context, reload)),
            episode.tasks.some((item) => item.status === 'held') ? h('p', { class: 'muted' }, `${episode.tasks.filter((item) => item.status === 'held').length} tasks start when you approve.`) : null,
            task ? h('details', { class: 'quiet-details' }, h('summary', {}, 'Add a task'), task) : null),
        ...section('Results still to come', episode.pending_results.length ? rowList(episode.pending_results.map((row) => listRow({
            leadIcon: row.status === 'pending' ? 'clock' : 'check',
            tone: row.status === 'pending' ? '' : 'good',
            title: row.test_name,
            meta: row.status === 'pending' ? `Expected ${row.expected_by ? when(row.expected_by) : 'date not set'}` : `Final: ${row.result_note}`,
            tags: [row.status === 'pending' ? h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    const note = await ask('Result summary');
                    if (!note) return;
                    await act(() => api(`${BASE}/pending-results/${row.id}/finalise`, { method: 'POST', body: { result_note: note } }), context);
                    reload();
                },
            }, 'Mark final') : badge('Final', 'good')],
        })), null) : emptyState('None pending', 'Results expected after the patient leaves go here.'),
        pending ? h('details', { class: 'quiet-details' }, h('summary', {}, 'Add a result still to come'), pending) : null),
        ...section('Summary', summary),
        ...section('Instructions', episode.instructions.length
            ? h('div', { class: 'instruction-list' }, episode.instructions.map((row) => h('div', { class: 'instruction', lang: row.language?.slice(0, 2) }, h('strong', {}, row.topic), h('p', {}, row.text))))
            : emptyState('No instructions yet', 'Add at least one instruction before approving.'),
        instruction ? h('details', { class: 'quiet-details', open: !episode.instructions.length }, h('summary', {}, 'Add an instruction'), instruction) : null),
        episode.status === 'closed' ? h('p', { class: 'muted' }, `Closed ${when(episode.closed_at)}.${episode.close_exception ? ` Closed with work outstanding: ${episode.close_exception}` : ''}`) : null);

    const familyBox = h('div', { class: 'tab-panel', role: 'tabpanel', 'aria-label': 'What the family sees' });
    const body = h('div', {}, staffView);
    let view = 'staff';
    const pick = async (key) => {
        view = key;
        show(switcher, tabs([{ key: 'staff', label: 'Readiness' }, { key: 'family', label: 'What the family sees' }], view, pick, 'Discharge views'));
        if (key === 'staff') { show(body, staffView); return; }
        show(body, familyBox);
        if (draft) {
            show(familyBox, emptyState('Nothing to show the family yet', 'The family checklist appears once you approve the plan.'));
            return;
        }
        const data = await api(`${BASE}/episodes/${episode.id}/checklist`).catch(() => null);
        show(familyBox, data ? [h('p', { class: 'muted' }, 'A preview. Only the family can tick their steps.'), checklist(data, context, () => pick('family'), true)]
            : emptyState('The checklist could not load', 'Try again in a moment.'));
    };
    const switcher = h('div', {});

    show(area, h('section', { class: 'sheet episode', 'aria-label': 'Discharge plan' },
        h('div', { class: 'section-head' },
            h('h2', {}, `Discharge to ${episode.destination}`),
            h('div', { class: 'row' },
                draft ? h('mark', {}, 'Not approved') : badge(episode.status === 'active' ? 'Approved' : 'Closed', episode.status === 'active' ? 'good' : ''),
                h('span', { class: 'muted' }, when(episode.discharge_date)))),
        switcher,
        body,
        h('div', { class: 'action-bar' },
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    await act(() => api(url, { method: 'PATCH', body: { flagged: !episode.flagged } }), context, 'Updated');
                    reload();
                },
            }, episode.flagged ? 'Remove flag' : 'Flag for attention'),
            h('span', { class: 'action-note' }),
            primary)));
    pick(view);
}

// The family's view. Plain words, the phone number first, one large button for each step.
function checklist(data, context, onChange, preview = false) {
    const setStatus = async (step, status, note = '') => {
        await act(() => api(`/api/tasks/${step.id}/status`, { method: 'POST', body: { status, note } }), context);
        onChange();
    };
    const steps = data.tasks.map((step) => {
        const done = step.status === 'done';
        const stuck = step.status === 'blocked' || step.status === 'missed';
        return h('li', { class: `step ${done ? 'done' : ''}` },
            h('div', {},
                h('strong', {}, done ? icon('check', 'done-tick') : null, step.title),
                step.added_after_approval ? [' ', badge('New', 'bad')] : null,
                step.detail ? h('p', {}, step.detail) : null,
                step.due_at ? h('p', { class: 'muted' }, `${step.overdue && !done ? 'This was due by' : 'Do this by'} ${when(step.due_at)}`) : null,
                stuck ? h('p', {}, h('mark', {}, 'You told us you could not do this. Your care team has been told.')) : null),
            preview ? null : done
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
    return h('div', { class: 'family-checklist', lang: 'en' },
        h('div', { class: 'who-to-call' },
            h('h2', {}, icon('phone', 'button-icon'), 'Who to call'),
            h('p', { class: 'call-line' }, data.emergency_contact),
            h('p', {}, 'Call them if you are worried. In an emergency, call 112.')),
        h('div', { class: 'sheet' },
            h('h2', {}, 'Your going-home plan'),
            h('p', {}, `Going home on ${when(data.discharge_date)}, to: ${data.destination}.`),
            data.approved_by ? h('p', { class: 'muted' }, `${data.approved_by} checked this plan on ${when(data.approved_at)}.`) : null),
        ...section('What to do', steps.length ? [
            h('p', { class: 'muted' }, `${data.tasks.filter((step) => step.status === 'done').length} of ${data.tasks.length} done`),
            h('ul', { class: 'steps' }, steps)] : h('p', { class: 'empty' }, 'Nothing to do right now.')),
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
    if (start) start.querySelector('button[type="submit"]').classList.add('quiet');
    show(container,
        h('h1', {}, 'DischargeCare'),
        h('p', { class: 'lede' }, 'Turns a discharge plan into tracked tasks. It coordinates the work and leaves the decision to discharge with you.'),
        start ? h('section', { class: 'sheet start-panel' }, h('h2', {}, 'Start a discharge'), start) : null,
        area,
        h('div', { class: 'section-head' }, h('h2', {}, 'Discharge board'), h('p', { class: 'muted' }, `${plural(rows.length, 'open discharge')}`)),
        board(rows, open),
        ...(closed.length ? section(`Closed discharges for ${patient.first_name}`, rowList(closed.map((row) => listRow({
            leadIcon: 'check',
            tone: 'good',
            title: `To ${row.destination}`,
            meta: `Discharged ${when(row.discharge_date)} · Closed ${when(row.closed_at)}`,
            onclick: () => open(row.id),
        })), null)) : []),
    );
    return undefined;
}
