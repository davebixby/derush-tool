# -*- coding: utf-8 -*-
"""Lie chaque plan vidéo de la timeline COURANTE à toutes ses pistes son ingé
qui démarrent exactement à la même frame (`Timeline.SetClipsLinked`) — en une
seule passe sur toute la timeline, pas plan par plan à la main.

**Pourquoi ce script existe** (sept. 2026, piège #44 CLAUDE.md) : un export
DRT de Derush Tool NE contient PAS l'info de liaison vidéo/son, même quand la
timeline construite en direct côté serveur a été correctement liée avant
l'export (vérifié : `Timeline.SetClipsLinked` fonctionne bien EN DIRECT dans
Resolve — icône de lien visible, déplacement solidaire une fois « Linked
Selection » activé — mais ce lien ne survit pas à l'aller-retour export
`.drt` → réimport, y compris sur un `.drt` de référence lié manuellement par
l'utilisateur avant son propre export natif). C'est une limite du format
`.drt`/de l'export DaVinci, pas quelque chose que Derush Tool peut corriger
côté fichier. Ce script fait donc le lien APRÈS import, directement sur la
timeline réelle où ça a un effet — en une fois pour tous les plans plutôt que
de sélectionner chaque plan + ses pistes son à la main (Ctrl+Alt+L) un par un.

**À lancer à CHAQUE import d'une timeline DRT Derush**, juste après l'avoir
importée (File > Import > Timeline…) : ne supprime ni ne déplace rien,
seulement de la métadonnée de liaison (annulable par Ctrl+Z si besoin).
N'oublie pas d'activer ensuite **« Linked Selection »** dans la barre
d'outils de la timeline (icône maillon de chaîne, à côté du magnétisme) —
sans ça, un lien posé ne produit aucun déplacement solidaire (juste un
décalage temporel affiché).

Usage : coller tel quel dans la Console DaVinci (Workspace > Console, onglet
Py3 — `resolve` y est déjà défini), ou lancer depuis un terminal externe
(mêmes variables d'environnement que les autres scripts de ce projet — voir
§ API de scripting DaVinci Resolve dans CLAUDE.md).
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

groups = {}
for track_type in ('video', 'audio'):
    for i in range(1, tl.GetTrackCount(track_type) + 1):
        for item in (tl.GetItemListInTrack(track_type, i) or []):
            groups.setdefault(item.GetStart(), []).append(item)

linked = 0
skipped = 0
for items in groups.values():
    if len(items) > 1:
        tl.SetClipsLinked(items, True)
        linked += 1
    else:
        skipped += 1

print(f"{linked} plan(s) lié(s) (vidéo + pistes son ingé regroupées).")
if skipped:
    print(f"{skipped} position(s) avec un seul item (rien à lier — normal si le clip n'a pas de son ingé synchronisé).")
print()
print(">>> N'oublie pas d'activer « Linked Selection » dans la barre d'outils")
print(">>> de la timeline (icône maillon, à côté du magnétisme) pour que le")
print(">>> lien produise un déplacement solidaire vidéo/son.")
