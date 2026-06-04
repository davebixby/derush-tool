// ─── 4-up multi-cam viewer (overlay + nudge + sync) ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── 4-up multi-cam viewer ───────────────────────────────────────────────
// All angles play simultaneously, video offsets are preserved so the audio
// stays in sync. Only the "primary" angle is unmuted. Hotkeys 1/2/3/4 swap
// which angle is large + audible. Drift correction every second.
let _mcView = null;

function openMcViewer() {
    if (!activeClip) return;
    const g = findMcGroup(activeClip.id);
    if (!g) { alert('Ce clip n\'appartient à aucun groupe multi-cam validé.'); return; }
    // Pause le player principal : sinon son audio continue à jouer pendant
    // qu'on est dans le viewer multicam → double piste son.
    const mainPlayer = document.getElementById('player');
    if (mainPlayer && !mainPlayer.paused) { try { mainPlayer.pause(); } catch(e) {} }
    const clipById = {};
    (clips || []).forEach(c => clipById[c.id] = c);

    const minOff = Math.min(...Object.values(g.offsets));
    const angles = g.clip_ids.map(cid => {
        const c = clipById[cid];
        if (!c) return null;
        const off = g.offsets[cid] || 0;
        return {
            cid, clip: c,
            normOff: off - minOff,
            duration: c.duration_sec || 0,
        };
    }).filter(Boolean);
    if (!angles.length) return;

    const groupDur = Math.max(...angles.map(a => a.normOff + a.duration));
    _mcView = {group: g, angles, groupDur, primaryIdx: 0, playing: false, raf: null, drift: null, lastT: 0, layoutMode: 'primary', nudgeDelta: 0};

    // Start primary on the active clip if possible
    const idx = angles.findIndex(a => a.cid === activeClip.id);
    if (idx > 0) _mcView.primaryIdx = idx;

    _buildMcLayout(true);
    document.getElementById('mcNudgeDisplay').textContent = 'Δ 0.00s';
    document.getElementById('mcNudgeSaveBtn').style.display = 'none';
    document.getElementById('mcLayoutBtn').textContent = '⊞ Grille';
    const bwfBtn = document.getElementById('mcBwfBtn');
    if (bwfBtn) bwfBtn.style.display = 'none';
    document.getElementById('mcViewerOverlay').classList.add('active');
    document.addEventListener('keydown', _mcKeydown);
    _mcStartRaf();
    _mcDriftCorrect();
    _mcView.drift = setInterval(_mcDriftCorrect, 1000);
    // Load BWF audio (if a BWF covers the group's TC range)
    _mcView.bwfAudio = null; _mcView.bwfOffset = 0; _mcView.bwfEnabled = true;
    apiFetch(`/api/project/${currentProjectId}/multicam/group_bwf?group_id=${g.id}`)
    .then(r => r.json()).then(d => {
        if (!d.ok || !d.stream_url || !_mcView) return;
        const audio = new Audio(d.stream_url);
        audio.preload = 'auto';
        // Route multi-channel via le ctx du multicam viewer (créé dans _mcAttachAudio)
        const ctx = window._mcAudioCtx;
        if (ctx) _routeBwfMultiChannel(audio, ctx);
        _mcView.bwfAudio = audio;
        _mcView.bwfOffset = d.bwf_offset_sec || 0;
        _mcView.bwfFilename = d.filename;
        const btn = document.getElementById('mcBwfBtn');
        if (btn) {
            btn.style.display = '';
            btn.style.color = '';  // laisse les classes gérer
            btn.style.borderColor = '';
            btn.title = `Son ingé actif (${d.filename}) — clic pour repasser au son caméra`;
            btn.textContent = '🔊 Son ingé';
            btn.classList.remove('bwf-off');
            btn.classList.add('bwf-on');  // démarre ON puisque bwfEnabled=true par défaut
        }
        try { audio.currentTime = Math.max(0, _mcView.bwfOffset + _mcCurrentGroupTime()); } catch(e) {}
        if (_mcView.playing) audio.play().catch(() => {});
    }).catch(() => {});
}

function _mcToggleBwf() {
    const v = _mcView; if (!v || !v.bwfAudio) return;
    v.bwfEnabled = !v.bwfEnabled;
    const btn = document.getElementById('mcBwfBtn');
    if (v.bwfEnabled) {
        if (btn) {
            btn.classList.remove('bwf-off');
            btn.classList.add('bwf-on');
            btn.title = `Son ingé actif (${v.bwfFilename||''}) — clic pour repasser au son caméra`;
        }
        if (v.playing) {
            const T = _mcCurrentGroupTime();
            try { v.bwfAudio.currentTime = Math.max(0, v.bwfOffset + T); } catch(e) {}
            v.bwfAudio.play().catch(() => {});
        }
    } else {
        if (btn) {
            btn.classList.remove('bwf-on');
            btn.classList.add('bwf-off');
            btn.title = 'Son caméra (clic pour passer au son ingé)';
        }
        try { v.bwfAudio.pause(); } catch(e) {}
    }
}

// Per-angle audio routing.
// FS5 clips have LTC on the L channel (we put it there during transcode). Playing the
// stereo would let the LTC BZZZZ leak into the output, so we route R → both channels
// via WebAudio. FX6 clips keep native stereo. In both cases mute is centralised via
// _mcSetMute() — for WebAudio-routed clips we cannot rely on vidEl.muted (the native
// output is bypassed once createMediaElementSource is called), so we drive a GainNode.
function _mcAttachAudio(a) {
    if (a._audioAttached) return;
    a._audioAttached = true;
    const hasLtc = (a.clip && a.clip.ltc_tc_in_sec != null);
    if (!hasLtc) { a._monoR = false; return; }
    try {
        const ctx = window._mcAudioCtx || (window._mcAudioCtx = new (window.AudioContext || window.webkitAudioContext)());
        if (ctx.state === 'suspended') ctx.resume().catch(() => {});
        const src = ctx.createMediaElementSource(a.vidEl);
        const splitter = ctx.createChannelSplitter(2);
        const merger = ctx.createChannelMerger(2);
        const gain = ctx.createGain();
        gain.gain.value = 0;  // start muted; mute logic sets it to 1 for the primary
        src.connect(splitter);
        splitter.connect(merger, 1, 0); // R input → L output
        splitter.connect(merger, 1, 1); // R input → R output
        merger.connect(gain);
        gain.connect(ctx.destination);
        // Keep refs so closeMcViewer can disconnect them — otherwise the AudioContext
        // (which is shared across sessions) accumulates dead nodes that retain the
        // <video> elements via MediaElementSource → memory bloat after a few opens.
        a._sourceNode = src;
        a._splitterNode = splitter;
        a._mergerNode = merger;
        a._gainNode = gain;
        a._monoR = true;
    } catch (e) {
        console.warn('Audio routing fail for', a.clip && a.clip.stem, e);
        a._monoR = false;
    }
}

function _mcSetMute(a, muted) {
    if (a._monoR && a._gainNode) {
        a._gainNode.gain.value = muted ? 0 : 1;
        // Keep vidEl.muted in sync as a no-op safety (native output is bypassed anyway)
        if (a.vidEl) a.vidEl.muted = muted;
    } else if (a.vidEl) {
        a.vidEl.muted = muted;
    }
}

function _buildMcLayout(isInitial) {
    const v = _mcView;
    if (!v) return;
    const isGrid = v.layoutMode === 'grid';
    const stage = document.getElementById('mcStage');
    const primaryEl = document.getElementById('mcPrimary');
    const thumbsEl = document.getElementById('mcThumbs');
    primaryEl.innerHTML = '';
    thumbsEl.innerHTML = '';

    if (isGrid) {
        const N = v.angles.length;
        const cols = N <= 3 ? N : Math.ceil(Math.sqrt(N));
        stage.style.gridTemplateColumns = '1fr';
        primaryEl.style.cssText = `display:grid;grid-template-columns:repeat(${cols},1fr);gap:6px;border:none;border-radius:0;background:transparent;`;
        thumbsEl.style.display = 'none';
    } else {
        stage.style.gridTemplateColumns = '';
        primaryEl.style.cssText = '';
        thumbsEl.style.display = '';
    }

    v.angles.forEach((a, i) => {
        const isPri = (i === v.primaryIdx);
        if (isInitial) {
            // Create elements once — kept alive to avoid reload/black-screen on rapid switch
            const wrap = document.createElement('div');
            wrap.style.position = 'relative';
            const vid = document.createElement('video');
            vid.id = `mcVid_${i}`;
            vid.src = a.clip.proxy_url || '';
            vid.preload = 'auto';
            vid.playsInline = true;
            vid.controls = false;
            vid.muted = true;
            wrap.appendChild(vid);
            // Renseigne les insets pour le cadre (crop multicam à étendre après
            // validation du comparateur — cellules 16:9, layout différent).
            if (typeof _applyLetterbox === 'function') _applyLetterbox(vid, a.cid, false);
            // Applique le format de cadre sélectionné à cet angle dès qu'il est prêt
            vid.addEventListener('loadedmetadata', () => { if (typeof _drawAspOn === 'function') _drawAspOn(vid, wrap, a.cid); }, { once: true });
            const numBadge = document.createElement('div');
            numBadge.className = 'mc-thumb-num';
            wrap.appendChild(numBadge);
            const label = document.createElement('div');
            label.className = 'mc-thumb-label';
            const offTxt = a.normOff > 0 ? ` · +${a.normOff.toFixed(2)}s` : '';
            label.innerHTML = `${a.clip.camera || a.clip.day || '?'}${offTxt}<br><span style="opacity:.7;">${a.clip.stem}</span>`;
            wrap.appendChild(label);
            const waitEl = document.createElement('div');
            waitEl.className = 'mc-waiting-overlay';
            waitEl.textContent = '⏳';
            wrap.appendChild(waitEl);
            a.vidEl = vid;
            a.wrapEl = wrap;
            a.numBadgeEl = numBadge;
            a.waitingEl = waitEl;
            a._inRange = true; // will be corrected on first seek
            _mcAttachAudio(a);
        }

        _mcSetMute(a, !isPri);
        a.numBadgeEl.textContent = (i + 1) + (isPri ? ' · 🔊' : '');

        if (isGrid) {
            a.wrapEl.className = 'mc-grid-cell' + (isPri ? ' mc-grid-active' : '');
            a.wrapEl.style.width = '';
            a.wrapEl.style.height = '';
            a.wrapEl.onclick = () => _setMcPrimary(i);
            primaryEl.appendChild(a.wrapEl);
        } else {
            a.wrapEl.className = isPri ? 'mc-primary-inner' : 'mc-thumb';
            a.wrapEl.style.width = '100%';
            a.wrapEl.style.height = isPri ? '100%' : '';
            a.wrapEl.onclick = isPri ? null : () => _setMcPrimary(i);
            (isPri ? primaryEl : thumbsEl).appendChild(a.wrapEl);
        }
    });

    if (isInitial) {
        const pri = v.angles[v.primaryIdx].vidEl;
        // Start at the primary clip's own beginning (= its normOff in group time)
        // so the primary always shows content right away
        pri.addEventListener('loadedmetadata', () => _mcSeekGroup(v.angles[v.primaryIdx].normOff), {once: true});
    }
    _mcRenderTimelineMarks();
    // Repositionne le cadre sur chaque angle après que le layout est en place
    // (taille des cellules connue) — couvre aussi le basculement grille/primaire.
    if (typeof _drawAspOn === 'function') {
        requestAnimationFrame(() => v.angles.forEach(a => { if (a.vidEl && a.wrapEl) _drawAspOn(a.vidEl, a.wrapEl, a.cid); }));
    }
}

function _mcToggleLayout() {
    const v = _mcView; if (!v) return;
    v.layoutMode = v.layoutMode === 'grid' ? 'primary' : 'grid';
    const btn = document.getElementById('mcLayoutBtn');
    btn.textContent = v.layoutMode === 'grid' ? '⊡ Primaire' : '⊞ Grille';
    const oldT = _mcCurrentGroupTime();
    const wasPlaying = v.playing;
    if (wasPlaying) _mcPause();
    _buildMcLayout(false);
    _mcSeekGroup(oldT);
    if (wasPlaying) _mcPlay();
}

// ─── Nudge frame-par-frame ────────────────────────────────────────────────
// Décale tous les angles sauf le primaire de ±1 frame pour corriger
// un décalage résiduel laissé par l'empreinte audio.
function _mcNudge(sign, unitSec) {
    const v = _mcView; if (!v) return;
    const fps = v.angles[v.primaryIdx].clip.fps || 25;
    const step = (unitSec === undefined || unitSec === null) ? 1 / fps : Number(unitSec);
    const delta = sign * step;
    v.nudgeDelta = (v.nudgeDelta || 0) + delta;
    const oldT = _mcCurrentGroupTime();
    v.angles.forEach((a, i) => {
        if (i !== v.primaryIdx) a.normOff -= delta;
    });
    v.groupDur = Math.max(...v.angles.map(a => a.normOff + a.duration));
    _mcSeekGroup(oldT);
    _mcRenderTimelineMarks();
    const d = v.nudgeDelta;
    document.getElementById('mcNudgeDisplay').textContent = `Δ ${d >= 0 ? '+' : ''}${d.toFixed(3)}s`;
    document.getElementById('mcNudgeSaveBtn').style.display = Math.abs(d) > 1e-6 ? '' : 'none';
}

function _mcNudgeStep(sign) {
    const sel = document.getElementById('mcNudgeStep');
    const val = sel ? sel.value : 'frame';
    if (val === 'frame') return _mcNudge(sign);
    return _mcNudge(sign, parseFloat(val));
}

async function _mcSaveNudge() {
    const v = _mcView; if (!v || !v.nudgeDelta) return;
    // Reconstruct absolute offsets (use normOff directly — server just needs a consistent scale)
    const newOffsets = {};
    v.angles.forEach(a => { newOffsets[a.cid] = a.normOff; });
    try {
        const r = await fetch(`/api/project/${currentProjectId}/multicam/nudge`, {
            method: 'POST',
            headers: {'Content-Type':'application/json','X-Token': currentSession && currentSession.token || ''},
            body: JSON.stringify({group_id: v.group.id, offsets: newOffsets})
        });
        const d = await r.json();
        if (d.ok) {
            // Update local group state so panels reflect new offsets
            v.group.offsets = newOffsets;
            v.nudgeDelta = 0;
            document.getElementById('mcNudgeDisplay').textContent = 'Δ 0.00s';
            document.getElementById('mcNudgeSaveBtn').style.display = 'none';
            // Refresh angles panel in background
            await refreshMulticam();
            renderAnglesPanel();
        }
    } catch(e) { console.error('nudge save failed', e); }
}

function _mcRenderTimelineMarks() {
    const v = _mcView; if (!v) return;
    const tl = document.getElementById('mcTl');
    tl.querySelectorAll('.mc-tl-clip, .mc-tl-overlap').forEach(e => e.remove());

    // Zone de synchro : intersection de tous les angles (overlap commun)
    if (v.angles.length >= 2 && v.groupDur > 0) {
        const ovStart = Math.max(...v.angles.map(a => a.normOff));
        const ovEnd = Math.min(...v.angles.map(a => a.normOff + a.duration));
        if (ovEnd > ovStart + 0.01) {
            const band = document.createElement('div');
            band.className = 'mc-tl-overlap';
            band.style.left = (ovStart / v.groupDur * 100) + '%';
            band.style.width = ((ovEnd - ovStart) / v.groupDur * 100) + '%';
            const lbl = document.createElement('span');
            lbl.className = 'mc-tl-overlap-lbl';
            const ovDur = ovEnd - ovStart;
            lbl.textContent = `✓ SYNCHRO ${ovDur.toFixed(1)}s`;
            band.appendChild(lbl);
            tl.appendChild(band);
        }
    }

    // Bars par angle, empilées verticalement
    const trackH = tl.clientHeight || 42;
    const n = Math.max(v.angles.length, 1);
    const gap = 2;
    const top0 = 4;
    const barH = Math.max(6, Math.floor((trackH - top0 * 2 - gap * (n - 1)) / n));
    v.angles.forEach((a, i) => {
        const div = document.createElement('div');
        const isPrimary = i === v.primaryIdx;
        div.className = 'mc-tl-clip' + (isPrimary ? '' : ' is-secondary');
        div.style.left = (a.normOff / v.groupDur * 100) + '%';
        div.style.width = (a.duration / v.groupDur * 100) + '%';
        div.style.top = (top0 + i * (barH + gap)) + 'px';
        div.style.height = barH + 'px';
        div.style.background = isPrimary ? 'var(--accent)' : 'rgba(255,255,255,.32)';
        const stem = (a.clip && (a.clip.stem || a.clip.filename || a.clip.id)) || `angle ${i+1}`;
        const cam = (a.clip && a.clip.camera) ? ` · ${a.clip.camera}` : '';
        const lbl = document.createElement('span');
        lbl.className = 'mc-tl-clip-label';
        lbl.textContent = stem + cam;
        div.appendChild(lbl);
        tl.appendChild(div);
    });

    // Labels durée/fin
    const dur = v.groupDur || 0;
    const dm = Math.floor(dur / 60), ds = Math.floor(dur % 60);
    const durStr = `${dm}:${ds.toString().padStart(2,'0')}`;
    const lblDur = document.getElementById('mcTlDurLabel');
    if (lblDur) lblDur.textContent = `Durée ${durStr} · ${n} angle${n>1?'s':''}`;
    const lblEnd = document.getElementById('mcTlEndTc');
    if (lblEnd) lblEnd.textContent = durStr;
}

function _mcSwapPrimary() {
    // Swap PHYSIQUE des emplacements : intervertit les 2 premiers angles dans
    // le tableau → la vidéo de gauche prend la place de droite et inversement.
    // Pour 3+ angles, swap juste les positions 0 et 1.
    const v = _mcView;
    if (!v || v.angles.length < 2) return;
    [v.angles[0], v.angles[1]] = [v.angles[1], v.angles[0]];
    // primaryIdx suit le swap pour que la primary reste sur le même clip logique
    if (v.primaryIdx === 0) v.primaryIdx = 1;
    else if (v.primaryIdx === 1) v.primaryIdx = 0;
    _buildMcLayout(false);
}

function _setMcPrimary(idx) {
    const v = _mcView;
    if (!v || idx === v.primaryIdx || idx < 0 || idx >= v.angles.length) return;
    // Block switch to an angle that hasn't started yet
    if (!v.angles[idx]._inRange) return;
    const oldT = _mcCurrentGroupTime();
    const wasPlaying = v.playing;
    if (wasPlaying) _mcPause();
    v.primaryIdx = idx;
    _buildMcLayout(false); // elements already exist, just rearrange
    _mcSeekGroup(oldT);    // videos are loaded — seek is immediate, no race condition
    if (wasPlaying) _mcPlay();
}

function _mcCurrentGroupTime() {
    const v = _mcView; if (!v) return 0;
    const pri = v.angles[v.primaryIdx];
    if (!pri || !pri.vidEl) return v.lastT || 0;
    const priDur = pri.vidEl.duration || pri.duration || 0;
    const priT = (pri.vidEl.currentTime || 0) + pri.normOff;
    // Si le primary est à la fin de son clip pendant qu'on joue, on prend la base de temps
    // sur l'angle in-range le plus avancé. Sinon le drift correct rebobine les autres en boucle.
    if (v.playing && priDur > 0 && pri.vidEl.currentTime >= priDur - 0.1) {
        let bestT = priT;
        v.angles.forEach((a, i) => {
            if (i === v.primaryIdx || !a.vidEl || !a._inRange) return;
            const aDur = a.vidEl.duration || a.duration || 0;
            if (aDur > 0 && a.vidEl.currentTime < aDur - 0.1) {
                const aT = (a.vidEl.currentTime || 0) + a.normOff;
                if (aT > bestT) bestT = aT;
            }
        });
        return Math.max(0, Math.min(v.groupDur, bestT));
    }
    return Math.max(0, Math.min(v.groupDur, priT));
}

function _mcSeekGroup(T) {
    const v = _mcView; if (!v) return;
    v.lastT = T;
    v.angles.forEach((a, i) => {
        if (!a.vidEl) return;
        const isPri = (i === v.primaryIdx);
        const dur = a.vidEl.duration || a.duration || 0;
        const localT = T - a.normOff;
        if (isPri) {
            const ct = Math.max(0, Math.min(localT, dur - 0.04));
            try { a.vidEl.currentTime = ct; } catch(e) {}
            a.wrapEl && a.wrapEl.classList.remove('mc-out-of-range');
            a._inRange = true;
        } else {
            const wasInRange = a._inRange;
            const inRange = localT >= 0 && localT < dur;
            a._inRange = inRange;
            if (inRange) {
                try { a.vidEl.currentTime = Math.min(localT, dur - 0.04); } catch(e) {}
                a.wrapEl && a.wrapEl.classList.remove('mc-out-of-range');
                if (v.playing) a.vidEl.play().catch(()=>{});
            } else {
                if (!wasInRange || !a.vidEl.paused) try { a.vidEl.pause(); } catch(e) {}
                a.wrapEl && a.wrapEl.classList.add('mc-out-of-range');
            }
        }
    });
    if (v.bwfAudio) try { v.bwfAudio.currentTime = Math.max(0, v.bwfOffset + T); } catch(e) {}
}

function _mcPlay() {
    const v = _mcView; if (!v) return;
    v.playing = true;
    document.getElementById('mcPlayBtn').textContent = '⏸';
    const T = _mcCurrentGroupTime();
    v.angles.forEach(a => {
        if (!a.vidEl) return;
        const dur = a.vidEl.duration || a.duration || 0;
        const localT = T - a.normOff;
        if (localT >= 0 && localT < dur) {
            if (Math.abs(a.vidEl.currentTime - localT) > 0.1) {
                try { a.vidEl.currentTime = Math.min(localT, dur - 0.04); } catch(e) {}
            }
            a.vidEl.play().catch(()=>{});
        }
    });
    if (v.bwfAudio && v.bwfEnabled) {
        try { v.bwfAudio.currentTime = Math.max(0, v.bwfOffset + T); } catch(e) {}
        v.bwfAudio.play().catch(() => {});
    }
}

function _mcPause() {
    const v = _mcView; if (!v) return;
    v.playing = false;
    document.getElementById('mcPlayBtn').textContent = '▶';
    v.angles.forEach(a => { if (a.vidEl) try { a.vidEl.pause(); } catch(e) {} });
    if (v.bwfAudio) try { v.bwfAudio.pause(); } catch(e) {}
}

function mcViewerPlayPause() {
    const v = _mcView; if (!v) return;
    v.playing ? _mcPause() : _mcPlay();
}

function _mcStartRaf() {
    const v = _mcView; if (!v) return;
    const tick = () => {
        if (!_mcView) return;
        const T = _mcCurrentGroupTime();
        const pct = v.groupDur ? (T / v.groupDur * 100) : 0;
        document.getElementById('mcTlProg').style.width = pct + '%';
        document.getElementById('mcTlHead').style.left = pct + '%';
        const totMin = Math.floor(v.groupDur / 60), totSec = Math.floor(v.groupDur % 60);
        const curMin = Math.floor(T / 60), curSec = Math.floor(T % 60);
        document.getElementById('mcViewerTime').textContent =
            `${curMin}:${curSec.toString().padStart(2,'0')} / ${totMin}:${totSec.toString().padStart(2,'0')}`;
        // Mute cameras: all when BWF is active, else only non-primary
        const useBwf = !!(v.bwfAudio && v.bwfEnabled);
        v.angles.forEach((a, i) => { if (a.vidEl) _mcSetMute(a, useBwf || (i !== v.primaryIdx)); });
        // Frame-accurate start/stop for secondaries + waiting overlay countdown
        v.angles.forEach((a, i) => {
            if (i === v.primaryIdx || !a.vidEl) return;
            const dur = a.vidEl.duration || a.duration || 0;
            const localT = T - a.normOff;
            const inRange = localT >= 0 && localT < dur;
            // Update waiting overlay (every frame but cheap)
            if (a.waitingEl) {
                if (localT < 0)   a.waitingEl.textContent = `⏳ ${(-localT).toFixed(1)}s`;
                else if (!inRange) a.waitingEl.textContent = '⏹';
            }
            // Detect transition to trigger start or stop
            if (inRange !== a._inRange) {
                a._inRange = inRange;
                a.wrapEl && a.wrapEl.classList.toggle('mc-out-of-range', !inRange);
                if (inRange) {
                    try { a.vidEl.currentTime = Math.min(localT, dur - 0.04); } catch(e) {}
                    if (v.playing) a.vidEl.play().catch(()=>{});
                } else {
                    try { a.vidEl.pause(); } catch(e) {}
                }
            }
        });
        v.raf = requestAnimationFrame(tick);
    };
    v.raf = requestAnimationFrame(tick);
}

function _mcDriftCorrect() {
    const v = _mcView; if (!v) return;
    const T = _mcCurrentGroupTime();
    v.angles.forEach((a, i) => {
        if (i === v.primaryIdx || !a.vidEl || !a._inRange) return;
        const dur = a.vidEl.duration || a.duration || 0;
        const localT = T - a.normOff;
        if (localT < 0 || localT >= dur) return;
        if (Math.abs(a.vidEl.currentTime - localT) > 0.15) {
            try { a.vidEl.currentTime = localT; } catch(e) {}
        }
        if (v.playing && a.vidEl.paused) a.vidEl.play().catch(()=>{});
    });
    if (v.bwfAudio && v.bwfEnabled && !v.bwfAudio.paused) {
        const bwfT = v.bwfOffset + T;
        if (Math.abs(v.bwfAudio.currentTime - bwfT) > 0.2) {
            try { v.bwfAudio.currentTime = Math.max(0, bwfT); } catch(e) {}
        }
    }
}

function mcTlSeek(e) {
    const v = _mcView; if (!v) return;
    const tl = document.getElementById('mcTl');
    const doSeek = (ev) => {
        const rect = tl.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        _mcSeekGroup(pct * v.groupDur);
    };
    doSeek(e);
    const onMove = ev => doSeek(ev);
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

function _mcKeydown(e) {
    if (!_mcView) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    if (e.key === 'Escape') { closeMcViewer(); e.preventDefault(); e.stopPropagation(); return; }
    if (e.key === ' ') { mcViewerPlayPause(); e.preventDefault(); e.stopPropagation(); return; }
    if (e.key === 'ArrowLeft')  { _mcNudgeStep(-1); e.preventDefault(); e.stopPropagation(); return; }
    if (e.key === 'ArrowRight') { _mcNudgeStep(+1); e.preventDefault(); e.stopPropagation(); return; }
    const num = parseInt(e.key, 10);
    if (num >= 1 && num <= 9) {
        _setMcPrimary(num - 1);
        e.preventDefault();
        e.stopPropagation();
    }
}

function closeMcViewer() {
    const v = _mcView;
    if (!v) return;
    if (v.raf) cancelAnimationFrame(v.raf);
    if (v.drift) clearInterval(v.drift);

    // Dispose every angle's WebAudio graph + the video element itself.
    // Critical for memory: a MediaElementSource keeps a strong reference to its
    // <video>, which itself retains the decoded video buffer. Without disconnect +
    // removeAttribute('src') + load(), each viewer open accumulates a full proxy
    // worth of decoder state in RAM — bloats fast on rapid open/close cycles.
    v.angles.forEach(a => {
        try { if (a._gainNode)     a._gainNode.disconnect(); } catch(e) {}
        try { if (a._mergerNode)   a._mergerNode.disconnect(); } catch(e) {}
        try { if (a._splitterNode) a._splitterNode.disconnect(); } catch(e) {}
        try { if (a._sourceNode)   a._sourceNode.disconnect(); } catch(e) {}
        a._gainNode = a._mergerNode = a._splitterNode = a._sourceNode = null;
        a._audioAttached = false;
        a._monoR = false;
        if (a.vidEl) {
            try {
                a.vidEl.pause();
                a.vidEl.removeAttribute('src');
                a.vidEl.load();
            } catch(e) {}
            a.vidEl = null;
        }
        a.wrapEl = null; a.numBadgeEl = null; a.waitingEl = null;
    });

    if (v.bwfAudio) {
        _unrouteBwf(v.bwfAudio);
        try {
            v.bwfAudio.pause();
            v.bwfAudio.removeAttribute('src');
            v.bwfAudio.load();
        } catch(e) {}
        v.bwfAudio = null;
    }

    // Close the AudioContext so all dangling nodes are freed. A fresh ctx is
    // recreated on next openMcViewer.
    if (window._mcAudioCtx) {
        try { window._mcAudioCtx.close(); } catch(e) {}
        window._mcAudioCtx = null;
    }

    document.getElementById('mcPrimary').innerHTML = '';
    document.getElementById('mcThumbs').innerHTML = '';
    const bwfBtn = document.getElementById('mcBwfBtn');
    if (bwfBtn) bwfBtn.style.display = 'none';
    document.getElementById('mcViewerOverlay').classList.remove('active');
    document.removeEventListener('keydown', _mcKeydown);
    _mcView = null;
}

// Swap to another angle in the same multicam group, preserving the moment in time.
// Uses the offsets so the new clip's currentTime aligns with what was on screen.
function swapToAngle(otherCid) {
    if (!activeClip) return;
    const g = findMcGroup(activeClip.id);
    if (!g || !g.clip_ids.includes(otherCid)) return;
    const other = (clips || []).find(c => c.id === otherCid);
    if (!other) return;
    const player = document.getElementById('player');
    const curT = player && player.currentTime || 0;
    const myOff = g.offsets[activeClip.id] || 0;
    const otherOff = g.offsets[otherCid] || 0;
    const newT = Math.max(0, curT + (otherOff - myOff));
    const wasPlaying = !player.paused;
    selectClip(other);
    // selectClip resets the video; wait for loadedmetadata to apply the new time
    const p = document.getElementById('player');
    p.addEventListener('loadedmetadata', () => {
        try { p.currentTime = Math.min(newT, (p.duration || newT) - 0.04); } catch(e) {}
        if (wasPlaying) p.play().catch(()=>{});
    }, {once: true});
}

