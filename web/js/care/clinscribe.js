// ClinScribe: capture a consultation, review the draft, sign the note.
import { act, api, badge, emptyState, form, h, listRow, plural, rowList, show, stateTrack, toast, when } from './ui.js';
import { icon } from './icons.js';
import { needPatient } from './overview.js';

const BASE = '/api/addons/clinscribe';
const CHUNK_MS = 25000; // the transcript updates about this often
const VERDICT_WORDS = {
    supported: 'Matches the transcript',
    uncertain: 'Please check',
    unsupported: 'Does not match the transcript',
    // The rules can't compare English with a transcript in another language. This is not a pass.
    not_checked: 'Not checked: compare with the source line',
    clinician_entered: 'Written by you',
};

const MIN_CHUNK_BYTES = 2000;
const MIC_PROBLEMS = {
    NotAllowedError: 'Microphone permission was refused. Allow it in the browser, or type the lines below.',
    NotFoundError: 'No microphone was found. Connect one, or type the lines below.',
    NotReadableError: 'The microphone is in use by another app. Close it, or type the lines below.',
    SecurityError: 'This page is not allowed to use the microphone. It needs HTTPS.',
};

let recorder = null;

export function micProblem(error) {
    return MIC_PROBLEMS[error?.name] || 'The microphone could not start. Type the lines below instead.';
}

// Leaving the tool mid-recording must not leave the record saying it's still on.
export async function leaveRecording(context) {
    const sessionId = await stopMicrophone();
    if (sessionId) {
        await act(() => api(`${BASE}/sessions/${sessionId}/state`, { method: 'POST', body: { state: 'paused' } }), context);
    }
}

// Ends capture and waits for the last chunk, so the final words aren't lost.
async function stopMicrophone() {
    const current = recorder;
    if (!current) return null;
    recorder = null;
    current.active = false;
    clearTimeout(current.timer);
    const finished = new Promise((resolve) => { current.finish = resolve; });
    if (current.media?.state === 'recording') current.media.stop();
    else current.finish();
    await finished;
    current.stream?.getTracks().forEach((track) => track.stop());
    await Promise.allSettled(current.uploads);
    return current.sessionId;
}

async function startMicrophone(session, speakerControl, handlers, context) {
    // Claimed before the slow permission step, so Stop works while it is still opening.
    const current = { stream: null, active: true, media: null, timer: null, uploads: [], finish: null, sessionId: session.id };
    recorder = current;
    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (problem) {
        if (recorder === current) recorder = null;
        throw problem;
    }
    if (!current.active) {
        stream.getTracks().forEach((track) => track.stop());
        return;
    }
    current.stream = stream;
    const upload = async (blob) => {
        const data = new FormData();
        data.append('audio', blob, 'chunk.webm');
        data.append('speaker', speakerControl.value);
        const saved = await act(() => api(`${BASE}/sessions/${session.id}/transcribe`, { method: 'POST', form: data, active: true }), context);
        if (saved === undefined) handlers.onLost();
        else if (saved.segment) handlers.onSegment();
    };
    const nextChunk = () => {
        if (!current.active) return;
        const media = new MediaRecorder(stream);
        const parts = [];
        media.ondataavailable = (event) => parts.push(event.data);
        media.onstop = () => {
            const blob = new Blob(parts, { type: media.mimeType || 'audio/webm' });
            nextChunk();
            if (blob.size >= MIN_CHUNK_BYTES) current.uploads.push(upload(blob));
            if (!current.active) current.finish?.();
        };
        current.media = media;
        media.start();
        current.timer = setTimeout(() => media.state === 'recording' && media.stop(), CHUNK_MS);
    };
    nextChunk();
}

function transcriptView(session) {
    const list = h('div', { class: 'transcript sheet', 'aria-live': 'polite' });
    const fill = (segments) => {
        show(list, ...(segments.length
            ? segments.map((segment) => h('div', {},
                h('span', { class: 'who' }, `Line ${segment.sequence}, ${segment.speaker}`),
                segment.text))
            : [h('p', { class: 'muted' }, 'Lines appear here as they are transcribed or typed.')]));
        list.scrollTop = list.scrollHeight;
    };
    fill(session.segments);
    return { list, fill };
}

// The four states of a consultation, in order. Each state shows one primary action.
const STAGES = [['record', 'Record'], ['transcript', 'Check the transcript'], ['draft', 'Review the draft'], ['signed', 'Signed']];

async function renderSession(area, session, context, showNotes, setStage) {
    const speaker = h('select', { 'aria-label': 'Who is speaking' },
        ['unknown', 'clinician', 'patient', 'other'].map((name) => h('option', { value: name }, name === 'unknown' ? 'Speaker not set' : name)));
    const { list, fill } = transcriptView(session);
    const reload = async () => fill((await api(`${BASE}/sessions/${session.id}`)).segments);

    const warning = h('div', { class: 'banner danger', id: 'mic-warning', hidden: true });
    const warn = (message) => {
        warning.textContent = message;
        warning.hidden = false;
    };
    // Audio that never became text. The server keeps the count, so it survives a reload; a chunk
    // that never reached the server (no network) is added here.
    let lost = session.chunks_lost || 0;
    const lostBadge = h('span', { id: 'chunks-lost', class: 'status bad', role: 'status', hidden: true });
    const showLost = () => {
        lostBadge.hidden = lost === 0;
        lostBadge.textContent = `${plural(lost, 'chunk')} lost`;
    };
    showLost();
    const lostChunk = async () => {
        const counted = (await api(`${BASE}/sessions/${session.id}`).catch(() => null))?.chunks_lost ?? 0;
        lost = Math.max(counted, lost + 1);
        showLost();
        warn(`${plural(lost, 'part')} of this recording could not be transcribed. Type what was missed below.`);
    };
    // Shows the session again from the server: after "Stop and finish" the record controls go.
    const reopen = async () => renderSession(area, await api(`${BASE}/sessions/${session.id}`), context, showNotes, setStage);

    const state = h('div', { class: 'recording' }, h('span', { class: 'dot' }), h('span', {}));
    // Start and Pause share one place: whichever is possible now is the primary action.
    const startButton = h('button', {
        type: 'button',
        id: 'start-recording',
        class: 'primary-lg',
        onclick: async () => {
            if (recorder) return;
            if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
                warn('This browser cannot record. Type the lines below instead.');
                return;
            }
            // The server checks consent first, so the microphone never opens without it.
            if (!(await setState('recording'))) return;
            try {
                await startMicrophone(session, speaker, { onSegment: reload, onLost: lostChunk }, context);
            } catch (problem) {
                await setState('paused');
                warn(micProblem(problem));
            }
        },
    }, icon('mic', 'button-icon'), 'Start recording');
    const pauseButton = h('button', { type: 'button', class: 'primary-lg', onclick: async () => { await stopMicrophone(); await setState('paused'); } }, 'Pause');
    const paint = (name) => {
        state.classList.toggle('on', name === 'recording');
        state.lastChild.textContent = { recording: 'Recording. The patient has been told.', paused: 'Not recording', stopped: 'Session ended' }[name];
        startButton.hidden = name === 'recording';
        pauseButton.hidden = name !== 'recording';
    };
    const setState = async (name) => {
        const changed = await act(() => api(`${BASE}/sessions/${session.id}/state`, { method: 'POST', body: { state: name } }), context);
        if (!changed) return false;
        session.state = name;
        paint(name);
        return true;
    };
    paint(session.state);

    const ended = session.state === 'stopped';
    const typed = form(
        [{ name: 'text', label: ended ? 'Something the recording missed' : 'Type a line, for example if audio failed', type: 'textarea', required: true }],
        ended ? 'Add a missed line' : 'Add line',
        async ({ text }, element) => {
            // The server takes a line for an ended session only when it is marked as a missed one.
            const body = { text, speaker: speaker.value, missed_line: session.state === 'stopped' };
            const added = await act(() => api(`${BASE}/sessions/${session.id}/segments`, { method: 'POST', body }), context);
            if (!added) return;
            element.reset();
            reload();
        },
    );
    typed.querySelector('button[type="submit"]').classList.add('quiet');
    const heading = h('div', { class: 'section-head' },
        h('h2', {}, ended ? 'Check the transcript' : 'Record the consultation'),
        h('p', { class: 'muted' }, `Started ${when(session.started_at)}`));

    if (!ended) {
        setStage('record');
        show(area, h('section', { class: 'sheet stage-panel' },
            heading,
            h('div', { class: 'row' }, state, lostBadge),
            h('div', { class: 'row record-controls' },
                startButton,
                pauseButton,
                h('button', { type: 'button', class: 'quiet', onclick: async () => { await stopMicrophone(); if (await setState('stopped')) await reopen(); } }, 'Stop and finish'),
                h('label', { class: 'inline-label' }, 'Speaker', speaker)),
            warning,
            h('h3', {}, 'Transcript so far'),
            list,
            h('details', { class: 'quiet-details' }, h('summary', {}, 'Type a line instead'), typed),
            h('p', { class: 'muted' }, 'When the consultation is over, press Stop and finish. You can then check the transcript and draft the note.')));
        return;
    }

    setStage('transcript');
    const draft = form(
        [{
            name: 'template',
            label: 'Note format',
            type: 'select',
            options: [['soap', 'SOAP'], ['history_physical', 'History and physical'], ...(context.config.defaults.clinscribe_custom_headings.length ? [['custom', 'Our clinic format']] : [])],
        }],
        'Draft the note',
        async (values) => {
            if (values.template === 'custom') values.custom_headings = context.config.defaults.clinscribe_custom_headings;
            try {
                const note = await api(`${BASE}/sessions/${session.id}/draft-note`, { method: 'POST', body: values });
                toast('Draft ready');
                showNotes(note.id);
            } catch (error) {
                // A session has one draft at a time. Show the one that is already there.
                if (error.detail?.code === 'draft_exists') {
                    toast(error.detail.message);
                    showNotes(error.detail.note_id);
                } else {
                    await act(() => { throw error; }, context);
                }
            }
        },
        { inline: true },
    );
    draft.querySelector('button[type="submit"]').classList.add('primary-lg');
    show(area, h('section', { class: 'sheet stage-panel' },
        heading,
        h('div', { class: 'row' }, state, lostBadge),
        warning,
        list,
        h('details', { class: 'quiet-details' }, h('summary', {}, 'Add a line the recording missed'),
            h('label', { class: 'inline-label' }, 'Speaker', speaker), typed),
        h('div', { class: 'action-bar' },
            h('p', { class: 'action-note' }, 'Read the transcript, add anything it missed, then draft the note. The draft is not part of the record until you sign it.'),
            draft)));
}

const FLAGGED = ['uncertain', 'unsupported', 'not_checked'];
// Lines the clinician has ticked as checked, kept while a note is re-drawn after a save.
const ticked = new Set();

// The words a statement rests on, shown beside it so the two can be compared, in their own language.
function sourceLines(statement) {
    if (!statement.sources?.length) return null;
    return h('div', { class: 'source-lines' },
        h('span', { class: 'muted' }, statement.sources.length === 1 ? 'Source line' : 'Source lines'),
        statement.sources.map((source) => h('blockquote', { lang: source.language.slice(0, 2) },
            h('span', { class: 'who', lang: 'en' }, `Line ${source.line}, ${source.speaker}`),
            source.text)));
}

function statementEditor(statement, section_) {
    const check = statement.check || {};
    const flagged = FLAGGED.includes(check.verdict);
    const box = h('textarea', { 'aria-label': `Statement in ${section_}`, value: statement.text });
    // One tick for each flagged line. Changing the words makes it a new line, so its tick goes.
    const tick = flagged ? h('input', { type: 'checkbox', checked: ticked.has(statement.id), 'data-statement': statement.id }) : null;
    tick?.addEventListener('change', () => (tick.checked ? ticked.add(statement.id) : ticked.delete(statement.id)));
    box.addEventListener('input', () => {
        if (!tick || box.value.trim() === statement.text) return;
        tick.checked = false;
        ticked.delete(statement.id);
    });
    return {
        box,
        id: statement.id,
        original: statement.text,
        tick,
        element: h('div', { class: `statement verdict-${check.verdict}`, style: 'margin:8px 0' },
            h('div', {},
                box,
                h('div', { class: 'row muted' },
                    flagged ? h('mark', {}, VERDICT_WORDS[check.verdict]) : h('span', {}, VERDICT_WORDS[check.verdict]),
                    check.evidence?.length ? h('span', {}, `Transcript ${check.evidence.length === 1 ? 'line' : 'lines'} ${check.evidence.join(', ')}`) : null,
                    h('span', {}, statement.origin === 'patient_statement' ? 'Patient said' : statement.origin === 'ai_summary' ? 'AI summary' : 'Clinician said')),
                check.reasons?.length ? h('ul', { class: 'reasons' }, check.reasons.map((reason) => h('li', {}, reason))) : null,
                tick ? h('label', { class: 'tick' }, tick, 'I have checked this line') : null),
            sourceLines(statement)),
    };
}

function renderNote(area, note, context, afterChange, setStage) {
    const content = note.content;
    if (note.status === 'approved') {
        setStage('signed');
        show(area,
            h('section', { class: 'sheet locked-note', 'aria-label': 'Signed note, locked' },
                h('div', { class: 'section-head' }, h('h2', {}, 'Signed note'), h('p', { class: 'muted' }, note.template.toUpperCase())),
                h('p', { class: 'lock-line' }, icon('lock', 'lock-icon'), `Signed ${when(note.approved_at)}. Locked: a signed note can't be changed.`),
                content.sections.map((part) => [
                    h('h3', {}, part.heading),
                    part.statements.length ? part.statements.map((line) => h('p', {}, line.text)) : h('p', { class: 'muted' }, 'Nothing recorded.'),
                ]),
                h('div', { class: 'row' },
                    h('a', { class: 'button quiet', href: `${BASE}/notes/${note.id}/fhir`, download: `note-${note.id.slice(0, 8)}.json` }, 'Export as FHIR'))),
        );
        return;
    }
    setStage('draft');
    const editors = content.sections.map((part) => ({
        heading: part.heading,
        lines: part.statements.map((statement) => statementEditor(statement, part.heading)),
    }));
    const collect = () => ({
        sections: editors.map((part) => ({
            heading: part.heading,
            statements: part.lines.map((line) => ({ text: line.box.value.trim() })).filter((line) => line.text),
        })),
    });
    const save = () => act(() => api(`${BASE}/notes/${note.id}`, { method: 'PATCH', body: collect() }), context, 'Saved');
    const flaggedIds = (content_) => content_.sections.flatMap((part) => part.statements).filter((line) => FLAGGED.includes(line.check?.verdict)).map((line) => line.id);
    show(area,
        h('div', { class: 'section-head' }, h('h2', {}, 'Review the draft'), h('p', { class: 'muted' }, `Drafted by ${note.model}, prompt ${note.prompt_version}`)),
        h('div', { class: 'banner warn' }, 'This is an AI draft and not part of the record until you sign it. Highlighted lines need your eye.'),
        h('p', { class: 'muted' }, note.open_flags ? `${plural(note.open_flags, 'line')} to check.` : 'No lines flagged. Read it through before signing.'),
        note.chunks_lost ? h('div', { class: 'banner danger' }, `${plural(note.chunks_lost, 'chunk')} lost: that much of the recording could not be transcribed, so this draft may be missing what was said then.`) : null,
        editors.map((part) => h('section', { class: 'sheet note-part' },
            h('h3', {}, part.heading),
            part.lines.length ? part.lines.map((line) => line.element) : h('p', { class: 'muted' }, 'Nothing said on this.'),
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: (event) => {
                    const line = statementEditor({ text: '', check: { verdict: 'clinician_entered' } }, part.heading);
                    part.lines.push(line);
                    event.target.before(line.element);
                },
            }, 'Add a line'))),
        content.missing_information?.length
            ? h('div', {}, h('h3', {}, 'Not in the transcript'), h('ul', {}, content.missing_information.map((item) => h('li', {}, item))))
            : null,
        h('div', { class: 'action-bar sticky' },
            h('p', { class: 'action-note' }, note.open_flags
                ? `Tick "I have checked this line" on each of the ${plural(note.open_flags, 'highlighted line')} before signing.`
                : 'Signing adds this note to the record and locks it.'),
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => {
                    await act(() => api(`${BASE}/notes/${note.id}/discard`, { method: 'POST' }), context, 'Draft discarded');
                    afterChange(null);
                },
            }, 'Discard draft'),
            h('button', {
                type: 'button',
                class: 'quiet',
                onclick: async () => { if (await save()) afterChange(note.id); },
            }, 'Save changes'),
            h('button', {
                type: 'button',
                class: 'primary-lg',
                onclick: async () => {
                    const saved = await save();
                    if (!saved) return;
                    // Saving checks typed lines again, so the flags are read from what was saved. Each
                    // one needs its own tick: a flag raised by this save is shown before anything is signed.
                    const open = flaggedIds(saved.content).filter((id) => !ticked.has(id));
                    if (open.length) {
                        toast(`${plural(open.length, 'highlighted line')} still to check. Tick each one after comparing it, then sign.`, true);
                        afterChange(note.id);
                        return;
                    }
                    const acknowledged = flaggedIds(saved.content);
                    const signed = await act(() => api(`${BASE}/notes/${note.id}/approve`, { method: 'POST', body: { acknowledged } }), context, 'Note signed');
                    if (signed) afterChange(note.id);
                },
            }, icon('lock', 'button-icon'), 'Sign note')),
    );
}

export async function renderClinScribe(container, context) {
    await leaveRecording(context);
    const { patient, refresh } = context;
    if (!patient) return needPatient(container);
    const [encounters, sessions, notes] = await Promise.all([
        api(`/api/patients/${patient.id}/encounters`),
        api(`${BASE}/patients/${patient.id}/sessions`),
        api(`${BASE}/patients/${patient.id}/notes`),
    ]);
    const area = h('div', { class: 'stage-area' });
    const track = h('div', {});
    const setStage = (key) => show(track, stateTrack(STAGES, key, 'Where this consultation is'));
    const showNote = async (noteId) => {
        if (!noteId) return refresh();
        renderNote(area, await api(`${BASE}/notes/${noteId}`), context, (next) => showNote(next), setStage);
        area.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return undefined;
    };
    const showSession = async (id) => {
        await renderSession(area, await api(`${BASE}/sessions/${id}`), context, showNote, setStage);
        area.scrollIntoView({ block: 'start', behavior: 'smooth' });
    };

    const open = encounters.filter((item) => item.status === 'in_progress');
    const start = open.length ? form(
        [
            { name: 'encounter', label: 'Visit', type: 'select', options: open.map((item) => [item.id, `${when(item.started_at)} ${item.reason}`]) },
            { name: 'language', label: 'Language spoken', type: 'select', value: context.config.defaults.clinscribe_language, options: [['en-IN', 'English'], ['hi-IN', 'Hindi']] },
        ],
        'Open a session',
        async ({ encounter, language }) => {
            const made = await act(() => api(`${BASE}/encounters/${encounter}/sessions`, { method: 'POST', body: { language } }), context);
            if (made) showSession(made.id);
        },
        { inline: true },
    ) : form(
        [{ name: 'reason', label: 'Reason for this visit' }],
        'Start a visit',
        async (values) => {
            const made = await act(() => api(`/api/patients/${patient.id}/encounters`, { method: 'POST', body: values }), context, 'Visit started');
            if (made) refresh();
        },
        { inline: true },
    );
    start.querySelector('button[type="submit"]').classList.add('primary-lg');
    setStage('record');
    show(area, h('section', { class: 'sheet stage-panel' },
        h('h2', {}, open.length ? 'Start recording a consultation' : 'Start a visit first'),
        h('p', { class: 'muted' }, open.length
            ? 'Choose the visit and the language spoken. Recording starts only when you press Start recording.'
            : 'A consultation is recorded against a visit. Say why the patient came, then open a session.'),
        start));

    const sessionRows = sessions.map((row) => listRow({
        leadIcon: 'mic',
        title: `Consultation, ${when(row.started_at)}`,
        meta: plural(row.segments, 'line'),
        tone: row.state === 'recording' ? 'urgent' : row.state === 'stopped' ? '' : 'warn',
        tags: [
            row.chunks_lost ? badge(`${plural(row.chunks_lost, 'chunk')} lost`, 'bad') : null,
            badge(row.transcript_deleted_at ? 'transcript deleted' : { recording: 'Recording', paused: 'Paused', stopped: 'Ended' }[row.state] || row.state,
                row.state === 'stopped' ? '' : 'warn'),
        ],
        onclick: () => showSession(row.id),
        attrs: { 'aria-label': `Open the consultation from ${when(row.started_at)}` },
    }));
    const noteRows = notes.map((row) => listRow({
        leadIcon: row.status === 'draft' ? 'file' : 'lock',
        title: `${row.status === 'draft' ? 'Draft note' : 'Signed note'}, ${when(row.created_at)}`,
        meta: row.status === 'draft' ? (row.open_flags ? `${plural(row.open_flags, 'line')} to check` : 'Ready to read and sign') : 'Locked',
        tone: row.status === 'draft' ? 'warn' : 'good',
        tags: [row.status === 'draft' ? h('mark', {}, 'Draft') : badge('Signed', 'good')],
        onclick: () => showNote(row.id),
        attrs: { 'aria-label': `Open the ${row.status === 'draft' ? 'draft' : 'signed'} note from ${when(row.created_at)}` },
    }));

    show(container,
        h('h1', {}, 'ClinScribe'),
        h('p', { class: 'lede' }, 'Turns a consultation into a draft note for you to check and sign. Audio is sent for transcription and not kept.'),
        h('div', { class: 'banner' }, 'Tell the patient before you start. Recording never begins on its own, and you can stop at any time.'),
        context.config.ai_ready ? null : h('div', { class: 'banner danger' }, 'AI isn\'t set up, so audio can\'t be transcribed and notes can\'t be drafted. Add a free Groq key in Settings.'),
        track,
        area,
        h('div', { class: 'columns history-columns' },
            h('section', {}, h('h2', {}, 'Earlier sessions'),
                rowList(sessionRows, emptyState('No sessions yet', 'A session appears here once you open one.'))),
            h('section', {}, h('h2', {}, 'Notes'),
                rowList(noteRows, emptyState('No notes yet', 'Draft a note from a finished session.')))),
    );
    return undefined;
}
