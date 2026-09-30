#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BOOT="$ROOT/android/termux/boot.sh"
TEMP_DIR="$(mktemp -d)"
NODE_HOME="$TEMP_DIR/node"
BIN_DIR="$TEMP_DIR/bin"
LOG="$TEMP_DIR/events.log"
REAL_PYTHON="$(command -v python)"
PYTHON_BIN="$BIN_DIR/python"

cleanup() {
    rm -f "$BIN_DIR/python" "$BIN_DIR/flock" "$BIN_DIR/sleep" "$BIN_DIR/termux-wake-lock" "$BIN_DIR/termux-wake-unlock" "$BIN_DIR/termux-notification"
    rm -f "$NODE_HOME/node_config.py" "$NODE_HOME/monitor.py" "$NODE_HOME/config.json" "$NODE_HOME/supervisor.lock" "$LOG"
    rmdir "$BIN_DIR" "$NODE_HOME" "$TEMP_DIR"
}
trap cleanup EXIT

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

prepare() {
    PYTHON_BIN="$BIN_DIR/python"
    mkdir "$NODE_HOME" "$BIN_DIR"
    : > "$LOG"
    cat > "$BIN_DIR/python" <<SH
#!/bin/sh
case "\${2:-}" in
    *[!0-9]*|'') exec "$REAL_PYTHON" "\$@" ;;
esac
printf '%s\n' "{\"pid\":\$2,\"started_at\":\"2026-07-31T10:00:00+00:00\",\"process_start_ticks\":1,\"script_path\":\"\$3\"}"
SH
    chmod +x "$BIN_DIR/python"
    cat > "$NODE_HOME/node_config.py" <<'PY'
class Config:
    startup_delay_seconds = 1
    check_interval_seconds = 60


def load_config(path):
    return Config()
PY
    cat > "$NODE_HOME/monitor.py" <<'PY'
import os
raise SystemExit(int(os.environ["MONITOR_EXIT"]))
PY
    : > "$NODE_HOME/config.json"
    for command in flock sleep termux-wake-lock termux-wake-unlock termux-notification; do
        cat > "$BIN_DIR/$command" <<'SH'
#!/bin/sh
printf '%s %s\n' "$(basename "$0")" "${1:-}" >> "$BOOT_LOG"
SH
        chmod +x "$BIN_DIR/$command"
    done
}

run_boot() {
    PYTHONDONTWRITEBYTECODE=1 PATH="$BIN_DIR:$PATH" BOOT_LOG="$LOG" NODE_HOME="$NODE_HOME" NODE_CONFIG="$NODE_HOME/config.json" NODE_SCRIPT="$NODE_HOME/monitor.py" PYTHON_BIN="$PYTHON_BIN" FLOCK_BIN="$BIN_DIR/flock" MONITOR_EXIT="$1" bash "$BOOT"
}

# Exercise the real run_forever -> InstanceLock classification before the shell boundary.
IO_ERROR_EXIT="$(PYTHONPATH="$ROOT" "$REAL_PYTHON" - <<'PYCODE'
import errno
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from android.termux import monitor_node
from android.termux.node_config import NodeConfig
with TemporaryDirectory() as directory:
    root = Path(directory)
    with patch.object(monitor_node, 'load_config', return_value=NodeConfig()), patch.object(monitor_node, '_node_paths', return_value=(root/'state.json', root/'monitor.log', root/'monitor.lock')), patch('android.termux.node_runtime.os.link', side_effect=OSError(errno.ENOSPC, 'injected')):
        print(monitor_node.run_forever(root/'config.json'))
PYCODE
)"
[ "$IO_ERROR_EXIT" -ne 0 ] && [ "$IO_ERROR_EXIT" -ne 3 ] || fail "real lock I/O failure must not exit successfully or as contention"
prepare
if run_boot "$IO_ERROR_EXIT"; then
    status=0
else
    status=$?
fi
[ "$status" -eq "$IO_ERROR_EXIT" ] || fail "rapid crashes must preserve the child failure status"
[ "$(grep -c '^termux-notification ' "$LOG")" -eq 1 ] || fail "rapid crashes must notify once"
[ "$(grep -c '^sleep ' "$LOG")" -eq 6 ] || fail "startup plus five backoffs required"
[ "$(grep '^sleep ' "$LOG" | cut -d' ' -f2 | tr '\n' ' ')" = "1 5 15 30 60 300 " ] || fail "bounded backoff order must be preserved"
[ "$(grep -c '^termux-wake-unlock ' "$LOG")" -eq 1 ] || fail "rapid crash exit must release the wake lock"
[ ! -e "$NODE_HOME/supervisor.lock" ] || fail "rapid crash exit must remove the supervisor record"
cleanup
trap - EXIT

TEMP_DIR="$(mktemp -d)"
NODE_HOME="$TEMP_DIR/node"
BIN_DIR="$TEMP_DIR/bin"
LOG="$TEMP_DIR/events.log"
trap cleanup EXIT
prepare
if run_boot 3; then
    status=0
else
    status=$?
fi
[ "$status" -eq 0 ] || fail "InstanceLock contention must be idempotent"
[ "$(grep -c '^termux-notification ' "$LOG")" -eq 0 ] || fail "lock contention must not notify"
[ "$(grep -c '^sleep ' "$LOG")" -eq 1 ] || fail "lock contention must not back off"
[ "$(grep -c '^termux-wake-unlock ' "$LOG")" -eq 1 ] || fail "lock contention exit must release the wake lock"
[ ! -e "$NODE_HOME/supervisor.lock" ] || fail "lock contention exit must remove the supervisor record"
grep -Fq 'PYTHON_BIN="${PYTHON_BIN:-/data/data/com.termux/files/usr/bin/python}"' "$BOOT" || fail "Termux Python must be absolute"

cleanup
trap - EXIT

TEMP_DIR="$(mktemp -d)"
NODE_HOME="$TEMP_DIR/node"
BIN_DIR="$TEMP_DIR/bin"
LOG="$TEMP_DIR/events.log"
trap cleanup EXIT
prepare
run_boot 0
[ "$(grep -c '^termux-wake-unlock ' "$LOG")" -eq 1 ] || fail "normal exit must release the wake lock"
[ ! -e "$NODE_HOME/supervisor.lock" ] || fail "normal exit must remove the supervisor record"

# A transient lock I/O error must be retried and then exit cleanly.
cleanup
trap - EXIT
TEMP_DIR="$(mktemp -d)"
NODE_HOME="$TEMP_DIR/node"
BIN_DIR="$TEMP_DIR/bin"
LOG="$TEMP_DIR/events.log"
trap cleanup EXIT
prepare
cat > "$NODE_HOME/monitor.py" <<'PYCODE'
import os
from pathlib import Path
marker = Path(os.environ["NODE_HOME"]) / "attempt"
if not marker.exists():
    marker.write_text("failed once")
    raise SystemExit(int(os.environ["MONITOR_EXIT"]))
marker.unlink()
PYCODE
run_boot "$IO_ERROR_EXIT"
[ "$(grep -c '^sleep ' "$LOG")" -eq 2 ] || fail "transient failure must retry once"
[ "$(grep -c '^termux-notification ' "$LOG")" -eq 0 ] || fail "recovered node must not notify failure"
