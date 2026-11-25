// Imua — Issues Dashboard
// PR 2c: page route + table + detail modal + action buttons
(function () {
    'use strict';

    const API = '/api/issues';

    let allIssues = [];
    let currentDetailId = null;
    let refreshTimer = null;
    const REFRESH_INTERVAL_MS = 30000;

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    // The operator key used to be kept in localStorage for these actions. They now
    // use the signed-in session (task 5.9); remove any key left behind.
    try { localStorage.removeItem('imua-operator-key'); } catch (e) { /* storage unavailable */ }

    // --- Build query string from current filters ---
    function currentFilters() {
        return {
            status: $('#status-filter').value || null,
            severity: $('#severity-filter').value || null,
            source: $('#source-filter').value || null,
        };
    }

    // --- Fetch issues ---
    async function fetchIssues() {
        const f = currentFilters();
        const params = new URLSearchParams();
        // Map UI 'active' to default (server returns open+acknowledged when status omitted)
        if (f.status && f.status !== 'active') params.set('status', f.status);
        if (f.severity) params.set('severity', f.severity);
        if (f.source) params.set('source', f.source);
        params.set('limit', '200');

        try {
            const resp = await fetch(`${API}?${params}`);
            const data = await resp.json();
            allIssues = data.issues || [];
            renderIssues(allIssues);
            updateStats(allIssues);
            populateSourceFilter(allIssues);
        } catch (err) {
            console.error('Failed to fetch issues:', err);
            const tbody = $('#issues-body');
            if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="placeholder" style="text-align:center;padding:24px;color:var(--accent-error)">Failed to load issues. Is the Imua server running?</td></tr>';
        }
    }

    // --- Render table ---
    function renderIssues(issues) {
        const tbody = $('#issues-body');
        if (!tbody) return;

        if (!issues.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="placeholder" style="text-align:center;padding:24px;color:var(--text-tertiary)">No issues. The system is healthy (or instrumentation hasn\'t fired yet).</td></tr>';
            return;
        }

        tbody.innerHTML = issues.map(i => `
            <tr class="issue-row" data-id="${i.id}">
                <td>#${i.id}</td>
                <td><span class="severity-pill severity-pill-${esc(i.severity || 'info')}">${esc(i.severity || 'info')}</span></td>
                <td><span class="status-badge status-${esc(i.status || 'open')}">${esc(i.status || 'open')}</span></td>
                <td><span class="cap-tag">${esc(i.source || '—')}</span> <span style="color:var(--text-tertiary);font-size:12px;">${esc(i.type || '')}</span></td>
                <td class="cell-title">${esc(i.subject || '(global)')}</td>
                <td>${i.count || 1}</td>
                <td class="cell-time">${timeAgo(i.last_seen)}</td>
                <td><button class="btn btn-sm" onclick="showIssueDetail(${i.id})">&#x1F441; View</button></td>
            </tr>
        `).join('');
    }

    // --- Stats ---
    function updateStats(issues) {
        const open = issues.filter(i => i.status === 'open').length;
        const ack = issues.filter(i => i.status === 'acknowledged').length;
        const errCrit = issues.filter(i => (i.severity === 'error' || i.severity === 'critical') && (i.status === 'open' || i.status === 'acknowledged')).length;
        const since = Date.now() - 24 * 60 * 60 * 1000;
        const resolved24 = issues.filter(i => i.status === 'resolved' && i.resolved_at && new Date(i.resolved_at).getTime() >= since).length;

        const set = (id, v) => { const e = $('#' + id); if (e) e.textContent = v; };
        set('stat-open', open);
        set('stat-acknowledged', ack);
        set('stat-error', errCrit);
        set('stat-resolved-24h', resolved24);
    }

    // --- Populate source filter from data ---
    function populateSourceFilter(issues) {
        const sel = $('#source-filter');
        if (!sel) return;
        const current = sel.value;
        const sources = [...new Set(issues.map(i => i.source).filter(Boolean))].sort();
        // Keep the "All Sources" option
        sel.innerHTML = '<option value="">All Sources</option>' +
            sources.map(s => `<option value="${esc(s)}"${s === current ? ' selected' : ''}>${esc(s)}</option>`).join('');
    }

    // --- Detail modal ---
    window.showIssueDetail = async function(id) {
        currentDetailId = id;
        const modal = $('#issue-detail-modal');
        const body = $('#issue-detail-body');
        const footer = $('#issue-detail-footer');
        if (!modal || !body) return;

        body.innerHTML = '<div class="detail-loading">Loading...</div>';
        if (footer) footer.style.display = 'none';
        modal.classList.remove('hidden');

        try {
            const resp = await fetch(`${API}/${id}`);
            if (!resp.ok) {
                body.innerHTML = `<div class="detail-loading">Issue #${id} not found.</div>`;
                return;
            }
            const issue = await resp.json();
            renderDetail(issue);
            if (footer && (issue.status === 'open' || issue.status === 'acknowledged')) {
                footer.style.display = 'flex';
            }
        } catch (err) {
            console.error('Failed to fetch issue:', err);
            body.innerHTML = '<div class="detail-loading">Failed to load issue.</div>';
        }
    };

    function renderDetail(i) {
        const body = $('#issue-detail-body');
        if (!body) return;
        body.innerHTML = `
            <div class="detail-field"><span class="detail-label">ID</span><span class="detail-value">#${i.id}</span></div>
            <div class="detail-field"><span class="detail-label">Severity</span><span class="detail-value"><span class="severity-pill severity-pill-${esc(i.severity || 'info')}">${esc(i.severity || 'info')}</span></span></div>
            <div class="detail-field"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-${esc(i.status || 'open')}">${esc(i.status || 'open')}</span></span></div>
            <div class="detail-field"><span class="detail-label">Source</span><span class="detail-value">${esc(i.source || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Type</span><span class="detail-value">${esc(i.type || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Subject</span><span class="detail-value">${esc(i.subject || '(global)')}</span></div>
            <div class="detail-field"><span class="detail-label">Count</span><span class="detail-value">${i.count || 1}</span></div>
            <div class="detail-field"><span class="detail-label">First Seen</span><span class="detail-value">${esc(i.first_seen || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Last Seen</span><span class="detail-value">${esc(i.last_seen || '—')}</span></div>
            ${i.acknowledged_at ? `<div class="detail-field"><span class="detail-label">Acknowledged</span><span class="detail-value">${esc(i.acknowledged_at)} by ${esc(i.acknowledged_by || '—')}</span></div>` : ''}
            ${i.resolved_at ? `<div class="detail-field"><span class="detail-label">Resolved</span><span class="detail-value">${esc(i.resolved_at)}${i.resolution ? ' — ' + esc(i.resolution) : ''}</span></div>` : ''}
            ${i.detail ? `<div class="detail-field detail-field-full"><span class="detail-label">Detail</span><div class="detail-body-text">${esc(i.detail)}</div></div>` : ''}
            <div class="detail-field detail-field-full"><span class="detail-label">Fingerprint</span><span class="detail-value" style="font-family:monospace;font-size:11px;color:var(--text-tertiary)">${esc(i.fingerprint || '—')}</span></div>
        `;
    }

    // --- Action handlers ---
    async function performAction(action) {
        if (!currentDetailId) return;
        try {
            // Signed-in session; base.html adds the CSRF token to this request.
            const resp = await fetch(`${API}/${currentDetailId}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (resp.status === 401) {  // session expired
                window.location = '/login?next=' + encodeURIComponent(location.pathname + location.search);
                return;
            }
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                alert(`Action failed: ${err.message || err.error || resp.statusText}`);
                return;
            }
            // Refresh detail + table
            await showIssueDetail(currentDetailId);
            await fetchIssues();
        } catch (err) {
            console.error(`Action ${action} failed:`, err);
            alert(`Network error during ${action}.`);
        }
    }

    // --- Utilities ---
    function esc(str) {
        if (str === null || str === undefined) return '';
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

    function timeAgo(dt) {
        if (!dt) return '—';
        const then = new Date(dt);
        if (isNaN(then.getTime())) return '—';
        const sec = Math.floor((Date.now() - then.getTime()) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    }

    // --- Event wiring ---
    function init() {
        // Apply query-param-driven filters (for tile clicks on dashboard)
        const params = new URLSearchParams(window.location.search);
        if (params.has('severity')) $('#severity-filter').value = params.get('severity');
        if (params.has('status')) $('#status-filter').value = params.get('status');
        if (params.has('source')) $('#source-filter').value = params.get('source');

        // Filter changes
        ['status-filter', 'severity-filter', 'source-filter'].forEach(id => {
            const el = $('#' + id);
            if (el) el.addEventListener('change', fetchIssues);
        });

        // Refresh button
        const refreshBtn = $('#refresh-btn');
        if (refreshBtn) refreshBtn.addEventListener('click', fetchIssues);

        // Action buttons
        const ackBtn = $('#btn-acknowledge');
        const supBtn = $('#btn-suppress');
        const resBtn = $('#btn-resolve');
        if (ackBtn) ackBtn.addEventListener('click', () => performAction('acknowledge'));
        if (supBtn) supBtn.addEventListener('click', () => performAction('suppress'));
        if (resBtn) resBtn.addEventListener('click', () => performAction('resolve'));

        // Modal close handlers
        document.addEventListener('click', function (e) {
            if (e.target.matches('.modal-overlay') || e.target.matches('#issue-modal-close')) {
                const modal = $('#issue-detail-modal');
                if (modal) modal.classList.add('hidden');
            }
        });

        // ESC to close modals
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                $$('.modal:not(.hidden)').forEach(m => m.classList.add('hidden'));
            }
        });

        // Initial fetch + auto-refresh
        fetchIssues();
        refreshTimer = setInterval(fetchIssues, REFRESH_INTERVAL_MS);
    }

    document.addEventListener('DOMContentLoaded', init);
})();