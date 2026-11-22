// The slot QR login (BUILD.md step 5). A phone number and a one-time code, then the patient's own
// masked name, then a normal one-interview link. Text from the server goes in with textContent only.
const code = new URLSearchParams(location.search).get('code') || '';
const base = `/api/opd/qr/${encodeURIComponent(code)}`;
const $ = (id) => document.getElementById(`slot-${id}`);
let phone = '';
let session = '';

function only(section) {
    ['inactive', 'phone', 'code', 'names'].forEach((name) => { $(name).hidden = name !== section; });
}

function post(path, body) {
    return apiFetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then((response) => response.json());
}

function clearErrors() {
    ['phone-error', 'code-error', 'names-error'].forEach((id) => { $(id).hidden = true; });
}

async function sendCode() {
    clearErrors();
    phone = $('phone-number').value.trim();
    $('send').disabled = true;
    try {
        const reply = await post('/otp', { phone });
        $('demo-note').hidden = !reply.demo_code;
        if (reply.demo_code) $('demo-note').textContent = `Demo: no SMS is sent. Your code is ${reply.demo_code} / डेमो: आपका कोड ${reply.demo_code} है`;
        $('code-input').value = '';
        only('code');
        $('code-input').focus();
    } catch (error) {
        showError($('phone-error'), error.message);
    }
    $('send').disabled = false;
}

function nameButton(item) {
    const button = element('button', 'specialty-card');
    button.type = 'button';
    button.append(element('strong', '', item.name));
    if (item.age !== null && item.age !== undefined) button.append(element('span', '', `Age ${item.age} / उम्र ${item.age}`));
    button.addEventListener('click', () => choose(item.id));
    return button;
}

async function verify() {
    clearErrors();
    $('verify').disabled = true;
    try {
        const reply = await post('/verify', { phone, code: $('code-input').value.trim() });
        session = reply.session;
        const list = $('name-list');
        list.replaceChildren(...reply.bookings.map(nameButton));
        if (!reply.bookings.length) showError($('names-error'), 'No booking in this slot has this number. Please ask reception. / इस स्लॉट में इस नंबर से कोई बुकिंग नहीं है।');
        only('names');
    } catch (error) {
        showError($('code-error'), error.message);
    }
    $('verify').disabled = false;
}

async function choose(bookingId) {
    clearErrors();
    document.querySelectorAll('#slot-name-list button').forEach((button) => { button.disabled = true; });
    try {
        const reply = await post('/choose', { session, booking_id: bookingId });
        location.replace(reply.link);  // replace: the back button doesn't return to a used session
    } catch (error) {
        showError($('names-error'), error.message);
        document.querySelectorAll('#slot-name-list button').forEach((button) => { button.disabled = false; });
    }
}

async function start() {
    try {
        const response = await apiFetch(base);
        const slot = await response.json();
        $('details').textContent = `${slot.department} · ${slot.starts_at.slice(0, 10)} ${slot.starts_at.slice(11)}–${slot.ends_at.slice(11)}`;
        only('phone');
    } catch (error) {
        $('inactive-message').textContent = error.message;
        only('inactive');
    }
}

$('send').addEventListener('click', sendCode);
$('verify').addEventListener('click', verify);
$('phone-number').addEventListener('keydown', (event) => { if (event.key === 'Enter') sendCode(); });
$('code-input').addEventListener('keydown', (event) => { if (event.key === 'Enter') verify(); });
start();
