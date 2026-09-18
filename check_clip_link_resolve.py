# -*- coding: utf-8 -*-
"""Diagnostic (sept. 2026) : teste `Timeline.SetClipsLinked` en conditions
réelles pour savoir si (a) l'appel a un effet visible sur la timeline
COURANTE de DaVinci, et (b) si cette API existe réellement dans cette version
de Resolve (piège connu de ce projet : `hasattr()` renvoie toujours True sur
ces objets, jamais fiable pour vérifier qu'une méthode existe).

Ne supprime rien, ne modifie que la timeline actuellement affichée
(annulable par Ctrl+Z dans DaVinci après coup).

Usage : ouvrir un projet DaVinci, une timeline avec au moins un clip vidéo +
une piste son synchronisée sélectionnée comme timeline courante, puis SOIT
coller ce script tel quel dans la Console DaVinci (Workspace > Console,
onglet Py3 — `resolve` y est déjà défini, le script le détecte et saute la
connexion externe), SOIT le lancer depuis un terminal externe (mêmes
variables d'environnement que les autres scripts de diagnostic de ce projet
— voir § API de scripting DaVinci Resolve dans CLAUDE.md).
"""
import sys

if 'resolve' not in globals():
    # Pas dans la Console DaVinci (qui prédéfinit `resolve`) : connexion externe.
    import os

    _RESOLVE_API_PATHS = (
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
    )
    _RESOLVE_LIB_PATHS = (
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    )
    for p in _RESOLVE_API_PATHS:
        if os.path.isdir(p):
            os.environ.setdefault('RESOLVE_SCRIPT_API', p)
            break
    for p in _RESOLVE_LIB_PATHS:
        if os.path.isfile(p):
            os.environ.setdefault('RESOLVE_SCRIPT_LIB', p)
            break
    api_path = os.environ.get('RESOLVE_SCRIPT_API')
    if not api_path:
        print("RESOLVE_SCRIPT_API introuvable — DaVinci Resolve est-il installé sur ce PC ?")
        sys.exit(1)
    sys.path.insert(0, os.path.join(api_path, 'Modules'))

    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')

if resolve is None:
    print("DaVinci Resolve n'est pas lancé (ou l'API de scripting externe est désactivée).")
    sys.exit(1)
proj = resolve.GetProjectManager().GetCurrentProject()
if proj is None:
    print("Aucun projet ouvert.")
    sys.exit(1)
tl = proj.GetCurrentTimeline()
if tl is None:
    print("Aucune timeline courante sélectionnée dans ce projet.")
    sys.exit(1)
print("Timeline courante :", tl.GetName())

video_items = tl.GetItemListInTrack('video', 1) or []
if not video_items:
    print("Aucun item vidéo sur la piste vidéo 1 de cette timeline.")
    sys.exit(1)
v0 = video_items[0]
start = v0.GetStart()
print("1er item vidéo :", v0.GetName(), "Start =", start)

audio_items = []
for i in range(1, tl.GetTrackCount('audio') + 1):
    for it in (tl.GetItemListInTrack('audio', i) or []):
        if it.GetStart() == start:
            audio_items.append(it)
print(f"{len(audio_items)} item(s) audio trouvé(s) à la même position (Start={start}).")

items = [v0] + audio_items
if len(items) < 2:
    print("Pas assez d'items à cette position pour tester la liaison (besoin d'au moins vidéo + 1 audio).")
    sys.exit(1)

print()
print("hasattr(tl, 'SetClipsLinked') =", hasattr(tl, 'SetClipsLinked'),
      "  (rappel : toujours True sur ces objets, ne prouve rien)")

try:
    result = tl.SetClipsLinked(items, True)
    print("tl.SetClipsLinked(items, True) a retourné :", repr(result))
except Exception as e:
    print("EXCEPTION en appelant SetClipsLinked :", repr(e))

print()
print(">>> Regarde MAINTENANT dans DaVinci (sans rien exporter) : sélectionne")
print(">>> ce clip vidéo dans la timeline et essaie de le déplacer un peu.")
print(">>> Le son suit-il visuellement ? (Ctrl+Z pour annuler le déplacement)")
print(">>> Rapporte le résultat : lié tout de suite dans DaVinci, ou pas du tout ?")
