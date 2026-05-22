"""Test standalone du décodeur LTC sur les proxys DRIFT.
Lit le canal L (où on a mis le LTC lors du transcode) et tente de décoder le TC.
"""
import subprocess, sys
from pathlib import Path
import numpy as np


def extract_proxy_audio_channel(proxy_path, channel=0, max_sec=10, sample_rate=48000):
    """Extract one channel of audio from proxy as int16 mono PCM array."""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error',
           '-t', str(max_sec), '-i', str(proxy_path),
           '-af', f'pan=mono|c0=c{channel}',
           '-ac', '1', '-ar', str(sample_rate),
           '-f', 's16le', '-vn', 'pipe:1']
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    if r.returncode != 0:
        return None
    arr = np.frombuffer(r.stdout, dtype=np.int16)
    return arr if arr.size > 0 else None


def decode_ltc_pcm(pcm, sample_rate, fps=25, verbose=False):
    """Decode LTC from mono PCM int16. Returns first valid TC as seconds, or None.

    LTC = biphase mark encoded:
    - bit period = sample_rate / (80 * fps)  (full period)
    - 'long' interval (~bit_period) = bit 0
    - 'short' interval (~bit_period/2) followed by another short = bit 1
    - Sync word at frame end: 0011111111111101 (LSB first, 16 bits)
    - 80 bits per frame total
    """
    if pcm is None or len(pcm) < sample_rate / fps:
        return None

    s = pcm.astype(np.float32)
    s = s - s.mean()
    if s.std() < 100:  # silence
        return None

    # Find zero crossings (sign changes)
    signs = np.sign(s)
    # Ignore exact zeros to avoid noise (rare in 16-bit audio anyway)
    signs[signs == 0] = 1
    zc = np.where(np.diff(signs) != 0)[0]
    if len(zc) < 80:
        return None

    intervals = np.diff(zc).astype(np.float32)
    bit_period = sample_rate / (80.0 * fps)
    # Threshold midway between "short" (bit_period/2) and "long" (bit_period)
    threshold = bit_period * 0.75

    if verbose:
        print(f"  sample_rate={sample_rate} fps={fps} bit_period={bit_period:.2f} samples threshold={threshold:.2f}")
        print(f"  zero crossings: {len(zc)}, intervals: {len(intervals)}")
        print(f"  interval stats: min={intervals.min():.1f} max={intervals.max():.1f} median={np.median(intervals):.1f}")

    # Decode bits
    bits = []
    i = 0
    n = len(intervals)
    while i < n:
        d = intervals[i]
        if d > threshold:
            bits.append(0)
            i += 1
        else:
            # Need another short interval to make a "1"
            if i + 1 < n and intervals[i+1] < threshold:
                bits.append(1)
                i += 2
            else:
                # Glitch (single short without pair) — skip
                i += 1

    if verbose:
        ones = sum(bits)
        print(f"  decoded {len(bits)} bits ({ones} ones, {len(bits)-ones} zeros)")

    if len(bits) < 80:
        return None

    # Sync word (LSB first in the bit stream): 0011111111111101 at end of frame
    SYNC = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]

    def bcd(bs):
        """LSB first BCD decode."""
        return sum(b << i for i, b in enumerate(bs))

    # Slide a window: a frame is 80 bits ending with the sync word
    for start in range(len(bits) - 80):
        if bits[start+64:start+80] == SYNC:
            fb = bits[start:start+80]
            ff_u = bcd(fb[0:4])
            ff_t = bcd(fb[8:10])
            ss_u = bcd(fb[16:20])
            ss_t = bcd(fb[24:27])
            mm_u = bcd(fb[32:36])
            mm_t = bcd(fb[40:43])
            hh_u = bcd(fb[48:52])
            hh_t = bcd(fb[56:58])
            ff = ff_t * 10 + ff_u
            ss = ss_t * 10 + ss_u
            mm = mm_t * 10 + mm_u
            hh = hh_t * 10 + hh_u
            if hh < 24 and mm < 60 and ss < 60 and ff < fps:
                if verbose:
                    print(f"  >>> Frame TC: {hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}  (at bit offset {start})")
                return hh * 3600 + mm * 60 + ss + ff / fps
    return None


def format_tc(sec, fps=25):
    if sec is None: return "None"
    sec = float(sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    f = int(round((sec - int(sec)) * fps)) % fps
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


if __name__ == '__main__':
    # Test on a few proxies
    tests = [
        # (label, path)
        ("J02 Clip0002 (LTC connu, piste 2 MXF)", "D:/DRIFT_CLUB/J02_2026_04_08/IMAGE/FS5/1/PRIVATE/XDROOT/Sub/Clip0002.mp4"),
        ("J02 Clip0001 (PAS de LTC)",             "D:/DRIFT_CLUB/J02_2026_04_08/IMAGE/FS5/1/PRIVATE/XDROOT/Sub/Clip0001.mp4"),
        ("J02 Clip0003 (LTC, Crest 1.26)",        "D:/DRIFT_CLUB/J02_2026_04_08/IMAGE/FS5/1/PRIVATE/XDROOT/Sub/Clip0003.mp4"),
        ("J03 Clip0001 (LTC)",                    "D:/DRIFT_CLUB/J03_2026_04_09/IMAGE/FS5/1/PRIVATE/XDROOT/Sub/Clip0001.mp4"),
        ("J07 Clip0001S03 proxy camera (LTC sur L camera)", "D:/DRIFT_CLUB/J07_2026_05_04/IMAGE/FS5/private/XDROOT/Sub/Clip0001S03.MP4"),
        ("J06 Clip0001 (PAS de LTC selon Crest)", "D:/DRIFT_CLUB/J06_2026_04_12/IMAGE/FS5/1/PRIVATE/XDROOT/Sub/Clip0001.mp4"),
    ]

    for label, path in tests:
        print(f"\n=== {label} ===")
        print(f"  {path}")
        if not Path(path).exists():
            print("  [X] Fichier introuvable")
            continue
        pcm = extract_proxy_audio_channel(path, channel=0, max_sec=5, sample_rate=48000)
        if pcm is None:
            print("  [X] Extraction audio échouée")
            continue
        print(f"  PCM extrait: {len(pcm)} samples (~{len(pcm)/48000:.1f}s)")
        tc = decode_ltc_pcm(pcm, sample_rate=48000, fps=25, verbose=True)
        print(f"  ==> TC décodé: {format_tc(tc)} ({tc})")
