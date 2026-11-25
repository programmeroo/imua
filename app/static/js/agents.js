// Imua — Agents Page
// Renders the agent roster and generates a copy-pasteable join command.

(function () {
    'use strict';

    const agentsGrid = document.getElementById('agents-grid');
    const statTotal = document.getElementById('stat-total');
    const statOnline = document.getElementById('stat-online');
    const statBusy = document.getElementById('stat-busy');
    const statOffline = document.getElementById('stat-offline');
    const nameInput = document.getElementById('invite-name');
    const capsInput = document.getElementById('invite-capabilities');
    const generateBtn = document.getElementById('invite-generate');
    const copyBtn = document.getElementById('invite-copy');
    const output = document.getElementById('invite-output');

    let hubUrl = location.origin;

    function esc(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function safeJSON(str) {
        if (!str) return [];
        try { return JSON.parse(str); } catch { return []; }
    }

    function timeAgo(dt) {
        const sec = Math.floor((new Date() - new Date(dt)) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    }

    function renderAgents(agents) {
        if (!agentsGrid) return;
        agentsGrid.innerHTML = '';
        if (!agents || agents.length === 0) {
            agentsGrid.innerHTML = `<div class="placeholder" style="grid-column:1/-1;text-align:center;padding:40px">No agents registered yet. Invite one below.</div>`;
            return;
        }
        agents.forEach((agent) => {
            const isOnline = agent.status === 'online';
            const lastSeen = agent.last_heartbeat ? timeAgo(agent.last_heartbeat) : 'never';
            const caps = safeJSON(agent.capabilities);
            const card = document.createElement('div');
            card.className = 'agent-card';
            card.innerHTML = `
                <div class="agent-card-header">
                    <span class="agent-status-dot ${isOnline ? 'online' : 'offline'}"></span>
                    <span class="agent-name">${esc(agent.display_name || agent.name)}</span>
                    <span class="agent-role">${esc(agent.role || 'worker')}</span>
                </div>
                <div class="agent-card-body">
                    <div class="agent-meta">
                        <span class="agent-meta-label">Host</span>
                        <span class="agent-meta-value">${esc(agent.host || '—')}</span>
                    </div>
                    <div class="agent-meta">
                        <span class="agent-meta-label">Status</span>
                        <span class="agent-meta-value ${isOnline ? 'text-emerald' : 'text-muted'}">${isOnline ? 'Online' : 'Offline'}</span>
                    </div>
                    <div class="agent-meta">
                        <span class="agent-meta-label">Last seen</span>
                        <span class="agent-meta-value">${esc(lastSeen)}</span>
                    </div>
                    ${caps.length ? `<div class="agent-caps">${caps.map((c) => `<span class="cap-tag">${esc(c)}</span>`).join('')}</div>` : ''}
                </div>
            `;
            agentsGrid.appendChild(card);
        });
    }

    function renderStats(agents) {
        const total = agents ? agents.length : 0;
        const online = (agents || []).filter((a) => a.status === 'online').length;
        const offline = (agents || []).filter((a) => a.status === 'offline').length;
        const busy = total - online - offline;
        if (statTotal) statTotal.textContent = total;
        if (statOnline) statOnline.textContent = online;
        if (statBusy) statBusy.textContent = busy;
        if (statOffline) statOffline.textContent = offline;
    }

    async function fetchAgents() {
        try {
            const resp = await fetch('/api/agents');
            const data = await resp.json();
            renderAgents(data.agents);
            renderStats(data.agents);
        } catch (err) {
            console.error('Failed to fetch agents:', err);
        }
    }

    function generateJoinCommand() {
        const name = (nameInput.value || '').trim();
        if (!name) {
            nameInput.focus();
            return;
        }
        const caps = (capsInput.value || '').trim();
        let cmd = `python scripts/join.py --name ${name} --hub ${hubUrl}`;
        if (caps) cmd += ` --capabilities ${caps}`;
        output.textContent = cmd;
        output.hidden = false;
        copyBtn.hidden = false;
    }

    function copyOutput() {
        navigator.clipboard.writeText(output.textContent).then(() => {
            copyBtn.textContent = 'Copied!';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
        });
    }

    async function fetchHubUrl() {
        try {
            const resp = await fetch('/api/health');
            const data = await resp.json();
            if (data.hub_url) hubUrl = data.hub_url;
        } catch (err) {
            console.error('Failed to fetch hub URL, falling back to location.origin:', err);
        }
    }

    function init() {
        fetchHubUrl();
        fetchAgents();
        setInterval(fetchAgents, 15000);
        if (generateBtn) generateBtn.addEventListener('click', generateJoinCommand);
        if (copyBtn) copyBtn.addEventListener('click', copyOutput);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
