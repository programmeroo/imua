// Imua — Messages Dashboard
(function () {
    'use strict';

    const API = { messages: '/api/messages' };
    let allMessages = [];
    let detailModal = null;
    let detailBody = null;

    function $(sel) { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    // --- Fetch messages ---
    async function fetchMessages() {
        // Fetch all senders' messages by iterating known agents
        try {
            const agentResp = await fetch('/api/agents');
            const agentData = await agentResp.json();
            const agents = agentData.agents || [];

            let combined = [];
            for (const agent of agents) {
                try {
                    const resp = await fetch(`/api/messages?to=${encodeURIComponent(agent.name)}&limit=100`);
                    const data = await resp.json();
                    if (data.messages) combined = combined.concat(data.messages);
                } catch { /* skip agent with no messages */ }
            }

            // Deduplicate by id
            const seen = new Set();
            allMessages = combined.filter(m => {
                if (seen.has(m.id)) return false;
                seen.add(m.id);
                return true;
            });

            // Sort by created_at descending
            allMessages.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
            renderMessages(allMessages);
            updateStats(allMessages);
        } catch (err) {
            console.error('Failed to fetch messages:', err);
        }
    }

    // --- Render messages table ---
    function renderMessages(messages) {
        const tbody = document.getElementById('messages-body');
        if (!tbody) return;

        if (!messages.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="placeholder" style="text-align:center;padding:24px">No messages found.</td></tr>';
            return;
        }

        tbody.innerHTML = messages.map(msg => `
            <tr class="msg-row" data-id="${msg.id}" onclick="showMessageDetail(${msg.id})">
                <td onclick="event.stopPropagation()"><input type="checkbox" class="msg-select" value="${msg.id}" aria-label="Select message ${msg.id}"></td>
                <td><span class="msg-type-badge type-${esc(msg.msg_type || 'direct')}">${esc(msg.msg_type || 'direct')}</span></td>
                <td class="cell-sender">${esc(msg.sender || '—')}</td>
                <td class="cell-recipient">${esc(msg.recipient || 'broadcast')}</td>
                <td class="cell-topic">${esc(msg.topic || '—')}</td>
                <td class="cell-time">${timeAgo(msg.created_at)}</td>
                <td><span class="status-badge status-${esc(msg.status || 'pending')}">${esc(msg.status || 'pending')}</span></td>
                <td class="msg-row-actions" onclick="event.stopPropagation()">
                    ${msg.status !== 'read' ? `<button class="btn btn-sm" onclick="msgMarkRead([${msg.id}])">Mark read</button>` : ''}
                    <button class="btn btn-sm btn-danger" onclick="msgDelete([${msg.id}])">Delete</button>
                </td>
            </tr>
        `).join('');

        document.getElementById('msg-count').textContent = `${messages.length} messages`;
    }

    // --- Update stats ---
    function updateStats(messages) {
        const total = messages.length;
        const broadcasts = messages.filter(m => m.msg_type === 'broadcast' || m.recipient === 'all').length;
        const pending = messages.filter(m => m.status === 'pending').length;
        const uniqueSenders = new Set(messages.map(m => m.sender)).size;

        const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        el('stat-total', total);
        el('stat-broadcast', broadcasts);
        el('stat-pending', pending);
        el('stat-unique-senders', uniqueSenders);
    }

    // --- Message detail ---
    window.showMessageDetail = function(id) {
        const msg = allMessages.find(m => m.id === id);
        if (!msg) return;

        const modal = document.getElementById('message-detail-modal');
        const body = document.getElementById('message-detail-body');
        if (!modal || !body) return;

        let payloadHtml = '';
        if (msg.payload) {
            try {
                const parsed = JSON.parse(msg.payload);
                payloadHtml = `<pre class="detail-payload">${esc(JSON.stringify(parsed, null, 2))}</pre>`;
            } catch {
                payloadHtml = `<pre class="detail-payload">${esc(msg.payload)}</pre>`;
            }
        }

        body.innerHTML = `
            <div class="detail-field"><span class="detail-label">ID</span><span class="detail-value">#${msg.id}</span></div>
            <div class="detail-field"><span class="detail-label">Type</span><span class="detail-value">${esc(msg.msg_type || 'direct')}</span></div>
            <div class="detail-field"><span class="detail-label">Sender</span><span class="detail-value">${esc(msg.sender || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Recipient</span><span class="detail-value">${esc(msg.recipient || 'broadcast')}</span></div>
            <div class="detail-field"><span class="detail-label">Topic</span><span class="detail-value">${esc(msg.topic || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-${esc(msg.status || 'pending')}">${esc(msg.status || 'pending')}</span></span></div>
            <div class="detail-field"><span class="detail-label">Timestamp</span><span class="detail-value">${esc(msg.created_at || '—')}</span></div>
            <div class="detail-field detail-field-full"><span class="detail-label">Body</span><div class="detail-body-text">${esc(msg.body || '(empty)')}</div></div>
            ${payloadHtml ? `<div class="detail-field detail-field-full"><span class="detail-label">Payload</span>${payloadHtml}</div>` : ''}
        `;

        const actions = document.getElementById('message-detail-actions');
        if (actions) {
            actions.innerHTML = (msg.status !== 'read'
                ? `<button class="btn btn-sm" onclick="msgMarkRead([${msg.id}])">Mark read</button>` : '') +
                `<button class="btn btn-sm btn-danger" onclick="msgDelete([${msg.id}])">Delete</button>`;
        }
        modal.classList.remove('hidden');
    };

    // --- Admin actions (task 5.14): signed-in session; base.html adds the CSRF token ---
    async function send(method, url, body) {
        const opts = { method, headers: {} };
        if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
        const resp = await fetch(url, opts);
        if (resp.status === 401) { location = '/login?next=/messages'; throw new Error('Signed out'); }
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.message || (data.details || []).join(', ') || resp.statusText);
        return data;
    }

    async function afterChange() {
        const modal = document.getElementById('message-detail-modal');
        if (modal) modal.classList.add('hidden');
        await fetchMessages();
        applyFilters();
    }

    function selectedIds() {
        return Array.from($$('.msg-select:checked')).map(c => Number(c.value));
    }

    window.msgMarkRead = async function (ids) {
        if (!ids.length) return alert('Select at least one message.');
        try {
            await send('POST', '/api/messages/read', { ids });
            await afterChange();
        } catch (e) { alert('Could not mark read: ' + e.message); }
    };

    window.msgDelete = async function (ids) {
        if (!ids.length) return alert('Select at least one message.');
        if (!confirm(`Delete ${ids.length} message${ids.length > 1 ? 's' : ''}? This can't be undone.`)) return;
        try {
            for (const id of ids) await send('DELETE', `/api/messages/${id}`);
            await afterChange();
        } catch (e) { alert('Could not delete: ' + e.message); }
    };

    async function pruneOlder() {
        const day = document.getElementById('prune-before').value;
        if (!day) return alert('Pick a date first.');
        if (!confirm(`Delete ALL messages from before ${day}? This can't be undone.`)) return;
        try {
            const r = await send('DELETE', `/api/messages?before=${encodeURIComponent(day)}`);
            alert(`Deleted ${r.deleted} message${r.deleted === 1 ? '' : 's'}.`);
            await afterChange();
        } catch (e) { alert('Could not delete: ' + e.message); }
    }

    document.getElementById('btn-mark-selected').addEventListener('click', () => msgMarkRead(selectedIds()));
    document.getElementById('btn-delete-selected').addEventListener('click', () => msgDelete(selectedIds()));
    document.getElementById('btn-prune').addEventListener('click', pruneOlder);
    document.getElementById('msg-select-all').addEventListener('change', (e) => {
        $$('.msg-select').forEach(c => { c.checked = e.target.checked; });
    });

    // --- Filters ---
    function applyFilters() {
        const sender = (document.getElementById('filter-sender')?.value || '').toLowerCase();
        const recipient = (document.getElementById('filter-recipient')?.value || '').toLowerCase();
        const type = document.getElementById('filter-type')?.value || '';
        const status = document.getElementById('filter-status')?.value || '';

        let filtered = allMessages;
        if (sender) filtered = filtered.filter(m => (m.sender || '').toLowerCase().includes(sender));
        if (recipient) filtered = filtered.filter(m => (m.recipient || '').toLowerCase().includes(recipient));
        if (type) filtered = filtered.filter(m => (m.msg_type || '') === type);
        if (status) filtered = filtered.filter(m => (m.status || '') === status);

        renderMessages(filtered);
    }

    // --- Modal close ---
    document.addEventListener('click', function(e) {
        if (e.target.matches('.modal-overlay') || e.target.matches('#modal-close')) {
            const modal = document.getElementById('message-detail-modal');
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
        fetchMessages();
        const btn = document.getElementById('btn-apply-filters');
        if (btn) btn.addEventListener('click', applyFilters);
        // Auto-refresh every 30s
        setInterval(fetchMessages, 30000);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
