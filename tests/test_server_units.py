"""Tests unitaires des fonctions pures de derush_server.py.

Complète les tests E2E Playwright (*.spec.js) : ici on teste en isolation la
logique critique — hachage de mots de passe, timecodes, fusion de sync, etc.

Lancer depuis la racine du projet :
    python -m unittest tests.test_server_units
ou :
    python tests/test_server_units.py
"""
import os
import sys
import hashlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import derush_server as ds
import derush_exports as de

try:
    import numpy as _np_probe
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class TestPassword(unittest.TestCase):
    """Audit 2.1 — hachage PBKDF2 salé + migration depuis SHA-256."""

    def test_pbkdf2_roundtrip(self):
        h = ds.hash_password('motdepasse')
        self.assertTrue(h.startswith('pbkdf2$'))
        self.assertTrue(ds.verify_password('motdepasse', h))

    def test_wrong_password_rejected(self):
        h = ds.hash_password('bon')
        self.assertFalse(ds.verify_password('mauvais', h))

    def test_salt_is_random(self):
        # Deux hachages du même mot de passe doivent différer (sel aléatoire).
        self.assertNotEqual(ds.hash_password('x'), ds.hash_password('x'))

    def test_legacy_sha256_still_verifies(self):
        legacy = hashlib.sha256('vieux'.encode()).hexdigest()
        self.assertTrue(ds.verify_password('vieux', legacy))
        self.assertTrue(ds.is_legacy_hash(legacy))
        self.assertFalse(ds.is_legacy_hash(ds.hash_password('x')))

    def test_empty_hash_rejected(self):
        self.assertFalse(ds.verify_password('x', ''))
        self.assertFalse(ds.verify_password('x', None))


class TestTimecode(unittest.TestCase):
    def test_tc_to_seconds(self):
        self.assertEqual(ds.tc_to_seconds('01:00:00:00', 25), 3600)
        self.assertEqual(ds.tc_to_seconds('00:00:01:00', 25), 1)
        self.assertAlmostEqual(ds.tc_to_seconds('00:00:00:12', 25), 12 / 25)

    def test_tc_roundtrip(self):
        for sec in (0, 1, 60, 3661, 7325.4):
            tc = ds.seconds_to_tc(sec, 25)
            self.assertAlmostEqual(ds.tc_to_seconds(tc, 25),
                                   round(sec * 25) / 25, places=6)

    def test_tc_empty(self):
        self.assertIsNone(ds.tc_to_seconds('', 25))
        self.assertEqual(ds.seconds_to_tc(None, 25), '')

    def test_semicolon_drop_frame(self):
        # Le ';' du drop-frame doit être accepté comme un ':'.
        self.assertEqual(ds.tc_to_seconds('01:00:00;00', 25), 3600)


class TestUserKey(unittest.TestCase):
    def test_user_note_key_priority(self):
        self.assertEqual(ds.user_note_key({'id': 'abc', 'username': 'Bob'}), 'abc')
        self.assertEqual(ds.user_note_key({'username': 'Paola'}), 'Paola')
        self.assertEqual(ds.user_note_key({'name': 'Seb'}), 'Seb')

    def test_find_project_user_case_insensitive(self):
        proj = {'users': [{'username': 'Paola'}, {'name': 'Sebastien'}]}
        self.assertIsNotNone(ds.find_project_user(proj, 'paola'))
        self.assertIsNotNone(ds.find_project_user(proj, 'SEBASTIEN'))
        self.assertIsNone(ds.find_project_user(proj, 'inconnu'))


class TestPidFromPath(unittest.TestCase):
    """Audit 1.1 — extraction du pid pour le verrou par projet."""

    def test_extracts_pid(self):
        self.assertEqual(ds._pid_from_path('/api/project/drift_club/notes'), 'drift_club')
        self.assertEqual(ds._pid_from_path('/api/project/drift_club/export/fcpxml?x=1'),
                         'drift_club')

    def test_no_pid(self):
        self.assertIsNone(ds._pid_from_path('/api/login'))
        self.assertIsNone(ds._pid_from_path('/api/project/create'))
        self.assertIsNone(ds._pid_from_path('/'))


class TestMergeProjects(unittest.TestCase):
    """Audit §5 — la sync ne doit plus ressusciter une suppression."""

    def test_own_uid_preserves_others_deletions(self):
        # A a supprimé un marqueur (remote à jour). La machine de B a une copie
        # périmée de notes[A] : elle ne doit PAS la re-publier.
        remote = {'notes': {'A': {'c1': {'markers': []}}}, 'users': [], 'discussions': {}}
        local_b = {'notes': {'A': {'c1': {'markers': ['vieux']}},
                             'B': {'c2': {'markers': ['b']}}},
                   'users': [], 'discussions': {}}
        merged = ds.merge_projects(local_b, remote, own_uid='B')
        self.assertEqual(merged['notes']['A']['c1']['markers'], [])
        self.assertEqual(merged['notes']['B']['c2']['markers'], ['b'])

    def test_legacy_behaviour_without_own_uid(self):
        remote = {'notes': {'A': {'x': 1}}, 'users': [], 'discussions': {}}
        local_b = {'notes': {'A': {'x': 2}}, 'users': [], 'discussions': {}}
        merged = ds.merge_projects(local_b, remote)  # own_uid=None → ancien comportement
        self.assertEqual(merged['notes']['A'], {'x': 2})

    def test_own_uid_without_local_notes(self):
        remote = {'notes': {'A': {'x': 1}}, 'users': [], 'discussions': {}}
        local_b = {'notes': {}, 'users': [], 'discussions': {}}
        merged = ds.merge_projects(local_b, remote, own_uid='B')
        self.assertEqual(merged['notes'], {'A': {'x': 1}})

    def test_discussions_union(self):
        remote = {'notes': {}, 'users': [], 'discussions':
                  {'c1': {'m1': [{'ts': '2026-01-01', 'text': 'r'}]}}}
        local = {'notes': {}, 'users': [], 'discussions': {}}
        merged = ds.merge_projects(local, remote, own_uid='B')
        self.assertEqual(len(merged['discussions']['c1']['m1']), 1)


class TestResolveRelpath(unittest.TestCase):
    """Audit — résolveur de chemins tolérant au zero-padding."""

    def test_literal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'IMAGE' / '01').mkdir(parents=True)
            (root / 'IMAGE' / '01' / 'clip.mxf').write_text('x')
            self.assertIsNotNone(
                ds._resolve_relpath_tolerant(root, 'IMAGE/01/clip.mxf'))

    def test_zero_padding_variant(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'IMAGE' / '01').mkdir(parents=True)
            (root / 'IMAGE' / '01' / 'clip.mxf').write_text('x')
            # On demande IMAGE/1 — le résolveur doit retrouver IMAGE/01.
            r = ds._resolve_relpath_tolerant(root, 'IMAGE/1/clip.mxf')
            self.assertIsNotNone(r)
            self.assertEqual(Path(r).name, 'clip.mxf')

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(
                ds._resolve_relpath_tolerant(Path(td), 'nexiste/pas.mxf'))


class TestExportFcpxml(unittest.TestCase):
    """Tests unitaires de derush_exports.export_fcpxml."""

    def _clip(self, cid, **kw):
        base = {'id': cid, 'path': f'/media/{cid}.mxf', 'fps': 25,
                'duration_sec': 10, 'tc_in': '00:00:00:00',
                'stem': cid, 'filename': cid + '.mxf', 'resolution': '1920x1080'}
        base.update(kw)
        return base

    def _project(self, clips, notes_by_uid):
        users = [{'id': uid} for uid in notes_by_uid]
        return {'name': 'Test', 'clips': clips, 'notes': notes_by_uid, 'users': users}

    def _asset_names(self, xml_str):
        """Retourne l'ensemble des name= des éléments <asset> dans le XML."""
        body = '\n'.join(l for l in xml_str.splitlines()
                         if not l.startswith('<?xml') and not l.startswith('<!DOCTYPE'))
        root = ET.fromstring(body.strip())
        return {a.get('name') for a in root.iter('asset')}

    def test_rated_clip_included(self):
        clips = [self._clip('c1')]
        proj = self._project(clips, {'u1': {'c1': {'rating': '3', 'markers': [], 'notes': ''}}})
        self.assertIn('c1.mxf', self._asset_names(de.export_fcpxml(proj)))

    def test_rejected_clip_excluded(self):
        clips = [self._clip('c1')]
        proj = self._project(clips, {'u1': {'c1': {'rating': 'X', 'markers': [], 'notes': ''}}})
        self.assertNotIn('c1.mxf', self._asset_names(de.export_fcpxml(proj)))

    def test_unannotated_clip_excluded(self):
        clips = [self._clip('c1')]
        proj = self._project(clips, {})
        self.assertNotIn('c1.mxf', self._asset_names(de.export_fcpxml(proj)))

    def test_filter_min_rating_2(self):
        clips = [self._clip('c1'), self._clip('c2')]
        proj = self._project(clips, {
            'u1': {'c1': {'rating': '1', 'markers': [], 'notes': ''},
                   'c2': {'rating': '2', 'markers': [], 'notes': ''}},
        })
        assets = self._asset_names(de.export_fcpxml(proj, filter_config={'min_rating': 2}))
        self.assertNotIn('c1.mxf', assets)
        self.assertIn('c2.mxf', assets)

    def test_note_text_only_included(self):
        clips = [self._clip('c1')]
        proj = self._project(clips, {'u1': {'c1': {'rating': '', 'markers': [], 'notes': 'Beau plan'}}})
        self.assertIn('c1.mxf', self._asset_names(de.export_fcpxml(proj)))

    def test_marker_generates_element(self):
        clips = [self._clip('c1')]
        proj = self._project(clips, {
            'u1': {'c1': {'rating': '2',
                          'markers': [{'time': 1.0, 'cat': 'T', 'desc': 'détail'}],
                          'notes': ''}}
        })
        xml_str = de.export_fcpxml(proj)
        body = '\n'.join(l for l in xml_str.splitlines()
                         if not l.startswith('<?xml') and not l.startswith('<!DOCTYPE'))
        root = ET.fromstring(body.strip())
        self.assertGreaterEqual(len(list(root.iter('marker'))), 1)


@unittest.skipUnless(HAS_NUMPY, 'numpy requis pour les tests LTC')
class TestLtcDecoder(unittest.TestCase):
    """Tests du décodeur LTC (_ltc_decode_pcm dans derush_server.py).

    Signal synthétique : biphase mark, 80 bits/trame, 25 fps, 48 kHz.
    bit 0 → 1 intervalle ≈ bp,  bit 1 → 2 intervalles ≈ bp/2 chacun.
    """

    def _bcd(self, val, n):
        return [(val >> i) & 1 for i in range(n)]

    def _frame_bits(self, hh, mm, ss, ff, fps=25):
        b = [0] * 80
        b[0:4]   = self._bcd(ff % 10, 4)
        b[8:10]  = self._bcd(ff // 10, 2)
        b[16:20] = self._bcd(ss % 10, 4)
        b[24:27] = self._bcd(ss // 10, 3)
        b[32:36] = self._bcd(mm % 10, 4)
        b[40:43] = self._bcd(mm // 10, 3)
        b[48:52] = self._bcd(hh % 10, 4)
        b[56:58] = self._bcd(hh // 10, 2)
        b[64:80] = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]
        return b

    def _make_pcm(self, hh, mm, ss, ff, fps=25, sr=48000, num_frames=5):
        """Signal PCM synthétique pour num_frames trames LTC à partir de hh:mm:ss:ff."""
        import numpy as np
        bp = sr // (80 * fps)  # ≈24 samples/bit à 48kHz/25fps

        transitions = []
        pos = 0
        for fn in range(num_frames):
            total_ff = ff + fn
            cur_ss = ss + total_ff // fps
            cur_ff = total_ff % fps
            cur_mm = mm + cur_ss // 60
            cur_ss = cur_ss % 60
            cur_hh = hh + cur_mm // 60
            cur_mm = cur_mm % 60
            for bit in self._frame_bits(cur_hh, cur_mm, cur_ss, cur_ff, fps):
                if bit == 0:
                    pos += bp
                    transitions.append(pos)
                else:
                    pos += bp // 2
                    transitions.append(pos)
                    pos += bp - bp // 2
                    transitions.append(pos)

        pcm = np.zeros(pos + bp, dtype=np.int16)
        polarity, prev = 10000, 0
        for t in transitions:
            pcm[prev:t] = polarity
            polarity = -polarity
            prev = t
        pcm[prev:] = polarity
        return pcm

    def test_none_returns_none(self):
        self.assertIsNone(ds._ltc_decode_pcm(None))

    def test_silence_returns_none(self):
        import numpy as np
        self.assertIsNone(ds._ltc_decode_pcm(np.zeros(48000, dtype=np.int16)))

    def test_short_input_returns_none(self):
        import numpy as np
        self.assertIsNone(ds._ltc_decode_pcm(np.zeros(10, dtype=np.int16)))

    def test_valid_ltc_decoded(self):
        """01:00:00:00 doit décoder à ≈ 3600 secondes."""
        result = ds._ltc_decode_pcm(self._make_pcm(1, 0, 0, 0),
                                    sample_rate=48000, fps=25, min_consecutive_frames=3)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 3600.0, delta=0.1)

    def test_nonzero_tc_decoded(self):
        """01:23:45:10 doit décoder à ≈ 5025.4 secondes."""
        hh, mm, ss, ff, fps = 1, 23, 45, 10, 25
        expected = hh * 3600 + mm * 60 + ss + ff / fps
        result = ds._ltc_decode_pcm(self._make_pcm(hh, mm, ss, ff),
                                    sample_rate=48000, fps=25, min_consecutive_frames=3)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, expected, delta=0.1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
