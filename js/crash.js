// ─── Crash log viewer modal ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── Crash log viewer ───────────────────────────────────────────────
async function openCrashModal() {
    document.getElementById('crashModal').style.display = 'flex';
    const list = document.getElementById('crashList');
    list.innerHTML = '<span style="color:var(--dim);">Chargement…</span>';
    try {
        const r = await fetch('/api/crashes?limit=200');
        const d = await r.json();
        const crashes = (d.crashes || []).reverse(); // plus récent en haut
        if (!crashes.length) {
            list.innerHTML = '<span style="color:var(--dim);">Aucune erreur enregistrée. 🎉</span>';
            return;
        }
        list.innerHTML = crashes.map(c => {
            const ts = (c.ts || '').replace('T', ' ');
            const srcColor = c.source === 'js' ? '#fbbf24' : '#a78bfa';
            const srcLabel = c.source === 'js' ? 'JS' : 'PY';
            const loc = c.url ? `<div style="color:var(--dim);font-size:.92em;">${escapeHtml(c.url)}${c.line ? ':' + c.line : ''}</div>` : '';
            const stack = c.stack ? `<pre style="white-space:pre-wrap;color:var(--dim);font-size:.85em;margin-top:6px;max-height:200px;overflow:auto;">${escapeHtml(c.stack)}</pre>` : '';
            return `<div style="border-bottom:1px solid rgba(255,255,255,.06);padding:8px 4px;">
                <div style="display:flex;gap:8px;align-items:baseline;">
                    <span style="background:${srcColor};color:#000;padding:1px 6px;border-radius:3px;font-weight:700;font-size:.78em;">${srcLabel}</span>
                    <span style="color:var(--dim);">${escapeHtml(ts)}</span>
                    <span style="color:${srcColor};font-weight:600;">${escapeHtml(c.type || 'Error')}</span>
                </div>
                <div style="margin-top:4px;color:var(--text);">${escapeHtml(c.message || '')}</div>
                ${loc}
                ${stack}
            </div>`;
        }).join('');
    } catch(e) {
        list.innerHTML = '<span style="color:var(--red);">Erreur de chargement.</span>';
    }
}

function closeCrashModal() {
    document.getElementById('crashModal').style.display = 'none';
}

async function clearCrashes() {
    try { await fetch('/api/crashes/clear'); } catch(e) {}
    openCrashModal(); // recharge → liste vide
}

function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
