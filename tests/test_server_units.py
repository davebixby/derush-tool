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
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import derush_server as ds


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
