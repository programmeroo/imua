// Imua — Cron Job Detail Page
(function () {
    'use strict';

    const page = document.querySelector('.cron-detail-page');
    if (!page) return;
    const jobId = page.dataset.jobId;
    const API = `/api/cron/${jobId}`;

    function $(sel) { return document.querySelector(sel); }

    async function fetchJobDetail() {
        try {
            const resp = await fetch(API);
            const job = await resp.json();
            renderDetail(job);
        } catch (err) {
            console.error('Failed to fetch cron job:', err);
        }
    }

    function renderDetail(job) {
        // Header
        const nameEl = document.getElementById('job-name');
        const descEl = document.getElementById('job-description');
        if (nameEl) nameEl.textContent = job.name || 'Unnamed Job';
        if (descEl) descEl.textContent = job.description || '';

        // Info section
        const infoBody = document.getElementById('job-info-body');
        if (infoBody) {
            const statusIcon = job.status === 'active' ? '&#x1F7E2;' : job.status === 'paused' ? '&#x23F8;&#xFE0F;' : '&#x274C;';
            infoBody.innerHTML = `
                <div class="detail-field"><span class="detail-label">ID</span><span class="detail-value">#${job.id}</span></div>
                <div class="detail-field"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-${esc(job.status || 'active')}">${statusIcon} ${esc(job.status || 'active')}</span></span></div>
                <div class="detail-field"><span class="detail-label">Schedule</span><span class="detail-value"><code>${esc(job.schedule || '—')}</code></span></div>
                <div class="detail-field"><span class="detail-label">Human Schedule</span><span class="detail-value">${esc(job.schedule_human || '—')}</span></div>
                <div class="detail-field"><span class="detail-label">Assigned To</span><span class="detail-value">${esc(job.assigned_to || '—')}</span></div>
                <div class="detail-field"><span class="detail-label">Last Run</span><span class="detail-value">${esc(job.last_run || 'never')}</span></div>
                <div class="detail-field"><span class="detail-label">Next Run</span><span class="detail-value">${esc(job.next_run || '—')}</span></div>
                <div class="detail-field"><span class="detail-label">Success Rate</span><span class="detail-value"><span class="rate-badge">${job.success_count || 0}/${(job.success_count || 0) + (job.failure_count || 0) || 0}</span></span></div>
                <div class="detail-field"><span class="detail-label">Created By</span><span class="detail-value">${esc(job.created_by || '—')}</span></div>
                <div class="detail-field"><span class="detail-label">Created At</span><span class="detail-value">${esc(job.created_at || '—')}</span></div>
            `;
        }

        // Agent section
        const agentBody = document.getElementById('job-agent-body');
        if (agentBody) {
            agentBody.innerHTML = `
                <div class="detail-field"><span class="detail-label">Agent</span><span class="detail-value">${esc(job.assigned_to || 'Unassigned')}</span></div>
                <div class="detail-field"><span class="detail-label">Description</span><span class="detail-value">${esc(job.description || 'No description')}</span></div>
            `;
        }

        // History
        const historyBody = document.getElementById('history-body');
        const historyCount = document.getElementById('history-count');
        const history = job.history || [];
        if (historyCount) historyCount.textContent = `${history.length} runs`;

        if (historyBody) {
            if (!history.length) {
                historyBody.innerHTML = '<tr><td colspan="5" class="placeholder" style="text-align:center;padding:24px">No execution history yet.</td></tr>';
            } else {
                historyBody.innerHTML = history.map(h => `
                    <tr>
                        <td class="cell-time">${esc(h.created_at || '—')}</td>
                        <td><span class="status-badge status-${esc(h.status || 'running')}">${esc(h.status || 'running')}</span></td>
                        <td>${h.duration_ms ? `${h.duration_ms}ms` : '—'}</td>
                        <td>${esc(h.triggered_by || 'schedule')}</td>
                        <td>${h.error ? `<span class="error-preview" title="${esc(h.error)}">&#x26A0;</span>` : '—'}</td>
                    </tr>
                `).join('');
            }
        }

        // Update toggle button
        const toggleBtn = document.getElementById('btn-toggle-pause');
        if (toggleBtn) {
            toggleBtn.textContent = job.status === 'active' ? '&#x23F8; Pause' : '&#x25B6; Resume';
            toggleBtn.onclick = () => togglePause(job);
        }
    }

    async function togglePause(job) {
        const newStatus = job.status === 'active' ? 'paused' : 'active';
        try {
            const resp = await fetch(API, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: newStatus }),
            });
            if (resp.ok) fetchJobDetail();
        } catch (err) {
            console.error('Failed to toggle job:', err);
        }
    }

    // Run now
    const runBtn = document.getElementById('btn-run-now');
    if (runBtn) {
        runBtn.addEventListener('click', async () => {
            try {
                await fetch(`${API}/run`, { method: 'POST' });
                fetchJobDetail();
            } catch (err) {
                console.error('Failed to trigger job:', err);
            }
        });
    }

    // Delete
    const deleteBtn = document.getElementById('btn-delete');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            if (!confirm('Delete this cron job? This cannot be undone.')) return;
            try {
                const resp = await fetch(API, { method: 'DELETE' });
                if (resp.ok) window.location.href = '/cron';
            } catch (err) {
                console.error('Failed to delete job:', err);
            }
        });
    }

    function esc(str) { if (!str) return ''; const d = document.createElement('div'); d.textContent = str; return d.innerHTML; }

    function init() {
        fetchJobDetail();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
