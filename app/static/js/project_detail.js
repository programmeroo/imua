// Imua — Project detail page (task 6.7, docs/imua_projects_plan_v1.md §5.3)
// Tabs: Overview, Tasks, Documents, Knowledge, Cron, Agents. The URL hash (#task) picks the tab.
(function () {
    'use strict';

    const root = document.querySelector('.project-detail');
    const slug = root.dataset.slug;
    const panel = document.getElementById('project-panel');
    const tabs = Array.from(document.querySelectorAll('.project-tab'));
    const API = `/api/projects/${encodeURIComponent(slug)}`;
    const cache = {};

    function esc(str) {
        const d = document.createElement('div');
        d.textContent = str == null ? '' : String(str);
        return d.innerHTML;
    }

    function when(dt) {
        if (!dt) return '—';
        const t = new Date(dt);
        return isNaN(t) ? esc(dt) : t.toLocaleString();
    }

    function badge(status) {
        return status ? `<span class="status-badge status-${esc(status)}">${esc(status)}</span>` : '—';
    }

    function table(headers, rows, empty) {
        if (!rows.length) return `<div class="placeholder">${empty}</div>`;
        return `<div class="table-wrapper"><table class="data-table"><thead><tr>${
            headers.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${
            rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    }

    // Per item type: table columns, how to render one row, and the empty-tab message.
    const VIEWS = {
        task: [['Title', 'Status', 'Assigned to', 'Priority', 'Created'], t => [
            esc(t.title || t.type), badge(t.status), esc(t.assigned_to || '—'), esc(t.priority), when(t.created_at),
        ], 'No tasks in this project yet.'],
        document: [['File', 'Size', 'Uploaded', 'Status'], d => [
            `<a href="/api/documents/${d.id}/download">${esc(d.filename)}</a>`,
            `${Math.max(1, Math.round((d.size || 0) / 1024))} KB`, when(d.created_at),
            d.archived ? badge('archived') : badge('active'),
        ], 'No documents in this project yet.'],
        knowledge: [['Title', 'Excerpt', 'Source', 'Agent', 'Added'], k => [
            esc(k.title || '—'), esc((k.body || '').slice(0, 120)) + ((k.body || '').length > 120 ? '…' : ''),
            esc(k.source), esc(k.agent || '—'), when(k.created_at),
        ], 'No knowledge entries in this project yet.'],
        cron: [['Name', 'Schedule', 'Status', 'Assigned to', 'Last run'], c => [
            `<a href="/cron/${c.id}">${esc(c.name)}</a>`, esc(c.schedule_human || c.schedule), badge(c.status),
            esc(c.assigned_to || '—'), when(c.last_run),
        ], 'No cron jobs in this project yet.'],
    };

    async function getJSON(url) {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(resp.status);
        return resp.json();
    }

    async function overview() {
        const p = await getJSON(API);
        const counts = [['task', 'Tasks'], ['document', 'Documents'], ['knowledge', 'Knowledge'], ['cron', 'Cron']]
            .map(([k, label]) => `<a class="stat-card project-stat" href="#${k}">
                <span class="stat-value">${p.counts[k] || 0}</span><span class="stat-label">${label}</span></a>`)
            .join('');
        return `<div class="stats-grid">${counts}</div>
            <div class="project-facts">
                <div><span class="project-fact-label">Agents</span>${p.agents.length
                    ? p.agents.map(a => `<span class="project-chip">${esc(a)}</span>`).join(' ')
                    : '<span class="project-muted">No agents yet</span>'}</div>
                <div><span class="project-fact-label">Created</span>${when(p.created_at)}${
                    p.created_by ? ' by ' + esc(p.created_by) : ''}</div>
                <div><span class="project-fact-label">Updated</span>${when(p.updated_at)}</div>
            </div>`;
    }

    // --- Adding and removing items and agents (task 6.8b) ---
    const archived = root.dataset.status === 'archived';
    const SOURCES = {  // where to find items that could be added, and how to label them
        task: ['/api/tasks', d => d.tasks, t => t.title || t.type],
        document: ['/api/documents', d => d.documents, x => x.filename],
        knowledge: ['/api/knowledge/recent?limit=100', d => d.entries, k => k.title || (k.body || '').slice(0, 60)],
        cron: ['/api/cron', d => d.cron_jobs, c => c.name],
    };
    const NAMES = { task: 'task', document: 'document', knowledge: 'knowledge entry', cron: 'cron job', agents: 'agent' };

    function removeButton(kind, id) {
        return `<button class="btn btn-sm" data-remove="${kind}" data-id="${esc(id)}">Remove</button>`;
    }

    function addBar(kind, options) {
        if (archived) return '<p class="project-muted">This project is archived. Unarchive it to add items.</p>';
        if (!options.length) return `<p class="project-muted">Nothing else to add.</p>`;
        return `<div class="project-add-bar"><select class="form-input" data-add-select="${kind}">${
            options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('')
        }</select><button class="btn btn-primary btn-sm" data-add="${kind}">Add ${NAMES[kind]}</button></div>`;
    }

    async function itemsView(kind) {
        const [mine, all] = await Promise.all([getJSON(`${API}/items?type=${kind}`), getJSON(SOURCES[kind][0])]);
        const [, pick, label] = SOURCES[kind];
        const options = (pick(all) || []).filter(i => i.project !== slug).map(i =>
            [i.id, `${label(i)}${i.project ? `  (in ${i.project}; will move)` : ''}`]);
        const [headers, row, empty] = VIEWS[kind];
        return addBar(kind, options) + table([...headers, ''],
            mine.items.map(i => [...row(i), removeButton(kind, i.id)]), empty);
    }

    async function agentsView() {
        const [p, all] = await Promise.all([getJSON(API), getJSON('/api/agents')]);
        const list = all.agents || all;
        const byName = Object.fromEntries(list.map(a => [a.name, a]));
        const options = list.filter(a => !p.agents.includes(a.name)).map(a => [a.name, a.display_name || a.name]);
        return addBar('agents', options) + table(['Agent', 'Status', 'Role', 'Last heartbeat', ''], p.agents.map(name => {
            const a = byName[name] || {};
            return [esc(a.display_name || name), badge(a.status || 'unknown'), esc(a.role || '—'), when(a.last_heartbeat),
                removeButton('agents', name)];
        }), 'No agents in this project yet.');
    }

    function itemUrl(kind, id) {
        return kind === 'agents' ? `${API}/agents/${encodeURIComponent(id)}` : `${API}/items/${kind}/${id}`;
    }

    panel.addEventListener('click', async (e) => {
        const add = e.target.closest('[data-add]');
        const remove = e.target.closest('[data-remove]');
        if (!add && !remove) return;
        const kind = (add || remove).dataset.add || (add || remove).dataset.remove;
        const id = add ? panel.querySelector(`[data-add-select="${kind}"]`).value : remove.dataset.id;
        if (remove && !confirm(`Remove this ${NAMES[kind]} from the project? It is not deleted.`)) return;
        try {
            await ImuaProjects.api(add ? 'PUT' : 'DELETE', itemUrl(kind, id));
            location.reload();  // refresh tab counts and lists
        } catch (ex) { alert(ex.message); }
    });

    async function render(tab) {
        tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        panel.innerHTML = '<div class="placeholder">Loading...</div>';
        try {
            if (!(tab in cache)) {
                if (tab === 'overview') cache[tab] = await overview();
                else if (tab === 'agents') cache[tab] = await agentsView();
                else cache[tab] = await itemsView(tab);
            }
            panel.innerHTML = cache[tab];
        } catch (err) {
            panel.innerHTML = '<div class="placeholder">Could not load this tab.</div>';
        }
    }

    function current() {
        const tab = location.hash.slice(1);
        return tabs.some(t => t.dataset.tab === tab) ? tab : 'overview';
    }

    // Admin controls (task 6.8): edit, archive/unarchive, delete.
    ImuaProjects.form('edit-project-form', document.getElementById('edit-project-btn'), async (fields) => {
        await ImuaProjects.api('PATCH', API, fields);
        location.reload();
    });

    const archiveBtn = document.getElementById('archive-project-btn');
    archiveBtn.addEventListener('click', async () => {
        const next = archiveBtn.dataset.status === 'active' ? 'archived' : 'active';
        try {
            await ImuaProjects.api('PATCH', API, { status: next });
            location.reload();
        } catch (ex) { alert(ex.message); }
    });

    document.getElementById('delete-project-btn').addEventListener('click', async () => {
        if (!confirm(`Delete project "${slug}"? This can't be undone.`)) return;
        try {
            await ImuaProjects.api('DELETE', API);
            location = '/projects';
        } catch (ex) {
            alert(ex.message.includes('still contains')
                ? 'This project still has tasks, documents, knowledge or cron jobs in it. ' +
                  'Remove or move them first, or archive the project instead.'
                : ex.message);
        }
    });

    tabs.forEach(t => t.addEventListener('click', () => { location.hash = t.dataset.tab; }));
    window.addEventListener('hashchange', () => render(current()));
    render(current());
})();
