// Sets the colour theme before the page paints, so there is no flash. A plain script (not a module)
// loaded in <head>: the content-security-policy allows no inline script.
// The choice is "light" (the default), "dark", or "system" (follow the device).
(function applyTheme() {
    var KEY = 'curai-theme';
    var root = document.documentElement;
    var query = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function stored() {
        try {
            var value = window.localStorage.getItem(KEY);
            return value === 'dark' || value === 'system' ? value : 'light';
        } catch (blocked) {
            return 'light';
        }
    }

    function resolve(choice) {
        if (choice === 'system') return query && query.matches ? 'dark' : 'light';
        return choice;
    }

    function apply(choice) {
        root.setAttribute('data-theme', resolve(choice));
        root.setAttribute('data-theme-choice', choice);
    }

    window.curaiTheme = {
        get: stored,
        set: function set(choice) {
            try {
                window.localStorage.setItem(KEY, choice);
            } catch (blocked) { /* the page still switches for this visit */ }
            apply(choice);
        },
    };

    apply(stored());
    if (query && query.addEventListener) {
        query.addEventListener('change', function onChange() {
            if (stored() === 'system') apply('system');
        });
    }
}());
