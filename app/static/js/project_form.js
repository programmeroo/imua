// Imua — shared project form + API helper (task 6.8). Used by projects.js and project_detail.js.
// Requests go out with the signed-in session; base.html adds the CSRF token to fetch() writes.
window.ImuaProjects = (function () {
    'use strict';

    async function api(method, url, body) {
        const opts = { method, headers: {} };
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const resp = await fetch(url, opts);
        if (resp.status === 401) {  // session expired
            location = '/login?next=' + encodeURIComponent(location.pathname + location.hash);
            throw new Error('Signed out');
        }
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.message || (data.details || []).join(', ') || resp.statusText);
        return data;
    }

    // Wire a <section hidden><form>…</form></section>: `opener` shows it, Cancel hides it,
    // submit calls onSubmit({name, description}) and shows any error inside the form.
    function form(sectionId, opener, onSubmit) {
        const section = document.getElementById(sectionId);
        const f = section.querySelector('form');
        const err = section.querySelector('.project-form-error');
        const show = (on) => {
            section.hidden = !on;
            err.hidden = true;
            if (on) f.elements.name.focus();
        };
        opener.addEventListener('click', () => show(section.hidden));
        f.querySelector('[data-cancel]').addEventListener('click', () => show(false));
        f.addEventListener('submit', async (e) => {
            e.preventDefault();
            const button = f.querySelector('[type=submit]');
            button.disabled = true;
            try {
                await onSubmit({ name: f.elements.name.value.trim(), description: f.elements.description.value.trim() });
            } catch (ex) {
                err.textContent = ex.message;
                err.hidden = false;
            } finally {
                button.disabled = false;
            }
        });
    }

    return { api, form };
})();
