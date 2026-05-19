// ─── Session live : leader / follower via WebSocket ─────────────────────────
// Un utilisateur "dirige" la session, les autres peuvent activer "Suivre" pour
// voir ses actions (select clip, seek, play, pause) en temps réel sur leur UI.
//
// Backend : POST /api/project/<pid>/session/start_leading | stop_leading | action
//           GET  /api/project/<pid>/session/state
//           WS broadcast : {type: 'session_state', leader} et
//                          {type: 'session_action', action, data, from}
//
// Module externalisé.

let _sessionLeader = null;       // username du leader actuel (null si personne)
let _sessionIsLeading = false;   // true si c'est nous
let _sessionFollowing = false;   // true si on a activé le suivi
let _sessionLastClipId = null;   // dédup broadcast select_clip
let _sessionApplyingRemote = false; // anti-loop quand on applique une action distante

async function loadSessionState() {
    if (!currentProjectId) { _sessionLeader = null; _sessionIsLeading = false; return; }
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/session/state`);
        const d = await r.json();
        _sessionLeader = d.leader || null;
        _sessionIsLeading = (_sessionLeader && currentSession && _sessionLeader === currentSession.username);
        _updateSessionUI();
    } catch(e) {}
}

function _updateSessionUI() {
    const btn = document.getElementById('sessionBtn');
    if (!btn) return;
    if (_sessionIsLeading) {
        btn.textContent = '🛑 Arrêter de diriger';
        btn.title = "Tu diriges la session — tes actions sont diffusées aux autres";
        btn.style.background = 'rgba(52,211,153,.2)';
        btn.style.color = '#34d399';
        btn.style.borderColor = 'rgba(52,211,153,.5)';
    } else if (_sessionLeader) {
        if (_sessionFollowing) {
            btn.textContent = `✓ Suit ${_sessionLeader}`;
            btn.title = `Tu suis ${_sessionLeader} — clic pour arrêter`;
            btn.style.background = 'rgba(167,139,250,.2)';
            btn.style.color = '#a78bfa';
            btn.style.borderColor = 'rgba(167,139,250,.5)';
        } else {
            btn.textContent = `👁 Suivre ${_sessionLeader}`;
            btn.title = `${_sessionLeader} dirige — clic pour suivre`;
            btn.style.background = '';
            btn.style.color = '';
            btn.style.borderColor = '';
        }
    } else {
        btn.textContent = '🎬 Diriger la session';
        btn.title = "Personne ne dirige — clic pour devenir leader (tes actions seront diffusées)";
        btn.style.background = '';
        btn.style.color = '';
        btn.style.borderColor = '';
    }
}

async function toggleSession() {
    if (!currentProjectId) return;
    if (_sessionIsLeading) {
        // Arrête de diriger
        try {
            await apiFetch(`/api/project/${currentProjectId}/session/stop_leading`, {method:'POST'});
        } catch(e) {}
        _sessionIsLeading = false;
        _sessionLeader = null;
        _sessionLastClipId = null;
        _updateSessionUI();
        showToast('Tu ne diriges plus la session', 'info');
    } else if (_sessionLeader) {
        // Toggle follow
        _sessionFollowing = !_sessionFollowing;
        _updateSessionUI();
        if (_sessionFollowing) {
            showToast(`👁 Tu suis ${_sessionLeader}`, 'ok');
        } else {
            showToast('Tu ne suis plus', 'info');
        }
    } else {
        // Deviens leader
        try {
            await apiFetch(`/api/project/${currentProjectId}/session/start_leading`, {method:'POST'});
        } catch(e) { showToast('Erreur', 'err'); return; }
        _sessionIsLeading = true;
        _sessionLeader = currentSession.username;
        _sessionLastClipId = activeClip ? activeClip.id : null;
        _updateSessionUI();
        showToast('🎬 Tu diriges la session — tes actions seront diffusées', 'ok', 4000);
    }
}

// Handler appelé depuis startWebSocket onmessage pour les messages session_*
function handleSessionWsMessage(msg) {
    if (msg.type === 'session_state') {
        _sessionLeader = msg.leader || null;
        const me = currentSession && currentSession.username;
        _sessionIsLeading = (_sessionLeader && _sessionLeader === me);
        if (!_sessionLeader) _sessionFollowing = false;
        _updateSessionUI();
        // Notification quand qqn d'autre commence à diriger
        if (_sessionLeader && !_sessionIsLeading) {
            showToast(`🎬 ${_sessionLeader} dirige la session — clic 👁 pour suivre`, 'info', 5000);
        }
    } else if (msg.type === 'session_action') {
        if (!_sessionFollowing) return;
        if (msg.from === (currentSession && currentSession.username)) return; // ignore mes propres actions
        _applySessionAction(msg.action, msg.data);
    }
}

function _applySessionAction(action, data) {
    _sessionApplyingRemote = true;
    try {
        const v = document.getElementById('player');
        if (action === 'select_clip') {
            const clip = clips.find(c => c.id === data.clip_id);
            if (clip && (!activeClip || activeClip.id !== clip.id)) {
                selectClip(clip);
            }
        } else if (action === 'seek') {
            if (v && !isNaN(v.duration) && Math.abs((v.currentTime||0) - data.time) > 0.3) {
                v.currentTime = data.time;
            }
        } else if (action === 'play') {
            if (v && v.paused) v.play().catch(()=>{});
        } else if (action === 'pause') {
            if (v && !v.paused) v.pause();
        }
    } catch(e) {}
    setTimeout(() => { _sessionApplyingRemote = false; }, 50);
}

function _sessionBroadcast(action, data) {
    if (!_sessionIsLeading || _sessionApplyingRemote) return;
    if (!currentProjectId || !currentSession) return;
    fetch(`/api/project/${currentProjectId}/session/action`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + currentSession.token},
        body: JSON.stringify({action, data}),
        keepalive: true,
    }).catch(()=>{});
}

// Hook public : appelé depuis selectClip pour broadcaster le changement de clip
function _sessionOnSelectClip(c) {
    if (!_sessionIsLeading || !c) return;
    if (c.id === _sessionLastClipId) return;
    _sessionLastClipId = c.id;
    _sessionBroadcast('select_clip', {clip_id: c.id});
}

// Attache les listeners play/pause/seeked au video element (une fois)
function attachSessionVideoListeners() {
    const v = document.getElementById('player');
    if (!v || v._sessionAttached) return;
    v._sessionAttached = true;
    v.addEventListener('play', () => _sessionBroadcast('play', {}));
    v.addEventListener('pause', () => _sessionBroadcast('pause', {}));
    let _seekDebounce = null;
    v.addEventListener('seeked', () => {
        if (_seekDebounce) clearTimeout(_seekDebounce);
        _seekDebounce = setTimeout(() => _sessionBroadcast('seek', {time: v.currentTime}), 150);
    });
}
