// ─── Changelog / nouveautés modal ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── Changelog / nouveautés ─────────────────────────────────────────
let _appVersion = null;
let _changelogEntries = [];

async function _loadVersionAndChangelog() {
    try {
        const r = await fetch('/api/version');
        const d = await r.json();
        _appVersion = d.version;
        const lbl = document.getElementById('appVersionLabel');
        if (lbl) lbl.textContent = 'v' + _appVersion;
        // Si la version actuelle diffère de la dernière vue → modal auto
        const lastSeen = localStorage.getItem('derush_last_seen_version');
        if (lastSeen && lastSeen !== _appVersion) {
            await openChangelogModal(true);  // mode "what's new"
        } else if (!lastSeen) {
            // Premier lancement jamais — pas de modal auto, on mémorise juste
            localStorage.setItem('derush_last_seen_version', _appVersion);
        }
    } catch(e) {}
}

async function openChangelogModal(onlyNew = false) {
    document.getElementById('changelogModal').style.display = 'flex';
    const body = document.getElementById('changelogBody');
    const intro = document.getElementById('changelogIntro');
    body.innerHTML = '<span style="color:var(--dim);">Chargement…</span>';
    try {
        const r = await fetch('/api/changelog');
        const d = await r.json();
        _changelogEntries = d.entries || [];
        let entries = _changelogEntries;
        const lastSeen = localStorage.getItem('derush_last_seen_version');
        if (onlyNew && lastSeen) {
            const idx = entries.findIndex(e => e.version === lastSeen);
            if (idx > 0) entries = entries.slice(0, idx);  // garde toutes les versions depuis lastSeen (excluse)
        }
        if (!entries.length) {
            body.innerHTML = '<span style="color:var(--dim);">Aucune nouveauté.</span>';
        } else {
            intro.textContent = onlyNew
                ? `${entries.length} nouvelle${entries.length>1?'s':''} version${entries.length>1?'s':''} depuis ta dernière utilisation.`
                : `Historique des évolutions · version actuelle v${d.current_version}`;
            body.innerHTML = entries.map(e => `
                <div style="margin-bottom:24px;">
                    <h3 style="color:var(--accent);font-size:1em;margin-bottom:4px;">v${escapeHtml(e.version)}</h3>
                    <div style="font-size:0.72em;color:var(--dim);margin-bottom:10px;">${escapeHtml(e.date)}</div>
                    <div class="changelog-content">${_renderMarkdown(e.body)}</div>
                </div>
            `).join('');
        }
        // Marque la version actuelle comme vue
        if (_appVersion) localStorage.setItem('derush_last_seen_version', _appVersion);
    } catch(e) {
        body.innerHTML = '<span style="color:var(--red);">Erreur de chargement.</span>';
    }
}

function closeChangelogModal() {
    document.getElementById('changelogModal').style.display = 'none';
}

// Markdown léger : ## ### **bold** *italic* `code` listes — suffisant pour un changelog
function _renderMarkdown(md) {
    let html = escapeHtml(md);
    // Convert ### headers
    html = html.replace(/^### (.+)$/gm, '<h4 style="color:var(--text);font-size:0.92em;margin:14px 0 6px;">$1</h4>');
    // **bold**
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // `code`
    html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,.06);padding:1px 5px;border-radius:3px;font-size:0.88em;">$1</code>');
    // Listes : lignes commençant par -
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.+<\/li>\n?)+/g, m => '<ul style="margin:4px 0 8px 18px;font-size:0.88em;line-height:1.55;">' + m + '</ul>');
    return html;
}

