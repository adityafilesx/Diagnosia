// The evidence and history graphs on the DiagnoFast report (BUILD.md step 8), in plain SVG.
// Neo4j only says which items link; every word here was read from SQLite by the server. All text goes in
// with textContent. These are pictures of where things came from, never a diagnosis.
import { h } from './ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const ROW_HEIGHT = 46;
const BOX_HEIGHT = 34;
const MAX_LABEL = 46;

function svg(tag, attributes = {}, text) {
    const node = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
}

function short(text) {
    const clean = String(text ?? '').replace(/\s+/g, ' ').trim();
    return clean.length > MAX_LABEL ? `${clean.slice(0, MAX_LABEL - 1)}…` : clean;
}

function box(x, y, width, label, full, kind) {
    const group = svg('g', { class: `graph-node ${kind}` });
    group.append(svg('title', {}, full));
    group.append(svg('rect', { x, y, width, height: BOX_HEIGHT, rx: 8 }));
    group.append(svg('text', { x: x + 10, y: y + 22 }, short(label)));
    return group;
}

function line(x1, y1, x2, y2) {
    const middle = (x1 + x2) / 2;
    return svg('path', { d: `M${x1},${y1} C${middle},${y1} ${middle},${y2} ${x2},${y2}`, class: 'graph-edge' });
}

export function evidenceGraph(view) {
    const rows = view.evidence;
    if (!rows.length) return h('p', { class: 'muted' }, 'The summary has no rows that cite answers.');
    const turns = [...new Map(rows.flatMap((item) => item.answers).map((answer) => [answer.turn, answer])).values()]
        .sort((a, b) => a.turn - b.turn);
    const height = Math.max(rows.length, turns.length, 1) * ROW_HEIGHT + 10;
    const picture = svg('svg', { viewBox: `0 0 760 ${height}`, role: 'img', class: 'graph-picture', 'aria-labelledby': 'evidence-title' });
    picture.append(svg('title', { id: 'evidence-title' }, 'Each report row linked to the answers it cites'));
    const rowY = (index) => 6 + index * ROW_HEIGHT;
    const turnY = new Map(turns.map((answer, index) => [answer.turn, 6 + index * ROW_HEIGHT]));
    rows.forEach((item, index) => item.answers.forEach((answer) => {
        picture.append(line(330, rowY(index) + BOX_HEIGHT / 2, 430, turnY.get(answer.turn) + BOX_HEIGHT / 2));
    }));
    rows.forEach((item, index) => {
        const label = `${item.row.parameter || item.row.system}: ${item.row.finding} (${item.row.flag})`;
        picture.append(box(4, rowY(index), 326, label, label, item.answers.length ? 'row' : 'row uncited'));
    });
    turns.forEach((answer) => {
        const label = `${answer.has_recording ? '🎙 ' : ''}Answer ${answer.turn}: ${answer.answer}`;
        picture.append(box(430, turnY.get(answer.turn), 326, label, `${answer.question}\n${answer.answer}`, 'answer'));
    });
    const uncited = rows.filter((item) => !item.answers.length).length;
    return h('div', {},
        h('div', { class: 'graph-scroll' }, picture),
        uncited ? h('p', { class: 'muted' }, `${uncited === 1 ? '1 row cites' : `${uncited} rows cite`} no answer. Check ${uncited === 1 ? 'it' : 'them'} against the patient's own words below.`) : null,
        h('details', {}, h('summary', {}, 'The same links as a list'),
            h('ul', {}, rows.map((item) => h('li', {}, `${item.row.parameter || item.row.system}: ${item.row.finding} ← `,
                item.answers.length ? item.answers.map((answer) => `answer ${answer.turn} “${answer.answer}”`).join('; ') : 'no answer cited')))));
}

export function historyGraph(view) {
    const visits = view.history;
    if (!visits.length) return h('p', { class: 'muted' }, 'No finished visits yet.');
    const width = 760;
    const columns = Math.min(visits.length, 3);
    const cell = (width - 20) / columns;
    const rows = Math.ceil(visits.length / columns);
    const height = 70 + rows * 104;
    const picture = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', class: 'graph-picture', 'aria-labelledby': 'history-title' });
    picture.append(svg('title', { id: 'history-title' }, "This patient's finished visits, with their medicines and allergies"));
    picture.append(box(width / 2 - 90, 6, 180, 'This patient', 'This patient', 'patient'));
    visits.forEach((visit, index) => {
        const x = 10 + (index % columns) * cell;
        const y = 70 + Math.floor(index / columns) * 104;
        picture.append(line(width / 2, 6 + BOX_HEIGHT, x + cell / 2 - 4, y));
        const title = `${visit.day} · ${visit.chief_complaint}${visit.current ? ' (this visit)' : ''}`;
        picture.append(box(x, y, cell - 12, title, `${title}${visit.reviewed ? '' : ' · not yet reviewed'}`, visit.current ? 'visit current' : 'visit'));
        const medicines = visit.medicines.length ? `Medicines: ${visit.medicines.join(', ')}` : 'Medicines: none stated';
        const allergies = visit.allergies.length ? `Allergies: ${visit.allergies.join(', ')}` : 'Allergies: none stated';
        picture.append(svg('text', { x: x + 4, y: y + BOX_HEIGHT + 18, class: 'graph-note' }, short(medicines)));
        picture.append(svg('text', { x: x + 4, y: y + BOX_HEIGHT + 36, class: allergies.endsWith('none stated') ? 'graph-note' : 'graph-note warn' }, short(allergies)));
    });
    return h('div', { class: 'graph-scroll' }, picture);
}

export function graphsPanel(view) {
    return h('section', { class: 'no-print graph-panel' },
        h('h3', {}, 'Where each row came from'),
        h('p', { class: 'muted' }, `Drawn from ${view.source === 'neo4j' ? 'the Neo4j copy' : 'the record'}. Words are read from the record. Hover a box for the full text.`),
        evidenceGraph(view),
        h('h3', {}, 'Visits for this patient'),
        h('p', { class: 'muted' }, 'Medicines and allergies are what the patient said at each visit. Confirm them with the patient.'),
        historyGraph(view));
}
