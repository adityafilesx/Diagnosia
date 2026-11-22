// Where everyone lands after signing in: their patients, who is waiting, and every tool.
import { api, emptyState, h, loadingRows, plural, show } from './ui.js';
import { STAGES, canUse } from './catalogue.js';
import { icon } from './icons.js';
import { QUEUE_FILTERS, queueRow } from './diagnofast.js';

export function toolList(context) {
    return h('div', { class: 'stages' }, STAGES.map((stage) => {
        const tools = stage.tools.filter((tool) => canUse(tool, context));
        return tools.length ? h('section', { class: 'stage' },
            h('h3', {}, stage.title),
            tools.map((tool) => h('a', { class: 'tool-link', href: `#/${tool.id}` },
                h('strong', {}, icon(tool.id), tool.label),
                h('span', {}, tool.blurb)))) : null;
    }));
}

// A short route to the next tool, shown at the top of a patient's record.
export function visitStrip(context) {
    return h('nav', { class: 'visit-strip', 'aria-label': 'Tools for this patient' }, STAGES.map((stage) => {
        const tools = stage.tools.filter((tool) => canUse(tool, context));
        return tools.length ? h('div', {},
            h('span', { class: 'muted' }, stage.title),
            h('div', { class: 'row' }, tools.map((tool) => h('a', { href: `#/${tool.id}` }, tool.label)))) : null;
    }));
}

function patientFinder(context) {
    const { patients, openPatient, me } = context;
    const open = async (patient) => {
        await openPatient(patient.id);
        window.location.hash = '#/overview';
    };
    const list = h('ul', { class: 'patient-list' });
    const fill = (words) => {
        const found = patients
            .filter((patient) => `${patient.first_name} ${patient.last_name}`.toLowerCase().includes(words))
            .slice(0, 8);
        show(list, found.length
            ? found.map((patient) => h('li', {}, h('button', { type: 'button', class: 'patient-row', onclick: () => open(patient) },
                h('strong', {}, `${patient.first_name} ${patient.last_name}`),
                h('span', { class: 'muted' }, patient.date_of_birth ? `Born ${patient.date_of_birth}` : `ID ${patient.id.slice(0, 8)}`))))
            : h('li', { class: 'muted' }, patients.length ? 'No patient has that name.' : 'No patients yet. Add your first one to begin.'));
    };
    fill('');
    return [
        patients.length > 3 && h('label', {}, 'Find a patient',
            h('input', { type: 'search', oninput: (event) => fill(event.target.value.trim().toLowerCase()) })),
        list,
        h('p', {}, h('button', { type: 'button', class: 'quiet', onclick: () => context.startNewPatient() }, me.role === 'doctor' ? 'Add a patient' : 'Create or join a record')),
    ];
}

// What needs a person today, counted from the record. Each line opens the list it counts. A count
// that couldn't be read says so; nothing here is ever a made-up number.
async function workItems(context) {
    const staff = (id) => canUse({ id, audience: 'staff' }, context);
    const today = new Date().toISOString().slice(0, 10);
    const [intakes, exceptions, board] = await Promise.all([
        staff('diagnofast') ? api('/api/diagnofast/intakes').catch(() => null) : undefined,
        staff('referrals') ? api('/api/addons/referrals/exceptions').catch(() => null) : undefined,
        staff('discharge') ? api('/api/addons/dischargecare/board').catch(() => null) : undefined,
    ]);
    const items = [];
    const count = (list, test) => (list === null ? null : list.filter(test).length);
    if (intakes !== undefined) {
        items.push(
            { key: 'urgent', icon: 'alert', tone: 'urgent', label: 'Urgent, not reviewed', zero: 'No urgent interviews waiting', href: '#/diagnofast/urgent_open', value: count(intakes, QUEUE_FILTERS.urgent_open[1]) },
            { key: 'waiting', icon: 'diagnofast', label: 'Waiting or answering', zero: 'Nobody is in an interview', href: '#/diagnofast/waiting', value: count(intakes, QUEUE_FILTERS.waiting[1]) },
            { key: 'review', icon: 'file', tone: 'warn', label: 'Reports to review', zero: 'Every report is reviewed', href: '#/diagnofast/review', value: count(intakes, QUEUE_FILTERS.review[1]) },
        );
    }
    if (exceptions !== undefined) {
        items.push({ key: 'referrals', icon: 'clock', tone: 'urgent', label: 'Overdue referrals', zero: 'No referral is overdue', href: '#/referrals/overdue',
            value: count(exceptions, (row) => row.respond_by < today) });
    }
    if (board !== undefined) {
        items.push({ key: 'tasks', icon: 'tasks', tone: 'warn', label: 'Overdue discharge tasks', zero: 'No discharge task is overdue', href: '#/discharge',
            value: board === null ? null : board.reduce((sum, row) => sum + (row.tasks_overdue || 0), 0) });
    }
    return items;
}

function workList(items) {
    if (!items.length) return null;
    return h('section', { class: 'sheet today', 'aria-labelledby': 'today-title' },
        h('h2', { id: 'today-title' }, 'Needs you today'),
        h('ul', { class: 'work-list' }, items.map((item) => {
            const none = item.value === 0;
            const unknown = item.value === null;
            return h('li', {}, h('a', {
                class: `work-item${none || unknown ? ' quiet-item' : ` ${item.tone || 'accent'}`}`,
                href: item.href,
                'data-count': item.key,
            },
            h('span', { class: 'work-icon', 'aria-hidden': 'true' }, icon(item.icon, 'q-icon')),
            h('span', { class: 'work-text' },
                h('span', { class: 'work-label' }, item.label),
                none ? h('span', { class: 'muted' }, item.zero) : unknown ? h('span', { class: 'muted' }, "Couldn't load this count") : null),
            none || unknown ? null : h('span', { class: 'work-count' }, String(item.value)),
            h('span', { class: 'row-chevron go', 'aria-hidden': 'true' })));
        })));
}

async function waitingRoom(context) {
    if (!canUse({ id: 'diagnofast', audience: 'staff' }, context)) return null;
    const intakes = await api('/api/diagnofast/intakes').catch(() => []);
    const waiting = intakes.slice(0, 5);
    return h('div', { class: 'sheet' },
        h('div', { class: 'section-head' }, h('h2', {}, 'Waiting room'),
            h('a', { href: '#/diagnofast' }, intakes.length > 5 ? `See all ${plural(intakes.length, 'patient')}` : 'Open DiagnoFast')),
        waiting.length
            ? h('div', { class: 'queue-list' }, waiting.map(queueRow))
            : emptyState('Nobody is waiting', 'Send a patient a DiagnoFast link to start their interview.'));
}

export async function renderHome(container, context) {
    const { me } = context;
    // Filled in once the counts arrive. If the page changes first, these are no longer on it.
    const rest = h('div', {});
    const today = h('div', {}, me.role === 'doctor' ? h('section', { class: 'sheet today' }, h('h2', {}, 'Needs you today'), loadingRows('Counting today\'s work…', 2)) : null);
    show(container,
        h('h1', {}, `Hello, ${me.first_name}`),
        h('p', { class: 'lede' }, me.role === 'doctor'
            ? 'Open a patient, and every tool stays with them as you move through the visit.'
            : 'Your record, your medicines and your care, in one place.'),
        today,
        rest);
    const [items, waiting] = await Promise.all([me.role === 'doctor' ? workItems(context) : [], waitingRoom(context)]);
    show(today, workList(items));
    show(rest,
        h('div', { class: 'columns' },
            h('div', { class: 'sheet' }, h('h2', {}, me.role === 'doctor' ? 'Your patients' : 'Your records'), patientFinder(context)),
            waiting),
        h('h2', {}, 'All tools'),
        toolList(context));
}

export function renderAccount(container, context) {
    const { me } = context;
    show(container,
        h('h1', {}, 'Account'),
        h('div', { class: 'sheet' },
            h('dl', { class: 'facts-list' },
                h('dt', {}, 'Name'), h('dd', {}, `${me.first_name} ${me.last_name}`),
                h('dt', {}, 'Email'), h('dd', {}, me.email),
                h('dt', {}, 'Account type'), h('dd', {}, me.role === 'doctor' ? 'Clinic staff' : 'Patient')),
            // On a phone the header has no room for "Sign out", so it lives here too.
            h('p', {}, h('button', { type: 'button', class: 'quiet', onclick: () => document.getElementById('sign-out').click() }, 'Sign out'))));
}
