// Imua — Live Dashboard
// Connects to WebSocket, renders agent cards, shows activity feed

(function () {
    'use strict';

    const WS_URL = `ws://${location.hostname}:${location.port}`;
    const API = {
        agents: '/api/agents',
        messages: (agent) => `/api/messages?to=${agent}&limit=10`,
    };

    let socket = null;

    // --- DOM refs ---
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const agentsGrid = document.getElementById('agents-grid');
    const activityFeed = document.getElementById('activity-feed');
    const statAgents = document.getElementById('stat-agents');
    const statMessages = document.getElementById('stat-messages');

    // --- WebSocket ---
    function connectWS() {
        socket = io(WS_URL, { query: { agent_name: 'dashboard' } });

        socket.on('connect', () => {
            addActivity('system', 'Dashboard connected', 'WebSocket live');
        });

        socket.on('message.new', (msg) => {
            addActivity(
                msg.sender === 'dashboard' ? 'system' : 'agent',
                `${msg.sender} → ${msg.recipient || 'broadcast'}`,
                msg.body ? msg.body.slice(0, 80) : '(no body)'
            );
        });

        socket.on('disconnect', () => {
            addActivity('alert', 'Dashboard disconnected', 'Reconnecting...');
            setTimeout(connectWS, 3000);
        });
    }

    // --- Activity Feed ---
    function addActivity(type, title, meta) {
        if (!activityFeed) return;
        const item = document.createElement('div');
        item.className = 'activity-item';
        item.innerHTML = `
            <span class="activity-dot ${type}"></span>
            <div class="activity-body">
                <div class="activity-title">${esc(title)}</div>
                <div class="activity-meta">${esc(meta)}</div>
            </div>
        `;
        activityFeed.prepend(item);
        // Keep max 20 items
        while (activityFeed.children.length > 20) {
            activityFeed.lastChild.remove();
        }
    }

    // --- Agent Cards ---
    function renderAgentCards(agents) {
        if (!agentsGrid) return;
        agentsGrid.innerHTML = '';
        if (!agents || agents.length === 0) {
            agentsGrid.innerHTML = `<div class="placeholder" style="grid-column:1/-1;text-align:center;padding:40px">No agents registered yet. Register one to see it here.</div>`;
            return;
        }
        agents.forEach((agent) => {
            const card = document.createElement('div');
            card.className = 'agent-card';
            const isOnline = agent.status === 'online';
            const lastSeen = agent.last_heartbeat
                ? timeAgo(agent.last_heartbeat)
                : 'never';
            const caps = safeJSON(agent.capabilities);
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
                    ${caps.length ? `<div class="agent-caps">${caps.map(c => `<span class="cap-tag">${esc(c)}</span>`).join('')}</div>` : ''}
                </div>
            `;
            agentsGrid.appendChild(card);
        });
    }

    // --- Fetch Agents ---
    async function fetchAgents() {
        try {
            const resp = await fetch(API.agents);
            const data = await resp.json();
            renderAgentCards(data.agents);
            const onlineCount = (data.agents || []).filter((a) => a.status === 'online').length;
            if (statAgents) statAgents.textContent = onlineCount;
        } catch (err) {
            console.error('Failed to fetch agents:', err);
        }
    }

    // --- Utilities ---
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
        const now = new Date();
        const then = new Date(dt);
        const sec = Math.floor((now - then) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    }

    // --- Issues tiles (severity summary) ---
    const ISSUES_API = '/api/issues/summary';
    const SEVERITIES = ['info', 'warning', 'error', 'critical'];

    async function fetchIssueSummary() {
        try {
            const resp = await fetch(ISSUES_API);
            const data = await resp.json();
            const summary = data.summary || {};
            let totalActive = 0;
            SEVERITIES.forEach((sev) => {
                const el = document.getElementById(`sev-${sev}-count`);
                if (!el) return;
                let n = 0;
                // Sum across all sources for this severity.
                Object.values(summary).forEach((bySev) => {
                    n += (bySev[sev] || 0);
                });
                el.textContent = n;
                totalActive += n;
            });
            const badge = document.getElementById('issues-badge');
            if (badge) badge.textContent = `${totalActive} active`;
        } catch (err) {
            console.error('Failed to fetch issue summary:', err);
        }
    }

    // --- Init ---
    function init() {
        // Version comes from the server-rendered sidebar tag (base.html), never hardcoded.
        const version = document.querySelector('.version')?.textContent || '';
        addActivity('system', 'Dashboard loaded', `Imua ${version}`.trim());
        fetchAgents();
        fetchIssueSummary();
        connectWS();
        // Refresh agents list every 15s, issues every 10s
        setInterval(fetchAgents, 15000);
        setInterval(fetchIssueSummary, 10000);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
