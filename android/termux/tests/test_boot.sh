#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BOOT="$ROOT/android/termux/boot.sh"
TEMP_DIR="$(mktemp -d)"
NODE_HOME="$TEMP_DIR/node"
BIN_DIR="$TEMP_DIR/bin"
LOG="$TEMP_DIR/events.log"
PYTHON_BIN="$(command -v python)"

cleanup() {
    rm -f "$BIN_DIR/sleep" "$BIN_DIR/termux-wake-lock" "$BIN_DIR/termux-notification"
    rm -f "$NODE_HOME/node_config.py" "$NODE_HOME/monitor.py" "$NODE_HOME/config.json" "$LOG"
    rmdir "$BIN_DIR" "$NODE_HOME" "$TEMP_DIR"
}
trap cleanup EXIT

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

prepare() {
    mkdir "$NODE_HOME" "$BIN_DIR"
    : > "$LOG"
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
    for command in sleep termux-wake-lock termux-notification; do
        cat > "$BIN_DIR/$command" <<'SH'
#!/bin/sh
printf '%s %s\n' "$(basename "$0")" "${1:-}" >> "$BOOT_LOG"
SH
        chmod +x "$BIN_DIR/$command"
    done
}

run_boot() {
    PYTHONDONTWRITEBYTECODE=1 PATH="$BIN_DIR:$PATH" BOOT_LOG="$LOG" NODE_HOME="$NODE_HOME" NODE_CONFIG="$NODE_HOME/config.json" NODE_SCRIPT="$NODE_HOME/monitor.py" PYTHON_BIN="$PYTHON_BIN" MONITOR_EXIT="$1" bash "$BOOT"
}

prepare
if run_boot 7; then
    status=0
else
    status=$?
fi
[ "$status" -eq 7 ] || fail "rapid crashes must preserve the child failure status"
[ "$(grep -c '^termux-notification ' "$LOG")" -eq 1 ] || fail "rapid crashes must notify once"
[ "$(grep -c '^sleep ' "$LOG")" -eq 6 ] || fail "startup plus five backoffs required"
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
grep -Fq 'PYTHON_BIN="${PYTHON_BIN:-/data/data/com.termux/files/usr/bin/python}"' "$BOOT" || fail "Termux Python must be absolute"
