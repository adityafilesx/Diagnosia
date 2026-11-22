// Reminders, and the clinic's list of people who need a call.
import { act, api, badge, emptyState, form, h, listRow, rowList, section, show, table, toast, when } from './ui.js';

const STATE_WORDS = {
    pending: 'Scheduled',
    in_app_sent: 'Shown in the app, not confirmed',
    external_delivery_pending: 'With the provider, not confirmed',
    delivered: 'Provider reported delivery',
    failed: 'Delivery failed',
    staff_followup_required: 'Staff follow-up needed',
    acknowledged: 'Confirmed',
    cancelled: 'Cancelled',
};
const OUTCOMES = [
    ['reached', 'Reached the patient'],
    ['no_answer', 'No answer'],
    ['message_left', 'Left a message'],
    ['wrong_number', 'Wrong number'],
    ['patient_declined', 'Patient declined'],
    ['unable_to_contact', 'Could not contact'],
];

function stateBadge(state) {
    if (state === 'staff_followup_required' || state === 'failed') return badge(STATE_WORDS[state], 'bad');
    if (state === 'acknowledged') return badge(STATE_WORDS[state], 'good');
    return badge(STATE_WORDS[state]);
}

function outcomeControl(reminder, context) {
    const choice = h('select', { 'aria-label': 'What happened' }, OUTCOMES.map(([value, label]) => h('option', { value }, label)));
    return h('div', { class: 'row' },
        choice,
        h('button', {
            type: 'button',
            class: 'quiet',
            onclick: async () => {
                await act(() => api(`/api/reminders/${reminder.id}/outcome`, { method: 'POST', body: { outcome: choice.value } }), context, 'Outcome recorded');
                context.refresh();
            },
        }, 'Record'));
}

async function printCallList(area, context) {
    const list = await act(() => api('/api/reminders/call-list'), context);
    if (!list) return;
    show(area,
        h('div', { class: 'print-list' },
            h('h2', {}, 'Clinic call list'),
            h('p', { class: 'muted' }, `Printed ${when(list.generated_at)}. Confidential: destroy after use.`),
            table(
                [
                    { label: 'Name', cell: (row) => row.name },
                    { label: 'Phone', cell: (row) => row.phone || 'No phone on record' },
                    { label: 'Reason', cell: (row) => row.reason },
                    { label: 'Tries so far', number: true, cell: (row) => row.attempts },
                    { label: 'Outcome', cell: () => '' },
                ],
                list.entries,
                'Nobody needs a call.',
            )));
    document.body.classList.add('printing-list');
    window.addEventListener('afterprint', () => document.body.classList.remove('printing-list'), { once: true });
    window.print();
}

async function preferencesPanel(context) {
    const { patient } = context;
    const saved = await api(`/api/patients/${patient.id}/communication-preferences`);
    const canWrite = patient.relationship !== 'caregiver';
    return form(
        [
            { name: 'in_app', label: 'In the app', type: 'checkbox', value: saved.in_app },
            { name: 'clinic_call', label: 'Phone call from the clinic', type: 'checkbox', value: saved.clinic_call },
            { name: 'sms', label: 'SMS, if the clinic has set this up', type: 'checkbox', value: saved.sms },
            { name: 'voice', label: 'Automated voice call, if the clinic has set this up', type: 'checkbox', value: saved.voice },
        ],
        canWrite ? 'Save preferences' : 'Saving is not available',
        async (values) => {
            if (!canWrite) return;
            await act(() => api(`/api/patients/${patient.id}/communication-preferences`, { method: 'PUT', body: values }), context, 'Preferences saved');
        },
    );
}

export async function renderReminders(container, context) {
    const { patient, isClinician, isStaff, refresh } = context;
    const printArea = h('div', { class: 'print-holder' });
    const followUps = isStaff ? await api('/api/reminders/follow-up') : [];
    const reminders = patient ? await api(`/api/patients/${patient.id}/reminders`) : [];

    const schedule = isClinician ? form(
        [
            { name: 'title', label: 'Reminder', required: true },
            { name: 'purpose', label: 'About', type: 'select', options: [['follow_up', 'Follow-up'], ['appointment', 'Appointment'], ['test', 'Test'], ['medicine_review', 'Medicine review'], ['other', 'Other']] },
            { name: 'module', label: 'Linked to', type: 'select', options: [['general', 'General'], ['dischargecare', 'DischargeCare'], ['referralloop', 'ReferralLoop']] },
            { name: 'priority', label: 'Priority', type: 'select', options: ['routine', 'high'] },
            { name: 'scheduled_for', label: 'When', type: 'datetime-local', required: true },
            { name: 'respond_within_hours', label: 'Hours to confirm', type: 'number', min: 1, max: 168, value: context.config.defaults.reminders_respond_hours },
        ],
        'Schedule reminder',
        async (values) => {
            values.scheduled_for = new Date(values.scheduled_for).toISOString();
            const made = await act(() => api(`/api/patients/${patient.id}/reminders`, { method: 'POST', body: values }), context, 'Reminder scheduled');
            if (made) refresh();
        },
        { inline: true },
    ) : null;

    show(container,
        h('h1', {}, 'Reminders'),
        h('p', { class: 'lede' }, 'Tracks whether a reminder reached someone. If it can\'t be confirmed, a person follows up.'),
        h('div', { class: 'banner' }, 'A reminder is not an emergency or clinical escalation. Scheduled or sent does not mean it was received.'),
        isStaff ? [
            h('div', { class: 'section-head' }, h('h2', {}, 'Clinic follow-up'),
                h('button', { type: 'button', class: 'quiet', onclick: () => printCallList(printArea, context) }, 'Print a call list')),
            rowList(followUps.map((row) => listRow({
                leadIcon: 'phone',
                tone: row.overdue ? 'urgent' : 'warn',
                title: `${row.first_name} ${row.last_name} · ${row.title}`,
                meta: [row.phone || 'No phone on record', `Follow up by ${when(row.followup_due_at)}`, `${row.contact_attempts} ${row.contact_attempts === 1 ? 'try' : 'tries'}`].join(' · '),
                tags: [row.overdue ? badge('Overdue', 'bad') : null, row.priority === 'high' ? badge('High priority', 'bad') : null],
                details: [
                    row.failure_reason ? h('p', {}, row.failure_reason) : null,
                    outcomeControl(row, context),
                ],
            })), emptyState('Nobody needs a call right now', 'A reminder nobody confirmed comes here for a person to follow up.')),
        ] : null,
        printArea,
        patient ? [
            h('h2', {}, `Reminders for ${patient.first_name}`),
            schedule ? h('details', { class: 'sheet add-panel' }, h('summary', {}, h('h2', {}, 'Schedule a reminder')), schedule) : null,
            rowList(reminders.map((row) => {
                const kind = ['staff_followup_required', 'failed'].includes(row.state) ? 'urgent' : row.state === 'acknowledged' ? 'good' : '';
                const canConfirm = ['in_app_sent', 'delivered', 'external_delivery_pending'].includes(row.state) && !isClinician;
                return listRow({
                    leadIcon: row.state === 'acknowledged' ? 'check' : 'bell',
                    tone: kind,
                    title: row.title,
                    meta: `${when(row.scheduled_for)} · ${(row.channel || 'Channel not chosen yet').replaceAll('_', ' ')}`,
                    tags: [stateBadge(row.state)],
                    details: canConfirm ? h('div', { class: 'row' }, h('button', {
                        type: 'button',
                        onclick: async () => {
                            const done = await act(() => api(`/api/reminders/${row.id}/acknowledge`, { method: 'POST' }), context);
                            if (done) { toast('Thank you. Your care team can see this.'); refresh(); }
                        },
                    }, 'I saw this')) : h('p', { class: 'muted' }, STATE_WORDS[row.state] || row.state),
                    open: canConfirm,
                });
            }), emptyState('No reminders', isClinician ? 'Schedule one above.' : 'Reminders from your care team appear here.')),
        ] : emptyState('Open a patient', 'Open a patient to see or schedule their reminders.'),
        patient ? section('How to reach this person', await preferencesPanel(context)) : null,
    );
    return undefined;
}
