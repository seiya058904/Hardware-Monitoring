#!/data/data/com.termux/files/usr/bin/sh
set -eu

NODE_HOME="${NODE_HOME:-$HOME/.local/share/hardware-monitor-node}"
NODE_CONFIG="${NODE_CONFIG:-$NODE_HOME/config.json}"
NODE_SCRIPT="${NODE_SCRIPT:-$NODE_HOME/monitor_node.py}"
PYTHON_BIN="${PYTHON_BIN:-/data/data/com.termux/files/usr/bin/python}"
FLOCK_BIN="${FLOCK_BIN:-/data/data/com.termux/files/usr/bin/flock}"
SUPERVISOR_LOCK="$NODE_HOME/supervisor.lock"
INSTANCE_LOCK_CONTENDED_EXIT=3

config_values="$("$PYTHON_BIN" - "$NODE_CONFIG" "$NODE_SCRIPT" <<'PY'
import sys
from pathlib import Path

script_path = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(script_path.parent))
from node_config import load_config

config = load_config(Path(sys.argv[1]))
print(f"{config.startup_delay_seconds}:{config.check_interval_seconds}")
PY
)"

case "$config_values" in
    *[!0-9:]*|*:*:*) exit 2 ;;
esac
startup_delay_seconds="${config_values%%:*}"
stable_window_seconds="${config_values#*:}"
[ -n "$startup_delay_seconds" ] && [ -n "$stable_window_seconds" ] || exit 2

exec 9>> "$SUPERVISOR_LOCK"
"$FLOCK_BIN" -n 9 || exit 0
supervisor_record="$("$PYTHON_BIN" - "$$" "$0" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

pid = int(sys.argv[1])
stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
fields_after_command = stat[stat.rfind(")") + 1 :].split()
if int(fields_after_command[2]) != pid:
    raise SystemExit(2)
print(json.dumps({
    "pid": pid,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "process_start_ticks": int(fields_after_command[19]),
    "script_path": str(Path(sys.argv[2]).resolve()),
}, sort_keys=True))
PY
)"
: > "$SUPERVISOR_LOCK"
printf '%s\n' "$supervisor_record" > "$SUPERVISOR_LOCK"

wake_locked=false
cleanup() {
    status=$?
    trap - EXIT
    if [ "$wake_locked" = true ]; then
        termux-wake-unlock || :
    fi
    rm -f "$SUPERVISOR_LOCK"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 0' HUP INT TERM

sleep "$startup_delay_seconds"
wake_locked=true
termux-wake-lock

while :; do
    # Five rapid crashes use the documented 5, 15, 30, 60, 300 second backoff.
    for backoff_seconds in 5 15 30 60 300; do
        started_at="$(date +%s)"
        if "$PYTHON_BIN" "$NODE_SCRIPT" --config "$NODE_CONFIG"; then
            exit 0
        else
            exit_code=$?
        fi
        [ "$exit_code" -eq "$INSTANCE_LOCK_CONTENDED_EXIT" ] && exit 0
        ended_at="$(date +%s)"

        if [ $((ended_at - started_at)) -ge "$stable_window_seconds" ]; then
            sleep 5
            continue 2
        fi
        sleep "$backoff_seconds"
    done

    if command -v termux-notification >/dev/null 2>&1; then
        termux-notification --id hardware-monitor-node-supervisor --title "Hardware monitor stopped" --content "Supervisor crashed repeatedly" || :
    fi
    exit "$exit_code"
done
