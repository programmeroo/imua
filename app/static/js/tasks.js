// Imua — Tasks Dashboard
(function () {
    'use strict';

    const API = '/api/tasks';
    let allTasks = [];
    let taskDetailModal = null;
    let taskDetailBody = null;

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    // --- Fetch tasks ---
    async function fetchTasks(statusFilter) {
        try {
            const url = statusFilter ? `${API}?status=${encodeURIComponent(statusFilter)}` : API;
            const resp = await fetch(url);
            const data = await resp.json();
            allTasks = data.tasks || [];
            renderTasks(allTasks);
            updateStats(allTasks);
        } catch (err) {
            console.error('Failed to fetch tasks:', err);
        }
    }

    // --- Render tasks table ---
    function renderTasks(tasks) {
        const tbody = document.getElementById('tasks-body');
        if (!tbody) return;

        if (!tasks.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="placeholder" style="text-align:center;padding:24px">No tasks found.</td></tr>';
            return;
        }

        tbody.innerHTML = tasks.map(t => `
            <tr class="task-row" data-id="${t.id}">
                <td>#${t.id}</td>
                <td><span class="task-type-badge">${esc(t.type || '—')}</span></td>
                <td class="cell-title">${esc(t.title || '(untitled)')}</td>
                <td><span class="priority-badge priority-${t.priority || 3}">${t.priority || 3}</span></td>
                <td>${esc(t.assigned_to || 'unassigned')}</td>
                <td><select class="filter-input task-status" data-id="${t.id}" aria-label="Status of task ${t.id}">${
                    STATUSES.map(s => `<option value="${s}"${s === (t.status || 'pending') ? ' selected' : ''}>${STATUS_LABELS[s] || s}</option>`).join('')
                }</select></td>
                <td class="cell-time">${timeAgo(t.created_at)}</td>
                <td class="msg-row-actions">
                    <button class="btn btn-sm" onclick="showTaskDetail(${t.id})">&#x1F441; View</button>
                    <button class="btn btn-sm btn-danger" onclick="taskDelete(${t.id})">Delete</button>
                </td>
            </tr>
        `).join('');
    }

    // --- Update stats ---
    function updateStats(tasks) {
        const pending = tasks.filter(t => t.status === 'pending').length;
        const inProgress = tasks.filter(t => t.status === 'in_progress').length;
        const completed = tasks.filter(t => t.status === 'completed').length;
        const failed = tasks.filter(t => t.status === 'failed').length;

        const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        el('stat-pending', pending);
        el('stat-in-progress', inProgress);
        el('stat-completed', completed);
        el('stat-failed', failed);
    }

    // --- Task detail ---
    window.showTaskDetail = function(id) {
        const task = allTasks.find(t => t.id === id);
        if (!task) return;

        const modal = document.getElementById('task-detail-modal');
        const body = document.getElementById('task-detail-body');
        if (!modal || !body) return;

        let paramsHtml = '', contextHtml = '', resultHtml = '';
        try { if (task.params) paramsHtml = `<pre class="detail-payload">${esc(JSON.stringify(JSON.parse(task.params), null, 2))}</pre>`; } catch {}
        try { if (task.context) contextHtml = `<pre class="detail-payload">${esc(JSON.stringify(JSON.parse(task.context), null, 2))}</pre>`; } catch {}
        if (task.result) resultHtml = `<div class="detail-body-text">${esc(task.result)}</div>`;

        let tagsHtml = '';
        try {
            const tags = JSON.parse(task.tags || '[]');
            if (tags.length) tagsHtml = `<div class="detail-tags">${tags.map(t => `<span class="cap-tag">${esc(t)}</span>`).join('')}</div>`;
        } catch {}

        body.innerHTML = `
            <div class="detail-field"><span class="detail-label">ID</span><span class="detail-value">#${task.id}</span></div>
            <div class="detail-field"><span class="detail-label">Type</span><span class="detail-value">${esc(task.type || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Title</span><span class="detail-value">${esc(task.title || '(untitled)')}</span></div>
            <div class="detail-field"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-${esc(task.status || 'pending')}">${esc(task.status || 'pending')}</span></span></div>
            <div class="detail-field"><span class="detail-label">Priority</span><span class="detail-value"><span class="priority-badge priority-${task.priority || 3}">${task.priority || 3}</span></span></div>
            <div class="detail-field"><span class="detail-label">Assigned To</span><span class="detail-value">${esc(task.assigned_to || 'unassigned')}</span></div>
            <div class="detail-field"><span class="detail-label">Created By</span><span class="detail-value">${esc(task.created_by || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Created</span><span class="detail-value">${esc(task.created_at || '—')}</span></div>
            ${task.assigned_at ? `<div class="detail-field"><span class="detail-label">Assigned</span><span class="detail-value">${esc(task.assigned_at)}</span></div>` : ''}
            ${task.completed_at ? `<div class="detail-field"><span class="detail-label">Completed</span><span class="detail-value">${esc(task.completed_at)}</span></div>` : ''}
            ${tagsHtml}
            ${paramsHtml ? `<div class="detail-field detail-field-full"><span class="detail-label">Parameters</span>${paramsHtml}</div>` : ''}
            ${contextHtml ? `<div class="detail-field detail-field-full"><span class="detail-label">Context</span>${contextHtml}</div>` : ''}
            ${resultHtml ? `<div class="detail-field detail-field-full"><span class="detail-label">Result</span>${resultHtml}</div>` : ''}
        `;

        modal.classList.remove('hidden');
    };

    // --- Admin actions (task 5.16): signed-in session; base.html adds the CSRF token ---
    const STATUSES = ['pending', 'in_progress', 'completed', 'failed', 'cancelled'];
    // "failed" re-queues the task (pending, unassigned) until its retries run out; "cancelled" stops it.
    const STATUS_LABELS = { in_progress: 'in progress', failed: 'failed (hub retries)', cancelled: 'cancelled (stop)' };

    async function send(method, url, body) {
        const opts = { method, headers: {} };
        if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
        const resp = await fetch(url, opts);
        if (resp.status === 401) { location = '/login?next=/tasks'; throw new Error('Signed out'); }
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.message || (data.details || []).join(', ') || resp.statusText);
        return data;
    }

    function reload() { fetchTasks(document.getElementById('status-filter')?.value || null); }

    document.addEventListener('change', async function (e) {
        if (!e.target.matches('.task-status')) return;
        try {
            await send('PATCH', `${API}/${e.target.dataset.id}`, { status: e.target.value });
        } catch (ex) { alert('Could not change status: ' + ex.message); }
        reload();
    });

    window.taskDelete = async function (id) {
        if (!confirm(`Delete task #${id}? This can't be undone.`)) return;
        try {
            await send('DELETE', `${API}/${id}`);
            reload();
        } catch (ex) { alert('Could not delete: ' + ex.message); }
    };

    document.getElementById('btn-task-prune').addEventListener('click', async () => {
        const day = document.getElementById('task-prune-before').value;
        if (!day) return alert('Pick a date first.');
        if (!confirm(`Delete completed, failed and cancelled tasks that finished before ${day}? ` +
                     'Pending and in-progress tasks are kept. This can\'t be undone.')) return;
        try {
            const r = await send('DELETE', `${API}?before=${encodeURIComponent(day)}`);
            alert(`Deleted ${r.deleted} finished task${r.deleted === 1 ? '' : 's'}.`);
            reload();
        } catch (ex) { alert('Could not delete: ' + ex.message); }
    });

    // --- Status filter ---
    document.addEventListener('change', function(e) {
        if (e.target.id === 'status-filter') {
            fetchTasks(e.target.value || null);
        }
    });

    // --- Modal close ---
    document.addEventListener('click', function(e) {
        if (e.target.matches('.modal-overlay') || e.target.matches('#task-modal-close')) {
            const modal = document.getElementById('task-detail-modal');
            if (modal) modal.classList.add('hidden');
        }
    });

    // --- Utilities ---
    function esc(str) { if (!str) return ''; const d = document.createElement('div'); d.textContent = str; return d.innerHTML; }
    function timeAgo(dt) {
        if (!dt) return '—';
        const now = new Date(); const then = new Date(dt);
        const sec = Math.floor((now - then) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    }

    // --- Init ---
    function init() {
        fetchTasks();
        setInterval(fetchTasks, 30000);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
