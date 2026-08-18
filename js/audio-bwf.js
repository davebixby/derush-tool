// ─── Son ingé sur player principal + BWF multichannel routing ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── Mémorisation de la position de lecture par clip ───────────────────────
// Partagée par le lecteur principal (selectClip), le comparateur (loadCmpClip)
// et le viewer multicam (_mcGroupResumeTime, dans multicam-viewer.js) : quand on
// quitte un clip pour un autre puis qu'on y revient, on retombe où on l'avait laissé.
let _clipResumeTime = {};  // clip.id -> secondes

// Persistance de _clipResumeTime entre relances de l'app (pas juste en mémoire pour
// la session en cours) : sauvegardé dans localStorage par projet.
function _persistClipResumeTime() {
    if (!currentProjectId) return;
    try { localStorage.setItem('derush_resume_' + currentProjectId, JSON.stringify(_clipResumeTime)); } catch(e) {}
}
function _loadClipResumeTime(pid) {
    try {
        const raw = localStorage.getItem('derush_resume_' + pid);
        if (raw) Object.assign(_clipResumeTime, JSON.parse(raw));
    } catch(e) {}
}
// Filet de sécurité : si l'app est fermée pendant qu'un clip joue (sans passer par
// selectClip, qui est le seul autre endroit où _clipResumeTime est mis à jour), on
// capture quand même sa position courante avant que la page ne disparaisse.
window.addEventListener('pagehide', () => {
    const player = document.getElementById('player');
    if (activeClip && player) _clipResumeTime[activeClip.id] = player.currentTime || 0;
    _persistClipResumeTime();
});

// ─── Volume control (HTML5 video.volume + mute toggle) ────────────────────
let _playerVolume = parseFloat(localStorage.getItem('derush_volume') || '1');
let _playerMutedBefore = _playerVolume;

function setVolume(v) {
    v = Math.max(0, Math.min(1, parseFloat(v)));
    _playerVolume = v;
    try { localStorage.setItem('derush_volume', String(v)); } catch(e) {}
    const video = document.getElementById('player');
    if (video) video.volume = v;
    // BWF audio : volume via l'élément audio. Fonctionne même avec le mixeur
    // multipiste (js/bwf-mixer.js) — audio.volume s'applique en amont du
    // graphe WebAudio, les gains par piste restent un multiplicateur indépendant.
    if (_singleBwf && _singleBwf.audio) {
        try { _singleBwf.audio.volume = v; } catch(e) {}
    }
    // Update UI
    const slider = document.getElementById('volSlider');
    if (slider && Math.abs(parseFloat(slider.value)/100 - v) > 0.01) slider.value = Math.round(v * 100);
    const icon = document.getElementById('volIcon');
    if (icon) icon.textContent = v === 0 ? '🔇' : (v < 0.5 ? '🔉' : '🔊');
}

function toggleMute() {
    if (_playerVolume > 0) {
        _playerMutedBefore = _playerVolume;
        setVolume(0);
    } else {
        setVolume(_playerMutedBefore > 0 ? _playerMutedBefore : 1);
    }
}

function _restoreVolume() {
    // Appelé à chaque selectClip pour ré-appliquer le volume sur le nouveau video element
    setVolume(_playerVolume);
}

// ─── Son ingé sur player principal ──────────────────────────────────────────
// Charge un BWF qui couvre le TC du clip actif et le joue en sync avec la vidéo.
// Pendant la lecture BWF : on coupe l'audio natif (gain stereo + monoR à 0).
let _singleBwf = null;  // {audio, offset, filename, enabled, listenersAttached}
let _playerMonoRActive = false;

function _setPlayerVideoAudioMuted(muted) {
    if (!_playerAudioCtx) return;
    if (muted) {
        if (_playerGainStereo) _playerGainStereo.gain.value = 0;
        if (_playerGainMonoR)  _playerGainMonoR.gain.value  = 0;
    } else {
        // Restaure selon l'état mono-R en cours pour ce clip
        if (_playerGainStereo) _playerGainStereo.gain.value = _playerMonoRActive ? 0 : 1;
        if (_playerGainMonoR)  _playerGainMonoR.gain.value  = _playerMonoRActive ? 1 : 0;
    }
}

// Le routage WebAudio multipiste (mix jusqu'à 8 canaux vers une sortie stéréo,
// sans quoi le <audio> HTML ne lirait que les 2 premières pistes) vit désormais
// dans js/bwf-mixer.js (_bwfBuildMixerGraph / _bwfTeardownMixerGraph) : gain
// indépendant par piste (mute/solo/fader) au lieu d'un mixdown à gain fixe.

function _cleanupSingleBwf() {
    if (!_singleBwf) return;
    const v = document.getElementById('player');
    if (_singleBwf.audio) {
        try { _singleBwf.audio.pause(); } catch(e) {}
        if (typeof _bwfTeardownMixerGraph === 'function') _bwfTeardownMixerGraph(_singleBwf.audio);
        try { _singleBwf.audio.src = ''; _singleBwf.audio.load(); } catch(e) {}
    }
    if (_singleBwf.listenersAttached && v) {
        v.removeEventListener('play', _singleBwf._onPlay);
        v.removeEventListener('pause', _singleBwf._onPause);
        v.removeEventListener('seeked', _singleBwf._onSeek);
        v.removeEventListener('ratechange', _singleBwf._onRate);
    }
    _setPlayerVideoAudioMuted(false);
    _singleBwf = null;
    if (typeof closeBwfMixerPanel === 'function') closeBwfMixerPanel();
    const btn = document.getElementById('bwfBtn');
    if (btn) {
        btn.style.display = 'none';
        btn.textContent = '🔊 Son ingé';
        btn.classList.remove('bwf-on', 'bwf-off');
        btn.style.color = '';  // reset inline styles
    }
    const mixBtn = document.getElementById('bwfMixerBtn');
    if (mixBtn) mixBtn.style.display = 'none';
}

async function _loadSingleBwfForClip(clip) {
    _cleanupSingleBwf();
    if (!clip || !currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/clip_bwf/${encodeURIComponent(clip.id)}`);
        const d = await r.json();
        if (!d.ok || !d.stream_url) return;
        const audio = new Audio(d.stream_url);
        audio.preload = 'auto';
        // Route multi-channel : si AudioContext player dispo, on l'utilise pour
        // mixer toutes les pistes BWF vers stéréo (js/bwf-mixer.js — gain par
        // piste). Sinon fallback downmix browser.
        if (_playerAudioCtx && typeof _bwfBuildMixerGraph === 'function') {
            _bwfBuildMixerGraph(audio, _playerAudioCtx, d.bwf_id, d.channels, d.track_names);
        }
        _singleBwf = {
            audio,
            offset: d.bwf_offset_sec || 0,
            filename: d.filename || '',
            enabled: false,
            listenersAttached: false,
        };
        const btn = document.getElementById('bwfBtn');
        if (btn) {
            btn.style.display = '';
            btn.title = `Son ingé disponible (${d.filename}) — clic pour activer`;
            btn.style.color = '';  // reset, classe gère le style
            btn.classList.remove('bwf-on');
            btn.classList.add('bwf-off');  // par défaut : OFF (son caméra)
            btn.textContent = '🔊 Son ingé';
        }
        const mixBtn = document.getElementById('bwfMixerBtn');
        if (mixBtn) mixBtn.style.display = (d.channels && d.channels > 1) ? '' : 'none';
    } catch(e) {}
}

function toggleSingleBwf() {
    if (!_singleBwf) return;
    const v = document.getElementById('player');
    const btn = document.getElementById('bwfBtn');
    if (_singleBwf.enabled) {
        // OFF → repasse au son caméra
        try { _singleBwf.audio.pause(); } catch(e) {}
        _setPlayerVideoAudioMuted(false);
        _singleBwf.enabled = false;
        if (btn) {
            btn.classList.remove('bwf-on');
            btn.classList.add('bwf-off');
            btn.title = 'Son caméra (clic pour passer au son ingé)';
        }
    } else {
        // ON
        if (_playerAudioCtx && _playerAudioCtx.state === 'suspended') {
            _playerAudioCtx.resume().catch(() => {});
        }
        _setPlayerVideoAudioMuted(true);
        _singleBwf.enabled = true;
        // Attach listeners 1×
        if (!_singleBwf.listenersAttached && v) {
            _singleBwf._onPlay = () => { if (_singleBwf && _singleBwf.enabled) {
                try { _singleBwf.audio.currentTime = Math.max(0, _singleBwf.offset + v.currentTime); } catch(e) {}
                _singleBwf.audio.play().catch(() => {});
            }};
            _singleBwf._onPause = () => { if (_singleBwf && _singleBwf.enabled) try { _singleBwf.audio.pause(); } catch(e) {} };
            _singleBwf._onSeek = () => { if (_singleBwf && _singleBwf.enabled) try { _singleBwf.audio.currentTime = Math.max(0, _singleBwf.offset + v.currentTime); } catch(e) {} };
            _singleBwf._onRate = () => { if (_singleBwf && _singleBwf.audio) _singleBwf.audio.playbackRate = v.playbackRate; };
            v.addEventListener('play', _singleBwf._onPlay);
            v.addEventListener('pause', _singleBwf._onPause);
            v.addEventListener('seeked', _singleBwf._onSeek);
            v.addEventListener('ratechange', _singleBwf._onRate);
            _singleBwf.listenersAttached = true;
        }
        // Sync immédiat si la vidéo joue
        if (v && !v.paused) {
            try { _singleBwf.audio.currentTime = Math.max(0, _singleBwf.offset + v.currentTime); } catch(e) {}
            _singleBwf.audio.playbackRate = v.playbackRate;
            _singleBwf.audio.play().catch(() => {});
        }
        if (btn) {
            btn.classList.remove('bwf-off');
            btn.classList.add('bwf-on');
            btn.title = 'Son ingé actif (clic pour repasser au son caméra)';
        }
    }
}

function selectClip(c) {
    const _prevPlayer = document.getElementById('player');
    if (activeClip && _prevPlayer) _clipResumeTime[activeClip.id] = _prevPlayer.currentTime || 0;
    _persistClipResumeTime();
    if(activeClip) saveClipNotes();
    // Un point d'entrée posé (touche [) sur le clip qu'on quitte n'a plus de sens
    // sur le nouveau clip — l'annuler silencieusement plutôt que le laisser traîner.
    if (typeof cancelPendingSelect === 'function' && typeof _pendingSelectIn !== 'undefined' && _pendingSelectIn !== null) {
        cancelPendingSelect();
    }
    activeClip = c;
    // Mémorise le dernier clip consulté par projet, pour y revenir au prochain
    // lancement du logiciel (cf. enterWorkspace).
    try { localStorage.setItem('derush_last_clip_' + currentProjectId, c.id); } catch(e) {}
    renderClipList();

    // Miroir horizontal : propre à ce clip, pas un réglage global — applique l'état
    // mémorisé pour CE clip (false par défaut si jamais flippé).
    if (typeof _applyFlipH === 'function') _applyFlipH(!!_flipHState[c.id]);

    document.getElementById('clipTitle').textContent = c.stem;
    const techParts = [c.iso ? `ISO ${c.iso}` : '', c.aperture||'', c.shutter_angle||'', c.focal_length||''].filter(Boolean);
    const techEl = document.getElementById('techMeta');
    if(techEl) techEl.textContent = techParts.join(' · ');

    const player = document.getElementById('player');
    const msg = document.getElementById('noVideoMsg');
    if(c.proxy_url) {
        player.src = c.proxy_url;
        player.style.display = 'block';
        msg.style.display = 'none';
        // Renseigne les insets de bandes pour le cadre (pas de crop du player : les
        // canvas dessin/LUT se calent sur la vidéo qui doit garder sa boîte).
        if (typeof _applyLetterbox === 'function') _applyLetterbox(player, c.id, false);
    } else {
        player.style.display = 'none';
        msg.style.display = 'block';
        msg.textContent = 'Pas de proxy trouvé';
    }
    player.addEventListener('loadedmetadata', () => {
        player.playbackRate = currentSpeed;
        const resumeT = _clipResumeTime[c.id];
        if (resumeT && resumeT > 0.1) {
            try { player.currentTime = Math.min(resumeT, (player.duration || resumeT) - 0.04); } catch(e) {}
        }
    }, {once: true});

    // Audio routing: les FS5 (ltc_tc_in_sec !== null) ont le LTC sur le canal L
    // de leur proxy. On force mono R pour ne pas entendre le BZZZZ.
    _attachPlayerAudio();
    _setPlayerMonoR(c.ltc_tc_in_sec != null);
    _restoreVolume();  // applique le volume sauvegardé au nouveau video element

    // LUT : ré-évalue l'assignation propre à ce clip (override clip > défaut caméra > rien)
    if (typeof _lutRefreshForActiveClip === 'function') _lutRefreshForActiveClip();

    // BWF Son ingé : charge le BWF qui couvre ce clip (s'il existe). Cleanup d'abord.
    _loadSingleBwfForClip(c);

    // Rendu candidats auto-détection sur timeline (délai = laisser la duration se charger)
    if (typeof renderAutoDetectCandidates === 'function') {
        setTimeout(() => renderAutoDetectCandidates(), 100);
    }

    // Session live : broadcast le changement de clip si on dirige
    if (typeof _sessionOnSelectClip === 'function') _sessionOnSelectClip(c);
    // Attache les listeners play/pause/seeked au player (one-shot via attribut)
    if (typeof attachSessionVideoListeners === 'function') attachSessionVideoListeners();

    const _myKey = currentSession.user_id || currentSession.username;
    const n = (allNotes[_myKey] || {})[c.id] || {};
    document.getElementById('clipNotes').value = n.notes || '';
    // Le champ de saisie tag n'était jamais vidé au changement de clip : un tag
    // tapé sans valider (Entrée/virgule) restait visible en quittant le clip, et
    // semblait "collé" au clip suivant alors qu'il n'avait jamais été enregistré
    // nulle part (d'où l'invisibilité totale en recherche).
    const tagInputEl = document.getElementById('tagInput');
    if (tagInputEl) tagInputEl.value = '';
    if (typeof closeTagAutocomplete === 'function') closeTagAutocomplete();
    seenClipIds.add(c.id);
    renderMarkers();
    renderMultiUser();
    renderAnglesPanel();
    renderStatusBtn();
    renderTags();
    renderTeamTags();
    clearCanvas();
    loadWaveform(c);
}

// Returns the validated multicam group (and its offsets) containing this clip, or null.
function findMcGroup(clipId) {
    for (const g of (_mcGroups.groups || [])) {
        if ((g.clip_ids || []).includes(clipId)) return g;
    }
    return null;
}

function renderAnglesPanel() {
    const wrap = document.getElementById('anglesPanelWrap');
    const panel = document.getElementById('anglesPanel');
    if (!activeClip) { wrap.style.display = 'none'; return; }
    const g = findMcGroup(activeClip.id);
    if (!g) { wrap.style.display = 'none'; return; }
    wrap.style.display = '';

    const myOff = g.offsets[activeClip.id] || 0;
    const clipById = {};
    (clips || []).forEach(c => clipById[c.id] = c);
    const rows = [];
    for (const cid of g.clip_ids) {
        const c = clipById[cid];
        const off = (g.offsets[cid] || 0);
        const rel = off - myOff;   // offset relative to the active clip
        const isMe = (cid === activeClip.id);
        const offTxt = isMe ? 'actif'
                            : ((rel >= 0 ? '+' : '') + rel.toFixed(2) + ' s');
        const camera = c ? (c.camera || c.day) : '?';
        const label = c ? c.stem : `<span style="color:var(--red);">${cid}</span>`;
        rows.push(`<div class="angle-row${isMe ? ' active' : ''}" ${isMe || !c ? '' : `onclick="swapToAngle('${cid}')"`}
                       style="display:flex;gap:8px;align-items:center;padding:4px 6px;border-radius:4px;cursor:${isMe || !c ? 'default' : 'pointer'};background:${isMe ? 'rgba(99,102,241,.15)' : 'transparent'};">
                       <img src="/api/project/${currentProjectId}/thumbnail/${cid}" style="width:36px;height:20px;object-fit:cover;border-radius:2px;background:#000;" loading="lazy" onerror="this.style.opacity=0">
                       <div style="flex:1;min-width:0;font-size:0.78em;">
                           <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label}</div>
                           <div style="color:var(--dim);font-size:0.85em;">${camera}</div>
                       </div>
                       <span style="font-family:monospace;font-size:0.78em;color:${isMe ? 'var(--accent)' : '#10b981'};">${offTxt}</span>
                   </div>`);
    }
    panel.innerHTML = rows.join('');
}

