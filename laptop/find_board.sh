#!/usr/bin/env bash
# Find the ESP32-P4 board on the current network (works on phone hotspots
# where the Mac can't show you a DHCP lease table).
#
# Usage:  bash laptop/find_board.sh
# Then:   export ESP32_HOST=<printed ip>
#
# How it works: derives your subnet from the Wi-Fi interface, ping-sweeps it
# to populate the ARP cache, then probes each live host for the firmware's
# HTTP signature (camera :81/stream.mjpg, motor/thermal :80/control/status).

set -u
DEV="${1:-en0}"

ip="$(ipconfig getifaddr "$DEV" 2>/dev/null)"
if [ -z "$ip" ]; then
  echo "✘ $DEV has no IP — join the hotspot first, then re-run." >&2
  exit 1
fi
mask="$(ipconfig getoption "$DEV" subnet_mask 2>/dev/null)"
router="$(ipconfig getoption "$DEV" router 2>/dev/null)"
echo "Mac on $DEV: $ip  mask=$mask  gateway=$router"

# Build the /24 (or smaller) host range. Phone hotspots are tiny; we sweep the
# whole last octet which covers iPhone /28 and Android /24 alike.
base="$(echo "$ip" | cut -d. -f1-3)"
echo "Sweeping ${base}.1-254 ..."

# Concurrent ping sweep to populate ARP, then read neighbors.
for n in $(seq 1 254); do
  ( ping -c1 -W120 -t1 "${base}.${n}" >/dev/null 2>&1 ) &
done
wait

echo
echo "Live neighbors:"
arp -a -n 2>/dev/null | grep "($base\." | grep -v incomplete

echo
echo "Probing for board firmware signature ..."
found=""
for n in $(seq 1 254); do
  host="${base}.${n}"
  arp -n "$host" >/dev/null 2>&1 || continue
  # Camera port :81 carries the MJPEG stream; control on :80.
  if curl -s --max-time 2 -o /dev/null -w '%{http_code}' "http://${host}:80/control/status" 2>/dev/null | grep -q '200'; then
    echo "  ✔ ${host}  (responded on :80/control/status — this is the board)"
    found="$host"
  elif curl -s --max-time 2 "http://${host}:81/stream.mjpg" 2>/dev/null | head -c 32 | grep -qi 'multipart\|jpeg\|boundary'; then
    echo "  ✔ ${host}  (camera stream on :81 — this is the board)"
    found="$host"
  fi
done

echo
if [ -n "$found" ]; then
  echo "Board found:  export ESP32_HOST=$found"
else
  echo "No board responded. Either it isn't on this network (it still has the"
  echo "SKKU enterprise firmware flashed and won't join WPA2-Personal), or it's"
  echo "still booting. Re-flash with the hotspot creds, wait ~15s, re-run."
fi
