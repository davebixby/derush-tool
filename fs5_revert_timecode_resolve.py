# -*- coding: utf-8 -*-
"""
DRIFT_CLUB — RETOUR ARRIÈRE : remet le Start Timecode des FS5 à la valeur du
fichier MXF (celle que DaVinci lit nativement).

À utiliser si, après fs5_fix_timecode_resolve.py, les clips FS5 sont passés
« Media Offline » : le montage picture avait été conformé sur l'ANCIEN TC, donc
changer le Start TC casse les références de la timeline.

Après ce retour arrière :
  - la timeline picture revient online
  - on synchronise le son par WAVEFORM (qui ignore le timecode) :
      Media Pool -> sélection FS5 -> Clip Attributes -> Audio -> isoler le canal micro
      puis sélection FS5 + WAV -> clic droit -> Auto Sync Audio -> Based on Waveform

UTILISATION : identique à l'autre script.
  Workspace ▸ Console ▸ onglet Py3 ▸ coller ▸ Entrée.
  Tourne en DRY-RUN d'abord ; passe DRY_RUN = False pour appliquer.

Idempotent. Si Resolve rame (reconform), attends ; s'il crashe, relance,
il reprend là où il s'était arrêté (affiche « = déjà bon » pour les faits).
"""

DRY_RUN = True   # <-- passe à False pour appliquer

import re

# ── "<dossier jour>/<fichier>" -> Start TC du fichier MXF (HH:MM:SS:FF @ 25) ────
TC = {
  "J02_2026_04_08/Clip0001.MXF": "00:00:02:13",
  "J02_2026_04_08/Clip0002.MXF": "17:14:14:03",
  "J02_2026_04_08/Clip0003.MXF": "17:21:20:21",
  "J02_2026_04_08/Clip0004.MXF": "17:50:21:15",
  "J03_2026_04_09/Clip0001.MXF": "11:01:45:19",
  "J03_2026_04_09/Clip0002.MXF": "11:11:35:13",
  "J03_2026_04_09/Clip0003.MXF": "11:12:54:20",
  "J03_2026_04_09/Clip0004.MXF": "11:45:47:17",
  "J03_2026_04_09/Clip0005.MXF": "11:49:38:01",
  "J03_2026_04_09/Clip0006.MXF": "11:54:35:01",
  "J03_2026_04_09/Clip0007.MXF": "11:57:47:07",
  "J03_2026_04_09/Clip0008.MXF": "12:01:06:20",
  "J03_2026_04_09/Clip0009.MXF": "12:09:44:22",
  "J03_2026_04_09/Clip0010.MXF": "12:43:38:16",
  "J03_2026_04_09/Clip0011.MXF": "12:45:14:20",
  "J03_2026_04_09/Clip0012.MXF": "12:48:40:15",
  "J03_2026_04_09/Clip0013.MXF": "12:52:16:23",
  "J03_2026_04_09/Clip0014.MXF": "13:16:05:00",
  "J03_2026_04_09/Clip0015.MXF": "13:22:41:04",
  "J03_2026_04_09/Clip0016.MXF": "00:12:42:24",
  "J03_2026_04_09/Clip0017.MXF": "00:25:41:03",
  "J03_2026_04_09/Clip0018.MXF": "00:27:13:15",
  "J03_2026_04_09/Clip0019.MXF": "00:37:45:15",
  "J03_2026_04_09/Clip0020.MXF": "01:10:14:12",
  "J03_2026_04_09/Clip0021.MXF": "01:20:39:01",
  "J03_2026_04_09/Clip0022.MXF": "01:27:19:04",
  "J03_2026_04_09/Clip0023.MXF": "01:27:42:09",
  "J03_2026_04_09/Clip0024.MXF": "01:35:48:06",
  "J03_2026_04_09/Clip0025.MXF": "01:40:18:07",
  "J03_2026_04_09/Clip0026.MXF": "01:47:16:16",
  "J04_2026_04_10/Clip0001.MXF": "20:11:08:13",
  "J04_2026_04_10/Clip0002.MXF": "20:25:27:22",
  "J04_2026_04_10/Clip0003.MXF": "20:27:19:22",
  "J04_2026_04_10/Clip0004.MXF": "20:28:07:19",
  "J04_2026_04_10/Clip0005.MXF": "20:31:25:06",
  "J04_2026_04_10/Clip0006.MXF": "20:42:05:17",
  "J04_2026_04_10/Clip0007.MXF": "20:44:49:17",
  "J04_2026_04_10/Clip0008.MXF": "20:45:59:07",
  "J04_2026_04_10/Clip0009.MXF": "20:55:15:18",
  "J04_2026_04_10/Clip0010.MXF": "20:56:53:24",
  "J04_2026_04_10/Clip0011.MXF": "21:08:38:13",
  "J04_2026_04_10/Clip0012.MXF": "21:17:22:13",
  "J04_2026_04_10/Clip0013.MXF": "21:25:07:24",
  "J04_2026_04_10/Clip0014.MXF": "21:26:54:12",
  "J04_2026_04_10/Clip0015.MXF": "00:08:33:09",
  "J04_2026_04_10/Clip0016.MXF": "00:09:48:13",
  "J04_2026_04_10/Clip0017.MXF": "00:20:37:11",
  "J04_2026_04_10/Clip0018.MXF": "00:22:34:02",
  "J04_2026_04_10/Clip0019.MXF": "00:23:55:18",
  "J04_2026_04_10/Clip0020.MXF": "00:26:40:11",
  "J04_2026_04_10/Clip0021.MXF": "00:29:48:17",
  "J04_2026_04_10/Clip0022.MXF": "00:39:22:14",
  "J04_2026_04_10/Clip0023.MXF": "00:46:58:07",
  "J04_2026_04_10/Clip0024.MXF": "00:48:44:19",
  "J04_2026_04_10/Clip0025.MXF": "01:05:50:14",
  "J04_2026_04_10/Clip0026.MXF": "01:42:16:17",
  "J04_2026_04_10/Clip0027.MXF": "01:42:46:11",
  "J04_2026_04_10/Clip0028.MXF": "01:46:41:17",
  "J04_2026_04_10/Clip0029.MXF": "01:49:22:24",
  "J04_2026_04_10/Clip0030.MXF": "01:51:05:00",
  "J04_2026_04_10/Clip0031.MXF": "01:52:12:10",
  "J04_2026_04_10/Clip0032.MXF": "01:52:53:01",
  "J04_2026_04_10/Clip0033.MXF": "01:55:02:03",
  "J04_2026_04_10/Clip0034.MXF": "01:57:21:11",
  "J04_2026_04_10/Clip0035.MXF": "02:02:08:15",
  "J04_2026_04_10/Clip0036.MXF": "02:02:55:21",
  "J04_2026_04_10/Clip0037.MXF": "02:09:18:24",
  "J04_2026_04_10/Clip0038.MXF": "03:07:20:16",
  "J04_2026_04_10/Clip0039.MXF": "03:08:10:18",
  "J04_2026_04_10/Clip0040.MXF": "03:11:22:16",
  "J05_2026_04_11/Clip0001.MXF": "23:08:23:05",
  "J05_2026_04_11/Clip0002.MXF": "23:39:55:03",
  "J05_2026_04_11/Clip0003.MXF": "23:40:20:24",
  "J05_2026_04_11/Clip0004.MXF": "23:41:17:16",
  "J05_2026_04_11/Clip0005.MXF": "01:04:07:16",
  "J05_2026_04_11/Clip0006.MXF": "01:13:49:20",
  "J05_2026_04_11/Clip0007.MXF": "02:21:03:17",
  "J05_2026_04_11/Clip0008.MXF": "02:22:34:05",
  "J05_2026_04_11/Clip0009.MXF": "02:23:33:21",
  "J05_2026_04_11/Clip0010.MXF": "02:25:56:04",
  "J05_2026_04_11/Clip0011.MXF": "02:28:18:01",
  "J05_2026_04_11/Clip0012.MXF": "02:42:36:00",
  "J05_2026_04_11/Clip0013.MXF": "02:54:15:19",
  "J05_2026_04_11/Clip0014.MXF": "02:55:29:08",
  "J05_2026_04_11/Clip0015.MXF": "03:17:38:18",
  "J06_2026_04_12/Clip0001.MXF": "02:33:36:22",
  "J06_2026_04_12/Clip0002.MXF": "02:39:23:11",
  "J06_2026_04_12/Clip0003.MXF": "02:45:25:15",
  "J06_2026_04_12/Clip0004.MXF": "02:46:02:08",
  "J06_2026_04_12/Clip0005.MXF": "03:26:42:10",
  "J06_2026_04_12/Clip0006.MXF": "03:29:12:08",
  "J06_2026_04_12/Clip0007.MXF": "03:30:28:05",
  "J06_2026_04_12/Clip0008.MXF": "03:31:02:04",
  "J06_2026_04_12/Clip0009.MXF": "04:06:41:07",
  "J06_2026_04_12/Clip0010.MXF": "04:08:04:20",
  "J06_2026_04_12/Clip0011.MXF": "04:08:29:08",
  "J06_2026_04_12/Clip0012.MXF": "04:15:45:07",
  "J06_2026_04_12/Clip0013.MXF": "04:21:14:24",
  "J06_2026_04_12/Clip0014.MXF": "04:25:38:07",
  "J06_2026_04_12/Clip0015.MXF": "04:26:20:13",
  "J06_2026_04_12/Clip0016.MXF": "04:27:11:12",
  "J06_2026_04_12/Clip0017.MXF": "04:28:15:00",
  "J07_2026_05_04/Clip0001.MXF": "04:07:05:09",
  "J07_2026_05_04/Clip0002.MXF": "04:15:36:12",
  "J07_2026_05_04/Clip0003.MXF": "04:43:38:04",
  "J07_2026_05_04/Clip0004.MXF": "04:54:48:03",
  "J07_2026_05_04/Clip0005.MXF": "05:00:47:04",
  "J07_2026_05_04/Clip0006.MXF": "05:03:14:18",
  "J07_2026_05_04/Clip0007.MXF": "05:05:18:04",
  "J07_2026_05_04/Clip0008.MXF": "05:07:48:11",
  "J07_2026_05_04/Clip0009.MXF": "05:19:12:07",
  "J07_2026_05_04/Clip0010.MXF": "05:31:17:14",
  "J07_2026_05_04/Clip0011.MXF": "05:33:00:19",
  "J07_2026_05_04/Clip0012.MXF": "05:35:37:16",
  "J07_2026_05_04/Clip0013.MXF": "05:37:56:02",
  "J07_2026_05_04/Clip0014.MXF": "05:38:34:14",
  "J07_2026_05_04/Clip0015.MXF": "05:41:34:20",
  "J07_2026_05_04/Clip0016.MXF": "05:44:58:03",
  "J07_2026_05_04/Clip0017.MXF": "05:48:38:03",
  "J07_2026_05_04/Clip0018.MXF": "05:58:26:02",
  "J07_2026_05_04/Clip0019.MXF": "05:59:48:04",
  "J07_2026_05_04/Clip0020.MXF": "06:18:28:08",
  "J07_2026_05_04/Clip0021.MXF": "06:25:16:16",
  "J07_2026_05_04/Clip0022.MXF": "06:38:31:00",
  "J07_2026_05_04/Clip0023.MXF": "06:40:07:23",
  "J10_2026_05_07/Clip0001.MXF": "04:57:16:22",
  "J10_2026_05_07/Clip0002.MXF": "04:58:15:16",
  "J10_2026_05_07/Clip0003.MXF": "04:59:39:00",
  "J10_2026_05_07/Clip0004.MXF": "05:11:23:05",
  "J10_2026_05_07/Clip0005.MXF": "05:51:27:23",
  "J10_2026_05_07/Clip0006.MXF": "05:53:25:11",
  "J10_2026_05_07/Clip0007.MXF": "06:01:17:11",
  "J10_2026_05_07/Clip0008.MXF": "06:09:52:09",
  "J10_2026_05_07/Clip0009.MXF": "06:11:43:09",
  "J10_2026_05_07/Clip0010.MXF": "06:33:41:22",
  "J10_2026_05_07/Clip0011.MXF": "06:39:24:00",
  "J10_2026_05_07/Clip0012.MXF": "06:40:29:03",
  "J10_2026_05_07/Clip0013.MXF": "06:46:31:02",
  "J11_2026_05_08/Clip0001.MXF": "01:48:02:19",
  "J11_2026_05_08/Clip0002.MXF": "01:57:24:02",
  "J11_2026_05_08/Clip0003.MXF": "02:01:21:02",
  "J11_2026_05_08/Clip0004.MXF": "02:04:08:09",
  "J11_2026_05_08/Clip0005.MXF": "02:25:58:05",
  "J11_2026_05_08/Clip0006.MXF": "02:33:19:19",
  "J11_2026_05_08/Clip0007.MXF": "07:45:42:15",
  "J11_2026_05_08/Clip0008.MXF": "07:50:34:21",
  "J11_2026_05_08/Clip0009.MXF": "07:53:57:11",
}

DAY_RE = re.compile(r"(J\d\d_\d{4}_\d\d_\d\d)")


def get_resolve():
    try:
        return resolve
    except NameError:
        pass
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve")
    except Exception:
        try:
            return bmd.scriptapp("Resolve")  # noqa: F821
        except Exception:
            return None


def walk(folder, out):
    for c in folder.GetClipList():
        out.append(c)
    for sub in folder.GetSubFolderList():
        walk(sub, out)


def main():
    R = get_resolve()
    if R is None:
        print("ERREUR : API Resolve inaccessible. Lance depuis la Console de Resolve.")
        return
    proj = R.GetProjectManager().GetCurrentProject()
    if not proj:
        print("ERREUR : aucun projet ouvert.")
        return

    clips = []
    walk(proj.GetMediaPool().GetRootFolder(), clips)
    print("Media Pool : %d entrees" % len(clips))
    print("Mode : %s  (RETOUR ARRIERE vers le TC du fichier)\n"
          % ("DRY-RUN" if DRY_RUN else "APPLICATION"))

    done = same = fail = 0
    for c in clips:
        fp = (c.GetClipProperty("File Path") or "").replace("\\", "/")
        if not fp.lower().endswith(".mxf"):
            continue
        name = fp.split("/")[-1]
        m = DAY_RE.search(fp)
        if not m:
            continue
        key = m.group(1) + "/" + name
        if key not in TC:
            continue
        target = TC[key]
        cur = c.GetClipProperty("Start TC") or "?"
        if cur == target:
            same += 1
            continue
        if DRY_RUN:
            done += 1
            print("  -> remettrait  %-30s  %s  ->  %s" % (key, cur, target))
            continue
        ok = c.SetClipProperty("Start TC", target)
        if ok:
            done += 1
            print("  OK remis       %-30s  %s  ->  %s" % (key, cur, target))
        else:
            fail += 1
            print("  ECHEC API      %-30s  (cible %s)" % (key, target))

    print("\n=== Bilan ===")
    print("  %s : %d" % ("a remettre" if DRY_RUN else "remis", done))
    print("  deja au TC fichier : %d" % same)
    print("  echecs API         : %d" % fail)
    print("")
    print("Ensuite : verifie que la timeline picture est de nouveau online,")
    print("puis synchronise le son par WAVEFORM (isole le canal micro d'abord).")


main()
