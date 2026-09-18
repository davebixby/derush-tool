# -*- coding: utf-8 -*-
"""export_drt : construit une timeline DaVinci Resolve EN DIRECT via l'API de
scripting (pas un fichier hors-ligne comme les autres exports) et la
retourne au format `.drt`, natif de Resolve.

**Nécessite que DaVinci Resolve tourne, avec le projet correspondant déjà
ouvert et son Media Pool déjà complet + synchronisé** (Auto Sync Audio Based
on Timecode déjà fait — voir § Workflow FS5 dans CLAUDE.md). Contrairement à
`export_aaf`/`export_fcpxml`, ce n'est pas un fichier portable généré
hors-ligne : c'est une contrainte de déploiement assumée, choisie
explicitement par l'utilisateur après une longue enquête (voir
`D:\\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md` §21-28) qui a fermé toutes les
voies "fichier d'échange portable" (AAF construit à la main, AAF natif
Resolve, OTIO, API `AppendToTimeline`) pour le son ingé multipiste sur ce
projet — seul un DRT produit par `MediaPool.CreateTimelineFromClips` s'est
révélé fiable, et cette fonction ne peut exister que via une connexion Resolve
en direct au moment de l'export.

Recette validée (sept. 2026, §28) :
    `MediaPool.CreateTimelineFromClips(nom, [{"mediaPoolItem", "startFrame",
    "endFrame"}, ...])` construit une timeline avec TOUTES les pistes son
    ingé correctement rattachées — contrairement à `AppendToTimeline`, limité
    à 1 seul canal par plan, et contrairement à l'AAF, qui résout l'audio par
    timecode seul et se trompe de fichier dès qu'une collision de TC existe
    entre journées (§25). Cette timeline, une fois **exportée en DRT** puis
    **réimportée**, restitue le bon son sur tous les canaux — même si la
    LECTURE EN DIRECT de cette même timeline dans Resolve reste muette (bug
    Resolve distinct, §26, sans incidence ici puisqu'on n'écoute jamais la
    timeline en direct, seulement le fichier réimporté).

Le rattachement vidéo ET son se fait entièrement via l'identité live du
MediaPoolItem retrouvé dans le Media Pool (par nom de fichier + jour) — cette
fonction ne lit JAMAIS `clip['path']` ni ne résout de chemin de fichier
elle-même, à la différence des autres exports (pas besoin de
`_proj_with_resolved_export_paths`/`_proj_with_resolved_bwf_links`).
"""
import copy
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

from derush_exports import _chrono_sort_clips, _aaf_kept_segments, user_note_key, _basket_entries

_RESOLVE_API_PATHS = (
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
)
_RESOLVE_LIB_PATHS = (
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
)


class DrtExportError(Exception):
    """Erreur métier (message montrable tel quel à l'utilisateur), pas une
    exception Python brute — toujours attrapée explicitement par l'appelant
    HTTP plutôt que de remonter en 500 générique."""


def _connect_resolve():
    for api_path in _RESOLVE_API_PATHS:
        if os.path.isdir(api_path):
            os.environ.setdefault('RESOLVE_SCRIPT_API', api_path)
            break
    for lib_path in _RESOLVE_LIB_PATHS:
        if os.path.isfile(lib_path):
            os.environ.setdefault('RESOLVE_SCRIPT_LIB', lib_path)
            break
    api_path = os.environ.get('RESOLVE_SCRIPT_API')
    if not api_path:
        raise DrtExportError(
            "DaVinci Resolve introuvable sur cette machine (chemin de l'API de scripting "
            "non détecté). L'export DRT nécessite Resolve installé et lancé sur ce PC.")
    modules_path = os.path.join(api_path, 'Modules')
    if modules_path not in sys.path:
        sys.path.insert(0, modules_path)
    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        raise DrtExportError(f"Impossible de charger l'API de scripting DaVinci Resolve : {exc}")

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        raise DrtExportError(
            "DaVinci Resolve n'est pas lancé (ou l'API de scripting externe est désactivée "
            "dans Preferences > General).")
    proj_mgr = resolve.GetProjectManager()
    proj = proj_mgr.GetCurrentProject() if proj_mgr else None
    if proj is None:
        raise DrtExportError("Aucun projet ouvert dans DaVinci Resolve.")
    return resolve, proj


def _walk_media_pool(folder, path=""):
    here = (path + "/" + folder.GetName()).strip("/")
    for clip in folder.GetClipList():
        yield here, clip
    for sub in folder.GetSubFolderList():
        for item in _walk_media_pool(sub, here):
            yield item


def _find_media_pool_item(all_items, clip):
    """Retrouve le MediaPoolItem Resolve correspondant à un clip Derush, en
    matchant NOM DE FICHIER + JOUR (code court, ex. "J11" pour
    "J11_2026_05_08") — les noms seuls collisionnent entre journées (FS5
    notamment, voir piège #38/#41 CLAUDE.md). Lève une erreur explicite
    plutôt que de deviner en cas d'ambiguïté ou d'absence, cohérent avec
    toute l'enquête sur les mauvais rattachements silencieux menée sur ce
    projet — mieux vaut un export qui échoue clairement qu'un qui réussit
    sur le mauvais clip."""
    filename = clip.get('filename', '')
    day_short = (clip.get('day') or '').split('_')[0]
    matches = [
        (bin_path, item) for bin_path, item in all_items
        if item.GetName() == filename and day_short and day_short in bin_path.split('/')
    ]
    if not matches:
        raise DrtExportError(
            f"Clip introuvable dans le Media Pool DaVinci : {filename} (jour {day_short}). "
            "Le Media Pool doit contenir tous les médias référencés avant l'export.")
    if len(matches) > 1:
        bins = ', '.join(b for b, _ in matches)
        raise DrtExportError(
            f"Plusieurs clips {filename} trouvés pour le jour {day_short} dans le Media Pool "
            f"({bins}) — ambigu, export annulé plutôt que de deviner.")
    return matches[0][1]


def _included_clips(project, filter_config):
    """Même contrat de filtre/inclusion que `export_aaf`/`export_fcpxml` —
    dupliqué ici plutôt que partagé, cohérent avec la convention déjà en
    place dans ce fichier pour ces blocs d'inclusion (voir `export_markers_edl`)."""
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
            if include_clip:
                included.append(clip)
        else:
            if not is_rejected and include_clip:
                included.append(clip)
    return included, notes, users


def export_drt(project, filter_config=None):
    """Construit une timeline DaVinci Resolve EN DIRECT (via
    `MediaPool.CreateTimelineFromClips`) et la retourne exportée au format
    `.drt` (bytes). Lève `DrtExportError` (message montrable à l'utilisateur
    tel quel) en cas de problème de connexion, de Media Pool incomplet, ou
    de clip ambigu."""
    resolve, proj = _connect_resolve()
    pool = proj.GetMediaPool()
    all_items = list(_walk_media_pool(pool.GetRootFolder()))

    included, notes, users = _included_clips(project, filter_config)
    if not included:
        raise DrtExportError("Aucun clip ne correspond à ce filtre.")

    picks = [
        (clip, seg_start, seg_end)
        for clip in included
        for seg_start, seg_end in _aaf_kept_segments(clip, notes, users)
    ]
    timeline_name = (project.get('name') or 'Projet').replace('/', '_')
    return _build_and_export_drt(resolve, pool, all_items, picks, timeline_name)


def export_basket_drt(project, user_key, item_ids=None):
    """Export du panier personnel d'un utilisateur (voir `_basket_entries`) en
    timeline DaVinci Resolve — mêmes contraintes/mécanisme que `export_drt`
    (connexion live à Resolve, `CreateTimelineFromClips`), mais la sélection
    et l'ordre viennent du pré-montage de l'utilisateur, pas d'un filtre
    rating/équipe. `item_ids` (optionnel) restreint aux items cochés."""
    resolve, proj = _connect_resolve()
    pool = proj.GetMediaPool()
    all_items = list(_walk_media_pool(pool.GetRootFolder()))

    entries = _basket_entries(project, user_key, item_ids)
    if not entries:
        raise DrtExportError("Panier vide (ou aucun item sélectionné).")

    picks = [
        (clip, float(sel.get('in', 0) or 0), float(sel.get('out', 0) or 0))
        for clip, sel in entries
    ]
    timeline_name = f"{(project.get('name') or 'Projet').replace('/', '_')}_panier"
    return _build_and_export_drt(resolve, pool, all_items, picks, timeline_name)


def _seq_container_name(zf):
    return next(n for n in zf.namelist() if n.startswith('SeqContainer/') and n.endswith('.xml'))


def _parse_seq_container(raw_bytes):
    """Sépare l'en-tête (déclaration XML + commentaire `DbAppVer`/`DbPrjVer`,
    ex. `<!--DbAppVer="21.1.0.0014" DbPrjVer="17"-->`) du corps XML. On
    préserve l'en-tête TEL QUEL en chaîne plutôt que de le faire survivre à
    un aller-retour ElementTree (qui ignore les commentaires par défaut) —
    Resolve pourrait s'en servir pour valider la compatibilité de version à
    l'import, donc on ne prend pas le risque de le reconstruire nous-mêmes."""
    import re
    raw = raw_bytes.decode('utf-8')
    m = re.match(r'(<\?xml[^>]*\?>\s*(?:<!--.*?-->\s*)?)', raw, re.S)
    header = m.group(1) if m else '<?xml version="1.0" encoding="UTF-8"?>\n'
    root = ET.fromstring(raw)
    return header, root


def _serialize_seq_container(header, root):
    return (header + ET.tostring(root, encoding='unicode')).encode('utf-8')


def _all_tracks(root):
    """Toutes les pistes (vidéo + audio) de la timeline, dans l'ordre où
    elles apparaissent dans le XML — `Sm2TiTrack`, enfant unique de chaque
    `<Element>` de `VideoTrackVec`/`AudioTrackVec`."""
    tracks = []
    for vec_tag in ('VideoTrackVec', 'AudioTrackVec'):
        vec = root.find(vec_tag)
        if vec is None:
            continue
        for track_el in vec.findall('Element'):
            tracks.append(list(track_el)[0])
    return tracks


def _discover_media_refs(base_bytes, unique_clip_ids):
    """Associe chaque `clip['id']` de `unique_clip_ids` (dans l'ORDRE où ils
    ont été passés à `CreateTimelineFromClips`) au `MediaRef` (GUID interne
    DaVinci) que Resolve leur a assigné dans la timeline de base — en
    supposant que la piste vidéo restitue les clips dans le même ordre que
    la liste d'entrée (déjà une hypothèse implicite de tout ce module, cf.
    tri chronologique avant construction des `infos`). Vérifié empiriquement
    (sept. 2026) sur un `.drt` généré manuellement dans DaVinci avec 4 coupes
    d'un même plan : chaque piste (vidéo et chacune des pistes son ingé)
    porte un `<Sm2Ti*Clip>` par coupe, DbId unique, mais un `<MediaRef>`
    IDENTIQUE pour toutes les coupes d'un même plan — c'est cette identité
    partagée qui permet de retrouver, pour une piste donnée, TOUS les blocs
    appartenant à un clip (voir `_collect_clip_templates`)."""
    import zipfile
    import io
    zin = zipfile.ZipFile(io.BytesIO(base_bytes))
    _, root = _parse_seq_container(zin.read(_seq_container_name(zin)))
    video_vec = root.find('VideoTrackVec')
    video_tracks = [list(el)[0] for el in video_vec.findall('Element')] if video_vec is not None else []
    video_track = max(video_tracks, key=lambda t: len(t.find('Items').findall('Element')) if t.find('Items') is not None else 0, default=None)
    items = video_track.find('Items').findall('Element') if video_track is not None else []
    if len(items) != len(unique_clip_ids):
        raise DrtExportError(
            "Incohérence interne entre les clips demandés et la timeline construite par "
            "DaVinci Resolve (nombre de plans différent) — export annulé plutôt que de "
            "deviner quelle coupe correspond à quel clip.")
    mapping = {}
    for clip_id, item_el in zip(unique_clip_ids, items):
        clip_el = list(item_el)[0]
        mapping[clip_id] = clip_el.findtext('MediaRef')
    return mapping


def _collect_clip_templates(root):
    """Pour chaque `MediaRef` présent dans la timeline, la liste des
    `(piste, item_element)` où ce clip a du contenu — un par piste vidéo/son
    sur laquelle il est câblé. Sert de gabarit pour cloner un plan déjà
    présent une fois de plus, avec tout son câblage audio multipiste intact
    (contrairement à une réimportation du fichier, qui perd la synchro son
    ingé — voir piège #42 CLAUDE.md)."""
    templates = {}
    for track in _all_tracks(root):
        items_el = track.find('Items')
        if items_el is None:
            continue
        for item_el in items_el.findall('Element'):
            clip_el = list(item_el)[0]
            mref = clip_el.findtext('MediaRef')
            templates.setdefault(mref, []).append((track, item_el))
    return templates


_ZSTD_MAGIC = bytes.fromhex("28b52ffd")
_UUID_RE_LINK = __import__('re').compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _decode_link_frame(hexstr):
    """`FieldsBlob` (hex) → `(header_9_octets, payload_decompressé)` si ce
    champ contient bien la trame de liaison ZSTD, sinon `(None, None)`.
    Format retro-ingénié (sept. 2026, voir CLAUDE.md § Export DRT — liaison
    vidéo/son) : 9 octets d'en-tête (`00 00 00 02` + longueur trame+1 en
    big-endian + `81`) suivis d'une trame ZSTD (signature `28 B5 2F FD`)."""
    import zstandard as zstd
    b = bytes.fromhex(hexstr)
    i = b.find(_ZSTD_MAGIC)
    if i < 0:
        return None, None
    header, frame = b[:i], b[i:]
    try:
        payload = zstd.ZstdDecompressor().decompress(frame, max_output_size=1 << 24)
    except zstd.ZstdError:
        return None, None
    return header, payload


def _encode_link_frame(header, payload):
    import zstandard as zstd
    frame = zstd.ZstdCompressor(level=19).compress(payload)
    new_len = len(frame) + 1
    new_header = header[:4] + new_len.to_bytes(4, 'big') + b'\x81'
    return (new_header + frame).hex()


def _find_uuids_in_payload(payload):
    """Décoder tout le payload d'un coup en UTF-16 casse silencieusement sur
    certaines séquences d'entiers binaires internes au format (fausses paires
    de substituts Unicode) et fait perdre des UUID sans erreur visible — ne
    garder que les octets imprimables ASCII est la méthode fiable."""
    ascii_only = bytes(x for x in payload if 32 <= x < 127).decode()
    return _UUID_RE_LINK.findall(ascii_only)


def _fix_clip_linking(root):
    """Réécrit le `FieldsBlob` de chaque item (vidéo + chaque piste audio)
    pour qu'il liste les VRAIS `DbId` des autres items de son groupe de
    liaison — le groupe étant défini par `(MediaRef, Start)` : tous les items
    qui démarrent exactement à la même frame ET viennent du même plan source
    (PAS tous les items partageant seulement le même `MediaRef` — plusieurs
    coupes d'un même plan partagent légitimement leur `MediaRef`, mais
    chacune a son propre groupe de liaison limité à sa position).

    Nécessaire : un item cloné par `_splice_repeated_clips` hérite du
    `FieldsBlob` de son gabarit tel quel, qui référence encore les `DbId` du
    groupe D'ORIGINE du gabarit (une autre position sur la timeline) — jamais
    ceux de sa propre position. Sans ce correctif, DaVinci n'affiche aucune
    icône de liaison vidéo/son sur les plans coupés plusieurs fois. Appelée
    aussi sur la timeline de base (un seul plan par position) en filet de
    sécurité — un groupe déjà correct n'est pas modifié.

    Retro-ingénié et vérifié (sept. 2026) par comparaison automatisée entre
    un `.drt` de référence généré nativement par DaVinci (groupes déjà
    corrects) et un export Derush Tool réel (groupes faux sur toutes les
    coupes clonées, confirmés correctement réparés par ce même mécanisme et
    reconfirmés par réimport réel dans DaVinci — icône de liaison présente
    sur chaque coupe, y compris les plans coupés plusieurs fois)."""
    groups = {}
    for track in _all_tracks(root):
        items_el = track.find('Items')
        if items_el is None:
            continue
        for item_el in items_el.findall('Element'):
            clip_el = list(item_el)[0]
            key = (clip_el.findtext('MediaRef'), clip_el.findtext('Start'))
            groups.setdefault(key, []).append(clip_el)

    for members in groups.values():
        if len(members) < 2:
            continue
        real_ids = [m.get('DbId') for m in members]
        for clip_el in members:
            blob_el = clip_el.find('FieldsBlob')
            if blob_el is None or not blob_el.text:
                continue
            header, payload = _decode_link_frame(blob_el.text)
            if header is None:
                continue
            found = _find_uuids_in_payload(payload)
            replacements = [i for i in real_ids if i != clip_el.get('DbId')]
            if len(found) != len(replacements):
                # Topologie inattendue (nombre de pistes différent de celui du
                # gabarit) : on laisse tel quel plutôt que de deviner un
                # appariement — cohérent avec le reste de ce module (mieux
                # vaut un lien manquant qu'un lien faux sur le mauvais item).
                continue
            new_payload = payload
            for old_uuid, new_uuid in zip(found, replacements):
                for enc in ('utf-16-be', 'utf-16-le'):
                    old_b = old_uuid.encode(enc)
                    if old_b in new_payload:
                        new_payload = new_payload.replace(old_b, new_uuid.encode(enc), 1)
                        break
            blob_el.text = _encode_link_frame(header, new_payload)


def _apply_linking_fix(drt_bytes):
    """Applique `_fix_clip_linking` à un `.drt` déjà construit (chemin sans
    coupe répétée, qui ne passe pas par `_splice_repeated_clips`) — parse,
    corrige, réécrit le zip."""
    import zipfile
    import io

    zin = zipfile.ZipFile(io.BytesIO(drt_bytes))
    seq_name = _seq_container_name(zin)
    header, root = _parse_seq_container(zin.read(seq_name))
    _fix_clip_linking(root)
    new_seq_xml = _serialize_seq_container(header, root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            zout.writestr(name, new_seq_xml if name == seq_name else zin.read(name))
    return buf.getvalue()


def _splice_repeated_clips(base_bytes, ordered_picks):
    """Reconstruit la timeline pour que `ordered_picks`
    (`[(media_ref, in_frames, duration_frames), ...]`, dans l'ordre final
    voulu) apparaisse sur chaque piste — y compris les répétitions d'un même
    `media_ref` (plusieurs coupes du même plan). Chaque occurrence est un
    CLONE d'un des blocs déjà construits par `CreateTimelineFromClips` pour
    ce clip (voir `_collect_clip_templates`), avec un nouveau DbId et
    `Start`/`Duration`/`In` mis à jour — tous les autres champs (`MediaRef`,
    `MediaStartTime`, `PreConformMediaExtents`, `MediaTimemapBA`,
    `FieldsBlob`) sont conservés tels quels : vérifié constants d'une coupe à
    l'autre du même plan sur un `.drt` de référence généré nativement par
    DaVinci (4 coupes, sept. 2026) — seuls `Start`/`Duration`/`In` varient
    réellement avec le découpage.

    Toutes les pistes sont vidées puis reconstruites dans le même ordre
    (`cursor` avance de `duration_frames` à chaque pick, pas de trou) — les
    positions d'origine posées par `CreateTimelineFromClips` sur la timeline
    de base ne correspondent qu'à l'ordre dédupliqué utilisé pour cet appel,
    pas à l'ordre réel voulu par l'utilisateur (qui peut entrelacer les
    coupes d'un même plan avec d'autres plans)."""
    import zipfile
    import io
    import uuid

    zin = zipfile.ZipFile(io.BytesIO(base_bytes))
    seq_name = _seq_container_name(zin)
    header, root = _parse_seq_container(zin.read(seq_name))

    templates = _collect_clip_templates(root)
    tracks = _all_tracks(root)
    for track in tracks:
        items_el = track.find('Items')
        if items_el is not None:
            for child in list(items_el):
                items_el.remove(child)

    cursor = None
    for media_ref, in_frames, duration_frames in ordered_picks:
        tpls = templates.get(media_ref)
        if not tpls:
            raise DrtExportError(
                "Incohérence interne : un plan référencé dans la sélection est absent de la "
                "timeline de base construite par DaVinci Resolve — export annulé.")
        if cursor is None:
            first_clip_el = list(tpls[0][1])[0]
            cursor = int(first_clip_el.findtext('Start') or '0')
        for track, template_item in tpls:
            new_item = copy.deepcopy(template_item)
            clip_el = list(new_item)[0]
            clip_el.set('DbId', str(uuid.uuid4()))
            clip_el.find('Start').text = str(cursor)
            clip_el.find('Duration').text = str(duration_frames)
            in_el = clip_el.find('In')
            in_el.text = str(in_frames) if in_frames else None
            track.find('Items').append(new_item)
        cursor += duration_frames

    _fix_clip_linking(root)
    new_seq_xml = _serialize_seq_container(header, root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            zout.writestr(name, new_seq_xml if name == seq_name else zin.read(name))
    return buf.getvalue()


def _build_and_export_drt(resolve, pool, all_items, picks, timeline_name):
    """Cœur commun à `export_drt`/`export_basket_drt` : résout chaque
    `(clip, seg_start_sec, seg_end_sec)` en `MediaPoolItem` + startFrame/
    endFrame, construit une timeline DE BASE via `CreateTimelineFromClips`
    (seule méthode qui restitue le son ingé multipiste — voir docstring du
    module) avec UNE SEULE occurrence de chaque plan distinct, l'exporte en
    `.drt`, supprime la timeline temporaire — puis, si des plans étaient
    repris plusieurs fois dans `picks` (plusieurs coupes du même plan),
    reconstruit la timeline finale en clonant les blocs XML déjà câblés par
    Resolve pour ce plan (`_splice_repeated_clips`), plutôt que de rappeler
    l'API : `CreateTimelineFromClips` ne place qu'une seule instance par
    MediaPoolItem par appel (les occurrences suivantes du même objet sont
    silencieusement ignorées, sans erreur, si on les laisse passer), et une
    duplication du clip via `MediaPool.ImportMedia` a été essayée puis
    abandonnée : la synchro son ingé (Auto Sync Audio Based on Timecode) est
    un état du `MediaPoolItem` d'origine, pas du fichier — un clip réimporté
    n'en hérite pas et joue le mauvais son (piège #42 CLAUDE.md). La
    manipulation XML directe évite ce problème par construction : chaque
    coupe supplémentaire est un clone du bloc DÉJÀ correctement synchronisé
    par Resolve pour ce plan, jamais un nouveau média importé.

    `timeline_name` reçoit un suffixe horodaté : `CreateTimelineFromClips`
    échoue si une timeline de ce nom existe déjà dans le projet — ce qui
    arrive systématiquement dès qu'un .drt précédent a été réimporté (le nom
    du fichier redevient le nom d'une timeline persistante dans le projet
    DaVinci)."""
    import datetime as _dt

    valid_picks = [(clip, s, e) for clip, s, e in picks if e - s > 0]
    if not valid_picks:
        raise DrtExportError("Aucun segment à exporter.")

    seen_ids = set()
    unique_picks = []
    for clip, s, e in valid_picks:
        if clip['id'] in seen_ids:
            continue
        seen_ids.add(clip['id'])
        unique_picks.append((clip, s, e))

    infos = []
    for clip, seg_start, seg_end in unique_picks:
        fps = round(clip.get('fps', 25) or 25)
        mp_item = _find_media_pool_item(all_items, clip)
        infos.append({
            "mediaPoolItem": mp_item,
            "startFrame": int(round(seg_start * fps)),
            "endFrame": int(round(seg_end * fps)),
        })

    timeline_name = f"{timeline_name}_{_dt.datetime.now():%Y%m%d_%H%M%S}"
    tl = pool.CreateTimelineFromClips(timeline_name, infos)
    if not tl:
        raise DrtExportError("Échec de la création de la timeline dans DaVinci Resolve (CreateTimelineFromClips).")

    # PAS de `Timeline.SetClipsLinked` ici (essayé puis retiré, sept. 2026) : la
    # méthode fonctionne réellement en direct sur la timeline temporaire (icône
    # de lien visible, déplacement solidaire une fois "Linked Selection" activé
    # dans DaVinci), mais ce lien ne survit PAS à l'export `.drt` + réimport —
    # vérifié à la fois sur un `.drt` de référence lié manuellement par
    # l'utilisateur (Ctrl+Alt+L) avant son propre export natif, et sur un export
    # réel via ce module : dans les deux cas, aucune trace de liaison après
    # réimport. Limite du format `.drt`/de l'export DaVinci, pas de notre code
    # — voir `link_timeline_clips_resolve.py` pour le contournement (script à
    # coller dans la Console DaVinci APRÈS import, qui fait exactement ce que
    # cette fonction tentait de faire ici, mais sur la timeline déjà importée
    # où ça a un effet réel). Piège #44 CLAUDE.md.

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.drt')
    os.close(tmp_fd)
    os.remove(tmp_path)
    try:
        ok = tl.Export(tmp_path, resolve.EXPORT_DRT)
        if not ok:
            raise DrtExportError("Échec de l'export DRT côté DaVinci Resolve.")
        with open(tmp_path, 'rb') as fh:
            base_bytes = fh.read()
    finally:
        pool.DeleteTimelines([tl])
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if len(valid_picks) == len(unique_picks):
        return _apply_linking_fix(base_bytes)

    media_ref_by_clip_id = _discover_media_refs(base_bytes, [c['id'] for c, _, _ in unique_picks])
    ordered = []
    for clip, seg_start, seg_end in valid_picks:
        fps = round(clip.get('fps', 25) or 25)
        start_frame = int(round(seg_start * fps))
        end_frame = int(round(seg_end * fps))
        ordered.append((media_ref_by_clip_id[clip['id']], start_frame, end_frame - start_frame))

    return _splice_repeated_clips(base_bytes, ordered)
