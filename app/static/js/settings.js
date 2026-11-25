// Imua — Settings Page
(function () {
    'use strict';

    function $(sel) { return document.querySelector(sel); }

    async function loadSettings() {
        await loadSystemInfo();
        await loadVaultInfo();
    }

    async function loadSystemInfo() {
        const infoBody = document.getElementById('system-info');
        if (!infoBody) return;

        try {
            const resp = await fetch('/api/health');
            const health = await resp.json();

            let agentsCount = 0, tasksCount = 0, messagesCount = 0, secretsCount = 0;

            try {
                const aResp = await fetch('/api/agents');
                const aData = await aResp.json();
                agentsCount = aData.count || 0;
            } catch {}

            try {
                const tResp = await fetch('/api/tasks');
                const tData = await tResp.json();
                tasksCount = tData.count || 0;
            } catch {}

            infoBody.innerHTML = `
                <div class="detail-field"><span class="detail-label">Version</span><span class="detail-value">${esc(health.version || '0.1.0')}</span></div>
                <div class="detail-field"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-delivered">&#x2705; ${esc(health.status || 'ok')}</span></span></div>
                <div class="detail-field"><span class="detail-label">Registered Agents</span><span class="detail-value">${agentsCount}</span></div>
                <div class="detail-field"><span class="detail-label">Total Tasks</span><span class="detail-value">${tasksCount}</span></div>
                <div class="detail-field"><span class="detail-label">Host</span><span class="detail-value">${esc(health.hub_url || window.location.origin)}</span></div>
                <div class="detail-field"><span class="detail-label">Database</span><span class="detail-value">SQLite</span></div>
                <div class="detail-field"><span class="detail-label">WebSocket</span><span class="detail-value"><span class="status-badge status-delivered">&#x1F7E2; Connected</span></span></div>
            `;
        } catch (err) {
            infoBody.innerHTML = '<div class="placeholder">Failed to load system information.</div>';
        }
    }

    async function loadVaultInfo() {
        const vaultBody = document.getElementById('vault-info');
        if (!vaultBody) return;

        try {
            const resp = await fetch('/api/vault/secrets');
            const data = await resp.json();
            const secrets = data.secrets || [];

            if (!secrets.length) {
                vaultBody.innerHTML = '<div class="placeholder">No secrets stored in the vault. Use the Secrets API to add one.</div>';
                return;
            }

            vaultBody.innerHTML = `
                <div class="detail-field"><span class="detail-label">Total Secrets</span><span class="detail-value">${secrets.length}</span></div>
                <div class="detail-field" style="flex-direction:column;align-items:flex-start;gap:8px;">
                    <span class="detail-label">Stored Secrets</span>
                    <div class="secret-list">${secrets.map(s => `<span class="cap-tag">${esc(s.name || s)}</span>`).join('')}</div>
                </div>
            `;
        } catch (err) {
            vaultBody.innerHTML = '<div class="placeholder">Vault not accessible.</div>';
        }
    }

    // Preferences: Theme toggle
    const themeSelect = document.getElementById('pref-theme');
    if (themeSelect) {
        themeSelect.addEventListener('change', function() {
            document.documentElement.setAttribute('data-theme', this.value);
            localStorage.setItem('imua-theme', this.value);
        });
        const saved = localStorage.getItem('imua-theme');
        if (saved) {
            themeSelect.value = saved;
            document.documentElement.setAttribute('data-theme', saved);
        }
    }

    // Preferences: Auto-refresh toggle
    const refreshCheck = document.getElementById('pref-autorefresh');
    const intervalSelect = document.getElementById('pref-interval');
    if (refreshCheck) {
        refreshCheck.addEventListener('change', function() {
            localStorage.setItem('imua-autorefresh', this.checked);
        });
        const saved = localStorage.getItem('imua-autorefresh');
        if (saved !== null) refreshCheck.checked = saved === 'true';
    }
    if (intervalSelect) {
        intervalSelect.addEventListener('change', function() {
            localStorage.setItem('imua-refresh-interval', this.value);
        });
        const saved = localStorage.getItem('imua-refresh-interval');
        if (saved) intervalSelect.value = saved;
    }

    // The operator key is no longer kept in the browser (task 5.9): admin actions
    // use the signed-in session. Remove any key left from earlier versions.
    try { localStorage.removeItem('imua-operator-key'); } catch (e) { /* storage unavailable */ }

    function esc(str) { if (!str) return ''; const d = document.createElement('div'); d.textContent = str; return d.innerHTML; }

    function init() {
        loadSettings();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
