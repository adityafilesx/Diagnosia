// Prescription Analyzer. Nothing is explained until the patient has confirmed it. The server keeps
// its own copy of what was read and says which medicines can be ticked (`confirmable`); this page
// sends back only which cards were ticked, so the server never relies on the page for what was read.
import { api, h, plural, readAloud, show, toast } from './ui.js';

const LEGIBILITY_NOTE = {
    unsure: 'We are not sure about this one. Please check it carefully.',
    unreadable: "We couldn't read this. Please ask your pharmacist.",
};
const LANGUAGES = [['hi-IN', 'हिन्दी'], ['en-IN', 'English']];

function medicineCheckText(match) {
    if (!match) return null;
    const contains = match.contains ? ` It contains ${match.contains}.` : '';
    if (match.status === 'found') return `Found in our medicine list.${contains}`;
    if (match.status === 'close') return `Did you mean ${match.name}?${contains}`;
    if (match.status === 'not_found') return "This name isn't in our medicine list.";
    if (match.status === 'unchecked') return 'We could not check this name against a list. Compare it with your prescription letter by letter.';
    return null;
}

const FIELD_WORDS = { name: 'name', dose: 'dose', frequency: 'how often', day_pattern: 'daily pattern', duration: 'how long', notes: 'notes' };

// When the photo was read twice and the readings disagree, both are shown. Neither is chosen:
// the patient checks the paper.
function otherReading(medicine) {
    if (medicine.only_in_one_reading) {
        return h('p', {}, h('mark', {}, 'We read your photo twice and only one reading found this medicine. Check it against your prescription.'));
    }
    const different = Object.entries(medicine.differs || {});
    if (!different.length) return null;
    return h('p', {}, h('mark', {}, 'We read your photo twice and the readings differ. Check your prescription.'),
        h('ul', {}, different.map(([key, value]) => h('li', {}, `${FIELD_WORDS[key] || key}: the other reading said "${value || 'nothing'}"`))));
}

// The patient's own photos, shown beside each card so the reading can be compared with the paper.
// They are local object addresses made in this browser: nothing here uploads them.
let photoAddresses = [];

function forgetPhotos() {
    photoAddresses.forEach((address) => URL.revokeObjectURL(address));
    photoAddresses = [];
}

function rememberPhotos(files) {
    forgetPhotos();
    photoAddresses = [...files].map((photo) => URL.createObjectURL(photo));
}

function photoStrip() {
    if (!photoAddresses.length) return null;
    return h('div', { class: 'rx-photos' }, photoAddresses.map((address, number) => {
        const image = h('img', { src: address, alt: `Your photo ${number + 1} of the prescription`, loading: 'lazy' });
        const toggle = h('button', { type: 'button', class: 'rx-photo', 'aria-expanded': 'false', 'aria-label': `Photo ${number + 1}: make larger or smaller` }, image);
        toggle.addEventListener('click', () => {
            const large = toggle.classList.toggle('large');
            toggle.setAttribute('aria-expanded', String(large));
        });
        return toggle;
    }));
}

function medicineCard(medicine, index) {
    const worst = [medicine.name, medicine.frequency, medicine.dose, medicine.duration]
        .some((field) => field.legibility === 'unsure') ? 'unsure' : 'clear';
    // The server's rule, the same one it applies before explaining anything.
    const readable = Boolean(medicine.confirmable);
    const state = readable ? worst : 'unreadable';
    const written = [medicine.dose.value, medicine.frequency.value, medicine.day_pattern.value, medicine.duration.value]
        .filter(Boolean).join(', ');
    return h('div', { class: `medicine-card with-photo ${state}` },
        h('div', {},
            h('strong', {}, medicine.name.value || 'A medicine we could not read'),
            written && h('p', {}, `As written: ${written}`),
            medicine.plain && h('p', {}, medicine.plain),
            // A card with no name has nothing to check, so it says nothing about the list.
            medicine.name.value.trim() && medicineCheckText(medicine.match) && h('p', {}, medicineCheckText(medicine.match)),
            LEGIBILITY_NOTE[state] && h('p', {}, h('mark', {}, LEGIBILITY_NOTE[state])),
            otherReading(medicine),
            readable && h('label', { class: 'tick' },
                h('input', { type: 'checkbox', 'data-index': index }),
                'This matches my prescription')),
        photoStrip());
}

// Which cards the patient ticked, by their place in the reading.
function tickedCards(list) {
    return [...list.querySelectorAll('input:checked')].map((tick) => Number(tick.dataset.index));
}

function listenButton(text, language) {
    const button = h('button', { type: 'button', class: 'quiet no-print' }, 'Listen');
    button.addEventListener('click', async () => {
        button.disabled = true;
        const spoken = await readAloud(text, language);
        if (!spoken) button.textContent = 'Audio unavailable';
        button.disabled = false;
    });
    return button;
}

function listCard(title, items, language) {
    return h('div', { class: 'sheet' },
        h('h2', {}, title),
        h('ul', {}, items.map((item) => h('li', {}, item))),
        language && listenButton(items.join('. ').slice(0, 2400), language));
}

function saveButton(readingId, confirmed) {
    const button = h('button', { type: 'button', class: 'quiet no-print' }, 'Save to my record');
    button.addEventListener('click', async () => {
        button.disabled = true;
        try {
            await api('/api/prescription/save', { method: 'POST', body: { reading_id: readingId, confirmed: confirmed } });
            button.textContent = 'Saved to your record';
        } catch (error) {
            toast(error.message, true);
            button.disabled = false;
        }
    });
    return h('div', { class: 'sheet no-print' },
        h('p', {}, 'Keep the medicines you ticked in your record, so your doctors can see them. Your photo is not kept.'),
        button);
}
// Saves the calendar file the server built. Any calendar app can open it; nothing is sent anywhere.
function downloadIcs(icsText) {
    const blob = new Blob([icsText], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = h('a', { href: url, download: 'diagnosia-schedule.ics' });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

const SLOT_LABELS = { morning: 'Morning', afternoon: 'Afternoon', night: 'Night' };

// "days 1–5", "from day 6, no end date written", or "5 days". Never a length nobody wrote.
function courseWords(part) {
    if (part.no_end_date || !part.duration_days) {
        return part.first_day > 1 ? `from day ${part.first_day}, no end date written` : 'no end date written';
    }
    return part.first_day > 1 || part.last_day !== part.duration_days ? `days ${part.first_day}–${part.last_day}` : plural(part.duration_days, 'day');
}

function medicineLine(item) {
    return h('li', {},
        h('strong', {}, item.name),
        item.quantity ? ` — ${item.quantity}` : '',
        item.food ? `, ${item.food}` : '',
        item.purpose ? h('em', {}, ` (${item.purpose})`) : '',
        item.assumed ? h('span', { class: 'muted' }, " · usual time, the prescription doesn't say") : '',
        item.no_end_date ? h('span', { class: 'muted' }, ' · No end date written. Ask your doctor how long to take it.') : '');
}

// The one schedule: a table of what to take when, the reminder times, and the same thing as a
// calendar file. `request` is what the server needs to rebuild it for other times.
function scheduleView(schedule, language, request) {
    const slots = schedule.slots || {};
    const asNeeded = schedule.as_needed || [];
    const unscheduled = schedule.unscheduled || [];
    if (!Object.keys(slots).length && !asNeeded.length && !unscheduled.length) return null;

    const sheet = h('div', { class: 'sheet' });
    const startInput = h('input', { type: 'date', value: schedule.start_date });
    const timeInputs = Object.fromEntries(Object.keys(SLOT_LABELS).map((slot) => [slot, h('input', { type: 'time', value: schedule.times[slot] })]));
    const update = h('button', { type: 'button', class: 'quiet' }, 'Update times');
    update.addEventListener('click', async () => {
        update.disabled = true;
        try {
            const times = Object.fromEntries(Object.entries(timeInputs).filter(([, input]) => input.value).map(([slot, input]) => [slot, input.value]));
            const updated = await api('/api/prescription/calendar', { method: 'POST', body: { ...request, language, start_date: startInput.value, times } });
            sheet.replaceWith(scheduleView(updated, language, request));
        } catch (error) {
            toast(error.message, true);
            update.disabled = false;
        }
    });

    const rows = Object.keys(SLOT_LABELS).filter((slot) => slots[slot]).flatMap((slot) => slots[slot].segments.map((part) => h('tr', {},
        h('th', { scope: 'row' }, SLOT_LABELS[slot], h('div', { class: 'muted' }, slots[slot].time)),
        h('td', {}, h('ul', { class: 'plain' }, part.medicines.map(medicineLine))),
        h('td', {}, courseWords(part)))));

    sheet.append(
        h('h2', {}, 'Daily schedule'),
        rows.length ? h('div', { class: 'table-scroll' }, h('table', { class: 'schedule-table' },
            h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'When'), h('th', { scope: 'col' }, 'Medicines'), h('th', { scope: 'col' }, 'For how long'))),
            h('tbody', {}, rows))) : '',
        asNeeded.length ? h('div', {},
            h('h3', {}, 'Only when needed (no reminder)'),
            h('ul', {}, asNeeded.map((item) => h('li', {}, h('strong', {}, item.name), item.dose ? ` ${item.dose}` : '', item.purpose ? h('em', {}, ` (${item.purpose})`) : '')))) : '',
        unscheduled.length ? h('div', {},
            h('h3', {}, 'No time set. Ask your doctor or pharmacist when to take these'),
            h('ul', {}, unscheduled.map((item) => h('li', {}, h('strong', {}, item.name), item.reason ? ` — ${item.reason}` : '')))) : '',
        rows.length ? h('div', { class: 'schedule-controls no-print' },
            h('label', {}, 'Start date', startInput),
            ...Object.entries(SLOT_LABELS).map(([slot, label]) => h('label', {}, `${label} reminder`, timeInputs[slot])),
            update) : '',
        schedule.ics ? h('div', { class: 'row no-print', style: 'margin-top:12px' },
            h('button', { type: 'button', onclick: () => downloadIcs(schedule.ics) }, 'Download reminders (.ics)'),
            h('span', { class: 'muted' }, 'Open the file in your phone or computer calendar to set the reminders.')) : '');
    return sheet;
}

function resultsView(data, language, reading, confirmed) {
    const guidance = data.guidance;
    // What the server needs to rebuild the schedule when the patient changes the reminder times.
    const request = { reading_id: reading.reading_id, confirmed: confirmed, guidance, plan: data.plan };
    return [
        guidance && h('div', { class: 'sheet', lang: language.slice(0, 2) },
            h('h2', { lang: 'en' }, 'Your medicines'),
            guidance.medicines.map((medicine) => h('div', { class: 'medicine-card' },
                h('strong', {}, medicine.name),
                medicine.purpose && h('p', {}, medicine.purpose),
                h('p', {}, medicine.how_to_take),
                // The rules' own reading of the prescription, beside the sentence above, so the two can be compared.
                (medicine.decoded || medicine.as_written) && h('p', { class: 'muted', lang: 'en' },
                    medicine.as_written ? `As written: ${medicine.as_written}. ` : '',
                    medicine.decoded ? `That means: ${medicine.decoded}.` : ''),
                medicine.directions_rejected && h('p', { lang: 'en' }, h('mark', {}, "We left out the AI's wording for this one because its numbers didn't match your prescription.")),
                listenButton(`${medicine.name}. ${medicine.purpose} ${medicine.how_to_take}`, language)))),
        scheduleView(data.schedule, language, request),
        reading.follow_up_date.value && listCard('Next appointment', [reading.follow_up_date.value]),
        data.ask_pharmacist.length > 0 && listCard('Please ask your pharmacist or doctor about', data.ask_pharmacist),
        confirmed.length > 0 && saveButton(reading.reading_id, confirmed),
    ];
}

// The same words and version as backend/records/consent.py (a test checks they match).
const CONSENT_VERSION = '2026-11-21';
const CONSENT_TEXT = "I agree to my photo being sent to outside AI services to read it. Diagnosia doesn't keep the photo.";

const NO_LIST = "Medicine names can't be checked against a list on this server right now, so a misread name won't be flagged. Compare every name with your prescription, and ask your pharmacist if any looks wrong.";

export function renderPrescription(container, context) {
    const stepOne = h('div', {});
    const stepTwo = h('div', {});
    const stepThree = h('div', {});
    const photos = h('input', { type: 'file', name: 'images', accept: 'image/jpeg,image/png', multiple: true, required: true });
    const consent = h('input', { type: 'checkbox', required: true });
    const readButton = h('button', { type: 'submit' }, 'Read my prescription');

    const showConfirm = (reading) => {
        const list = h('div', {}, reading.medicines.map(medicineCard));
        const language = h('select', {}, LANGUAGES.map(([value, label]) => h('option', { value, lang: value.slice(0, 2) }, label)));
        const explain = h('button', { type: 'button' }, 'Explain my prescription');
        explain.addEventListener('click', async () => {
            explain.disabled = true;
            explain.textContent = 'Explaining...';
            try {
                const notes = reading.doctor_notes.legibility === 'unreadable' ? '' : reading.doctor_notes.value;
                const confirmed = tickedCards(list);
                const data = await api('/api/prescription/explain', {
                    method: 'POST',
                    body: { reading_id: reading.reading_id, confirmed: confirmed, language: language.value, doctor_notes: notes.slice(0, 2000) },
                });
                show(stepThree, resultsView(data, language.value, reading, confirmed));
                stepThree.scrollIntoView({ behavior: 'smooth' });
            } catch (error) {
                toast(error.message, true);
            }
            explain.disabled = false;
            explain.textContent = 'Explain my prescription';
        });
        show(stepTwo, h('div', { class: 'sheet' },
            h('h2', {}, 'Check what we read'),
            h('p', { class: 'lede' }, "Tick each medicine that matches your prescription. Anything you don't tick goes to your pharmacist's list and isn't explained."),
            reading.names_checked === false ? h('div', { class: 'banner danger', role: 'status' }, NO_LIST) : null,
            photoAddresses.length ? h('p', { class: 'muted' }, 'Your photo is beside each medicine so you can compare. Tap it to make it larger. It stays on this device.') : null,
            list,
            h('label', {}, 'Explain it in', language),
            h('div', { class: 'row' }, explain)));
        stepTwo.scrollIntoView({ behavior: 'smooth' });
    };

    const upload = h('form', {
        class: 'stack',
        onsubmit: async (event) => {
            event.preventDefault();
            show(stepOne);
            show(stepTwo);
            show(stepThree);
            readButton.disabled = true;
            readButton.textContent = 'Reading...';
            const body = new FormData();
            rememberPhotos(photos.files);
            [...photos.files].forEach((photo) => body.append('images', photo));
            body.append('consent', consent.checked);
            body.append('consent_version', CONSENT_VERSION);
            try {
                const reading = await api('/api/prescription/read', { method: 'POST', form: body });
                if (!reading.is_prescription) {
                    show(stepOne, h('p', { class: 'error', role: 'alert' }, "This doesn't look like a prescription. Please try another photo."));
                } else if (!reading.medicines.length) {
                    show(stepOne, h('p', { class: 'error', role: 'alert' }, "We couldn't find any medicines in this photo. Please take a clearer one."));
                } else {
                    showConfirm(reading);
                }
            } catch (error) {
                show(stepOne, h('p', { class: 'error', role: 'alert' }, error.message));
            }
            readButton.disabled = false;
            readButton.textContent = 'Read my prescription';
        },
    },
    h('label', {}, 'Photos of your prescription (JPG or PNG). Add the front and back if both have writing, up to 4 photos.', photos),
    h('label', { class: 'tick consent-row' }, consent, CONSENT_TEXT),
    readButton);

    show(container,
        h('h1', {}, 'Prescription Analyzer'),
        h('p', { class: 'lede' }, 'Reads your prescription and explains it in plain words. It never changes a dose.'),
        context?.config?.medicine_list_ready === false ? h('div', { class: 'banner danger no-print', id: 'no-medicine-list', role: 'status' }, NO_LIST) : null,
        h('div', { class: 'sheet no-print' }, upload),
        stepOne, stepTwo, stepThree,
        h('p', { class: 'muted no-print' }, h('a', { href: 'prescription_analyzer_hiw.html' }, 'How it works')));
}
