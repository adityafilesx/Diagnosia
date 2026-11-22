// The referral network for staff (stretch A, BUILD.md): who refers to whom, overdue loops and specialist
// load, in plain SVG. The server read every name from the record and decided which referrals are shown.
// No patient appears here.
import { api, badge, h, table, when } from './ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const ROW = 52;
const BOX = 36;

function svg(tag, attributes = {}, text) {
    const node = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
}

function short(text, size = 30) {
    const clean = String(text ?? '');
    return clean.length > size ? `${clean.slice(0, size - 1)}…` : clean;
}

function node(x, y, width, label, kind) {
    const group = svg('g', { class: `graph-node ${kind}` });
    group.append(svg('title', {}, label), svg('rect', { x, y, width, height: BOX, rx: 8 }), svg('text', { x: x + 10, y: y + 23 }, short(label)));
    return group;
}

function picture(paths) {
    const senders = [...new Map(paths.map((edge) => [edge.from.ref, edge.from])).values()];
    const receivers = [...new Map(paths.map((edge) => [edge.to.ref, edge.to])).values()];
    const height = Math.max(senders.length, receivers.length, 1) * ROW + 12;
    const drawing = svg('svg', { viewBox: `0 0 760 ${height}`, role: 'img', class: 'graph-picture', 'aria-labelledby': 'network-title' });
    drawing.append(svg('title', { id: 'network-title' }, 'Referrals from each doctor to each service, with open and overdue counts'));
    const y = (list, ref) => 6 + list.findIndex((item) => item.ref === ref) * ROW + BOX / 2;
    for (const edge of paths) {
        const y1 = y(senders, edge.from.ref);
        const y2 = y(receivers, edge.to.ref);
        drawing.append(svg('path', {
            d: `M230,${y1} C380,${y1} 380,${y2} 530,${y2}`,
            class: `graph-edge${edge.overdue ? ' overdue' : ''}`,
            'stroke-width': Math.min(2 + edge.referrals, 9),
        }));
        drawing.append(svg('text', { x: 380, y: (y1 + y2) / 2 - 4, 'text-anchor': 'middle', class: `graph-note${edge.overdue ? ' warn' : ''}` },
            `${short(edge.specialty, 18)} · ${edge.referrals}${edge.overdue ? ` · ${edge.overdue} overdue` : ''}`));
    }
    senders.forEach((item, index) => drawing.append(node(4, 6 + index * ROW, 226, item.name, 'row')));
    receivers.forEach((item, index) => drawing.append(node(530, 6 + index * ROW, 226, item.name, 'answer')));
    return h('div', { class: 'graph-scroll' }, drawing);
}

export async function networkPanel() {
    const network = await api('/api/addons/referrals/network');
    if (!network.paths.length) return h('p', { class: 'muted' }, 'No referrals to draw yet.');
    return h('div', {},
        h('p', { class: 'muted' }, `Drawn from ${network.source === 'neo4j' ? 'the Neo4j copy' : 'the record'}. Only referrals you sent or received are included. Thicker lines mean more referrals.`),
        picture(network.paths),
        h('h3', {}, 'Specialist load (open referrals)'),
        table([
            { label: 'Service', cell: (row) => row.destination.name },
            { label: 'Open', cell: (row) => String(row.open), number: true },
            { label: 'Overdue', cell: (row) => (row.overdue ? badge(String(row.overdue), 'bad') : '0'), number: true },
        ], network.load, 'Nothing open.'),
        h('h3', {}, 'Overdue loops'),
        table([
            { label: 'Specialty', cell: (row) => row.specialty },
            { label: 'Sent to', cell: (row) => row.to.name },
            { label: 'Reply was due', cell: (row) => when(row.respond_by) },
            { label: 'Priority', cell: (row) => badge(row.priority, row.priority === 'urgent' ? 'bad' : '') },
        ], network.overdue, 'Nothing overdue.'));
}
