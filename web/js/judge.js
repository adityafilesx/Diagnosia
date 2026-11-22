// Judge mode (a public demo with made-up patients): each tool's links on the home page open that
// tool already signed in, through the server's demo door. Off, the page is left exactly as written.
(function () {
    'use strict';
    var TOOL_LINK = /^care\.html#\/([a-z]+)$/;

    function pointAtDemo() {
        document.querySelectorAll('a[href^="care.html#/"]').forEach(function (link) {
            var match = TOOL_LINK.exec(link.getAttribute('href'));
            if (match) link.setAttribute('href', '/demo/open?tool=' + encodeURIComponent(match[1]));
        });
        // "Open Diagnosia" would ask for a sign-in; in the demo it leads to the six tools instead.
        document.querySelectorAll('a.use-now[href="care.html"]').forEach(function (link) {
            link.setAttribute('href', '#How-It-works');
        });
    }

    fetch('/api/demo/status', { credentials: 'same-origin' })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (status) { if (status && status.judge_mode) pointAtDemo(); })
        .catch(function () { /* no demo: the links stay as they are */ });
}());
