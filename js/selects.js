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
// Point de trim "armé" au clavier sur la timeline de séquence du pré-montage
// (façon DaVinci : clic sur une poignée sans glisser → ←/→ trimme frame par
// frame). Voir _basketArmTrimHandle/_basketNudgeArmedTrim/_basketCommitArmedTrim
// juste avant _wireBasketSeqHandle.
let _basketArmedTrim = null;

// Sélection multiple d'items du pré-montage pour un export PARTIEL (retour
// terrain : « pouvoir sélectionner plusieurs clips au sein du prémontage et
// n'exporter qu'une timeline de cette sélection »). Set d'`item.id` (id propre
// à la ligne du panier, cf. push dans allBaskets[uid] — distinct du select_id
// qui identifie la sélection in/out sur le clip). Volontairement non persisté
// (état d'édition transitoire, pas une donnée de projet) et réinitialisé au
// changement d'utilisateur affiché (_basketSwitchUser) puisque les ids ne
// concernent que le panier actuellement visible.
let _basketExportSelIds = new Set();
// Ancre pour la sélection par plage au Shift+clic (façon Explorateur Windows/Gmail) :
// `item.id` (id STABLE, PAS un index) de la dernière case cochée par un clic
// SIMPLE. Un Shift+clic coche toute la plage entre cette ancre et l'item
// cliqué, sans changer l'ancre elle-même (permet d'étendre/rétrécir la plage
// en Shift+cliquant plusieurs fois de suite). Réinitialisée en même temps que
// _basketExportSelIds.
//
// ⚠️ Piège corrigé (retour terrain : « des plans qui ne sont même pas dans le
// prémontage sont intégrés dans la sélection ») : stocker un INDEX positionnel
// (`_basketExportAnchorIdx`, version précédente) devient invalide dès qu'un
// glisser-déposer réordonne le panier ENTRE le clic d'ancrage et le Maj+clic
// suivant — l'index pointe alors sur un item totalement différent, et la plage
// calculée entre les deux mauvaises positions embarque des plans sans rapport
// avec l'intention de l'utilisateur. Stocker l'id (stable, indépendant de
// l'ordre) et retrouver sa position COURANTE à chaque usage via
// _basketAnchorCurrentIdx() rend la plage immune à tout réordonnancement
// survenu entre les deux clics.
let _basketExportAnchorItemId = null;

// Position actuelle de l'ancre dans le rendu courant, ou -1 si pas d'ancre /
// ancre pointant sur un item qui n'est plus dans le panier (retiré depuis).
function _basketAnchorCurrentIdx() {
    if(_basketExportAnchorItemId === null) return -1;
    return _basketLastResolved.findIndex(r => r.item.id === _basketExportAnchorItemId);
}

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

// Autocomplete filtré par sous-séquence pendant la frappe — même comportement
// que le champ tag du panneau de notes (updateTagAutocomplete/_tagSubsequenceScore
// dans derush_app.html, réutilisé tel quel) : les lettres tapées doivent
// apparaître dans le tag existant dans le même ordre, pas forcément contiguës.
// Champ vide → liste complète (parcours libre, comportement d'avant conservé).
let _spTagAcMatches = [];
let _spTagAcIndex = -1;

function _spCurrentMatches(val) {
    const already = new Set(_selectPopupTags);
    const all = _allProjectTagsForSuggest().filter(t => !already.has(t));
    if(!val) return all;
    return all
        .map(t => ({ t, score: _tagSubsequenceScore(val, t.toLowerCase()) }))
        .filter(x => x.score >= 0)
        .sort((a, b) => a.score - b.score || a.t.localeCompare(b.t))
        .map(x => x.t)
        .slice(0, 8);
}

function _spRenderTagSuggestions() {
    const box = document.getElementById('selectPopupTagSuggest');
    if(!box) return;
    const input = document.getElementById('selectPopupTagInput');
    const val = (input ? input.value : '').trim().toLowerCase();
    const matches = _spCurrentMatches(val);
    _spTagAcMatches = matches;
    if(_spTagAcIndex >= matches.length) _spTagAcIndex = -1;
    if(!matches.length) { box.innerHTML = ''; return; }
    box.innerHTML = matches.map((t, i) =>
        `<button type="button" class="sp-tag-pill${i === _spTagAcIndex ? ' active' : ''}" onclick="_spAddTag('${t.replace(/'/g, "\\'")}')">+ ${_escHtml(t)}</button>`
    ).join('');
}

function _spOnTagInput() {
    _spTagAcIndex = -1;
    _spRenderTagSuggestions();
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
    if(e.key === 'ArrowDown') {
        if(!_spTagAcMatches.length) return;
        e.preventDefault();
        _spTagAcIndex = (_spTagAcIndex + 1) % _spTagAcMatches.length;
        _spRenderTagSuggestions();
        return;
    }
    if(e.key === 'ArrowUp') {
        if(!_spTagAcMatches.length) return;
        e.preventDefault();
        _spTagAcIndex = (_spTagAcIndex - 1 + _spTagAcMatches.length) % _spTagAcMatches.length;
        _spRenderTagSuggestions();
        return;
    }
    if(e.key === 'Escape') {
        if(_spTagAcIndex < 0) return;
        e.preventDefault();
        _spTagAcIndex = -1;
        _spRenderTagSuggestions();
        return;
    }
    if(e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const tag = (_spTagAcIndex >= 0 && _spTagAcMatches[_spTagAcIndex])
        ? _spTagAcMatches[_spTagAcIndex]
        : e.target.value;
    _spAddTag(tag);
    e.target.value = '';
    _spTagAcIndex = -1;
}

function openSelectPopup(inSec, outSec) {
    _selectPopupIn = inSec;
    _selectPopupOut = outSec;
    _selectPopupEditId = null;
    _selectPopupTags = [];
    _spTagAcIndex = -1;
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
    _spTagAcIndex = -1;
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
    _pushBasketUndo();
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
    _loadBasketSeqMarkers(currentProjectId);
    renderBasketOverlay();
    document.getElementById('basketOverlay').classList.add('active');
    document.addEventListener('keydown', _basketKeydown, true);
    // Rappelée ici APRÈS l'ajout de .active : le chargement du 1er item par
    // renderBasketOverlay() (via _basketGoto) a pu déclencher un premier appel
    // pendant que l'overlay n'était pas encore marqué actif — sa garde interne
    // l'aurait alors annulé (cf. _basketLutRefresh).
    _basketLutRefresh();
}

function closeBasket() {
    _basketCommitArmedTrim();  // valide un trim clavier resté en attente plutôt que de le perdre silencieusement
    _basketCancelRename();
    _basketStop();
    _basketReleaseViewer();
    _basketCurrentItemRef = null;
    document.removeEventListener('keydown', _basketKeydown, true);
    const ov = document.getElementById('basketOverlay');
    if(ov) ov.classList.remove('active');
    const menu = document.getElementById('basketExportMenu');
    if(menu) menu.style.display = 'none';
    // Retour terrain : « il y a des clips que je n'ai pas sélectionnés dans
    // l'export » — la case à cocher de l'export partiel n'était réinitialisée
    // qu'au changement d'utilisateur consulté, jamais à la fermeture du panier.
    // De vieilles coches oubliées d'une session précédente survivaient donc
    // silencieusement (visibles si on scrolle, mais facile à manquer) et
    // pouvaient se retrouver incluses dans un export "sélection cochée" bien
    // plus tard, sans rapport avec la tâche en cours. Chaque ouverture du
    // pré-montage repart maintenant d'une ardoise vierge.
    _basketExportSelIds.clear();
    _basketExportAnchorItemId = null;
}

// Capture phase, comme _cmpKeydown (js/compare.js) : intercepte avant le handler
// clavier global (qui se met de côté dès que #basketOverlay est actif, cf.
// derush_app.html). Espace pilote #basketVid, pas le lecteur principal caché.
// ←/→ ont un double rôle façon DaVinci : trim frame-exact d'un point de montage
// ARMÉ (_basketArmedTrim, cf. _wireBasketSeqHandle) s'il y en a un, sinon
// nudge classique de la tête de lecture (même convention Maj = pas plus large
// que le lecteur principal, cf. derush_app.html).
function _basketKeydown(e) {
    if(!document.getElementById('basketOverlay').classList.contains('active')) return;
    const tag = e.target.tagName;
    if(tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    switch(e.key) {
        case ' ':
            e.preventDefault(); e.stopPropagation();
            _basketTogglePlay();
            return;
        case 'Enter':
            if(_basketArmedTrim) {
                e.preventDefault(); e.stopPropagation();
                _basketCommitArmedTrim();
            }
            return;
        case 'Escape':
            e.preventDefault(); e.stopPropagation();
            if(_basketArmedTrim) _basketCancelArmedTrim();
            else if(!_basketDeselectSeqMarker()) closeBasket();
            return;
        case 'Delete':
        case 'Backspace':
            if(_basketSelectedSeqMarker !== null) {
                e.preventDefault(); e.stopPropagation();
                _basketDeleteSelectedSeqMarker();
            }
            return;
        case 'ArrowLeft':
        case 'ArrowRight': {
            e.preventDefault(); e.stopPropagation();
            const dir = e.key === 'ArrowLeft' ? -1 : 1;
            if(_basketArmedTrim) {
                const step = (e.shiftKey ? 1 : 1 / _basketArmedTrim.fps) * dir;
                _basketNudgeArmedTrim(step);
                return;
            }
            const vid = _basketActiveVid();
            if(!vid) return;
            if(_basketPlaying) _basketTogglePlay();
            const cur = _basketLastResolved[_basketPlayIdx];
            const fps = (cur && cur.clip.fps) || 25;
            vid.currentTime = Math.max(0, vid.currentTime + (e.shiftKey ? 1 : 1 / fps) * dir);
            _basketUpdateSeqHead();
            return;
        }
        case 'm': case 'M':
            e.preventDefault(); e.stopPropagation();
            _basketAddSeqMarkerAtPlayhead();
            return;
        case 'c': case 'C':
            e.preventDefault(); e.stopPropagation();
            _basketCutAtPlayhead();
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
    _basketExportSelIds.clear();
    _basketExportAnchorItemId = null;
    renderBasketOverlay();
}

function _fmtDurShort(sec) {
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return m > 0 ? `${m}min ${s}s` : `${s}s`;
}

function renderBasketOverlay() {
    // N'importe quel autre re-rendu (ajout, retrait, réordonnancement, switch
    // d'utilisateur…) pendant qu'un point de trim est armé au clavier doit
    // d'abord valider ce trim en attente — sinon la référence DOM `handleEl`
    // gardée dans _basketArmedTrim deviendrait obsolète (la timeline de séquence
    // recrée tous ses éléments à chaque rendu). _basketCommitArmedTrim() vide
    // _basketArmedTrim AVANT de rappeler renderBasketOverlay() lui-même, donc
    // pas de récursion infinie ici.
    if(_basketArmedTrim) { _basketCommitArmedTrim(); return; }
    const body = document.getElementById('basketBody');
    if(!body || !currentSession) return;
    const isMine = _basketViewUser === currentSession.user_id;
    const clearBtn = document.getElementById('basketClearBtn');
    if(clearBtn) clearBtn.style.display = isMine ? '' : 'none';
    const cutBtn = document.getElementById('basketCutBtn');
    if(cutBtn) cutBtn.style.display = isMine ? '' : 'none';

    const items = allBaskets[_basketViewUser] || [];
    const resolved = items.map(it => {
        const clip = clips.find(c => c.id === it.clip_id);
        const uNotes = (allNotes[_basketViewUser] || {})[it.clip_id] || {};
        const sel = (uNotes.selects || []).find(s => s.id === it.select_id);
        return {item: it, clip, sel};
    }).filter(r => r.clip && r.sel);
    _basketLastResolved = resolved;

    // Purge les ids d'une éventuelle sélection d'export dont l'item a disparu
    // depuis (retrait, ou re-render sur un panier différent) — sans ça un id
    // fantôme resterait compté dans le badge du bouton Exporter la sélection.
    const _liveItemIds = new Set(resolved.map(r => r.item.id));
    for(const id of [..._basketExportSelIds]) if(!_liveItemIds.has(id)) _basketExportSelIds.delete(id);
    if(_basketExportAnchorItemId !== null && !_liveItemIds.has(_basketExportAnchorItemId)) _basketExportAnchorItemId = null;
    _basketUpdateExportSelUI();

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
        row.dataset.itemId = r.item.id;
        const dur = Math.max(0, r.sel.out - r.sel.in);
        const fps = r.clip.fps || 25;
        const thumbUrl = `/api/project/${currentProjectId}/thumbnail/${r.clip.id}?t=${Math.floor(r.sel.in)}`;
        row.classList.toggle('export-checked', _basketExportSelIds.has(r.item.id));
        row.innerHTML = `<label class="basket-item-check" draggable="false" title="Cocher pour un export partiel (seulement les éléments cochés) — Maj+clic pour cocher toute une plage d'un coup" onclick="event.stopPropagation();" onmousedown="event.stopPropagation();">
                <input type="checkbox" ${_basketExportSelIds.has(r.item.id) ? 'checked' : ''} onclick="_basketCheckboxClick(event, '${r.item.id}', ${idx})">
            </label>
            <div class="basket-item-thumb-wrap" style="background-image:url('${thumbUrl}');">
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
                ${isMine ? `<button title="Dupliquer cette sélection (répéter le plan dans le pré-montage)" onclick="_basketDuplicateItem(${idx})">⧉</button>` : ''}
                ${isMine ? `<button title="Renommer cette sélection" onclick="_basketRenameItem(${idx})">✏️</button>` : ''}
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
        if(e.target.closest('.basket-item-check')) return;  // déjà géré par _basketCheckboxClick sur la case elle-même
        // Maj+clic n'IMPORTE OÙ sur la ligne (pas seulement sur la petite case) déclenche
        // la sélection par plage — retour terrain : le geste naturel est de Maj+cliquer la
        // ligne/vignette, pas de viser précisément la case à cocher.
        if(e.shiftKey) { _basketRowShiftClick(idx); return; }
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
        _pushBasketUndo();
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
    _pushBasketUndo();
    arr.splice(realIdx, 1);
    renderBasketOverlay();
    _updateBasketBadge();
    if(activeClip) renderSelects();  // rafraîchit le badge 📽️✓/+ si le clip actif est concerné
    saveBasket();
}

// Suffixe numéroté ("copie 2", "cut 3"…) plutôt qu'un suffixe fixe identique à
// chaque nouvelle occurrence — retour terrain : « tu peux la nommer avec le
// suffixe cut et un numéro [...] quand je copie un même clip tu peux la
// nommer avec le suffixe copie et un numéro ». Repart toujours du nom de BASE
// (sans suffixe) pour numéroter à plat : dupliquer une copie, ou couper un
// segment déjà issu d'une coupe, ne doit pas empiler les suffixes
// (" (copie 1) (copie 1)") — juste avancer au prochain numéro libre parmi
// TOUTES les sélections du même clip déjà nommées "<base> (<suffix> N)".
function _basketBaseSelectName(name) {
    const m = /^(.*) \((?:copie|cut) \d+\)$/.exec(name || '');
    return (m ? m[1] : (name || 'Sélection')).trim() || 'Sélection';
}

function _basketNextSuffixedName(selects, name, suffix) {
    const base = _basketBaseSelectName(name);
    const re = new RegExp('^' + base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' \\(' + suffix + ' (\\d+)\\)$');
    let max = 0;
    (selects || []).forEach(s => {
        const m = re.exec(s.name || '');
        if(m) max = Math.max(max, parseInt(m[1], 10));
    });
    return base + ' (' + suffix + ' ' + (max + 1) + ')';
}

// Duplique une sélection du pré-montage — retour terrain : « j'aimerais qu'on
// puisse copier coller une sélection plusieurs fois dans le prémontage »,
// pour répéter un plan (ex. un plan de coupe, une réaction) à plusieurs
// endroits d'un montage sans en changer les bornes à chaque fois. Implémenté
// en un clic plutôt qu'un vrai copier/coller avec presse-papier : cliquer
// à nouveau (sur l'original ou une copie) crée une copie de plus — "coller
// plusieurs fois" sans avoir besoin de gérer un état de sélection/presse-
// papier séparé. Combiné au glisser-déposer déjà existant, une copie peut
// ensuite être déplacée n'importe où dans la bobine.
//
// Crée une SÉLECTION INDÉPENDANTE (nouvel id, mêmes in/out/tags/desc au
// départ) plutôt que de réutiliser select_id — sinon retrimmer une copie
// depuis la timeline de séquence (_wireBasketSeqHandle mute sel.in/out en
// place) changerait aussi silencieusement toutes les autres occurrences de
// la même sélection dans le pré-montage. Chaque copie doit pouvoir être
// ajustée indépendamment, comme dupliquer un clip sur une timeline DaVinci.
function _basketDuplicateItem(idx) {
    const r = _basketLastResolved[idx];
    if(!r || !currentSession) return;
    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[r.clip.id];
    const arr = allBaskets[uid];
    if(!n || !n.selects || !arr) return;
    const realIdx = arr.indexOf(r.item);
    if(realIdx < 0) return;

    pushUndo(r.clip.id);
    const newSel = {
        id: Math.random().toString(36).slice(2, 10),
        in: r.sel.in, out: r.sel.out,
        name: _basketNextSuffixedName(n.selects, r.sel.name, 'copie'),
        tags: (r.sel.tags || []).slice(),
        desc: r.sel.desc || '',
    };
    n.selects.push(newSel);
    n.selects.sort((a, b) => a.in - b.in);

    _pushBasketUndo();
    const newItem = {id: Math.random().toString(36).slice(2, 10), clip_id: r.clip.id, select_id: newSel.id};
    arr.splice(realIdx + 1, 0, newItem);  // juste après l'original — facile à repérer, à glisser ensuite si besoin

    if(activeClip && activeClip.id === r.clip.id) renderMarkers();  // resync le panneau ✂️ Sélections si affiché
    renderBasketOverlay();
    _updateBasketBadge();
    saveNotes(true);  // persiste newSel dans allNotes
    saveBasket();      // persiste newItem dans allBaskets
    showToast('⧉ Sélection dupliquée', 'ok');
}

// ─── Renommer une sélection du pré-montage ──────────────────────────────────
// Petite modale dédiée (`#basketRenameOverlay`) plutôt qu'un `prompt()` natif
// (piège CLAUDE.md #1 : prompt() casse le focus state sous Electron) ou une
// édition inline dans `.basket-item-name` (le `innerHTML` du body entier est
// reconstruit à chaque `renderBasketOverlay()` — un poll/WS `basket_updated`
// pendant la frappe détruirait le champ en cours d'édition, cf. piège #32
// sur les références DOM qui survivent à un re-rendu).
// Référence par IDENTITÉ d'item (`_basketRenameItemRef`), pas par index — même
// raison que `_basketCurrentItemRef` : l'index dans `_basketLastResolved` peut
// se périmer si un re-rendu survient pendant que la modale est ouverte
// (réorganisation, suppression depuis un autre appareil).
let _basketRenameItemRef = null;

function _basketRenameItem(idx) {
    const r = _basketLastResolved[idx];
    if(!r || !currentSession || _basketViewUser !== currentSession.user_id) return;
    _basketRenameItemRef = r.item;
    const input = document.getElementById('basketRenameInput');
    if(input) input.value = r.sel.name || '';
    const ov = document.getElementById('basketRenameOverlay');
    if(ov) ov.style.display = 'flex';
    requestAnimationFrame(() => requestAnimationFrame(() => {
        if(input) { input.focus(); input.select(); }
    }));
}

function _basketCancelRename() {
    _basketRenameItemRef = null;
    const ov = document.getElementById('basketRenameOverlay');
    if(ov) ov.style.display = 'none';
}

function _basketConfirmRename() {
    if(!_basketRenameItemRef) { _basketCancelRename(); return; }
    const r = _basketLastResolved.find(x => x.item === _basketRenameItemRef);
    const input = document.getElementById('basketRenameInput');
    if(!r || !input) { _basketCancelRename(); return; }
    const name = (input.value || '').trim();
    if(!name) { showToast('Le nom ne peut pas être vide', 'warn'); return; }

    if(name !== r.sel.name) {
        pushUndo(r.clip.id);
        r.sel.name = name;
        if(activeClip && activeClip.id === r.clip.id) renderMarkers();  // resync le panneau ✂️ Sélections si affiché
        saveNotes(true);
        showToast('✏️ Sélection renommée', 'ok');
    }
    _basketCancelRename();
    renderBasketOverlay();
}

function _basketRenameKeydown(e) {
    if(e.key === 'Enter') { e.preventDefault(); _basketConfirmRename(); }
    else if(e.key === 'Escape') { e.preventDefault(); _basketCancelRename(); }
}

let _basketClearConfirmUntil = 0;

function _basketClear() {
    if(!currentSession || _basketViewUser !== currentSession.user_id) return;
    const now = Date.now();
    if(now < _basketClearConfirmUntil) {
        _basketStop();
        _pushBasketUndo();
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
let _basketCurrentItemRef = null;  // identité de l'item chargé dans le lecteur actif (joue ou pas)
let _basketVidHandlersAttached = false;

// ─── Double lecteur (crossfade, pas de flash noir entre deux plans) ────────
// #basketVid / #basketVidB : un seul est "actif" (visible + audio routé) à la
// fois. Pendant qu'un segment joue, le SUIVANT est préchargé + pré-seeké dans
// l'élément inactif (_basketPreloadNextSegment) ; à l'avance automatique de
// segment (_basketAdvance → _basketGoto), si ce préchargement est prêt, on
// bascule juste laquelle des deux vidéos est visible (_basketSwapActiveVideo)
// au lieu de réassigner .src sur un seul élément — c'est CE rechargement qui
// causait le flash noir (retour terrain 31/07/2026), inhérent à tout swap de
// source sur un unique <video>, même avec le fichier déjà en cache réseau.
let _basketVidActiveId = 'basketVid';

function _basketActiveVid() { return document.getElementById(_basketVidActiveId); }
function _basketInactiveVid() { return document.getElementById(_basketVidActiveId === 'basketVid' ? 'basketVidB' : 'basketVid'); }

function _basketSwapActiveVideo() {
    const oldActive = _basketActiveVid();
    _basketVidActiveId = _basketVidActiveId === 'basketVid' ? 'basketVidB' : 'basketVid';
    const newActive = _basketActiveVid();
    newActive.classList.add('bv-active');
    if(oldActive) { oldActive.classList.remove('bv-active'); oldActive.pause(); }
    if(typeof refreshAllAspectOverlays === 'function') refreshAllAspectOverlays();
    _basketLutRefresh();
}

// ─── LUT dans le pré-montage ─────────────────────────────────────────────────
// Retour terrain : « quand j'applique une LUT sur un clip, ça affecte aussi les
// sélections de ce clip dans le pré-montage ». Pipeline WebGL indépendant de
// celui du lecteur principal (js/lut.js, _lutGL/#lutCanvas) mais réutilisant
// ses briques génériques (_lutInitGL/_lutUploadLUT/_lutApplySettings acceptent
// un contexte GL en paramètre depuis leur refactor pour ce besoin, _lutResolveFor/
// _lutEnsureLoaded sont déjà génériques). Un seul canvas (#basketLutCanvas)
// pour les DEUX lecteurs du crossfade : la boucle de rendu relit _basketActiveVid()
// à chaque frame plutôt que d'avoir sa propre notion de "lequel regarder" — le
// swap crossfade est donc suivi automatiquement, sans synchronisation dédiée.
let _basketLutGL = null;
let _basketLutRaf = null;
let _basketLutCurrentLutName = null;

// Résout la LUT du clip COURANT du pré-montage (celui de l'item actif,
// _basketPlayIdx) et (re)démarre/arrête le rendu en conséquence. À appeler à
// chaque fois que le clip affiché change (swap, goto) — pas besoin de le
// rappeler à chaque frame, la boucle de rendu suit déjà _basketActiveVid()
// toute seule pour le crossfade.
//
// Deux chemins de résolution — retour terrain : « voir le prémontage d'un
// autre utilisateur avec les LUTs et réglages qu'elle a faits [...] en dehors
// de l'outil prémontage et du prémontage d'un autre utilisateur, je veux que
// ce soit mes réglages qui soient pris en compte ». Donc UNIQUEMENT quand on
// regarde le panier d'un AUTRE user (`_basketViewUser`) : résolution via
// `_lutResolveForRemote`/`_lutEnsureLoadedByHash` sur SON assignation publiée
// (`allLutAssign`, js/lut.js). Sur son propre panier (le cas courant), chemin
// strictement inchangé : `_lutResolveFor`/`_lutEnsureLoaded` sur `_lutAssign`
// local — jamais influencé par ce qu'un collaborateur a publié.
async function _basketLutRefresh() {
    const c = document.getElementById('basketLutCanvas');
    const overlay = document.getElementById('basketOverlay');
    // Se ré-appelle elle-même sans condition depuis divers points (goto, swap,
    // et — via js/lut.js — toute modification de LUT pendant que le pré-montage
    // est ouvert) : cette garde évite qu'une boucle requestAnimationFrame ne
    // continue de tourner indéfiniment (coût CPU pour rien) une fois l'overlay
    // refermé, plutôt que de demander à chaque appelant de vérifier lui-même.
    if(!c || !overlay || !overlay.classList.contains('active')) {
        if(_basketLutRaf) { cancelAnimationFrame(_basketLutRaf); _basketLutRaf = null; }
        if(c) c.style.display = 'none';
        return;
    }
    const cur = _basketLastResolved[_basketPlayIdx];
    if(!cur || typeof _lutEnabled === 'undefined' || !_lutEnabled) {
        c.style.display = 'none';
        if(_basketLutRaf) { cancelAnimationFrame(_basketLutRaf); _basketLutRaf = null; }
        return;
    }
    const viewingOther = currentSession && _basketViewUser !== currentSession.user_id;
    const resolved = viewingOther
        ? (typeof _lutResolveForRemote === 'function' ? _lutResolveForRemote(_basketViewUser, cur.clip) : null)
        : _lutResolveFor(cur.clip);
    if(!resolved) {
        c.style.display = 'none';
        c.title = '';
        if(_basketLutRaf) { cancelAnimationFrame(_basketLutRaf); _basketLutRaf = null; }
        return;
    }
    const parsed = viewingOther
        ? await _lutEnsureLoadedByHash(resolved.hash)
        : await _lutEnsureLoaded(resolved.lutName);
    // Le clip affiché (ou l'utilisateur consulté) a pu changer pendant l'attente
    // réseau/IndexedDB (même précaution que _lutRefreshForActiveClip côté lecteur
    // principal).
    if(_basketLastResolved[_basketPlayIdx] !== cur) return;
    if(!parsed) { c.style.display = 'none'; c.title = ''; return; }
    if(!_basketLutGL) _basketLutGL = _lutInitGL(c);
    if(!_basketLutGL) return;
    // Clé de cache distincte en mode "remote" (indexée par hash, pas par nom —
    // deux users peuvent avoir chacun une LUT différente sous le même nom de
    // fichier) pour ne jamais réutiliser à tort la texture GL d'une LUT locale.
    const lutKey = viewingOther ? ('hash:' + resolved.hash) : resolved.lutName;
    if(_basketLutCurrentLutName !== lutKey) {
        _lutUploadLUT(_basketLutGL, parsed);
        _basketLutCurrentLutName = lutKey;
    }
    _lutApplySettings(_basketLutGL, resolved.settings);
    c.style.display = 'block';
    c.title = viewingOther ? `LUT de ${_basketViewUser} — ${resolved.lutName}` : '';
    if(!_basketLutRaf) _basketRenderLUT();
}

function _basketRenderLUT() {
    _basketLutRaf = null;
    if(!_lutEnabled || !_basketLutGL || !_basketLastResolved[_basketPlayIdx]) return;
    _basketLutRaf = requestAnimationFrame(_basketRenderLUT);
    const v = _basketActiveVid();
    if(!v || v.readyState < 2 || !v.videoWidth) return;
    const c = document.getElementById('basketLutCanvas');
    const w = v.videoWidth, h = v.videoHeight;
    if(c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const {gl, videoTex, u_time} = _basketLutGL;
    gl.viewport(0, 0, w, h);
    gl.uniform1f(u_time, (performance.now() * 0.001) % 1000.0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    try {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, v);
    } catch(e) {
        return;  // frame pas prête — retentera au prochain RAF
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
}

// Précharge le segment SUIVANT dans la vidéo actuellement inactive, pré-seeké
// à son point d'entrée, prêt pour un swap instantané. Précharge désormais
// AUSSI quand le prochain segment est sur le MÊME clip que celui en cours de
// lecture (retour terrain sept. 2026 : « la transition entre deux sélections
// n'est pas fluide, ça freeze la vidéo qui vient »). L'ancienne hypothèse
// « même clip → un seek direct dans _basketGoto suffit, il est déjà
// instantané » était fausse : un seek sur un flux H.264/H.265 long-GOP EN
// COURS DE LECTURE doit retrouver la keyframe la plus proche et redécoder
// depuis là, ce qui peut geler l'image une fraction de seconde — exactement
// le symptôme remonté. Précharger systématiquement dans l'élément inactif
// (même fichier source ou non) permet de toujours basculer par swap
// d'élément (_basketSwapActiveVideo) plutôt que par seek à vif sur l'élément
// qui joue. Identité de préchargement suivie par clip ET par sélection
// (`dataset.selectId`, pas seulement `dataset.clipId`) : un même clip peut
// apparaître plusieurs fois dans le pré-montage avec des points in/out
// différents, il faut savoir EXACTEMENT quel segment est déjà pré-seeké.
function _basketPreloadNextSegment() {
    const next = _basketLastResolved[_basketPlayIdx + 1];
    const inactive = _basketInactiveVid();
    const active = _basketActiveVid();
    if(!next || !inactive || !active) return;
    // Le prochain segment est sur le MÊME clip que celui déjà en lecture dans
    // l'élément actif : NE PAS le re-précharger dans l'autre lecteur — ça
    // forcerait un rechargement complet (nouveau décodeur, network refetch)
    // d'un fichier déjà en train d'être décodé ailleurs, juste pour finalement
    // basculer dessus. Sur une série de sélections découpées dans le même
    // rush (le cas le plus courant du pré-montage), ce cycle de rechargements
    // répétés à chaque transition n'avait jamais le temps de finir → chemin
    // de repli déclenché à chaque fois → flash noir à CHAQUE transition —
    // puis, décodeurs vidéo ouverts/fermés en boucle sans jamais se stabiliser,
    // crash du renderer Electron après une ou deux lectures complètes (retour
    // terrain, sept. 2026). La transition reste fluide SANS ce préchargement
    // grâce au chemin de repli de _basketGoto (pause → seek → attend l'évènement
    // `seeked` → reprend, sur l'élément déjà chargé, sans rien recharger).
    if(next.clip.id === active.dataset.clipId) return;
    if(inactive.dataset.clipId === next.clip.id && inactive.dataset.selectId === next.sel.id) return;
    inactive.pause();
    inactive.dataset.clipId = next.clip.id;
    inactive.dataset.selectId = next.sel.id;
    inactive.src = next.clip.proxy_url || '';
    if(typeof _applyLetterbox === 'function') _applyLetterbox(inactive, next.clip.id, false);
    _attachBasketVidAudio(inactive);
    _setBasketMonoR(inactive, next.clip.ltc_tc_in_sec != null);
    inactive.addEventListener('loadedmetadata', () => {
        try { inactive.currentTime = next.sel.in; } catch(e) {}
    }, {once: true});
}

// `readyState>=2` (HAVE_CURRENT_DATA) garantit juste l'image du point de
// seek, pas de quoi continuer à jouer sans re-bufferiser aussitôt — un seuil
// trop permissif qui laissait passer des swaps vers un segment pas vraiment
// prêt, avec un gel juste après la bascule au lieu d'avant. Exige en plus une
// vraie marge tampon autour du point de reprise.
function _basketSegmentReady(video, atTime) {
    if(!video || video.readyState < 3) return false;  // HAVE_FUTURE_DATA minimum
    try {
        const buf = video.buffered;
        for(let i = 0; i < buf.length; i++) {
            if(atTime >= buf.start(i) - 0.1 && buf.end(i) - atTime >= 0.3) return true;
        }
    } catch(e) {}
    return video.readyState >= 4;  // HAVE_ENOUGH_DATA — repli si buffered() est capricieux
}

// Attache les listeners UNE SEULE FOIS PAR ÉLÉMENT (les deux <video> sont
// statiques dans le DOM, jamais recréées) : timeupdate pilote l'avancée
// automatique en fin de segment ET la tête de la timeline de séquence, mais
// seulement pour celle des deux vidéos qui est actuellement active/visible —
// l'autre peut être en train de précharger silencieusement en arrière-plan.
function _ensureBasketVidHandlers() {
    if(_basketVidHandlersAttached) return;
    ['basketVid', 'basketVidB'].forEach(id => {
        const vid = document.getElementById(id);
        if(!vid) return;
        vid.addEventListener('timeupdate', () => {
            if(vid !== _basketActiveVid()) return;
            const cur = _basketLastResolved[_basketPlayIdx];
            if(cur && _basketPlaying && vid.currentTime >= cur.sel.out) { _basketAdvance(); return; }
            _basketUpdateSeqHead();
        });
        vid.addEventListener('loadedmetadata', () => {
            if(vid === _basketActiveVid() && typeof refreshAllAspectOverlays === 'function') refreshAllAspectOverlays();
        });
    });
    _basketVidHandlersAttached = true;
}

function _basketTogglePlay() {
    if(_basketPlaying) {
        const vid = _basketActiveVid();
        if(vid) vid.pause();
        _basketPlaying = false;
        _setBasketPlayBtnLabel();
        return;
    }
    if(!_basketLastResolved.length) { showToast('Pré-montage vide', 'warn'); return; }
    if(_basketPlayIdx >= 0 && _basketLastResolved[_basketPlayIdx]) {
        const vid = _basketActiveVid();
        _basketPlaying = true;
        _setBasketPlayBtnLabel();
        if(vid) vid.play().catch(() => {});
        _basketPreloadNextSegment();
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
// `scrubbing` (utilisé par _basketSeekSeqRatio pendant un drag sur la timeline
// de séquence, potentiellement des dizaines d'appels/s) désactive le filet
// d'attente sur `seeked` du chemin de repli ci-dessous : pendant un scrub actif,
// la réactivité prime sur la fluidité — attendre `seeked`/le timeout à chaque
// mousemove rendrait le glisser visiblement saccadé/en retard.
function _basketGoto(idx, withinOffset, autoplay, scrubbing) {
    const r = _basketLastResolved[idx];
    if(!r) return;
    if(_basketArmedTrim) _basketCommitArmedTrim();  // navigation ailleurs = validation implicite du trim en attente
    _ensureBasketVidHandlers();
    _basketPlayIdx = idx;
    _basketCurrentItemRef = r.item;
    _highlightBasketPlaying();
    _updateBasketViewerInfo(r);
    _basketLutRefresh();

    const inactive = _basketInactiveVid();
    // Chemin rapide : le segment visé (clip ET sélection, pas juste le clip —
    // cf. _basketPreloadNextSegment) est déjà préchargé, pré-seeké ET
    // réellement jouable (_basketSegmentReady, pas juste « métadonnées
    // chargées ») dans la vidéo inactive → simple bascule d'affichage, aucune
    // source à recharger, aucun seek à vif sur l'élément en cours de lecture.
    if(inactive && inactive.dataset.clipId === r.clip.id && inactive.dataset.selectId === r.sel.id
        && _basketSegmentReady(inactive, withinOffset)) {
        _basketSwapActiveVideo();
        const now = _basketActiveVid();
        // Déjà pré-seeké à ~withinOffset pendant le préchargement — ne
        // resollicite le décodeur que si l'écart est réellement significatif.
        if(Math.abs(now.currentTime - withinOffset) > 0.05) {
            try { now.currentTime = withinOffset; } catch(e) {}
        }
        _basketPlaying = !!autoplay;
        _setBasketPlayBtnLabel();
        if(autoplay) now.play().catch(() => {});
        else now.pause();
        _basketUpdateSeqHead();
        _basketPreloadNextSegment();
        return;
    }

    // Chemin de repli : le prochain segment n'a pas eu le temps d'être
    // préchargé (segment précédent trop court, ou premier segment de la
    // séquence) — seek/charge directement sur l'élément actif. On attend
    // l'évènement `seeked` avant de relancer la lecture (plutôt que de la
    // laisser continuer pendant que le seek se résout en arrière-plan), pour
    // éviter un sursaut de frames pendant la recherche de keyframe.
    const vid = _basketActiveVid();
    if(!vid) return;
    const seekAndMaybePlay = () => {
        if(scrubbing) {
            // Scrub actif sur la timeline de séquence : seek instantané, pas
            // d'attente — la réactivité au geste prime, un léger décalage
            // pendant qu'on glisse est attendu/normal (comportement d'origine).
            try { vid.currentTime = withinOffset; } catch(e) {}
            _basketPlaying = !!autoplay;
            _setBasketPlayBtnLabel();
            if(autoplay) vid.play().catch(() => {});
            else vid.pause();
            _basketUpdateSeqHead();
            _basketPreloadNextSegment();  // fire-and-forget, ne bloque pas le scrub
            return;
        }
        let settled = false;
        const finish = () => {
            if(settled) return;
            settled = true;
            vid.removeEventListener('seeked', finish);
            clearTimeout(safetyTimer);
            _basketPlaying = !!autoplay;
            _setBasketPlayBtnLabel();
            if(autoplay) vid.play().catch(() => {});
            else vid.pause();
            _basketUpdateSeqHead();
            _basketPreloadNextSegment();
        };
        vid.pause();
        vid.addEventListener('seeked', finish);
        // Filet de sécurité : si `currentTime` vaut déjà ~withinOffset, certains
        // navigateurs ne déclenchent jamais `seeked` (seek no-op) — sans ce
        // timeout la lecture resterait bloquée en pause indéfiniment.
        const safetyTimer = setTimeout(finish, 700);
        try { vid.currentTime = withinOffset; } catch(e) { finish(); }
    };
    vid.dataset.selectId = r.sel.id;
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
        // la vidéo joue le stéréo brut du proxy, donc le LTC en plus du micro.
        _attachBasketVidAudio(vid);
        _setBasketMonoR(vid, r.clip.ltc_tc_in_sec != null);
        vid.addEventListener('loadedmetadata', seekAndMaybePlay, {once: true});
    }
}

// Routage WebAudio dédié au lecteur du pré-montage — même schéma que
// _attachCmpSlotAudio/_setCmpMonoR (js/compare.js), mais paramétré PAR ÉLÉMENT
// (2 gains stockés sur le <video> lui-même, vid._gainStereo/_gainMonoR) plutôt
// que par slot, puisqu'il y a maintenant 2 lecteurs (#basketVid/#basketVidB,
// cf. section double lecteur ci-dessus). Un seul AudioContext partagé.
let _basketAudioCtx = null;

function _attachBasketVidAudio(vid) {
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
        const gainStereo = _basketAudioCtx.createGain();
        gainStereo.gain.value = 1;
        mergerS.connect(gainStereo);
        gainStereo.connect(_basketAudioCtx.destination);
        // Route B : mono canal droit dupliqué (supprime le LTC du canal gauche)
        const mergerM = _basketAudioCtx.createChannelMerger(2);
        splitter.connect(mergerM, 1, 0);
        splitter.connect(mergerM, 1, 1);
        const gainMonoR = _basketAudioCtx.createGain();
        gainMonoR.gain.value = 0;
        mergerM.connect(gainMonoR);
        gainMonoR.connect(_basketAudioCtx.destination);
        vid._gainStereo = gainStereo;
        vid._gainMonoR = gainMonoR;
        vid._audioAttached = true;
    } catch(e) { console.warn('Basket viewer audio routing fail:', e); }
}

function _setBasketMonoR(vid, on) {
    if(!vid || !_basketAudioCtx) return;
    if(_basketAudioCtx.state === 'suspended') _basketAudioCtx.resume().catch(() => {});
    if(vid._gainStereo) vid._gainStereo.gain.value = on ? 0 : 1;
    if(vid._gainMonoR) vid._gainMonoR.gain.value = on ? 1 : 0;
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
    const vid = _basketActiveVid();
    if(vid) vid.pause();
    _basketPlaying = false;
    _setBasketPlayBtnLabel();
    document.querySelectorAll('.basket-item.playing').forEach(el => el.classList.remove('playing'));
}

// Libère les DEUX décodeurs vidéo + réinitialise la timeline — appelé à la
// fermeture de l'overlay (même raison que closeMcViewer/closeCompare : sans
// ça, l'élément <video> garde une référence au buffer décodé même invisible).
function _basketReleaseViewer() {
    ['basketVid', 'basketVidB'].forEach(id => {
        const vid = document.getElementById(id);
        if(!vid) return;
        vid.pause();
        vid.removeAttribute('src');
        vid.load();
        delete vid.dataset.clipId;
        delete vid.dataset.selectId;
    });
    _basketVidActiveId = 'basketVid';
    const a = document.getElementById('basketVid'), b = document.getElementById('basketVidB');
    if(a) a.classList.add('bv-active');
    if(b) b.classList.remove('bv-active');
    const ph = document.getElementById('basketViewerPlaceholder');
    if(ph) ph.style.display = '';
    const nameEl = document.getElementById('basketViewerName');
    if(nameEl) nameEl.textContent = '—';
    const metaEl = document.getElementById('basketViewerMeta');
    if(metaEl) metaEl.textContent = '--:--:--:-- → --:--:--:--';
    // Reset du zoom de la timeline de séquence pour la prochaine ouverture.
    _basketSeqZoom = 1;
    const track = document.getElementById('basketSeqTimeline');
    if(track) track.style.width = '';
    const markersLane = document.getElementById('basketSeqMarkers');
    if(markersLane) markersLane.style.width = '';
    // Coupe la boucle de rendu LUT (inutile tant que l'overlay est fermé) —
    // le contexte GL/canvas lui-même est conservé, réutilisé à la prochaine
    // ouverture (même logique que le lecteur principal, jamais détruit non plus).
    if(_basketLutRaf) { cancelAnimationFrame(_basketLutRaf); _basketLutRaf = null; }
    const lutCanvas = document.getElementById('basketLutCanvas');
    if(lutCanvas) lutCanvas.style.display = 'none';
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
    const isMine = _basketViewUser === (currentSession && currentSession.user_id);
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
        // Poignées de trim (façon DaVinci) — lecture seule si on regarde le
        // pré-montage d'un collaborateur (cohérent avec le reste de l'overlay :
        // seul l'auteur peut éditer, cf. CLAUDE.md § Visibilité vs édition).
        if(isMine) {
            const handleIn = document.createElement('div');
            handleIn.className = 'bseq-handle bseq-handle-in';
            handleIn.draggable = false;  // ne doit jamais déclencher le drag natif du segment parent
            const handleOut = document.createElement('div');
            handleOut.className = 'bseq-handle bseq-handle-out';
            handleOut.draggable = false;
            el.appendChild(handleIn);
            el.appendChild(handleOut);
            _wireBasketSeqHandle(handleIn, seg, 'in');
            _wireBasketSeqHandle(handleOut, seg, 'out');
            // Glisser le CORPS du segment (pas une poignée) le réordonne dans la
            // séquence, façon DaVinci — retour terrain : « pouvoir, en cliquant
            // gauche sur un clip dans la timeline, le déplacer pour l'intercaler
            // entre deux clips ou au début/fin de la séquence ». Drag natif HTML5
            // (pas le pattern mousedown/mousemove des poignées) : plus simple, et
            // coexiste proprement avec les poignées grâce à draggable=false + leur
            // propre preventDefault/stopPropagation sur mousedown (empêche le drag
            // natif de démarrer quand on saisit une poignée précisément).
            el.draggable = true;
            _wireBasketSeqSegDrag(el, seg);
        }
        track.insertBefore(el, head);
    });
    _basketUpdateSeqHead();
    _basketRenderSeqMarkers();
}

// Identité du segment en cours de glisser sur la timeline de séquence — par
// INDEX de rendu (pas par référence d'objet) car un `dragover`/`drop` doit
// pouvoir retrouver `seg.idx` de la cible sans recalculer `_basketSeqSegments()`
// à chaque évènement (des dizaines/s pendant qu'on survole).
let _basketSeqDragIdx = null;

// Glisser-déposer un CLIP entier sur la timeline de séquence pour le
// réordonner — distinct de _wireBasketDrag (réordonnancement depuis la LISTE
// à gauche) mais même logique de fond sur allBaskets[uid]. Ici, la moitié du
// segment survolée (gauche/droite) détermine si le clip glissé s'insère AVANT
// ou APRÈS la cible — c'est ce qui permet de l'intercaler précisément entre
// deux clips, ou de viser le tout début/toute la fin de la bobine en lâchant
// sur la moitié extérieure du premier/dernier segment.
function _wireBasketSeqSegDrag(el, seg) {
    el.addEventListener('dragstart', (e) => {
        if(_basketArmedTrim) _basketCommitArmedTrim();  // flush avant de démarrer un nouveau geste
        _basketSeqDragIdx = seg.idx;
        el.classList.add('dragging');
        if(e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', ''); } catch(err) {}  // requis par Firefox pour autoriser le drag
        }
    });
    el.addEventListener('dragend', () => {
        el.classList.remove('dragging');
        document.querySelectorAll('.basket-seq-seg.drop-before, .basket-seq-seg.drop-after')
            .forEach(x => x.classList.remove('drop-before', 'drop-after'));
        _basketSeqDragIdx = null;
    });
    el.addEventListener('dragover', (e) => {
        if(_basketSeqDragIdx === null || _basketSeqDragIdx === seg.idx) return;
        e.preventDefault();
        if(e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        const rect = el.getBoundingClientRect();
        const before = (e.clientX - rect.left) < rect.width / 2;
        document.querySelectorAll('.basket-seq-seg.drop-before, .basket-seq-seg.drop-after')
            .forEach(x => { if(x !== el) x.classList.remove('drop-before', 'drop-after'); });
        el.classList.toggle('drop-before', before);
        el.classList.toggle('drop-after', !before);
    });
    el.addEventListener('dragleave', () => el.classList.remove('drop-before', 'drop-after'));
    el.addEventListener('drop', (e) => {
        e.preventDefault();
        const before = el.classList.contains('drop-before');
        el.classList.remove('drop-before', 'drop-after');
        if(_basketSeqDragIdx === null || _basketSeqDragIdx === seg.idx) return;
        _basketSeqReorder(_basketSeqDragIdx, seg.idx, before);
    });
}

function _basketSeqReorder(fromIdx, toIdx, before) {
    const fromR = _basketLastResolved[fromIdx];
    const toR = _basketLastResolved[toIdx];
    const arr = allBaskets[_basketViewUser];
    if(!fromR || !toR || !arr) return;
    const fromRealIdx = arr.indexOf(fromR.item);
    let toRealIdx = arr.indexOf(toR.item);
    if(fromRealIdx < 0 || toRealIdx < 0) return;
    _pushBasketUndo();
    const [moved] = arr.splice(fromRealIdx, 1);
    if(fromRealIdx < toRealIdx) toRealIdx--;  // le splice a décalé les index suivants d'un cran
    arr.splice(before ? toRealIdx : toRealIdx + 1, 0, moved);
    renderBasketOverlay();
    saveBasket();
}

// ─── Repères de séquence (façon DaVinci) ────────────────────────────────────
// De simples points d'accroche pour le magnétisme des poignées de trim — PAS
// les marqueurs annotés (catégorie/commentaire/discussion) posés sur un clip
// via addMarker(). Position en SECONDES DANS LA SÉQUENCE assemblée (pas dans
// un clip source précis), donc valables tant que l'ordre/durée des sélections
// ne change pas radicalement — comme dans tout NLE, un repère ne "ripple" pas
// automatiquement si on retrime largement en amont. Personnels (pas partagés
// avec l'équipe, pas dans allNotes) : persistés en localStorage par projet,
// même logique que _lutAssign/_bwfMixerSettings.
let _basketSeqMarkers = [];
// Repère actuellement sélectionné (sa valeur en secondes-séquence, pas un
// index — un index se périmerait au moindre ajout/retrait puisque le tableau
// est retrié). `null` si aucun. Un clic sur un repère sélectionne + déplace la
// tête de lecture dessus (aperçu immédiat) ; `Suppr`/`Backspace` le retire —
// retour terrain : « je ne veux pas que le clic l'efface, je veux avancer le
// clip à cet endroit et voir l'image, la suppression doit être un geste à part ».
let _basketSelectedSeqMarker = null;

function _basketMarkersStorageKey(pid) { return 'derush_basket_seq_markers_' + pid; }

function _loadBasketSeqMarkers(pid) {
    _basketSeqMarkers = [];
    if(!pid) return;
    try {
        const raw = localStorage.getItem(_basketMarkersStorageKey(pid));
        if(raw) _basketSeqMarkers = JSON.parse(raw).filter(t => typeof t === 'number');
    } catch(e) {}
}

function _saveBasketSeqMarkers(pid) {
    if(!pid) return;
    try { localStorage.setItem(_basketMarkersStorageKey(pid), JSON.stringify(_basketSeqMarkers)); } catch(e) {}
}

function _basketRenderSeqMarkers() {
    const lane = document.getElementById('basketSeqMarkers');
    if(!lane) return;
    lane.innerHTML = '';
    const total = _basketSeqTotalDuration();
    if(total <= 0) return;
    _basketSeqMarkers.forEach(t => {
        const pin = document.createElement('div');
        pin.className = 'basket-seq-marker-pin bseq-marker-diamond' + (t === _basketSelectedSeqMarker ? ' selected' : '');
        pin.style.left = Math.max(0, Math.min(100, t / total * 100)) + '%';
        pin.title = _fmtDurShort(t) + (t === _basketSelectedSeqMarker
            ? ' — sélectionné (Suppr pour retirer)' : ' — clic pour y aller');
        // stopPropagation dès le mousedown (pas juste au click) : la lane parente
        // écoute désormais mousedown pour distinguer clic (pose un repère) et
        // glisser (scrub) — sans ça, presser un repère existant déclencherait
        // AUSSI cette logique et poserait un repère parasite au même endroit.
        pin.addEventListener('mousedown', (e) => e.stopPropagation());
        pin.onclick = (e) => { e.stopPropagation(); _basketSelectSeqMarker(t); };
        lane.appendChild(pin);
    });
}

function _basketAddSeqMarkerAt(t) {
    const total = _basketSeqTotalDuration();
    if(total <= 0) return;
    t = Math.max(0, Math.min(total, Math.round(t * 1000) / 1000));
    // Pas de doublon quasi-identique (< 0.1s) — n'apporterait rien de plus au magnétisme.
    if(_basketSeqMarkers.some(m => Math.abs(m - t) < 0.1)) return;
    _basketSeqMarkers.push(t);
    _basketSeqMarkers.sort((a, b) => a - b);
    _saveBasketSeqMarkers(currentProjectId);
    _basketRenderSeqMarkers();
    showToast('📍 Repère ajouté — glissez une poignée à proximité pour vous y accrocher', 'ok');
}

// Position de lecture courante DANS LA SÉQUENCE (même formule que _basketUpdateSeqHead).
function _basketAddSeqMarkerAtPlayhead() {
    const segs = _basketSeqSegments();
    const cur = segs[_basketPlayIdx];
    const vid = _basketActiveVid();
    if(!cur || !vid) { showToast('Charge une sélection dans la visionneuse d’abord', 'warn'); return; }
    const withinSel = Math.max(0, (vid.currentTime || 0) - cur.r.sel.in);
    _basketAddSeqMarkerAt(cur.start + Math.min(withinSel, cur.dur));
}

// Traduit une position en secondes-séquence vers {idx, offset} exploitable par
// _basketGoto (offset = secondes DANS le clip source du segment concerné).
function _basketSeqTimeToSegmentOffset(t) {
    const segs = _basketSeqSegments();
    if(!segs.length) return null;
    let seg = segs.find(s => t < s.start + s.dur - 1e-6);
    if(!seg) seg = segs[segs.length - 1];
    const within = Math.max(0, Math.min(seg.dur, t - seg.start));
    return {idx: seg.idx, offset: seg.r.sel.in + within};
}

// Sélectionne un repère (surbrillance) ET avance la tête de lecture dessus
// pour en montrer l'image exacte dans la visionneuse — le clic ne supprime
// plus rien, cf. _basketKeydown pour la suppression via Suppr/Backspace.
function _basketSelectSeqMarker(t) {
    _basketSelectedSeqMarker = t;
    _basketRenderSeqMarkers();
    const hit = _basketSeqTimeToSegmentOffset(t);
    if(hit) _basketGoto(hit.idx, hit.offset, false);
}

function _basketDeselectSeqMarker() {
    if(_basketSelectedSeqMarker === null) return false;
    _basketSelectedSeqMarker = null;
    _basketRenderSeqMarkers();
    return true;
}

function _basketDeleteSelectedSeqMarker() {
    if(_basketSelectedSeqMarker === null) return;
    const idx = _basketSeqMarkers.indexOf(_basketSelectedSeqMarker);
    if(idx >= 0) _basketSeqMarkers.splice(idx, 1);
    _basketSelectedSeqMarker = null;
    _saveBasketSeqMarkers(currentProjectId);
    _basketRenderSeqMarkers();
    showSaveStatus('📍 Repère supprimé', '#f59e0b');
}

// Retour terrain : « plutôt que de placer un repère quand je clique au-dessus
// de la timeline, que je puisse me déplacer dans la sélection quand je
// maintiens le clic gauche. » Même distinction clic/glisser que le reste du
// pré-montage (poignées de trim, segments à réordonner) : un simple clic
// (pas de glisser réel) pose toujours un repère à cet endroit — un clic
// MAINTENU et déplacé scrube la séquence à la place, comme sur la piste des
// segments juste en-dessous (_basketSeqMouseDown/_basketSeekSeqRatio, même
// mécanisme, juste déclenché depuis la lane des repères).
function _basketMarkerLaneMouseDown(e) {
    const lane = document.getElementById('basketSeqMarkers');
    if(!lane) return;
    const startX = e.clientX;
    let dragged = false;
    const onMove = (e2) => {
        if(!dragged && Math.abs(e2.clientX - startX) < 3) return;
        dragged = true;
        const rect = lane.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e2.clientX - rect.left) / rect.width));
        _basketSeekSeqRatio(ratio);
    };
    const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        if(dragged) return;  // le scrub a déjà eu lieu pendant le glisser, rien de plus à faire
        _basketDeselectSeqMarker();
        const rect = lane.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (startX - rect.left) / rect.width));
        _basketAddSeqMarkerAt(ratio * _basketSeqTotalDuration());
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

// Repère le plus proche de `pos` (secondes-séquence) sous le seuil `tolSec`,
// ou `null` si aucun n'est assez proche — utilisé par le magnétisme du drag.
function _basketNearestSeqMarker(pos, tolSec) {
    let best = null, bestDist = Infinity;
    for(const m of _basketSeqMarkers) {
        const d = Math.abs(m - pos);
        if(d < bestDist) { bestDist = d; best = m; }
    }
    return (best !== null && bestDist <= tolSec) ? best : null;
}

// ─── Précision de trim façon DaVinci : snap-frame + HUD TC/delta + trim clavier ──
// Trois briques réutilisées à la fois par le glisser-souris (_wireBasketSeqHandle)
// et par le trim "armé" au clavier (_basketArmTrimHandle & co juste après) :
// 1. _basketSnapClamp — arrondit TOUJOURS le point trimmé à la frame exacte la
//    plus proche (fps du clip) et le clampe aux bornes valides. Avant, un
//    glisser souris produisait un `sel.in`/`out` en secondes flottantes
//    arbitraires (résolution pixel, pas frame) — retour terrain : « on perd
//    vite l'endroit précis où l'on voulait atterrir ». Snapper sur la grille
//    de frames, comme le fait toute timeline NLE, élimine ce flou par
//    construction : le point où l'on relâche/valide EST une frame exacte.
// 2. _basketFmtDelta — formate l'écart entre la position live et la position
//    de départ en "+1s04f"/"−12f"/"±0f", pour savoir exactement de combien on
//    a déplacé le point, pas seulement où il se trouve dans l'absolu.
// 3. _basketShowTrimHud/_basketHideTrimHud — bulle flottante au-dessus de la
//    poignée concernée (TC exact + delta + rappel des raccourcis), seule vraie
//    réponse à "je ne sais plus où j'atterris" : elle est visible en continu
//    pendant tout le geste, glisser ou nudge clavier.
function _basketSnapClamp(edge, rawT, otherBound, fps, clipDur, minDur) {
    let t = edge === 'in' ? Math.max(0, Math.min(rawT, otherBound - minDur))
                          : Math.min(clipDur, Math.max(rawT, otherBound + minDur));
    t = Math.round(t * fps) / fps;
    // Le snap peut repousser très légèrement hors bornes (arrondi) → re-clamp.
    t = edge === 'in' ? Math.max(0, Math.min(t, otherBound - minDur))
                      : Math.min(clipDur, Math.max(t, otherBound + minDur));
    return t;
}

function _basketFmtDelta(deltaSec, fps) {
    const totalFrames = Math.round(Math.abs(deltaSec) * fps);
    if(totalFrames === 0) return {text: '±0f', cls: 'zero'};
    const sign = deltaSec > 0 ? '+' : '−';
    const s = Math.floor(totalFrames / fps);
    const f = totalFrames % fps;
    const text = sign + (s > 0 ? s + 's' : '') + String(f).padStart(2, '0') + 'f';
    return {text, cls: deltaSec > 0 ? 'pos' : 'neg'};
}

function _basketShowTrimHud(handleEl, tcText, deltaSec, fps, hint) {
    const hud = document.getElementById('basketTrimHud');
    if(!hud || !handleEl) return;
    const d = _basketFmtDelta(deltaSec, fps);
    hud.innerHTML = `<div class="bth-tc">${tcText}</div><div class="bth-delta ${d.cls}">${d.text}</div>` +
        (hint ? `<div class="bth-hint">${hint}</div>` : '');
    const r = handleEl.getBoundingClientRect();
    hud.style.left = Math.round(r.left + r.width / 2) + 'px';
    hud.style.top = Math.round(r.top - 8) + 'px';
    hud.style.display = 'block';
}

function _basketHideTrimHud() {
    const hud = document.getElementById('basketTrimHud');
    if(hud) hud.style.display = 'none';
}

// Poignées de trim directement sur la timeline de séquence : redimensionne
// r.sel.in/out du segment survolé. Aucune notion de "ripple" à gérer entre
// segments voisins — chaque segment n'est jamais qu'un bloc positionné bout à
// bout proportionnellement à SA PROPRE durée : agrandir un segment repousse
// simplement le suivant plus loin dans la séquence sans jamais toucher aux
// bornes in/out de ce voisin — "raccorde" automatiquement, par construction.
// Même principe que les poignées du lecteur principal (_wireSelectRangeHandle) :
// pendant le glisser, seuls les styles CSS des blocs bougent (_basketPreviewSeqWidths,
// pas de refetch de vignette) — sel.in/out n'est muté QU'AU relâchement, pour un
// undo propre (pushUndo lirait sinon l'état déjà modifié par le live-preview).
// UN CLIC SANS GLISSER n'est plus un no-op : il ARME la poignée pour un trim
// au clavier frame-exact (_basketArmTrimHandle) — façon DaVinci, où cliquer un
// point de montage puis utiliser ←/→ est le geste de précision de référence,
// le glisser souris restant le geste rapide/approximatif.
const _BASKET_TRIM_MIN_DUR = 0.08;  // ~2 frames — évite une sélection de durée nulle/négative

function _wireBasketSeqHandle(handleEl, seg, edge) {
    handleEl.addEventListener('mousedown', (e) => {
        e.stopPropagation();  // ne pas déclencher le seek du track parent (_basketSeqMouseDown)
        e.preventDefault();
        if(_basketArmedTrim) {
            // Valider un trim clavier en attente reconstruit TOUTE la timeline de
            // séquence (_basketRenderSeqTimeline détruit/recrée chaque poignée) —
            // y compris CETTE poignée qu'on vient de presser. Continuer avec la
            // référence DOM désormais détachée positionnerait le HUD n'importe où
            // (getBoundingClientRect d'un nœud hors document = tout à zéro). On
            // se contente donc de valider et on s'arrête là : un second clic
            // engage la nouvelle poignée sur un DOM frais.
            _basketCommitArmedTrim();
            return;
        }
        const sel = seg.r.sel;
        const fps = seg.r.clip.fps || 25;
        const clipDur = seg.r.clip.duration_sec || (sel.out + 3600);
        let liveIn = sel.in, liveOut = sel.out, wasDragged = false;
        const startX = e.clientX;

        // Prévisualisation live dans la visionneuse pendant le trim — même principe
        // que les poignées du lecteur principal, qui font déjà v.currentTime =
        // liveIn/liveOut pendant le glisser (_wireSelectRangeHandle). Une lecture en
        // cours est stoppée (on prend la main manuellement sur la tête de lecture),
        // le segment visé devient le "courant" du pré-montage, et le clip est chargé
        // dans le lecteur actif (réutilise le swap crossfade s'il est déjà préchargé
        // dans le lecteur inactif — cf. section double lecteur).
        if(_basketPlaying) _basketTogglePlay();
        _basketPlayIdx = seg.idx;
        _basketCurrentItemRef = seg.r.item;
        _highlightBasketPlaying();
        _updateBasketViewerInfo(seg.r);
        _basketPreviewLoadClip(seg.r.clip, edge === 'in' ? sel.in : sel.out);

        const SNAP_PX = 10;  // rayon d'accroche en pixels écran — indépendant du zoom, comme le magnétisme DaVinci
        const onMove = (e2) => {
            if(!wasDragged && Math.abs(e2.clientX - startX) < 3) return;
            wasDragged = true;
            // Échelle px→secondes recalculée à chaque frame (la largeur de la
            // track change avec le zoom).
            const track = document.getElementById('basketSeqTimeline');
            const rect = track.getBoundingClientRect();
            const totalSec = _basketSeqTotalDuration() || 1;
            const pxPerSec = rect.width / totalSec;
            const dSec = (e2.clientX - startX) / pxPerSec;
            const otherBound = edge === 'in' ? sel.out : sel.in;
            const raw = edge === 'in' ? sel.in + dSec : sel.out + dSec;
            let snapped = _basketSnapClamp(edge, raw, otherBound, fps, clipDur, _BASKET_TRIM_MIN_DUR);
            // Magnétisme : seule la borne qui BOUGE réellement dans la séquence a un
            // sens à accrocher — pour CE segment c'est toujours sa frontière avec le
            // suivant (seg.start + durée), quelle que soit la poignée tenue (sa
            // frontière avec le PRÉCÉDENT ne bouge jamais, cf. _basketSeqSegments —
            // chaque bloc est juste recollé après ses prédécesseurs).
            let snappedToMarker = false;
            if(_basketSeqMarkers.length) {
                const movingBoundarySeq = seg.start + (edge === 'in' ? sel.out - snapped : snapped - sel.in);
                const nearest = _basketNearestSeqMarker(movingBoundarySeq, SNAP_PX / pxPerSec);
                if(nearest !== null) {
                    const targetDur = Math.max(_BASKET_TRIM_MIN_DUR, nearest - seg.start);
                    const raw2 = edge === 'in' ? sel.out - targetDur : sel.in + targetDur;
                    snapped = _basketSnapClamp(edge, raw2, otherBound, fps, clipDur, _BASKET_TRIM_MIN_DUR);
                    snappedToMarker = true;
                }
            }
            if(edge === 'in') liveIn = snapped; else liveOut = snapped;
            _basketPreviewSeqWidths(seg.idx, liveIn, liveOut);
            const vid = _basketActiveVid();
            if(vid) { try { vid.currentTime = snapped; } catch(err) {} }
            const orig = edge === 'in' ? sel.in : sel.out;
            _basketShowTrimHud(handleEl, timeToTC(snapped, fps) + (snappedToMarker ? ' 🧲' : ''), snapped - orig, fps, 'relâcher pour valider');
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            _basketHideTrimHud();
            if(!wasDragged) {
                // Simple clic (pas de glisser) → arme la poignée pour un trim clavier.
                _basketArmTrimHandle(handleEl, seg, edge);
                return;
            }
            pushUndo(seg.r.clip.id);
            sel.in = liveIn;
            sel.out = liveOut;
            if(activeClip && activeClip.id === seg.r.clip.id) renderMarkers();  // resync le panneau ✂️ Sélections si c'est le clip affiché
            renderBasketOverlay();
            saveNotes(true);
            showSaveStatus('✂️ Sélection ajustée', '#34d399');
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
    handleEl.addEventListener('click', (e) => e.stopPropagation());
}

// ─── Trim armé au clavier (façon DaVinci : sélectionner un point de montage
// puis ←/→ pour l'ajuster frame par frame) ───────────────────────────────────
// Comme le glisser souris, la position "live" n'est écrite dans sel.in/out
// qu'à la VALIDATION (_basketCommitArmedTrim) — chaque frappe ←/→ ne fait que
// mettre à jour l'aperçu (vidéo + largeur du bloc + HUD), pour un seul undo et
// une seule sauvegarde par session de trim plutôt qu'un par frappe.
function _basketArmTrimHandle(handleEl, seg, edge) {
    if(_basketArmedTrim) _basketCommitArmedTrim();  // une seule poignée armée à la fois
    const sel = seg.r.sel;
    const fps = seg.r.clip.fps || 25;
    _basketArmedTrim = {
        seg, edge, fps, handleEl,
        clipDur: seg.r.clip.duration_sec || (sel.out + 3600),
        origIn: sel.in, origOut: sel.out,
        liveIn: sel.in, liveOut: sel.out,
    };
    handleEl.classList.add('armed');
    if(_basketPlaying) _basketTogglePlay();
    _basketPlayIdx = seg.idx;
    _basketCurrentItemRef = seg.r.item;
    _highlightBasketPlaying();
    _updateBasketViewerInfo(seg.r);
    _basketPreviewLoadClip(seg.r.clip, edge === 'in' ? sel.in : sel.out);
    _basketShowTrimHud(handleEl, timeToTC(edge === 'in' ? sel.in : sel.out, fps), 0, fps, '←/→ 1 frame · Maj+←/→ 1s · Entrée valider · Échap annuler');
}

// `stepSec` déjà en secondes (le sens ± est porté par le signe) — retourne
// `false` si aucune poignée n'est armée (le caller retombe alors sur le
// comportement par défaut des flèches, cf. _basketKeydown).
function _basketNudgeArmedTrim(stepSec) {
    const a = _basketArmedTrim;
    if(!a) return false;
    const sel = a.seg.r.sel;
    const otherBound = a.edge === 'in' ? a.liveOut : a.liveIn;
    const raw = (a.edge === 'in' ? a.liveIn : a.liveOut) + stepSec;
    const snapped = _basketSnapClamp(a.edge, raw, otherBound, a.fps, a.clipDur, _BASKET_TRIM_MIN_DUR);
    if(a.edge === 'in') a.liveIn = snapped; else a.liveOut = snapped;
    _basketPreviewSeqWidths(a.seg.idx, a.liveIn, a.liveOut);
    const vid = _basketActiveVid();
    if(vid) { try { vid.currentTime = snapped; } catch(e) {} }
    const orig = a.edge === 'in' ? a.origIn : a.origOut;
    _basketShowTrimHud(a.handleEl, timeToTC(snapped, a.fps), snapped - orig, a.fps, '←/→ 1 frame · Maj+←/→ 1s · Entrée valider · Échap annuler');
    return true;
}

function _basketCommitArmedTrim() {
    const a = _basketArmedTrim;
    if(!a) return;
    _basketArmedTrim = null;  // avant tout re-rendu : évite la récursion avec renderBasketOverlay()
    _basketHideTrimHud();
    if(a.handleEl) a.handleEl.classList.remove('armed');
    const changed = Math.abs(a.liveIn - a.origIn) > 0.0005 || Math.abs(a.liveOut - a.origOut) > 0.0005;
    if(!changed) return;
    const sel = a.seg.r.sel;
    pushUndo(a.seg.r.clip.id);
    sel.in = a.liveIn;
    sel.out = a.liveOut;
    if(activeClip && activeClip.id === a.seg.r.clip.id) renderMarkers();
    renderBasketOverlay();
    saveNotes(true);
    showSaveStatus('✂️ Sélection ajustée', '#34d399');
}

function _basketCancelArmedTrim() {
    const a = _basketArmedTrim;
    if(!a) return;
    _basketArmedTrim = null;
    _basketHideTrimHud();
    if(a.handleEl) a.handleEl.classList.remove('armed');
    // sel.in/out n'ont jamais été mutés → il suffit de rejouer l'aperçu réel.
    _basketPreviewSeqWidths(a.seg.idx, a.origIn, a.origOut);
    const vid = _basketActiveVid();
    if(vid) { try { vid.currentTime = a.edge === 'in' ? a.origIn : a.origOut; } catch(e) {} }
}

// ─── Couper (façon DaVinci, touche C) ───────────────────────────────────────
// Scinde en deux la sélection actuellement chargée dans la visionneuse, pile
// à la position de lecture — même principe qu'un outil Lame/Razor NLE. Ne
// touche à AUCUNE donnée du clip source : ça reste une opération sur des
// sélections dans le pré-montage. La moitié d'avant réutilise l'id existant
// (mute sel.out en place), la moitié d'après devient une sélection nouvelle
// et indépendante (même schéma que _basketDuplicateItem, pour la même raison :
// retrimmer l'une des deux ensuite ne doit jamais affecter l'autre) insérée
// juste après dans allBaskets[uid]. Auteur seulement (comme tout le reste de
// l'édition du pré-montage) — bouton masqué et raccourci sans effet sinon.
function _basketCutAtPlayhead() {
    if(!currentSession || _basketViewUser !== currentSession.user_id) return;
    const segs = _basketSeqSegments();
    const seg = segs[_basketPlayIdx];
    const vid = _basketActiveVid();
    if(!seg || !vid) { showToast('Charge une sélection dans la visionneuse d’abord', 'warn'); return; }
    if(_basketArmedTrim) _basketCommitArmedTrim();  // flush un trim en attente avant de couper

    const sel = seg.r.sel;
    const clip = seg.r.clip;
    const fps = clip.fps || 25;
    if(sel.out - sel.in < _BASKET_TRIM_MIN_DUR * 2) {
        showToast('Sélection trop courte pour être coupée', 'warn');
        return;
    }
    // Snap frame-exact (même grille que le trim), clampé pour garder au moins
    // _BASKET_TRIM_MIN_DUR de chaque côté — jamais de moitié de durée nulle.
    let cutT = Math.round((vid.currentTime || 0) * fps) / fps;
    cutT = Math.max(sel.in + _BASKET_TRIM_MIN_DUR, Math.min(sel.out - _BASKET_TRIM_MIN_DUR, cutT));

    const uid = currentSession.user_id;
    const n = (allNotes[uid] || {})[clip.id];
    const arr = allBaskets[uid];
    if(!n || !n.selects || !arr) return;
    const realIdx = arr.indexOf(seg.r.item);
    if(realIdx < 0) return;

    if(_basketPlaying) _basketTogglePlay();
    pushUndo(clip.id);
    const origOut = sel.out;
    sel.out = cutT;  // 1ère moitié : mute l'original en place (même id, même item)

    const newSel = {
        id: Math.random().toString(36).slice(2, 10),
        in: cutT, out: origOut,
        name: _basketNextSuffixedName(n.selects, sel.name, 'cut'),
        tags: (sel.tags || []).slice(),
        desc: sel.desc || '',
    };
    n.selects.push(newSel);
    n.selects.sort((a, b) => a.in - b.in);

    _pushBasketUndo();
    const newItem = {id: Math.random().toString(36).slice(2, 10), clip_id: clip.id, select_id: newSel.id};
    arr.splice(realIdx + 1, 0, newItem);  // juste après la 1ère moitié dans la bobine

    if(activeClip && activeClip.id === clip.id) renderMarkers();  // resync le panneau ✂️ Sélections si affiché
    renderBasketOverlay();
    _updateBasketBadge();
    saveNotes(true);  // persiste newSel dans allNotes
    saveBasket();      // persiste newItem dans allBaskets
    showToast('✂️ Sélection coupée en deux', 'ok');
}

// Charge `clip` dans le lecteur ACTIF de la visionneuse si ce n'est pas déjà
// lui, puis seek à `thenSeekTo` — utilisé au début d'un drag de poignée de
// trim pour que la visionneuse montre tout de suite le bon clip/la bonne
// image, avant même le premier mousemove. Réutilise le lecteur inactif s'il
// a déjà ce clip de préchargé (même chemin rapide que _basketGoto), sinon
// charge une nouvelle source (un seul chargement par début de drag, jamais
// répété pendant le glisser — seul currentTime bouge ensuite, cf. onMove).
function _basketPreviewLoadClip(clip, thenSeekTo) {
    const active = _basketActiveVid();
    if(!active) return;
    if(active.dataset.clipId === clip.id) {
        if(thenSeekTo != null) { try { active.currentTime = thenSeekTo; } catch(e) {} }
        return;
    }
    const inactive = _basketInactiveVid();
    if(inactive && inactive.dataset.clipId === clip.id && inactive.readyState >= 2) {
        _basketSwapActiveVideo();
        const now = _basketActiveVid();
        if(thenSeekTo != null) { try { now.currentTime = thenSeekTo; } catch(e) {} }
        return;
    }
    active.pause();
    active.dataset.clipId = clip.id;
    active.src = clip.proxy_url || '';
    if(typeof _applyLetterbox === 'function') _applyLetterbox(active, clip.id, false);
    _attachBasketVidAudio(active);
    _setBasketMonoR(active, clip.ltc_tc_in_sec != null);
    active.addEventListener('loadedmetadata', () => {
        if(thenSeekTo != null) { try { active.currentTime = thenSeekTo; } catch(e) {} }
    }, {once: true});
}

// Ajuste juste les largeurs (%) des blocs déjà en place, sans toucher aux
// données ni recréer les vignettes — l'aperçu live du drag doit être bon
// marché (potentiellement des dizaines de mousemove/s).
function _basketPreviewSeqWidths(idx, previewIn, previewOut) {
    const track = document.getElementById('basketSeqTimeline');
    if(!track) return;
    const els = track.querySelectorAll('.basket-seq-seg');
    let total = 0;
    const durs = _basketLastResolved.map((r, i) => {
        const dur = i === idx ? Math.max(0.01, previewOut - previewIn) : Math.max(0.01, r.sel.out - r.sel.in);
        total += dur;
        return dur;
    });
    els.forEach((el, i) => { el.style.width = (total > 0 ? durs[i] / total * 100 : 0) + '%'; });
}

function _basketUpdateSeqHead() {
    const head = document.getElementById('basketSeqHead');
    const tcEl = document.getElementById('basketSeqTc');
    const total = _basketSeqTotalDuration();
    const segs = _basketSeqSegments();
    const cur = segs[_basketPlayIdx];
    const vid = _basketActiveVid();
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
    _basketGoto(seg.idx, withinOffset, _basketPlaying, true);
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

// Zoom molette sur la timeline de séquence (utile avec beaucoup de clips, pour
// viser précisément une poignée de trim). #basketSeqTimelineScroll a une
// largeur fixe (viewport) ; #basketSeqTimeline à l'intérieur s'élargit
// (width:N*100%) — les segments ont des largeurs en %, donc relatives à LEUR
// parent (la track) et se recalculent automatiquement sans toucher au reste
// du rendu. Zoom ancré sous le curseur, comme DaVinci/Premiere.
let _basketSeqZoom = 1;
const _BASKET_SEQ_ZOOM_MIN = 1, _BASKET_SEQ_ZOOM_MAX = 25;

function _basketSeqWheel(e) {
    if(!_basketLastResolved.length) return;
    e.preventDefault();
    const scrollEl = document.getElementById('basketSeqTimelineScroll');
    const track = document.getElementById('basketSeqTimeline');
    if(!scrollEl || !track) return;
    const rectBefore = track.getBoundingClientRect();
    const ratioAtCursor = rectBefore.width > 0 ? Math.max(0, Math.min(1, (e.clientX - rectBefore.left) / rectBefore.width)) : 0.5;
    const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2;
    const newZoom = Math.max(_BASKET_SEQ_ZOOM_MIN, Math.min(_BASKET_SEQ_ZOOM_MAX, _basketSeqZoom * factor));
    if(newZoom === _basketSeqZoom) return;
    _basketSeqZoom = newZoom;
    track.style.width = (_basketSeqZoom * 100) + '%';
    const markersLane = document.getElementById('basketSeqMarkers');
    if(markersLane) markersLane.style.width = track.style.width;  // reste alignée avec la piste zoomée
    requestAnimationFrame(() => {
        const rectAfter = track.getBoundingClientRect();
        const cursorOffsetInScroll = e.clientX - scrollEl.getBoundingClientRect().left;
        scrollEl.scrollLeft = ratioAtCursor * rectAfter.width - cursorOffsetInScroll;
    });
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

// Coche/décoche un item pour un export PARTIEL (case à cocher sur chaque ligne
// du pré-montage). Ne touche jamais allBaskets — état d'édition transitoire,
// jamais sauvegardé/synchronisé.
function _basketToggleExportSel(itemId, checked) {
    if(checked) _basketExportSelIds.add(itemId);
    else _basketExportSelIds.delete(itemId);
    const row = document.querySelector(`.basket-item[data-item-id="${itemId}"]`);
    if(row) row.classList.toggle('export-checked', checked);
    _basketUpdateExportSelUI();
}

// Handler `onclick` (pas `onchange` — un `change` de checkbox est un Event
// générique sans `shiftKey`, un `click` est un MouseEvent qui le porte) sur
// chaque case du pré-montage. Clic simple : coche/décoche normalement et pose
// l'ancre de plage sur cet item. Maj+clic : coche toute la plage entre l'ancre
// et l'item cliqué (façon Explorateur Windows/Gmail), sans changer l'ancre —
// un Maj+clic répété depuis la même ancre étend/rétrécit la plage.
function _basketCheckboxClick(e, itemId, idx) {
    const anchorIdx = _basketAnchorCurrentIdx();
    if(e.shiftKey && anchorIdx >= 0) {
        e.preventDefault();  // annule le toggle natif déjà appliqué par le navigateur : la plage décide seule du résultat
        _basketApplyRangeSelect(anchorIdx, idx);
        return;
    }
    _basketExportAnchorItemId = itemId;
    _basketToggleExportSel(itemId, e.target.checked);
}

// Même geste que _basketCheckboxClick mais déclenché depuis un Maj+clic sur le
// CORPS de la ligne (vignette, nom...) plutôt que sur la case elle-même — la
// cible naturelle d'un Maj+clic est la ligne entière, pas un petit carré de
// quelques pixels. Avec une ancre déjà posée : coche la plage. Sans ancre
// (tout premier clic du panier tenu avec Maj) : coche juste cet item et le
// prend comme ancre, même résultat qu'un clic simple sur sa case.
function _basketRowShiftClick(idx) {
    const anchorIdx = _basketAnchorCurrentIdx();
    if(anchorIdx >= 0) {
        _basketApplyRangeSelect(anchorIdx, idx);
        return;
    }
    const it = _basketLastResolved[idx] && _basketLastResolved[idx].item;
    if(!it) return;
    _basketExportAnchorItemId = it.id;
    _basketExportSelIds.add(it.id);
    const row = document.querySelector(`.basket-item[data-item-id="${it.id}"]`);
    if(row) {
        row.classList.add('export-checked');
        const cb = row.querySelector('.basket-item-check input');
        if(cb) cb.checked = true;
    }
    _basketUpdateExportSelUI();
}

// Coche toute la plage [fromIdx, toIdx] (bornes incluses, ordre indifférent)
// dans l'ordre du rendu courant (_basketLastResolved) — ne décoche jamais rien
// hors de la plage, cohérent avec le comportement standard d'un Maj+clic.
function _basketApplyRangeSelect(fromIdx, toIdx) {
    const lo = Math.min(fromIdx, toIdx), hi = Math.max(fromIdx, toIdx);
    for(let i = lo; i <= hi; i++) {
        const it = _basketLastResolved[i] && _basketLastResolved[i].item;
        if(it) _basketExportSelIds.add(it.id);
    }
    document.querySelectorAll('#basketBody .basket-item').forEach(row => {
        const checked = _basketExportSelIds.has(row.dataset.itemId);
        const cb = row.querySelector('.basket-item-check input');
        if(cb) cb.checked = checked;
        row.classList.toggle('export-checked', checked);
    });
    _basketUpdateExportSelUI();
}

function _basketExportSelClearAll() {
    _basketExportSelIds.clear();
    _basketExportAnchorItemId = null;
    document.querySelectorAll('#basketBody .basket-item').forEach(row => {
        row.classList.remove('export-checked');
        const cb = row.querySelector('.basket-item-check input');
        if(cb) cb.checked = false;
    });
    _basketUpdateExportSelUI();
}

// Reflète le nombre d'items cochés sur le bouton Export + active/désactive les
// deux entrées "sélection" du menu déroulant.
function _basketUpdateExportSelUI() {
    const n = _basketExportSelIds.size;
    const btn = document.getElementById('basketExportBtn');
    if(btn) btn.textContent = n > 0 ? `📤 Exporter (${n} coché${n > 1 ? 's' : ''})` : '📤 Exporter';
    const selBtns = document.querySelectorAll('.basket-export-sel-only');
    selBtns.forEach(b => { b.disabled = n === 0; });
    const clearBtn = document.getElementById('basketExportSelClearBtn');
    if(clearBtn) clearBtn.style.display = n > 0 ? '' : 'none';
}

async function _basketExport(fmt, onlySelected) {
    const menu = document.getElementById('basketExportMenu');
    if(menu) menu.style.display = 'none';
    if(!currentProjectId || !_basketViewUser) return;
    let itemsQs = '';
    if(onlySelected) {
        if(!_basketExportSelIds.size) {
            showToast('Coche au moins un élément du pré-montage (case à cocher sur chaque ligne) avant d’exporter la sélection', 'warn');
            return;
        }
        itemsQs = `&items=${encodeURIComponent([..._basketExportSelIds].join(','))}`;
    }
    let labelRaw = (currentProject && currentProject.name) || 'projet';
    if(fmt === 'fcpxml' || fmt === 'drt') {
        // Retour terrain : proposer un nom plutôt qu'un nom automatique — cf.
        // _promptExportName dans derush_app.html (générique, partagée avec tous
        // les autres points d'export .fcpxml/.drt).
        const chosen = await _promptExportName(labelRaw);
        if(chosen === null) return;
        labelRaw = _sanitizeFilenamePart(chosen);
    }
    const label = encodeURIComponent(labelRaw);
    // root_path configuré (📁) → prime sur clip['path'] figé au scan (piège #36)
    const rp = currentSession && currentSession.root_path;
    const rootQs = rp ? `&root=${encodeURIComponent(rp)}` : '';
    const url = `/api/project/${currentProjectId}/export/basket_${fmt}?user=${encodeURIComponent(_basketViewUser)}&label=${label}${rootQs}${itemsQs}`;
    if(fmt === 'drt') {
        // Choix du nom ET de l'emplacement via File System Access API — voir
        // _downloadWithPicker (derush_app.html) pour le détail/fallback.
        await _downloadWithPicker(url, `${labelRaw}_panier.drt`);
        return;
    }
    window.open(url, '_blank');
}
