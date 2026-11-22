// ReferralLoop: send a referral and follow it until the outcome is reviewed.
import { act, api, ask, badge, emptyState, form, h, listRow, loadingRows, plural, rowList, table, tabs, toast, when, show } from './ui.js';
import { icon, initials } from './icons.js';
import { packPanel } from './pack.js';
import { networkPanel } from './referral_network.js';

const BASE = '/api/addons/referrals';
const PACK_STATUSES = ['accepted', 'appointment_offered', 'booked', 'rescheduled', 'no_show', 'attended', 'outcome_returned'];
const RECEIVER_ACTIONS = {
    sent: [['acknowledged', 'Acknowledge'], ['needs_information', 'Ask for more information'], ['declined', 'Decline'], ['redirected', 'Redirect']],
    acknowledged: [['accepted', 'Accept'], ['needs_information', 'Ask for more information'], ['declined', 'Decline'], ['redirected', 'Redirect']],
    booked: [['attended', 'Patient attended'], ['no_show', 'Did not attend'], ['rescheduled', 'Rescheduled']],
    rescheduled: [['attended', 'Patient attended'], ['no_show', 'Did not attend'], ['booked', 'Booked again']],
    appointment_offered: [['booked', 'Patient accepted'], ['declined', 'Decline']],
};

function daysFromNow(days) {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return date.toISOString().slice(0, 10);
}

const destinationName = (link) => link.organization || link.manual_destination || 'a named clinician';

// A declined or redirected referral: the referrer sends the same request somewhere else. The new
// referral replaces this one, which then closes with a link to it.
function replacement(referral, context, reload) {
    const holder = h('div', {});
    const { defaults } = context.config;
    const days = referral.priority === 'urgent' ? defaults.referrals_urgent_days : defaults.referrals_routine_days;
    api('/api/organizations').then((organizations) => {
        const choices = organizations
            .filter((item) => item.verification_status === 'verified' && item.id !== referral.receiving_organization_id)
            .map((item) => [item.id, `${item.name} (${item.specialities || item.type})`]);
        show(holder,
            h('h3', {}, 'Send this referral somewhere else'),
            h('p', { class: 'muted' }, 'The reason, question, priority and shared documents are copied. This referral then closes and links to the new one.'),
            form(
                [
                    { name: 'organization', label: 'Send to', type: 'select', options: [['', 'Phone, fax or paper'], ...choices] },
                    { name: 'manual_destination', label: 'If by phone, fax or paper: who' },
                    { name: 'respond_by', label: 'Reply needed by', type: 'date', required: true, value: daysFromNow(days) },
                ],
                'Send the replacement referral',
                async (values) => {
                    const body = {
                        patient_id: referral.patient_id,
                        specialty: referral.specialty,
                        priority: referral.priority,
                        respond_by: values.respond_by,
                        reason: referral.reason,
                        clinical_question: referral.clinical_question || '',
                        document_ids: (referral.documents || []).map((item) => item.id),
                        receiving_organization_id: values.organization || null,
                        manual_destination: values.organization ? '' : values.manual_destination || '',
                        replaces_referral_id: referral.id,
                    };
                    const made = await act(() => api(BASE, { method: 'POST', body }), context, 'Replacement referral sent');
                    if (made) reload(made.id);
                },
            ));
    }).catch(() => show(holder, h('p', { class: 'muted' }, "The list of services isn't available. Use New referral below.")));
    return holder;
}

function referralDetail(area, referral, context, reload) {
    const manual = !referral.receiving_organization_id && !referral.receiving_user_id;
    const canAct = referral.side === 'receiver' || (referral.side === 'referrer' && manual);
    const move = (status) => async () => {
        const needsNote = ['declined', 'redirected', 'needs_information'].includes(status);
        const note = needsNote ? await ask('Please give a reason, so the referrer knows what to do next') : '';
        if (needsNote && !note) return;
        const body = { status, note: note || '' };
        await act(() => api(`${BASE}/${referral.id}/status`, { method: 'PATCH', body }), context, 'Updated');
        reload(referral.id);
    };
    const actions = canAct ? (RECEIVER_ACTIONS[referral.status] || []) : [];
    const booking = canAct && ['accepted', 'appointment_offered', 'no_show'].includes(referral.status) ? form(
        [
            { name: 'scheduled_at', label: 'Date and time', type: 'datetime-local', required: true },
            { name: 'location', label: 'Where' },
            { name: 'booked', label: 'The patient has agreed this time', type: 'checkbox' },
        ],
        'Save appointment',
        async (values) => {
            await act(() => api(`${BASE}/${referral.id}/appointments`, { method: 'POST', body: values }), context, 'Appointment saved');
            reload(referral.id);
        },
        { inline: true },
    ) : null;
    const outcome = canAct && referral.status === 'attended' ? form(
        [
            { name: 'summary', label: 'Outcome', type: 'textarea', required: true },
            { name: 'recommendations', label: 'Recommendations', type: 'textarea' },
            { name: 'follow_up_owner', label: 'Who follows up' },
            { name: 'file', label: 'Consult note (optional)', type: 'file' },
        ],
        'Return the outcome',
        async (values) => {
            const data = new FormData();
            data.append('summary', values.summary);
            data.append('recommendations', values.recommendations || '');
            data.append('follow_up_owner', values.follow_up_owner || '');
            if (values.file) data.append('file', values.file);
            await act(() => api(`${BASE}/${referral.id}/outcome`, { method: 'POST', form: data }), context, 'Outcome returned');
            reload(referral.id);
        },
    ) : null;
    const open = !['closed', 'cancelled'].includes(referral.status);
    const pack = h('div', {});
    const showsPack = referral.side === 'receiver' && referral.pack_shared && PACK_STATUSES.includes(referral.status);

    show(area,
        h('section', { class: 'sheet referral-detail', 'aria-label': 'Referral' },
            h('div', { class: 'section-head' },
                h('h2', {}, `${referral.specialty} for ${referral.patient.first_name} ${referral.patient.last_name}`),
                h('div', { class: 'row' },
                    referral.priority === 'urgent' ? badge('Urgent', 'bad') : badge('Routine'),
                    badge(STATUS_WORDS[referral.status] || referral.status, statusKind(referral)))),
            (referral.exceptions || []).map((item) => h('div', { class: 'banner danger with-icon' }, icon('alert', 'button-icon'), h('span', {}, item))),
            referral.replaced_by ? h('p', {}, `Replaced by a referral to ${destinationName(referral.replaced_by)} (${referral.replaced_by.status.replaceAll('_', ' ')}). `,
                h('button', { type: 'button', class: 'link-button', onclick: () => reload(referral.replaced_by.id) }, 'Open the new referral')) : null,
            referral.replaces ? h('p', {}, `Follows an earlier referral to ${destinationName(referral.replaces)}. `,
                h('button', { type: 'button', class: 'link-button', onclick: () => reload(referral.replaces.id) }, 'Open the earlier referral')) : null,
            h('p', {}, referral.reason),
            referral.clinical_question ? h('p', {}, h('strong', {}, 'Question: '), referral.clinical_question) : null,
            h('p', { class: 'muted' }, `From ${referral.referring_clinician}. Reply needed by ${when(referral.respond_by)}.${referral.manual_destination ? ` Sent to: ${referral.manual_destination}.` : ''}`),
            referral.documents?.length ? h('ul', {}, referral.documents.map((item) => h('li', {}, h('a', { href: `/api/documents/${item.id}/file` }, item.filename)))) : null,
            showsPack ? h('div', { class: 'detail-block' },
                h('button', { type: 'button', class: 'quiet', onclick: async () => show(pack, await packPanel(referral.patient_id, context)) }, "Open the patient's pack"),
                pack) : null,
            referral.appointments.length ? table(
                [
                    { label: 'Appointment', cell: (row) => when(row.scheduled_at) },
                    { label: 'Where', cell: (row) => row.location },
                    { label: 'Status', cell: (row) => badge(row.status) },
                ],
                referral.appointments,
            ) : null,
            referral.outcome?.summary ? h('div', { class: 'outcome-block' }, h('h3', {}, 'Outcome'), h('p', {}, referral.outcome.summary), h('p', {}, referral.outcome.recommendations)) : null,
            actions.length ? h('div', { class: 'action-bar' },
                h('p', { class: 'action-note' }, 'Next step for this referral'),
                actions.map(([status, label], index) => h('button', { type: 'button', class: index === 0 ? 'primary-lg' : 'quiet', onclick: move(status) }, label))) : null,
            booking, outcome,
            referral.side === 'referrer' && ['redirected', 'declined'].includes(referral.status) ? replacement(referral, context, reload) : null,
            h('div', { class: 'detail-primary' },
                referral.side === 'referrer' && referral.status === 'needs_information' ? h('button', { type: 'button', class: 'primary-lg', onclick: move('sent') }, 'Send again with the information') : null,
                referral.side === 'referrer' && referral.status === 'outcome_returned' ? h('button', {
                type: 'button',
                class: 'primary-lg',
                onclick: async () => {
                    await act(() => api(`${BASE}/${referral.id}/review`, { method: 'POST', body: {} }), context, 'Referral closed');
                    reload(referral.id);
                },
            }, 'I have reviewed this: close the referral') : null,
            ),
            h('div', { class: 'row detail-secondary' },
            canAct && open ? h('button', {
                type: 'button',
                class: 'link-button detail-link',
                onclick: async () => {
                    const note = await ask('What happened on this contact attempt?') ?? '';
                    await act(() => api(`${BASE}/${referral.id}/contact-attempts`, { method: 'POST', body: { note } }), context, 'Attempt recorded');
                    reload(referral.id);
                },
            }, `Record a contact attempt (${referral.contact_attempts} so far)`) : null,
            referral.side !== 'patient' && open ? h('details', { class: 'inline-details' },
                h('summary', {}, 'Change priority'),
                form(
                    [
                        { name: 'priority', label: 'Priority, by your judgement', type: 'select', value: referral.priority === 'urgent' ? 'routine' : 'urgent', options: ['routine', 'urgent'] },
                        { name: 'reason', label: 'Why is it changing?', required: true },
                    ],
                    'Save priority',
                    async (values) => {
                        const changed = await act(() => api(`${BASE}/${referral.id}/priority`, { method: 'POST', body: values }), context, 'Priority changed');
                        if (changed) reload(referral.id);
                    },
                    { inline: true },
                )) : null,
            // A returned outcome is closed by reviewing it, never by cancelling: the server refuses that too.
            referral.side === 'referrer' && open && referral.status !== 'outcome_returned' ? h('button', {
                type: 'button',
                class: 'link-button detail-link',
                onclick: async () => {
                    const reason = await ask('Why is this referral closing without an outcome?');
                    if (!reason) return;
                    await act(() => api(`${BASE}/${referral.id}/close`, { method: 'POST', body: { reason } }), context, 'Referral closed');
                    reload(referral.id);
                },
            }, 'Close without an outcome') : null,
            ),
            h('details', { class: 'quiet-details' }, h('summary', {}, 'History'),
                table(
                    [
                        { label: 'When', cell: (row) => when(row.created_at) },
                        { label: 'Status', cell: (row) => row.to_status.replaceAll('_', ' ') },
                        { label: 'By', cell: (row) => (row.first_name ? `${row.first_name} ${row.last_name}` : '') },
                        { label: 'Note', cell: (row) => row.note || '' },
                    ],
                    referral.events,
                ))));
}

// Status words a person says, and how each one looks. Never colour alone: every tag is a word.
const STATUS_WORDS = {
    draft: 'Draft', sent: 'Sent', acknowledged: 'Acknowledged', accepted: 'Accepted', needs_information: 'Needs information',
    declined: 'Declined', redirected: 'Redirected', appointment_offered: 'Appointment offered', booked: 'Booked',
    rescheduled: 'Rescheduled', no_show: 'Did not attend', attended: 'Attended', outcome_returned: 'Outcome back',
    closed: 'Closed', cancelled: 'Cancelled',
};
function statusKind(referral) {
    if (['declined', 'redirected', 'no_show', 'needs_information'].includes(referral.status)) return 'warn';
    if (['closed', 'attended', 'outcome_returned'].includes(referral.status)) return 'good';
    return '';
}
const today = () => new Date().toISOString().slice(0, 10);
const isOverdue = (row) => !['closed', 'cancelled'].includes(row.status) && Boolean(row.exceptions?.length) && row.respond_by < today();

function referralRow(row, open) {
    const overdue = isOverdue(row);
    const chasing = !overdue && row.exceptions?.length;
    const where = row.side === 'receiver' ? `From ${row.referring_clinician}` : `To ${destinationName(row)}`;
    return listRow({
        lead: overdue ? undefined : initials(`${row.patient.first_name} ${row.patient.last_name}`),
        leadIcon: overdue ? 'clock' : undefined,
        tone: overdue ? 'urgent' : chasing ? 'warn' : '',
        title: `${row.patient.first_name} ${row.patient.last_name} · ${row.specialty}`,
        meta: [where, `Reply by ${when(row.respond_by)}`, row.exceptions?.[0]].filter(Boolean).join(' · '),
        tags: [
            overdue ? h('span', { class: 'status bad' }, 'Overdue') : chasing ? h('span', { class: 'status warn' }, 'Needs chasing') : null,
            row.priority === 'urgent' ? badge('Urgent', 'bad') : null,
            badge(STATUS_WORDS[row.status] || row.status, statusKind(row)),
        ],
        onclick: () => open(row.id),
        attrs: { 'aria-label': `Open the ${row.specialty} referral for ${row.patient.first_name} ${row.patient.last_name}${overdue ? ', overdue' : ''}` },
    });
}

function list(rows, open, empty) {
    return rowList(rows.map((row) => referralRow(row, open)), empty);
}

// One field with its label and a place for its own error, wired up for screen readers.
function field(label, control, { hint } = {}) {
    const id = `referral-${control.name}`;
    const error = h('p', { class: 'field-error', id: `${id}-error`, role: 'alert', hidden: true });
    control.id = id;
    control.setAttribute('aria-describedby', `${id}-error`);
    return {
        control,
        element: h('div', { class: 'field' }, h('label', { for: id }, label), control, hint ? h('p', { class: 'muted' }, hint) : null, error),
        fail(message) {
            error.textContent = message;
            error.hidden = false;
            control.setAttribute('aria-invalid', 'true');
        },
        clear() {
            error.hidden = true;
            control.removeAttribute('aria-invalid');
        },
    };
}

function newReferral(context, organizations, documents) {
    const { patient, refresh } = context;
    const { defaults } = context.config;
    const services = organizations.filter((item) => item.verification_status === 'verified');
    const picks = documents.map((item) => ({ item, box: h('input', { type: 'checkbox' }) }));

    const specialty = field('Specialty', h('input', { name: 'specialty', required: true, maxLength: 80 }));
    const priority = field('Priority, by your judgement', h('select', { name: 'priority' }, ['routine', 'urgent'].map((value) => h('option', { value }, value))));
    const respondBy = field('Reply needed by', h('input', { name: 'respond_by', type: 'date', required: true, value: daysFromNow(defaults.referrals_routine_days), min: daysFromNow(0) }));
    const service = field('Which service', h('select', { name: 'service' }, [h('option', { value: '' }, 'Choose a service'), ...services.map((item) => h('option', { value: item.id }, `${item.name} (${item.specialities || item.type})`))]));
    const manual = field('Who, and how to reach them', h('input', { name: 'manual_destination', maxLength: 200 }), { hint: 'For example: Dr Rao, City Heart Clinic, phone 011-555-0100' });
    const reason = field('Reason', h('textarea', { name: 'reason', required: true, maxLength: 1000 }));
    const question = field('Your question for the specialist', h('textarea', { name: 'clinical_question', maxLength: 1000 }));

    // Where it goes is a choice the clinician makes, so nothing is picked for them.
    const destinationError = h('p', { class: 'field-error', id: 'referral-destination-error', role: 'alert', hidden: true });
    const choice = (value, label) => h('label', { class: 'tick' }, h('input', { type: 'radio', name: 'destination', value, required: true }), label);
    const destination = h('fieldset', { class: 'choice', 'aria-describedby': 'referral-destination-error' },
        h('legend', {}, 'Send to'),
        choice('service', 'A service on Diagnosia'),
        choice('manual', 'By phone, fax or paper'),
        destinationError);
    service.element.hidden = true;
    manual.element.hidden = true;
    const chosen = () => destination.querySelector('input:checked')?.value;
    destination.addEventListener('change', () => {
        service.element.hidden = chosen() !== 'service';
        manual.element.hidden = chosen() !== 'manual';
        destinationError.hidden = true;
    });
    priority.control.addEventListener('change', () => {
        respondBy.control.value = daysFromNow(priority.control.value === 'urgent' ? defaults.referrals_urgent_days : defaults.referrals_routine_days);
    });

    const all = [specialty, priority, respondBy, service, manual, reason, question];
    // What is wrong, said beside the field it is wrong in. Returns the first one, to move focus to.
    const check = () => {
        all.forEach((item) => item.clear());
        destinationError.hidden = true;
        const problems = [];
        if (!specialty.control.value.trim()) problems.push([specialty, 'Say which specialty this is for.']);
        if (!respondBy.control.value) problems.push([respondBy, 'Give the date you need a reply by.']);
        else if (respondBy.control.value < daysFromNow(0)) problems.push([respondBy, "The reply-by date can't be in the past."]);
        if (!chosen()) {
            destinationError.textContent = 'Choose where to send this referral.';
            destinationError.hidden = false;
            problems.push([{ control: destination.querySelector('input') }, '']);
        } else if (chosen() === 'service' && !service.control.value) {
            problems.push([service, services.length ? 'Choose the service.' : 'No verified service is set up yet. Send it by phone, fax or paper instead.']);
        } else if (chosen() === 'manual' && !manual.control.value.trim()) {
            problems.push([manual, 'Say who it is going to.']);
        }
        if (!reason.control.value.trim()) problems.push([reason, 'Give the reason for this referral.']);
        problems.forEach(([item, message]) => message && item.fail(message));
        return problems[0]?.[0];
    };

    const submit = h('button', { type: 'submit' }, 'Send referral');
    const element = h('form', { class: 'stack', novalidate: true },
        specialty.element, priority.element, respondBy.element, destination, service.element, manual.element, reason.element, question.element,
        picks.length ? h('fieldset', { class: 'choice' }, h('legend', {}, 'Share these documents'), picks.map((pick) => h('label', { class: 'tick' }, pick.box, pick.item.filename))) : null,
        submit);
    element.addEventListener('submit', async (event) => {
        event.preventDefault();
        const first = check();
        if (first) {
            first.control.focus();
            return;
        }
        const body = {
            patient_id: patient.id,
            specialty: specialty.control.value.trim(),
            priority: priority.control.value,
            respond_by: respondBy.control.value,
            reason: reason.control.value.trim(),
            clinical_question: question.control.value.trim(),
            document_ids: picks.filter((pick) => pick.box.checked).map((pick) => pick.item.id),
            receiving_organization_id: chosen() === 'service' ? service.control.value : null,
            manual_destination: chosen() === 'manual' ? manual.control.value.trim() : '',
        };
        submit.disabled = true;
        try {
            const send = () => api(BASE, { method: 'POST', body });
            try {
                await send();
            } catch (error) {
                if (error.detail?.code !== 'possible_duplicate') throw error;
                const why = await ask(`${error.detail.message}\n\nReason:`);
                if (!why) return;
                body.confirm_duplicate_reason = why;
                await send();
            }
            toast('Referral sent');
            refresh();
        } catch (error) {
            // What the server refuses is shown on the field it is about, where there is one.
            const message = error.message || '';
            const target = /respond-by|reply/i.test(message) ? respondBy : /service/i.test(message) ? service : null;
            if (target) {
                target.fail(message);
                target.control.focus();
            } else {
                await act(() => { throw error; }, context);
            }
        } finally {
            submit.disabled = false;
        }
    });
    return element;
}

export async function renderReferrals(container, context) {
    const { patient, isClinician, isStaff } = context;
    const area = h('div', { class: 'stage-area' });
    const lists = h('div', { class: 'referral-lists' }, loadingRows('Loading referrals…'));
    const networkBox = h('div', {});
    // The open view survives a reload of the lists, so acting on a referral doesn't jump tabs.
    let current = ['sent', 'received', 'overdue', 'outcomes'].includes(context.route) ? context.route : null;
    const loadLists = async () => {
        const [rows, sent, inbox, exceptions] = await Promise.all([
            patient ? api(`${BASE}/patients/${patient.id}`) : [],
            api(`${BASE}/sent`),
            api(`${BASE}/inbox`),
            api(`${BASE}/exceptions`),
        ]);
        const views = [
            ...(patient ? [{ key: 'patient', label: `For ${patient.first_name}`, rows, empty: emptyState('No referrals for this patient', 'A referral you send for them appears here.') }] : []),
            { key: 'sent', label: 'Sent', rows: sent, empty: emptyState('Nothing sent yet', 'Referrals you send appear here until they are closed.') },
            { key: 'received', label: 'Received', rows: inbox, empty: emptyState('Nothing received', 'Referrals sent to you or your service appear here.') },
            { key: 'overdue', label: 'Overdue', rows: exceptions, alert: exceptions.some(isOverdue), empty: emptyState('Nothing to chase', 'Every open referral is on track.') },
            { key: 'outcomes', label: 'Outcome review', rows: sent.filter((row) => row.status === 'outcome_returned'), empty: emptyState('No outcomes to review', 'When a specialist returns an outcome, you review it here and close the loop.') },
        ];
        current = current || (patient ? 'patient' : exceptions.length ? 'overdue' : 'received');
        const view = views.find((item) => item.key === current) || views[0];
        show(
            lists,
            tabs(views.map((item) => ({ key: item.key, label: item.label, count: item.rows.length, alert: item.alert })), view.key, (key) => {
                current = key;
                loadLists().then(() => lists.querySelector(`[data-tab="${key}"]`)?.focus());
            }, 'Referral lists'),
            h('div', { class: 'tab-panel', role: 'tabpanel', 'aria-label': view.label },
                view.key === 'overdue' && view.rows.length ? h('p', { class: 'muted' }, 'Open referrals past their reply-by date, or waiting on someone. Each row says why.') : null,
                list(view.rows, open, view.empty)),
        );
    };
    const open = async (id) => {
        referralDetail(area, await api(`${BASE}/${id}`), context, open);
        await loadLists();
        area.scrollIntoView({ block: 'start' });
    };
    // With no patient open there is nobody to refer, so nothing here asks for one.
    const writing = Boolean(patient) && isClinician;
    const organizations = writing ? await api('/api/organizations') : [];
    const documents = writing ? await api(`/api/patients/${patient.id}/documents`) : [];

    if (!isStaff) {
        const patientRows = patient ? await api(`${BASE}/patients/${patient.id}`) : [];
        show(
            container,
            h('h1', {}, 'ReferralLoop'),
            h('p', { class: 'lede' }, 'Where your specialist referrals have got to.'),
            patient ? rowList(patientRows.map((row) => {
                const next = row.appointments.at(-1);
                return listRow({
                    leadIcon: 'referrals',
                    title: row.specialty,
                    meta: next ? `Appointment ${when(next.scheduled_at)}${next.location ? `, ${next.location}` : ''}` : 'No appointment yet',
                    tags: [badge(STATUS_WORDS[row.status] || row.status, statusKind(row))],
                });
            }), emptyState('No referrals', 'When your doctor refers you to a specialist, it shows here.')) : emptyState('Open your record first', ''),
        );
        return undefined;
    }
    show(
            container,
        h('h1', {}, 'ReferralLoop'),
        h('p', { class: 'lede' }, 'Follows a referral until the outcome is back and reviewed. Priority and timing stay your decision.'),
        // Sending a referral is why most people open this, so it comes first.
        writing
            ? h('details', { class: 'sheet new-referral', id: 'new-referral', open: true }, h('summary', {}, h('h2', {}, `New referral for ${patient.first_name}`)), newReferral(context, organizations, documents))
            : h('div', { class: 'empty', id: 'new-referral-guard' }, patient ? 'Only a clinician on this patient\'s care team can send a referral.' : 'Open a patient to send a new referral. Referrals sent to you are listed below.'),
        area,
        lists,
        context.config?.addons?.['referrals.network_view'] && h('details', { class: 'sheet referral-network' },
            h('summary', {}, h('h2', {}, 'Referral network'), h('span', { class: 'status' }, 'Staff only')), networkBox),
    );
    await loadLists();
    if (context.config?.addons?.['referrals.network_view']) {
        show(networkBox, await networkPanel().catch((error) => h('p', { class: 'error' }, error.message)));
    }
    return undefined;
}
