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

prepare
if run_boot 7; then
    status=0
else
    status=$?
fi
[ "$status" -eq 7 ] || fail "rapid crashes must preserve the child failure status"
[ "$(grep -c '^termux-notification ' "$LOG")" -eq 1 ] || fail "rapid crashes must notify once"
[ "$(grep -c '^sleep ' "$LOG")" -eq 6 ] || fail "startup plus five backoffs required"
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
