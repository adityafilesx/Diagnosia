// Small line icons, drawn as SVG paths. Every icon sits beside a visible label or carries an
// aria-label on its button, so nothing is understood from the picture alone.
const paths = {
    home: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1Z',
    overview: 'M8 4H6a1 1 0 0 0-1 1v15a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1h-2M8 3h8v3H8ZM8.5 11h7M8.5 15h5',
    careflow: 'M5 4v16M5 7h13M5 12h9M5 17h13',
    diagnofast: 'M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5 4ZM8.5 8.5h7M8.5 11.5h4',
    clinscribe: 'M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0ZM5.5 10.5a6.5 6.5 0 0 0 13 0M12 17v4M8.5 21h7',
    lablens: 'M9.5 3h5M10 3v6.5L4.6 18.4A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.4-2.6L14 9.5V3M7.5 15h9',
    prescription: 'M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM14 3v5h5M9.5 13.5h5M12 11v5',
    referrals: 'M4 7.5h14m-4-4 4 4-4 4M20 16.5H6m4-4-4 4 4 4',
    discharge: 'M3.5 10.5 12 4l8.5 6.5V20H3.5ZM8.5 14.5l2.5 2.5 4.5-5',
    settings: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4',
    inbox: 'M4 13l2.5-8h11L20 13v6H4ZM4 13h5l1 2h4l1-2h5',
    menu: 'M4 7h16M4 12h16M4 17h16',
    close: 'M6 6l12 12M18 6 6 18',
    sun: 'M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9ZM12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4',
    moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z',
    system: 'M3.5 5h17v11h-17ZM9 20h6M12 16v4',
    alert: 'M12 3.5 22 20.5H2ZM12 10v4.5M12 17.5v.5',
    help: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.8M12 17v.4',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    mic: 'M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0ZM5.5 10.5a6.5 6.5 0 0 0 13 0M12 17v4',
    speaker: 'M4 9.5h4l5-4v13l-5-4H4ZM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12',
    search: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM15.5 15.5 20 20',
};

export function icon(name, className = 'nav-icon') {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    for (const [key, value] of Object.entries({
        viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7',
        'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: className, 'aria-hidden': 'true', focusable: 'false',
    })) svg.setAttribute(key, value);
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', paths[name] || paths.overview);
    svg.append(path);
    return svg;
}

export function initials(name) {
    return String(name || '').trim().split(/\s+/).filter(Boolean).slice(0, 2)
        .map((part) => part[0].toUpperCase()).join('') || '?';
}
