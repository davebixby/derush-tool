# -*- coding: utf-8 -*-
"""
DRIFT_CLUB — Diagnostic des collisions de timecode dans le Media Pool DaVinci
==============================================================================

Pourquoi : le SMPTE ne code pas la date — deux fichiers de journées différentes
peuvent couvrir la même plage de timecode. Déjà documenté comme cause de
mauvais rattachement pour *Auto Sync Audio Based on Timecode* (voir CLAUDE.md,
piège #39). Ce script (lecture seule, ne modifie RIEN) répond à la même
question pour le rattachement AAF (§19/§22 de
D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md) : à l'instant précis où l'audio d'un
clip donné doit démarrer, combien d'autres fichiers du Media Pool couvrent ce
même instant ?

Origine : script fourni par un audit externe (`check_tc_collisions_resolve.py`,
conçu pour tourner collé dans la console DaVinci avec `resolve` déjà injecté).
Adapté ici pour tourner en terminal externe via `dvr.scriptapp('Resolve')`, et
CORRIGÉ d'un bug trouvé en l'utilisant sur le vrai Media Pool DRIFT_CLUB (641
clips, 14 sept. 2026) : la propriété `Frames` de l'API Resolve est VIDE sur les
clips AUDIO (WAV) dans cette version — la version d'origine calculait donc une
durée de 0 pour tous les WAV, donnant `end == start` et un FAUX NÉGATIF total
sur toute collision impliquant un WAV (0 recouvrement trouvé au lieu des 481
réels). Fix : `End TC` (fiable sur les deux types de clip) comme source
primaire de la fin de plage, `Frames` seulement en repli si `End TC` manque.

Trois sections en sortie :
  1. Paires de WAV dont la plage de TC se recouvre, de journées différentes.
  2. Noms de fichiers (vidéo ou audio) portés par plusieurs clips.
  3. Tous les clips dont la plage de TC contient un timecode CIBLE précis —
     la question décisive : "si j'importe un AAF qui demande le fichier X à
     ce timecode, combien de candidats DaVinci pourrait-il confondre avec X ?"

UTILISATION (terminal externe, PAS la console DaVinci) :
  DaVinci Resolve doit déjà tourner avec le projet ouvert. Puis, en PowerShell,
  depuis ce dossier :
    $env:RESOLVE_SCRIPT_API = "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting"
    $env:RESOLVE_SCRIPT_LIB  = "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll"
    $env:PYTHONPATH = "$env:RESOLVE_SCRIPT_API\\Modules\\;$env:PYTHONPATH"
    python check_tc_collisions_resolve.py

Modifier CIBLE ci-dessous pour vérifier un autre timecode/clip.
"""

import collections
import os
import sys

os.environ.setdefault("RESOLVE_SCRIPT_API",
                       r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting")
os.environ.setdefault("RESOLVE_SCRIPT_LIB",
                       r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
sys.path.insert(0, os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules"))

import DaVinciResolveScript as dvr

# Timecode à vérifier en priorité, ou None pour sauter la section 3.
# Exemple : le vrai début de 2-6T02.WAV, attendu pour Clip0008.MXF/J11.
CIBLE = "16:42:37:00"

FPS = 25


def tc_to_frames(tc, fps=FPS):
    if not tc:
        return None
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return None
    try:
        h, m, s, f = (int(p) for p in parts)
    except ValueError:
        return None
    return ((h * 60 + m) * 60 + s) * fps + f


def frames_to_tc(fr, fps=FPS):
    if fr is None:
        return "-"
    return "%02d:%02d:%02d:%02d" % (
        fr // (fps * 3600), (fr // (fps * 60)) % 60, (fr // fps) % 60, fr % fps
    )


def walk(folder, path=""):
    here = (path + "/" + folder.GetName()).strip("/")
    for clip in folder.GetClipList():
        yield here, clip
    for sub in folder.GetSubFolderList():
        for item in walk(sub, here):
            yield item


def main():
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        print("Resolve non accessible via scripting.")
        return
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        print("Aucun projet ouvert.")
        return
    print("Projet:", project.GetName())
    pool = project.GetMediaPool()

    clips = []
    for bin_path, clip in walk(pool.GetRootFolder()):
        name = clip.GetName()
        props = clip.GetClipProperty()
        begin = tc_to_frames(props.get("Start TC"))
        # "Frames" est vide sur les clips audio (WAV) dans cette version de
        # l'API — "End TC" est fiable sur les deux types, donc source
        # primaire ; repli sur "Frames" pour les rares cas où End TC manque.
        end = tc_to_frames(props.get("End TC"))
        if end is None:
            try:
                dur = int(props.get("Frames"))
            except (TypeError, ValueError):
                dur = 0
            end = (begin + dur) if begin is not None else None
        clips.append({
            "bin": bin_path,
            "name": name,
            "path": props.get("File Path"),
            "start": begin,
            "end": end,
            "audio_ch": props.get("Audio Ch"),
        })

    print("Media Pool : %d clips analyses.\n" % len(clips))

    # ---------------------------------------------------------------- 1
    print("=" * 72)
    print("1. WAV dont la plage de timecode en recouvre une autre (jours differents)")
    print("=" * 72)
    wavs = [c for c in clips
            if c["path"] and c["path"].lower().endswith(".wav")
            and c["start"] is not None and c["end"] is not None]
    wavs.sort(key=lambda c: c["start"])
    overlaps = 0
    for i, a in enumerate(wavs):
        for b in wavs[i + 1:]:
            if b["start"] >= a["end"]:
                break
            if a["bin"] == b["bin"]:
                continue  # même journée : normal, pas une ambiguïté entre jours
            overlaps += 1
            print("  %s [%s]  %s -> %s" % (a["name"], a["bin"],
                                           frames_to_tc(a["start"]), frames_to_tc(a["end"])))
            print("  %s [%s]  %s -> %s" % (b["name"], b["bin"],
                                           frames_to_tc(b["start"]), frames_to_tc(b["end"])))
            print("  ---")
    if not overlaps:
        print("  Aucun recouvrement entre journees differentes.")
    else:
        print("\n  %d recouvrement(s). Chacun est un candidat possible pour un mauvais" % overlaps)
        print("  rattachement si DaVinci resout par timecode.")

    # ---------------------------------------------------------------- 2
    print()
    print("=" * 72)
    print("2. Noms de fichiers portes par plusieurs clips")
    print("=" * 72)
    by_name = collections.defaultdict(list)
    for c in clips:
        by_name[c["name"]].append(c)
    dupes = 0
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        dupes += 1
        print("  %s  (%d exemplaires)" % (name, len(group)))
        for c in group:
            print("      [%s] TC %s  %s" % (c["bin"], frames_to_tc(c["start"]), c["path"]))
    if not dupes:
        print("  Aucun nom en double.")

    # ---------------------------------------------------------------- 3
    if CIBLE:
        print()
        print("=" * 72)
        print("3. Clips dont la plage contient %s" % CIBLE)
        print("=" * 72)
        target = tc_to_frames(CIBLE)
        hits = [c for c in clips
                if c["start"] is not None and c["end"] is not None
                and c["start"] <= target < c["end"]]
        if not hits:
            print("  Aucun clip ne couvre ce timecode.")
        for c in hits:
            print("  %-24s [%s]  %s -> %s  (%s canaux)  %s"
                  % (c["name"], c["bin"], frames_to_tc(c["start"]),
                     frames_to_tc(c["end"]), c["audio_ch"], c["path"]))
        if len(hits) > 1:
            print("\n  Plusieurs candidats : c'est exactement la situation ou DaVinci")
            print("  peut rattacher le mauvais fichier tout en affichant le bon nom.")

    print("\nTermine (aucune modification effectuee).")


main()
