// ─── Son ingé sur player principal + BWF multichannel routing ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── Volume control (HTML5 video.volume + mute toggle) ────────────────────
let _playerVolume = parseFloat(localStorage.getItem('derush_volume') || '1');
let _playerMutedBefore = _playerVolume;

function setVolume(v) {
    v = Math.max(0, Math.min(1, parseFloat(v)));
    _playerVolume = v;
    try { localStorage.setItem('derush_volume', String(v)); } catch(e) {}
    const video = document.getElementById('player');
    if (video) video.volume = v;
    // BWF audio : volume via l'élément audio (fonctionne même avec WebAudio routing)
    if (_singleBwf && _singleBwf.audio) {
        try { _singleBwf.audio.volume = v; } catch(e) {}
        // Synchronise aussi les gains du routing multichannel
        if (_singleBwf.audio._bwfRouted) {
            const r = _singleBwf.audio._bwfRouted;
            try { r.gainL.gain.value = v / 3.0; r.gainR.gain.value = v / 3.0; } catch(e) {}
        }
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

// Routage WebAudio pour un BWF multipistes : mixe toutes les pistes (jusqu'à 8 canaux)
// vers une sortie stéréo. Sans ça, le <audio> HTML ne lit que les 2 premières pistes.
// Réutilise un AudioContext partagé pour éviter de multiplier les contextes.
function _routeBwfMultiChannel(audio, ctx) {
    try {
        if (ctx.state === 'suspended') ctx.resume().catch(()=>{});
        const src = ctx.createMediaElementSource(audio);
        src.channelInterpretation = 'discrete';
        const MAX_CH = 8;
        const splitter = ctx.createChannelSplitter(MAX_CH);
        const merger = ctx.createChannelMerger(2);
        const gainL = ctx.createGain();
        const gainR = ctx.createGain();
        // Mix simple : somme de toutes les pistes sur L et R, atténué pour éviter la satu.
        // Le facteur 1/3 = compromis ; les canaux vides (au-delà du nb réel) restent à 0.
        gainL.gain.value = 1.0 / 3.0;
        gainR.gain.value = 1.0 / 3.0;
        src.connect(splitter);
        for (let i = 0; i < MAX_CH; i++) {
            try { splitter.connect(gainL, i); } catch(_) {}
            try { splitter.connect(gainR, i); } catch(_) {}
        }
        gainL.connect(merger, 0, 0);
        gainR.connect(merger, 0, 1);
        merger.connect(ctx.destination);
        audio._bwfRouted = {src, splitter, merger, gainL, gainR};
        return true;
    } catch(e) {
        console.warn('BWF WebAudio routing failed (will fallback to default stereo downmix):', e);
        return false;
    }
}

function _unrouteBwf(audio) {
    if (!audio || !audio._bwfRouted) return;
    const r = audio._bwfRouted;
    try { r.src.disconnect(); } catch(_) {}
    try { r.splitter.disconnect(); } catch(_) {}
    try { r.merger.disconnect(); } catch(_) {}
    try { r.gainL.disconnect(); } catch(_) {}
    try { r.gainR.disconnect(); } catch(_) {}
    audio._bwfRouted = null;
}

function _cleanupSingleBwf() {
    if (!_singleBwf) return;
    const v = document.getElementById('player');
    if (_singleBwf.audio) {
        try { _singleBwf.audio.pause(); } catch(e) {}
        _unrouteBwf(_singleBwf.audio);
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
    const btn = document.getElementById('bwfBtn');
    if (btn) {
        btn.style.display = 'none';
        btn.textContent = '🔊 Son ingé';
        btn.classList.remove('bwf-on', 'bwf-off');
        btn.style.color = '';  // reset inline styles
    }
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
        // mixer toutes les pistes BWF vers stéréo. Sinon fallback downmix browser.
        if (_playerAudioCtx) {
            _routeBwfMultiChannel(audio, _playerAudioCtx);
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
    if(activeClip) saveClipNotes();
    activeClip = c;
    renderClipList();
    
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
    player.addEventListener('loadedmetadata', () => { player.playbackRate = currentSpeed; }, {once: true});

    // Audio routing: les FS5 (ltc_tc_in_sec !== null) ont le LTC sur le canal L
    // de leur proxy. On force mono R pour ne pas entendre le BZZZZ.
    _attachPlayerAudio();
    _setPlayerMonoR(c.ltc_tc_in_sec != null);
    _restoreVolume();  // applique le volume sauvegardé au nouveau video element

    // LUT : ré-évalue le scope pour ce clip (active/désactive le canvas selon la caméra)
    if (_lut) enableLUT(_lutEnabled);

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
    seenClipIds.add(c.id);
    renderMarkers();
    renderMultiUser();
    renderAnglesPanel();
    renderStatusBtn();
    renderTags();
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

