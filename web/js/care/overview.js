// The shared record: patient choice, consent, care team, timeline, documents, tasks and inbox.
import { act, api, ask, badge, emptyState, form, h, listRow, provenance, rowList, when, show } from './ui.js';
import { icon, initials } from './icons.js';
import { canUse } from './catalogue.js';
import { visitStrip } from './home.js';
import { packPanel } from './pack.js';

export function needPatient(container, message = 'Choose a patient from the bar above, or go to Home.') {
    show(container, h('h1', {}, 'Open a patient first'), h('p', { class: 'empty' }, message, ' ', h('a', { href: '#/home' }, 'Go to Home')));
}

function startScreen(container, context) {
    const { me } = context;
    const joinForm = form(
        [{ name: 'code', label: 'Share code', required: true }],
        'Use this code',
        async ({ code }) => {
            const joined = await act(() => api('/api/patients/join', { method: 'POST', body: { code } }), context, 'Added');
            if (joined) {
                await context.reloadPatients();
                await context.openPatient(joined.patient_id);
            }
        },
    );
    const details = [
        { name: 'first_name', label: 'First name', required: true },
        { name: 'last_name', label: 'Last name', required: true },
        { name: 'date_of_birth', label: 'Date of birth', type: 'date' },
        { name: 'sex', label: 'Sex', type: 'select', options: [['unknown', 'Not recorded'], ['female', 'Female'], ['male', 'Male'], ['other', 'Other']], value: 'unknown' },
        { name: 'phone', label: 'Phone' },
        { name: 'preferred_language', label: 'Language', type: 'select', options: [['en-IN', 'English'], ['hi-IN', 'Hindi']] },
    ];
    const newRecord = form(details, me.role === 'doctor' ? 'Add patient' : 'Create my record', async (values) => {
        const url = me.role === 'doctor' ? '/api/patients' : '/api/patients/me';
        const created = await act(() => api(url, { method: 'POST', body: values }), context, 'Record created');
        if (created) {
            await context.reloadPatients();
            await context.openPatient(created.id);
        }
    });
    show(container,
        h('h1', {}, me.role === 'doctor' ? 'Open a patient' : 'Your health record'),
        h('p', { class: 'lede' }, me.role === 'doctor'
            ? 'Choose a patient from the bar above, or add one here. You only see patients who are on your list or have shared their record with you.'
            : 'Create your record, or use the code your clinic gave you.'),
        h('div', { class: 'columns' },
            h('div', { class: 'sheet' }, h('h2', {}, me.role === 'doctor' ? 'Add a patient' : 'Create my record'), newRecord),
            h('div', { class: 'sheet' }, h('h2', {}, 'I have a code'), joinForm)),
    );
}

async function careTeamPanel(context) {
    const { patient, refresh, me } = context;
    const team = await api(`/api/patients/${patient.id}/care-team`);
    const output = h('p', { class: 'muted' });
    const issue = (purpose, scope) => async () => {
        const made = await act(() => api(`/api/patients/${patient.id}/share-codes`, { method: 'POST', body: { purpose, scope } }), context);
        if (made) {
            show(output, 'Share this code once. It works for 24 hours: ', h('strong', {}, made.code));
        }
    };
    const canShare = patient.relationship !== 'caregiver';
    return [
        rowList(team.map((row) => listRow({
            lead: initials(`${row.first_name} ${row.last_name}`),
            title: `${row.first_name} ${row.last_name}`,
            meta: `${row.role} · ${row.scope === 'full' ? 'Can update' : 'View only'}`,
            tags: [(patient.relationship === 'self' || row.user_id === me.id)
                ? h('button', {
                    type: 'button',
                    class: 'quiet',
                    onclick: async () => {
                        await act(() => api(`/api/patients/${patient.id}/care-team/${row.id}`, { method: 'DELETE' }), context, 'Access removed');
                        if (row.user_id === me.id) window.location.reload();
                        else refresh();
                    },
                }, row.user_id === me.id ? 'Leave' : 'Remove')
                : null],
        })), emptyState('Only the patient can see this record', '')),
        canShare && h('div', { class: 'row share-codes' },
            h('button', { type: 'button', class: 'quiet', onclick: issue('clinician', 'full') }, 'Code for a clinician'),
            (patient.relationship === 'self' || !patient.user_id) && h('button', { type: 'button', class: 'quiet', onclick: issue('caregiver', 'read') }, 'Code for a caregiver (view only)'),
            patient.relationship === 'clinician' && !patient.user_id && h('button', { type: 'button', class: 'quiet', onclick: issue('claim', 'full') }, 'Code for the patient to claim this record')),
        output,
    ];
}

export async function renderOverview(container, context) {
    const { patient, isClinician, refresh } = context;
    if (!patient) return startScreen(container, context);
    const showInterviews = context.isStaff && canUse({ id: 'diagnofast', audience: 'staff' }, context);
    const [timeline, encounters, documents, interviews] = await Promise.all([
        api(`/api/patients/${patient.id}/timeline`),
        api(`/api/patients/${patient.id}/encounters`),
        api(`/api/patients/${patient.id}/documents`),
        showInterviews ? api(`/api/diagnofast/intakes?patient_id=${patient.id}`).catch(() => []) : [],
    ]);
    const allergyForm = patient.relationship === 'caregiver' ? null : form(
        [
            { name: 'substance', label: 'Allergy to', required: true },
            { name: 'reaction', label: 'Reaction' },
            { name: 'severity', label: 'Severity', type: 'select', options: ['unknown', 'mild', 'moderate', 'severe'] },
        ],
        'Add allergy',
        async (values) => {
            await act(() => api(`/api/patients/${patient.id}/allergies`, { method: 'POST', body: values }), context, 'Allergy added');
            await context.openPatient(patient.id);
        },
        { inline: true },
    );
    const visitForm = isClinician ? form(
        [
            { name: 'type', label: 'Type', type: 'select', options: ['outpatient', 'inpatient', 'emergency', 'telehealth', 'home'] },
            { name: 'reason', label: 'Reason for visit' },
        ],
        'Start visit',
        async (values) => {
            await act(() => api(`/api/patients/${patient.id}/encounters`, { method: 'POST', body: values }), context, 'Visit started');
            refresh();
        },
        { inline: true },
    ) : null;
    const upload = form(
        [
            { name: 'file', label: 'PDF, JPG or PNG', type: 'file', required: true },
            { name: 'document_type', label: 'What is it', type: 'select', options: [['other', 'Other'], ['x_ray', 'X-ray'], ['scan', 'Scan'], ['prescription', "Doctor's prescription"], ['report', 'Report']] },
            { name: 'description', label: 'Describe it, so it can be found later', maxlength: 2000 },
        ],
        'Upload document',
        async ({ file, document_type: documentType, description }) => {
            const data = new FormData();
            data.append('file', file);
            data.append('document_type', documentType);
            data.append('description', description || '');
            await act(() => api(`/api/patients/${patient.id}/documents`, { method: 'POST', form: data }), context, 'Document uploaded');
            refresh();
        },
        { inline: true },
    );

    // Where each journey entry came from. Only reviewed and approved events reach the journey.
    const JOURNEY_SOURCE = { encounters: 'doctor_recorded', clinscribe: 'doctor', dischargecare: 'doctor', referralloop: 'doctor_recorded', lablens: 'checked', diagnofast: 'patient', prescription: 'patient_confirmed' };
    const allergies = await api(`/api/patients/${patient.id}/allergies`).catch(() => []);
    const sections = [
        ['journey', 'Journey'], ['visits', 'Visits'], showInterviews && ['interviews', 'Interviews'],
        ['allergies', 'Allergies'], ['documents', 'Documents'],
        patient.relationship !== 'caregiver' && ['pack', 'Patient pack'], ['access', 'Who can see this'],
    ].filter(Boolean);
    // Buttons, not links: the address bar holds the workspace route.
    const jump = h('nav', { class: 'jump-nav', 'aria-label': 'Sections of this record' },
        sections.map(([id, label]) => h('button', { type: 'button', class: 'quiet', onclick: () => document.getElementById(`record-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, label)));
    const part = (id, title, ...children) => h('section', { class: 'sheet record-part', id: `record-${id}`, 'aria-labelledby': `record-${id}-title` },
        h('h2', { id: `record-${id}-title` }, title), ...children);
    const folded = (label, formElement) => (formElement ? h('details', { class: 'quiet-details' }, h('summary', {}, label), formElement) : null);
    [allergyForm, visitForm, upload].forEach((item) => item?.querySelector('button[type="submit"]').classList.add('quiet'));

    show(container,
        h('h1', {}, 'Patient record'),
        h('p', { class: 'lede' }, 'Everything in this journey, in order. Each entry says where it came from: what the patient said, what a doctor confirmed, and what came from ABHA.'),
        visitStrip(context),
        jump,
        h('div', { class: 'record-layout' },
            h('div', { class: 'record-main' },
                part('journey', 'Journey',
                    h('p', { class: 'muted' }, 'Only reviewed and approved events appear here.'),
                    timeline.length
                        ? h('ol', { class: 'timeline record-timeline' }, timeline.map((event) => h('li', {},
                            h('div', { class: 'journey-line' }, h('strong', {}, event.title), event.detail ? h('span', {}, ` ${event.detail}`) : null),
                            h('div', { class: 'row journey-meta' },
                                h('span', { class: 'muted' }, `${when(event.occurred_at)} · ${event.module}`),
                                JOURNEY_SOURCE[event.module] ? provenance(JOURNEY_SOURCE[event.module]) : null))))
                        : emptyState('Nothing yet', 'Visits, confirmed lab reports, signed notes and referrals will appear here.')),
                part('visits', 'Visits',
                    rowList(encounters.map((row) => listRow({
                        leadIcon: row.status === 'in_progress' ? 'clock' : 'check',
                        tone: row.status === 'in_progress' ? 'accent' : '',
                        title: row.reason || 'Visit',
                        meta: `${when(row.started_at)} · ${row.type}`,
                        tags: [badge(row.status === 'in_progress' ? 'In progress' : row.status, row.status === 'in_progress' ? '' : 'good'), provenance('doctor_recorded')],
                    })), emptyState('No visits recorded', isClinician ? 'Start one below.' : '')),
                    folded('Start a visit', visitForm)),
                showInterviews ? part('interviews', 'Pre-visit interviews',
                    h('p', { class: 'muted' }, 'Answers are what the patient said. Past records in a report are marked From ABHA (simulated), and nothing is confirmed until a doctor marks the report as reviewed.'),
                    rowList(interviews.map((item) => listRow({
                        lead: item.urgent.length ? undefined : initials(item.patient_name),
                        leadIcon: item.urgent.length ? 'alert' : undefined,
                        tone: item.urgent.length ? 'urgent' : '',
                        title: item.urgent.length ? `Urgent: ${item.urgent.join(', ')}` : 'DiagnoFast interview',
                        meta: when(item.created_at),
                        tags: [provenance('patient'), item.reviewed ? badge('Reviewed', 'good') : ['done', 'report_failed'].includes(item.status) ? badge('To review', 'warn') : null],
                        href: `#/diagnofast/${item.id}`,
                    })), emptyState('No interviews yet', h('a', { href: '#/diagnofast' }, 'Send a DiagnoFast link')))) : null,
                part('documents', 'Documents',
                    rowList(documents.map((row) => listRow({
                        leadIcon: 'file',
                        title: row.filename,
                        meta: `${row.document_type.replaceAll('_', ' ')} · added ${when(row.created_at)}`,
                        tags: [h('a', { class: 'button quiet', href: `/api/documents/${row.id}/file` }, 'Open')],
                    })), emptyState('No documents yet', 'Upload a report, scan or prescription so it stays with the record.')),
                    patient.relationship !== 'caregiver' ? folded('Upload a document', upload) : null)),
            h('div', { class: 'record-side' },
                part('allergies', 'Allergies',
                    allergies.length
                        ? h('ul', { class: 'allergy-list' }, allergies.map((item) => h('li', { class: item.status === 'active' ? 'active' : '' },
                            h('div', {}, h('strong', {}, item.substance), [item.reaction, item.severity && item.severity !== 'unknown' ? item.severity : ''].filter(Boolean).length
                                ? h('span', { class: 'muted' }, ` · ${[item.reaction, item.severity !== 'unknown' ? item.severity : ''].filter(Boolean).join(', ')}`) : null),
                            h('div', { class: 'row' }, provenance(item.source_type === 'clinician_entered' ? 'doctor' : 'patient'),
                                item.status !== 'active' ? badge(item.status) : null))))
                        : emptyState('No allergies recorded', "That doesn't mean there are none. Ask, and record what the patient says."),
                    folded('Add an allergy', allergyForm)),
                patient.relationship !== 'caregiver' ? part('pack', 'Patient pack', await packPanel(patient.id, context)) : null,
                part('access', 'Who can see this record', await careTeamPanel(context)))),
    );
    return undefined;
}

const STATUS_CHOICES = { open: 'Reopen', done: 'Done', blocked: 'Blocked', missed: 'Missed' };

const TASK_WORDS = { open: 'Open', done: 'Done', blocked: 'Blocked', missed: 'Missed', held: 'Starts on approval' };

// Tasks as rows: what, when, and its state in words. The status buttons sit in the row's details.
export function taskList(tasks, context, onChange) {
    return rowList(tasks.map((task) => listRow({
        leadIcon: task.status === 'done' ? 'check' : task.overdue ? 'clock' : 'tasks',
        tone: task.status === 'done' ? 'good' : task.overdue || ['blocked', 'missed'].includes(task.status) ? 'urgent' : '',
        title: task.title,
        meta: [task.due_at ? `Due ${when(task.due_at)}` : 'No due date', task.audience === 'patient' ? 'For the patient or family' : task.audience === 'care_team' ? 'For the care team' : null].filter(Boolean).join(' · '),
        tags: [
            task.overdue && task.status !== 'done' ? badge('Overdue', 'bad') : null,
            task.priority === 'high' ? badge('High priority', 'bad') : null,
            badge(TASK_WORDS[task.status] || task.status, task.status === 'done' ? 'good' : ['blocked', 'missed'].includes(task.status) ? 'warn' : ''),
        ],
        details: [
            task.detail ? h('p', {}, task.detail) : null,
            task.status_note ? h('p', { class: 'muted' }, `Note: ${task.status_note}`) : null,
            h('div', { class: 'row', role: 'group', 'aria-label': `Change ${task.title}` }, Object.entries(STATUS_CHOICES)
                .filter(([status]) => status !== task.status && (status !== 'open' || task.status !== 'open'))
                .map(([status, label]) => h('button', {
                    type: 'button',
                    class: status === 'done' ? '' : 'quiet',
                    onclick: async () => {
                        const note = status === 'blocked' || status === 'missed' ? await ask('What happened?') ?? '' : '';
                        await act(() => api(`/api/tasks/${task.id}/status`, { method: 'POST', body: { status, note } }), context, 'Task updated');
                        onChange();
                    },
                }, label))),
        ],
    })), emptyState('No tasks', 'Tasks for this patient appear here.'));
}

export async function renderTasks(container, context) {
    const { patient, isClinician, refresh } = context;
    if (!patient) return needPatient(container);
    const tasks = await api(`/api/patients/${patient.id}/tasks`);
    const add = isClinician ? form(
        [
            { name: 'title', label: 'Task', required: true },
            { name: 'audience', label: 'For', type: 'select', options: [['care_team', 'Care team'], ['patient', 'Patient']] },
            { name: 'priority', label: 'Priority', type: 'select', options: ['routine', 'high'] },
            { name: 'due_at', label: 'Due', type: 'datetime-local' },
        ],
        'Add task',
        async (values) => {
            if (values.due_at) values.due_at = new Date(values.due_at).toISOString();
            await act(() => api(`/api/patients/${patient.id}/tasks`, { method: 'POST', body: values }), context, 'Task added');
            refresh();
        },
        { inline: true },
    ) : null;
    if (add) add.querySelector('button[type="submit"]').classList.add('quiet');
    const open = tasks.filter((task) => !['done', 'held'].includes(task.status));
    show(container,
        h('h1', {}, 'Tasks'),
        add ? h('details', { class: 'sheet add-panel' }, h('summary', {}, h('h2', {}, 'Add a task')), add) : null,
        h('div', { class: 'section-head' }, h('h2', {}, 'Open'), h('p', { class: 'muted' }, `${open.length} of ${tasks.length}`)),
        taskList(open, context, refresh),
        tasks.length > open.length ? [h('h2', {}, 'Done or waiting'), taskList(tasks.filter((task) => !open.includes(task)), context, refresh)] : null);
    return undefined;
}

export async function renderInbox(container, context) {
    const notes = await api('/api/notifications');
    const unread = notes.filter((note) => !note.read_at).length;
    show(container,
        h('h1', {}, 'Inbox'),
        h('p', { class: 'lede' }, unread ? `${unread} new` : 'Everything here has been read.'),
        rowList(notes.map((note) => listRow({
            leadIcon: 'bell',
            tone: note.read_at ? 'muted-row' : 'accent',
            title: note.title,
            meta: when(note.created_at),
            tags: [note.read_at ? null : badge('New', 'warn')],
            details: [
                note.body ? h('p', {}, note.body) : h('p', { class: 'muted' }, 'No more detail.'),
                note.read_at ? null : h('div', { class: 'row' }, h('button', {
                    type: 'button',
                    class: 'quiet',
                    onclick: async () => {
                        await act(() => api(`/api/notifications/${note.id}/read`, { method: 'POST' }), context);
                        context.refresh();
                    },
                }, 'Mark as read')),
            ],
            open: !note.read_at && notes.length <= 3,
        })), emptyState('Nothing new', 'Messages from your care team and the tools arrive here.')),
    );
}
