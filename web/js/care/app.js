// The care workspace shell: who is signed in, which patient is open, and which tool shows.
import { act, api, form, h, loading, show, toast } from './ui.js';
import { STAGES, SWITCHED_TOOLS, canUse } from './catalogue.js';
import { renderAccount, renderHome } from './home.js';
import { renderInbox, renderOverview, renderTasks } from './overview.js';
import { leaveRecording, renderClinScribe } from './clinscribe.js';
import { renderLabLens } from './lablens.js';
import { renderCareFlow } from './careflow.js';
import { renderDiagnoFast } from './diagnofast.js';
import { renderPrescription } from './prescription.js';
import { renderReferrals } from './referrals.js';
import { renderDischarge } from './discharge.js';
import { renderGovernance } from './governance.js';
import { renderReminders } from './reminders.js';
import { renderSettings } from './settings.js';
import { icon, initials } from './icons.js';

const RENDERERS = {
    home: renderHome,
    overview: renderOverview,
    tasks: renderTasks,
    reminders: renderReminders,
    inbox: renderInbox,
    account: renderAccount,
    careflow: renderCareFlow,
    governance: renderGovernance,
    settings: renderSettings,
    diagnofast: renderDiagnoFast,
    clinscribe: renderClinScribe,
    lablens: renderLabLens,
    prescription: renderPrescription,
    referrals: renderReferrals,
    discharge: renderDischarge,
};
// Left off the rail, but still reachable by address: staff verification only happens on Governance.
const LABELS = { inbox: 'Inbox', account: 'Account', governance: 'Governance', tasks: 'Tasks', reminders: 'Reminders' };
const GROUPS = [
    { tools: [{ id: 'home', label: 'Home' }] },
    {
        title: 'This patient',
        tools: [
            { id: 'overview', label: 'Patient record' },
            { id: 'careflow', label: 'CareFlow' },
        ],
    },
    ...STAGES,
    {
        title: 'Manage',
        tools: [
            { id: 'settings', label: 'Settings', audience: 'staff' },
        ],
    },
];
const TOOLS = Object.fromEntries(GROUPS.flatMap((group) => group.tools).map((tool) => [tool.id, tool]));

const state = { me: null, patients: [], patient: null, config: { tools: [], defaults: {} } };
const main = document.getElementById('main');

function currentRoute() {
    const [name, detail] = window.location.hash.replace('#/', '').split('/');
    return { name: RENDERERS[name] ? name : 'home', detail };
}

function renderRail() {
    const active = currentRoute().name;
    const rail = document.getElementById('rail');
    show(rail,
        GROUPS.map((group) => {
            const links = group.tools
                .filter((tool) => canUse(tool, state))
                .map((tool) => h('a', { href: `#/${tool.id}`, 'aria-current': tool.id === active ? 'page' : null }, icon(tool.id), tool.label));
            return links.length ? h('div', {}, group.title && h('h2', {}, group.title), links) : null;
        }));
}

async function renderWristband() {
    const band = document.getElementById('wristband');
    const patient = state.patient;
    const picker = h('select', {
        'aria-label': 'Choose a patient',
        onchange: (event) => openPatient(event.target.value),
    },
    h('option', { value: '' }, state.patients.length ? (patient ? 'Switch patient' : 'Select a patient to begin') : 'No patients yet'),
    state.patients.map((item) => h('option', { value: item.id, selected: item.id === patient?.id }, `${item.first_name} ${item.last_name}`)));
    // A patient with only their own record has nobody to switch to. Caregivers can have several.
    const chooser = state.me.role === 'doctor' || state.patients.length > 1 ? picker : null;

    if (!patient) {
        show(band, h('span', { class: 'no-patient' }, 'No patient open'), chooser);
        return;
    }
    const allergies = await api(`/api/patients/${patient.id}/allergies`).catch(() => []);
    const active = allergies.filter((item) => item.status === 'active');
    const sex = patient.sex && patient.sex !== 'unknown' ? patient.sex : null;
    const facts = [sex, patient.date_of_birth && `Born ${patient.date_of_birth}`, `ID ${patient.id.slice(0, 8)}`]
        .filter(Boolean).join(' · ');
    const name = `${patient.first_name} ${patient.last_name}`;
    show(band,
        h('div', { class: 'who-block' },
            h('span', { class: 'initials', 'aria-hidden': 'true' }, initials(name)),
            h('span', { class: 'stack-lines' }, h('span', { class: 'name' }, name), h('span', { class: 'facts' }, facts))),
        active.length
            ? h('span', { class: 'allergy-band', title: active.map((item) => item.substance).join(', ') },
                icon('alert', 'nav-icon'), `Allergies: ${active.map((item) => item.substance).join(', ')}`)
            : h('span', { class: 'allergy-none' }, 'No allergies recorded'),
        chooser,
    );
}

function askConsent(detail) {
    const notice = h('div', { class: 'sheet alert-card' },
        h('h2', {}, 'Consent needed'),
        h('p', {}, detail.message),
        h('p', { class: 'muted' }, 'Record this only after the patient has agreed.'),
        h('div', { class: 'row' },
            h('button', {
                type: 'button',
                onclick: async () => {
                    const saved = await act(() => api(`/api/patients/${state.patient.id}/consents`, { method: 'POST', body: { purpose: detail.purpose } }), null, 'Consent recorded');
                    if (saved) render();
                },
            }, 'The patient agreed: record consent'),
            h('button', { type: 'button', class: 'quiet', onclick: () => notice.remove() }, 'Not now')));
    main.prepend(notice);
    notice.scrollIntoView({ block: 'center' });
}

let lastRoute = null;

// Keeps the scroll padding equal to the sticky header, whose height changes with the patient and width.
function trackStickyHeight() {
    const bar = document.querySelector('.topbar');
    if (!bar || !window.ResizeObserver) return;
    new ResizeObserver(() => {
        document.documentElement.style.scrollPaddingTop = `${bar.offsetHeight + 16}px`;
    }).observe(bar);
}

// After a route change, focus moves to the new page's heading so keyboard and screen reader users land on it.
function focusHeading() {
    const heading = main.querySelector('h1');
    const target = heading || main;
    if (heading) heading.tabIndex = -1;
    target.focus({ preventScroll: true });
}

async function render() {
    renderRail();
    const { name, detail } = currentRoute();
    main.dataset.tool = name;
    const routeChanged = window.location.hash !== lastRoute;
    lastRoute = window.location.hash;
    const label = TOOLS[name]?.label ?? LABELS[name];
    document.title = name === 'home' ? 'Diagnosia' : `${label}: Diagnosia`;
    loading(main);
    if (SWITCHED_TOOLS.includes(name) && !state.config.tools.includes(name)) {
        show(main, h('h1', {}, label), h('p', { class: 'empty' }, 'This tool is switched off. An administrator can turn it on in Settings.'));
        return;
    }
    try {
        await RENDERERS[name](main, {
            ...state,
            route: detail,
            reloadConfig,
            isClinician: state.patient?.relationship === 'clinician',
            isStaff: state.me.role === 'doctor',
            askConsent,
            refresh: render,
            reloadPatients,
            openPatient,
            startNewPatient,
        });
    } catch (error) {
        show(main, h('p', { class: 'error', role: 'alert' }, error.message));
    }
    if (routeChanged) focusHeading();
}

// The add-a-patient form is the patient record's empty state.
async function startNewPatient() {
    window.history.replaceState(null, '', '#/overview');
    await openPatient('');
}

async function reloadConfig() {
    state.config = await api('/api/platform/config');
}

async function reloadPatients() {
    state.patients = await api('/api/patients');
}

async function openPatient(patientId) {
    state.patient = state.patients.find((item) => item.id === patientId) || null;
    try {
        if (patientId) sessionStorage.setItem('care-patient', patientId);
        else sessionStorage.removeItem('care-patient');
    } catch (storageBlocked) { /* the page works without it */ }
    await renderWristband();
    await render();
}

// Urgent stops and requests for help from the waiting room. Every staff screen asks every few seconds,
// so an alert shows whatever page is open. The banner stays until someone marks it seen.
const ALERT_POLL_MS = 5000;
const shownAlerts = new Map();

async function refreshAlerts() {
    const found = await api('/api/diagnofast/alerts').catch(() => null);
    if (!found) return;
    const area = document.getElementById('alerts');
    const current = new Set(found.map((item) => item.id));
    for (const [id, node] of shownAlerts) {
        if (!current.has(id)) { node.remove(); shownAlerts.delete(id); }
    }
    for (const item of found) {
        if (shownAlerts.has(item.id)) continue;
        const seen = h('button', { type: 'button', class: 'quiet' }, 'Mark as seen');
        const help = item.kind === 'help' || /help/i.test(item.kind || '');
        const node = h('div', { class: `staff-alert ${help ? 'help' : 'urgent'}` },
            icon(help ? 'help' : 'alert', 'alert-icon'),
            h('span', {}, item.body ? `${item.title}: ${item.body}` : item.title),
            h('span', { class: 'alert-actions' },
                h('a', { href: `#/diagnofast/${item.intake_id}` }, 'Open'),
                seen));
        seen.addEventListener('click', async () => {
            await api(`/api/notifications/${item.id}/read`, { method: 'POST' }).catch(() => {});
            refreshAlerts();
            refreshInbox();
        });
        shownAlerts.set(item.id, node);
        area.append(node);
    }
}

async function refreshInbox() {
    const items = await api('/api/notifications').catch(() => []);
    const unread = items.filter((item) => !item.read_at).length;
    document.getElementById('inbox-count').textContent = unread || '';
}

document.getElementById('sign-out').addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    try {
        sessionStorage.clear();
    } catch (storageBlocked) { /* nothing to clear */ }
    window.location.href = 'index.html';
});

// The tools menu is a drawer on narrow screens. Escape and the scrim close it.
const sidebar = document.getElementById('sidebar');
const scrim = document.getElementById('scrim');
const navButton = document.getElementById('open-nav');
navButton.append(icon('menu', 'nav-icon'));
function setNav(open) {
    sidebar.classList.toggle('open', open);
    scrim.hidden = !open;
    navButton.setAttribute('aria-expanded', String(open));
    if (open) sidebar.querySelector('a')?.focus();
}
navButton.addEventListener('click', () => setNav(!sidebar.classList.contains('open')));
scrim.addEventListener('click', () => setNav(false));
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && sidebar.classList.contains('open')) {
        setNav(false);
        navButton.focus();
    }
});

// Light by default; staff can choose dark or follow the device. theme.js applied it before paint.
const THEMES = [['light', 'sun', 'Light'], ['dark', 'moon', 'Dark'], ['system', 'system', 'Same as device']];
const themeButton = document.getElementById('theme-toggle');
function drawThemeButton() {
    const choice = window.diagnosiaTheme?.get() || 'light';
    const [, iconName, label] = THEMES.find(([value]) => value === choice) || THEMES[0];
    const next = THEMES[(THEMES.findIndex(([value]) => value === choice) + 1) % THEMES.length];
    show(themeButton, icon(iconName, 'nav-icon'));
    themeButton.setAttribute('aria-label', `Colour theme: ${label}. Switch to ${next[2].toLowerCase()}`);
    themeButton.title = `Theme: ${label}`;
}
themeButton.addEventListener('click', () => {
    const choice = window.diagnosiaTheme?.get() || 'light';
    const next = THEMES[(THEMES.findIndex(([value]) => value === choice) + 1) % THEMES.length][0];
    window.diagnosiaTheme?.set(next);
    drawThemeButton();
});
drawThemeButton();

window.addEventListener('hashchange', async () => {
    setNav(false);
    await leaveRecording(null);
    render();
    refreshInbox();
});

const STATUS_WORDS = {
    pending_verification: 'Your account is waiting for verification. Staff tools stay closed until an organization administrator confirms your credentials.',
    rejected: 'Your account was not verified. Contact your organization administrator.',
};

// Unverified staff see only this: the server refuses everything else anyway.
async function renderOnboarding() {
    const profile = await api('/api/practitioner');
    show(main,
        h('h1', {}, 'Account verification'),
        h('div', { class: 'banner' }, STATUS_WORDS[state.me.account_status]),
        h('div', { class: 'columns' },
            h('div', { class: 'sheet' },
                h('h2', {}, 'I have an invitation'),
                form([{ name: 'code', label: 'Invitation code', required: true }], 'Join organization', async ({ code }) => {
                    await act(() => api('/api/staff/invitations/accept', { method: 'POST', body: { code } }), null, 'Invitation accepted. Your administrator still needs to verify you.');
                })),
            h('div', { class: 'sheet' },
                h('h2', {}, 'About you'),
                h('p', { class: 'muted' }, 'Your administrator checks this against evidence. Saying it here proves nothing.'),
                form(
                    [
                        { name: 'profession', label: 'Profession', type: 'select', value: profile.profession, options: ['doctor', 'nurse', 'midwife', 'pharmacist', 'coordinator', 'community_health_worker', 'laboratory_professional'].map((item) => [item, item.replaceAll('_', ' ')]) },
                        { name: 'speciality', label: 'Speciality', value: profile.speciality },
                        { name: 'registration_number', label: 'Registration number', value: profile.registration_number },
                    ],
                    'Save details',
                    async (values) => {
                        await act(() => api('/api/practitioner', { method: 'PUT', body: values }), null, 'Details saved');
                    },
                ))));
}

async function start() {
    trackStickyHeight();
    state.me = await api('/api/me');
    const myName = `${state.me.first_name} ${state.me.last_name}`;
    show(document.getElementById('who'),
        h('span', { class: 'initials', 'aria-hidden': 'true' }, initials(myName)),
        h('span', { class: 'account-name' }, myName));
    document.getElementById('who').setAttribute('aria-label', `Your account: ${myName}`);
    if (state.me.role === 'doctor' && state.me.account_status !== 'verified') {
        await renderOnboarding();
        return;
    }
    await reloadConfig();
    // Judge mode (a public demo): say the patients are made up, and open the demo chart so each tool works at once.
    document.getElementById('demo-note').hidden = !state.config.judge_mode;
    await reloadPatients();
    let remembered = null;
    try {
        remembered = sessionStorage.getItem('care-patient');
    } catch (storageBlocked) { /* the page works without it */ }
    const first = state.me.role === 'patient'
        ? state.patients.find((item) => item.relationship === 'self')
        : state.patients.find((item) => item.id === state.config.judge_patient_id);
    await openPatient(state.patients.some((item) => item.id === remembered) ? remembered : first?.id ?? '');
    refreshInbox();
    if (state.me.role === 'doctor') {
        refreshAlerts();
        setInterval(refreshAlerts, ALERT_POLL_MS);
    }
}

start().catch((error) => {
    if (error.status !== 401) toast(error.message, true);
});
