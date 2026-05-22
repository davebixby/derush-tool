// ─── Auto-détection de plans (scene change ffmpeg) ──────────────────────────
// Module externalisé. Fait apparaître les candidats sur la timeline comme losanges
// jaunes semi-transparents. Clic gauche = accepter (devient marker D), clic droit
// ou bouton du milieu = rejeter (mémorisé, ne re-suggérera pas au prochain scan).

let _autoDetected = {};        // {clip_id: {candidates: [...], scanned_at, threshold}}
let _autoDetectPoll = null;    // setInterval ID pendant le job

async function loadAutoDetected() {
    if (!currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/auto_detect`);
        const d = await r.json();
        _autoDetected = d.auto_detected || {};
    } catch(e) { _autoDetected = {}; }
}

function openAutoDetectModal() {
    document.getElementById('autoDetectModal').style.display = 'flex';
    _updateAutoDetectStats();
}

function closeAutoDetectModal() {
    document.getElementById('autoDetectModal').style.display = 'none';
    if (_autoDetectPoll) { clearInterval(_autoDetectPoll); _autoDetectPoll = null; }
}

function _updateAutoDetectStats() {
    const el = document.getElementById('adStats');
    if (!el) return;
    let total = 0, pending = 0, accepted = 0, rejected = 0, scannedClips = 0;
    for (const cid in _autoDetected) {
        scannedClips++;
        for (const c of (_autoDetected[cid].candidates || [])) {
            total++;
            if (c.status === 'pending') pending++;
            else if (c.status === 'accepted') accepted++;
            else if (c.status === 'rejected') rejected++;
        }
    }
    if (!total) {
        el.innerHTML = '<em>Aucun scan effectué pour ce projet.</em>';
    } else {
        el.innerHTML = `<strong>${scannedClips}</strong> clip(s) déjà scanné(s) · <strong>${pending}</strong> en attente · <span style="color:var(--green);">${accepted} acceptés</span> · <span style="color:var(--red);">${rejected} rejetés</span>`;
    }
}

async function startAutoDetect() {
    if (!currentProjectId) return;
    const scope = document.querySelector('input[name="adScope"]:checked').value;
    const threshold = parseFloat(document.getElementById('adThresh').value);
    let clip_ids = null;
    if (scope === 'active') {
        if (!activeClip) { showToast('Aucun clip sélectionné', 'err'); return; }
        clip_ids = [activeClip.id];
    }
    const btn = document.getElementById('adStartBtn');
    btn.disabled = true; btn.textContent = '⏳ Lancement…';
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/auto_detect/start`,
            {method: 'POST', body: JSON.stringify({threshold, clip_ids})});
        const d = await r.json();
        if (!d.ok) {
            showToast(d.error || 'Erreur', 'err');
            btn.disabled = false; btn.textContent = '🔍 Lancer la détection';
            return;
        }
        // Affiche progress + poll
        document.getElementById('adProgress').style.display = '';
        _autoDetectPoll = setInterval(_pollAutoDetectStatus, 1000);
    } catch(e) {
        showToast('Erreur réseau', 'err');
        btn.disabled = false; btn.textContent = '🔍 Lancer la détection';
    }
}

async function _pollAutoDetectStatus() {
    if (!currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/auto_detect/status`);
        const d = await r.json();
        const bar = document.getElementById('adProgressBar');
        const lbl = document.getElementById('adProgressLabel');
        if (d.status === 'running') {
            const pct = d.total > 0 ? Math.round(d.done / d.total * 100) : 0;
            bar.style.width = pct + '%';
            lbl.textContent = `${d.done}/${d.total} · ${d.current || ''}`;
        } else if (d.status === 'done') {
            clearInterval(_autoDetectPoll); _autoDetectPoll = null;
            bar.style.width = '100%';
            const n = d.new_candidates || 0;
            lbl.textContent = `✓ Terminé · ${n} nouveaux candidats`;
            const btn = document.getElementById('adStartBtn');
            btn.disabled = false; btn.textContent = '🔍 Re-scanner';
            if (n === 0) {
                // Feedback explicite : 0 candidats = sensibilité trop élevée pour ce contenu
                showToast(`0 candidat trouvé — essaie une sensibilité plus basse (0.05 ou moins) si tes clips sont des longs takes sans cuts secs`, 'warn', 7000);
                lbl.innerHTML = `<span style="color:var(--orange);">⚠ 0 candidat · baisse la sensibilité (slider à gauche) puis re-scan</span>`;
            } else {
                showToast(`Auto-détection terminée : ${n} nouveaux candidats`, 'ok');
            }
            // Recharge le state et re-render
            await loadAutoDetected();
            _updateAutoDetectStats();
            if (activeClip) renderAutoDetectCandidates();
        } else if (d.status === 'error') {
            clearInterval(_autoDetectPoll); _autoDetectPoll = null;
            showToast(`Erreur : ${d.error || 'inconnue'}`, 'err');
            const btn = document.getElementById('adStartBtn');
            btn.disabled = false; btn.textContent = '🔍 Lancer la détection';
        }
    } catch(e) {}
}

function renderAutoDetectCandidates() {
    const track = document.getElementById('timelineTrack');
    if (!track || !activeClip) return;
    // Clear previous candidates
    track.querySelectorAll('.timeline-autodetect-pin').forEach(p => p.remove());
    const v = document.getElementById('player');
    if (!v || !v.duration || isNaN(v.duration)) return;
    const data = _autoDetected[activeClip.id];
    if (!data || !data.candidates) return;
    const fps = activeClip.fps || 25;
    for (const cand of data.candidates) {
        if (cand.status !== 'pending') continue;  // n'affiche que les en attente
        const pin = document.createElement('div');
        pin.className = 'timeline-autodetect-pin';
        pin.style.left = (cand.time / v.duration * 100) + '%';
        pin.dataset.candidateId = cand.id;
        pin.setAttribute('data-label', `🔍 Candidat @ ${_secToTC(cand.time, fps)} — Clic G : accepter · Clic D : rejeter`);
        pin.addEventListener('click', (e) => { e.stopPropagation(); _decideCandidate(cand.id, 'accepted', pin); });
        pin.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); _decideCandidate(cand.id, 'rejected', pin); });
        track.appendChild(pin);
    }
}

function _secToTC(sec, fps) {
    if (typeof timeToTC === 'function') return timeToTC(sec, fps);
    const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = Math.floor(sec%60), f = Math.floor((sec%1)*fps);
    const pad = n => String(n).padStart(2,'0');
    return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(f)}`;
}

async function _decideCandidate(candidateId, status, pinEl) {
    if (!activeClip || !currentProjectId) return;
    // Animation immédiate (avant que le serveur réponde, pour ressenti instantané)
    if (status === 'rejected') {
        pinEl.classList.add('rejecting');
        setTimeout(() => pinEl.remove(), 250);
    } else {
        pinEl.style.background = 'var(--green)';
        pinEl.style.borderColor = 'var(--green)';
    }
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/auto_detect/decide`, {
            method: 'POST',
            body: JSON.stringify({clip_id: activeClip.id, candidate_id: candidateId, status}),
        });
        const d = await r.json();
        if (!d.ok) {
            showToast(d.error || 'Erreur', 'err');
            return;
        }
        // Maj local + re-render markers (un nouveau a peut-être été créé côté serveur)
        const data = _autoDetected[activeClip.id];
        if (data) {
            const cand = data.candidates.find(c => c.id === candidateId);
            if (cand) cand.status = status;
        }
        if (status === 'accepted') {
            // Recharge les notes pour récupérer le nouveau marker D
            try {
                const nRes = await apiFetch(`/api/project/${currentProjectId}/notes`);
                if (nRes.ok) allNotes = await nRes.json();
                if (typeof renderMarkers === 'function') renderMarkers();
            } catch(e) {}
            // Le pin candidat disparaît une fois accepté (devenu un vrai marker)
            setTimeout(() => pinEl.remove(), 250);
        }
    } catch(e) {
        showToast('Erreur réseau', 'err');
    }
}
