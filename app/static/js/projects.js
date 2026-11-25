// Imua — Projects list (task 6.6, docs/imua_projects_plan_v1.md §5.3)
(function () {
    'use strict';

    const grid = document.getElementById('projects-grid');
    const archivedGrid = document.getElementById('archived-grid');
    const archivedSection = document.getElementById('archived-section');
    const total = document.getElementById('projects-total');

    const COUNTS = [
        ['task', 'Tasks'],
        ['document', 'Documents'],
        ['knowledge', 'Knowledge'],
        ['cron', 'Cron'],
    ];

    function esc(str) {
        const d = document.createElement('div');
        d.textContent = str == null ? '' : String(str);
        return d.innerHTML;
    }

    function card(p) {
        const agents = p.agents.length
            ? p.agents.map(a => `<span class="project-chip">${esc(a)}</span>`).join('')
            : '<span class="project-muted">No agents yet</span>';
        const counts = COUNTS.map(([key, label]) =>
            `<div class="project-count"><span class="project-count-value">${p.counts[key] || 0}</span>` +
            `<span class="project-count-label">${label}</span></div>`).join('');
        return `
            <a class="project-card${p.status === 'archived' ? ' archived' : ''}" href="/projects/${encodeURIComponent(p.slug)}">
                <div class="project-card-head">
                    <span class="project-name">${esc(p.name)}</span>
                    <span class="project-slug">${esc(p.slug)}</span>
                </div>
                <p class="project-desc">${p.description ? esc(p.description) : '<span class="project-muted">No description</span>'}</p>
                <div class="project-agents">${agents}</div>
                <div class="project-counts">${counts}</div>
            </a>`;
    }

    async function load() {
        let projects;
        try {
            const resp = await fetch('/api/projects');
            projects = (await resp.json()).projects || [];
        } catch (err) {
            grid.innerHTML = '<div class="placeholder projects-empty">Could not load projects.</div>';
            return;
        }
        const active = projects.filter(p => p.status !== 'archived');
        const archived = projects.filter(p => p.status === 'archived');

        total.textContent = `${active.length} active`;
        grid.innerHTML = active.length
            ? active.map(card).join('')
            : '<div class="placeholder projects-empty">No projects yet. A project groups tasks, documents, ' +
              'knowledge and cron jobs, and the agents working on them.</div>';
        archivedSection.hidden = archived.length === 0;
        archivedGrid.innerHTML = archived.map(card).join('');
    }

    // New project (task 6.8): create, then go to its page.
    ImuaProjects.form('new-project-form', document.getElementById('new-project-btn'), async (fields) => {
        const p = await ImuaProjects.api('POST', '/api/projects', fields);
        location = '/projects/' + encodeURIComponent(p.slug);
    });

    document.addEventListener('DOMContentLoaded', load);
})();
