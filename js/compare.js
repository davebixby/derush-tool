// ─── Compare 2-clip overlay ───────────────────────────────────────────
// Module externalisé depuis derush_app.html.

// ─── COMPARE ─────────────────────────────────────────────────────────────────
let _cmpSync = false;
let _cmpClips = [null, null];
// Multicam offset : when both slots belong to the same multicam group, this is
// (offset[slot1] - offset[slot0]) in seconds. So slot1 should always be at
// (slot0.currentTime + _cmpOffset) for the two videos to be frame-aligned.
let _cmpOffset = 0;

function openCompare() {
    const o = document.getElementById('compareOverlay');
    o.classList.add('active');
    const sel0 = document.getElementById('cmpSel0');
    const sel1 = document.getElementById('cmpSel1');
    [sel0, sel1].forEach(s => {
        s.innerHTML = '<option value="">— Sélectionner un clip —</option>';
        clips.forEach(c => { const o = document.createElement('option'); o.value = c.id; o.textContent = `${c.day ? c.day+' · ' : ''}${c.filename}`; s.appendChild(o); });
    });
    if(activeClip) { sel0.value = activeClip.id; loadCmpClip(0); }
}

function closeCompare() {
    document.getElementById('compareOverlay').classList.remove('active');
    ['cmpVid0','cmpVid1'].forEach(id => {
        const v = document.getElementById(id);
        if (v) {
            try { v.pause(); v.removeAttribute('src'); v.load(); } catch(e) {}
        }
    });
    _cmpClips = [null, null];
}

function loadCmpClip(slot) {
    const clipId = document.getElementById(`cmpSel${slot}`).value;
    const clip = clips.find(c => c.id === clipId);
    _cmpClips[slot] = clip || null;
    const vid = document.getElementById(`cmpVid${slot}`);
    const info = document.getElementById(`cmpInfo${slot}`);
    if(!clip) { vid.src=''; info.innerHTML='<span style="color:var(--dim);">Sélectionnez un clip</span>'; _detectCmpMulticam(); return; }
    const proxyUrl = clip.proxy_url || `/proxy/${encodeURIComponent(clip.rel_path).replace(/%2F/g,'/')}`;
    vid.src = proxyUrl; vid.load();
    vid.addEventListener('loadedmetadata', () => { renderCmpMarkers(slot); _detectCmpMulticam(); }, {once: true});
    const uid = currentSession?.user_id || currentSession?.username;
    const RLBL = {'3':'⭐⭐⭐','2':'⭐⭐','1':'⭐','X':'❌'};
    let html = '';
    Object.entries(allNotes).forEach(([key, userNotes]) => {
        const cn = (userNotes || {})[clip.id] || {};
        if(!cn.rating && !cn.notes && !(cn.markers||[]).length) return;
        const uobj = (currentProject?.users||[]).find(u => (u.id||u.username||u.name) === key) || {};
        const col = uobj.color || '#888';
        const lbl = uobj.username || uobj.name || key;
        html += `<div style="margin-bottom:6px;"><span style="color:${col};font-weight:600;font-size:0.82em;">${lbl}</span>`;
        if(cn.rating) html += ` <span class="cmp-rating">${RLBL[cn.rating]||''}</span>`;
        if(cn.notes) html += `<div style="color:var(--dim);font-size:0.78em;margin-top:2px;">${cn.notes}</div>`;
        (cn.markers||[]).forEach(m => {
            html += `<div class="cmp-marker" onclick="(function(){const v=document.getElementById('cmpVid${slot}');if(v)v.currentTime=${m.time||0};})()">${m.tc||''} <span style="font-size:0.85em;opacity:.7;">${m.cat||''}</span> ${m.desc||''}</div>`;
        });
        html += '</div>';
    });
    info.innerHTML = html || '<span style="color:var(--dim);font-size:0.82em;">Pas encore annoté</span>';
}

function renderCmpMarkers(slot) {
    const clip = _cmpClips[slot];
    const vid = document.getElementById(`cmpVid${slot}`);
    const track = document.getElementById(`cmpTrack${slot}`);
    if(!clip || !vid || !track) return;
    track.querySelectorAll('.cmp-pin').forEach(p => p.remove());
    const dur = vid.duration;
    if(!dur) return;
    const RATING_COLORS = {'T':'#a78bfa','S':'#f59e0b','X':'#ef4444','3':'#22c55e','2':'#60a5fa','1':'#94a3b8','D':'#fb923c'};
    Object.values(allNotes).forEach(userNotes => {
        const n = (userNotes || {})[clip.id];
        if(!n) return;
        (n.markers || []).forEach(m => {
            const pin = document.createElement('div');
            pin.className = 'cmp-pin';
            pin.style.left = (m.time / dur * 100) + '%';
            pin.style.color = RATING_COLORS[m.cat] || '#a78bfa';
            const lbl = (m.desc || m.tc || '').substring(0, 40);
            pin.setAttribute('data-label', lbl);
            pin.addEventListener('click', e => { e.stopPropagation(); vid.currentTime = m.time; });
            track.appendChild(pin);
        });
    });
}

// If both compare slots are clips of the same multicam group, auto-enable Sync
// and store the time offset between them. Updates the Sync button label.
function _detectCmpMulticam() {
    const a = _cmpClips[0], b = _cmpClips[1];
    if (!a || !b || a.id === b.id) { _cmpOffset = 0; _updateCmpSyncBtn(); return; }
    const g = findMcGroup(a.id);
    if (g && g.clip_ids.includes(b.id)) {
        _cmpOffset = (g.offsets[b.id] || 0) - (g.offsets[a.id] || 0);
        _cmpSync = true;
        // Snap slot1 to the aligned position right away
        const v0 = document.getElementById('cmpVid0');
        const v1 = document.getElementById('cmpVid1');
        if (v0 && v1 && v1.duration) {
            v1.currentTime = Math.max(0, Math.min(v1.duration - 0.04, v0.currentTime + _cmpOffset));
        }
    } else {
        _cmpOffset = 0;
    }
    _updateCmpSyncBtn();
}

function _updateCmpSyncBtn() {
    const btn = document.getElementById('cmpSyncBtn');
    if (!btn) return;
    const offTxt = _cmpOffset ? ` (Δ${_cmpOffset >= 0 ? '+' : ''}${_cmpOffset.toFixed(2)}s)` : '';
    btn.textContent = `🔗 Sync ${_cmpSync ? 'ON' : 'OFF'}${offTxt}`;
    btn.style.color = _cmpSync ? 'var(--green)' : '';
    btn.title = _cmpOffset ? `Multi-cam aligné automatiquement (offset audio détecté)` : '';
}

function _syncSlot(srcSlot) {
    if (!_cmpSync) return;
    const dst = 1 - srcSlot;
    const vSrc = document.getElementById(`cmpVid${srcSlot}`);
    const vDst = document.getElementById(`cmpVid${dst}`);
    if (!vSrc || !vDst || !vDst.duration) return;
    // slot1 = slot0 + _cmpOffset, so when src=0 dst=1 we ADD offset, when src=1 dst=0 we SUBTRACT
    const target = srcSlot === 0 ? vSrc.currentTime + _cmpOffset
                                 : vSrc.currentTime - _cmpOffset;
    vDst.currentTime = Math.max(0, Math.min(vDst.duration - 0.04, target));
}

function cmpSeek(slot, e) {
    const v = document.getElementById(`cmpVid${slot}`);
    if(!v || !v.duration) return;
    // Use track rect (not timeline) so seek aligns with marker pin positions
    const track = document.getElementById(`cmpTrack${slot}`);
    if(!track) return;
    const doSeek = (ev) => {
        const rect = track.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        v.currentTime = pct * v.duration;
        _syncSlot(slot);
    };
    doSeek(e);
    const onMove = ev => doSeek(ev);
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

function updateCmpTc(slot) {
    const v = document.getElementById(`cmpVid${slot}`);
    const c = _cmpClips[slot];
    if(!v || !c) return;
    document.getElementById(`cmpTc${slot}`).textContent = timeToTC(v.currentTime, c.fps||25);
    if(v.duration) {
        const pct = (v.currentTime / v.duration * 100).toFixed(2) + '%';
        const prog = document.getElementById(`cmpProg${slot}`);
        const head = document.getElementById(`cmpHead${slot}`);
        if(prog) prog.style.width = pct;
        if(head) head.style.left = pct;
    }
    // Drift correction during playback : slot 0 is master.
    if(_cmpSync && slot === 0) {
        const v1 = document.getElementById('cmpVid1');
        const target = v.currentTime + _cmpOffset;
        if(v1 && v1.duration && Math.abs(v1.currentTime - target) > 0.15) {
            v1.currentTime = Math.max(0, Math.min(v1.duration - 0.04, target));
        }
    }
}

function toggleCmpSync() {
    _cmpSync = !_cmpSync;
    _updateCmpSyncBtn();
    if (_cmpSync) _syncSlot(0);
}

