// Imua — Cron Jobs Dashboard
(function () {
    'use strict';

    const API = '/api/cron';
    let allJobs = [];

    function $(sel) { return document.querySelector(sel); }

    async function fetchJobs() {
        try {
            const resp = await fetch(API);
            const data = await resp.json();
            allJobs = data.cron_jobs || [];
            renderJobs(allJobs);
            updateStats(allJobs);
        } catch (err) {
            console.error('Failed to fetch cron jobs:', err);
        }
    }

    function renderJobs(jobs) {
        const tbody = document.getElementById('cron-body');
        if (!tbody) return;

        if (!jobs.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="placeholder" style="text-align:center;padding:24px">No cron jobs configured.</td></tr>';
            return;
        }

        tbody.innerHTML = jobs.map(j => {
            const statusIcon = j.status === 'active' ? '&#x1F7E2;' : j.status === 'paused' ? '&#x23F8;&#xFE0F;' : '&#x274C;';
            const lastRunStatus = j.last_run_status === 'success' ? '&#x2705;' : j.last_run_status === 'failed' ? '&#x274C;' : '—';
            return `
            <tr class="cron-row" data-id="${j.id}">
                <td class="cell-name"><a href="/cron/${j.id}" class="cron-link">${esc(j.name || 'Unnamed Job')}</a></td>
                <td><span class="schedule-display">${esc(j.schedule || '—')}</span>${j.schedule_human ? `<br><span class="schedule-human">${esc(j.schedule_human)}</span>` : ''}</td>
                <td>${esc(j.assigned_to || '—')}</td>
                <td class="cell-time">${timeAgo(j.last_run)}</td>
                <td class="cell-time">${j.next_run ? timeAgo(j.next_run) : '—'}</td>
                <td><span class="status-badge status-${esc(j.status || 'active')}">${statusIcon} ${esc(j.status || 'active')}</span></td>
                <td><span class="rate-badge">${j.success_count || 0}/${(j.success_count || 0) + (j.failure_count || 0) || 0}</span></td>
                <td><a href="/cron/${j.id}" class="btn btn-sm">&#x1F441; View</a></td>
            </tr>`;
        }).join('');

        const countEl = document.getElementById('job-count');
        if (countEl) countEl.textContent = `${jobs.length} jobs`;
    }

    function updateStats(jobs) {
        const total = jobs.length;
        const active = jobs.filter(j => j.status === 'active').length;
        const paused = jobs.filter(j => j.status === 'paused').length;
        const failed = jobs.filter(j => j.status === 'failed').length;

        const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        el('stat-total', total);
        el('stat-active', active);
        el('stat-paused', paused);
        el('stat-failed', failed);
    }

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

    function init() {
        fetchJobs();
        setInterval(fetchJobs, 30000);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
