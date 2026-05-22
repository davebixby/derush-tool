"""derush_core — fonctions utilitaires pures de Derush Tool.

Module feuille : ne dépend QUE de la stdlib, n'importe aucun autre module du
projet → pas de dépendance circulaire possible.

Extrait de derush_server.py le 22 mai 2026 (audit §4 — découpage du monolithe,
étape 1). derush_server le ré-importe, tous les appels existants restent valides.
"""
import hashlib
import secrets


# ─── Hachage de mots de passe — PBKDF2 salé (audit 2.1) ──────────────────────
_PBKDF2_ITERS = 200_000


def hash_password(pw, salt=None):
    """Hache un mot de passe en PBKDF2-HMAC-SHA256 (salé).
    Format stocké : 'pbkdf2$<iters>$<salt_hex>$<hash_hex>'."""
    if salt is None:
        salt = secrets.token_bytes(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def is_legacy_hash(stored):
    """True si le hash est dans l'ancien format SHA-256 nu (à re-hacher)."""
    return bool(stored) and not str(stored).startswith('pbkdf2$')


def verify_password(pw, stored):
    """Vérifie un mot de passe contre un hash stocké. Gère le nouveau format
    PBKDF2 et l'ancien SHA-256 nu (pour la migration transparente)."""
    if not stored:
        return False
    stored = str(stored)
    if stored.startswith('pbkdf2$'):
        try:
            _, iters, salt_hex, hash_hex = stored.split('$')
            dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'),
                                     bytes.fromhex(salt_hex), int(iters))
            return secrets.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    # Ancien format : SHA-256 nu, non salé
    return secrets.compare_digest(hashlib.sha256(pw.encode('utf-8')).hexdigest(), stored)


# ─── Timecode ────────────────────────────────────────────────────────────────
def tc_to_seconds(tc_str, fps=25):
    if not tc_str:
        return None
    parts = tc_str.replace(';', ':').split(':')
    if len(parts) == 4:
        h, m, s, f = [int(p) for p in parts]
        return h * 3600 + m * 60 + s + f / fps
    return None


def seconds_to_tc(sec, fps=25):
    if sec is None:
        return ''
    fps_int = round(fps)
    total_frames = int(round(sec * fps_int))
    f = total_frames % fps_int
    total_secs = total_frames // fps_int
    s = total_secs % 60
    total_mins = total_secs // 60
    m = total_mins % 60
    h = total_mins // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def seconds_to_rational(sec, fps=25):
    fps_int = round(fps)
    frames = int(round(sec * fps_int))
    return f"{frames}/{fps_int}s"


# ─── Utilisateurs de projet ──────────────────────────────────────────────────
def find_project_user(proj, username):
    """Trouve l'entrée user d'un projet par username (insensible à la casse).
    Gère aussi l'ancien champ 'name'."""
    for u in proj.get('users', []):
        uname = u.get('username') or u.get('name', '')
        if uname.lower() == username.lower():
            return u
    return None


def user_note_key(u):
    """Clé sous laquelle sont rangées les notes de cet utilisateur (supporte
    l'ancien modèle par id et le nouveau par username)."""
    return u.get('id') or u.get('username') or u.get('name', '')
