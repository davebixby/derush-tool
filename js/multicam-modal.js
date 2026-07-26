// ─── Multi-cam detection modal + groups management ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// --- MULTI-CAM ---

function _syncBadge(method) {
    return '<span style="font-size:0.7em;background:#1e3a8a;color:#93c5fd;border-radius:4px;padding:1px 6px;font-weight:600;white-space:nowrap;">📼 TC</span>';
}

let _mcPollTimer = null;
let _mcGroups = {proposals: [], groups: []};
let _mcSelected = new Set();
let _mcLastClickIdx = -1;
let _mcSortedProposals = [];
let _mcSelectedValid = new Set();
let _mcLastClickIdxValid = -1;
let _mcGroupsList = [];

async function openMulticamModal() {
    if (!currentProjectId) return;
    document.getElementById('multicamModal').style.display = 'flex';
    await Promise.all([refreshMulticam(), loadSonConfig(), refreshLtcSummary()]);
    // Resume polling if a job is currently running
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/multicam/status`);
        const j = await r.json();
        if (j.status === 'running') startMulticamPolling();
    } catch(e) {}
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/decode_ltc/status`);
        const j = await r.json();
        if (j.status === 'running') {
            document.getElementById('ltcDecodeBtn').disabled = true;
            document.getElementById('ltcDecodeForceBtn').disabled = true;
            document.getElementById('ltcProgress').style.display = '';
            _startLtcPolling();
        }
    } catch(e) {}
}

async function loadSonConfig() {
    if (!currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/son`);
        if (!r.ok) return;
        const d = await r.json();
        document.getElementById('sonDirInput').value = d.son_dir || '';
        const stEl = document.getElementById('sonStatus');
        if (d.count) {
            stEl.textContent = `${d.count} fichier(s) BWF indexé(s) — sync TC activée`;
            stEl.style.color = '#10b981';
        } else if (d.son_dir) {
            stEl.textContent = 'Dossier configuré mais aucun fichier BWF avec TC trouvé';
            stEl.style.color = '#f59e0b';
        } else {
            stEl.textContent = '';
        }
    } catch(e) {}
}

async function scanSonDir() {
    const son_dir = (document.getElementById('sonDirInput').value || '').trim();
    if (!son_dir) { alert('Indiquez un dossier son.'); return; }
    const btn = document.getElementById('sonScanBtn');
    const stEl = document.getElementById('sonStatus');
    btn.disabled = true; btn.textContent = 'Scan…';
    stEl.style.color = 'var(--dim)'; stEl.textContent = 'Scan en cours…';
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/scan_son`, {
            method: 'POST', body: JSON.stringify({son_dir})
        });
        const d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.error || 'Erreur');
        if (d.count) {
            stEl.textContent = `${d.count} fichier(s) BWF trouvé(s) avec TC — sync TC activée`;
            stEl.style.color = '#10b981';
        } else {
            stEl.textContent = 'Aucun fichier BWF avec timecode BEXT trouvé dans ce dossier';
            stEl.style.color = '#f59e0b';
        }
    } catch(e) {
        stEl.textContent = 'Erreur : ' + e.message;
        stEl.style.color = 'var(--red, #ef4444)';
    } finally {
        btn.disabled = false; btn.textContent = 'Scanner';
    }
}

async function refreshMulticam() {
    if (!currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/multicam`);
        _mcGroups = await r.json();
    } catch(e) {
        _mcGroups = {proposals: [], groups: []};
    }
    renderMulticamContent();
}

function renderMulticamContent() {
    const el = document.getElementById('mcContent');
    const clipById = {};
    (clips || []).forEach(c => clipById[c.id] = c);

    // Sort proposals by score descending
    _mcSortedProposals = [...(_mcGroups.proposals || [])].sort((a, b) => (b.score || 0) - (a.score || 0));
    // Purge stale selection IDs
    const validIds = new Set(_mcSortedProposals.map(p => p.id));
    _mcSelected = new Set([..._mcSelected].filter(id => validIds.has(id)));

    const groups = _mcGroups.groups || [];

    if (!_mcSortedProposals.length && !groups.length) {
        el.innerHTML = `<p style="color:var(--dim);font-size:0.85em;text-align:center;padding:20px 0;">Aucun groupe détecté. Cliquez sur « Lancer la détection » pour analyser le projet.</p>`;
        return;
    }

    function _clipRows(g) {
        return (g.clip_ids || []).map(cid => {
            const c = clipById[cid];
            const off = (g.offsets && g.offsets[cid] != null) ? g.offsets[cid] : 0;
            const offTxt = (off >= 0 ? '+' : '') + off.toFixed(2) + ' s';
            const label = c
                ? `${c.stem} <span style="color:var(--dim);font-size:0.85em;">· ${c.camera || '?'}</span>`
                : `<span style="color:var(--red);">${cid}</span>`;
            return `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px dashed rgba(255,255,255,.06);">
                <span style="font-size:0.85em;">${label}</span>
                <span style="font-family:monospace;color:var(--accent);font-size:0.82em;">${offTxt}</span>
            </div>`;
        }).join('');
    }

    let html = '';

    // ── Proposals (selectable, sorted by score)
    if (_mcSortedProposals.length) {
        const nSel = _mcSelected.size;
        html += `<div style="display:flex;justify-content:space-between;align-items:center;margin:4px 0 10px;">
            <h3 style="font-size:0.82em;color:var(--accent);margin:0;text-transform:uppercase;letter-spacing:.05em;">
                À valider (${_mcSortedProposals.length}) · trié par score ▼
            </h3>
            <div style="display:flex;gap:6px;align-items:center;">
                <span id="mcSelCount" style="font-size:0.78em;color:var(--dim);min-width:90px;text-align:right;">${nSel ? `${nSel} sélectionné(s)` : 'Clic / Shift+clic'}</span>
                <button id="mcAcceptSelBtn" onclick="mcAcceptSelected()" class="btn-primary" style="font-size:0.78em;padding:3px 10px;" ${nSel ? '' : 'disabled'}>✓ Valider (${nSel})</button>
                <button id="mcRejectSelBtn" onclick="mcRejectSelected()" style="font-size:0.78em;padding:3px 10px;" ${nSel ? '' : 'disabled'}>✕ Rejeter (${nSel})</button>
            </div>
        </div>`;
        html += _mcSortedProposals.map((g, idx) => {
            const scorePct = Math.round((g.score || 0) * 100);
            const scoreCol = scorePct >= 80 ? '#10b981' : scorePct >= 65 ? '#f59e0b' : '#9ca3af';
            const isSel = _mcSelected.has(g.id);
            const syncBadge = _syncBadge(g.sync_method);
            return `<div class="mc-prop-row${isSel ? ' mc-prop-sel' : ''}"
                         onclick="mcPropClick(event,'${g.id}',${idx})"
                         title="Clic = sélectionner · Shift+clic = sélectionner plage">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                    <span style="font-size:1.05em;font-weight:700;color:${scoreCol};min-width:40px;">${scorePct}%</span>
                    <span style="font-size:0.8em;color:var(--dim);">${(g.clip_ids||[]).length} clips</span>
                    ${syncBadge}
                    <div style="flex:1;"></div>
                    <button onclick="event.stopPropagation();acceptMulticam('${g.id}')" class="btn-primary" style="font-size:0.75em;padding:2px 9px;" title="Valider">✓</button>
                    <button onclick="event.stopPropagation();rejectMulticam('${g.id}')" style="font-size:0.75em;padding:2px 9px;" title="Rejeter">✕</button>
                </div>
                ${_clipRows(g)}
            </div>`;
        }).join('');
    }

    // ── Validated groups (selectable: clic / shift+clic, like proposals)
    _mcGroupsList = [...groups];
    const validGroupIds = new Set(_mcGroupsList.map(g => g.id));
    _mcSelectedValid = new Set([..._mcSelectedValid].filter(id => validGroupIds.has(id)));
    if (groups.length) {
        const nSelV = _mcSelectedValid.size;
        html += `<div style="display:flex;justify-content:space-between;align-items:center;margin:14px 0 8px;">
            <h3 style="font-size:0.82em;color:#10b981;margin:0;text-transform:uppercase;letter-spacing:.05em;">Groupes validés (${groups.length})</h3>
            <div style="display:flex;gap:6px;align-items:center;">
                <span id="mcSelCountValid" style="font-size:0.78em;color:var(--dim);min-width:90px;text-align:right;">${nSelV ? `${nSelV} sélectionné(s)` : 'Clic / Shift+clic'}</span>
                <button id="mcRejectSelValidBtn" onclick="mcRejectSelectedValid()" style="font-size:0.78em;padding:3px 10px;color:var(--red);" ${nSelV ? '' : 'disabled'}>🗑 Supprimer (${nSelV})</button>
            </div>
        </div>`;
        html += _mcGroupsList.map((g, idx) => {
            const scorePct = Math.round((g.score || 0) * 100);
            const scoreCol = scorePct >= 80 ? '#10b981' : scorePct >= 65 ? '#f59e0b' : '#9ca3af';
            const syncBadge = _syncBadge(g.sync_method);
            const isSel = _mcSelectedValid.has(g.id);
            return `<div class="mc-prop-row${isSel ? ' mc-prop-sel' : ''}"
                         onclick="mcValidClick(event,'${g.id}',${idx})"
                         title="Clic = sélectionner · Shift+clic = sélectionner plage">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                    <strong>${(g.clip_ids||[]).length} clips${scorePct ? ` · <span style="color:${scoreCol};">${scorePct}%</span>` : ''}</strong>
                    ${syncBadge}
                    <div style="flex:1;"></div>
                    <button onclick="event.stopPropagation();rejectMulticam('${g.id}')" style="font-size:0.82em;color:var(--red);" title="Supprimer ce groupe">🗑</button>
                </div>
                ${_clipRows(g)}
            </div>`;
        }).join('');
    }

    el.innerHTML = html;
}

function mcPropClick(e, gid, idx) {
    if (e.shiftKey && _mcLastClickIdx >= 0) {
        const lo = Math.min(_mcLastClickIdx, idx);
        const hi = Math.max(_mcLastClickIdx, idx);
        for (let i = lo; i <= hi; i++) {
            if (_mcSortedProposals[i]) _mcSelected.add(_mcSortedProposals[i].id);
        }
        // Don't update _mcLastClickIdx on shift-click (standard behavior)
    } else {
        if (_mcSelected.has(gid)) _mcSelected.delete(gid);
        else _mcSelected.add(gid);
        _mcLastClickIdx = idx;
    }
    renderMulticamContent();
}

async function mcAcceptSelected() {
    if (!_mcSelected.size) return;
    const ids = [..._mcSelected];
    for (const gid of ids) {
        await apiFetch(`/api/project/${currentProjectId}/multicam/accept`, {
            method: 'POST', body: JSON.stringify({group_id: gid})
        });
    }
    _mcSelected.clear(); _mcLastClickIdx = -1;
    await refreshMulticam(); renderAnglesPanel(); renderClipList();
}

async function mcRejectSelected() {
    if (!_mcSelected.size) return;
    showToast(`Rejet de ${_mcSelected.size} groupe(s)…`, 'warn', 2000);
    const ids = [..._mcSelected];
    for (const gid of ids) {
        await apiFetch(`/api/project/${currentProjectId}/multicam/reject`, {
            method: 'POST', body: JSON.stringify({group_id: gid})
        });
    }
    _mcSelected.clear(); _mcLastClickIdx = -1;
    await refreshMulticam(); renderAnglesPanel(); renderClipList();
}

function mcValidClick(e, gid, idx) {
    if (e.shiftKey && _mcLastClickIdxValid >= 0) {
        const lo = Math.min(_mcLastClickIdxValid, idx);
        const hi = Math.max(_mcLastClickIdxValid, idx);
        for (let i = lo; i <= hi; i++) {
            if (_mcGroupsList[i]) _mcSelectedValid.add(_mcGroupsList[i].id);
        }
    } else {
        if (_mcSelectedValid.has(gid)) _mcSelectedValid.delete(gid);
        else _mcSelectedValid.add(gid);
        _mcLastClickIdxValid = idx;
    }
    renderMulticamContent();
}

async function mcRejectSelectedValid() {
    if (!_mcSelectedValid.size) return;
    showToast(`Suppression de ${_mcSelectedValid.size} groupe(s) validé(s)…`, 'warn', 2000);
    const ids = [..._mcSelectedValid];
    for (const gid of ids) {
        await apiFetch(`/api/project/${currentProjectId}/multicam/reject`, {
            method: 'POST', body: JSON.stringify({group_id: gid})
        });
    }
    _mcSelectedValid.clear(); _mcLastClickIdxValid = -1;
    await refreshMulticam(); renderAnglesPanel(); renderClipList();
}

let _ltcPollTimer = null;

async function _refreshClipsAfterLtcDecode() {
    // Sans ça, `clips` (chargé une fois à l'entrée du projet) garde
    // ltc_tc_in_sec=null pour tous les clips après un décodage LTC : le
    // silencing mono-R (_setPlayerMonoR, cf. selectClip/audio-bwf.js) ne se
    // réactivait qu'après un redémarrage complet de l'app (rechargement des
    // clips depuis le serveur). On recharge la liste tout de suite et on
    // réapplique le routage audio si le clip actif vient d'être décodé.
    if (!currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/clips`);
        if (!r.ok) return;
        clips = await r.json();
        if (activeClip) {
            const updated = clips.find(c => c.id === activeClip.id);
            if (updated) {
                activeClip = updated;
                _setPlayerMonoR(updated.ltc_tc_in_sec != null);
            }
        }
    } catch(e) {}
}

async function refreshLtcSummary() {
    if (!currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/decode_ltc/summary`);
        const j = await r.json();
        const el = document.getElementById('ltcSummary');
        if (!el) return;
        if (j.decoded === 0) {
            el.textContent = `Jamais décodé · ${j.total} clips`;
        } else if (j.pending > 0) {
            el.textContent = `${j.with_ltc} avec LTC · ${j.without_ltc} sans · ${j.pending} non décodés`;
        } else {
            el.textContent = `${j.with_ltc}/${j.total} clips ont du LTC exploitable`;
        }
    } catch(e) {}
}

async function runDecodeLtc(force = false) {
    if (!currentProjectId) return;
    if (force) showToast('Re-décodage de tous les clips (forcé)…', 'warn', 2500);
    const btn = document.getElementById('ltcDecodeBtn');
    const fbtn = document.getElementById('ltcDecodeForceBtn');
    btn.disabled = true; fbtn.disabled = true;
    document.getElementById('ltcSummary').textContent = 'Démarrage…';
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/decode_ltc/start`, {
            method: 'POST',
            body: JSON.stringify({force: !!force})
        });
        const j = await r.json();
        if (!j.ok) {
            document.getElementById('ltcSummary').textContent = j.error || 'Erreur';
            btn.disabled = false; fbtn.disabled = false;
            return;
        }
        document.getElementById('ltcProgress').style.display = '';
        _startLtcPolling();
    } catch(e) {
        document.getElementById('ltcSummary').textContent = 'Erreur réseau';
        btn.disabled = false; fbtn.disabled = false;
    }
}

function _startLtcPolling() {
    if (_ltcPollTimer) clearInterval(_ltcPollTimer);
    _ltcPollTimer = setInterval(async () => {
        try {
            const r = await apiFetch(`/api/project/${currentProjectId}/decode_ltc/status`);
            const j = await r.json();
            if (j.status === 'running') {
                const done = j.done || 0, total = j.total || 1;
                const pct = total ? (done / total * 100) : 0;
                document.getElementById('ltcBar').style.width = pct + '%';
                document.getElementById('ltcCount').textContent = `${done} / ${total}`;
                document.getElementById('ltcCurrent').textContent = j.current ? `· ${j.current}` : '';
            } else {
                clearInterval(_ltcPollTimer); _ltcPollTimer = null;
                document.getElementById('ltcDecodeBtn').disabled = false;
                document.getElementById('ltcDecodeForceBtn').disabled = false;
                if (j.status === 'done') {
                    const dur = j.elapsed ? `${Math.round(j.elapsed)}s` : '';
                    document.getElementById('ltcSummary').textContent =
                        `Terminé en ${dur} : ${j.n_with_ltc} avec LTC · ${j.n_without_ltc} sans LTC` +
                        (j.n_skipped ? ` · ${j.n_skipped} déjà décodés` : '');
                    document.getElementById('ltcBar').style.width = '100%';
                    _refreshClipsAfterLtcDecode();
                    setTimeout(() => {
                        document.getElementById('ltcProgress').style.display = 'none';
                        refreshLtcSummary();
                    }, 4000);
                } else if (j.status === 'error') {
                    document.getElementById('ltcSummary').textContent = 'Erreur : ' + (j.error || 'inconnue');
                } else {
                    document.getElementById('ltcProgress').style.display = 'none';
                }
            }
        } catch(e) {
            clearInterval(_ltcPollTimer); _ltcPollTimer = null;
            document.getElementById('ltcDecodeBtn').disabled = false;
            document.getElementById('ltcDecodeForceBtn').disabled = false;
        }
    }, 800);
}

async function runMulticamDetect() {
    if (!currentProjectId) return;
    _mcSelected.clear(); _mcLastClickIdx = -1; _mcSortedProposals = [];
    _mcSelectedValid.clear(); _mcLastClickIdxValid = -1; _mcGroupsList = [];
    const btn = document.getElementById('mcDetectBtn');
    btn.disabled = true;
    document.getElementById('mcStatus').textContent = 'Démarrage…';
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/multicam/detect`, {method: 'POST', body: '{}'});
        const j = await r.json();
        if (!j.ok) {
            document.getElementById('mcStatus').textContent = j.error || 'Erreur';
            btn.disabled = false;
            return;
        }
        startMulticamPolling();
    } catch(e) {
        document.getElementById('mcStatus').textContent = 'Erreur réseau';
        btn.disabled = false;
    }
}

function _formatEta(seconds) {
    if (!seconds || seconds < 0 || !isFinite(seconds)) return '';
    if (seconds < 60) return `~${Math.round(seconds)} s restantes`;
    const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    return `~${m} min ${s.toString().padStart(2,'0')} s restantes`;
}

function _updateMcProgressUI(j) {
    const prog = document.getElementById('mcProgress');
    prog.style.display = '';
    const corrDone = j.corr_done || 0, corrTotal = j.corr_total || 0;
    const corrPct = corrTotal ? (corrDone / corrTotal * 100) : 0;
    document.getElementById('mcCorrBar').style.width = corrPct + '%';
    document.getElementById('mcCorrCount').textContent = corrTotal ? `${corrDone} / ${corrTotal}` : '—';

    let eta = null;
    if (j.phase === 'correlate' && corrDone > 0 && j.corr_started_at) {
        const elapsed = Date.now() / 1000 - j.corr_started_at;
        eta = (corrTotal - corrDone) * (elapsed / corrDone);
    }
    document.getElementById('mcEta').textContent = _formatEta(eta);
}

function startMulticamPolling() {
    if (_mcPollTimer) clearInterval(_mcPollTimer);
    document.getElementById('mcProgress').style.display = '';
    _mcPollTimer = setInterval(async () => {
        try {
            const r = await apiFetch(`/api/project/${currentProjectId}/multicam/status`);
            const j = await r.json();
            const stEl = document.getElementById('mcStatus');
            if (j.status === 'running') {
                const phaseLabel = {pairs: 'Préparation…', correlate: 'Appariement TC'}[j.phase] || 'Analyse';
                stEl.textContent = phaseLabel;
                _updateMcProgressUI(j);
            } else {
                clearInterval(_mcPollTimer); _mcPollTimer = null;
                document.getElementById('mcDetectBtn').disabled = false;
                if (j.status === 'done') {
                    stEl.textContent = `Terminé : ${j.group_count || 0} groupe(s) trouvé(s)`;
                    document.getElementById('mcProgress').style.display = 'none';
                    refreshMulticam();
                } else if (j.status === 'error') {
                    stEl.textContent = 'Erreur : ' + (j.error || 'inconnue');
                    document.getElementById('mcProgress').style.display = 'none';
                } else {
                    stEl.textContent = '';
                    document.getElementById('mcProgress').style.display = 'none';
                }
            }
        } catch(e) {
            clearInterval(_mcPollTimer); _mcPollTimer = null;
        }
    }, 1500);
}

async function acceptMulticam(gid) {
    await apiFetch(`/api/project/${currentProjectId}/multicam/accept`, {
        method: 'POST', body: JSON.stringify({group_id: gid}),
    });
    await refreshMulticam();
    renderAnglesPanel();
    renderClipList();
}

async function rejectMulticam(gid) {
    await apiFetch(`/api/project/${currentProjectId}/multicam/reject`, {
        method: 'POST', body: JSON.stringify({group_id: gid}),
    });
    await refreshMulticam();
    renderAnglesPanel();
    renderClipList();
}

