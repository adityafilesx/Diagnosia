// OPD bookings for reception: slots, queue numbers and the demo SMS outbox (BUILD.md step 4).
// Patients here are made up. Nothing is sent to any phone: the outbox only shows what would go.
import { act, api, badge, form, h, show, table, when } from './ui.js';

const STATUS = {
    waiting: 'Link not opened', in_progress: 'Answering now', preparing_report: 'Preparing report',
    done: 'Report ready', report_failed: 'Answers ready', expired: 'Link expired',
};

function today() {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function messageBox(message) {
    return h('div', { class: 'banner' },
        h('p', {}, h('strong', {}, `Demo ${message.channel === 'whatsapp' ? 'WhatsApp' : 'SMS'} to ${message.phone}`),
            ` · would send ${when(message.send_at)}`),
        h('p', {}, message.text),
        h('p', { class: 'muted' }, message.note));
}

export async function renderBookings(container, context) {
    const enabled = context.config?.addons?.['diagnofast.bookings'];
    if (!enabled) {
        show(container, h('h1', {}, 'OPD bookings'),
            h('p', { class: 'empty' }, 'OPD bookings are switched off. An administrator can turn them on in Settings, under DiagnoFast add-ons.'));
        return;
    }
    const forms = await api('/api/diagnofast/forms');
    let day = today();
    const slotsBox = h('div', {});
    const bookingsBox = h('div', {});
    const outboxBox = h('div', {});
    const lastMessage = h('div', { 'aria-live': 'polite' });
    const slotChoice = h('select', { name: 'slot_id', required: true });

    const load = async () => {
        const [slots, bookings, outbox] = await Promise.all([
            api(`/api/opd/slots?date=${day}`), api(`/api/opd/bookings?date=${day}`), api('/api/opd/outbox'),
        ]);
        show(slotChoice, (slots.length
            ? slots.map((slot) => h('option', { value: slot.id }, `${slot.starts_at.slice(11)}–${slot.ends_at.slice(11)} · ${slot.department}`))
            : [h('option', { value: '' }, 'Add a slot first')]));
        show(slotsBox, table([
            { label: 'Time', cell: (slot) => `${slot.starts_at.slice(11)}–${slot.ends_at.slice(11)}` },
            { label: 'Department', cell: (slot) => slot.department },
            { label: 'Booked', cell: (slot) => String(slot.booked), number: true },
            { label: 'QR', cell: (slot) => h('a', { href: `/api/opd/slots/${slot.id}/qr`, target: '_blank', rel: 'noopener' }, 'Show QR') },
        ], slots, 'No slots on this day yet.'));
        show(bookingsBox, table([
            { label: 'Queue', cell: (row) => h('strong', {}, String(row.queue_number)), number: true },
            { label: 'Patient', cell: (row) => [row.patient_name, row.urgent && h('span', {}, ' ', badge('urgent', 'bad'))] },
            { label: 'Department', cell: (row) => row.department || badge('to confirm', 'warn') },
            { label: 'Phone', cell: (row) => row.phone },
            { label: 'Interview', cell: (row) => row.intake_id
                ? h('a', { href: `#/diagnofast/${row.intake_id}` }, STATUS[row.interview_status] || row.interview_status)
                : 'No link yet' },
            { label: '', cell: (row) => row.form_id && ['waiting', 'expired', null].includes(row.interview_status) && h('button', {
                type: 'button', class: 'quiet',
                onclick: async () => {
                    const message = await act(() => api(`/api/opd/bookings/${row.id}/link`, { method: 'POST', body: {} }), context, 'New link in the demo outbox');
                    if (message) { show(lastMessage, messageBox(message)); await load(); }
                },
            }, 'Send link again') },
        ], bookings, 'No bookings on this day yet.'));
        show(outboxBox, table([
            { label: 'When', cell: (row) => when(row.send_at) },
            { label: 'To', cell: (row) => `${row.channel === 'whatsapp' ? 'WhatsApp' : 'SMS'} ${row.phone}` },
            { label: 'Message', cell: (row) => row.text },
        ], outbox.slice(0, 20), 'Nothing in the demo outbox yet.'));
    };

    const dayPicker = h('input', { type: 'date', value: day, 'aria-label': 'Day' });
    dayPicker.addEventListener('change', async () => { day = dayPicker.value || today(); await load(); });

    const addSlot = form(
        [
            { name: 'form_id', label: 'Department', type: 'select', options: forms.map((item) => [item.id, item.title]) },
            { name: 'starts', label: 'Starts', type: 'time', required: true, value: '09:00' },
            { name: 'ends', label: 'Ends', type: 'time', required: true, value: '10:00' },
        ],
        'Add slot',
        async (values) => {
            const made = await act(() => api('/api/opd/slots', {
                method: 'POST', body: { form_id: values.form_id, starts_at: `${day}T${values.starts}`, ends_at: `${day}T${values.ends}` },
            }), context, 'Slot added');
            if (made) await load();
        },
    );

    const bookForm = form(
        [
            { name: 'patient_name', label: 'Patient name (made up)', required: true, maxlength: 120 },
            { name: 'patient_age', label: 'Age', type: 'number', min: 0, max: 130 },
            { name: 'patient_sex', label: 'Sex', type: 'select', options: [['', 'Not recorded'], ['female', 'Female'], ['male', 'Male'], ['other', 'Other']] },
            { name: 'phone', label: 'Mobile number', required: true, maxlength: 20, placeholder: '98765 43210' },
            { name: 'channel', label: 'Send by', type: 'select', options: [['sms', 'SMS'], ['whatsapp', 'WhatsApp']] },
        ],
        'Book and send link',
        async (values, element) => {
            const booked = await act(() => api('/api/opd/bookings', {
                method: 'POST',
                body: {
                    slot_id: slotChoice.value, patient_name: values.patient_name, phone: values.phone, channel: values.channel,
                    patient_age: values.patient_age === '' ? null : Number(values.patient_age), patient_sex: values.patient_sex || null,
                },
            }), context, 'Booked');
            if (!booked) return;
            show(lastMessage, h('p', {}, h('strong', {}, `Queue number ${booked.queue_number}`), ` · ${booked.department}`), messageBox(booked.message));
            element.reset();
            await load();
        },
    );
    bookForm.prepend(h('label', {}, 'Slot', slotChoice));

    await load();
    show(container,
        h('h1', {}, 'OPD bookings'),
        h('p', { class: 'lede' }, 'Book a patient into a slot. They get a queue number, and their interview link goes to the demo outbox. Nothing is sent to a real phone.'),
        h('p', {}, h('a', { href: '#/diagnofast' }, '← Back to DiagnoFast')), h('label', {}, 'Day', dayPicker),
        h('div', { class: 'columns' },
            h('div', { class: 'sheet' }, h('h2', {}, 'Book a patient'), bookForm, lastMessage),
            h('div', { class: 'sheet' }, h('h2', {}, 'Slots'), slotsBox, h('h3', {}, 'Add a slot'), addSlot)),
        h('div', { class: 'sheet' }, h('h2', {}, 'Queue for the day'), bookingsBox),
        h('div', { class: 'sheet' }, h('h2', {}, 'Demo SMS / WhatsApp outbox'), outboxBox));
}
