// Patient text is always a text node or an input value. A draft is never sent as an answer.
const TEXT = {
    'en-IN': {
        start: 'Start my interview', record: 'Tap and speak', stop: 'Stop recording', thinking: 'Please wait…',
        type: 'Edit / type', send: 'Confirm answer',
        assistant: 'Your question', transcript: 'Speak or type', replay: '↻ Hear the question',
        chipHint: 'Tap an option or speak in your own words.', review: 'Check these words. Edit anything that is wrong, then confirm.',
        safety: 'If you need help now, please tell reception.', answer: 'Your answer', ready: 'Ready when you are',
        listening: '● Recording · listening', reviewStatus: 'Ready to review', confidence: 'Recognition confidence unavailable',
        browserConfidence: 'Browser recognition estimate', edited: 'Edited / typed answer · review before confirming',
        fallback: 'Live words unavailable. We’ll transcribe the recording when you stop.',
        microphone: 'Microphone unavailable. You can type your answer below.',
        micInsecure: 'The microphone works only on a secure (https) link. Please type your answer below, or tell reception.',
        micDenied: 'Microphone permission is blocked. Allow it from the lock icon in the address bar, or type your answer below.',
        micMissing: 'No microphone was found. You can type your answer below.',
        micBusy: 'The microphone is being used by another app. Close it, or type your answer below.',
        partial: 'We could not transcribe the full recording. Check that your answer is complete, or type it below.',
        name: 'Please enter your name and check your age.', placeholder: 'Your words will appear here. You can also type.',
        statusTitle: 'Your queue number', toldTitle: 'What you told us', summaryTitle: 'Summary checked by your doctor',
        summaryWaiting: 'The doctor will add a summary here after reading your answers.', hearAgain: 'Hear it again',
        complaint: 'Main problem', history: 'Details', medicines: 'Medicines', allergies: 'Allergies', none: 'None stated',
        listen: 'Read this aloud', agree: 'I agree, start my interview', consentTitle: 'Before we begin', decline: 'If you do not agree, please tell reception.',
        yes: 'Yes', no: 'No', abhaNeeded: 'Please choose yes or no for your past records.',
        failed: 'Something went wrong on our side. Please try again, or tell reception.',
        helpSent: 'Reception has been told. If nobody comes, please go to the desk.',
        helpFailed: 'We could not reach reception from here. Please go to the desk.',
    },
    'hi-IN': {
        start: 'बातचीत शुरू करें', record: 'दबाएँ और बोलें', stop: 'रिकॉर्डिंग रोकें', thinking: 'कृपया रुकिए…',
        type: 'बदलें / लिखें', send: 'जवाब की पुष्टि करें',
        assistant: 'आपका सहायक', transcript: 'आपके शब्द', replay: '↻ प्रश्न फिर सुनें',
        chipHint: 'विकल्प चुनें या अपने शब्दों में बोलें।', review: 'अपने शब्द जाँचें। गलती हो तो सुधारें, फिर पुष्टि करें।',
        safety: 'अभी मदद चाहिए तो रिसेप्शन को बताएँ।', answer: 'आपका जवाब', ready: 'जब आप तैयार हों',
        listening: '● रिकॉर्डिंग · सुन रहे हैं', reviewStatus: 'जवाब जाँचें', confidence: 'आवाज़ पहचान का विश्वास स्तर उपलब्ध नहीं',
        browserConfidence: 'ब्राउज़र की आवाज़ पहचान का अनुमान', edited: 'लिखा / बदला हुआ जवाब · पुष्टि से पहले जाँचें',
        fallback: 'शब्द अभी नहीं दिख रहे। रोकने पर रिकॉर्डिंग लिखी जाएगी।',
        microphone: 'माइक्रोफ़ोन उपलब्ध नहीं है। नीचे अपना जवाब लिख सकते हैं।',
        micInsecure: 'माइक्रोफ़ोन केवल सुरक्षित (https) लिंक पर चलता है। नीचे अपना जवाब लिखें, या रिसेप्शन को बताएँ।',
        micDenied: 'माइक्रोफ़ोन की अनुमति बंद है। पता-पट्टी में ताले के निशान से अनुमति दें, या नीचे जवाब लिखें।',
        micMissing: 'कोई माइक्रोफ़ोन नहीं मिला। नीचे अपना जवाब लिख सकते हैं।',
        micBusy: 'माइक्रोफ़ोन किसी और ऐप में चल रहा है। उसे बंद करें, या नीचे जवाब लिखें।',
        partial: 'पूरी रिकॉर्डिंग लिखी नहीं जा सकी। जवाब पूरा है या नहीं जाँचें, या नीचे लिखें।',
        name: 'कृपया नाम भरें और उम्र जाँचें।', placeholder: 'आपके शब्द यहाँ दिखेंगे। आप लिख भी सकते हैं।',
        statusTitle: 'आपका नंबर', toldTitle: 'आपने हमें यह बताया', summaryTitle: 'डॉक्टर द्वारा जाँचा गया सारांश',
        summaryWaiting: 'डॉक्टर आपके जवाब पढ़ने के बाद यहाँ सारांश जोड़ेंगे।', hearAgain: 'फिर से सुनें',
        complaint: 'मुख्य परेशानी', history: 'विवरण', medicines: 'दवाइयाँ', allergies: 'एलर्जी', none: 'कुछ नहीं बताया',
        listen: 'यह सुनकर समझें', agree: 'मैं सहमत हूँ, बातचीत शुरू करें', consentTitle: 'शुरू करने से पहले', decline: 'सहमत नहीं हैं तो रिसेप्शन को बताएँ।',
        yes: 'हाँ', no: 'नहीं', abhaNeeded: 'पुराने रिकॉर्ड के लिए हाँ या नहीं चुनें।',
        failed: 'हमारी तरफ़ से कुछ गड़बड़ हुई। दोबारा कोशिश करें, या रिसेप्शन को बताएँ।',
        helpSent: 'रिसेप्शन को बता दिया गया है। कोई न आए तो कृपया डेस्क पर जाएँ।',
        helpFailed: 'यहाँ से रिसेप्शन तक बात नहीं पहुँची। कृपया डेस्क पर जाएँ।',
    },
};
const DEPARTMENTS = {
    general_physician: ['General Medicine', 'सामान्य चिकित्सा', '✚'],
    dermatologist: ['Dermatology', 'त्वचा विभाग', '◈'],
    cardiology: ['Cardiology', 'हृदय विभाग', '♡'],
    orthopedics: ['Orthopedics', 'हड्डी एवं जोड़', '◇'],
    ent: ['ENT', 'कान, नाक और गला', '◎'],
    pediatrics: ['Pediatrics', 'बाल चिकित्सा', '☆'],
};
const MAX_RECORDING_MS = 28000;
// After an urgent stop the message stays on the screen for a minute: the "Finish" control is held
// back, so the next person at a shared tablet can't clear it before the patient has read it.
const URGENT_HOLD_MS = 60000;
const $ = (id) => document.getElementById(`intake-${id}`);
let token = new URLSearchParams(location.search).get('token');
const kiosk = !token;
let formId = null;
let busy = false;
let acquiring = false;
let stopping = false;
let disposed = false;
let recorder = null;
let stream = null;
let recognition = null;
let recognitionComplete = null;
let recognitionIncomplete = false;
let pendingBlob = null;
let stopTimer = null;
let audioContext = null;
let meterFrame = null;
let activeAudio = null;
let currentReply = null;
let playbackGeneration = 0;
// No language is chosen for the patient. Until they pick one, controls fall back to English labels.
const words = () => TEXT[$('language').value] || TEXT['en-IN'];
// The consent words come from the server with their version, so what is stored is what was shown.
let consentWords = null;
let abhaWords = null;
let abhaChoice = null;
let consentShown = false;

function renderConsent() {
    const language = $('language').value;
    if (!language || !consentWords) return;
    $('consent-title').textContent = words().consentTitle;
    $('consent-lines').replaceChildren(...consentWords.lines[language].map((line) => element('li', '', line)));
    $('abha').hidden = !abhaWords;
    if (abhaWords) {
        $('abha-question').textContent = abhaWords.lines[language][0];
        $('abha-yes').textContent = words().yes;
        $('abha-no').textContent = words().no;
    }
    $('consent-decline').textContent = words().decline;
    $('consent-listen').textContent = `🔊 ${words().listen}`;
    $('consent').hidden = false;
    consentShown = true;
}

// A failure the patient can do nothing about (the server, the network, a limit) is said in their own
// language with a next step, and a button that marks the visit in the staff queue. Messages about their
// own answer ("Please answer the question") are shown as they are.
function showFailure(node, failure) {
    const theirs = failure.status >= 400 && failure.status < 500 && failure.status !== 429;
    showError(node, theirs ? failure.message : words().failed);
    $('help-status').textContent = '';
    $('help-box').hidden = !token;
}

async function tellReception() {
    $('help-button').disabled = true;
    try {
        await apiFetch(`/api/diagnofast/patient/${encodeURIComponent(token)}/help`, { method: 'POST' });
        $('help-status').textContent = words().helpSent;
    } catch (_) {
        $('help-status').textContent = words().helpFailed;
    }
    $('help-button').disabled = false;
}

function chooseLanguage(language) {
    $('language').value = language;
    document.querySelectorAll('.language-choice button').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.language === language));
    });
    applyLanguage();
    renderConsent();
}

function chooseAbha(choice) {
    abhaChoice = choice;
    $('abha-yes').setAttribute('aria-pressed', String(choice === true));
    $('abha-no').setAttribute('aria-pressed', String(choice === false));
}

function applyLanguage() {
    document.documentElement.lang = $('language').value.startsWith('hi') ? 'hi' : 'en';
    const labels = { type: 'type', send: 'send',
        'assistant-label': 'assistant', 'transcript-label': 'transcript', replay: 'replay', 'chip-hint': 'chipHint',
        'review-hint': 'review', 'safety-note': 'safety', 'answer-label': 'answer' };
    for (const [id, key] of Object.entries(labels)) $(id).textContent = words()[key];
    $('start').textContent = words().agree;
    $('language-tag').textContent = $('language').value === 'hi-IN' ? 'हिन्दी' : 'English (IN)';
    $('answer').placeholder = words().placeholder;
    $('confidence').textContent = words().confidence;
    $('record-status').textContent = words().ready;
    syncControls();
}

function syncControls() {
    const recording = !!recorder;
    const locked = busy || acquiring || stopping || recording;
    $('record').disabled = busy || acquiring || stopping;
    $('record').textContent = recording ? words().stop : (busy || acquiring || stopping) ? words().thinking : words().record;
    $('record').classList.toggle('recording', recording);
    $('answer').readOnly = locked;
    $('send').disabled = locked || !$('answer').value.trim();
    $('type').disabled = locked;
    $('replay').disabled = locked;
    document.querySelectorAll('#intake-chips button').forEach((button) => { button.disabled = locked; });
}

function stopPlayback() {
    playbackGeneration += 1;
    if (activeAudio) { activeAudio.pause(); activeAudio = null; }
    window.speechSynthesis?.cancel();
    document.querySelector('.assistant-orb').classList.remove('speaking');
}

function browserVoice(text, generation) {
    if (!text || !window.speechSynthesis || generation !== playbackGeneration) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = $('language').value;
    const voices = speechSynthesis.getVoices().filter((voice) => voice.lang.toLowerCase().startsWith(utterance.lang.slice(0, 2)));
    utterance.voice = voices.find((voice) => /neerja|swara|samantha|siri|female/i.test(voice.name))
        || voices.find((voice) => voice.lang.toLowerCase() === utterance.lang.toLowerCase()) || voices[0] || null;
    utterance.rate = 0.9;
    utterance.pitch = 1.0;
    const orb = document.querySelector('.assistant-orb');
    utterance.onstart = () => { if (generation === playbackGeneration) orb.classList.add('speaking'); };
    utterance.onend = utterance.onerror = () => { if (generation === playbackGeneration) orb.classList.remove('speaking'); };
    speechSynthesis.speak(utterance);
}

// For patients who can't read the consent easily: the server's voice when there is one, else the
// browser's. Reading aloud never counts as agreeing; the patient still presses "I agree".
async function readConsentAloud() {
    const language = $('language').value;
    if (!language || !consentWords) return;
    const button = $('consent-listen');
    button.disabled = true;
    const path = token ? `/api/diagnofast/patient/${encodeURIComponent(token)}/consent-audio` : '/api/diagnofast/kiosk/consent-audio';
    const fetchAudio = async (kind) => {
        const body = token ? { language, kind } : { language };
        try {
            const response = await apiFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            return (await response.json()).audio;
        } catch (_) {
            return null;  // the browser's voice reads it instead
        }
    };
    const parts = [{ text: consentWords.lines[language].join(' '), audio: await fetchAudio('interview') }];
    if (abhaWords && token) parts.push({ text: abhaWords.lines[language][0], audio: await fetchAudio('abha') });
    button.disabled = false;
    if (parts.some((part) => !part.audio)) {
        // One voice for everything: mixing a server voice and the browser's would sound broken.
        play({ finished: true, message: parts.map((part) => part.text).join(' '), audio: null });
        return;
    }
    play({ finished: true, message: parts[0].text, audio: parts[0].audio });
    if (parts[1] && activeAudio) {
        const generation = playbackGeneration;
        activeAudio.addEventListener('ended', () => {
            if (generation === playbackGeneration) play({ finished: true, message: parts[1].text, audio: parts[1].audio });
        });
    }
}

function play(reply) {
    stopPlayback();
    const generation = playbackGeneration;
    const text = reply.finished ? reply.message : reply.question;
    if (!reply.audio) { browserVoice(text, generation); return; }
    activeAudio = new Audio(reply.audio);
    activeAudio.onplaying = () => document.querySelector('.assistant-orb').classList.add('speaking');
    activeAudio.onended = () => document.querySelector('.assistant-orb').classList.remove('speaking');
    activeAudio.play().catch(() => browserVoice(text, generation));
}

function renderChips(chips = []) {
    $('chips').replaceChildren();
    chips.forEach((chip) => {
        const button = element('button', '', chip.label);
        button.type = 'button';
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', () => {
            // A chip is a reviewable draft, never an automatic submission.
            pendingBlob = null;
            $('answer').value = chip.value;
            document.querySelectorAll('#intake-chips button').forEach((other) => other.setAttribute('aria-pressed', String(other === button)));
            $('confidence').textContent = words().edited;
            $('record-status').textContent = words().reviewStatus;
            syncControls();
        });
        $('chips').append(button);
    });
}

// One key per question. A retry after a lost reply sends the same key, so the answer is saved once.
const newAnswerKey = () => (window.crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
let answerKey = newAnswerKey();

// After a booked interview, the link becomes a read-only status page for the rest of the day: the
// queue number and department (read aloud), the patient's own words, and the AI summary only once a
// doctor has marked it reviewed. An urgent stop shows only "go to reception now".
const STATUS_POLL_MS = 30000;
let statusTimer = null;

function summaryList(summary) {
    const list = element('dl', 'status-summary');
    const add = (label, value) => {
        const text = Array.isArray(value) ? value.join(', ') : value;
        list.append(element('dt', '', label), element('dd', '', text && String(text).trim() ? text : words().none));
    };
    add(words().complaint, summary.chief_complaint);
    add(words().history, summary.present_illness);
    add(words().medicines, summary.current_medicines);
    add(words().allergies, summary.allergies);
    return list;
}

async function speakStatus() {
    $('status-listen').disabled = true;
    let audio = null;
    try {
        const response = await apiFetch(`/api/diagnofast/patient/${encodeURIComponent(token)}/status-audio`, { method: 'POST' });
        audio = (await response.json()).audio;
    } catch (_) {
        audio = null;
    }
    play({ finished: true, message: $('status-listen').dataset.words || '', audio });
    $('status-listen').disabled = false;
}

async function showStatus(speak) {
    const response = await apiFetch(`/api/diagnofast/patient/${encodeURIComponent(token)}/status`);
    const status = await response.json();
    if (status.language) chooseLanguageQuietly(status.language);
    ['welcome', 'interview', 'finish', 'inactive'].forEach((id) => { $(id).hidden = true; });
    $('status').hidden = false;
    $('status-listen').textContent = `🔊 ${words().hearAgain}`;
    if (status.urgent) {
        $('status-title').textContent = '';
        $('status-number').textContent = '';
        $('status-department').textContent = status.message;
        $('status-department').className = 'urgent-banner';
        $('status-listen').dataset.words = status.message;
        ['status-told-title', 'status-told', 'status-summary-title', 'status-summary'].forEach((id) => { $(id).hidden = true; });
        if (speak) speakStatus();
        return status;
    }
    $('status-title').textContent = words().statusTitle;
    $('status-number').textContent = String(status.queue_number);
    $('status-department').textContent = status.words;
    $('status-listen').dataset.words = status.words;
    $('status-told-title').textContent = words().toldTitle;
    $('status-told').replaceChildren(...status.told.map((turn) => {
        const item = element('li', '');
        item.append(element('span', 'status-question', turn.question), element('strong', '', turn.answer));
        return item;
    }));
    $('status-summary-title').textContent = words().summaryTitle;
    $('status-summary').replaceChildren(status.summary ? summaryList(status.summary) : element('p', 'intake-hint', words().summaryWaiting));
    if (speak) speakStatus();
    clearTimeout(statusTimer);
    if (!status.reviewed) statusTimer = setTimeout(() => showStatus(false).catch(() => {}), STATUS_POLL_MS);
    return status;
}

function chooseLanguageQuietly(language) {
    $('language').value = language;
    document.documentElement.lang = language.startsWith('hi') ? 'hi' : 'en';
}

function showNext(reply) {
    currentReply = reply;
    answerKey = newAnswerKey();
    pendingBlob = null;
    $('answer').value = '';
    $('confidence').textContent = words().confidence;
    $('record-status').textContent = words().ready;
    renderChips(reply.suggested_chips);
    $('help-box').hidden = true;
    if (reply.finished && reply.status_page && !kiosk) {
        // The patient's own phone keeps its link, so a reload shows the status again today.
        $('interview').hidden = true;
        // The status page reads the queue number and department aloud (or the urgent message). If it
        // can't be loaded, the patient still hears and sees the usual finishing message.
        showStatus(true).catch(() => {
            $('finish').hidden = false;
            $('finish-message').textContent = reply.message;
            $('finish-message').className = reply.urgent ? 'urgent-banner' : 'intake-question';
            play(reply);
        });
        syncControls();
        return;
    }
    if (reply.finished) {
        $('interview').hidden = true;
        $('finish').hidden = false;
        $('finish-message').textContent = reply.message;
        $('finish-message').className = reply.urgent ? 'urgent-banner' : 'intake-question';
        if (reply.urgent) {
            $('reset').hidden = true;
            setTimeout(() => { $('reset').hidden = false; }, URGENT_HOLD_MS);
        }
        // Remove the spent bearer token and identifying details from the shared screen.
        history.replaceState(null, '', 'intake.html');
        $('patient-name').value = '';
        $('name').textContent = '';
        $('age').value = '';
        $('sex').value = '';
    } else {
        $('question').textContent = reply.question;
        $('question').focus();
    }
    play(reply);
    syncControls();
}

async function sendAnswer() {
    if (busy || recorder || acquiring || stopping || !$('answer').value.trim()) return;
    const data = new FormData();
    data.append('text', $('answer').value.trim());
    data.append('answer_key', answerKey);
    if (pendingBlob) data.append('audio', pendingBlob, 'answer');
    $('answer-error').hidden = true;
    busy = true;
    syncControls();
    stopPlayback();
    try {
        const response = await apiFetch(`/api/diagnofast/patient/${encodeURIComponent(token)}/answer`, { method: 'POST', body: data });
        if (!disposed) showNext(await response.json());
    } catch (failure) {
        if (!disposed) showFailure($('answer-error'), failure);
    } finally {
        busy = false;
        syncControls();
    }
}

function startMeter(mic) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    try {
        audioContext = new AudioContextClass();
        audioContext.resume().catch(() => {});
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        audioContext.createMediaStreamSource(mic).connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const canvas = $('meter');
        const context = canvas.getContext('2d');
        const draw = () => {
            analyser.getByteFrequencyData(data);
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0b6b63';
            for (let i = 0; i < 40; i += 1) {
                const height = Math.max(2, data[i * 2] / 255 * 36);
                context.fillRect(i * 12 + 2, (40 - height) / 2, 8, height);
            }
            meterFrame = requestAnimationFrame(draw);
        };
        draw();
    } catch (_) { /* Recording still works without a visualizer. */ }
}

function releaseMic() {
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    cancelAnimationFrame(meterFrame);
    if (audioContext) { audioContext.close().catch(() => {}); audioContext = null; }
    $('meter').getContext('2d')?.clearRect(0, 0, 480, 40);
}

function startRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognitionIncomplete = !Recognition;
    if (!Recognition) { $('record-status').textContent = words().fallback; return; }
    const session = new Recognition();
    recognition = session;
    session.lang = $('language').value;
    session.interimResults = true;
    session.continuous = true;
    session.onresult = (event) => {
        if (disposed || recognition !== session) return;
        const fragments = [];
        const scores = [];
        for (const result of event.results) {
            fragments.push(result[0].transcript);
            if (result.isFinal && result[0].confidence > 0) scores.push(result[0].confidence);
        }
        $('answer').value = fragments.join(' ').slice(0, 2000);
        $('confidence').textContent = scores.length
            ? `${words().browserConfidence}: ${Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 100)}%`
            : words().confidence;
    };
    session.onerror = () => {
        recognitionIncomplete = true;
        if (!disposed) $('record-status').textContent = words().fallback;
    };
    recognitionComplete = new Promise((resolve) => {
        session.onend = () => {
            if (recorder && !stopping) recognitionIncomplete = true;
            resolve();
        };
    });
    try { session.start(); } catch (_) { recognitionIncomplete = true; recognition = null; recognitionComplete = null; }
}

async function finishRecording(chunks) {
    clearTimeout(stopTimer);
    stopping = true;
    recorder = null;
    releaseMic();
    syncControls();
    const session = recognition;
    if (session) {
        try { session.stop(); } catch (_) { /* It may have ended on its own. */ }
        let timeout;
        await Promise.race([recognitionComplete, new Promise((resolve) => {
            timeout = setTimeout(() => { recognitionIncomplete = true; resolve(); }, 1000);
        })]);
        clearTimeout(timeout);
        recognition = null;
        try { session.abort(); } catch (_) { /* Already ended. */ }
    }
    if (disposed) { stopping = false; return; }
    pendingBlob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' });
    if (!pendingBlob.size) pendingBlob = null;
    if (pendingBlob && (recognitionIncomplete || !$('answer').value.trim())) {
        $('record-status').textContent = words().thinking;
        const data = new FormData();
        data.append('audio', pendingBlob, 'answer');
        try {
            const response = await apiFetch(`/api/diagnofast/patient/${encodeURIComponent(token)}/transcribe`, { method: 'POST', body: data });
            const reply = await response.json();
            if (!disposed) { $('answer').value = reply.text; $('confidence').textContent = words().confidence; }
        } catch (failure) {
            if (!disposed) showError($('answer-error'), `${words().partial} ${failure.message}`);
        }
    }
    stopping = false;
    if (!disposed) {
        $('record-status').textContent = words().reviewStatus;
        syncControls();
    }
}

// Browsers expose the microphone only on https or localhost. On a plain http address, such as a
// phone opening the laptop's LAN address, navigator.mediaDevices is missing altogether.
function micProblem(error) {
    if (!window.isSecureContext) return words().micInsecure;
    switch (error?.name) {
    case 'NotAllowedError': case 'SecurityError': return words().micDenied;
    case 'NotFoundError': case 'OverconstrainedError': return words().micMissing;
    case 'NotReadableError': case 'AbortError': return words().micBusy;
    default: return words().microphone;
    }
}

async function startRecording() {
    if (busy || acquiring || stopping || disposed) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        showError($('answer-error'), micProblem());
        return;
    }
    acquiring = true;
    syncControls();
    stopPlayback();
    $('answer-error').hidden = true;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (disposed) { releaseMic(); return; }
        const chunks = [];
        const session = new MediaRecorder(stream);
        recorder = session;
        session.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
        session.onstop = () => finishRecording(chunks);
        session.onerror = () => {
            showError($('answer-error'), words().microphone);
            if (session.state !== 'inactive') session.stop();
            else { recorder = null; releaseMic(); syncControls(); }
        };
        session.start();
        pendingBlob = null;
        $('answer').value = '';
        $('confidence').textContent = words().confidence;
        $('record-status').textContent = words().listening;
        startRecognition();
        startMeter(stream);
        stopTimer = setTimeout(stopRecording, MAX_RECORDING_MS);
    } catch (failure) {
        recorder = null;
        releaseMic();
        if (!disposed) showError($('answer-error'), micProblem(failure));
    } finally {
        acquiring = false;
        syncControls();
    }
}

function stopRecording() {
    if (!recorder || recorder.state === 'inactive') return;
    stopping = true;
    syncControls();
    recorder.stop();
}

$('record').addEventListener('click', () => recorder ? stopRecording() : startRecording());
$('type').addEventListener('click', () => $('answer').focus());
$('typed').addEventListener('submit', (event) => { event.preventDefault(); sendAnswer(); });
$('answer').addEventListener('input', () => {
    $('confidence').textContent = words().edited;
    document.querySelectorAll('#intake-chips button').forEach((button) => button.setAttribute('aria-pressed', 'false'));
    syncControls();
});
$('replay').addEventListener('click', () => currentReply && play(currentReply));
$('consent-listen').addEventListener('click', readConsentAloud);
$('status-listen').addEventListener('click', speakStatus);
document.querySelectorAll('.language-choice button').forEach((button) => {
    button.addEventListener('click', () => chooseLanguage(button.dataset.language));
});
$('help-button').addEventListener('click', tellReception);
$('abha-yes').addEventListener('click', () => chooseAbha(true));
$('abha-no').addEventListener('click', () => chooseAbha(false));
$('change-specialty').addEventListener('click', () => { $('welcome').hidden = true; $('specialties').hidden = false; });

$('start').addEventListener('click', async () => {
    if ($('start').disabled || !consentShown) return;
    $('start-error').hidden = true;
    if (abhaWords && abhaChoice === null) { showError($('start-error'), words().abhaNeeded); return; }
    if (kiosk && (!$('patient-name').value.trim() || !$('age').checkValidity())) {
        showError($('start-error'), words().name); return;
    }
    $('start').disabled = true;
    $('change-specialty').disabled = true;
    const languageButtons = document.querySelectorAll('.language-choice button');
    languageButtons.forEach((button) => { button.disabled = true; });
    try {
        if (!token) {
            const made = await postJson('/api/diagnofast/kiosk/intakes', {
                form_id: formId, patient_name: $('patient-name').value.trim(),
                patient_age: $('age').value === '' ? null : Number($('age').value),
                patient_sex: $('sex').value || null, consent: consentShown,
            });
            token = new URL(made.link, location.href).searchParams.get('token');
            // Keep the new link on a start failure so a retry cannot create a second visit.
            history.replaceState(null, '', `intake.html?token=${encodeURIComponent(token)}`);
            $('change-specialty').hidden = true;
            $('demographics').querySelectorAll('input, select').forEach((input) => { input.disabled = true; });
        }
        const reply = await postJson(`/api/diagnofast/patient/${encodeURIComponent(token)}/start`, {
            language: $('language').value, consent: consentShown, consent_version: consentWords.version,
            abha_consent: abhaChoice === true,
        });
        $('welcome').hidden = true;
        $('interview').hidden = false;
        showNext({ finished: false, ...reply });
    } catch (failure) {
        showFailure($('start-error'), failure);
    } finally {
        $('start').disabled = false;
        $('change-specialty').disabled = false;
        languageButtons.forEach((button) => { button.disabled = false; });
    }
});

window.addEventListener('pagehide', () => {
    disposed = true;
    clearTimeout(stopTimer);
    stopPlayback();
    try { recognition?.abort(); } catch (_) { /* Already ended. */ }
    if (recorder?.state === 'recording') recorder.stop();
    releaseMic();
    pendingBlob = null;
    $('answer').value = '';
});
// A shared kiosk must not restore a previous patient's draft from the back/forward cache.
window.addEventListener('pageshow', (event) => { if (event.persisted) location.reload(); });

async function initialize() {
    applyLanguage();
    try {
        if (token) {
            const response = await apiFetch(`/api/diagnofast/patient/${encodeURIComponent(token)}`);
            const patient = await response.json();
            $('name').textContent = `, ${patient.patient_name}`;
            consentWords = patient.consent;
            abhaWords = patient.abha_consent || null;
            if (patient.status === 'in_progress' && patient.question) {
                // Reloaded mid-interview: carry on at the same question.
                chooseLanguage(patient.language);
                $('interview').hidden = false;
                showNext({ finished: false, question: patient.question, audio: patient.audio });
            } else {
                $('welcome').hidden = false;
            }
        } else {
            const response = await apiFetch('/api/diagnofast/kiosk');
            const { forms, consent } = await response.json();
            consentWords = consent;
            Object.entries(DEPARTMENTS).forEach(([id, [title, hindi, symbol]]) => {
                if (!forms.some((form) => form.id === id)) return;
                const button = element('button', 'specialty-card');
                button.type = 'button';
                const icon = element('span', 'specialty-symbol', symbol);
                icon.setAttribute('aria-hidden', 'true');
                button.append(icon, element('strong', '', title), element('small', '', hindi));
                button.addEventListener('click', () => {
                    formId = id;
                    $('department').textContent = `${title} · ${hindi}`;
                    $('specialties').hidden = true;
                    $('welcome').hidden = false;
                    $('patient-name').focus();
                });
                $('specialty-grid').append(button);
            });
            $('demographics').hidden = false;
            $('change-specialty').hidden = false;
            $('specialties').hidden = false;
        }
    } catch (failure) {
        // A finished, booked interview shows its status page instead, for the rest of the day.
        if (token && (await showStatus(true).then(() => true).catch(() => false))) return;
        $('inactive-message').textContent = failure.message;
        $('inactive').hidden = false;
    }
}
initialize();

// The journey strip shows where the patient is: language, agree, questions, done. It follows which
// section is on screen, so it never claims a percentage or a fixed number of questions.
(function trackJourney() {
    const strip = document.getElementById('intake-journey');
    if (!strip) return;
    const stageFor = () => {
        if (!$('status').hidden || !$('finish').hidden) return 'done';
        if (!$('interview').hidden) return 'questions';
        if (!$('consent').hidden) return 'consent';
        if (!$('welcome').hidden || !$('specialties').hidden) return 'language';
        return null;
    };
    const draw = () => {
        const stage = stageFor();
        // Written only on change: the observer watches "hidden", and an unchanged write still notifies.
        if (strip.hidden !== !stage) strip.hidden = !stage;
        let reached = true;
        strip.querySelectorAll('li').forEach((item) => {
            const current = item.dataset.stage === stage;
            item.toggleAttribute('aria-current', false);
            if (current) item.setAttribute('aria-current', 'step');
            item.classList.toggle('done', reached && !current);
            if (current) reached = false;
        });
    };
    new MutationObserver(draw).observe(document.querySelector('.intake-shell'), { attributes: true, subtree: true, attributeFilter: ['hidden'] });
    draw();
}());
