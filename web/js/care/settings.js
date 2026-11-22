// Settings: what an administrator can change without touching code, grouped by what it is for.
// Each change saves on its own and says so beside the control: saving, saved, or what went wrong.
import { act, api, badge, emptyState, form, h, show, tabs, toast } from './ui.js';
import { icon } from './icons.js';

// The server's sections, gathered into purposes. A section not listed here still shows, under Tools.
const GROUPS = [
    { key: 'ai', label: 'AI and models', sections: ['AI providers', 'AI models'], keys: ['groq', 'gemini'],
        intro: 'Which AI services answer, in which order, and with which model for each tool.' },
    { key: 'speech', label: 'Speech and voices', sections: ['Sarvam AI'], only: (setting) => setting.key !== 'sarvam.enabled' && setting.key !== 'sarvam.llm',
        extra: ['ai.model.transcription', 'clinscribe.default_language'], keys: ['sarvam'],
        intro: 'Speech to text, the voices that read questions aloud, and translation. Sarvam settings apply only while its add-on runs.' },
    { key: 'addons', label: 'Add-ons', sections: ['DiagnoFast add-ons', 'ReferralLoop add-ons', 'Medicine checks', 'Neo4j'],
        extra: ['sarvam.enabled', 'sarvam.llm'], keys: ['neo4j'],
        intro: 'Hackathon add-ons. Each starts off, and off means the app behaves exactly as before.' },
    { key: 'tools', label: 'Tools', sections: ['Tools', 'ClinScribe', 'Prescription Analyzer', 'LabLens', 'ReferralLoop', 'Reminders'],
        intro: 'Which tools appear in the workspace, and how each one behaves.' },
    { key: 'held', label: 'Held features', sections: ['Held for regulatory review'],
        intro: 'Features held until a written regulatory view arrives. Off means the server refuses them and nothing is stored or shown.' },
    { key: 'account', label: 'Account and security', sections: [],
        intro: 'Your own account, and how the workspace keeps sessions safe.' },
];
const MOVED = new Set(GROUPS.flatMap((group) => group.extra || []));

const KEY_HELP = {
    groq: 'A free key from console.groq.com. It also runs speech to text and the English voice.',
    gemini: 'A free key from aistudio.google.com. It answers when Groq fails, or takes turns with it. It has no speech.',
    sarvam: 'A key from dashboard.sarvam.ai, for Hindi and English speech, voice and translation. Used only with the Sarvam switch on and its sign-off recorded.',
    neo4j: 'The password of the local Neo4j server, for DiagnoFast graphs. Used only with the Neo4j switch on.',
};

let currentGroup = 'ai';

// One line under each control: what happened to the last change. Announced politely.
function feedback() {
    const line = h('p', { class: 'setting-feedback', role: 'status', 'aria-live': 'polite' });
    const say = (kind, text) => {
        line.className = `setting-feedback ${kind}`;
        line.replaceChildren(kind === 'saved' ? icon('check', 'feedback-icon') : kind === 'error' ? icon('alert', 'feedback-icon') : '', text);
    };
    return { line, say };
}

function control(setting, canEdit, context, say, locked) {
    let last = setting.value;
    const save = async (value, element) => {
        say('saving', 'Saving…');
        try {
            await api(`/api/platform/settings/${encodeURIComponent(setting.key)}`, { method: 'PUT', body: { value } });
            last = value;
            setting.value = value;
            say('saved', 'Saved. It applies straight away.');
            await context.reloadConfig();
            // Switching a tool on or off changes the menu, so the page is drawn again.
            if (setting.key.startsWith('tools.')) {
                toast(`${setting.label} ${value ? 'switched on' : 'switched off'}`);
                context.refresh();
            }
        } catch (error) {
            say('error', `Not saved: ${error.message}`);
            // Put the control back to what is really stored.
            if (element.type === 'checkbox') element.checked = last;
            else element.value = Array.isArray(last) ? last.join('\n') : last;
        }
    };
    const common = { disabled: !canEdit, 'aria-label': setting.label, id: `setting-${setting.key}` };
    if (locked) common['aria-describedby'] = `setting-${setting.key}-lock`;
    if (setting.type === 'bool') {
        // The label around it makes the whole 44px square a target on touch screens.
        return h('label', { class: 'switch-hit' },
            h('input', { ...common, type: 'checkbox', role: 'switch', class: 'switch', checked: setting.value, onchange: (event) => save(event.target.checked, event.target) }));
    }
    if (setting.type === 'choice' || setting.type === 'model') {
        const known = setting.choices.includes(setting.value) ? setting.choices : [setting.value, ...setting.choices];
        return h('select', { ...common, onchange: (event) => save(event.target.value, event.target) },
            known.map((choice) => h('option', { value: choice, selected: choice === setting.value }, choice)));
    }
    if (setting.type === 'int') {
        return h('input', { ...common, type: 'number', min: setting.min, max: setting.max, value: setting.value, onchange: (event) => save(Number(event.target.value), event.target) });
    }
    if (setting.type === 'list') {
        return h('textarea', {
            ...common,
            placeholder: 'One heading per line',
            value: setting.value.join('\n'),
            onchange: (event) => save(event.target.value.split('\n').map((item) => item.trim()).filter(Boolean), event.target),
        });
    }
    return h('input', { ...common, type: 'text', value: setting.value, maxLength: setting.max_length, onchange: (event) => save(event.target.value, event.target) });
}

function settingRow(setting, data, context, group) {
    const { line, say } = feedback();
    // Why a switch that is on still won't run: a missing key, a sign-off, or real patient data.
    const needs = data.addon_blockers?.[setting.key] || [];
    const held = group.key === 'held';
    const lockText = needs.length ? needs.join('. ') : held ? 'Held for regulatory review. Switch on only with a written regulatory view.' : '';
    const holder = control(setting, data.can_edit, context, say, Boolean(lockText));
    const input = holder.matches('input, select, textarea') ? holder : holder.querySelector('input');
    const isSwitch = setting.type === 'bool';
    const changed = JSON.stringify(setting.value) !== JSON.stringify(setting.default);
    return h('div', { class: `setting-row${isSwitch ? ' is-switch' : ''}` },
        h('div', { class: 'setting-text' },
            h('label', { for: input.id }, setting.label),
            h('span', { class: 'setting-key' }, setting.key, changed ? h('span', { class: 'setting-changed' }, ' · changed from the default') : null),
            lockText ? h('p', { class: `setting-lock ${needs.length ? 'warn' : ''}`, id: `setting-${setting.key}-lock` },
                icon('lock', 'feedback-icon'), h('span', {}, needs.length && setting.value ? `On, but not running. ${lockText}.` : needs.length ? `${lockText}.` : lockText)) : null),
        h('div', { class: 'setting-control' }, holder),
        line);
}

function keyPanel(provider, key, canEdit, context) {
    const status = key.configured
        ? badge(key.source === 'environment' ? 'Set in the server environment' : `Saved, ending ${key.last_four}`, 'good')
        : badge('Not set', 'bad');
    const endpoint = `/api/platform/ai-key?provider=${provider}`;
    const entry = canEdit && key.source !== 'environment' ? form(
        [{ name: 'key', label: `${key.label} API key`, type: 'password', required: true }],
        'Save key',
        async (values, element) => {
            const saved = await act(() => api(endpoint, { method: 'PUT', body: values }), context, 'Key saved');
            if (saved) {
                element.reset();
                await context.reloadConfig();
                context.refresh();
            }
        },
        { inline: true },
    ) : null;
    return h('div', { class: 'key-row' },
        h('div', { class: 'setting-text' },
            h('strong', {}, key.label),
            h('p', { class: 'muted' }, `${KEY_HELP[provider]} It is stored encrypted and never shown again.`)),
        h('div', { class: 'key-state' }, status,
            key.source === 'settings' && canEdit ? h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    await act(() => api(endpoint, { method: 'DELETE' }), context, 'Key removed');
                    await context.reloadConfig();
                    context.refresh();
                },
            }, 'Remove key') : null),
        entry ? h('div', { class: 'key-entry' }, entry) : null);
}

function accountPanel(context) {
    return h('div', { class: 'settings-block' },
        h('div', { class: 'key-row' },
            h('div', { class: 'setting-text' },
                h('strong', {}, `${context.me.first_name} ${context.me.last_name}`),
                h('p', { class: 'muted' }, 'Your name, email and sign-out are on your account page.')),
            h('div', { class: 'key-state' }, h('a', { class: 'button quiet', href: '#/account' }, 'Open your account'))),
        h('div', { class: 'key-row' },
            h('div', { class: 'setting-text' },
                h('strong', {}, 'Sessions'),
                h('p', { class: 'muted' }, 'A session ends after 30 idle minutes. Timed refreshes do not keep it open; typing and clicking do.'))),
        h('div', { class: 'key-row' },
            h('div', { class: 'setting-text' },
                h('strong', {}, 'Every change is logged'),
                h('p', { class: 'muted' }, 'Each setting change is written to the audit log with who made it and when. Keys are stored encrypted and never shown again.'))));
}

export async function renderSettings(container, context) {
    const data = await api('/api/platform/settings');
    const placed = new Set();
    const groupSettings = (group) => {
        const list = data.settings.filter((setting) => (group.sections.includes(setting.section) && !MOVED.has(setting.key) && (!group.only || group.only(setting)))
            || (group.extra || []).includes(setting.key));
        list.forEach((setting) => placed.add(setting.key));
        return list;
    };
    const grouped = GROUPS.map((group) => ({ ...group, settings: groupSettings(group) }));
    // Anything new the server adds still appears somewhere.
    grouped.find((group) => group.key === 'tools').settings.push(...data.settings.filter((setting) => !placed.has(setting.key)));
    const todo = data.setup.filter((step) => !step.done);

    const panel = h('div', {});
    const switcher = h('div', {});
    const draw = (key) => {
        currentGroup = key;
        const group = grouped.find((item) => item.key === key) || grouped[0];
        show(switcher, tabs(grouped.map((item) => ({
            key: item.key,
            label: item.label,
            alert: item.settings.some((setting) => setting.value && (data.addon_blockers?.[setting.key] || []).length),
        })), group.key, (next) => {
            draw(next);
            switcher.querySelector(`[data-tab="${next}"]`)?.focus();
        }, 'Settings groups'));
        const bySection = {};
        group.settings.forEach((setting) => { (bySection[setting.section] ||= []).push(setting); });
        show(panel, h('div', { class: 'tab-panel', role: 'tabpanel', 'aria-label': group.label },
            h('p', { class: 'muted group-intro' }, group.intro),
            (group.keys || []).length ? h('section', { class: 'sheet settings-block' },
                h('h2', {}, group.keys.length === 1 ? 'Key' : 'Keys'),
                group.keys.map((provider) => keyPanel(provider, data.ai_keys[provider], data.can_edit, context))) : null,
            Object.entries(bySection).map(([title, settings]) => h('section', { class: 'sheet settings-block' },
                h('h2', {}, title),
                settings.map((setting) => settingRow(setting, data, context, group)))),
            group.key === 'account' ? accountPanel(context) : null,
            !group.settings.length && !(group.keys || []).length && group.key !== 'account' ? emptyState('Nothing to set here', '') : null));
    };

    show(container,
        h('h1', {}, 'Settings'),
        h('p', { class: 'lede' }, data.can_edit ? 'Changes apply straight away, and each is logged.' : 'Only an administrator of a verified organization can change these.'),
        h('section', { class: `setup-strip ${todo.length ? 'warn' : 'good'}`, 'aria-label': 'Getting started' },
            h('strong', {}, todo.length ? `Getting started: ${todo.length} to do` : 'Set up: everything needed is in place'),
            h('ul', {}, data.setup.map((step) => h('li', { class: step.done ? 'done' : 'todo' },
                icon(step.done ? 'check' : 'clock', 'feedback-icon'),
                h('span', {}, step.name, step.done ? h('span', { class: 'visually-hidden' }, ': done') : null),
                step.done ? null : h('span', { class: 'muted' }, ` ${step.help}`))))),
        switcher,
        panel,
    );
    draw(currentGroup);
    return undefined;
}
