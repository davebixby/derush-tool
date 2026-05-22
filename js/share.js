// ─── Share link (review externe) ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── Share link (review externe) ────────────────────────────────────
let _shareState = null;  // {share: {token, url, created_at}, share_comments: {clip_id: [...]}}

// Toast non-bloquant : remplace alert() qui bloque l'event loop et fait crasher
// le watchdog backend (heartbeats ne partent plus pendant alert).
function showToast(msg, kind='info', durationMs=3500) {
    let host = document.getElementById('toastHost');
    if (!host) {
        host = document.createElement('div');
        host.id = 'toastHost';
        host.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
        document.body.appendChild(host);
    }
    const colors = {info:'#a78bfa', ok:'#34d399', err:'#ef4444', warn:'#f59e0b'};
    const t = document.createElement('div');
    t.style.cssText = `background:rgba(15,15,22,.95);border-left:3px solid ${colors[kind]||colors.info};color:#e0e0e8;padding:10px 16px;border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.6);font-size:0.85em;max-width:380px;transition:opacity .3s,transform .3s;opacity:0;transform:translateX(20px);pointer-events:auto;`;
    t.textContent = msg;
    host.appendChild(t);
    requestAnimationFrame(() => { t.style.opacity = '1'; t.style.transform = 'translateX(0)'; });
    setTimeout(() => {
        t.style.opacity = '0'; t.style.transform = 'translateX(20px)';
        setTimeout(() => t.remove(), 300);
    }, durationMs);
}

async function openShareModal() {
    document.getElementById('shareModal').style.display = 'flex';
    await _renderShareModal();
}

function closeShareModal() {
    document.getElementById('shareModal').style.display = 'none';
}

async function _refreshShareState() {
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/share/info`);
        _shareState = await r.json();
    } catch(e) { _shareState = null; }
}

async function _renderShareModal() {
    const body = document.getElementById('shareModalBody');
    body.innerHTML = '<span style="color:var(--dim);">Chargement…</span>';
    await _refreshShareState();
    const share = _shareState && _shareState.share;
    if (!share) {
        body.innerHTML = `
            <div style="background:rgba(0,0,0,.25);border-radius:8px;padding:14px;">
                <p style="font-size:0.88em;margin-bottom:12px;">Aucun lien actif pour ce projet.</p>
                <button class="btn-primary" onclick="createShare()" id="shareCreateBtn">🔗 Créer un lien</button>
            </div>`;
        return;
    }
    const commentsCount = Object.values(_shareState.share_comments || {}).reduce((n, arr) => n + arr.length, 0);
    body.innerHTML = `
        <div style="background:rgba(52,211,153,.08);border:1px solid rgba(52,211,153,.3);border-radius:8px;padding:14px;margin-bottom:12px;">
            <div style="font-size:0.78em;color:var(--green);font-weight:600;margin-bottom:8px;">✓ LIEN ACTIF</div>
            <div style="display:flex;gap:6px;align-items:center;">
                <input type="text" readonly value="${escapeHtml(share.url)}" id="shareUrlInput" style="flex:1;font-family:monospace;font-size:0.8em;background:var(--bg);padding:6px 8px;">
                <button onclick="_copyShareUrl()" id="shareCopyBtn">📋 Copier</button>
            </div>
            <div style="font-size:0.75em;color:var(--dim);margin-top:8px;">Créé le ${escapeHtml((share.created_at||'').replace('T',' '))} · ${commentsCount} commentaire${commentsCount>1?'s':''} reçu${commentsCount>1?'s':''}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button onclick="refreshShare()">🔄 Rafraîchir le contenu</button>
            <button onclick="pullShareComments(true)">📥 Récupérer commentaires</button>
            <button onclick="revokeShare()" style="color:var(--red);border-color:rgba(239,68,68,.3);margin-left:auto;">🗑 Révoquer</button>
        </div>
        <p style="font-size:0.74em;color:var(--dim);margin-top:12px;">Rafraîchir le contenu = re-push les markers/notes/thumbnails actuels vers le cloud (utile après de nouvelles annotations). Les commentaires retour sont aussi récupérés en tâche de fond toutes les ~10 min.</p>`;
}

async function createShare() {
    const btn = document.getElementById('shareCreateBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Génération… (jusqu\'à 30s pour gros projets)'; }
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/share/create`, {method: 'POST'});
        const d = await r.json();
        if (!d.ok) {
            showToast(d.error || 'Erreur création du lien', 'err', 5000);
            if (btn) { btn.disabled = false; btn.textContent = '🔗 Créer un lien'; }
            return;
        }
        showToast('Lien généré ✓', 'ok');
        await _renderShareModal();
    } catch(e) {
        showToast('Erreur : ' + e.message, 'err', 5000);
        if (btn) { btn.disabled = false; btn.textContent = '🔗 Créer un lien'; }
    }
}

async function refreshShare() {
    showToast('Rafraîchissement en cours…', 'info');
    await createShare();
}

async function revokeShare() {
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/share/revoke`, {method: 'POST'});
        const d = await r.json();
        if (d.ok) { showToast('Lien révoqué', 'ok'); await _renderShareModal(); }
    } catch(e) { showToast('Erreur : ' + e.message, 'err'); }
}

function _copyShareUrl() {
    const inp = document.getElementById('shareUrlInput');
    inp.select(); inp.setSelectionRange(0, 99999);
    try {
        navigator.clipboard.writeText(inp.value);
        const btn = document.getElementById('shareCopyBtn');
        const old = btn.textContent;
        btn.textContent = '✓ Copié';
        setTimeout(() => btn.textContent = old, 2000);
    } catch(e) { document.execCommand('copy'); }
}

async function pullShareComments(verbose) {
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/share/pull_comments`, {method: 'POST'});
        const d = await r.json();
        await _refreshShareState();
        if (activeClip) renderMultiUser();  // refresh la zone "Avis des autres"
        if (verbose) {
            if (d.ok) showToast(d.count > 0 ? `${d.count} nouveau${d.count>1?'x':''} commentaire${d.count>1?'s':''}` : 'Aucun nouveau commentaire', d.count > 0 ? 'ok' : 'info');
            else showToast('Erreur : ' + (d.error || 'inconnue'), 'err');
        }
        if (document.getElementById('shareModal').style.display !== 'none') _renderShareModal();
    } catch(e) {
        if (verbose) showToast('Erreur réseau', 'err');
    }
}

