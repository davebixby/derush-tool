// ─── LUT PREVIEW (WebGL2 + texture 3D, interpolation trilinéaire GPU) ────────
// Pleine résolution vidéo, zéro readback CPU. Le GPU fait la trilinéaire en hardware
// via gl.LINEAR sur la TEXTURE_3D. Sur Electron/Chromium ANGLE est fiable, donc
// pas de problème de drivers Windows (commentaire historique caduc).
//
// Module externalisé. Dépend des globals `clips`, `activeClip` (définis dans le
// script inline principal — chargés AVANT ce fichier).
let _lut = null;                     // {size, data: Float32Array(size³*3)}
let _lutEnabled = false;             // master toggle
let _lutRaf = null;
let _lutGL = null;                   // {gl, prog, vao, videoTex, lutTex, u_*}
let _lutScope = null;                // {mode:'cameras'|'clip', cameras:[], clip_id:''}
let _lutPendingFile = null;          // nom du fichier en attente de scope
let _lutSettings = {intensity: 1.0, exposure: 0.0, saturation: 1.0};

// Restaure le scope + settings depuis localStorage au démarrage
try {
    const saved = localStorage.getItem('derush_lut_scope');
    if (saved) _lutScope = JSON.parse(saved);
    const savedSet = localStorage.getItem('derush_lut_settings');
    if (savedSet) _lutSettings = {..._lutSettings, ...JSON.parse(savedSet)};
} catch(e) {}

function _lutSettingsSave() {
    try { localStorage.setItem('derush_lut_settings', JSON.stringify(_lutSettings)); } catch(e) {}
}

function _lutSettingsUpdateUI() {
    const i = document.getElementById('lutIntensity'),
          e = document.getElementById('lutExposure'),
          s = document.getElementById('lutSaturation');
    if (i) i.value = _lutSettings.intensity;
    if (e) e.value = _lutSettings.exposure;
    if (s) s.value = _lutSettings.saturation;
    const iv = document.getElementById('lutIntensityVal'),
          ev = document.getElementById('lutExposureVal'),
          sv = document.getElementById('lutSaturationVal');
    if (iv) iv.textContent = Math.round(_lutSettings.intensity * 100) + '%';
    if (ev) ev.textContent = (_lutSettings.exposure >= 0 ? '+' : '') + _lutSettings.exposure.toFixed(2) + ' EV';
    if (sv) sv.textContent = Math.round(_lutSettings.saturation * 100) + '%';
}

function setLutSetting(key, value) {
    _lutSettings[key] = parseFloat(value);
    _lutSettingsUpdateUI();
    _lutApplySettings();
    _lutSettingsSave();
}

function resetLutSettings() {
    _lutSettings = {intensity: 1.0, exposure: 0.0, saturation: 1.0};
    _lutSettingsUpdateUI();
    _lutApplySettings();
    _lutSettingsSave();
}

function toggleLutSettingsPanel() {
    const p = document.getElementById('lutSettingsPanel');
    const isOpen = p.style.display === 'block';
    p.style.display = isOpen ? 'none' : 'block';
    if (!isOpen) _lutSettingsUpdateUI();
}

function _lutClipMatchesScope(clip) {
    if (!clip || !_lutScope) return false;
    if (_lutScope.mode === 'clip')    return clip.id === _lutScope.clip_id;
    if (_lutScope.mode === 'cameras') return (_lutScope.cameras || []).includes(clip.camera || '');
    return false;
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
    // 2. LUT lookup avec coordonnées centrées dans les voxels (évite biais 1/2 voxel)
    float s = u_lutSize;
    vec3 lutSrc = clamp(src, 0.0, 1.0);
    vec3 uvw = (lutSrc * (s - 1.0) + 0.5) / s;
    vec3 lutted = texture(u_lut, uvw).rgb;
    // 3. Intensité : mix entre src post-expo et LUT (0% = pas de LUT, 100% = LUT pleine)
    vec3 color = mix(src, lutted, u_intensity);
    // 4. Saturation : interpole vers le gris luma (Rec.709 coeffs)
    float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
    color = mix(vec3(luma), color, u_saturation);
    // 5. Dithering anti-banding : noise sub-pixel ±0.5/255 décorrélé par canal.
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
    const u_time = gl.getUniformLocation(prog, 'u_time');
    gl.uniform1i(u_video, 0);
    gl.uniform1i(u_lut, 1);
    // Valeurs par défaut neutres (= LUT pur, pas d'ajustement)
    gl.uniform1f(u_intensity, 1.0);
    gl.uniform1f(u_exposure, 0.0);
    gl.uniform1f(u_saturation, 1.0);
    gl.uniform1f(u_time, 0.0);

    return {gl, prog, vao, videoTex, lutTex, u_lutSize, u_intensity, u_exposure, u_saturation, u_time, lutUploaded: false};
}

function _lutApplySettings() {
    if (!_lutGL || !_lutSettings) return;
    const {gl, u_intensity, u_exposure, u_saturation} = _lutGL;
    gl.useProgram(_lutGL.prog);
    gl.uniform1f(u_intensity, _lutSettings.intensity);
    gl.uniform1f(u_exposure, _lutSettings.exposure);
    gl.uniform1f(u_saturation, _lutSettings.saturation);
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

function onLUTFileSelected(e) {
    const file = e.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
        _lut = _parseCube(ev.target.result);
        if (!_lutGL) _lutGL = _lutInitGL(document.getElementById('lutCanvas'));
        if (!_lutGL) { alert("WebGL2 non disponible — le rendu LUT a besoin de WebGL2."); return; }
        _lutUploadLUT();
        _lutPendingFile = file.name;
        _openLutScopeModal();
    };
    reader.readAsText(file);
    e.target.value = '';  // permet de recharger la même LUT
}

function _openLutScopeModal() {
    // Liste les caméras uniques du projet (alpha-trié)
    const cams = Array.from(new Set(clips.map(c => c.camera || '').filter(Boolean))).sort();
    const wrap = document.getElementById('lutScopeCameras');
    wrap.innerHTML = cams.map(cam => {
        const preChecked = (_lutScope && _lutScope.mode === 'cameras' && (_lutScope.cameras||[]).includes(cam))
            || (cam.toUpperCase().includes('FS5'));  // pré-coche FS5 par défaut (log → besoin LUT)
        return `<label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="checkbox" class="lutScopeCam" value="${cam}" ${preChecked ? 'checked' : ''} style="width:auto;margin:0;">
            <span>📷 ${cam}</span>
        </label>`;
    }).join('') || '<span style="color:var(--dim);font-size:0.85em;">Aucune caméra détectée dans ce projet.</span>';

    document.getElementById('lutScopeFile').textContent = _lutPendingFile || '';
    // Sélectionne le bon radio selon scope persisté
    if (_lutScope && _lutScope.mode === 'clip') {
        document.getElementById('lutScopeRadioClip').checked = true;
    } else {
        document.getElementById('lutScopeRadioCameras').checked = true;
    }
    document.getElementById('lutScopeModal').style.display = 'flex';
}

function closeLutScopeModal() {
    document.getElementById('lutScopeModal').style.display = 'none';
}

function confirmLutScope() {
    const mode = document.querySelector('input[name="lutScopeMode"]:checked').value;
    if (mode === 'cameras') {
        const cams = Array.from(document.querySelectorAll('.lutScopeCam:checked')).map(cb => cb.value);
        if (!cams.length) { alert('Sélectionne au moins une caméra (ou choisis "Ce rush uniquement").'); return; }
        _lutScope = {mode: 'cameras', cameras: cams};
    } else {
        if (!activeClip) { alert('Aucun rush sélectionné.'); return; }
        _lutScope = {mode: 'clip', clip_id: activeClip.id};
    }
    try { localStorage.setItem('derush_lut_scope', JSON.stringify(_lutScope)); } catch(e) {}
    closeLutScopeModal();
    document.getElementById('lutBtn').style.display = '';
    enableLUT(true);
}

function toggleLUT() {
    // Si pas de scope ou pas de match → ne rien faire (visuel "not-applicable" déjà clair)
    enableLUT(!_lutEnabled);
}

function _updateLutBtnVisual() {
    const btn = document.getElementById('lutBtn');
    if (!btn) return;
    btn.classList.remove('lut-on', 'lut-off', 'lut-not-applicable');
    if (!_lut) { btn.style.display = 'none'; return; }
    const matches = _lutClipMatchesScope(activeClip);
    if (!_lutEnabled) btn.classList.add('lut-off');
    else if (!matches) btn.classList.add('lut-not-applicable');
    else btn.classList.add('lut-on');
}

function enableLUT(on) {
    _lutEnabled = on;
    const c = document.getElementById('lutCanvas');
    const badge = document.getElementById('lutBadge');
    // Le canvas ne s'affiche QUE si master ON ET clip dans le scope
    const shouldRender = on && _lut && _lutClipMatchesScope(activeClip);
    c.style.display = shouldRender ? 'block' : 'none';
    if (badge) badge.style.display = shouldRender ? 'block' : 'none';
    _updateLutBtnVisual();
    // Panneau réglages : auto-visible quand LUT actif sur ce clip, masqué sinon
    const p = document.getElementById('lutSettingsPanel');
    if (p) {
        p.style.display = shouldRender ? 'block' : 'none';
        if (shouldRender) _lutSettingsUpdateUI();
    }
    if (shouldRender) {
        _lutApplySettings();  // re-push uniforms au cas où on a switché clip
        if (_lutRaf) cancelAnimationFrame(_lutRaf);
        _renderLUT();
    } else {
        if (_lutRaf) { cancelAnimationFrame(_lutRaf); _lutRaf = null; }
    }
}
