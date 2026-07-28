// ─── Compare 2-clip overlay ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

let _cmpSync = false;
let _cmpClips = [null, null];
let _cmpOffset = 0;
let _cmpActiveSlot = 0;
let _cmpBwf = [null, null];  // {audio, offset, filename, enabled, _onPlay, _onPause, _onSeek, listenersAttached}

// WebAudio pour les slots compare — routing mono-R sur les clips FS5 (LTC sur canal gauche)
let _cmpAudioCtx = null;
let _cmpGainStereo = [null, null];
let _cmpGainMonoR  = [null, null];

function _attachCmpSlotAudio(slot) {
    const video = document.getElementById(`cmpVid${slot}`);
    if (!video || video._cmpAudioAttached) return;
    try {
        if (!_cmpAudioCtx) {
            _cmpAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (typeof _pinStereoDestination === 'function') _pinStereoDestination(_cmpAudioCtx);
        }
        if (_cmpAudioCtx.state === 'suspended') _cmpAudioCtx.resume().catch(() => {});
        const src = _cmpAudioCtx.createMediaElementSource(video);
        const splitter = _cmpAudioCtx.createChannelSplitter(2);
        src.connect(splitter);
        // Route A : stéréo native
        const mergerS = _cmpAudioCtx.createChannelMerger(2);
        splitter.connect(mergerS, 0, 0);
        splitter.connect(mergerS, 1, 1);
        _cmpGainStereo[slot] = _cmpAudioCtx.createGain();
        _cmpGainStereo[slot].gain.value = 1;
        mergerS.connect(_cmpGainStereo[slot]);
        _cmpGainStereo[slot].connect(_cmpAudioCtx.destination);
        // Route B : mono canal droit dupliqué (R→L+R, supprime le LTC du canal gauche)
        const mergerM = _cmpAudioCtx.createChannelMerger(2);
        splitter.connect(mergerM, 1, 0);
        splitter.connect(mergerM, 1, 1);
        _cmpGainMonoR[slot] = _cmpAudioCtx.createGain();
        _cmpGainMonoR[slot].gain.value = 0;
        mergerM.connect(_cmpGainMonoR[slot]);
        _cmpGainMonoR[slot].connect(_cmpAudioCtx.destination);
        video._cmpAudioAttached = true;
    } catch(e) { console.warn('cmp audio routing fail:', e); }
}

function _setCmpMonoR(slot, on) {
    if (_cmpAudioCtx && _cmpAudioCtx.state === 'suspended') _cmpAudioCtx.resume().catch(() => {});
    if (_cmpGainStereo[slot]) _cmpGainStereo[slot].gain.value = on ? 0 : 1;
    if (_cmpGainMonoR[slot])  _cmpGainMonoR[slot].gain.value  = on ? 1 : 0;
}

// ─── Slot actif ───────────────────────────────────────────────────────
function _setCmpActiveSlot(slot) {
    _cmpActiveSlot = slot;
    [0, 1].forEach(i => {
        const el = document.getElementById(`cmpSlot${i}`);
        if (el) el.classList.toggle('cmp-active', i === slot);
    });
}

// ─── Play / pause / nudge ─────────────────────────────────────────────
function cmpTogglePlay() {
    const v = document.getElementById(`cmpVid${_cmpActiveSlot}`);
    if (!v || !v.src) return;
    if (v.paused) {
        _syncSlot(_cmpActiveSlot);
        v.play().catch(() => {});
        if (_cmpSync) {
            const w = document.getElementById(`cmpVid${1 - _cmpActiveSlot}`);
            if (w && w.readyState >= 2) w.play().catch(() => {});
        }
    } else {
        v.pause();
        if (_cmpSync) {
            const w = document.getElementById(`cmpVid${1 - _cmpActiveSlot}`);
            if (w) w.pause();
        }
    }
}

function cmpNudge(slot, secs) {
    const v = document.getElementById(`cmpVid${slot}`);
    if (!v || !v.duration) return;
    v.pause();
    if (_cmpSync) {
        const w = document.getElementById(`cmpVid${1 - slot}`);
        if (w) w.pause();
    }
    v.currentTime = Math.max(0, Math.min(v.duration - 0.04, v.currentTime + secs));
    _syncSlot(slot);
}

// ─── Keyboard handler (capture phase → avant le handler global) ───────
function _cmpKeydown(e) {
    if (!document.getElementById('compareOverlay').classList.contains('active')) return;
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    const fps = (_cmpClips[_cmpActiveSlot] && _cmpClips[_cmpActiveSlot].fps) || 25;
    switch (e.key) {
        case ' ':
            e.preventDefault(); e.stopPropagation();
            cmpTogglePlay();
            return;
        case 'ArrowLeft':
            e.preventDefault(); e.stopPropagation();
            cmpNudge(_cmpActiveSlot, e.shiftKey ? -5 : -(1 / fps));
            return;
        case 'ArrowRight':
            e.preventDefault(); e.stopPropagation();
            cmpNudge(_cmpActiveSlot, e.shiftKey ? 5 : 1 / fps);
            return;
        case 'Escape':
            e.preventDefault(); e.stopPropagation();
            closeCompare();
            return;
        case '0': e.preventDefault(); _setCmpActiveSlot(0); return;
        case '1': e.preventDefault(); _setCmpActiveSlot(1); return;
    }
}

// ─── Open / close ─────────────────────────────────────────────────────
function openCompare() {
    const o = document.getElementById('compareOverlay');
    o.classList.add('active');
    [0, 1].forEach(slot => {
        const s = document.getElementById(`cmpSel${slot}`);
        s.innerHTML = '<option value="">— Sélectionner un clip —</option>';
        clips.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = `${c.day ? c.day + ' · ' : ''}${c.filename}`;
            s.appendChild(opt);
        });
        _cmpBuildComboList(slot);
    });
    if (activeClip) {
        document.getElementById('cmpSel0').value = activeClip.id;
        // Le slot 0 doit refléter l'endroit où on est VRAIMENT dans le lecteur
        // principal, pas une position mémorisée d'une session compare antérieure
        // sur ce même clip (sinon rouvrir Comparer peut ressusciter un ancien 3/4
        // de timeline qui n'a plus rien à voir avec la lecture en cours).
        const mainPlayer = document.getElementById('player');
        if (mainPlayer) _clipResumeTime[activeClip.id] = mainPlayer.currentTime || 0;
        loadCmpClip(0);
    }
    _setCmpActiveSlot(0);
    document.addEventListener('keydown', _cmpKeydown, true);
}

// ─── Combo custom avec miniatures (remplace le <select> natif, gardé caché) ──
function _cmpBuildComboList(slot) {
    const list = document.getElementById(`cmpComboList${slot}`);
    if (!list) return;
    list.innerHTML = '';
    clips.forEach(c => {
        const item = document.createElement('div');
        item.className = 'cmp-combo-item';
        item.dataset.clipId = c.id;
        const label = `${c.day ? c.day + ' · ' : ''}${c.filename}`;
        const img = document.createElement('img');
        img.loading = 'lazy';
        img.src = `/api/project/${currentProjectId}/thumbnail/${c.id}`;
        img.onerror = () => { img.style.visibility = 'hidden'; };
        const span = document.createElement('span');
        span.textContent = label;
        item.appendChild(img);
        item.appendChild(span);
        item.onclick = () => _cmpPickClip(slot, c.id);
        list.appendChild(item);
    });
}

function _cmpToggleCombo(slot) {
    const combo = document.getElementById(`cmpCombo${slot}`);
    const other = document.getElementById(`cmpCombo${1 - slot}`);
    if (!combo) return;
    const willOpen = !combo.classList.contains('open');
    if (other) other.classList.remove('open');
    combo.classList.toggle('open', willOpen);
    if (willOpen) document.addEventListener('click', _cmpComboOutsideClick, { capture: true, once: true });
}

function _cmpComboOutsideClick() {
    [0, 1].forEach(s => { const c = document.getElementById(`cmpCombo${s}`); if (c) c.classList.remove('open'); });
}

function _cmpPickClip(slot, clipId) {
    const sel = document.getElementById(`cmpSel${slot}`);
    if (sel) sel.value = clipId;
    const combo = document.getElementById(`cmpCombo${slot}`);
    if (combo) combo.classList.remove('open');
    loadCmpClip(slot);
}

function _cmpUpdateComboLabel(slot, clip) {
    const thumb = document.getElementById(`cmpComboThumb${slot}`);
    const label = document.getElementById(`cmpComboLabel${slot}`);
    const list = document.getElementById(`cmpComboList${slot}`);
    if (label) label.textContent = clip ? `${clip.day ? clip.day + ' · ' : ''}${clip.filename}` : '— Sélectionner un clip —';
    if (thumb) {
        if (clip) {
            thumb.src = `/api/project/${currentProjectId}/thumbnail/${clip.id}`;
            thumb.style.display = '';
            thumb.onerror = () => { thumb.style.display = 'none'; };
        } else {
            thumb.removeAttribute('src');
            thumb.style.display = 'none';
        }
    }
    if (list) {
        list.querySelectorAll('.cmp-combo-item').forEach(it => {
            it.classList.toggle('cmp-combo-selected', !!clip && it.dataset.clipId === clip.id);
        });
    }
}

function closeCompare() {
    document.getElementById('compareOverlay').classList.remove('active');
    document.removeEventListener('keydown', _cmpKeydown, true);
    [0, 1].forEach(slot => {
        _cleanupCmpBwf(slot);
        const clip = _cmpClips[slot];
        const v = document.getElementById(`cmpVid${slot}`);
        if (clip && v) _clipResumeTime[clip.id] = v.currentTime || 0;
        if (v) try { v.pause(); v.removeAttribute('src'); v.load(); } catch(e) {}
    });
    _cmpClips = [null, null];
    [0, 1].forEach(i => {
        const el = document.getElementById(`cmpSlot${i}`);
        if (el) el.classList.remove('cmp-active');
        const combo = document.getElementById(`cmpCombo${i}`);
        if (combo) combo.classList.remove('open');
        _cmpUpdateComboLabel(i, null);
    });
}

// ─── Load clip into a slot ────────────────────────────────────────────
function loadCmpClip(slot) {
    const clipId = document.getElementById(`cmpSel${slot}`).value;
    const clip = clips.find(c => c.id === clipId);
    // Mémorise la position du clip qu'on quitte dans ce slot avant de le remplacer
    const _prevClip = _cmpClips[slot];
    const _prevVid = document.getElementById(`cmpVid${slot}`);
    if (_prevClip && _prevVid) _clipResumeTime[_prevClip.id] = _prevVid.currentTime || 0;
    _cmpClips[slot] = clip || null;
    const vid = document.getElementById(`cmpVid${slot}`);
    const info = document.getElementById(`cmpInfo${slot}`);
    _cleanupCmpBwf(slot);
    _cmpUpdateComboLabel(slot, clip);
    // Reset immédiat de la barre visuelle : sans ça elle reste affichée à la position
    // du clip précédent tant que 'timeupdate' n'a pas refiré sur la nouvelle vidéo.
    const prog0 = document.getElementById(`cmpProg${slot}`);
    const head0 = document.getElementById(`cmpHead${slot}`);
    if (prog0) prog0.style.width = '0%';
    if (head0) head0.style.left = '0%';
    document.getElementById(`cmpTc${slot}`).textContent = '--:--:--:--';
    if (!clip) {
        vid.src = '';
        info.innerHTML = '<span style="color:var(--dim);">Sélectionnez un clip</span>';
        _detectCmpMulticam();
        return;
    }
    const proxyUrl = clip.proxy_url || `/proxy/${encodeURIComponent(clip.rel_path).replace(/%2F/g, '/')}`;
    vid.src = proxyUrl; vid.load();
    // Recadre les bandes noires incrustées (matte baké) pour ce clip
    if (typeof _applyLetterbox === 'function') _applyLetterbox(vid, clip.id, true);
    vid.addEventListener('loadedmetadata', () => {
        const resumeT = _clipResumeTime[clip.id];
        if (resumeT && resumeT > 0.1) {
            try { vid.currentTime = Math.min(resumeT, (vid.duration || resumeT) - 0.04); } catch(e) {}
        }
        // La ligne au-dessus ne garantit pas un 'timeupdate' immédiat (pas de seek si
        // resumeT est absent/0) → force la synchro visuelle TC/barre tout de suite.
        updateCmpTc(slot);
        renderCmpMarkers(slot); _detectCmpMulticam();
        // Applique le format de cadre sélectionné à ce slot
        if (typeof _drawAspOn === 'function') _drawAspOn(vid, vid.closest('.compare-video-area'), clip.id);
    }, { once: true });
    // Routing WebAudio : supprime le LTC (canal gauche) sur les clips FS5
    _attachCmpSlotAudio(slot);
    _setCmpMonoR(slot, clip.ltc_tc_in_sec != null);
    _loadCmpBwfForSlot(slot, clip);

    const RLBL = { '3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'X': '❌' };
    let html = '';
    Object.entries(allNotes).forEach(([key, userNotes]) => {
        const cn = (userNotes || {})[clip.id] || {};
        if (!cn.rating && !cn.notes && !(cn.markers || []).length) return;
        const uobj = (currentProject?.users || []).find(u => (u.id || u.username || u.name) === key) || {};
        const col = uobj.color || '#888';
        const lbl = uobj.username || uobj.name || key;
        html += `<div style="margin-bottom:6px;"><span style="color:${col};font-weight:600;font-size:0.82em;">${lbl}</span>`;
        if (cn.rating) html += ` <span class="cmp-rating">${RLBL[cn.rating] || ''}</span>`;
        if (cn.notes) html += `<div style="color:var(--dim);font-size:0.78em;margin-top:2px;">${cn.notes}</div>`;
        (cn.markers || []).forEach(m => {
            html += `<div class="cmp-marker" onclick="(function(){const v=document.getElementById('cmpVid${slot}');if(v)v.currentTime=${m.time || 0};})()">${m.tc || ''} <span style="font-size:0.85em;opacity:.7;">${m.cat || ''}</span> ${m.desc || ''}</div>`;
        });
        html += '</div>';
    });
    info.innerHTML = html || '<span style="color:var(--dim);font-size:0.82em;">Pas encore annoté</span>';
}

// ─── Markers ──────────────────────────────────────────────────────────
function renderCmpMarkers(slot) {
    const clip = _cmpClips[slot];
    const vid = document.getElementById(`cmpVid${slot}`);
    const tl = document.getElementById(`cmpTimeline${slot}`);
    if (!clip || !vid || !tl) return;
    tl.querySelectorAll('.cmp-pin').forEach(p => p.remove());
    const dur = vid.duration;
    if (!dur) return;
    const RATING_COLORS = { 'T': '#a78bfa', 'S': '#f59e0b', 'X': '#ef4444', '3': '#22c55e', '2': '#60a5fa', '1': '#94a3b8', 'D': '#fb923c' };
    Object.values(allNotes).forEach(userNotes => {
        const n = (userNotes || {})[clip.id];
        if (!n) return;
        (n.markers || []).forEach(m => {
            const pin = document.createElement('div');
            pin.className = 'cmp-pin';
            pin.style.left = (m.time / dur * 100) + '%';
            pin.style.color = RATING_COLORS[m.cat] || '#a78bfa';
            pin.setAttribute('data-label', (m.desc || m.tc || '').substring(0, 40));
            pin.addEventListener('click', e => { e.stopPropagation(); vid.currentTime = m.time; });
            tl.appendChild(pin);
        });
    });
}

// ─── Multicam sync auto-detection ────────────────────────────────────
function _detectCmpMulticam() {
    const a = _cmpClips[0], b = _cmpClips[1];
    if (!a || !b || a.id === b.id) { _cmpOffset = 0; _cmpSync = false; return; }
    const g = findMcGroup(a.id);
    if (g && g.clip_ids.includes(b.id)) {
        _cmpOffset = (g.offsets[b.id] || 0) - (g.offsets[a.id] || 0);
        _cmpSync = true;
        const v0 = document.getElementById('cmpVid0');
        const v1 = document.getElementById('cmpVid1');
        if (v0 && v1 && v1.duration) {
            v1.currentTime = Math.max(0, Math.min(v1.duration - 0.04, v0.currentTime + _cmpOffset));
        }
    } else {
        _cmpOffset = 0;
        _cmpSync = false;
    }
}

function _syncSlot(srcSlot) {
    if (!_cmpSync) return;
    const dst = 1 - srcSlot;
    const vSrc = document.getElementById(`cmpVid${srcSlot}`);
    const vDst = document.getElementById(`cmpVid${dst}`);
    if (!vSrc || !vDst || !vDst.duration) return;
    const target = srcSlot === 0 ? vSrc.currentTime + _cmpOffset : vSrc.currentTime - _cmpOffset;
    vDst.currentTime = Math.max(0, Math.min(vDst.duration - 0.04, target));
}

// ─── Timeline seek (style multiviewer : zone pleine hauteur) ──────────
function cmpSeek(slot, e) {
    e.preventDefault();
    _setCmpActiveSlot(slot);
    const v = document.getElementById(`cmpVid${slot}`);
    if (!v || !v.duration) return;
    const tl = document.getElementById(`cmpTimeline${slot}`);
    const doSeek = (ev) => {
        const rect = tl.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        v.currentTime = pct * v.duration;
        _syncSlot(slot);
    };
    doSeek(e);
    const onMove = ev => { ev.preventDefault(); doSeek(ev); };
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

// ─── TC + progress update ─────────────────────────────────────────────
function updateCmpTc(slot) {
    const v = document.getElementById(`cmpVid${slot}`);
    const c = _cmpClips[slot];
    if (!v || !c) return;
    document.getElementById(`cmpTc${slot}`).textContent = timeToTC(v.currentTime, c.fps || 25);
    if (v.duration) {
        const pct = (v.currentTime / v.duration * 100).toFixed(2) + '%';
        const prog = document.getElementById(`cmpProg${slot}`);
        const head = document.getElementById(`cmpHead${slot}`);
        if (prog) prog.style.width = pct;
        if (head) head.style.left = pct;
    }
    // Drift correction during playback (slot 0 = master)
    if (_cmpSync && slot === 0) {
        const v1 = document.getElementById('cmpVid1');
        const target = v.currentTime + _cmpOffset;
        if (v1 && v1.duration && Math.abs(v1.currentTime - target) > 0.15) {
            v1.currentTime = Math.max(0, Math.min(v1.duration - 0.04, target));
        }
    }
}

// ─── Son ingé pour les slots compare ──────────────────────────────────
async function _loadCmpBwfForSlot(slot, clip) {
    _cleanupCmpBwf(slot);
    if (!clip || !currentProjectId) return;
    try {
        const r = await apiFetch(`/api/project/${currentProjectId}/clip_bwf/${encodeURIComponent(clip.id)}`);
        const d = await r.json();
        if (!d.ok || !d.stream_url) return;
        const audio = new Audio(d.stream_url);
        audio.preload = 'auto';
        audio.volume = typeof _playerVolume !== 'undefined' ? _playerVolume : 1;
        _cmpBwf[slot] = {
            audio,
            offset: d.bwf_offset_sec || 0,
            filename: d.filename || '',
            enabled: false,
            listenersAttached: false,
        };
        const btn = document.getElementById(`cmpBwfBtn${slot}`);
        if (btn) {
            btn.style.display = '';
            btn.title = `Son ingé: ${d.filename}`;
            btn.classList.remove('bwf-on');
            btn.classList.add('bwf-off');
        }
    } catch(e) {}
}

function _cleanupCmpBwf(slot) {
    const bwf = _cmpBwf[slot];
    if (!bwf) return;
    const v = document.getElementById(`cmpVid${slot}`);
    try { bwf.audio.pause(); bwf.audio.src = ''; bwf.audio.load(); } catch(e) {}
    if (bwf.listenersAttached && v) {
        v.removeEventListener('play',   bwf._onPlay);
        v.removeEventListener('pause',  bwf._onPause);
        v.removeEventListener('seeked', bwf._onSeek);
    }
    // Restaure le son vidéo (gains ou muted selon si WebAudio est attaché)
    const clip = _cmpClips[slot];
    if (_cmpGainStereo[slot] !== null) {
        _setCmpMonoR(slot, !!(clip && clip.ltc_tc_in_sec != null));
    } else if (v) { v.muted = false; }
    _cmpBwf[slot] = null;
    const btn = document.getElementById(`cmpBwfBtn${slot}`);
    if (btn) { btn.style.display = 'none'; btn.classList.remove('bwf-on', 'bwf-off'); }
}

function toggleCmpBwf(slot) {
    const bwf = _cmpBwf[slot];
    if (!bwf) return;
    const v = document.getElementById(`cmpVid${slot}`);
    const btn = document.getElementById(`cmpBwfBtn${slot}`);
    if (bwf.enabled) {
        // OFF → son caméra (restaure le routing selon le type de clip)
        try { bwf.audio.pause(); } catch(e) {}
        bwf.enabled = false;
        const clip = _cmpClips[slot];
        if (_cmpGainStereo[slot] !== null) {
            _setCmpMonoR(slot, !!(clip && clip.ltc_tc_in_sec != null));
        } else if (v) { v.muted = false; }
        if (btn) { btn.classList.remove('bwf-on'); btn.classList.add('bwf-off'); }
    } else {
        // ON → son ingé (mute la vidéo via gains WebAudio ou muted)
        if (_cmpGainStereo[slot] !== null) {
            if (_cmpGainStereo[slot]) _cmpGainStereo[slot].gain.value = 0;
            if (_cmpGainMonoR[slot])  _cmpGainMonoR[slot].gain.value  = 0;
        } else if (v) { v.muted = true; }
        bwf.enabled = true;
        if (!bwf.listenersAttached && v) {
            bwf._onPlay = () => {
                if (!bwf.enabled) return;
                try { bwf.audio.currentTime = Math.max(0, bwf.offset + v.currentTime); } catch(e) {}
                bwf.audio.play().catch(() => {});
            };
            bwf._onPause = () => { if (bwf.enabled) try { bwf.audio.pause(); } catch(e) {} };
            bwf._onSeek = () => { if (bwf.enabled) try { bwf.audio.currentTime = Math.max(0, bwf.offset + v.currentTime); } catch(e) {} };
            v.addEventListener('play',   bwf._onPlay);
            v.addEventListener('pause',  bwf._onPause);
            v.addEventListener('seeked', bwf._onSeek);
            bwf.listenersAttached = true;
        }
        if (v && !v.paused) {
            try { bwf.audio.currentTime = Math.max(0, bwf.offset + v.currentTime); } catch(e) {}
            bwf.audio.play().catch(() => {});
        }
        if (btn) { btn.classList.remove('bwf-off'); btn.classList.add('bwf-on'); }
    }
}
