"""derush_exports — fonctions d'export de Derush Tool.

FCPXML, XML Premiere (FCP7), sous-clips, rough-cut, rapport HTML, EDL, CSV.
Extrait de derush_server.py le 22 mai 2026 (audit §4 — découpage du monolithe,
étape 2). derush_server les ré-importe ; tous les appels existants restent valides.
"""
import csv
import io
import xml.etree.ElementTree as ET
from datetime import datetime

from derush_core import (tc_to_seconds, seconds_to_tc, seconds_to_rational,
                         user_note_key)


def _chrono_sort_clips(clips):
    """Trie les clips par (jour, heure réelle de tournage) — mélange les caméras
    au sein d'une même journée, comme le mode de tri "heure" de la sidebar
    (`_clipTimeOfDay`/`_clipSortMode==='time'`, derush_app.html).

    Sans ce tri, les timelines de selects (FCPXML/XML Premiere/Markers EDL)
    gardent l'ordre brut du scan (`project['clips']`) : les jours sont dans le
    bon ordre, mais À L'INTÉRIEUR d'un jour multicam, toutes les FS5 sont
    listées avant toutes les FX6 (ordre de découverte des dossiers caméra),
    pas par heure réelle — un plan FX6 de 11h peut se retrouver après un plan
    FS5 de 17h du même jour, donnant l'impression que la timeline "mélange les
    jours" (retour terrain sept. 2026, alors que les jours eux-mêmes sont
    strictement ordonnés).

    Heure réelle = `ltc_tc_in_sec` si décodé (FS5), sinon `tc_in` brut converti
    via le fps du clip — même priorité que `_clip_asset_tc_sec`.
    """
    def _key(c):
        ltc = c.get('ltc_tc_in_sec')
        t = ltc if ltc is not None else (tc_to_seconds(c.get('tc_in', ''), round(c.get('fps', 25))) or 0)
        return (c.get('day', ''), t)
    return sorted(clips, key=_key)


def _clip_asset_tc_sec(clip, fps):
    """TC de départ à utiliser dans les exports NLE (<asset start>, TC source EDL).

    Priorise clip['ltc_tc_in_sec'] (décodé depuis la piste audio LTC) quand
    disponible, sinon repli sur le tag TC brut ffprobe/MXF (clip['tc_in']).

    Historique (piège CLAUDE.md #37) — deux tentatives précédentes, deux échecs,
    mais tous les deux confondus par un facteur qu'on n'a identifié qu'après coup :
      - v0.3.85 : Media Pool pas corrigé en amont → rejet massif ("timecode
        extents").
      - v0.3.87 : Media Pool corrigé en amont MAIS **Media Pool incomplet**
        (médias de certains jours/caméras jamais importés dans DaVinci) → log
        DaVinci ("timecode extents do not match any clip in the Media Pool")
        confondait deux causes bien distinctes : un clip absent du Media Pool
        ET un vrai désaccord de TC sur un clip présent. Un clip GoPro jamais
        touché par le LTC (`GX010155.MP4`) a échoué exactement pareil que les
        FS5 — preuve que le Media Pool incomplet était (au moins en partie) la
        vraie cause, pas la précision du LTC. Revert en v0.3.88, puis restauré
        ici en v0.3.89 pour retester dans des conditions propres (Media Pool
        complet, export régénéré après coup) avant de trancher définitivement.
    Précondition inchangée : le Media Pool DaVinci doit être corrigé à la même
    valeur AVANT l'import (voir § Workflow FS5). Si des échecs persistent une
    fois le Media Pool complet vérifié, ce sera enfin un signal fiable sur le
    vrai taux d'échec de cette approche — pas avant.
    """
    ltc = clip.get('ltc_tc_in_sec')
    if ltc is not None:
        return ltc
    return tc_to_seconds(clip.get('tc_in', ''), fps) or 0


# ─────────────────────────────────────────────────────────────────────────
# Export AAF multipiste (image + son caméra + son ingé par micro, canaux
# séparés) — remplace le FCPXML pour les timelines de selects depuis sept.
# 2026 : le FCPXML ne peut représenter qu'UNE seule piste son par clip, alors
# que le vrai besoin (retour terrain) est une piste par micro d'ingé son.
#
# Technique validée sur DRIFT_CLUB (voir D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md
# §14-20 pour le récit complet des impasses et de la résolution) :
#   - chaque piste (image, son caméra, chaque canal d'un WAV d'ingé son) est un
#     MasterMob séparé, portant SA PROPRE piste Timecode explicite au vrai TC
#     source (condition sine qua non pour que DaVinci rattache le clip aux
#     médias déjà présents dans son Media Pool, sans le réimporter en double —
#     voir §18-19) et un nom de mob STRICTEMENT identique au nom du fichier ;
#   - le mob "réel" (celui qui porte le Locator vers le fichier) est référencé
#     DIRECTEMENT par chaque MasterMob, jamais via un TapeMob intercalé (§14) ;
#   - ContainerFormat DOIT être "AAFKLV" (`f.dictionary.lookup_containerdef`),
#     jamais "AAF" (GUID différent, sans effet) ni le vrai GUID du codec/codec
#     conteneur natif (fait planter DaVinci — §14) ;
#   - le WAV réel est un `PCMDescriptor` (pas `WAVEDescriptor`), ses slots sont
#     à l'edit rate DE LA TIMELINE (pas la fréquence d'échantillonnage audio),
#     et la longueur du SourceClip de chaque slot est en frames à ce fps (pas
#     en échantillons) — piège trouvé en comparant à un export DaVinci réel
#     (§20). Les valeurs numériques du descriptor (bit depth, etc.) n'ont pas
#     besoin d'être exactes, DaVinci relit le fichier réel via son Locator.
#
# ⚠️ CONTRAINTE D'USAGE NON NÉGOCIABLE (à répercuter dans le mode d'emploi
# utilisateur) : l'import de ce fichier dans DaVinci doit TOUJOURS se faire
# via le menu manuel `File > Import > Timeline` (case "Automatically import
# source clips into media pool" décochée) — l'API de scripting de DaVinci
# (`Timeline.ImportIntoTimeline`) ne déclenche jamais ce mécanisme de
# rattachement, quelles que soient les options passées (§18).
# ─────────────────────────────────────────────────────────────────────────

def _aaf_locator(f, path):
    """NetworkLocator vers un fichier réel sur disque (file:/// URI)."""
    import pathlib
    n = f.create.NetworkLocator()
    n['URLString'].value = pathlib.Path(path).as_uri()
    return n


def _aaf_add_tc_slot(f, mob, fps, start_frames, length_frames, slot_id=10):
    """Piste Timecode explicite sur un MasterMob, au vrai TC source — condition
    sine qua non du rattachement sans doublon (voir en-tête de section)."""
    tc_slot = mob.create_timeline_slot(edit_rate=fps, slot_id=slot_id)
    tc_slot.segment = f.create.Timecode(fps=fps, length=length_frames)
    tc_slot.segment.start = int(round(start_frames))
    return tc_slot


def _aaf_camera_sound_channel(camera, day):
    """Numéro du canal caméra RÉELLEMENT porteur du micro (par opposition au
    LTC, qui n'est pas du son exploitable) — mêmes règles que le nettoyage
    du Media Pool (voir la correction "canaux mal rangés" du même jour) :
      - FX6 : canal 1 (canal 1 ET 2 sont tous deux du vrai micro stéréo,
        canal 1 suffit pour une piste "son caméra" mono) ;
      - FS5 : dépend du jour — le LTC occupe le canal 2 sur J02-J05 (micro
        réel = canal 1), et le canal 1 sur J07/J10/J11 (micro réel = canal 2)
        — sans ça, `_aaf_build_video_real_mob` exposait toujours un canal
        "sound" générique sans indication de piste physique, et DaVinci
        pouvait résoudre ça sur le LTC plutôt que le micro selon le jour
        (silence/bourdonnement constaté sur les FS5 du jour 11 — retour
        terrain sept. 2026) ;
      - autre (GoPro, inconnu) : canal 1 par défaut, pas de LTC documenté."""
    if camera == 'FS5':
        day_code = (day or '').split('_')[0]
        if day_code in ('J07', 'J10', 'J11'):
            return 2
        return 1
    return 1


def _aaf_build_video_real_mob(f, filename, path, width, height, fps, total_frames, sound_channel=1):
    """Mob "réel" vidéo : CDCIDescriptor générique (ContainerFormat=AAFKLV,
    jamais le vrai codec — voir en-tête), slots Picture(1)/Sound(2) "morts"
    (aucune référence plus bas, pas de TapeMob intercalé). `sound_channel`
    (voir `_aaf_camera_sound_channel`) est posé comme `PhysicalTrackNumber`
    du slot Sound pour indiquer à DaVinci quel canal RÉEL du fichier exposer
    (sans ça, la résolution du canal réel se fait à l'aveugle côté DaVinci)."""
    real = f.create.SourceMob()
    real.name = filename
    pic_slot = real.create_timeline_slot(edit_rate=fps, slot_id=1)
    pic_clip = f.create.SourceClip(media_kind="picture")
    pic_clip.length = total_frames
    pic_slot.segment = pic_clip
    snd_slot = real.create_timeline_slot(edit_rate=fps, slot_id=2)
    snd_slot['PhysicalTrackNumber'].value = sound_channel
    snd_clip = f.create.SourceClip(media_kind="sound")
    snd_clip.length = total_frames
    snd_slot.segment = snd_clip

    desc = f.create.CDCIDescriptor()
    desc['ComponentWidth'].value = 8
    desc['HorizontalSubsampling'].value = 2
    desc['FrameLayout'].value = 'FullFrame'
    desc['VideoLineMap'].value = [0, 1]
    desc['ImageAspectRatio'].value = f"{width}/{height}"
    desc['StoredWidth'].value = width
    desc['StoredHeight'].value = height
    desc['SampleRate'].value = fps
    desc['Length'].value = total_frames
    desc['FrameSampleSize'].value = width * height * 2
    desc['ContainerFormat'].value = f.dictionary.lookup_containerdef("AAFKLV")
    desc['Locator'].append(_aaf_locator(f, path))
    real.descriptor = desc
    f.content.mobs.append(real)
    return real


def _aaf_build_video_masters(f, video_real, filename, fps, total_frames, tc_start_frames, sound_channel=1):
    """MasterMob image + MasterMob son caméra, chacun avec sa propre piste TC
    explicite (même vrai TC pour les deux, c'est le même fichier physique).
    `sound_channel` reposé ici aussi (PhysicalTrackNumber du slot exposé par
    le MasterMob lui-même, pas seulement sur le mob réel en dessous) — sans
    certitude totale sur lequel des deux DaVinci consulte pour résoudre le
    canal réel, autant poser la même valeur aux deux endroits."""
    pic_master = f.create.MasterMob()
    pic_master.name = filename
    _aaf_add_tc_slot(f, pic_master, fps, tc_start_frames, total_frames)
    p_slot = pic_master.create_timeline_slot(edit_rate=fps, slot_id=1)
    p_slot.segment = video_real.create_source_clip(slot_id=1, length=total_frames, media_kind="picture")
    f.content.mobs.append(pic_master)

    cam_master = f.create.MasterMob()
    cam_master.name = filename
    _aaf_add_tc_slot(f, cam_master, fps, tc_start_frames, total_frames)
    c_slot = cam_master.create_timeline_slot(edit_rate=fps, slot_id=1)
    c_slot['PhysicalTrackNumber'].value = sound_channel
    c_slot.segment = video_real.create_source_clip(slot_id=2, length=total_frames, media_kind="sound")
    f.content.mobs.append(cam_master)

    return pic_master, cam_master


def _wav_header(path):
    """Lit canaux / bits / fréquence réels d'un WAV. `None` si illisible. Gère
    aussi les WAV > 4 Go / RF64 (le module `wave` stdlib les rejette) via une
    lecture manuelle du chunk `fmt `. Utilisé pour que le PCMDescriptor de
    l'AAF ne se contredise jamais lui-même (retour terrain sept. 2026, audit
    externe — voir D:\\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md §21/22 : un
    descriptor annonçant 1 canal quel que soit le nombre réel de canaux du
    fichier BWF était une incohérence interne systématique de l'AAF)."""
    import wave
    try:
        with wave.open(path, 'rb') as w:
            return {'channels': w.getnchannels(), 'sampwidth': w.getsampwidth(),
                    'framerate': w.getframerate()}
    except Exception:
        pass
    try:
        with open(path, 'rb') as fh:
            head = fh.read(12)
            if head[:4] not in (b'RIFF', b'RF64'):
                return None
            while True:
                hdr = fh.read(8)
                if len(hdr) < 8:
                    return None
                cid, size = hdr[:4], int.from_bytes(hdr[4:8], 'little')
                if cid == b'fmt ':
                    data = fh.read(size)
                    ch = int.from_bytes(data[2:4], 'little')
                    rate = int.from_bytes(data[4:8], 'little')
                    bits = int.from_bytes(data[14:16], 'little')
                    return {'channels': ch, 'sampwidth': bits // 8, 'framerate': rate}
                fh.seek(size + (size & 1), 1)
    except Exception:
        return None


def _aaf_build_bwf_real_mob(f, filename, path, channels, total_frames_seq_fps, total_samples):
    """Mob "réel" son ingé : un slot par canal EXPOSÉ (`channels`, qui peut être
    inférieur au nombre réel de canaux du fichier — on n'expose aujourd'hui que
    le canal 1, voir le repli documenté plus haut) à l'edit rate DE LA
    TIMELINE. Le `PCMDescriptor` reflète les vraies caractéristiques du
    fichier lues sur disque (fréquence, profondeur), mais son `Channels`
    correspond au nombre de SLOTS RÉELLEMENT DÉCLARÉS ici (`channels`), pas au
    nombre de canaux réel du fichier physique — sans ça, le fichier se
    contredirait lui-même (annoncer plus de canaux que ce qu'il expose
    vraiment), ce qu'un audit externe a identifié comme une incohérence
    interne systématique (voir §21/22 du fichier de méthodologie)."""
    real = f.create.SourceMob()
    real.name = filename
    for ch in range(1, channels + 1):
        s = real.create_timeline_slot(edit_rate=25, slot_id=ch)
        s['PhysicalTrackNumber'].value = ch
        c = f.create.SourceClip(media_kind="sound")
        c.length = total_frames_seq_fps
        s.segment = c

    hdr = _wav_header(path) or {}
    sample_rate = hdr.get('framerate') or 48000
    bit_depth = (hdr.get('sampwidth') or 2) * 8
    block_align = channels * (bit_depth // 8)

    desc = f.create.PCMDescriptor()
    desc['SampleRate'].value = sample_rate
    desc['AudioSamplingRate'].value = sample_rate
    desc['Channels'].value = channels
    desc['QuantizationBits'].value = bit_depth
    desc['BlockAlign'].value = block_align
    desc['AverageBPS'].value = sample_rate * block_align
    desc['Length'].value = total_samples
    desc['ContainerFormat'].value = f.dictionary.lookup_containerdef("AAFKLV")
    desc['Locator'].append(_aaf_locator(f, path))
    real.descriptor = desc
    f.content.mobs.append(real)
    return real


def _aaf_build_bwf_channel_master(f, bwf_real, filename, fps, channel, total_frames, tc_start_frames):
    """MasterMob d'un canal ingé son. `PhysicalTrackNumber` posé sur le slot
    exposé ICI (pas seulement sur le slot correspondant du mob réel en
    dessous) — retour terrain sept. 2026 : deux MasterMob distincts partageant
    le même nom+TC (donc identifiés comme LE MÊME clip WAV déjà lié ailleurs
    dans le projet) pouvaient jouer deux fois le même canal au lieu de deux
    canaux différents ; sans certitude totale que ce soit LA cause exacte,
    exposer le numéro de canal réel à cet endroit aussi ne peut pas nuire et
    donne à DaVinci une chance de plus de distinguer les deux références."""
    master = f.create.MasterMob()
    master.name = filename
    _aaf_add_tc_slot(f, master, fps, tc_start_frames, total_frames)
    m_slot = master.create_timeline_slot(edit_rate=fps, slot_id=1)
    m_slot['PhysicalTrackNumber'].value = channel
    m_slot.segment = bwf_real.create_source_clip(slot_id=channel, length=total_frames, media_kind="sound")
    f.content.mobs.append(master)
    return master


def _aaf_bwf_segment_plan(seg_start_frames, seg_dur_frames, tc_in_frames, bwf, fps,
                           bwf_tc_frames=None, bwf_total_frames=None):
    """Découpe un segment vidéo [seg_start_frames, seg_start_frames+seg_dur_frames[
    (temps RELATIF au clip, EN IMAGES) en une suite de tronçons pour la piste
    ingé son, en tenant compte du fait que le BWF ne couvre presque jamais
    EXACTEMENT la même fenêtre que le plan (son qui roule avant/après la
    caméra, de quelques secondes à quelques dizaines de secondes — la norme,
    pas l'exception) :

        [silence avant] [son synchronisé] [silence après]

    plutôt que de rejeter tout le segment dès que le recouvrement n'est pas
    total (bug initial de la v1 : `bwf_seg_start_frames >= 0` rejetait un
    plan démarrant ne serait-ce que 0,24s avant le début de l'ingé son —
    retour terrain sept. 2026 sur DRIFT_CLUB, piste MIROIRT03/DRIFT_avril0004).

    Prend tout en IMAGES DÉJÀ ARRONDIES (pas en secondes brutes) et calées sur
    les MÊMES arrondis que le reste du graphe (`tc_in_frames`/`bwf_tc_frames`,
    calculés par l'appelant exactement comme pour le placement des segments
    image et le slot Timecode du MasterMob du WAV) — arrondir deux fois
    indépendamment (une fois en secondes ici, une fois ailleurs pour ces mêmes
    instants) pouvait produire un écart d'exactement 1 image entre le filler
    réellement posé et le filler attendu par un contrôle de cohérence externe,
    invisible à l'oreille sur un point de montage mais confirmé par
    `validate_aaf.py` (OFFSET_SON sur Clip0008/REC-B-003.WAV, sept. 2026) —
    toute l'arithmétique se fait donc désormais en entiers-images de bout en
    bout, jamais en secondes flottantes.

    Retourne une liste de tuples, dont la somme des durées vaut EXACTEMENT
    `seg_dur_frames` pour ne jamais désynchroniser les pistes entre elles :
      ('silence', n_frames)
      ('audio', offset_frames_dans_le_bwf, n_frames)
    """
    seg_dur_frames = max(1, int(seg_dur_frames))
    if not bwf or bwf_tc_frames is None or bwf_total_frames is None:
        return [('silence', seg_dur_frames)]

    real_start = int(tc_in_frames) + int(seg_start_frames)
    real_end = real_start + seg_dur_frames
    bwf_start = int(bwf_tc_frames)
    bwf_end = bwf_start + int(bwf_total_frames)

    overlap_start = max(real_start, bwf_start)
    overlap_end = min(real_end, bwf_end)

    pre_frames = max(0, overlap_start - real_start)
    if overlap_end <= overlap_start:
        # Aucun recouvrement réel malgré un candidat retenu (ne devrait pas
        # arriver vu le filtre de _bwf_best_overlap_for_clip, filet de sécurité).
        return [('silence', seg_dur_frames)]

    mid_frames = max(0, overlap_end - overlap_start)
    post_frames = seg_dur_frames - pre_frames - mid_frames  # reste exact, jamais recalculé indépendamment
    if post_frames < 0:
        # Débordement (rare) — on rogne le milieu.
        mid_frames += post_frames
        post_frames = 0
    if mid_frames <= 0:
        return [('silence', seg_dur_frames)]

    bwf_offset_frames = overlap_start - bwf_start
    plan = []
    if pre_frames > 0:
        plan.append(('silence', pre_frames))
    plan.append(('audio', bwf_offset_frames, mid_frames))
    if post_frames > 0:
        plan.append(('silence', post_frames))
    return plan


def _aaf_kept_segments(clip, notes, users):
    """Segments conservés après découpe par marqueurs X — même logique que
    export_fcpxml (voir ce commentaire pour le détail des règles)."""
    dur = clip.get('duration_sec', 0) or 0
    x_times = sorted(set(
        m['time'] for u in users
        for m in ((notes.get(user_note_key(u)) or {}).get(clip['id']) or {}).get('markers', [])
        if m.get('cat') == 'X'
    ))
    if not x_times:
        return [(0.0, dur)]
    segments = []
    prev = 0.0
    for i, t in enumerate(x_times):
        if i % 2 == 0:
            if t > prev:
                segments.append((prev, t))
        else:
            prev = t
    if len(x_times) % 2 == 0 and x_times[-1] < dur:
        segments.append((x_times[-1], dur))
    return segments


def export_aaf(project, filter_config=None):
    """Export AAF multipiste : image + son caméra + une piste par micro d'ingé
    son (déduit du BWF déjà associé à chaque clip via `clip['_aaf_bwf']`, posé
    par `_proj_with_resolved_bwf_links` côté serveur avant l'appel — voir cette
    fonction dans derush_server.py pour la résolution du meilleur BWF candidat
    par clip). Même contrat de filtre que `export_fcpxml`.

    Retourne des BYTES (fichier binaire AAF/CFB), pas une chaîne — l'appelant
    doit répondre avec un Content-Type binaire, pas texte."""
    import os
    import tempfile
    import aaf2

    clips = _chrono_sort_clips(project.get('clips', []))
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False

    included = []
    for clip in clips:
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = str(cnotes.get('rating', ''))
            if rating == 'X':
                is_rejected = True
            if fc_rejected_only:
                if rating == 'X': include_clip = True
            elif fc_min_rating is not None:
                if rating in ['1','2','3'] and int(rating) >= fc_min_rating:
                    include_clip = True
            elif fc_cats is not None:
                if any(m.get('cat') in fc_cats for m in cnotes.get('markers', []) if m.get('cat') != 'X'):
                    include_clip = True
            else:
                if cnotes.get('markers') or cnotes.get('notes', '').strip() or rating in ['1','2','3']:
                    include_clip = True
        if fc_rejected_only:
            if include_clip: included.append(clip)
        else:
            if not is_rejected and include_clip: included.append(clip)

    # FPS de séquence unique (comme export_markers_edl) : les projets réels
    # sont mono-fps ; une composition AAF n'a qu'un seul edit rate par piste.
    seq_fps = round(included[0].get('fps', 25)) if included else 25

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.aaf')
    os.close(tmp_fd)
    os.remove(tmp_path)  # aaf2 veut créer le fichier lui-même

    try:
        with aaf2.open(tmp_path, 'w') as f:
            comp = f.create.CompositionMob()
            comp.name = project.get('name', 'Projet')
            f.content.mobs.append(comp)
            comp_tc = comp.create_timeline_slot(edit_rate=seq_fps, slot_id=1)
            comp_tc.segment = f.create.Timecode(fps=seq_fps, length=1)  # longueur réajustée en fin de fonction

            pic_track = comp.create_picture_slot(edit_rate=seq_fps)
            cam_track = comp.create_sound_slot(edit_rate=seq_fps)

            # Vrai multipiste ingé son (une piste par canal/micro, pas juste une
            # piste par fichier) — réactivé sept. 2026 après correction de deux
            # bugs structurels (cache BWF collisionnant entre journées + double
            # arrondi seconde→image, voir plus haut/§22 du fichier sur D:) qui
            # étaient très probablement la vraie cause de l'instabilité observée
            # lors des tentatives précédentes (canal dupliqué/muet, son d'un
            # autre jour malgré le bon nom affiché — voir §21). Retour terrain
            # explicite (sept. 2026) : le repli 1 canal/fichier n'est PAS un
            # compromis acceptable pour l'utilisateur, qui veut toutes les
            # pistes. Réserve honnête : n'élimine pas forcément le mystère
            # persistant sur Clip0008/J11 (§41, TC collision côté Media Pool,
            # cause probablement indépendante du nombre de canaux exposés).
            bwf_channel_count_cache = {}  # chemin réel du BWF -> nb de canaux réels
            max_ingest_channels = 0
            for clip in included:
                bwf = clip.get('_aaf_bwf')
                if not bwf:
                    continue
                # Même clé que `bwf_id` plus bas dans la boucle principale — DOIT
                # rester identique, sinon ce pré-calcul et le cache réel divergent.
                bwf_key = bwf.get('path') or bwf['id']
                if bwf_key not in bwf_channel_count_cache:
                    hdr = _wav_header(bwf.get('path', ''))
                    bwf_channel_count_cache[bwf_key] = (
                        (hdr and hdr.get('channels')) or bwf.get('channels') or 1)
                max_ingest_channels = max(max_ingest_channels, bwf_channel_count_cache[bwf_key])

            ingest_tracks = [comp.create_sound_slot(edit_rate=seq_fps) for _ in range(max_ingest_channels)]

            video_masters = {}   # clip_id -> (pic_master, cam_master)
            bwf_real_cache = {}  # chemin réel du BWF -> real mob (tous ses canaux réels exposés)
            bwf_master_cache = {}  # (clip_id, chemin réel du BWF, canal) -> master mob (dédié par clip+canal, voir §21)

            record_offset = 0.0
            for clip in included:
                path = clip.get('path', '')
                if not path:
                    continue
                clip_fps = seq_fps  # une seule fréquence de composition (voir plus haut)
                dur = clip.get('duration_sec', 0) or 0
                total_frames = max(1, int(round(dur * clip_fps)))
                res = clip.get('resolution') or '1920x1080'
                parts = res.split('x')
                width, height = (int(parts[0]), int(parts[1])) if len(parts) == 2 else (1920, 1080)
                tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
                tc_in_frames = int(round(tc_in_sec * clip_fps))

                if clip['id'] not in video_masters:
                    sound_ch = _aaf_camera_sound_channel(clip.get('camera'), clip.get('day'))
                    real = _aaf_build_video_real_mob(f, clip.get('filename', clip['id']), path,
                                                      width, height, clip_fps, total_frames, sound_ch)
                    video_masters[clip['id']] = _aaf_build_video_masters(
                        f, real, clip.get('filename', clip['id']), clip_fps, total_frames, tc_in_frames, sound_ch)
                pic_master, cam_master = video_masters[clip['id']]

                bwf = clip.get('_aaf_bwf')
                bwf_masters = []  # un MasterMob par canal réel de ce BWF (index 0 = canal 1)
                bwf_channels = 0
                if bwf:
                    # Clé de cache sur le CHEMIN réel, jamais sur bwf['id'] : cet id
                    # (dérivé du seul nom de fichier par scan_son_dir) collisionne entre
                    # journées différentes qui réutilisent les mêmes noms génériques
                    # d'enregistreur (ex. Mixpre6 "REC-B-001.WAV" chaque jour). Avec une
                    # clé non qualifiée par jour, un second clip matché au même NOM mais
                    # un AUTRE fichier (jour différent, chemin différent, durée
                    # différente) retombait sur le mob réel déjà construit pour le
                    # premier jour — mauvais fichier ET dépassement de la durée source
                    # réelle (confirmé par validate_aaf.py : OFFSET_SON/DEPASSEMENT_SOURCE
                    # sur Clip0008/REC-B-003.WAV, sept. 2026).
                    bwf_id = bwf.get('path') or bwf['id']
                    bwf_channels = bwf_channel_count_cache.get(bwf_id) or 1
                    bwf_dur = bwf.get('duration_sec') or 0
                    bwf_total_frames = max(1, int(round(bwf_dur * clip_fps)))
                    bwf_total_samples = int(round(bwf_dur * (bwf.get('sample_rate') or 48000)))
                    bwf_tc_frames = int(round((bwf.get('tc_in_sec') or 0) * clip_fps))
                    if bwf_id not in bwf_real_cache:
                        # TOUS les canaux réels exposés (repli 1 canal abandonné, voir plus haut).
                        bwf_real_cache[bwf_id] = _aaf_build_bwf_real_mob(
                            f, bwf.get('filename', bwf['id']), bwf.get('path', ''),
                            bwf_channels, bwf_total_frames, bwf_total_samples)
                    bwf_real = bwf_real_cache[bwf_id]
                    for ch in range(1, bwf_channels + 1):
                        master_key = (clip['id'], bwf_id, ch)
                        if master_key not in bwf_master_cache:
                            bwf_master_cache[master_key] = _aaf_build_bwf_channel_master(
                                f, bwf_real, bwf.get('filename', bwf['id']), clip_fps, ch,
                                bwf_total_frames, bwf_tc_frames)
                        bwf_masters.append(bwf_master_cache[master_key])

                segments = _aaf_kept_segments(clip, notes, users)
                for seg_start, seg_end in segments:
                    seg_dur = seg_end - seg_start
                    if seg_dur <= 0:
                        continue
                    seg_start_frames = int(round(seg_start * clip_fps))
                    seg_dur_frames = max(1, int(round(seg_dur * clip_fps)))

                    pic_track.segment.components.append(
                        pic_master.create_source_clip(slot_id=1, start=seg_start_frames, length=seg_dur_frames))
                    cam_track.segment.components.append(
                        cam_master.create_source_clip(slot_id=1, start=seg_start_frames, length=seg_dur_frames))

                    # Silence/son/silence par tronçon — voir _aaf_bwf_segment_plan
                    # pour pourquoi (un plan qui déborde un peu du son ingé de
                    # chaque côté est la norme, pas une raison de tout rejeter).
                    # Tout est passé en images déjà arrondies (pas en secondes) —
                    # voir la docstring de la fonction pour l'écart d'1 image que
                    # ça évite.
                    plan = _aaf_bwf_segment_plan(
                        seg_start_frames, seg_dur_frames, tc_in_frames, bwf, clip_fps,
                        bwf_tc_frames=bwf_tc_frames if bwf else None,
                        bwf_total_frames=bwf_total_frames if bwf else None)
                    # Le découpage silence/son/silence est IDENTIQUE pour tous les
                    # canaux d'un même BWF (même minutage) — seul le MasterMob
                    # source diffère par canal. Chaque piste ingé au-delà du
                    # nombre de canaux réels de CE clip (ou si pas de BWF du tout)
                    # reçoit du silence pour la durée totale du segment.
                    for track_idx, ingest_track in enumerate(ingest_tracks):
                        if track_idx >= bwf_channels:
                            ingest_track.segment.components.append(
                                f.create.Filler(media_kind="sound", length=seg_dur_frames))
                            continue
                        bwf_master = bwf_masters[track_idx]
                        for part in plan:
                            if part[0] == 'audio':
                                _, bwf_offset_frames, n_frames = part
                                ingest_track.segment.components.append(
                                    bwf_master.create_source_clip(slot_id=1, start=bwf_offset_frames, length=n_frames))
                            else:
                                n_frames = part[-1]
                                ingest_track.segment.components.append(
                                    f.create.Filler(media_kind="sound", length=n_frames))

                    record_offset += seg_dur

            # Longueur réelle de la piste Timecode de la composition
            comp_tc.segment.length = max(1, int(round(record_offset * seq_fps)))

        with open(tmp_path, 'rb') as fh:
            return fh.read()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def export_fcpxml(project, filter_config=None):
    clips = _chrono_sort_clips(project.get('clips', []))
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    # Format entries keyed by (resolution, fps_int) to handle mixed fps projects
    formats = {}
    for clip in clips:
        res = clip.get('resolution') or '1920x1080'
        fps_int = round(clip.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}

    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}

    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))

    seq_format_id = list(formats.values())[0]['id']
    
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project['name']} - Dérushage")
    proj = ET.SubElement(event, 'project', name='Selects')
    seq = ET.SubElement(proj, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    record_offset = 0
    asset_idx = 0

    for clip in clips:
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = str(cnotes.get('rating', ''))
            if rating == 'X':
                is_rejected = True
            if fc_rejected_only:
                if rating == 'X': include_clip = True
            elif fc_min_rating is not None:
                if rating in ['1','2','3'] and int(rating) >= fc_min_rating:
                    include_clip = True
            elif fc_cats is not None:
                if any(m.get('cat') in fc_cats for m in cnotes.get('markers', []) if m.get('cat') != 'X'):
                    include_clip = True
            else:
                if cnotes.get('markers') or cnotes.get('notes', '').strip() or rating in ['1','2','3']:
                    include_clip = True

        if fc_rejected_only:
            if not include_clip: continue
        else:
            if is_rejected or not include_clip: continue

        asset_idx += 1
        asset_id = f"asset_{asset_idx}"
        clip_fps = round(clip.get('fps', 25))
        dur = clip.get('duration_sec', 0) or 1
        dur_rational = seconds_to_rational(dur, clip_fps)

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        clip_res = clip.get('resolution') or '1920x1080'
        fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']

        # Source TC as <asset start> — voir _clip_asset_tc_sec (LTC si dispo, sinon
        # tag TC brut MXF ; tc_in est stocké correct après le byte-reversal FX6).
        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        tc_in_frames = int(round(tc_in_sec * clip_fps))
        tc_in_rational = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'

        ET.SubElement(resources, 'asset', id=asset_id,
                      src=src_uri,
                      start=tc_in_rational, duration=dur_rational, format=fmt_id,
                      name=clip.get('filename', ''), hasVideo='1', hasAudio='1')

        # Collect global notes/rating as clip-level note (shown in DaVinci clip metadata, no timeline marker)
        clip_note_parts = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = str(cnotes.get('rating', ''))
            global_note = cnotes.get('notes', '').strip()
            stars = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐'}.get(rating, '')
            parts = [p for p in [stars, global_note] if p]
            if parts:
                clip_note_parts.append(f"[{u.get('name') or u.get('username', '?')}] " + ' — '.join(parts))

        # Collect X-marker cut points across all users
        x_times = sorted(set(
            m['time'] for u in users
            for m in ((notes.get(user_note_key(u)) or {}).get(clip['id']) or {}).get('markers', [])
            if m.get('cat') == 'X'
        ))

        # Build kept segments from X markers:
        # 1 X at T  → keep [0,T]
        # 2 X       → keep [0,T1] + [T2,end]
        # 3 X       → keep [0,T1] + [T2,T3]
        # etc.
        if not x_times:
            segments = [(0.0, dur)]
        else:
            segments = []
            prev = 0.0
            for i, t in enumerate(x_times):
                if i % 2 == 0:
                    if t > prev:
                        segments.append((prev, t))
                else:
                    prev = t
            if len(x_times) % 2 == 0 and x_times[-1] < dur:
                segments.append((x_times[-1], dur))

        # Collect content markers (non-X) from all users
        all_markers = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            cat_labels = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'T': '🎨', 'S': '🎵', 'D': '📌'}
            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X':
                    continue
                cat = cat_labels.get(str(m.get('cat', '')), str(m.get('cat', '')))
                desc = m.get('desc', '')
                label = f"[{u.get('name') or u.get('username', '?')}] {cat}".strip()
                all_markers.append({'time': m.get('time', 0), 'val': label, 'note': desc})
        all_markers.sort(key=lambda x: x['time'])

        # Emit one asset-clip per kept segment
        for seg_start, seg_end in segments:
            seg_dur = seg_end - seg_start
            if seg_dur <= 0:
                continue
            seg_start_frames = int(round(seg_start * clip_fps))
            seg_dur_rational = seconds_to_rational(seg_dur, clip_fps)
            seg_tc_start_frames = tc_in_frames + seg_start_frames
            seg_tc_rational = f'{seg_tc_start_frames}/{clip_fps}s' if seg_tc_start_frames > 0 else '0s'

            ac_attrs = {
                'ref': asset_id,
                'offset': seconds_to_rational(record_offset, clip_fps),
                'duration': seg_dur_rational,
                'start': seg_tc_rational,
                'name': clip.get('filename', ''),
            }
            if clip_note_parts:
                ac_attrs['note'] = ' | '.join(clip_note_parts)
            ac = ET.SubElement(spine, 'asset-clip', **ac_attrs)

            # Add markers that fall within this segment
            seen_times = set()
            for m in all_markers:
                if m['time'] < seg_start or m['time'] >= seg_end:
                    continue
                offset_frames = int(round(m['time'] * clip_fps))
                frame_num = tc_in_frames + offset_frames
                while frame_num in seen_times:
                    frame_num += 1
                seen_times.add(frame_num)
                mk_attrs = {
                    'start': f'{frame_num}/{clip_fps}s',
                    'duration': f'1/{clip_fps}s',
                    'value': m['val'],
                }
                if m.get('note'):
                    mk_attrs['note'] = m['note']
                ET.SubElement(ac, 'marker', **mk_attrs)

            record_offset += seg_dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def _fcp7_rate_elem(fps_int):
    """<rate><timebase>N</timebase><ntsc>FALSE</ntsc></rate>"""
    # NTSC fractional rates : 23.976, 29.97, 59.94 → ntsc=TRUE
    # Ici on traite des fps entiers depuis round(clip.fps), donc ntsc=FALSE
    e = ET.Element('rate')
    ET.SubElement(e, 'timebase').text = str(fps_int)
    ET.SubElement(e, 'ntsc').text = 'FALSE'
    return e


def _fcp7_tc_elem(tc_sec, fps_int):
    """<timecode><rate>…</rate><string>HH:MM:SS:FF</string><frame>N</frame>…"""
    frames = int(round(tc_sec * fps_int))
    tc_str = seconds_to_tc(tc_sec, fps_int)
    e = ET.Element('timecode')
    e.append(_fcp7_rate_elem(fps_int))
    ET.SubElement(e, 'string').text = tc_str
    ET.SubElement(e, 'frame').text = str(frames)
    ET.SubElement(e, 'displayformat').text = 'NDF'
    return e


def export_xml_fcp7(project, filter_config=None):
    """
    Export Adobe Premiere Pro XML (Final Cut Pro 7 XML Interchange Format, v5).
    Schéma : <xmeml><sequence><media><video><track><clipitem>…
    Compatible Premiere Pro CC 2017+ (et toute version qui sait lire l'XML FCP7).
    Mêmes règles de filtrage et coupes X que export_fcpxml.
    """
    clips = _chrono_sort_clips(project.get('clips', []))
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False
    _rate_elem = _fcp7_rate_elem
    _tc_elem = _fcp7_tc_elem

    # Détermine fps de séquence (majoritaire) + dims max
    seq_fps = 25
    seq_w, seq_h = 1920, 1080
    if clips:
        fps_count = {}
        for c in clips:
            fps_count[round(c.get('fps', 25))] = fps_count.get(round(c.get('fps', 25)), 0) + 1
        seq_fps = max(fps_count.items(), key=lambda x: x[1])[0]
        for c in clips:
            res = c.get('resolution') or '1920x1080'
            parts = res.split('x')
            if len(parts) == 2:
                try:
                    w, h = int(parts[0]), int(parts[1])
                    if w * h > seq_w * seq_h:
                        seq_w, seq_h = w, h
                except ValueError:
                    pass

    root = ET.Element('xmeml', version='5')
    seq = ET.SubElement(root, 'sequence', id='sequence-1')
    ET.SubElement(seq, 'name').text = f"{project.get('name', 'Projet')} - Selects"

    # La durée sera calculée à la fin (somme des segments en frames)
    seq_duration_el = ET.SubElement(seq, 'duration')
    seq.append(_rate_elem(seq_fps))
    seq.append(_tc_elem(0, seq_fps))

    media = ET.SubElement(seq, 'media')
    video = ET.SubElement(media, 'video')
    fmt = ET.SubElement(video, 'format')
    sc = ET.SubElement(fmt, 'samplecharacteristics')
    sc.append(_rate_elem(seq_fps))
    ET.SubElement(sc, 'width').text = str(seq_w)
    ET.SubElement(sc, 'height').text = str(seq_h)
    ET.SubElement(sc, 'pixelaspectratio').text = 'square'
    track = ET.SubElement(video, 'track')

    file_ids_emitted = set()  # pour réutiliser <file id> sans dupliquer le body
    record_frames = 0  # offset cumulé dans la timeline séquence
    clip_idx = 0

    for clip in clips:
        # ─── Filter : même logique que export_fcpxml ────────────────────────
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes:
                continue
            rating = str(cnotes.get('rating', ''))
            if rating == 'X':
                is_rejected = True
            if fc_rejected_only:
                if rating == 'X':
                    include_clip = True
            elif fc_min_rating is not None:
                if rating in ['1', '2', '3'] and int(rating) >= fc_min_rating:
                    include_clip = True
            elif fc_cats is not None:
                if any(m.get('cat') in fc_cats for m in cnotes.get('markers', []) if m.get('cat') != 'X'):
                    include_clip = True
            else:
                if cnotes.get('markers') or cnotes.get('notes', '').strip() or rating in ['1', '2', '3']:
                    include_clip = True
        if fc_rejected_only:
            if not include_clip:
                continue
        else:
            if is_rejected or not include_clip:
                continue

        clip_idx += 1
        clip_fps = round(clip.get('fps', 25))
        dur_sec = clip.get('duration_sec', 0) or 1
        dur_frames = int(round(dur_sec * clip_fps))
        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        tc_in_frames = int(round(tc_in_sec * clip_fps))

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        file_id = f"file-{clip['id']}"
        first_emit = file_id not in file_ids_emitted
        file_ids_emitted.add(file_id)

        # ─── Notes globales + segments X (même logique que FCPXML) ─────────
        clip_note_parts = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes:
                continue
            rating = str(cnotes.get('rating', ''))
            global_note = cnotes.get('notes', '').strip()
            stars = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐'}.get(rating, '')
            parts = [p for p in [stars, global_note] if p]
            if parts:
                clip_note_parts.append(f"[{u.get('name') or u.get('username', '?')}] " + ' — '.join(parts))

        x_times = sorted(set(
            m['time'] for u in users
            for m in ((notes.get(user_note_key(u)) or {}).get(clip['id']) or {}).get('markers', [])
            if m.get('cat') == 'X'
        ))
        if not x_times:
            segments = [(0.0, dur_sec)]
        else:
            segments = []
            prev = 0.0
            for i, t in enumerate(x_times):
                if i % 2 == 0:
                    if t > prev:
                        segments.append((prev, t))
                else:
                    prev = t
            if len(x_times) % 2 == 0 and x_times[-1] < dur_sec:
                segments.append((x_times[-1], dur_sec))

        # ─── Markers content (non-X) ───────────────────────────────────────
        all_markers = []
        cat_labels = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'T': '🎨', 'S': '🎵', 'D': '📌'}
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes:
                continue
            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X':
                    continue
                cat = cat_labels.get(str(m.get('cat', '')), str(m.get('cat', '')))
                desc = m.get('desc', '')
                label = f"[{u.get('name') or u.get('username', '?')}] {cat}".strip()
                all_markers.append({'time': m.get('time', 0), 'name': label, 'desc': desc})
        all_markers.sort(key=lambda x: x['time'])

        # ─── 1 <clipitem> par segment kept ─────────────────────────────────
        for seg_start, seg_end in segments:
            seg_dur_sec = seg_end - seg_start
            if seg_dur_sec <= 0:
                continue
            seg_in = int(round(seg_start * clip_fps))
            seg_out = int(round(seg_end * clip_fps))
            seg_dur_frames = seg_out - seg_in

            ci = ET.SubElement(track, 'clipitem', id=f"clipitem-{clip_idx}-{int(seg_start*1000)}")
            ET.SubElement(ci, 'name').text = clip.get('filename', clip.get('id', ''))
            ET.SubElement(ci, 'duration').text = str(dur_frames)
            ci.append(_rate_elem(clip_fps))
            ET.SubElement(ci, 'in').text = str(seg_in)
            ET.SubElement(ci, 'out').text = str(seg_out)
            ET.SubElement(ci, 'start').text = str(record_frames)
            ET.SubElement(ci, 'end').text = str(record_frames + seg_dur_frames)

            if first_emit:
                # Définition complète du fichier la 1ère fois
                f = ET.SubElement(ci, 'file', id=file_id)
                ET.SubElement(f, 'name').text = clip.get('filename', '')
                ET.SubElement(f, 'pathurl').text = src_uri
                f.append(_rate_elem(clip_fps))
                ET.SubElement(f, 'duration').text = str(dur_frames)
                # TC source : critique pour que Premiere matche le fichier original
                f.append(_tc_elem(tc_in_sec, clip_fps))
                fmedia = ET.SubElement(f, 'media')
                fvideo = ET.SubElement(fmedia, 'video')
                fsc = ET.SubElement(fvideo, 'samplecharacteristics')
                fsc.append(_rate_elem(clip_fps))
                cres = clip.get('resolution') or f'{seq_w}x{seq_h}'
                cparts = cres.split('x')
                cw, ch = (cparts[0], cparts[1]) if len(cparts) == 2 else (str(seq_w), str(seq_h))
                ET.SubElement(fsc, 'width').text = cw
                ET.SubElement(fsc, 'height').text = ch
                ET.SubElement(fmedia, 'audio')  # placeholder = pas de detail mais Premiere accepte
                first_emit = False
            else:
                # Réutilisation par ref
                ET.SubElement(ci, 'file', id=file_id)

            # Note globale dans le commentaire du clipitem (visible Métadonnées Premiere)
            if clip_note_parts:
                comments = ET.SubElement(ci, 'comments')
                mc = ET.SubElement(comments, 'mastercomment1')
                mc.text = ' | '.join(clip_note_parts)

            # Markers content dans le segment
            for m in all_markers:
                if m['time'] < seg_start or m['time'] >= seg_end:
                    continue
                # <marker><in> = offset depuis le début du SOURCE FILE (pas du clipitem)
                # Premiere place le marker à cette frame relative au fichier média
                m_in = int(round(m['time'] * clip_fps))
                mk = ET.SubElement(ci, 'marker')
                ET.SubElement(mk, 'name').text = m['name']
                if m.get('desc'):
                    ET.SubElement(mk, 'comment').text = m['desc']
                ET.SubElement(mk, 'in').text = str(m_in)
                ET.SubElement(mk, 'out').text = '-1'

            record_frames += seg_dur_frames

    seq_duration_el.text = str(record_frames)

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def export_subclips_fcpxml(project, pre_roll=3.0, post_roll=7.0, filter_config=None):
    """
    Export FCPXML avec un sous-clip par marker : [marker - pre_roll, marker + post_roll].
    Chaque segment est clampé aux bornes du clip source.
    """
    clips = _chrono_sort_clips(project.get('clips', []))
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    cat_labels_map = {'3':'⭐⭐⭐','2':'⭐⭐','1':'⭐','T':'🎨','S':'🎵','D':'📌'}

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    formats = {}
    for clip in clips:
        res = clip.get('resolution') or '1920x1080'
        fps_int = round(clip.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}
    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}
    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))

    seq_format_id = list(formats.values())[0]['id']
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project['name']} - Subclips")
    proj_el = ET.SubElement(event, 'project',
                             name=f"Subclips -{int(pre_roll)}s/+{int(post_roll)}s")
    seq = ET.SubElement(proj_el, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    record_offset = 0.0
    asset_map = {}
    asset_idx = 0

    for clip in clips:
        clip_fps = round(clip.get('fps', 25))
        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        tc_in_frames = int(round(tc_in_sec * clip_fps))
        clip_dur = clip.get('duration_sec', 0) or 0

        all_markers = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            if cnotes.get('rating') == 'X': continue
            # Rating-based markers
            rating = str(cnotes.get('rating', ''))
            if fc_cats is None and fc_min_rating is not None:
                if rating in ['1','2','3'] and int(rating) >= fc_min_rating:
                    label = f"[{u.get('name') or u.get('username', '?')}] {cat_labels_map.get(rating,'')}"
                    all_markers.append({'time': 0, 'label': label, 'note': cnotes.get('notes','').strip()})
            # Individual markers
            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X': continue
                if fc_cats is not None and m.get('cat') not in fc_cats: continue
                if fc_min_rating is not None and fc_cats is None: continue
                cat = cat_labels_map.get(str(m.get('cat','')), '')
                desc = m.get('desc','').strip()
                label = f"[{u.get('name') or u.get('username', '?')}] {cat}"
                all_markers.append({'time': m.get('time', 0), 'label': label,
                                    'note': desc if desc.lower() not in ('marker','') else ''})

        if not all_markers: continue

        src_path = clip.get('path', '')
        if src_path not in asset_map:
            asset_idx += 1
            aid = f'asset_{asset_idx}'
            asset_map[src_path] = aid
            src_uri = src_path.replace(chr(92), '/')
            if not src_uri.startswith('/'): src_uri = '/' + src_uri
            src_uri = 'file://localhost' + src_uri
            clip_res = clip.get('resolution') or '1920x1080'
            fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']
            tc_r = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'
            ET.SubElement(resources, 'asset', id=aid, src=src_uri,
                          start=tc_r, duration=seconds_to_rational(clip_dur, clip_fps),
                          format=fmt_id, name=clip.get('filename',''), hasVideo='1', hasAudio='1')
        aid = asset_map[src_path]

        all_markers.sort(key=lambda x: x['time'])
        for m in all_markers:
            mtime = m['time']
            sub_start = max(tc_in_sec, tc_in_sec + mtime - pre_roll)
            sub_end   = min(tc_in_sec + clip_dur, tc_in_sec + mtime + post_roll)
            sub_dur   = sub_end - sub_start
            if sub_dur < 0.04: continue

            sub_start_frames = int(round(sub_start * clip_fps))
            ac = ET.SubElement(spine, 'asset-clip', ref=aid,
                               offset=seconds_to_rational(record_offset, clip_fps),
                               duration=seconds_to_rational(sub_dur, clip_fps),
                               start=f'{sub_start_frames}/{clip_fps}s',
                               name=f"{clip.get('stem','')} — {m['label']}")
            mk_frame = tc_in_frames + int(round(mtime * clip_fps))
            mk_attrs = {'start': f'{mk_frame}/{clip_fps}s',
                        'duration': f'1/{clip_fps}s', 'value': m['label']}
            if m.get('note'): mk_attrs['note'] = m['note']
            ET.SubElement(ac, 'marker', **mk_attrs)
            record_offset += sub_dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str

def export_rough_cut_fcpxml(project, min_rating=2, user_filter=None):
    """
    Génère une rough cut : timeline FCPXML avec tous les clips ayant rating >= min_rating
    (pour user_filter spécifique ou n'importe quel user si None), dans l'ordre TC source.
    Chaque clip est inclus en entier (pas de subclip), prêt à monter dans Resolve.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    min_rating = int(min_rating)

    def _matches(clip):
        for u in users:
            uid = user_note_key(u)
            if user_filter and uid != user_filter:
                continue
            cn = (notes.get(uid) or {}).get(clip['id'])
            if not cn: continue
            r = str(cn.get('rating', ''))
            if r in ('1', '2', '3') and int(r) >= min_rating:
                return True
        return False

    selected = [c for c in clips if _matches(c)]
    # Sort: by day then by source TC for natural editing order
    def _sortkey(c):
        fps = round(c.get('fps', 25))
        return (c.get('day', ''), tc_to_seconds(c.get('tc_in', ''), fps) or 0)
    selected.sort(key=_sortkey)

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    # Build format pool
    formats = {}
    for c in selected:
        res = c.get('resolution') or '1920x1080'
        fps_int = round(c.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}
    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}
    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))

    seq_format_id = list(formats.values())[0]['id']

    # Friendly project name
    rating_label = {1: 'OK+', 2: 'Bien+', 3: 'Top'}.get(min_rating, f'>={min_rating}')
    user_label = user_filter or 'équipe'

    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project['name']} - Rough cut")
    proj_el = ET.SubElement(event, 'project',
                            name=f"Rough cut {rating_label} ({user_label})")
    seq = ET.SubElement(proj_el, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    record_offset = 0.0
    for idx, clip in enumerate(selected, 1):
        clip_fps = round(clip.get('fps', 25))
        dur = clip.get('duration_sec', 0) or 1
        dur_rational = seconds_to_rational(dur, clip_fps)

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        clip_res = clip.get('resolution') or '1920x1080'
        fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']

        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        tc_in_frames = int(round(tc_in_sec * clip_fps))
        tc_in_rational = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'

        asset_id = f"asset_{idx}"
        ET.SubElement(resources, 'asset', id=asset_id,
                      src=src_uri,
                      start=tc_in_rational, duration=dur_rational, format=fmt_id,
                      name=clip.get('filename', ''), hasVideo='1', hasAudio='1')

        # Aggregate note: best rating + global notes from contributors
        note_parts = []
        for u in users:
            uid = user_note_key(u)
            if user_filter and uid != user_filter:
                continue
            cn = (notes.get(uid) or {}).get(clip['id'])
            if not cn: continue
            r = str(cn.get('rating', ''))
            stars = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐'}.get(r, '')
            gn = (cn.get('notes') or '').strip()
            uname = u.get('username') or u.get('name', '?')
            bits = [b for b in [stars, gn] if b]
            if bits:
                note_parts.append(f'[{uname}] ' + ' — '.join(bits))

        ac_attrs = {
            'ref': asset_id,
            'offset': seconds_to_rational(record_offset, clip_fps),
            'duration': dur_rational,
            'start': tc_in_rational,
            'name': clip.get('filename', ''),
        }
        if note_parts:
            ac_attrs['note'] = ' | '.join(note_parts)
        ET.SubElement(spine, 'asset-clip', **ac_attrs)
        record_offset += dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def _basket_entries(project, user_key, item_ids=None):
    """Résout le panier personnel d'un user en une liste ordonnée [(clip, select)],
    en ignorant silencieusement les entrées orphelines (clip ou select supprimé
    depuis l'ajout au panier).

    `item_ids` (optionnel) : itérable d'`item['id']` (id propre à la ligne du
    panier, distinct du select_id) — quand fourni, ne garde QUE ces entrées,
    dans leur ordre d'apparition dans le panier (pas l'ordre de `item_ids`,
    qui n'a pas de signification temporelle côté front). Permet d'exporter
    une timeline sur une sélection partielle du pré-montage plutôt que la
    bobine entière — cf. UI 📤 Exporter → "sélection cochée"."""
    clips_by_id = {c['id']: c for c in project.get('clips', [])}
    user_notes = project.get('notes', {}).get(user_key, {})
    basket = (project.get('baskets', {}) or {}).get(user_key, [])
    id_filter = set(item_ids) if item_ids is not None else None
    entries = []
    for item in basket:
        if id_filter is not None and item.get('id') not in id_filter:
            continue
        clip = clips_by_id.get(item.get('clip_id'))
        if not clip:
            continue
        selects = (user_notes.get(item.get('clip_id')) or {}).get('selects', [])
        sel = next((s for s in selects if s.get('id') == item.get('select_id')), None)
        if not sel:
            continue
        entries.append((clip, sel))
    return entries


def export_basket_fcpxml(project, user_key, item_ids=None):
    """Export du panier personnel d'un utilisateur : une séquence FCPXML avec
    exactement les sélections (in/out) qu'il a retenues, dans l'ordre où il les
    a rangées — pas de filtre rating/X ici, l'ordre et le contenu sont sa
    décision explicite (contrairement à export_fcpxml/export_rough_cut_fcpxml
    qui infèrent la sélection depuis les notes d'équipe). `item_ids` (optionnel)
    restreint l'export à un sous-ensemble d'items du panier — voir _basket_entries."""
    entries = _basket_entries(project, user_key, item_ids)

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    formats = {}
    for clip, _sel in entries:
        res = clip.get('resolution') or '1920x1080'
        fps_int = round(clip.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}
    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}
    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))
    seq_format_id = list(formats.values())[0]['id']

    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project.get('name', 'Projet')} - Panier")
    proj_el = ET.SubElement(event, 'project', name=f"Panier ({user_key})")
    seq = ET.SubElement(proj_el, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    asset_ids = {}  # clip_id -> asset_id, dédup si le panier référence 2x le même clip
    record_offset = 0.0
    asset_idx = 0
    for clip, sel in entries:
        clip_fps = round(clip.get('fps', 25))
        dur = clip.get('duration_sec', 0) or 1
        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        tc_in_frames = int(round(tc_in_sec * clip_fps))

        if clip['id'] not in asset_ids:
            asset_idx += 1
            asset_id = f"asset_{asset_idx}"
            asset_ids[clip['id']] = asset_id
            dur_rational = seconds_to_rational(dur, clip_fps)
            src_path = clip.get('path', '')
            src_uri = src_path.replace(chr(92), '/')
            if not src_uri.startswith('/'):
                src_uri = '/' + src_uri
            src_uri = 'file://localhost' + src_uri
            clip_res = clip.get('resolution') or '1920x1080'
            fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']
            tc_in_rational = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'
            ET.SubElement(resources, 'asset', id=asset_id,
                          src=src_uri, start=tc_in_rational, duration=dur_rational,
                          format=fmt_id, name=clip.get('filename', ''), hasVideo='1', hasAudio='1')
        asset_id = asset_ids[clip['id']]

        seg_start = float(sel.get('in', 0) or 0)
        seg_end = float(sel.get('out', dur) or dur)
        seg_dur = max(0.04, seg_end - seg_start)
        seg_start_frames = int(round(seg_start * clip_fps))
        seg_dur_rational = seconds_to_rational(seg_dur, clip_fps)
        seg_tc_start_frames = tc_in_frames + seg_start_frames
        seg_tc_rational = f'{seg_tc_start_frames}/{clip_fps}s' if seg_tc_start_frames > 0 else '0s'

        name = sel.get('name') or clip.get('filename', '')
        ac_attrs = {
            'ref': asset_id,
            'offset': seconds_to_rational(record_offset, clip_fps),
            'duration': seg_dur_rational,
            'start': seg_tc_rational,
            'name': name,
        }
        note_parts = []
        if sel.get('desc'):
            note_parts.append(sel['desc'])
        if sel.get('tags'):
            note_parts.append('#' + ' #'.join(sel['tags']))
        if note_parts:
            ac_attrs['note'] = ' — '.join(note_parts)
        ET.SubElement(spine, 'asset-clip', **ac_attrs)
        record_offset += seg_dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def export_basket_xml_fcp7(project, user_key, item_ids=None):
    """Panier personnel en Adobe Premiere XML (FCP7 Interchange), même source
    (_basket_entries) et même logique d'ordre/segments que export_basket_fcpxml.
    `item_ids` (optionnel) restreint l'export à un sous-ensemble d'items du panier."""
    entries = _basket_entries(project, user_key, item_ids)

    seq_fps = 25
    seq_w, seq_h = 1920, 1080
    if entries:
        fps_count = {}
        for c, _sel in entries:
            fps_count[round(c.get('fps', 25))] = fps_count.get(round(c.get('fps', 25)), 0) + 1
        seq_fps = max(fps_count.items(), key=lambda x: x[1])[0]
        for c, _sel in entries:
            res = c.get('resolution') or '1920x1080'
            parts = res.split('x')
            if len(parts) == 2:
                try:
                    w, h = int(parts[0]), int(parts[1])
                    if w * h > seq_w * seq_h:
                        seq_w, seq_h = w, h
                except ValueError:
                    pass

    root = ET.Element('xmeml', version='5')
    seq = ET.SubElement(root, 'sequence', id='sequence-1')
    ET.SubElement(seq, 'name').text = f"{project.get('name', 'Projet')} - Panier ({user_key})"

    seq_duration_el = ET.SubElement(seq, 'duration')
    seq.append(_fcp7_rate_elem(seq_fps))
    seq.append(_fcp7_tc_elem(0, seq_fps))

    media = ET.SubElement(seq, 'media')
    video = ET.SubElement(media, 'video')
    fmt = ET.SubElement(video, 'format')
    sc = ET.SubElement(fmt, 'samplecharacteristics')
    sc.append(_fcp7_rate_elem(seq_fps))
    ET.SubElement(sc, 'width').text = str(seq_w)
    ET.SubElement(sc, 'height').text = str(seq_h)
    ET.SubElement(sc, 'pixelaspectratio').text = 'square'
    track = ET.SubElement(video, 'track')

    file_ids_emitted = set()
    record_frames = 0
    for idx, (clip, sel) in enumerate(entries, 1):
        clip_fps = round(clip.get('fps', 25))
        dur_sec = clip.get('duration_sec', 0) or 1
        dur_frames = int(round(dur_sec * clip_fps))
        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        tc_in_frames = int(round(tc_in_sec * clip_fps))

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        file_id = f"file-{clip['id']}"
        first_emit = file_id not in file_ids_emitted
        file_ids_emitted.add(file_id)

        seg_start = float(sel.get('in', 0) or 0)
        seg_end = float(sel.get('out', dur_sec) or dur_sec)
        seg_in = int(round(seg_start * clip_fps))
        seg_out = max(seg_in + 1, int(round(seg_end * clip_fps)))
        seg_dur_frames = seg_out - seg_in

        ci = ET.SubElement(track, 'clipitem', id=f"clipitem-{idx}-{int(seg_start*1000)}")
        ET.SubElement(ci, 'name').text = sel.get('name') or clip.get('filename', clip.get('id', ''))
        ET.SubElement(ci, 'duration').text = str(dur_frames)
        ci.append(_fcp7_rate_elem(clip_fps))
        ET.SubElement(ci, 'in').text = str(seg_in)
        ET.SubElement(ci, 'out').text = str(seg_out)
        ET.SubElement(ci, 'start').text = str(record_frames)
        ET.SubElement(ci, 'end').text = str(record_frames + seg_dur_frames)

        if first_emit:
            f = ET.SubElement(ci, 'file', id=file_id)
            ET.SubElement(f, 'name').text = clip.get('filename', '')
            ET.SubElement(f, 'pathurl').text = src_uri
            f.append(_fcp7_rate_elem(clip_fps))
            ET.SubElement(f, 'duration').text = str(dur_frames)
            f.append(_fcp7_tc_elem(tc_in_sec, clip_fps))
            fmedia = ET.SubElement(f, 'media')
            fvideo = ET.SubElement(fmedia, 'video')
            fsc = ET.SubElement(fvideo, 'samplecharacteristics')
            fsc.append(_fcp7_rate_elem(clip_fps))
            cres = clip.get('resolution') or f'{seq_w}x{seq_h}'
            cparts = cres.split('x')
            cw, ch = (cparts[0], cparts[1]) if len(cparts) == 2 else (str(seq_w), str(seq_h))
            ET.SubElement(fsc, 'width').text = cw
            ET.SubElement(fsc, 'height').text = ch
            ET.SubElement(fmedia, 'audio')
        else:
            ET.SubElement(ci, 'file', id=file_id)

        note_parts = []
        if sel.get('desc'):
            note_parts.append(sel['desc'])
        if sel.get('tags'):
            note_parts.append('#' + ' #'.join(sel['tags']))
        if note_parts:
            comments = ET.SubElement(ci, 'comments')
            mc = ET.SubElement(comments, 'mastercomment1')
            mc.text = ' — '.join(note_parts)

        record_frames += seg_dur_frames

    seq_duration_el.text = str(record_frames)

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def export_report_html(project):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    proj_name = project.get('name', 'Projet')
    now = datetime.now().strftime('%d/%m/%Y à %H:%M')

    CAT_LABELS = {'3':'⭐⭐⭐ Top','2':'⭐⭐ Bien','1':'⭐ OK','X':'❌ Rejeté',
                  'T':'👁️ Image','S':'🎵 Son','D':'📌 Note'}
    CAT_COLORS = {'3':'#fcd34d','2':'#a78bfa','1':'#9ca3af','X':'#ef4444',
                  'T':'#3b82f6','S':'#10b981','D':'#f59e0b'}

    annotated, total_markers, total_rejected = [], 0, 0
    for clip in clips:
        included = False
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(clip['id'], {})
            if cn.get('rating') == 'X': total_rejected += 1
            if cn.get('rating') or cn.get('markers') or (cn.get('notes','').strip()):
                included = True
            total_markers += len([m for m in (cn.get('markers') or []) if m.get('cat') != 'X'])
        if included:
            annotated.append(clip)

    # Group by day
    days = {}
    for clip in annotated:
        day = clip.get('day', '—')
        days.setdefault(day, []).append(clip)

    def clip_card(clip):
        cid = clip['id']
        parts = []
        # Ratings
        rb = ''
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(cid, {})
            r = str(cn.get('rating', ''))
            if r:
                col = CAT_COLORS.get(r, '#888')
                lbl = CAT_LABELS.get(r, r)
                rb += (f'<span class="rbadge" style="color:{col};border-color:{col};background:{col}18;">'
                       f'<b style="color:{u.get("color","#888")}">{u["name"]}</b> {lbl}</span>')
        if rb:
            parts.append(f'<div class="ratings">{rb}</div>')

        # Markers
        mrows = ''
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(cid, {})
            for m in sorted(cn.get('markers') or [], key=lambda x: x.get('time', 0)):
                cat = str(m.get('cat', ''))
                if cat == 'X': continue
                col = CAT_COLORS.get(cat, '#888')
                lbl = CAT_LABELS.get(cat, cat)
                desc = (m.get('desc','') or '').strip() or '—'
                tc = m.get('tc', '')
                mrows += (f'<tr><td class="mono">{tc}</td>'
                          f'<td><span class="dot" style="background:{col}"></span>{lbl}</td>'
                          f'<td>{desc}</td>'
                          f'<td style="color:{u.get("color","#888")};font-weight:600">{u["name"]}</td></tr>')
        if mrows:
            parts.append(f'<table class="mtbl"><tr><th>TC</th><th>Catégorie</th><th>Description</th><th>Annotateur</th></tr>{mrows}</table>')

        # Global notes
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(cid, {})
            n = (cn.get('notes','') or '').strip()
            if n:
                parts.append(f'<div class="gnote"><b style="color:{u.get("color","#888")}">{u["name"]} :</b> {n}</div>')

        body = ''.join(parts) or '<span style="color:#aaa;font-size:0.85em;">—</span>'
        meta = ' · '.join(filter(None, [clip.get('camera',''), clip.get('tc_in',''),
                                         clip.get('duration_tc',''), clip.get('resolution','')]))
        return (f'<div class="card"><div class="card-head">'
                f'<span class="cname">{clip.get("stem","")}</span>'
                f'<span class="cmeta">{meta}</span></div>'
                f'<div class="card-body">{body}</div></div>\n')

    rows = ''
    for day, day_clips in days.items():
        rows += f'<div class="day">{day}</div>\n'
        for clip in day_clips:
            rows += clip_card(clip)

    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Arial,sans-serif;background:#f4f4f8;color:#1a1a2e;font-size:13px}
.hdr{background:#1a1a2e;color:#fff;padding:20px 28px}
.hdr h1{font-size:1.3em;margin-bottom:4px}
.hdr .sub{color:rgba(255,255,255,.5);font-size:.82em;margin-bottom:10px}
.stats{display:flex;gap:12px;flex-wrap:wrap}
.stat{background:rgba(255,255,255,.12);padding:4px 12px;border-radius:20px;font-size:.82em}
.wrap{max-width:1080px;margin:0 auto;padding:20px 14px}
.day{font-size:.78em;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.08em;
     margin:18px 0 6px;border-bottom:1px solid #ddd;padding-bottom:3px}
.card{background:#fff;border-radius:8px;margin-bottom:7px;overflow:hidden;
      box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card-head{display:flex;align-items:baseline;gap:12px;padding:8px 12px;background:#ebebf0;flex-wrap:wrap}
.cname{font-weight:700;font-size:.92em}
.cmeta{font-size:.75em;color:#888}
.card-body{padding:8px 12px}
.ratings{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:7px}
.rbadge{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;
        border-radius:20px;font-size:.8em;border:1px solid}
.mtbl{width:100%;border-collapse:collapse;font-size:.8em;margin-bottom:6px}
.mtbl th{text-align:left;color:#888;padding:3px 7px;border-bottom:1px solid #eee;font-weight:600}
.mtbl td{padding:3px 7px;border-bottom:1px solid #f3f3f3;vertical-align:top}
.mtbl tr:last-child td{border-bottom:none}
.mono{font-family:monospace;color:#555;white-space:nowrap}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:3px;vertical-align:middle}
.gnote{font-size:.8em;color:#555;font-style:italic;margin-top:4px;padding:3px 8px;
       background:#f8f8f8;border-left:3px solid #ddd;border-radius:2px}
@media print{body{background:#fff}.card{box-shadow:none;border:1px solid #ddd;break-inside:avoid}}
"""

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>Rapport — {proj_name}</title>
<style>{css}</style></head><body>
<div class="hdr">
  <h1>📋 Rapport de dérushage — {proj_name}</h1>
  <div class="sub">Généré le {now}</div>
  <div class="stats">
    <span class="stat">🎬 {len(clips)} clips scannés</span>
    <span class="stat">✏️ {len(annotated)} annotés</span>
    <span class="stat">📌 {total_markers} markers</span>
    <span class="stat">❌ {total_rejected} rejetés</span>
    <span class="stat">👥 {len(users)} annotateur(s)</span>
  </div>
</div>
<div class="wrap">{rows}</div>
</body></html>"""

def export_edl(project):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])

    lines = [f"TITLE: {project['name']}_DERUSHAGE", "FCM: NON-DROP FRAME", ""]
    event_num = 0
    record_tc = 0  # destination timeline in seconds at 25fps

    for clip in clips:
        clip_fps = round(clip.get('fps', 25))
        tc_in_sec = _clip_asset_tc_sec(clip, clip_fps)
        # CMX3600 : reel limité à 8 chars. DaVinci utilise * FROM CLIP NAME pour le vrai nom.
        reel = clip.get('stem', 'AX')[:8].ljust(8)
        cat_labels = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'T': '🎨', 'S': '🎵', 'D': '📌'}

        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes or not cnotes.get('markers'): continue
            seen_src = set()
            for m in cnotes['markers']:
                if m.get('cat') == 'X': continue
                mtime = m.get('time', 0)
                # Décaler les marqueurs au début du clip d'1 frame pour éviter les
                # erreurs "TC extents" quand la TC stockée diffère d'1 frame de celle de DaVinci
                if mtime == 0:
                    mtime = 1.0 / clip_fps
                # Dédupliquer les TC source identiques (décaler d'1 frame)
                src_frame = int(round((tc_in_sec + mtime) * clip_fps))
                while src_frame in seen_src:
                    src_frame += 1
                seen_src.add(src_frame)
                actual_src_sec = src_frame / clip_fps

                event_num += 1
                src_in = seconds_to_tc(actual_src_sec, clip_fps)
                src_out = seconds_to_tc(actual_src_sec + 1, clip_fps)
                rec_in = seconds_to_tc(record_tc, 25)
                rec_out = seconds_to_tc(record_tc + 1, 25)
                record_tc += 1

                lines.append(f"{event_num:03d}  {reel} V     C        {src_in} {src_out} {rec_in} {rec_out}")
                lines.append(f"* FROM CLIP NAME: {clip.get('filename', '')}")
                cat = cat_labels.get(str(m.get('cat', '')), '')
                desc = m.get('desc', '')
                lines.append(f"* LOC: {rec_in} RED [{u.get('name') or u.get('username', '?')}] {cat} {desc}".rstrip())
                lines.append("")

    return '\n'.join(lines)

def export_markers_edl(project, filter_config=None):
    """
    EDL au format DaVinci Resolve 'Import Timeline Markers from EDL'.
    Workflow : importer d'abord le FCPXML comme timeline dans DaVinci,
    puis clic droit sur la timeline -> Timelines -> Import -> Timeline Markers from EDL.
    Les TCs de la piste timeline correspondent aux positions dans la sequence FCPXML.

    filter_config (optionnel) : MÊME contrat que export_fcpxml
      {'min_rating': N} | {'cats': [...]} | {'rejected_only': True}.
    DOIT être identique au filter_config utilisé pour le FCPXML importé, sinon le
    jeu de clips (donc toutes les positions timeline cumulées) ne correspond pas.
    L'inclusion des clips, le découpage des zones X et le FPS de séquence sont
    répliqués à l'identique depuis export_fcpxml pour que l'EDL tombe pile sur la
    timeline générée avec le même filtre — y compris l'ordre chronologique
    (jour + heure réelle de tournage, `_chrono_sort_clips`) depuis sept. 2026 :
    toute future modif de l'ordre/inclusion/segments dans export_fcpxml doit
    rester répercutée ici.
    """
    clips = _chrono_sort_clips(project.get('clips', []))
    notes = project.get('notes', {})
    users = project.get('users', [])

    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False

    # FPS de séquence = celui du 1er clip du projet, exactement comme export_fcpxml
    # (dont la <sequence> hérite du format du premier clip). DaVinci convertit les
    # HH:MM:SS:FF de l'EDL en frames via le FPS de la timeline → ils doivent coller.
    SEQ_FPS = round(clips[0].get('fps', 25)) if clips else 25

    cat_colors = {
        '3': 'ResolveColorYellow',
        '2': 'ResolveColorPurple',
        '1': 'ResolveColorCream',
        'T': 'ResolveColorSky',
        'S': 'ResolveColorGreen',
        'D': 'ResolveColorSand',
    }
    cat_labels_en = {
        '3': '3 stars', '2': '2 stars', '1': '1 star',
        'T': 'treatment', 'S': 'sound', 'D': 'marker',
    }

    lines = [f"TITLE: {project['name']}_markers", "FCM: NON-DROP FRAME", ""]
    event_num = 0
    record_offset = 0.0  # position dans la timeline en secondes (même logique que FCPXML)

    for clip in clips:
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = str(cnotes.get('rating', ''))
            if rating == 'X':
                is_rejected = True
            if fc_rejected_only:
                if rating == 'X': include_clip = True
            elif fc_min_rating is not None:
                if rating in ['1', '2', '3'] and int(rating) >= fc_min_rating:
                    include_clip = True
            elif fc_cats is not None:
                if any(m.get('cat') in fc_cats for m in cnotes.get('markers', []) if m.get('cat') != 'X'):
                    include_clip = True
            else:
                if cnotes.get('markers') or cnotes.get('notes', '').strip() or rating in ['1', '2', '3']:
                    include_clip = True

        if fc_rejected_only:
            if not include_clip: continue
        else:
            if is_rejected or not include_clip: continue

        dur = clip.get('duration_sec', 0) or 0

        # Zones X → segments conservés, IDENTIQUE à export_fcpxml. Sans ça, un clip
        # raccourci par des marqueurs X décalait tous les marqueurs des clips suivants.
        x_times = sorted(set(
            m['time'] for u in users
            for m in ((notes.get(user_note_key(u)) or {}).get(clip['id']) or {}).get('markers', [])
            if m.get('cat') == 'X'
        ))
        if not x_times:
            segments = [(0.0, dur)]
        else:
            segments = []
            prev = 0.0
            for i, t in enumerate(x_times):
                if i % 2 == 0:
                    if t > prev:
                        segments.append((prev, t))
                else:
                    prev = t
            if len(x_times) % 2 == 0 and x_times[-1] < dur:
                segments.append((x_times[-1], dur))

        kept_dur = sum(e - s for s, e in segments if e > s)
        if kept_dur <= 0:
            continue

        # Traduit un temps SOURCE (dans le clip d'origine) en temps SÉQUENCE, à
        # travers les segments conservés. Retourne None si le temps tombe dans une
        # zone coupée (marqueur à ignorer, comme dans export_fcpxml).
        def _src_to_seq(src_t):
            acc = record_offset
            for s, e in segments:
                if e <= s:
                    continue
                if src_t < s:
                    return None
                if src_t < e:
                    return acc + (src_t - s)
                acc += (e - s)
            return None

        all_markers = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue

            rating = cnotes.get('rating', '')
            global_note = cnotes.get('notes', '').strip()

            if global_note or str(rating) in ['1', '2', '3']:
                r_cat = str(rating)
                color = cat_colors.get(r_cat, 'ResolveColorBlue')
                label = f"{u.get('name') or u.get('username', '?')} {cat_labels_en.get(r_cat, 'note')}"
                if global_note:
                    label += f" - {global_note}"
                # note/rating globaux → début du 1er segment conservé
                all_markers.append({'seq': record_offset, 'label': label, 'color': color})

            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X': continue
                seq_t = _src_to_seq(m.get('time', 0))
                if seq_t is None:
                    continue
                cat = str(m.get('cat', ''))
                color = cat_colors.get(cat, 'ResolveColorBlue')
                label = f"{u.get('name') or u.get('username', '?')} {cat_labels_en.get(cat, 'marker')}"
                desc = m.get('desc', '').strip()
                if desc and desc.lower() != 'marker':
                    label += f" - {desc}"
                all_markers.append({'seq': seq_t, 'label': label, 'color': color})

        all_markers.sort(key=lambda x: x['seq'])
        seen_frames = set()
        for m in all_markers:
            frame_num = int(round(m['seq'] * SEQ_FPS))
            while frame_num in seen_frames:
                frame_num += 1
            seen_frames.add(frame_num)

            tc_in = seconds_to_tc(frame_num / SEQ_FPS, SEQ_FPS)
            tc_out = seconds_to_tc((frame_num + 1) / SEQ_FPS, SEQ_FPS)

            event_num += 1
            lines.append(f"{event_num:03d}  001      V     C        {tc_in} {tc_out} {tc_in} {tc_out}")
            lines.append(f" |C:{m['color']} |M:{m['label']} |D:1")
            lines.append("")

        record_offset += kept_dur

    return '\n'.join(lines)

def export_csv(project):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Jour', 'Camera', 'Clip', 'TC_Source_In', 'Utilisateur', 'Rating',
                     'Marker_TC', 'Categorie', 'Description', 'Notes', 'Has_Drawing'])
    
    cat_labels = {3: '⭐⭐⭐', 2: '⭐⭐', 1: '⭐', 'T': '🎨', 'S': '🎵', 'X': '❌', 'D': '📌'}
    
    for clip in clips:
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = cat_labels.get(cnotes.get('rating'), str(cnotes.get('rating', '')))
            if cnotes.get('markers'):
                for m in cnotes['markers']:
                    has_draw = '1' if m.get('drawing') else '0'
                    writer.writerow([clip.get('day', ''), clip.get('camera', ''),
                                     clip.get('stem', ''), clip.get('tc_in', ''),
                                     u.get('name') or u.get('username', '?'), rating, m.get('tc', ''),
                                     cat_labels.get(m.get('cat'), str(m.get('cat', ''))),
                                     m.get('desc', ''), cnotes.get('notes', ''), has_draw])
            elif cnotes.get('rating') or cnotes.get('notes'):
                writer.writerow([clip.get('day', ''), clip.get('camera', ''),
                                 clip.get('stem', ''), clip.get('tc_in', ''),
                                 u.get('name') or u.get('username', '?'), rating, '', '', '',
                                 cnotes.get('notes', ''), '0'])
    return output.getvalue()
