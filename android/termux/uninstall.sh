#!/data/data/com.termux/files/usr/bin/sh
set -eu

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
NODE_HOME="$HOME/.local/share/hardware-monitor-node"
NODE_SCRIPT="$NODE_HOME/monitor_node.py"
NODE_LOCK="$NODE_HOME/monitor.lock"
BOOT_WRAPPER="$HOME/.termux/boot/start-hardware-monitor-node"
PURGE_DATA=false

usage() {
    printf '%s\n' 'usage: uninstall.sh [--purge-data]' >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --purge-data)
            [ "$PURGE_DATA" = false ] || usage
            PURGE_DATA=true
            shift
            ;;
        *) usage ;;
    esac
done

trusted_command_if_available() {
    command_path="$(command -v "$1" 2>/dev/null || :)"
    case "$command_path" in
        "$PREFIX"/bin/*) printf '%s\n' "$command_path" ;;
        *) printf '%s' '' ;;
    esac
}

stop_verified_node() {
    [ -f "$NODE_SCRIPT" ] && [ -f "$NODE_LOCK" ] || return 0
    python_path="$(trusted_command_if_available python)"
    [ -n "$python_path" ] || return 0
    group_and_pid="$(PYTHONDONTWRITEBYTECODE=1 "$python_path" - "$NODE_HOME" "$NODE_LOCK" "$NODE_SCRIPT" <<'PY'
import json
import os
from pathlib import Path
import signal
import sys

node_home = Path(sys.argv[1]).resolve()
lock_path = Path(sys.argv[2])
script_path = Path(sys.argv[3]).resolve()
if not node_home.is_dir() or not script_path.is_file():
    raise SystemExit(0)

try:
    record = json.loads(lock_path.read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or set(record) != {"pid", "started_at", "process_start_ticks", "script_path"}
        or type(record["pid"]) is not int
        or record["pid"] <= 0
        or type(record["process_start_ticks"]) is not int
        or record["process_start_ticks"] < 0
        or not isinstance(record["started_at"], str)
        or not record["started_at"]
        or record["script_path"] != str(script_path)
    ):
        raise SystemExit(0)
    os.kill(record["pid"], 0)
    cmdline = Path(f"/proc/{record['pid']}/cmdline").read_bytes().split(b"\0")
    command = [os.fsdecode(argument) for argument in cmdline if argument]
    stat = Path(f"/proc/{record['pid']}/stat").read_text(encoding="utf-8")
    fields_after_command = stat[stat.rfind(")") + 1 :].split()
    if str(script_path) not in command or int(fields_after_command[19]) != record["process_start_ticks"]:
        raise SystemExit(0)
    group_id = int(fields_after_command[2])
    group_stat = Path(f"/proc/{group_id}/stat").read_text(encoding="utf-8")
    group_command = [
        os.fsdecode(argument)
        for argument in Path(f"/proc/{group_id}/cmdline").read_bytes().split(b"\0")
        if argument
    ]
    if (
        group_id <= 0
        or int(group_stat.split(" ", 1)[0]) != group_id
        or str(node_home / "boot.sh") not in group_command
    ):
        raise SystemExit(0)
    print(f"{group_id}:{record['pid']}")
except (IndexError, OSError, TypeError, ValueError, json.JSONDecodeError):
    pass
PY
)" || group_and_pid=""
    case "$group_and_pid" in
        *:*)
            group_id="${group_and_pid%%:*}"
            pid="${group_and_pid#*:}"
            ;;
        *) return 0 ;;
    esac
    case "$group_id:$pid" in
        *[!0-9:]*|:*|*:) return 0 ;;
    esac
    kill -TERM "-$group_id" 2>/dev/null || return 0
    seconds=0
    while [ "$seconds" -lt 5 ] && kill -0 "$group_id" 2>/dev/null; do
        sleep 1
        seconds=$((seconds + 1))
    done
}

stop_verified_node
wake_unlock="$(trusted_command_if_available termux-wake-unlock)"
[ -z "$wake_unlock" ] || "$wake_unlock" || :

rm -f "$BOOT_WRAPPER"
rm -f "$NODE_HOME/monitor_node.py"
rm -f "$NODE_HOME/node_config.py"
rm -f "$NODE_HOME/node_checks.py"
rm -f "$NODE_HOME/node_state.py"
rm -f "$NODE_HOME/node_runtime.py"
rm -f "$NODE_HOME/boot.sh"

if [ "$PURGE_DATA" = true ]; then
    rm -f "$NODE_HOME/config.json"
    rm -f "$NODE_HOME/state.json"
    rm -f "$NODE_HOME/monitor.lock"
    rm -f "$NODE_HOME/.monitor.lock.guard"
    rm -f "$NODE_HOME/logs/monitor.log"
    rm -f "$NODE_HOME/logs/monitor.log.1"
    rm -f "$NODE_HOME/logs/monitor.log.2"
    rm -f "$NODE_HOME/logs/monitor.log.3"
    rm -f "$NODE_HOME/logs/monitor.log.4"
    rm -f "$NODE_HOME/logs/monitor.log.5"
    rmdir "$NODE_HOME/logs" 2>/dev/null || :
    rmdir "$NODE_HOME" 2>/dev/null || :
fi

printf '%s\n' 'hardware-monitor-node uninstalled'
