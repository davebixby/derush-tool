// ─── Sélections (in/out) + Pré-montage ──────────────────────────────────────
// Module externalisé depuis derush_app.html (point 1 : dérushage = pré-montage,
// pas juste un rapport). Une "sélection" est un segment in/out nommé/taggué sur
// un clip, stockée comme les markers (par user, dans allNotes[uid][clip.id].selects
// → undo/redo et sauvegarde gratuits, cf. pushUndo). Le "pré-montage" (nom affiché ;
// identifiants internes restés "basket"/"panier" — allBaskets[uid], /api/.../basket)
// est une bobine personnelle réordonnable, visible en lecture par toute l'équipe,
// éditable seulement par son auteur — cf. CLAUDE.md pour le détail.

let _pendingSelectIn = null;
let allBaskets = {};
let _basketViewUser = null;
let _basketLastResolved = [];  // dernier rendu résolu (clip+select), pour drag/remove/play par identité
let _basketDragIdx = null;

// ─── Marquage in/out ────────────────────────────────────────────────────────

function markSelectIn() {
    if(!activeClip || !currentSession) return;
    if(document.getElementById('selectPopupOverlay').style.display === 'block') return;
    const v = document.getElementById('player');
    if(!v) return;
    _pendingSelectIn = v.currentTime || 0;
    _renderPendingSelectMarker();
    const hint = document.getElementById('selectPendingHint');
    if(hint) hint.style.display = '';
    _updateSelectMarkBtn();
    showSaveStatus('✂️ Entrée posée à ' + timeToTC(_pendingSelectIn, activeClip.fps || 25), '#34d399');
}

function markSelectOut() {
    if(!activeClip || !currentSession) return;
    if(document.getElementById('selectPopupOverlay').style.display === 'block') return;
    if(_pendingSelectIn === null) {
        showToast("Pose d'abord un point d'entrée avec [", 'warn');
        return;
    }
    const v = document.getElementById('player');
    const out = v ? (v.currentTime || 0) : 0;
    if(out <= _pendingSelectIn + 0.05) {
        showToast('Le point de sortie doit être après le point d’entrée', 'warn');
        return;
    }
    if(v && !v.paused) v.pause();
    openSelectPopup(_pendingSelectIn, out);
}

function handleSelectMarkClick() {
    if(_pendingSelectIn === null) markSelectIn();
    else markSelectOut();
}

function cancelPendingSelect() {
    _pendingSelectIn = null;
    _renderPendingSelectMarker();
    const hint = document.getElementById('selectPendingHint');
    if(hint) hint.style.display = 'none';
    _updateSelectMarkBtn();
}

function _updateSelectMarkBtn() {
    const btn = document.getElementById('selectMarkBtn');
    if(!btn) return;
    if(_pendingSelectIn !== null) {
        btn.textContent = '✂️ Fin →';
        btn.style.background = '#f59e0b';
        btn.style.color = '#0a0a14';
        btn.style.borderColor = '#f59e0b';
    } else {
        btn.textContent = '✂️ Sélection';
        btn.style.background = '';
        btn.style.color = '';
        btn.style.borderColor = '#34d39944';
    }
}

function _renderPendingSelectMarker() {
    const track = document.getElementById('timelineTrack');
    if(!track) return;
    let el = document.getElementById('pendingSelectInMarker');
    if(_pendingSelectIn === null) { if(el) el.remove(); return; }
    const v = document.getElementById('player');
    const dur = (v && v.duration && !isNaN(v.duration)) ? v.duration : 1;
    if(!el) {
        el = document.createElement('div');
        el.id = 'pendingSelectInMarker';
        track.appendChild(el);
    }
    el.style.left = (_pendingSelectIn / dur * 100) + '%';
}

// ─── Popup nommage sélection ────────────────────────────────────────────────

let _selectPopupIn = 0, _selectPopupOut = 0, _selectPopupEditId = null;
let _selectPopupTags = [];

function _nextSelectDefaultName() {
    if(!activeClip || !currentSession) return 'Sélection';
    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[activeClip.id] || {};
    return 'Sélection ' + ((n.selects || []).length + 1);
}

// Vocabulaire de tags proposé dans le popup : union des tags clip ET des tags
// déjà posés sur d'autres sélections, toute l'équipe confondue (allNotes est
// déjà chargé intégralement côté client — aucun appel serveur). Volontairement
// distinct de _allProjectTags() (qui n'alimente que le filtre par tags de clip,
// clip-level uniquement) pour ne pas faire apparaître dans CE filtre un tag qui
// ne matcherait jamais aucun clip.
function _allProjectTagsForSuggest() {
    const set = new Set();
    Object.values(allNotes).forEach(byClip => {
        Object.values(byClip || {}).forEach(cn => {
            (cn.tags || []).forEach(t => set.add(t));
            (cn.selects || []).forEach(s => (s.tags || []).forEach(t => set.add(t)));
        });
    });
    return [...set].sort((a, b) => a.localeCompare(b));
}

function _spRenderTagChips() {
    const chips = document.getElementById('selectPopupTagsChips');
    if(!chips) return;
    chips.innerHTML = _selectPopupTags.map(t =>
        `<span class="tag-chip">${_escHtml(t)}<span class="tag-x" onclick="_spRemoveTag('${t.replace(/'/g, "\\'")}')">×</span></span>`
    ).join('');
}

function _spRenderTagSuggestions() {
    const box = document.getElementById('selectPopupTagSuggest');
    if(!box) return;
    const already = new Set(_selectPopupTags);
    const suggestions = _allProjectTagsForSuggest().filter(t => !already.has(t));
    if(!suggestions.length) { box.innerHTML = ''; return; }
    box.innerHTML = suggestions.map(t =>
        `<button type="button" class="sp-tag-pill" onclick="_spAddTag('${t.replace(/'/g, "\\'")}')">+ ${_escHtml(t)}</button>`
    ).join('');
}

function _spAddTag(tag) {
    tag = (tag || '').trim().replace(/,/g, '');
    if(!tag || _selectPopupTags.includes(tag)) return;
    _selectPopupTags.push(tag);
    _spRenderTagChips();
    _spRenderTagSuggestions();
}

function _spRemoveTag(tag) {
    _selectPopupTags = _selectPopupTags.filter(t => t !== tag);
    _spRenderTagChips();
    _spRenderTagSuggestions();
}

function _spTagInputKeydown(e) {
    if(e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    _spAddTag(e.target.value);
    e.target.value = '';
}

function openSelectPopup(inSec, outSec) {
    _selectPopupIn = inSec;
    _selectPopupOut = outSec;
    _selectPopupEditId = null;
    _selectPopupTags = [];
    const fps = activeClip.fps || 25;
    document.getElementById('selectPopupTc').textContent =
        timeToTC(inSec, fps) + ' → ' + timeToTC(outSec, fps) + ' (' + (outSec - inSec).toFixed(1) + 's)';
    document.getElementById('selectPopupName').value = _nextSelectDefaultName();
    document.getElementById('selectPopupTagInput').value = '';
    document.getElementById('selectPopupDesc').value = '';
    document.getElementById('selectPopupConfirmBtn').textContent = 'Créer la sélection';
    _spRenderTagChips();
    _spRenderTagSuggestions();
    document.getElementById('selectPopupOverlay').style.display = 'block';
    document.getElementById('selectPopup').style.display = 'block';
    requestAnimationFrame(() => requestAnimationFrame(() => {
        const el = document.getElementById('selectPopupName');
        if(el) { el.focus(); el.select(); }
    }));
}

function editSelect(id) {
    if(!activeClip || !currentSession) return;
    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[activeClip.id] || {};
    const sel = (n.selects || []).find(s => s.id === id);
    if(!sel) return;
    _selectPopupIn = sel.in;
    _selectPopupOut = sel.out;
    _selectPopupEditId = id;
    _selectPopupTags = (sel.tags || []).slice();
    const fps = activeClip.fps || 25;
    document.getElementById('selectPopupTc').textContent =
        timeToTC(sel.in, fps) + ' → ' + timeToTC(sel.out, fps) + ' (' + (sel.out - sel.in).toFixed(1) + 's)';
    document.getElementById('selectPopupName').value = sel.name || '';
    document.getElementById('selectPopupTagInput').value = '';
    document.getElementById('selectPopupDesc').value = sel.desc || '';
    document.getElementById('selectPopupConfirmBtn').textContent = 'Mettre à jour';
    _spRenderTagChips();
    _spRenderTagSuggestions();
    document.getElementById('selectPopupOverlay').style.display = 'block';
    document.getElementById('selectPopup').style.display = 'block';
    requestAnimationFrame(() => requestAnimationFrame(() => {
        const el = document.getElementById('selectPopupName');
        if(el) { el.focus(); el.select(); }
    }));
}

function cancelSelectPopup() {
    document.getElementById('selectPopupOverlay').style.display = 'none';
    document.getElementById('selectPopup').style.display = 'none';
    _selectPopupEditId = null;
    cancelPendingSelect();
}

function confirmSelect() {
    if(!activeClip || !currentSession) return;
    const uid = currentSession.user_id;
    const name = (document.getElementById('selectPopupName').value || '').trim() || 'Sélection';
    const pendingTagInput = (document.getElementById('selectPopupTagInput').value || '').trim();
    if(pendingTagInput) _spAddTag(pendingTagInput);  // tag tapé mais pas validé par Entrée : on ne le perd pas
    const tags = _selectPopupTags.slice();
    const desc = (document.getElementById('selectPopupDesc').value || '').trim();

    if(!allNotes[uid]) allNotes[uid] = {};
    if(!allNotes[uid][activeClip.id]) allNotes[uid][activeClip.id] = {};
    pushUndo();
    const n = allNotes[uid][activeClip.id];
    if(!n.selects) n.selects = [];

    let isNew = false;
    let newSelectId = null;
    if(_selectPopupEditId) {
        const sel = n.selects.find(s => s.id === _selectPopupEditId);
        if(sel) { sel.name = name; sel.tags = tags; sel.desc = desc; }
    } else {
        newSelectId = Math.random().toString(36).slice(2, 10);
        n.selects.push({
            id: newSelectId,
            in: _selectPopupIn, out: _selectPopupOut,
            name, tags, desc,
        });
        n.selects.sort((a, b) => a.in - b.in);
        isNew = true;
    }

    document.getElementById('selectPopupOverlay').style.display = 'none';
    document.getElementById('selectPopup').style.display = 'none';
    _selectPopupEditId = null;
    _pendingSelectIn = null;
    _renderPendingSelectMarker();
    const hint = document.getElementById('selectPendingHint');
    if(hint) hint.style.display = 'none';
    _updateSelectMarkBtn();

    if(isNew && newSelectId) {
        _pushToBasket(activeClip.id, newSelectId);
        _updateBasketBadge();
        saveBasket();
    }

    renderMarkers();  // appelle aussi renderSelects()
    renderClipList();
    saveNotes(true);  // sauve immédiatement (cf. bug tag 0.3.34 — ne pas attendre le cycle de 30s)
    showSaveStatus(isNew ? '✂️ Sélection créée et ajoutée au pré-montage 📽️' : '✂️ Sélection mise à jour', '#34d399');
}

function deleteSelect(id, e) {
    if(e) e.stopPropagation();
    if(!activeClip || !currentSession) return;
    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[activeClip.id] || {};
    const idx = (n.selects || []).findIndex(s => s.id === id);
    if(idx < 0) return;
    pushUndo();
    n.selects.splice(idx, 1);
    renderMarkers();
    renderClipList();
    saveNotes(true);
    showSaveStatus('🗑 Sélection supprimée (Ctrl+Z pour annuler)', '#f59e0b');
}

let _selectPreviewHandler = null, _selectPreviewOut = null;

function previewSelect(id, e) {
    if(e) e.stopPropagation();
    if(!activeClip || !currentSession) return;
    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[activeClip.id] || {};
    const sel = (n.selects || []).find(s => s.id === id);
    if(!sel) return;
    const v = document.getElementById('player');
    if(!v) return;
    if(_selectPreviewHandler) { v.removeEventListener('timeupdate', _selectPreviewHandler); _selectPreviewHandler = null; }
    v.currentTime = sel.in;
    _selectPreviewOut = sel.out;
    _selectPreviewHandler = () => {
        if(v.currentTime >= _selectPreviewOut) {
            v.pause();
            v.removeEventListener('timeupdate', _selectPreviewHandler);
            _selectPreviewHandler = null;
        }
    };
    v.addEventListener('timeupdate', _selectPreviewHandler);
    v.play();
}

// Pousse (clip, select) dans le panier de l'utilisateur courant sans notifier —
// utilisée à la fois par le clic manuel 📽️ (addSelectToBasket, avec toast) et par
// la création d'une sélection (confirmSelect, auto-ajout — cf. retour terrain :
// une sélection visible en vert sur la timeline mais absente du panier tant
// qu'on n'a pas explicitement cliqué 📽️ était vécu comme un bug, pas une étape
// volontaire). Retourne false si déjà présent.
function _pushToBasket(clipId, selectId) {
    if(!currentSession) return false;
    const uid = currentSession.user_id;
    if(!allBaskets[uid]) allBaskets[uid] = [];
    const already = allBaskets[uid].some(b => b.clip_id === clipId && b.select_id === selectId);
    if(already) return false;
    allBaskets[uid].push({id: Math.random().toString(36).slice(2, 10), clip_id: clipId, select_id: selectId});
    return true;
}

function addSelectToBasket(selectId, e) {
    if(e) e.stopPropagation();
    if(!activeClip || !currentSession) return;
    if(!_pushToBasket(activeClip.id, selectId)) { showToast('Déjà dans ton pré-montage', 'info'); return; }
    renderSelects();
    _updateBasketBadge();
    saveBasket();
    showToast('Ajouté au pré-montage 📽️', 'ok');
}

// ─── Rendu panneau "Sélections" + rangées timeline ─────────────────────────

function renderSelects() {
    const panel = document.getElementById('selectsPanel');
    const list = document.getElementById('selectsList');
    const track = document.getElementById('timelineTrack');
    if(track) track.querySelectorAll('.timeline-select-range').forEach(el => el.remove());
    if(!list) return;
    list.innerHTML = '';
    if(!activeClip || !currentSession) { if(panel) panel.style.display = 'none'; return; }
    if(panel) panel.style.display = '';

    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[activeClip.id] || {};
    const selects = n.selects || [];
    const v = document.getElementById('player');
    const dur = (v && v.duration && !isNaN(v.duration)) ? v.duration : 1;
    const myBasketSelectIds = new Set(
        (allBaskets[uid] || []).filter(b => b.clip_id === activeClip.id).map(b => b.select_id)
    );

    if(!selects.length) {
        list.innerHTML = '<p style="color:var(--dim);font-size:0.78em;padding:4px 2px;">Aucune sélection sur ce clip. Pose un point d’entrée avec <span class="kbd" style="font-size:0.95em;">[</span> pendant la lecture.</p>';
        return;
    }

    const fps = activeClip.fps || 25;
    selects.forEach(sel => {
        const inBasket = myBasketSelectIds.has(sel.id);
        const row = document.createElement('div');
        row.className = 'select-row';
        const tcIn = timeToTC(sel.in, fps), tcOut = timeToTC(sel.out, fps);
        const tagsHtml = (sel.tags || []).length
            ? `<div class="select-tags">${sel.tags.map(t => `<span>${_escHtml(t)}</span>`).join('')}</div>` : '';
        const thumbUrl = `/api/project/${currentProjectId}/thumbnail/${activeClip.id}?t=${Math.floor(sel.in)}`;
        row.innerHTML = `<div class="select-row-main">
            <img class="select-thumb" src="${thumbUrl}" loading="lazy" onerror="this.style.visibility='hidden'">
            <div class="select-tc">${tcIn}→${tcOut} <span style="opacity:.6;">(${(sel.out - sel.in).toFixed(1)}s)</span></div>
            <div class="select-name">${_escHtml(sel.name || 'Sélection')}</div>
            <div class="select-actions">
                <button title="Aperçu" onclick="previewSelect('${sel.id}',event)">▶</button>
                <button title="${inBasket ? 'Déjà dans le pré-montage' : 'Ajouter au pré-montage'}" onclick="addSelectToBasket('${sel.id}',event)" style="${inBasket ? 'color:#34d399;' : ''}">📽️${inBasket ? '✓' : '+'}</button>
                <button title="Éditer" onclick="event.stopPropagation();editSelect('${sel.id}')">✏️</button>
                <button title="Supprimer" onclick="deleteSelect('${sel.id}',event)" style="color:#ef4444;">🗑</button>
            </div>
        </div>${sel.desc ? `<div style="color:var(--dim);font-size:0.9em;margin-top:2px;">${_escHtml(sel.desc)}</div>` : ''}${tagsHtml}`;
        row.onclick = (e) => {
            if(e.target.closest('.select-actions')) return;
            if(v) v.currentTime = sel.in;
        };
        list.appendChild(row);

        if(track && v && v.duration) {
            const bar = document.createElement('div');
            bar.className = 'timeline-select-range';
            bar.style.left = (sel.in / dur * 100) + '%';
            bar.style.width = Math.max(0.3, (sel.out - sel.in) / dur * 100) + '%';
            bar.title = sel.name || 'Sélection';
            bar.onclick = (e) => { e.stopPropagation(); if(v) v.currentTime = sel.in; };
            const handleIn = document.createElement('div');
            handleIn.className = 'tsr-handle tsr-handle-in';
            bar.appendChild(handleIn);
            const handleOut = document.createElement('div');
            handleOut.className = 'tsr-handle tsr-handle-out';
            bar.appendChild(handleOut);
            _wireSelectRangeHandle(handleIn, bar, sel, 'in', track, v, dur);
            _wireSelectRangeHandle(handleOut, bar, sel, 'out', track, v, dur);
            track.appendChild(bar);
        }
    });
}

// Poignées de redimensionnement sur la bande verte (réduire/agrandir une
// sélection existante). Même pattern que le drag des pins de marker dans
// renderMarkers() : la donnée réelle (sel.in/sel.out) n'est mutée QU'À la fin
// du glisser (après pushUndo) — pendant le glisser, seuls le style CSS de la
// bande et la position de lecture bougent, pour permettre un undo propre qui
// restaure l'état exact d'avant le drag.
function _wireSelectRangeHandle(handle, bar, sel, edge, track, v, dur) {
    const MIN_DUR = 0.08;  // ~2 frames à 25fps — évite une sélection de durée nulle/négative
    handle.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        const rect = track.getBoundingClientRect();
        let liveIn = sel.in, liveOut = sel.out, wasDragged = false;
        const onMove = (e2) => {
            if(!wasDragged && Math.abs(e2.clientX - e.clientX) < 3) return;
            wasDragged = true;
            const ratio = Math.max(0, Math.min(1, (e2.clientX - rect.left) / rect.width));
            const t = ratio * dur;
            if(edge === 'in') liveIn = Math.max(0, Math.min(t, sel.out - MIN_DUR));
            else liveOut = Math.min(dur, Math.max(t, sel.in + MIN_DUR));
            bar.style.left = (liveIn / dur * 100) + '%';
            bar.style.width = Math.max(0.3, (liveOut - liveIn) / dur * 100) + '%';
            if(v) v.currentTime = edge === 'in' ? liveIn : liveOut;
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            if(!wasDragged) return;
            if(!activeClip || !currentSession) return;
            pushUndo();
            sel.in = liveIn;
            sel.out = liveOut;
            const uid = currentSession.user_id;
            const n = (allNotes[uid] || {})[activeClip.id] || {};
            if(n.selects) n.selects.sort((a, b) => a.in - b.in);
            renderMarkers();  // ré-affiche sélections + markers + timeline
            renderClipList();
            saveNotes(true);
            showSaveStatus('✂️ Sélection ajustée', '#34d399');
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
    handle.addEventListener('click', (e) => e.stopPropagation());
}

function _escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// ─── Panier : sauvegarde + badge ────────────────────────────────────────────

async function saveBasket() {
    if(!currentSession || !currentProjectId) return;
    const uid = currentSession.user_id;
    try {
        await apiFetch(`/api/project/${currentProjectId}/basket`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({basket: allBaskets[uid] || []}),
        });
    } catch(e) {}
}

function _updateBasketBadge() {
    const badge = document.getElementById('basketBadge');
    if(!badge || !currentSession) return;
    const uid = currentSession.user_id;
    const n = (allBaskets[uid] || []).length;
    badge.style.display = n > 0 ? '' : 'none';
    badge.textContent = n;
}

// ─── Overlay panier ─────────────────────────────────────────────────────────

function openBasket() {
    if(!currentSession) return;
    _basketViewUser = currentSession.user_id;
    _populateBasketUserSelect();
    renderBasketOverlay();
    document.getElementById('basketOverlay').classList.add('active');
    document.addEventListener('keydown', _basketKeydown, true);
}

function closeBasket() {
    _basketStop();
    _basketReleaseViewer();
    _basketCurrentItemRef = null;
    document.removeEventListener('keydown', _basketKeydown, true);
    const ov = document.getElementById('basketOverlay');
    if(ov) ov.classList.remove('active');
    const menu = document.getElementById('basketExportMenu');
    if(menu) menu.style.display = 'none';
}

// Capture phase, comme _cmpKeydown (js/compare.js) : intercepte avant le handler
// clavier global (qui se met de côté dès que #basketOverlay est actif, cf.
// derush_app.html). Espace pilote #basketVid, pas le lecteur principal caché.
function _basketKeydown(e) {
    if(!document.getElementById('basketOverlay').classList.contains('active')) return;
    const tag = e.target.tagName;
    if(tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    switch(e.key) {
        case ' ':
            e.preventDefault(); e.stopPropagation();
            _basketTogglePlay();
            return;
        case 'Escape':
            e.preventDefault(); e.stopPropagation();
            closeBasket();
            return;
    }
}

function _populateBasketUserSelect() {
    const sel = document.getElementById('basketUserSel');
    if(!sel || !currentSession) return;
    const myUid = currentSession.user_id;
    const users = (currentProject && currentProject.users) || [];
    sel.innerHTML = '';
    const seen = new Set();
    const addOpt = (uid, label, mine) => {
        if(!uid || seen.has(uid)) return;
        seen.add(uid);
        const opt = document.createElement('option');
        opt.value = uid;
        opt.textContent = mine ? `📽️ Mon pré-montage (${label})` : `👁 Pré-montage de ${label}`;
        sel.appendChild(opt);
    };
    addOpt(myUid, currentSession.name || myUid, true);
    users.forEach(u => {
        const uid = u.id || u.username || u.name;
        if(!uid || uid === myUid) return;
        addOpt(uid, u.username || u.name || uid, false);
    });
    sel.value = _basketViewUser;
}

function _basketSwitchUser(uid) {
    _basketStop();
    _basketCurrentItemRef = null;
    _basketViewUser = uid;
    renderBasketOverlay();
}

function _fmtDurShort(sec) {
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return m > 0 ? `${m}min ${s}s` : `${s}s`;
}

function renderBasketOverlay() {
    const body = document.getElementById('basketBody');
    if(!body || !currentSession) return;
    const isMine = _basketViewUser === currentSession.user_id;
    const clearBtn = document.getElementById('basketClearBtn');
    if(clearBtn) clearBtn.style.display = isMine ? '' : 'none';

    const items = allBaskets[_basketViewUser] || [];
    const resolved = items.map(it => {
        const clip = clips.find(c => c.id === it.clip_id);
        const uNotes = (allNotes[_basketViewUser] || {})[it.clip_id] || {};
        const sel = (uNotes.selects || []).find(s => s.id === it.select_id);
        return {item: it, clip, sel};
    }).filter(r => r.clip && r.sel);
    _basketLastResolved = resolved;

    // Un item peut changer d'INDEX (réorganisation, suppression) sans changer
    // d'IDENTITÉ — on retrouve la position courante par référence d'objet plutôt
    // que de garder l'ancien index, sinon un glisser-déposer pendant la lecture
    // ferait sauter la visionneuse vers une autre sélection.
    if(_basketCurrentItemRef) {
        const idx = resolved.findIndex(r => r.item === _basketCurrentItemRef);
        if(idx < 0) { _basketStop(); _basketCurrentItemRef = null; _basketPlayIdx = -1; }
        else _basketPlayIdx = idx;
    }

    const totalDur = resolved.reduce((sum, r) => sum + Math.max(0, r.sel.out - r.sel.in), 0);
    const totalEl = document.getElementById('basketDurTotal');
    if(totalEl) {
        totalEl.textContent = resolved.length
            ? `${resolved.length} sélection${resolved.length > 1 ? 's' : ''} · ${_fmtDurShort(totalDur)}` : '';
    }

    if(!resolved.length) {
        body.innerHTML = `<p style="color:var(--dim);text-align:center;margin-top:30px;">Pré-montage vide${isMine ? " — ajoute des sélections depuis le panneau ✂️ Sélections d'un clip." : "."}</p>`;
        _basketRenderSeqTimeline();
        return;
    }

    body.innerHTML = '';
    resolved.forEach((r, idx) => {
        const row = document.createElement('div');
        row.className = 'basket-item';
        row.draggable = isMine;
        row.dataset.idx = String(idx);
        const dur = Math.max(0, r.sel.out - r.sel.in);
        const fps = r.clip.fps || 25;
        const thumbUrl = `/api/project/${currentProjectId}/thumbnail/${r.clip.id}?t=${Math.floor(r.sel.in)}`;
        row.innerHTML = `<div class="basket-item-thumb-wrap" style="background-image:url('${thumbUrl}');">
                <div class="bi-scrub-bar"></div>
                <div class="bi-scrub-tc"></div>
                <div class="bi-play-badge">▶</div>
            </div>
            <div class="basket-item-info">
                <div class="basket-item-name">${_escHtml(r.sel.name || 'Sélection')} <span style="color:var(--dim);font-weight:400;">— ${_escHtml(r.clip.filename || r.clip.stem || '')}</span></div>
                <div class="basket-item-meta">${timeToTC(r.sel.in, fps)} → ${timeToTC(r.sel.out, fps)} · ${dur.toFixed(1)}s</div>
            </div>
            <div class="basket-item-actions">
                <button title="Lire depuis ici" onclick="_basketPlayFrom(${idx})">▶</button>
                ${isMine ? `<button title="Retirer du pré-montage" onclick="_basketRemoveAt(${idx})" style="color:#ef4444;">🗑</button>` : ''}
            </div>`;
        if(isMine) _wireBasketDrag(row);
        _wireBasketRowHover(row, r, idx);
        body.appendChild(row);
    });
    _highlightBasketPlaying();
    _basketRenderSeqTimeline();

    // Rien encore chargé dans la visionneuse (premier open, ou juste après avoir
    // ajouté la toute première sélection) → charge la première, en pause, pour
    // que le volet de droite ne reste pas vide.
    if(!_basketCurrentItemRef && resolved.length) {
        _basketGoto(0, resolved[0].sel.in, false);
    }
}

// Survol de LA CARTE ENTIÈRE (pas juste la vignette — demande explicite : "je
// veux que ça prenne en compte toute la bulle du clip"). Le défilement des
// frames de la sélection (pas tout le clip — sinon sur un plan de 20 min, la
// plupart des frames tomberaient hors de la plage retenue) s'affiche EN PLACE
// sur la vignette elle-même via background-position, PAS dans un popup flottant
// à côté (rejeté explicitement : "pas que tu en recrées une à côté"). Clé de
// garde dédiée (_activeHoverSelectKey, clip.id + select.id) : deux entrées du
// pré-montage peuvent partager le même clip avec des sélections différentes.
let _activeHoverSelectKey = null;
const _BASKET_STRIP_N = 8;

function _wireBasketRowHover(row, r, idx) {
    const wrap = row.querySelector('.basket-item-thumb-wrap');
    if(!wrap || !r.clip.duration_sec) return;
    const key = r.clip.id + ':' + r.sel.id;
    const scrubBar = wrap.querySelector('.bi-scrub-bar');
    const scrubTcEl = wrap.querySelector('.bi-scrub-tc');
    const span = Math.max(0.1, r.sel.out - r.sel.in);
    const staticUrl = `/api/project/${currentProjectId}/thumbnail/${r.clip.id}?t=${Math.floor(r.sel.in)}`;
    const stripUrl = `/api/project/${currentProjectId}/select_strip/${r.clip.id}?select_id=${encodeURIComponent(r.sel.id)}&in=${r.sel.in}&out=${r.sel.out}&n=${_BASKET_STRIP_N}`;
    let stripReady = false;

    row.addEventListener('click', (e) => {
        if(e.target.closest('.basket-item-actions')) return;
        _basketPlayFrom(idx);
    });

    row.addEventListener('mouseenter', () => {
        _activeHoverSelectKey = key;
        row.classList.add('hovering');
        if(!stripReady) {
            const loader = new Image();
            loader.onload = () => {
                stripReady = true;
                if(_activeHoverSelectKey === key) {
                    wrap.style.backgroundImage = `url(${stripUrl})`;
                    wrap.style.backgroundSize = `${_BASKET_STRIP_N * 112}px 63px`;
                }
            };
            loader.src = stripUrl;
        } else {
            wrap.style.backgroundImage = `url(${stripUrl})`;
            wrap.style.backgroundSize = `${_BASKET_STRIP_N * 112}px 63px`;
        }
    });

    row.addEventListener('mousemove', (e) => {
        // Ratio calculé sur la largeur de la VIGNETTE (clampé 0-1) même si le
        // survol déclencheur vient d'ailleurs sur la carte — "toute la bulle"
        // déclenche, mais la position défilée reste ancrée sur la vignette.
        const rect = wrap.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(0.9999, (e.clientX - rect.left) / rect.width));
        const frameIdx = Math.floor(ratio * _BASKET_STRIP_N);
        const tSec = r.sel.in + frameIdx * span / _BASKET_STRIP_N;
        if(scrubBar) scrubBar.style.width = (ratio * 100) + '%';
        if(scrubTcEl) scrubTcEl.textContent = timeToTC(tSec, r.clip.fps || 25).slice(0, 8);
        if(stripReady) wrap.style.backgroundPosition = `-${frameIdx * 112}px 0`;
    });

    row.addEventListener('mouseleave', () => {
        if(_activeHoverSelectKey === key) _activeHoverSelectKey = null;
        row.classList.remove('hovering');
        if(scrubBar) scrubBar.style.width = '0%';
        wrap.style.backgroundImage = `url('${staticUrl}')`;
        wrap.style.backgroundPosition = 'center';
        wrap.style.backgroundSize = 'cover';
    });
}

function _wireBasketDrag(row) {
    row.addEventListener('dragstart', () => {
        _basketDragIdx = parseInt(row.dataset.idx, 10);
        row.classList.add('dragging');
    });
    row.addEventListener('dragend', () => {
        row.classList.remove('dragging');
        document.querySelectorAll('.basket-item.drag-over').forEach(r => r.classList.remove('drag-over'));
        _basketDragIdx = null;
    });
    row.addEventListener('dragover', (e) => { e.preventDefault(); row.classList.add('drag-over'); });
    row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
    row.addEventListener('drop', (e) => {
        e.preventDefault();
        row.classList.remove('drag-over');
        const toIdx = parseInt(row.dataset.idx, 10);
        if(_basketDragIdx === null || _basketDragIdx === toIdx) return;
        const fromR = _basketLastResolved[_basketDragIdx];
        const toR = _basketLastResolved[toIdx];
        const arr = allBaskets[_basketViewUser];
        if(!fromR || !toR || !arr) return;
        const fromRealIdx = arr.indexOf(fromR.item);
        const toRealIdx = arr.indexOf(toR.item);
        if(fromRealIdx < 0 || toRealIdx < 0) return;
        const [moved] = arr.splice(fromRealIdx, 1);
        arr.splice(toRealIdx, 0, moved);
        renderBasketOverlay();
        saveBasket();
    });
}

function _basketRemoveAt(idx) {
    const r = _basketLastResolved[idx];
    if(!r) return;
    const arr = allBaskets[_basketViewUser];
    if(!arr) return;
    const realIdx = arr.indexOf(r.item);
    if(realIdx < 0) return;
    if(_basketPlaying && idx === _basketPlayIdx) _basketStop();
    arr.splice(realIdx, 1);
    renderBasketOverlay();
    _updateBasketBadge();
    if(activeClip) renderSelects();  // rafraîchit le badge 📽️✓/+ si le clip actif est concerné
    saveBasket();
}

let _basketClearConfirmUntil = 0;

function _basketClear() {
    if(!currentSession || _basketViewUser !== currentSession.user_id) return;
    const now = Date.now();
    if(now < _basketClearConfirmUntil) {
        _basketStop();
        allBaskets[_basketViewUser] = [];
        _basketClearConfirmUntil = 0;
        renderBasketOverlay();
        _updateBasketBadge();
        if(activeClip) renderSelects();
        saveBasket();
        showToast('Pré-montage vidé', 'ok');
        return;
    }
    _basketClearConfirmUntil = now + 8000;
    showToast('Reclique sur 🗑 Vider dans les 8s pour confirmer', 'warn');
}

// ─── Visionneuse + lecture bout-à-bout ──────────────────────────────────────
// Lecteur vidéo DÉDIÉ (#basketVid), pas le lecteur principal : #basketOverlay
// est plein écran et opaque, il masque totalement #player derrière lui — y
// jouer la lecture la rendait invisible tant qu'on ne fermait pas le
// pré-montage. Retour terrain : "ça serait bien d'avoir une visionneuse dans
// le panier". Découplé de selectClip()/_clipResumeTime : pas de dépendance au
// clip actif du lecteur principal, juste src + currentTime + play directs.

let _basketPlaying = false, _basketPlayIdx = -1;
let _basketCurrentItemRef = null;  // identité de l'item chargé dans #basketVid (joue ou pas)
let _basketVidHandlersAttached = false;

// Attache les listeners du lecteur dédié UNE SEULE FOIS (l'élément #basketVid est
// statique dans le DOM, pas recréé à chaque render) : timeupdate pilote à la fois
// l'avancée automatique en fin de segment ET la tête de la timeline de séquence.
function _ensureBasketVidHandlers() {
    if(_basketVidHandlersAttached) return;
    const vid = document.getElementById('basketVid');
    if(!vid) return;
    vid.addEventListener('timeupdate', () => {
        const cur = _basketLastResolved[_basketPlayIdx];
        if(cur && _basketPlaying && vid.currentTime >= cur.sel.out) { _basketAdvance(); return; }
        _basketUpdateSeqHead();
    });
    vid.addEventListener('loadedmetadata', () => { if(typeof refreshAllAspectOverlays === 'function') refreshAllAspectOverlays(); });
    _basketVidHandlersAttached = true;
}

function _basketTogglePlay() {
    if(_basketPlaying) {
        const vid = document.getElementById('basketVid');
        if(vid) vid.pause();
        _basketPlaying = false;
        _setBasketPlayBtnLabel();
        return;
    }
    if(!_basketLastResolved.length) { showToast('Pré-montage vide', 'warn'); return; }
    if(_basketPlayIdx >= 0 && _basketLastResolved[_basketPlayIdx]) {
        const vid = document.getElementById('basketVid');
        _basketPlaying = true;
        _setBasketPlayBtnLabel();
        if(vid) vid.play().catch(() => {});
    } else {
        _basketGoto(0, _basketLastResolved[0].sel.in, true);
    }
}

function _setBasketPlayBtnLabel() {
    const btn = document.getElementById('basketPlayBtn');
    if(btn) btn.textContent = _basketPlaying ? '⏸ Pause' : '▶ Lire tout';
}

function _updateBasketViewerInfo(r) {
    const nameEl = document.getElementById('basketViewerName');
    const metaEl = document.getElementById('basketViewerMeta');
    const fps = r.clip.fps || 25;
    if(nameEl) nameEl.textContent = (r.sel.name || 'Sélection') + ' — ' + (r.clip.filename || r.clip.stem || '');
    if(metaEl) metaEl.textContent = timeToTC(r.sel.in, fps) + ' → ' + timeToTC(r.sel.out, fps);
    const ph = document.getElementById('basketViewerPlaceholder');
    if(ph) ph.style.display = 'none';
}

// Cœur unique de navigation dans le pré-montage : charge (si besoin) le clip de
// l'item idx, seek à withinOffset (en secondes DANS ce clip, pas dans la
// séquence), puis joue ou reste en pause selon autoplay. Utilisé par le clic sur
// une vignette, "Lire tout", l'avance automatique en fin de segment ET le
// scrub/clic sur la timeline de séquence — un seul chemin de code pour tout ça.
function _basketGoto(idx, withinOffset, autoplay) {
    const r = _basketLastResolved[idx];
    if(!r) return;
    _ensureBasketVidHandlers();
    _basketPlayIdx = idx;
    _basketCurrentItemRef = r.item;
    _highlightBasketPlaying();
    _updateBasketViewerInfo(r);
    const vid = document.getElementById('basketVid');
    if(!vid) return;

    const seekAndMaybePlay = () => {
        try { vid.currentTime = withinOffset; } catch(e) {}
        _basketPlaying = !!autoplay;
        _setBasketPlayBtnLabel();
        if(autoplay) vid.play().catch(() => {});
        else vid.pause();
        _basketUpdateSeqHead();
    };
    if(vid.dataset.clipId === r.clip.id) {
        seekAndMaybePlay();
    } else {
        vid.dataset.clipId = r.clip.id;
        vid.src = r.clip.proxy_url || '';
        // Cadre : même logique que le lecteur/multicam, pas de crop, juste les
        // insets pour que le cadre choisi (setAspectFrame) se pose correctement.
        if(typeof _applyLetterbox === 'function') _applyLetterbox(vid, r.clip.id, false);
        // Audio FS5 : L=LTC (le "son de TC"/BZZZZ signalé), R=micro. Même routage
        // WebAudio mono-R que le lecteur principal/comparateur/multicam — sans ça
        // #basketVid joue le stéréo brut du proxy, donc le LTC en plus du micro.
        _attachBasketVidAudio();
        _setBasketMonoR(r.clip.ltc_tc_in_sec != null);
        vid.addEventListener('loadedmetadata', seekAndMaybePlay, {once: true});
    }
}

// Routage WebAudio dédié au lecteur du pré-montage — même schéma que
// _attachCmpSlotAudio/_setCmpMonoR (js/compare.js) mais pour un seul élément
// vidéo (pas de slots). ctx/gains créés une fois, réutilisés pour tous les
// clips chargés successivement dans #basketVid.
let _basketAudioCtx = null, _basketGainStereo = null, _basketGainMonoR = null;

function _attachBasketVidAudio() {
    const vid = document.getElementById('basketVid');
    if(!vid || vid._audioAttached) return;
    try {
        if(!_basketAudioCtx) {
            _basketAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if(typeof _pinStereoDestination === 'function') _pinStereoDestination(_basketAudioCtx);
        }
        if(_basketAudioCtx.state === 'suspended') _basketAudioCtx.resume().catch(() => {});
        const src = _basketAudioCtx.createMediaElementSource(vid);
        const splitter = _basketAudioCtx.createChannelSplitter(2);
        src.connect(splitter);
        // Route A : stéréo native
        const mergerS = _basketAudioCtx.createChannelMerger(2);
        splitter.connect(mergerS, 0, 0);
        splitter.connect(mergerS, 1, 1);
        _basketGainStereo = _basketAudioCtx.createGain();
        _basketGainStereo.gain.value = 1;
        mergerS.connect(_basketGainStereo);
        _basketGainStereo.connect(_basketAudioCtx.destination);
        // Route B : mono canal droit dupliqué (supprime le LTC du canal gauche)
        const mergerM = _basketAudioCtx.createChannelMerger(2);
        splitter.connect(mergerM, 1, 0);
        splitter.connect(mergerM, 1, 1);
        _basketGainMonoR = _basketAudioCtx.createGain();
        _basketGainMonoR.gain.value = 0;
        mergerM.connect(_basketGainMonoR);
        _basketGainMonoR.connect(_basketAudioCtx.destination);
        vid._audioAttached = true;
    } catch(e) { console.warn('Basket viewer audio routing fail:', e); }
}

function _setBasketMonoR(on) {
    if(!_basketAudioCtx) return;
    if(_basketAudioCtx.state === 'suspended') _basketAudioCtx.resume().catch(() => {});
    if(_basketGainStereo) _basketGainStereo.gain.value = on ? 0 : 1;
    if(_basketGainMonoR) _basketGainMonoR.gain.value = on ? 1 : 0;
}

function _basketPlayFrom(idx) {
    if(!_basketLastResolved[idx]) return;
    _basketGoto(idx, _basketLastResolved[idx].sel.in, true);
}

function _basketAdvance() {
    if(_basketPlayIdx + 1 < _basketLastResolved.length) {
        const next = _basketPlayIdx + 1;
        _basketGoto(next, _basketLastResolved[next].sel.in, true);
    } else {
        const vid = document.getElementById('basketVid');
        if(vid) vid.pause();
        _basketPlaying = false;
        _setBasketPlayBtnLabel();
    }
}

function _highlightBasketPlaying() {
    document.querySelectorAll('.basket-item').forEach((el, i) => el.classList.toggle('playing', i === _basketPlayIdx));
}

function _basketStop() {
    const vid = document.getElementById('basketVid');
    if(vid) vid.pause();
    _basketPlaying = false;
    _setBasketPlayBtnLabel();
    document.querySelectorAll('.basket-item.playing').forEach(el => el.classList.remove('playing'));
}

// Libère le décodeur vidéo + réinitialise la timeline — appelé à la fermeture de
// l'overlay (même raison que closeMcViewer/closeCompare : sans ça, l'élément
// <video> garde une référence au buffer décodé même invisible).
function _basketReleaseViewer() {
    const vid = document.getElementById('basketVid');
    if(vid) {
        vid.pause();
        vid.removeAttribute('src');
        vid.load();
        delete vid.dataset.clipId;
    }
    const ph = document.getElementById('basketViewerPlaceholder');
    if(ph) ph.style.display = '';
    const nameEl = document.getElementById('basketViewerName');
    if(nameEl) nameEl.textContent = '—';
    const metaEl = document.getElementById('basketViewerMeta');
    if(metaEl) metaEl.textContent = '--:--:--:-- → --:--:--:--';
}

// ─── Timeline de séquence : les sélections "collées" bout à bout ───────────
// Représente TOUTE la bobine assemblée (pas un seul segment) sur une seule
// piste, largeur de chaque segment proportionnelle à sa durée retenue. Cliquer
// ou glisser n'importe où navigue dans la séquence complète, en continu.

function _basketSeqSegments() {
    let acc = 0;
    return _basketLastResolved.map((r, idx) => {
        const dur = Math.max(0.01, r.sel.out - r.sel.in);
        const seg = {start: acc, dur, r, idx};
        acc += dur;
        return seg;
    });
}

function _basketSeqTotalDuration() {
    return _basketLastResolved.reduce((sum, r) => sum + Math.max(0.01, r.sel.out - r.sel.in), 0);
}

function _basketRenderSeqTimeline() {
    const track = document.getElementById('basketSeqTimeline');
    if(!track) return;
    track.querySelectorAll('.basket-seq-seg').forEach(el => el.remove());
    const head = document.getElementById('basketSeqHead');
    const segs = _basketSeqSegments();
    const total = _basketSeqTotalDuration();
    segs.forEach(seg => {
        const el = document.createElement('div');
        el.className = 'basket-seq-seg' + (seg.idx === _basketPlayIdx ? ' active' : '');
        el.style.width = (total > 0 ? seg.dur / total * 100 : 0) + '%';
        el.style.backgroundImage = `url('/api/project/${currentProjectId}/thumbnail/${seg.r.clip.id}?t=${Math.floor(seg.r.sel.in)}')`;
        el.title = seg.r.sel.name || 'Sélection';
        const label = document.createElement('span');
        label.className = 'basket-seq-seg-label';
        label.textContent = seg.r.sel.name || 'Sélection';
        el.appendChild(label);
        track.insertBefore(el, head);
    });
    _basketUpdateSeqHead();
}

function _basketUpdateSeqHead() {
    const head = document.getElementById('basketSeqHead');
    const tcEl = document.getElementById('basketSeqTc');
    const total = _basketSeqTotalDuration();
    const segs = _basketSeqSegments();
    const cur = segs[_basketPlayIdx];
    const vid = document.getElementById('basketVid');
    let posInSeq = 0;
    if(cur && vid) {
        const withinSel = Math.max(0, (vid.currentTime || 0) - cur.r.sel.in);
        posInSeq = cur.start + Math.min(withinSel, cur.dur);
    }
    if(head) head.style.left = (total > 0 ? posInSeq / total * 100 : 0) + '%';
    if(tcEl) tcEl.textContent = _fmtDurShort(posInSeq) + ' / ' + _fmtDurShort(total);
    document.querySelectorAll('.basket-seq-seg').forEach((el, i) => el.classList.toggle('active', i === _basketPlayIdx));
}

function _basketSeekSeqRatio(ratio) {
    const total = _basketSeqTotalDuration();
    if(total <= 0) return;
    const t = Math.max(0, Math.min(total - 0.01, ratio * total));
    const segs = _basketSeqSegments();
    let seg = segs.find(s => t >= s.start && t < s.start + s.dur);
    if(!seg) seg = segs[segs.length - 1];
    if(!seg) return;
    const withinOffset = seg.r.sel.in + (t - seg.start);
    _basketGoto(seg.idx, withinOffset, _basketPlaying);
}

function _basketSeqMouseDown(e) {
    const track = document.getElementById('basketSeqTimeline');
    if(!track || !_basketLastResolved.length) return;
    const doSeek = (ev) => {
        const rect = track.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        _basketSeekSeqRatio(ratio);
    };
    doSeek(e);
    const onMove = (ev) => doSeek(ev);
    const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

// ─── Export ─────────────────────────────────────────────────────────────────

function _basketToggleExportMenu(e) {
    if(e) e.stopPropagation();
    const menu = document.getElementById('basketExportMenu');
    if(!menu) return;
    const willOpen = menu.style.display !== 'block';
    menu.style.display = willOpen ? 'block' : 'none';
    if(willOpen) {
        document.addEventListener('click', _basketExportMenuOutsideClick, {capture: true, once: true});
    }
}

function _basketExportMenuOutsideClick() {
    const menu = document.getElementById('basketExportMenu');
    if(menu) menu.style.display = 'none';
}

function _basketExport(fmt) {
    const menu = document.getElementById('basketExportMenu');
    if(menu) menu.style.display = 'none';
    if(!currentProjectId || !_basketViewUser) return;
    const label = encodeURIComponent((currentProject && currentProject.name) || 'projet');
    const url = `/api/project/${currentProjectId}/export/basket_${fmt}?user=${encodeURIComponent(_basketViewUser)}&label=${label}`;
    window.open(url, '_blank');
}
