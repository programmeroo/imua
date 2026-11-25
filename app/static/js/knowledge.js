// Imua — Knowledge Base Page
(function () {
    'use strict';

    const API = '/api/knowledge';

    function esc(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function timeAgo(dt) {
        if (!dt) return '—';
        const sec = Math.floor((new Date() - new Date(dt)) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    }

    function tagsHtml(json) {
        if (!json) return '—';
        try {
            const arr = JSON.parse(json);
            if (!arr || !arr.length) return '—';
            return arr.map((t) => `<span class="tag">${esc(t)}</span>`).join(' ');
        } catch { return '—'; }
    }

    async function fetchStats() {
        try {
            const resp = await fetch(`${API}/stats`);
            const data = await resp.json();
            const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
            el('stat-total', data.entry_count || 0);
            el('stat-searchable', data.entry_count || 0);
        } catch (err) {
            console.error('Failed to fetch stats:', err);
        }
    }

    async function fetchRecent() {
        try {
            const resp = await fetch(`${API}/recent?limit=20`);
            const data = await resp.json();
            renderRecent(data.entries || []);
            const agents = new Set((data.entries || []).map((e) => e.agent).filter(Boolean));
            const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
            el('stat-agents', agents.size);
        } catch (err) {
            console.error('Failed to fetch recent:', err);
        }
    }

    function renderRecent(entries) {
        const tbody = document.getElementById('recent-body');
        if (!tbody) return;
        if (!entries.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="placeholder" style="text-align:center;padding:24px">No entries yet. Add the first one above.</td></tr>';
            return;
        }
        tbody.innerHTML = entries.map((e) => `
            <tr data-id="${e.id}">
                <td>${esc(e.title || '(untitled)')}</td>
                <td><span class="status-badge">${esc(e.source)}</span></td>
                <td>${esc(e.agent || '—')}</td>
                <td>${tagsHtml(e.tags)}</td>
                <td>${timeAgo(e.created_at)}</td>
                <td class="msg-row-actions">
                    <button class="btn btn-sm" data-action="edit" data-id="${e.id}">Edit</button>
                    <button class="btn btn-sm btn-danger" data-action="delete" data-id="${e.id}">Delete</button>
                </td>
            </tr>
        `).join('');
    }

    function renderSearchResults(data) {
        const container = document.getElementById('search-results');
        if (!container) return;
        if (!data.hits || !data.hits.length) {
            container.innerHTML = '<p style="padding:24px;text-align:center;color:#888">No matches.</p>';
            return;
        }
        const sim = (d) => (1 - d).toFixed(3);
        container.innerHTML = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width:60%">Result</th>
                        <th>Source</th>
                        <th>Agent</th>
                        <th>Similarity</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.hits.map((h) => `
                        <tr>
                            <td><div style="font-weight:600;margin-bottom:4px">${esc(h.title || '(untitled)')}</div>
                                <div style="color:#555;font-size:13px">${esc((h.body || '').substring(0, 300))}${(h.body || '').length > 300 ? '…' : ''}</div>
                            </td>
                            <td>${esc(h.source || '—')}</td>
                            <td>${esc(h.agent || '—')}</td>
                            <td><span class="status-badge">${sim(h.distance)}</span></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }

    async function search(e) {
        e.preventDefault();
        const query = document.getElementById('search-query').value.trim();
        const n = document.getElementById('search-n').value;
        if (!query) return;
        const container = document.getElementById('search-results');
        if (container) container.innerHTML = '<p style="padding:24px;text-align:center">Searching...</p>';
        try {
            const resp = await fetch(`${API}?q=${encodeURIComponent(query)}&n=${n}`);
            const data = await resp.json();
            renderSearchResults(data);
        } catch (err) {
            console.error('Search failed:', err);
            if (container) container.innerHTML = '<p style="padding:24px;color:red">Search failed.</p>';
        }
    }

    async function addEntry(e) {
        e.preventDefault();
        const title = document.getElementById('add-title').value.trim();
        const body = document.getElementById('add-body').value.trim();
        const tagsStr = document.getElementById('add-tags').value.trim();
        const tags = tagsStr ? tagsStr.split(',').map((t) => t.trim()).filter(Boolean) : [];
        if (!body) return;
        try {
            const resp = await fetch(API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, body, tags, source: 'manual' }),
            });
            if (resp.status === 401) {
                alert('You need to authenticate via the agent token before adding entries. Use join.py or send the Authorization header.');
                return;
            }
            document.getElementById('add-title').value = '';
            document.getElementById('add-body').value = '';
            document.getElementById('add-tags').value = '';
            fetchRecent();
            fetchStats();
        } catch (err) {
            console.error('Add failed:', err);
        }
    }

    async function deleteEntry(id) {
        if (!confirm('Delete this knowledge entry?')) return;
        try {
            await fetch(`${API}/${id}`, { method: 'DELETE' });
            fetchRecent();
            fetchStats();
        } catch (err) {
            console.error('Delete failed:', err);
        }
    }

    // --- Edit (task 5.18) ---
    const editPanel = document.getElementById('edit-entry');
    const editForm = editPanel.querySelector('form');
    const editError = editPanel.querySelector('.project-form-error');
    let editingId = null;

    async function openEdit(id) {
        try {
            const resp = await fetch(`${API}/${id}`);
            if (!resp.ok) throw new Error(resp.status);
            const entry = await resp.json();
            editingId = entry.id;
            editForm.elements.title.value = entry.title || '';
            editForm.elements.body.value = entry.body || '';
            let tags = [];
            try { tags = JSON.parse(entry.tags || '[]'); } catch (_) { tags = []; }
            editForm.elements.tags.value = tags.join(', ');
            editError.hidden = true;
            editPanel.hidden = false;
            editPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            editForm.elements.body.focus();
        } catch (err) {
            alert('Could not load this entry.');
        }
    }

    editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const tagsStr = editForm.elements.tags.value.trim();
        const payload = {
            title: editForm.elements.title.value.trim(),
            body: editForm.elements.body.value.trim(),
            tags: tagsStr ? tagsStr.split(',').map((t) => t.trim()).filter(Boolean) : [],
        };
        try {
            const resp = await fetch(`${API}/${editingId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (resp.status === 401) { location = '/login?next=/knowledge'; return; }
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.message || (data.details || []).join(', ') || resp.statusText);
            editPanel.hidden = true;
            fetchRecent();
        } catch (err) {
            editError.textContent = err.message;
            editError.hidden = false;
        }
    });
    editForm.querySelector('[data-cancel]').addEventListener('click', () => { editPanel.hidden = true; });

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action="delete"]');
        if (btn) deleteEntry(btn.dataset.id);
        const edit = e.target.closest('[data-action="edit"]');
        if (edit) openEdit(edit.dataset.id);
    });

    function init() {
        fetchStats();
        fetchRecent();
        setInterval(() => { fetchStats(); fetchRecent(); }, 30000);
        const sf = document.getElementById('search-form');
        if (sf) sf.addEventListener('submit', search);
        const af = document.getElementById('add-form');
        if (af) af.addEventListener('submit', addEntry);
    }

    document.addEventListener('DOMContentLoaded', init);
})();