// Imua — Audit log panel on the Settings page (task 5.6b). Data: GET /api/audit (admin only).
(function () {
    'use strict';

    const PAGE = 50;
    const tableBox = document.getElementById('audit-table');
    const moreBtn = document.getElementById('audit-more');
    const actorInput = document.getElementById('audit-actor');
    let rows = [];

    function esc(str) {
        const d = document.createElement('div');
        d.textContent = str == null ? '' : String(str);
        return d.innerHTML;
    }

    function when(dt) {
        const t = new Date(dt);
        return isNaN(t) ? esc(dt) : t.toLocaleString();
    }

    function result(status) {
        if (!status) return '—';
        const cls = status < 400 ? 'status-completed' : 'status-failed';
        return `<span class="status-badge ${cls}">${status}</span>`;
    }

    function render() {
        if (!rows.length) {
            tableBox.innerHTML = '<div class="placeholder">No entries.</div>';
            return;
        }
        tableBox.innerHTML = `<table class="data-table"><thead><tr><th>When</th><th>Who</th><th>Action</th>
            <th>Item</th><th>Result</th><th>IP</th></tr></thead><tbody>${rows.map(e => `<tr>
            <td>${when(e.at)}</td><td>${esc(e.actor)}</td><td><code>${esc(e.action)}</code></td>
            <td>${esc(e.target || '')}</td><td>${result(e.status)}</td><td>${esc(e.ip || '')}</td></tr>`).join('')}
            </tbody></table>`;
    }

    async function load(older) {
        const params = new URLSearchParams({ limit: PAGE });
        if (actorInput.value.trim()) params.set('actor', actorInput.value.trim());
        if (older && rows.length) params.set('before', rows[rows.length - 1].id);
        try {
            const resp = await fetch('/api/audit?' + params);
            if (!resp.ok) throw new Error(resp.status);
            const entries = (await resp.json()).entries || [];
            rows = older ? rows.concat(entries) : entries;
            moreBtn.hidden = entries.length < PAGE;
            render();
        } catch (err) {
            tableBox.innerHTML = '<div class="placeholder">Could not load the audit log.</div>';
        }
    }

    document.getElementById('audit-refresh').addEventListener('click', () => load(false));
    actorInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(false); });
    moreBtn.addEventListener('click', () => load(true));
    load(false);
})();
