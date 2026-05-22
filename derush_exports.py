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


def export_fcpxml(project, filter_config=None):
    clips = project.get('clips', [])
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

        # Use the actual source TC as start so DaVinci can validate it against
        # the embedded TC in the MXF file (they must match or DaVinci shows
        # "timecode extents" errors). tc_in is stored correctly after FX6 byte-reversal.
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
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


def export_xml_fcp7(project, filter_config=None):
    """
    Export Adobe Premiere Pro XML (Final Cut Pro 7 XML Interchange Format, v5).
    Schéma : <xmeml><sequence><media><video><track><clipitem>…
    Compatible Premiere Pro CC 2017+ (et toute version qui sait lire l'XML FCP7).
    Mêmes règles de filtrage et coupes X que export_fcpxml.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False

    def _rate_elem(fps_int):
        """<rate><timebase>N</timebase><ntsc>FALSE</ntsc></rate>"""
        # NTSC fractional rates : 23.976, 29.97, 59.94 → ntsc=TRUE
        # Ici on traite des fps entiers depuis round(clip.fps), donc ntsc=FALSE
        e = ET.Element('rate')
        ET.SubElement(e, 'timebase').text = str(fps_int)
        ET.SubElement(e, 'ntsc').text = 'FALSE'
        return e

    def _tc_elem(tc_sec, fps_int):
        """<timecode><rate>…</rate><string>HH:MM:SS:FF</string><frame>N</frame>…"""
        frames = int(round(tc_sec * fps_int))
        tc_str = seconds_to_tc(tc_sec, fps_int)
        e = ET.Element('timecode')
        e.append(_rate_elem(fps_int))
        ET.SubElement(e, 'string').text = tc_str
        ET.SubElement(e, 'frame').text = str(frames)
        ET.SubElement(e, 'displayformat').text = 'NDF'
        return e

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
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
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
    clips = project.get('clips', [])
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
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
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

        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
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
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
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

def export_markers_edl(project):
    """
    EDL au format DaVinci Resolve 'Import Timeline Markers from EDL'.
    Workflow : importer d'abord le FCPXML comme timeline dans DaVinci,
    puis clic droit sur la timeline -> Timelines -> Import -> Timeline Markers from EDL.
    Les TCs de la piste timeline correspondent aux positions dans la sequence FCPXML.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])

    SEQ_FPS = 25  # FPS de la séquence (doit correspondre au FCPXML)

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
    record_offset = 0  # position dans la timeline en secondes (même logique que FCPXML)

    for clip in clips:
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            if cnotes.get('rating') == 'X':
                is_rejected = True
            if cnotes.get('markers') or cnotes.get('notes', '').strip() or str(cnotes.get('rating', '')) in ['1', '2', '3']:
                include_clip = True

        if is_rejected or not include_clip:
            continue

        dur = clip.get('duration_sec', 0) or 0

        # Collecter tous les marqueurs de tous les utilisateurs
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
                all_markers.append({'time': 0, 'label': label, 'color': color})

            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X': continue
                cat = str(m.get('cat', ''))
                color = cat_colors.get(cat, 'ResolveColorBlue')
                label = f"{u.get('name') or u.get('username', '?')} {cat_labels_en.get(cat, 'marker')}"
                desc = m.get('desc', '').strip()
                if desc and desc.lower() != 'marker':
                    label += f" - {desc}"
                all_markers.append({'time': m.get('time', 0), 'label': label, 'color': color})

        all_markers.sort(key=lambda x: x['time'])
        seen_frames = set()
        for m in all_markers:
            seq_time = record_offset + m['time']
            frame_num = int(round(seq_time * SEQ_FPS))
            while frame_num in seen_frames:
                frame_num += 1
            seen_frames.add(frame_num)

            tc_in = seconds_to_tc(frame_num / SEQ_FPS, SEQ_FPS)
            tc_out = seconds_to_tc((frame_num + 1) / SEQ_FPS, SEQ_FPS)

            event_num += 1
            lines.append(f"{event_num:03d}  001      V     C        {tc_in} {tc_out} {tc_in} {tc_out}")
            lines.append(f" |C:{m['color']} |M:{m['label']} |D:1")
            lines.append("")

        record_offset += dur

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
