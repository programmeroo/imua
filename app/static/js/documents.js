// Imua — Documents Page
(function () {
    'use strict';

    const API = '/api/documents';
    let allDocuments = [];

    function esc(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function formatSize(bytes) {
        if (!bytes) return '0 B';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function timeAgo(dt) {
        if (!dt) return '—';
        const sec = Math.floor((new Date() - new Date(dt)) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    }

    async function fetchDocuments(archivedFilter) {
        try {
            const url = archivedFilter ? `${API}?archived=${archivedFilter}` : API;
            const resp = await fetch(url);
            const data = await resp.json();
            allDocuments = data.documents || [];
            renderDocuments(allDocuments);
            updateStats(allDocuments);
        } catch (err) {
            console.error('Failed to fetch documents:', err);
        }
    }

    function renderDocuments(docs) {
        const tbody = document.getElementById('documents-body');
        if (!tbody) return;

        if (!docs.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="placeholder" style="text-align:center;padding:24px">No documents found.</td></tr>';
            return;
        }

        tbody.innerHTML = docs.map((d) => `
            <tr data-id="${d.id}">
                <td>${esc(d.filename)}</td>
                <td>${formatSize(d.size)}</td>
                <td>${esc(d.uploaded_by || '—')}</td>
                <td>${timeAgo(d.created_at)}</td>
                <td><span class="status-badge status-${d.archived ? 'cancelled' : 'completed'}">${d.archived ? 'archived' : 'active'}</span></td>
                <td>
                    <a class="btn btn-sm" href="${API}/${d.id}/download">&#x2B07; Download</a>
                    <button class="btn btn-sm" data-action="${d.archived ? 'unarchive' : 'archive'}" data-id="${d.id}">
                        ${d.archived ? '&#x267A; Restore' : '&#x1F4E6; Archive'}
                    </button>
                </td>
            </tr>
        `).join('');
    }

    function updateStats(docs) {
        const total = docs.length;
        const archived = docs.filter((d) => d.archived).length;
        const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        el('stat-total', total);
        el('stat-archived', archived);
        el('stat-active', total - archived);
    }

    async function setArchived(id, action) {
        try {
            await fetch(`${API}/${id}/${action}`, { method: 'POST' });
            fetchDocuments(document.getElementById('archived-filter').value || null);
        } catch (err) {
            console.error(`Failed to ${action} document:`, err);
        }
    }

    async function uploadDocument(e) {
        e.preventDefault();
        const fileInput = document.getElementById('upload-file');
        const byInput = document.getElementById('upload-by');
        if (!fileInput.files.length) return;

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('uploaded_by', byInput.value || '');

        try {
            await fetch(API, { method: 'POST', body: formData });
            fileInput.value = '';
            byInput.value = '';
            fetchDocuments();
        } catch (err) {
            console.error('Failed to upload document:', err);
        }
    }

    document.addEventListener('change', (e) => {
        if (e.target.id === 'archived-filter') {
            fetchDocuments(e.target.value || null);
        }
    });

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (btn) setArchived(btn.dataset.id, btn.dataset.action);
    });

    function init() {
        fetchDocuments();
        setInterval(() => fetchDocuments(document.getElementById('archived-filter').value || null), 30000);
        const form = document.getElementById('upload-form');
        if (form) form.addEventListener('submit', uploadDocument);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
