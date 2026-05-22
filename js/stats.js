// ─── Stats dashboard projet ────────────────────────────────────────────────
// Fetch /api/project/<pid>/stats et rend des cards + barres horizontales.

async function openStatsModal() {
    if (!currentProjectId) return;
    document.getElementById('statsModal').style.display = 'flex';
    const body = document.getElementById('statsBody');
    body.innerHTML = '<span style="color:var(--dim);">Chargement…</span>';
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/stats`);
        if (!r.ok) { body.innerHTML = '<span style="color:var(--red);">Erreur</span>'; return; }
        const d = await r.json();
        body.innerHTML = _renderStats(d);
    } catch(e) {
        body.innerHTML = '<span style="color:var(--red);">Erreur réseau</span>';
    }
}

function closeStatsModal() {
    document.getElementById('statsModal').style.display = 'none';
}

function _statBar(label, value, total, color) {
    const pct = total > 0 ? Math.round(value / total * 100) : 0;
    return `<div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;font-size:0.85em;">
        <span style="width:140px;color:var(--text);">${escapeHtml(label)}</span>
        <div style="flex:1;height:14px;background:rgba(0,0,0,.3);border-radius:3px;overflow:hidden;position:relative;">
            <div style="width:${pct}%;height:100%;background:${color};transition:width .3s;"></div>
        </div>
        <span style="width:60px;text-align:right;font-family:monospace;color:var(--dim);">${value} (${pct}%)</span>
    </div>`;
}

function _statCard(label, value, color) {
    return `<div style="background:rgba(167,139,250,.06);border:1px solid rgba(167,139,250,.18);border-radius:8px;padding:12px 16px;flex:1;min-width:120px;text-align:center;">
        <div style="font-size:0.7em;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;">${escapeHtml(label)}</div>
        <div style="font-size:1.6em;font-weight:700;color:${color || 'var(--accent)'};">${value}</div>
    </div>`;
}

function _renderStats(d) {
    const t = d.totals || {};
    const cardsHtml = `<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px;">
        ${_statCard('Clips totaux', t.clips || 0)}
        ${_statCard('Annotés', t.clips_touched || 0, '#34d399')}
        ${_statCard('Non touchés', t.clips_untouched || 0, '#6b6b80')}
        ${_statCard('Rejetés (X)', t.clips_rejected || 0, '#ef4444')}
        ${_statCard('Validés ✓', t.clips_validated || 0, '#34d399')}
        ${_statCard('À revoir', t.clips_to_review || 0, '#f59e0b')}
        ${_statCard('Markers', t.markers || 0)}
        ${_statCard('Tags uniques', t.unique_tags || 0)}
    </div>`;

    // Progression globale
    const progressPct = t.clips ? Math.round(t.clips_touched / t.clips * 100) : 0;
    const progressHtml = `<div style="margin-bottom:18px;background:rgba(0,0,0,.3);border-radius:8px;padding:14px 16px;">
        <div style="font-size:0.85em;color:var(--dim);margin-bottom:6px;">Progression du dérushage</div>
        <div style="height:12px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;position:relative;">
            <div style="width:${progressPct}%;height:100%;background:linear-gradient(90deg,#7c3aed,var(--accent));transition:width .3s;"></div>
        </div>
        <div style="text-align:right;font-size:0.78em;color:var(--accent);margin-top:4px;font-weight:600;">${progressPct}% (${t.clips_touched}/${t.clips})</div>
    </div>`;

    // Distribution rating
    const rd = d.rating_dist || {};
    const totRated = (rd['3']||0)+(rd['2']||0)+(rd['1']||0)+(rd['X']||0)+(rd['none']||0);
    const ratingHtml = `<h3 style="color:var(--accent);font-size:0.85em;margin:14px 0 8px;text-transform:uppercase;letter-spacing:.06em;">Distribution des ratings</h3>
        ${_statBar('⭐⭐⭐ Top', rd['3']||0, totRated, '#fcd34d')}
        ${_statBar('⭐⭐ Bien', rd['2']||0, totRated, '#a78bfa')}
        ${_statBar('⭐ OK', rd['1']||0, totRated, '#9ca3af')}
        ${_statBar('❌ À couper', rd['X']||0, totRated, '#ef4444')}
        ${_statBar('Sans rating', rd['none']||0, totRated, '#444')}`;

    // Markers par catégorie
    const cc = d.cat_counts || {};
    const totCat = Object.values(cc).reduce((a,b) => a+b, 0);
    const catLabels = {'3':'⭐⭐⭐ Top','2':'⭐⭐ Bien','1':'⭐ OK','X':'❌ À couper','T':'⚠️ Image','S':'⚠️ Son','D':'📌 Note'};
    const catColors = {'3':'#fcd34d','2':'#a78bfa','1':'#9ca3af','X':'#ef4444','T':'#3b82f6','S':'#10b981','D':'#f59e0b'};
    const catHtml = `<h3 style="color:var(--accent);font-size:0.85em;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em;">Markers par catégorie</h3>
        ${Object.keys(catLabels).map(k => _statBar(catLabels[k], cc[k]||0, totCat || 1, catColors[k])).join('')}`;

    // Par user
    const users = d.by_user || [];
    const usersHtml = users.length ? `<h3 style="color:var(--accent);font-size:0.85em;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em;">Activité par utilisateur</h3>
        <table style="width:100%;font-size:0.82em;border-collapse:collapse;">
            <thead><tr style="border-bottom:1px solid var(--border);color:var(--dim);text-align:left;font-size:0.78em;text-transform:uppercase;letter-spacing:.05em;">
                <th style="padding:6px 4px;">Utilisateur</th>
                <th style="padding:6px 4px;text-align:right;">Clips</th>
                <th style="padding:6px 4px;text-align:right;">Markers</th>
                <th style="padding:6px 4px;text-align:right;">Ratings</th>
                <th style="padding:6px 4px;text-align:right;">Tags</th>
            </tr></thead><tbody>
            ${users.map(u => `<tr style="border-bottom:1px solid rgba(255,255,255,.05);">
                <td style="padding:6px 4px;"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${u.color||'#888'};margin-right:6px;"></span>${escapeHtml(u.name)}</td>
                <td style="padding:6px 4px;text-align:right;font-family:monospace;">${u.clips_touched||0}</td>
                <td style="padding:6px 4px;text-align:right;font-family:monospace;">${u.markers||0}</td>
                <td style="padding:6px 4px;text-align:right;font-family:monospace;">${u.ratings||0}</td>
                <td style="padding:6px 4px;text-align:right;font-family:monospace;">${u.tags||0}</td>
            </tr>`).join('')}
        </tbody></table>` : '';

    // Top tags
    const topTags = d.top_tags || [];
    const tagsHtml = topTags.length ? `<h3 style="color:var(--accent);font-size:0.85em;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em;">Top tags</h3>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
        ${topTags.map(t => `<span style="background:rgba(167,139,250,.15);color:#c4b5fd;border:1px solid rgba(167,139,250,.3);border-radius:12px;padding:3px 10px;font-size:0.82em;">${escapeHtml(t.tag)} <strong style="color:var(--accent);">${t.count}</strong></span>`).join('')}
        </div>` : '';

    // Par caméra
    const cams = d.cam_counts || {};
    const totCams = Object.values(cams).reduce((a,b) => a+b, 0);
    const camHtml = Object.keys(cams).length ? `<h3 style="color:var(--accent);font-size:0.85em;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em;">Répartition par caméra</h3>
        ${Object.entries(cams).sort((a,b)=>b[1]-a[1]).map(([cam, n]) => _statBar('📷 ' + (cam||'?'), n, totCams, '#a78bfa')).join('')}` : '';

    // Par jour
    const days = d.day_counts || {};
    const totDays = Object.values(days).reduce((a,b) => a+b, 0);
    const dayHtml = Object.keys(days).length ? `<h3 style="color:var(--accent);font-size:0.85em;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em;">Clips par jour de tournage</h3>
        ${Object.entries(days).sort((a,b)=>a[0].localeCompare(b[0])).map(([day, n]) => _statBar('📅 ' + day, n, totDays, '#60a5fa')).join('')}` : '';

    return cardsHtml + progressHtml + ratingHtml + catHtml + usersHtml + tagsHtml + camHtml + dayHtml;
}
