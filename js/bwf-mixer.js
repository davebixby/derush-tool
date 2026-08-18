// ─── Mixeur multipiste du son ingé (BWF) ───────────────────────────────────
// Un BWF multipistes (boom + HF1 + HF2 + ambiance...) était jusqu'ici sommé
// vers stéréo à gain fixe (1/3 par piste, cf. _bwfBuildMixerGraph). Ce module
// expose un GainNode par piste (mute/solo/volume), pilotable depuis un
// panneau flottant, avec les noms de piste réels lus depuis le chunk iXML
// quand l'enregistreur les a écrits (Sound Devices, Zoom...), sinon "Piste N".
//
// Un seul BWF joue à la fois (lecteur principal OU viewer multicam, jamais
// les deux — openMcViewer met le player principal en pause) donc un unique
// panneau + état partagé suffit pour les deux contextes.

const MAX_BWF_MIXER_CH = 8;
const BWF_MIXER_DEFAULT_GAIN = 1 / 3;  // = comportement d'avant ce module (mix fixe)

let _bwfMixerSettings = {};      // {pid: {bwfId: {gains:[...], mutes:[...], solos:[...]}}}
let _bwfMixerPanelState = null;  // {audio, bwfId, channels, trackNames} du BWF affiché dans le panneau

function _bwfMixerLoadAll(pid) {
    try {
        const raw = localStorage.getItem('derush_bwf_mixer_' + pid);
        _bwfMixerSettings[pid] = raw ? JSON.parse(raw) : {};
    } catch(e) { _bwfMixerSettings[pid] = {}; }
}

function _bwfMixerSave(pid) {
    try { localStorage.setItem('derush_bwf_mixer_' + pid, JSON.stringify(_bwfMixerSettings[pid] || {})); } catch(e) {}
}

function _bwfMixerGetSettings(bwfId, channels) {
    const pid = currentProjectId;
    if (!_bwfMixerSettings[pid]) _bwfMixerLoadAll(pid);
    const store = _bwfMixerSettings[pid];
    let s = store[bwfId];
    if (!s || s.gains.length !== channels) {
        s = {
            gains: Array(channels).fill(BWF_MIXER_DEFAULT_GAIN),
            mutes: Array(channels).fill(false),
            solos: Array(channels).fill(false),
        };
        store[bwfId] = s;
    }
    return s;
}

// Construit le graphe WebAudio : MediaElementSource -> ChannelSplitter(8) ->
// 1 GainNode indépendant par piste -> ChannelMerger(2) -> destination. Chaque
// piste mono alimente à la fois L et R du merger (centrée). Remplace l'ancien
// mixdown à gain fixe partagé par un gain par piste, piloté par le panneau.
function _bwfBuildMixerGraph(audio, ctx, bwfId, channels, trackNames) {
    try {
        if (ctx.state === 'suspended') ctx.resume().catch(() => {});
        const ch = Math.max(1, Math.min(channels || 2, MAX_BWF_MIXER_CH));
        const src = ctx.createMediaElementSource(audio);
        src.channelInterpretation = 'discrete';
        const splitter = ctx.createChannelSplitter(MAX_BWF_MIXER_CH);
        const merger = ctx.createChannelMerger(2);
        src.connect(splitter);
        const trackGains = [];
        for (let i = 0; i < ch; i++) {
            const g = ctx.createGain();
            splitter.connect(g, i);
            g.connect(merger, 0, 0);
            g.connect(merger, 0, 1);
            trackGains.push(g);
        }
        merger.connect(ctx.destination);
        audio._bwfMixer = {src, splitter, merger, trackGains, channels: ch, trackNames: trackNames || [], bwfId};
        _bwfMixerApplyGains(audio);
        return true;
    } catch(e) {
        console.warn('BWF mixer routing failed (fallback to default stereo downmix):', e);
        return false;
    }
}

function _bwfTeardownMixerGraph(audio) {
    if (!audio || !audio._bwfMixer) return;
    const m = audio._bwfMixer;
    try { m.src.disconnect(); } catch(_) {}
    try { m.splitter.disconnect(); } catch(_) {}
    try { m.merger.disconnect(); } catch(_) {}
    (m.trackGains || []).forEach(g => { try { g.disconnect(); } catch(_) {} });
    audio._bwfMixer = null;
}

// Recalcule le gain effectif de chaque piste à partir des réglages persistés
// (gain/mute/solo) et l'applique aux GainNode live du graphe.
function _bwfMixerApplyGains(audio) {
    if (!audio || !audio._bwfMixer) return;
    const m = audio._bwfMixer;
    const s = _bwfMixerGetSettings(m.bwfId, m.channels);
    const anySolo = s.solos.some(Boolean);
    m.trackGains.forEach((g, i) => {
        const muted = s.mutes[i] || (anySolo && !s.solos[i]);
        g.gain.value = muted ? 0 : s.gains[i];
    });
}

function _bwfMixerSetGain(idx, value) {
    const st = _bwfMixerPanelState; if (!st) return;
    const s = _bwfMixerGetSettings(st.bwfId, st.channels);
    s.gains[idx] = Math.max(0, Math.min(1.5, parseFloat(value)));
    _bwfMixerSave(currentProjectId);
    if (st.audio) _bwfMixerApplyGains(st.audio);
    _bwfMixerUpdateRowUI(idx);
}

function _bwfMixerToggleMute(idx) {
    const st = _bwfMixerPanelState; if (!st) return;
    const s = _bwfMixerGetSettings(st.bwfId, st.channels);
    s.mutes[idx] = !s.mutes[idx];
    _bwfMixerSave(currentProjectId);
    if (st.audio) _bwfMixerApplyGains(st.audio);
    renderBwfMixerPanel();
}

function _bwfMixerToggleSolo(idx) {
    const st = _bwfMixerPanelState; if (!st) return;
    const s = _bwfMixerGetSettings(st.bwfId, st.channels);
    s.solos[idx] = !s.solos[idx];
    _bwfMixerSave(currentProjectId);
    if (st.audio) _bwfMixerApplyGains(st.audio);
    renderBwfMixerPanel();
}

function _bwfMixerReset() {
    const st = _bwfMixerPanelState; if (!st) return;
    const pid = currentProjectId;
    if (!_bwfMixerSettings[pid]) _bwfMixerLoadAll(pid);
    _bwfMixerSettings[pid][st.bwfId] = {
        gains: Array(st.channels).fill(BWF_MIXER_DEFAULT_GAIN),
        mutes: Array(st.channels).fill(false),
        solos: Array(st.channels).fill(false),
    };
    _bwfMixerSave(pid);
    if (st.audio) _bwfMixerApplyGains(st.audio);
    renderBwfMixerPanel();
}

// Ouvre le panneau, positionné près du bouton qui l'a déclenché. Le lecteur
// principal et le viewer multicam ont chacun leur propre bouton 🎚 dans deux
// zones DOM différentes, mais le panneau lui-même est un unique élément
// partagé — un seul BWF joue à la fois.
function openBwfMixerPanel(anchorBtn) {
    const audio = (typeof _singleBwf !== 'undefined' && _singleBwf && _singleBwf.audio) ||
                  (typeof _mcView !== 'undefined' && _mcView && _mcView.bwfAudio) || null;
    if (!audio || !audio._bwfMixer) return;
    const m = audio._bwfMixer;
    _bwfMixerPanelState = {audio, bwfId: m.bwfId, channels: m.channels, trackNames: m.trackNames};
    renderBwfMixerPanel();
    const panel = document.getElementById('bwfMixerPanel');
    if (!panel) return;
    panel.style.display = 'block';
    if (anchorBtn) {
        const r = anchorBtn.getBoundingClientRect();
        const panelW = 260;
        const left = Math.max(8, Math.min(r.left, window.innerWidth - panelW - 12));
        panel.style.left = left + 'px';
        panel.style.top = Math.max(8, r.top - 8) + 'px';
        panel.style.transform = 'translateY(-100%)';
    }
}

function closeBwfMixerPanel() {
    const panel = document.getElementById('bwfMixerPanel');
    if (panel) panel.style.display = 'none';
    _bwfMixerPanelState = null;
}

function toggleBwfMixerPanel(e) {
    if (e) e.stopPropagation();
    const panel = document.getElementById('bwfMixerPanel');
    if (panel && panel.style.display === 'block') { closeBwfMixerPanel(); return; }
    openBwfMixerPanel(e ? e.currentTarget : null);
}

function renderBwfMixerPanel() {
    const st = _bwfMixerPanelState;
    const body = document.getElementById('bwfMixerRows');
    if (!body) return;
    if (!st) { body.innerHTML = ''; return; }
    const s = _bwfMixerGetSettings(st.bwfId, st.channels);
    const anySolo = s.solos.some(Boolean);
    body.innerHTML = '';
    for (let i = 0; i < st.channels; i++) {
        const rawName = (st.trackNames && st.trackNames[i]) || '';
        const name = rawName || `Piste ${i + 1}`;
        const pct = Math.round(s.gains[i] * 100);
        const muted = s.mutes[i] || (anySolo && !s.solos[i]);
        const row = document.createElement('div');
        row.style.cssText = 'margin-bottom:10px;';
        row.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px;">
                <span style="font-size:0.78em;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:150px;" title="${name.replace(/"/g, '&quot;')}">${name}</span>
                <span id="bwfMixPct_${i}" style="font-size:0.72em;color:var(--dim);font-family:monospace;">${pct}%</span>
            </div>
            <div style="display:flex;align-items:center;gap:6px;">
                <button class="bwf-mixer-btn${s.mutes[i] ? ' active' : ''}" onclick="_bwfMixerToggleMute(${i})" title="Couper cette piste">M</button>
                <button class="bwf-mixer-btn solo${s.solos[i] ? ' active' : ''}" onclick="_bwfMixerToggleSolo(${i})" title="Isoler cette piste">S</button>
                <input type="range" min="0" max="150" step="1" value="${pct}" oninput="_bwfMixerSetGain(${i}, this.value/100)" style="flex:1;${muted ? 'opacity:.4;' : ''}">
            </div>`;
        body.appendChild(row);
    }
}

function _bwfMixerUpdateRowUI(idx) {
    const st = _bwfMixerPanelState; if (!st) return;
    const s = _bwfMixerGetSettings(st.bwfId, st.channels);
    const el = document.getElementById(`bwfMixPct_${idx}`);
    if (el) el.textContent = Math.round(s.gains[idx] * 100) + '%';
}

// Ferme le panneau au clic en dehors (même pattern que #aspectMenu)
document.addEventListener('click', (e) => {
    const panel = document.getElementById('bwfMixerPanel');
    if (!panel || panel.style.display !== 'block') return;
    if (!e.target.closest('#bwfMixerPanel') && !e.target.closest('.bwf-mixer-trigger')) closeBwfMixerPanel();
});
