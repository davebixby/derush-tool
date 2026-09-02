// ─── LUT PREVIEW (WebGL2 + texture 3D, interpolation trilinéaire GPU) ────────
// Pleine résolution vidéo, zéro readback CPU. Le GPU fait la trilinéaire en hardware
// via gl.LINEAR sur la TEXTURE_3D. Sur Electron/Chromium ANGLE est fiable, donc
// pas de problème de drivers Windows (commentaire historique caduc).
//
// Module externalisé. Dépend des globals `clips`, `activeClip`, `currentProjectId`
// (définis dans le script inline principal — chargés AVANT ce fichier).
//
// ─── Modèle d'assignation (v0.3.5x) ──────────────────────────────────────────
// Chaque LUT chargée (.cube) est mémorisée dans une bibliothèque nommée par fichier
// (`_lutLibrary` en mémoire, contenu brut persisté dans IndexedDB pour survivre à un
// reload/relance — les .cube peuvent peser plusieurs Mo, hors budget raisonnable de
// localStorage). L'ASSIGNATION (quelle LUT + quels réglages pour quel plan) est un
// objet séparé et léger, `_lutAssign`, persisté dans localStorage par projet :
//   { cameras: { [camera]: {lutName, settings} },   // défaut hérité par tous les plans de cette caméra
//     clips:   { [clipId]:  {lutName, settings} } }  // override explicite propre à CE plan, prioritaire
// Résolution pour un plan (`_lutResolveFor`) : override clip explicite > défaut caméra > rien.
// Toucher un réglage (slider) sur un plan qui n'a encore qu'un défaut caméra "fork" un
// override clip (copie des réglages courants) SANS toucher au défaut caméra ni aux
// autres plans de cette caméra — c'est ce qui garantit que les réglages restent propres
// à chaque plan. Appliquer une LUT "à des caméras" n'écrit JAMAIS dans `clips` : un plan
// qui a déjà son propre override explicite n'est donc jamais écrasé par une application
// en masse malencontreuse (la modale de scope affiche d'ailleurs le nombre de plans
// "protégés" par caméra pour prévenir l'erreur avant qu'elle n'arrive).
let _lutEnabled = false;             // master toggle preview (session, pas persisté)
let _lutRaf = null;
let _lutGL = null;                   // {gl, prog, vao, videoTex, lutTex, u_*}
let _lut = null;                     // LUT actuellement uploadée en texture GL {size, data}
let _lutCurrentLutName = null;       // nom de la LUT actuellement uploadée (évite re-upload)
let _lutLibrary = {};                // lutName -> {size, data: Float32Array} (cache mémoire, session)
let _lutAssign = {cameras: {}, clips: {}};  // assignations persistées (voir doc ci-dessus)
let _lutPendingFile = null;          // {name, lutName} en attente de confirmation de scope
let _lutRefreshToken = 0;            // anti race-condition (clip switch pendant un await IndexedDB)
let _lutSettings = {intensity: 1.0, exposure: 0.0, saturation: 1.0, contrast: 0.0, temperature: 0.0, tint: 0.0};

const _LUT_NEUTRAL_SETTINGS = {intensity: 1.0, exposure: 0.0, saturation: 1.0, contrast: 0.0, temperature: 0.0, tint: 0.0};

// ─── IndexedDB : contenu brut des .cube (peut peser plusieurs Mo, hors budget localStorage) ──
function _lutDbOpen() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('derush_luts', 1);
        req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains('files')) db.createObjectStore('files', {keyPath: 'key'});
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}
async function _lutDbPut(pid, lutName, text) {
    try {
        const db = await _lutDbOpen();
        await new Promise((resolve, reject) => {
            const tx = db.transaction('files', 'readwrite');
            tx.objectStore('files').put({key: `${pid}::${lutName}`, pid, lutName, text});
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
        });
    } catch(e) { console.error('LUT: écriture IndexedDB échouée', e); }
}
async function _lutDbGet(pid, lutName) {
    try {
        const db = await _lutDbOpen();
        return await new Promise((resolve, reject) => {
            const tx = db.transaction('files', 'readonly');
            const req = tx.objectStore('files').get(`${pid}::${lutName}`);
            req.onsuccess = () => resolve(req.result ? req.result.text : null);
            req.onerror = () => reject(req.error);
        });
    } catch(e) { console.error('LUT: lecture IndexedDB échouée', e); return null; }
}

// ─── Assignations (localStorage, par projet) ─────────────────────────────────
function _lutLoadAssign(pid) {
    _lutAssign = {cameras: {}, clips: {}};
    try {
        const saved = localStorage.getItem('derush_lut_assign_' + pid);
        if (saved) _lutAssign = Object.assign({cameras: {}, clips: {}}, JSON.parse(saved));
    } catch(e) {}
}
function _lutPersistAssign() {
    if (!currentProjectId) return;
    try { localStorage.setItem('derush_lut_assign_' + currentProjectId, JSON.stringify(_lutAssign)); } catch(e) {}
}

// ─── Résolution : quelle LUT + réglages s'appliquent à ce plan ? ────────────
function _lutResolveFor(clip) {
    if (!clip) return null;
    const clipEntry = _lutAssign.clips[clip.id];
    if (clipEntry && clipEntry.lutName) return {lutName: clipEntry.lutName, settings: clipEntry.settings, scope: 'clip'};
    const camEntry = _lutAssign.cameras[clip.camera || ''];
    if (camEntry && camEntry.lutName) return {lutName: camEntry.lutName, settings: camEntry.settings, scope: 'camera'};
    return null;
}

// Fork paresseux : garantit un override clip éditable (créé depuis le défaut caméra
// courant si besoin), sans jamais muter l'objet de réglages partagé par la caméra.
function _lutEnsureEditableEntry() {
    if (!activeClip) return null;
    let entry = _lutAssign.clips[activeClip.id];
    if (entry && entry.lutName) return entry;
    const resolved = _lutResolveFor(activeClip);
    if (!resolved) return null;
    entry = {lutName: resolved.lutName, settings: {...resolved.settings}};
    _lutAssign.clips[activeClip.id] = entry;
    return entry;
}

function _lutSettingsSave() { /* conservé pour compat : les réglages sont maintenant persistés via _lutPersistAssign() */ }

function _lutSettingsUpdateUI() {
    const i = document.getElementById('lutIntensity'),
          e = document.getElementById('lutExposure'),
          s = document.getElementById('lutSaturation'),
          c = document.getElementById('lutContrast'),
          t = document.getElementById('lutTemperature'),
          n = document.getElementById('lutTint');
    if (i) i.value = _lutSettings.intensity;
    if (e) e.value = _lutSettings.exposure;
    if (s) s.value = _lutSettings.saturation;
    if (c) c.value = _lutSettings.contrast;
    if (t) t.value = _lutSettings.temperature;
    if (n) n.value = _lutSettings.tint;
    const iv = document.getElementById('lutIntensityVal'),
          ev = document.getElementById('lutExposureVal'),
          sv = document.getElementById('lutSaturationVal'),
          cv = document.getElementById('lutContrastVal'),
          tv = document.getElementById('lutTemperatureVal'),
          nv = document.getElementById('lutTintVal');
    if (iv) iv.textContent = Math.round(_lutSettings.intensity * 100) + '%';
    if (ev) ev.textContent = (_lutSettings.exposure >= 0 ? '+' : '') + _lutSettings.exposure.toFixed(2) + ' EV';
    if (sv) sv.textContent = Math.round(_lutSettings.saturation * 100) + '%';
    if (cv) cv.textContent = (_lutSettings.contrast >= 0 ? '+' : '') + Math.round(_lutSettings.contrast * 100) + '%';
    if (tv) tv.textContent = (_lutSettings.temperature >= 0 ? '+' : '') + Math.round(_lutSettings.temperature * 100);
    if (nv) nv.textContent = (_lutSettings.tint >= 0 ? '+' : '') + Math.round(_lutSettings.tint * 100);
}

function setLutSetting(key, value) {
    const entry = _lutEnsureEditableEntry();
    if (!entry) return;
    entry.settings[key] = parseFloat(value);
    _lutSettings = entry.settings;
    _lutSettingsUpdateUI();
    _lutApplySettings();
    _lutPersistAssign();
    _lutUpdateScopeInfo({lutName: entry.lutName, scope: 'clip'});
}

function resetLutSettings() {
    const entry = _lutEnsureEditableEntry();
    if (!entry) return;
    entry.settings = {..._LUT_NEUTRAL_SETTINGS};
    _lutSettings = entry.settings;
    _lutSettingsUpdateUI();
    _lutApplySettings();
    _lutPersistAssign();
    _lutUpdateScopeInfo({lutName: entry.lutName, scope: 'clip'});
}

function toggleLutSettingsPanel() {
    const p = document.getElementById('lutSettingsPanel');
    const isOpen = p.style.display === 'block';
    p.style.display = isOpen ? 'none' : 'block';
    if (!isOpen) _lutSettingsUpdateUI();
}

function _parseCube(text) {
    let size = 33; const vals = [];
    for(const line of text.split('\n')) {
        const t = line.trim();
        if(!t || t.startsWith('#')) continue;
        if(t.startsWith('LUT_3D_SIZE')) { size = parseInt(t.split(/\s+/)[1]); continue; }
        if(/^[A-Z_]/.test(t)) continue;
        const p = t.split(/\s+/).map(Number);
        if(p.length===3 && !isNaN(p[0])) vals.push(p[0],p[1],p[2]);
    }
    return { size, data: new Float32Array(vals) };
}

function _lutInitGL(canvas) {
    const gl = canvas.getContext('webgl2', {premultipliedAlpha: false, alpha: false, antialias: false});
    if (!gl) return null;

    const VS = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = vec2((a_pos.x + 1.0) * 0.5, 1.0 - (a_pos.y + 1.0) * 0.5);
    gl_Position = vec4(a_pos, 0.0, 1.0);
}`;
    const FS = `#version 300 es
precision highp float;
precision highp sampler3D;
uniform sampler2D u_video;
uniform sampler3D u_lut;
uniform float u_lutSize;
uniform float u_intensity;   // 0..1 mix entre source post-exposition et LUT
uniform float u_exposure;    // -2..+2 EV (1 EV = ×2)
uniform float u_saturation;  // 0..2 (1 = neutre)
uniform float u_contrast;    // -1..1, 0 = neutre, pivot sur le gris moyen (0.5)
uniform float u_temperature; // -1..1, négatif = froid (bleu), positif = chaud (orange)
uniform float u_tint;        // -1..1, négatif = vert, positif = magenta
uniform float u_time;        // varie par frame → dither animé (casse les patterns statiques)
in vec2 v_uv;
out vec4 outColor;

// Hash 2D → noise [0,1] uniform, sans pattern visible (IQ's classic)
float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

void main() {
    vec3 src = texture(u_video, v_uv).rgb;
    // 1. Exposition : multiplie par 2^EV (chaque stop double la lumière)
    src = src * pow(2.0, u_exposure);
    // 1b. Balance des couleurs (avant la LUT, comme une correction primaire) :
    // température = gain différentiel R/B (chaud = plus de rouge, moins de bleu),
    // teinte = gain sur G (positif = magenta = moins de vert, négatif = plus vert).
    src.r *= (1.0 + u_temperature * 0.3);
    src.b *= (1.0 - u_temperature * 0.3);
    src.g *= (1.0 - u_tint * 0.3);
    // 2. LUT lookup avec coordonnées centrées dans les voxels (évite biais 1/2 voxel)
    float s = u_lutSize;
    vec3 lutSrc = clamp(src, 0.0, 1.0);
    vec3 uvw = (lutSrc * (s - 1.0) + 0.5) / s;
    vec3 lutted = texture(u_lut, uvw).rgb;
    // 3. Intensité : mix entre src post-expo et LUT (0% = pas de LUT, 100% = LUT pleine)
    vec3 color = mix(src, lutted, u_intensity);
    // 4. Contraste : pivot sur le gris moyen (0.5), pente 1+u_contrast
    color = (color - 0.5) * (1.0 + u_contrast) + 0.5;
    // 5. Saturation : interpole vers le gris luma (Rec.709 coeffs)
    float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
    color = mix(vec3(luma), color, u_saturation);
    // 6. Dithering anti-banding : noise sub-pixel ±0.5/255 décorrélé par canal.
    // Le bruit varie chaque frame (u_time) → "film grain" doux, casse les bandes
    // visibles dans les ciels/dégradés sans perception consciente.
    vec2 fc = gl_FragCoord.xy;
    vec3 noise = vec3(
        hash21(fc + u_time),
        hash21(fc + u_time + 17.13),
        hash21(fc + u_time + 31.97)
    ) - 0.5;
    color += noise / 255.0;
    outColor = vec4(color, 1.0);
}`;

    function compile(type, src) {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
            console.error('Shader compile error', gl.getShaderInfoLog(s));
            return null;
        }
        return s;
    }
    const vs = compile(gl.VERTEX_SHADER, VS);
    const fs = compile(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) return null;
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.bindAttribLocation(prog, 0, 'a_pos');
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        console.error('Program link error', gl.getProgramInfoLog(prog));
        return null;
    }

    // Full-screen triangle (couvre tout le clip space sans triangle strip)
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1,  3, -1, -1,  3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    // Texture vidéo (sera mise à jour à chaque frame)
    const videoTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Texture LUT 3D (filtrage LINEAR = trilinéaire HW, le killer feature)
    const lutTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_3D, lutTex);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);

    gl.useProgram(prog);
    const u_video = gl.getUniformLocation(prog, 'u_video');
    const u_lut = gl.getUniformLocation(prog, 'u_lut');
    const u_lutSize = gl.getUniformLocation(prog, 'u_lutSize');
    const u_intensity = gl.getUniformLocation(prog, 'u_intensity');
    const u_exposure = gl.getUniformLocation(prog, 'u_exposure');
    const u_saturation = gl.getUniformLocation(prog, 'u_saturation');
    const u_contrast = gl.getUniformLocation(prog, 'u_contrast');
    const u_temperature = gl.getUniformLocation(prog, 'u_temperature');
    const u_tint = gl.getUniformLocation(prog, 'u_tint');
    const u_time = gl.getUniformLocation(prog, 'u_time');
    gl.uniform1i(u_video, 0);
    gl.uniform1i(u_lut, 1);
    // Valeurs par défaut neutres (= LUT pur, pas d'ajustement)
    gl.uniform1f(u_intensity, 1.0);
    gl.uniform1f(u_exposure, 0.0);
    gl.uniform1f(u_saturation, 1.0);
    gl.uniform1f(u_contrast, 0.0);
    gl.uniform1f(u_temperature, 0.0);
    gl.uniform1f(u_tint, 0.0);
    gl.uniform1f(u_time, 0.0);

    return {gl, prog, vao, videoTex, lutTex, u_lutSize, u_intensity, u_exposure, u_saturation, u_contrast, u_temperature, u_tint, u_time, lutUploaded: false};
}

function _lutApplySettings() {
    if (!_lutGL || !_lutSettings) return;
    const {gl, u_intensity, u_exposure, u_saturation, u_contrast, u_temperature, u_tint} = _lutGL;
    gl.useProgram(_lutGL.prog);
    gl.uniform1f(u_intensity, _lutSettings.intensity);
    gl.uniform1f(u_exposure, _lutSettings.exposure);
    gl.uniform1f(u_saturation, _lutSettings.saturation);
    gl.uniform1f(u_contrast, _lutSettings.contrast);
    gl.uniform1f(u_temperature, _lutSettings.temperature);
    gl.uniform1f(u_tint, _lutSettings.tint);
}

function _lutUploadLUT() {
    if (!_lutGL || !_lut) return;
    const {gl, lutTex, u_lutSize} = _lutGL;
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_3D, lutTex);
    // Upload comme float 3D texture (RGB16F). Trilinéaire gratuite via LINEAR.
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB16F, _lut.size, _lut.size, _lut.size,
                  0, gl.RGB, gl.FLOAT, _lut.data);
    gl.uniform1f(u_lutSize, _lut.size);
    _lutGL.lutUploaded = true;
}

function _renderLUT() {
    _lutRaf = null;
    if (!_lutEnabled || !_lut || !_lutGL) return;
    _lutRaf = requestAnimationFrame(_renderLUT);
    const v = document.getElementById('player');
    if (!v || v.readyState < 2 || !v.videoWidth) return;
    const c = document.getElementById('lutCanvas');
    const w = v.videoWidth, h = v.videoHeight;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const {gl, videoTex, u_time} = _lutGL;
    gl.viewport(0, 0, w, h);
    // Met à jour le seed du dither chaque frame → bruit décorrélé temporel = casse pattern visible
    gl.uniform1f(u_time, (performance.now() * 0.001) % 1000.0);
    // Upload frame courante en sampler2D (UNSIGNED_BYTE sRGB → bilinéaire HW)
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    try {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, v);
    } catch (e) {
        // CORS ou frame pas prête — silencieux, on retentera au prochain RAF
        return;
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
}

// Charge (parse) une LUT nommée si besoin — depuis le cache mémoire de la session,
// sinon depuis IndexedDB (persistance cross-reload). Retourne null si introuvable.
async function _lutEnsureLoaded(lutName) {
    if (_lutLibrary[lutName]) return _lutLibrary[lutName];
    if (!currentProjectId) return null;
    const text = await _lutDbGet(currentProjectId, lutName);
    if (!text) return null;
    const parsed = _parseCube(text);
    _lutLibrary[lutName] = parsed;
    return parsed;
}

function onLUTFileSelected(e) {
    const file = e.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
        const text = ev.target.result;
        const parsed = _parseCube(text);
        if (!_lutGL) _lutGL = _lutInitGL(document.getElementById('lutCanvas'));
        if (!_lutGL) { alert("WebGL2 non disponible — le rendu LUT a besoin de WebGL2."); return; }
        const lutName = file.name;
        _lutLibrary[lutName] = parsed;
        if (currentProjectId) _lutDbPut(currentProjectId, lutName, text);  // fire-and-forget
        _lutPendingFile = {name: file.name, lutName};
        _openLutScopeModal();
    };
    reader.readAsText(file);
    e.target.value = '';  // permet de recharger la même LUT
}

function _openLutScopeModal() {
    // Liste les caméras uniques du projet (alpha-trié), avec indication de ce qui est
    // déjà assigné (LUT courante + nombre de plans "protégés" par un override propre)
    // pour prévenir une application en masse malencontreuse.
    const cams = Array.from(new Set(clips.map(c => c.camera || '').filter(Boolean))).sort();
    const wrap = document.getElementById('lutScopeCameras');
    wrap.innerHTML = cams.map(cam => {
        const preChecked = cam.toUpperCase().includes('FS5');  // pré-coche FS5 par défaut (log → besoin LUT)
        const current = _lutAssign.cameras[cam];
        const protectedCount = clips.filter(c => (c.camera||'') === cam
            && _lutAssign.clips[c.id] && _lutAssign.clips[c.id].lutName).length;
        let info = '';
        if (current) info += ` <span style="color:var(--dim);">— actuellement ${current.lutName}</span>`;
        if (protectedCount > 0) info += ` <span style="color:#f59e0b;">🔒 ${protectedCount} plan(s) propre(s), non affecté(s)</span>`;
        return `<label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="checkbox" class="lutScopeCam" value="${cam}" ${preChecked ? 'checked' : ''} style="width:auto;margin:0;">
            <span>📷 ${cam}${info}</span>
        </label>`;
    }).join('') || '<span style="color:var(--dim);font-size:0.85em;">Aucune caméra détectée dans ce projet.</span>';

    document.getElementById('lutScopeFile').textContent = _lutPendingFile ? _lutPendingFile.name : '';
    const clipWarn = document.getElementById('lutScopeClipWarn');
    if (clipWarn) {
        const existing = activeClip && _lutAssign.clips[activeClip.id];
        clipWarn.textContent = existing && existing.lutName
            ? `⚠️ Ce plan a déjà sa propre LUT (${existing.lutName}) — sera remplacée.`
            : '';
    }
    document.getElementById('lutScopeRadioCameras').checked = true;
    document.getElementById('lutScopeModal').style.display = 'flex';
    _lutScopeModeChanged();
}

function _lutScopeModeChanged() {
    // Grise la liste des caméras quand "Ce rush uniquement" est sélectionné, pour ne
    // pas laisser croire que les cases cochées (ex. FS5 pré-cochée par défaut) seront
    // aussi affectées — confirmLutScope() les ignore déjà dans ce mode, mais rien ne
    // le montrait visuellement (retour terrain 31/08/2026).
    const isClipMode = document.getElementById('lutScopeRadioClip').checked;
    const wrap = document.getElementById('lutScopeCameras');
    wrap.style.opacity = isClipMode ? '0.4' : '1';
    wrap.querySelectorAll('.lutScopeCam').forEach(cb => { cb.disabled = isClipMode; });
}

function closeLutScopeModal() {
    document.getElementById('lutScopeModal').style.display = 'none';
}

function confirmLutScope() {
    const mode = document.querySelector('input[name="lutScopeMode"]:checked').value;
    const lutName = _lutPendingFile.lutName;
    if (mode === 'cameras') {
        const cams = Array.from(document.querySelectorAll('.lutScopeCam:checked')).map(cb => cb.value);
        if (!cams.length) { alert('Sélectionne au moins une caméra (ou choisis "Ce rush uniquement").'); return; }
        // N'écrit QUE le défaut caméra — ne touche jamais _lutAssign.clips, donc les
        // plans qui ont déjà leur propre override gardent leur LUT/réglages intacts.
        cams.forEach(cam => { _lutAssign.cameras[cam] = {lutName, settings: {..._LUT_NEUTRAL_SETTINGS}}; });
    } else {
        if (!activeClip) { alert('Aucun rush sélectionné.'); return; }
        _lutAssign.clips[activeClip.id] = {lutName, settings: {..._LUT_NEUTRAL_SETTINGS}};
    }
    _lutPersistAssign();
    closeLutScopeModal();
    _lutEnabled = true;
    _lutRefreshForActiveClip();
}

function toggleLUT() {
    _lutEnabled = !_lutEnabled;
    _lutRefreshForActiveClip();
}

function _lutUpdateBtnVisual(resolved) {
    const btn = document.getElementById('lutBtn');
    if (!btn) return;
    btn.classList.remove('lut-on', 'lut-off');
    if (!resolved) { btn.style.display = 'none'; return; }
    btn.style.display = '';
    btn.classList.add(_lutEnabled ? 'lut-on' : 'lut-off');
}

function _lutUpdateScopeInfo(resolved) {
    const wrap = document.getElementById('lutRemoveWrap');
    const info = document.getElementById('lutScopeInfo');
    const btn = document.getElementById('lutRemoveBtn');
    if (!wrap || !info || !btn) return;
    if (!resolved) { wrap.style.display = 'none'; return; }
    wrap.style.display = 'block';
    if (resolved.scope === 'clip') {
        info.textContent = `🔒 LUT propre à ce plan (${resolved.lutName})`;
        btn.style.display = '';
    } else {
        info.textContent = `📷 LUT héritée de la caméra (${resolved.lutName})`;
        btn.style.display = 'none';
    }
}

// "Annule" une LUT propre à ce plan (créée via "Ce rush uniquement" ou forkée au
// premier réglage manuel touché) — le plan retombe sur le défaut caméra s'il existe.
function _lutRemoveForActiveClip() {
    if (!activeClip || !_lutAssign.clips[activeClip.id]) return;
    delete _lutAssign.clips[activeClip.id];
    _lutPersistAssign();
    _lutRefreshForActiveClip();
}

// Ré-évalue et applique la LUT du plan actif (changement de clip, toggle master,
// nouvelle assignation…). Async car le contenu de la LUT peut devoir être relu
// depuis IndexedDB — protégé par un token contre un changement de clip pendant l'attente.
async function _lutRefreshForActiveClip() {
    const token = ++_lutRefreshToken;
    const clipAtCall = activeClip;
    const c = document.getElementById('lutCanvas');
    const badge = document.getElementById('lutBadge');
    const panel = document.getElementById('lutSettingsPanel');

    const resolved = _lutResolveFor(clipAtCall);
    if (!resolved) {
        if (c) c.style.display = 'none';
        if (badge) badge.style.display = 'none';
        if (panel) panel.style.display = 'none';
        _lutUpdateBtnVisual(null);
        _lutUpdateScopeInfo(null);
        if (_lutRaf) { cancelAnimationFrame(_lutRaf); _lutRaf = null; }
        return;
    }

    const parsed = await _lutEnsureLoaded(resolved.lutName);
    if (token !== _lutRefreshToken || activeClip !== clipAtCall) return;  // stale (clip changé entre temps)
    if (!parsed) {
        if (c) c.style.display = 'none';
        if (badge) badge.style.display = 'none';
        if (panel) panel.style.display = 'none';
        _lutUpdateBtnVisual(null);
        _lutUpdateScopeInfo(null);
        return;
    }

    if (!_lutGL) _lutGL = _lutInitGL(c);
    if (!_lutGL) return;
    if (_lutCurrentLutName !== resolved.lutName) {
        _lut = parsed;
        _lutUploadLUT();
        _lutCurrentLutName = resolved.lutName;
    }
    _lutSettings = resolved.settings;
    _lutApplySettings();

    const shouldRender = _lutEnabled;
    if (c) c.style.display = shouldRender ? 'block' : 'none';
    if (badge) badge.style.display = shouldRender ? 'block' : 'none';
    if (panel) {
        panel.style.display = shouldRender ? 'block' : 'none';
        if (shouldRender) _lutSettingsUpdateUI();
    }
    _lutUpdateBtnVisual(resolved);
    _lutUpdateScopeInfo(resolved);

    if (shouldRender) {
        if (_lutRaf) cancelAnimationFrame(_lutRaf);
        _renderLUT();
    } else {
        if (_lutRaf) { cancelAnimationFrame(_lutRaf); _lutRaf = null; }
    }
}
