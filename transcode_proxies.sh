#!/usr/bin/env bash
# Re-encode FS5 MXF → proxy MP4 720p NVENC for J02–J06.
# - Auto-detect LTC track by Crest factor (< 2 = LTC), maps it to channel L (matches J07–J11 camera proxy convention).
# - Otherwise audio goes through as L=track1, R=track2.
# - Preserves source TC tag if present, writes BT.709 colour tags, CBR 9 Mbps.
# - Overwrites existing Sub/ClipXXXX.mp4 (no backup, per user request).

set -u
LOG="/tmp/transcode_proxies.log"
: > "$LOG"

DAYS=(
  "J02_2026_04_08"
  "J03_2026_04_09"
  "J04_2026_04_10"
  "J05_2026_04_11"
  "J06_2026_04_12"
)

start_total=$(date +%s)
total_done=0
total_fail=0

for day in "${DAYS[@]}"; do
  CLIP_DIR="D:/DRIFT_CLUB/$day/IMAGE/FS5/1/PRIVATE/XDROOT/Clip"
  SUB_DIR="D:/DRIFT_CLUB/$day/IMAGE/FS5/1/PRIVATE/XDROOT/Sub"
  if [ ! -d "$CLIP_DIR" ]; then
    echo "[$day] SKIP — pas de dossier $CLIP_DIR" | tee -a "$LOG"
    continue
  fi
  mkdir -p "$SUB_DIR"
  files=( "$CLIP_DIR"/*.MXF )
  n=${#files[@]}
  echo "" | tee -a "$LOG"
  echo "=== $day : $n MXF ===" | tee -a "$LOG"

  i=0
  for SRC in "${files[@]}"; do
    i=$((i+1))
    [ -f "$SRC" ] || continue
    name=$(basename "$SRC" .MXF)
    DST="$SUB_DIR/${name}.mp4"

    # ── LTC detection: Crest factor on 10s at offset 10s for tracks 1 and 2
    c1=$(ffmpeg -hide_banner -ss 10 -t 10 -i "$SRC" -map 0:a:0 -af "astats=metadata=1:reset=0" -f null - 2>&1 | grep "Crest factor" | head -1 | awk '{print $NF}')
    c2=$(ffmpeg -hide_banner -ss 10 -t 10 -i "$SRC" -map 0:a:1 -af "astats=metadata=1:reset=0" -f null - 2>&1 | grep "Crest factor" | head -1 | awk '{print $NF}')
    if [ -z "$c1" ]; then c1="99"; fi
    if [ -z "$c2" ]; then c2="99"; fi

    if awk "BEGIN{exit !($c2 < 2)}"; then
      AFC="[0:a:1][0:a:0]amerge=inputs=2[a]"
      mapping="L=P2(LTC) R=P1(micro)"
    elif awk "BEGIN{exit !($c1 < 2)}"; then
      AFC="[0:a:0][0:a:1]amerge=inputs=2[a]"
      mapping="L=P1(LTC) R=P2(micro)"
    else
      AFC="[0:a:0][0:a:1]amerge=inputs=2[a]"
      mapping="L=P1 R=P2 (pas de LTC)"
    fi

    TC=$(ffprobe -v error -show_entries format_tags=timecode -of csv=p=0 "$SRC")

    start=$(date +%s)
    if ffmpeg -hide_banner -loglevel error -y \
        -i "$SRC" \
        -filter_complex "[0:v:0]scale=1280:720[v];$AFC" \
        -map "[v]" -map "[a]" \
        -c:v h264_nvenc -preset p5 -tune hq -rc cbr -b:v 9M -maxrate 12M -bufsize 18M \
        -profile:v main -level 4.0 -pix_fmt yuv420p \
        -color_range pc -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
        -bf 3 -spatial_aq 1 -temporal_aq 1 \
        -c:a aac -b:a 128k -ar 48000 \
        ${TC:+-metadata timecode="$TC"} \
        -movflags +faststart \
        "$DST" 2>>"$LOG"; then
      dt=$(($(date +%s) - start))
      sz=$(stat -c %s "$DST" 2>/dev/null || echo 0)
      sz_mb=$((sz / 1024 / 1024))
      total_done=$((total_done + 1))
      echo "[$day $i/$n] OK ${name}.mp4  ${dt}s  ${sz_mb}MB  $mapping  TC=$TC" | tee -a "$LOG"
    else
      total_fail=$((total_fail + 1))
      echo "[$day $i/$n] ECHEC ${name}.mp4 — voir log" | tee -a "$LOG"
    fi
  done
done

elapsed=$(($(date +%s) - start_total))
echo "" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
echo "TERMINE en $((elapsed/60)) min $((elapsed%60)) s" | tee -a "$LOG"
echo "  Succès : $total_done"  | tee -a "$LOG"
echo "  Échecs : $total_fail" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
