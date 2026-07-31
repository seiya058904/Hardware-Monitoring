#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
INSTALL="$ROOT/android/termux/install.sh"
UNINSTALL="$ROOT/android/termux/uninstall.sh"
TEMP_DIR="$(mktemp -d)"
HOME_DIR="$TEMP_DIR/home"
BIN_DIR="$TEMP_DIR/bin"
CONFIG_SOURCE="$TEMP_DIR/custom-config.json"
DIAGNOSTICS="$TEMP_DIR/diagnostics.log"
TERMUX_LOG="$TEMP_DIR/termux.log"
ERROR_LOG="$TEMP_DIR/error.log"
REAL_PYTHON="$(command -v python)"

cleanup_node() {
    rm -f "$HOME_DIR/.termux/boot/start-hardware-monitor-node"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/monitor_node.py"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/node_config.py"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/node_checks.py"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/node_state.py"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/node_runtime.py"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/boot.sh"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/config.json"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/state.json"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/monitor.lock"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/logs/monitor.log"
    rm -f "$HOME_DIR/.local/share/hardware-monitor-node/keep.txt"
    rmdir "$HOME_DIR/.local/share/hardware-monitor-node/logs" 2>/dev/null || :
    rmdir "$HOME_DIR/.local/share/hardware-monitor-node" 2>/dev/null || :
    rmdir "$HOME_DIR/.local/share" 2>/dev/null || :
    rmdir "$HOME_DIR/.local" 2>/dev/null || :
    rmdir "$HOME_DIR/.termux/boot" 2>/dev/null || :
    rmdir "$HOME_DIR/.termux" 2>/dev/null || :
    rm -f "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/monitor_node.py"
    rm -f "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/node_config.py"
    rm -f "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/node_checks.py"
    rm -f "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/node_state.py"
    rm -f "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/node_runtime.py"
    rm -f "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/boot.sh"
    rmdir "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node/logs" 2>/dev/null || :
    rmdir "$TEMP_DIR/invalid-home/.local/share/hardware-monitor-node" 2>/dev/null || :
    rmdir "$TEMP_DIR/invalid-home/.local/share" 2>/dev/null || :
    rmdir "$TEMP_DIR/invalid-home/.local" 2>/dev/null || :
    rmdir "$TEMP_DIR/invalid-home" 2>/dev/null || :
}

cleanup() {
    cleanup_node
    rm -f "$BIN_DIR/python"
    rm -f "$BIN_DIR/termux-wake-lock"
    rm -f "$BIN_DIR/termux-wake-unlock"
    rm -f "$BIN_DIR/setsid"
    rmdir "$BIN_DIR" 2>/dev/null || :
    rm -f "$CONFIG_SOURCE"
    rm -f "$DIAGNOSTICS"
    rm -f "$TERMUX_LOG"
    rm -f "$ERROR_LOG"
    rmdir "$HOME_DIR" 2>/dev/null || :
    rmdir "$TEMP_DIR" 2>/dev/null || :
}
trap cleanup EXIT

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

write_config() {
    cat > "$1" <<'JSON'
{
  "dashboard_base_url": "http://127.0.0.1:1",
  "check_interval_seconds": 60,
  "request_timeout_seconds": 1,
  "failure_threshold": 3,
  "recovery_threshold": 2,
  "reminder_interval_seconds": 3600,
  "startup_delay_seconds": 30,
  "log_max_bytes": 1048576,
  "log_backup_count": 5,
  "check_gateway": false,
  "check_internet": false,
  "internet_probe_urls": []
}
JSON
}

prepare_commands() {
    mkdir -p "$HOME_DIR" "$BIN_DIR"
    cat > "$BIN_DIR/python" <<PY
#!/usr/bin/env bash
if [ "\${1:-}" = "-" ] && [ -n "\${VERIFY_GROUP:-}" ]; then
    printf '%s:%s\n' "\$VERIFY_GROUP" "\${VERIFY_CHILD:-\$VERIFY_GROUP}"
    exit 0
fi
if [ "\${1:-}" != "-" ] && [ "\${1##*/}" = "monitor_node.py" ]; then
    printf '%s\n' "\$*" >> "\$PYTHON_DIAGNOSTICS"
    [ "\${FAIL_DIAGNOSTIC:-}" != 1 ] || exit 42
    exit 0
fi
exec "$REAL_PYTHON" "\$@"
PY
    chmod +x "$BIN_DIR/python"
    for command in termux-wake-lock termux-wake-unlock setsid; do
        cat > "$BIN_DIR/$command" <<'SH'
#!/usr/bin/env bash
if [ "$(basename "$0")" = setsid ] && [ -n "${WRAPPER_CAPTURE:-}" ]; then
    printf '%s\n' "$1" > "$WRAPPER_CAPTURE"
    env | grep -E '^(NODE_HOME|NODE_CONFIG|NODE_SCRIPT|PYTHON_BIN)=' >> "$WRAPPER_CAPTURE" || :
    exit 0
fi
printf '%s\n' "$(basename "$0")" >> "$TERMUX_LOG"
SH
        chmod +x "$BIN_DIR/$command"
    done
}

run_install() {
    HOME="$HOME_DIR" PREFIX="$TEMP_DIR" PATH="$BIN_DIR:$PATH" PYTHON_DIAGNOSTICS="$DIAGNOSTICS" TERMUX_LOG="$TERMUX_LOG" bash "$INSTALL" "$@"
}

run_uninstall() {
    HOME="$HOME_DIR" PREFIX="$TEMP_DIR" PATH="$BIN_DIR:$PATH" PYTHON_DIAGNOSTICS="$DIAGNOSTICS" TERMUX_LOG="$TERMUX_LOG" bash "$UNINSTALL" "$@"
}

prepare_commands
write_config "$CONFIG_SOURCE"
INVALID_HOME="$TEMP_DIR/invalid-home"
printf '%s\n' '{' > "$TEMP_DIR/invalid-config.json"
if HOME="$INVALID_HOME" PREFIX="$TEMP_DIR" PATH="$BIN_DIR:$PATH" PYTHON_DIAGNOSTICS="$DIAGNOSTICS" TERMUX_LOG="$TERMUX_LOG" bash "$INSTALL" --config "$TEMP_DIR/invalid-config.json" > "$ERROR_LOG" 2>&1; then
    fail "install must reject an invalid supplied config"
fi
[ ! -e "$INVALID_HOME/.local/share/hardware-monitor-node" ] || fail "invalid supplied config must fail before deployment"
rm -f "$TEMP_DIR/invalid-config.json"

run_install --config "$CONFIG_SOURCE"
NODE_HOME="$HOME_DIR/.local/share/hardware-monitor-node"
WRAPPER="$HOME_DIR/.termux/boot/start-hardware-monitor-node"
[ -f "$NODE_HOME/config.json" ] || fail "install must create the deployed configuration"
[ -x "$NODE_HOME/boot.sh" ] || fail "install must make deployed boot.sh executable"
[ -x "$WRAPPER" ] || fail "install must create an executable Boot wrapper"
[ "$(wc -l < "$DIAGNOSTICS")" -eq 1 ] || fail "install must run one foreground diagnostic"
HOME="$HOME_DIR" WRAPPER_CAPTURE="$TEMP_DIR/wrapper-capture.log" NODE_HOME="$TEMP_DIR/escaped-node" NODE_CONFIG="$TEMP_DIR/escaped-config.json" NODE_SCRIPT="$TEMP_DIR/escaped-script.py" bash "$WRAPPER"
[ "$(head -n 1 "$TEMP_DIR/wrapper-capture.log")" = "$NODE_HOME/boot.sh" ] || fail "Boot wrapper must use the fixed deployed boot path"
[ "$(wc -l < "$TEMP_DIR/wrapper-capture.log")" -eq 1 ] || fail "Boot wrapper must clear inherited node path overrides"

cp "$NODE_HOME/config.json" "$TEMP_DIR/preserved-config.json"
run_install
cmp -s "$TEMP_DIR/preserved-config.json" "$NODE_HOME/config.json" || fail "repeated install must preserve valid config"
[ "$(wc -l < "$DIAGNOSTICS")" -eq 2 ] || fail "repeated install must still run one diagnostic"

printf '%s\n' '{' > "$NODE_HOME/config.json"
run_install
cmp -s "$ROOT/android/termux/config.example.json" "$NODE_HOME/config.json" || fail "install must replace invalid config with the template"
rm -f "$NODE_HOME/config.json"
run_install
cmp -s "$ROOT/android/termux/config.example.json" "$NODE_HOME/config.json" || fail "install must create missing config from the template"

printf '%s\n' 'old monitor program' > "$NODE_HOME/monitor_node.py"
printf '%s\n' 'old boot program' > "$NODE_HOME/boot.sh"
cp "$NODE_HOME/config.json" "$TEMP_DIR/pre-diagnostic-config.json"
if FAIL_DIAGNOSTIC=1 run_install --config "$CONFIG_SOURCE" > "$ERROR_LOG" 2>&1; then
    fail "install must return the foreground diagnostic failure"
fi
grep -Fxq 'old monitor program' "$NODE_HOME/monitor_node.py" || fail "diagnostic failure must restore the previous program"
grep -Fxq 'old boot program' "$NODE_HOME/boot.sh" || fail "diagnostic failure must restore every previous program file"
cmp -s "$TEMP_DIR/pre-diagnostic-config.json" "$NODE_HOME/config.json" || fail "diagnostic failure must restore the previous config"

BAD_PREFIX="$TEMP_DIR/missing-prefix"
BAD_BIN="$BAD_PREFIX/bin"
mkdir -p "$BAD_BIN"
cp "$BIN_DIR/python" "$BAD_BIN/python"
if HOME="$HOME_DIR" PREFIX="$BAD_PREFIX" PATH="$BAD_BIN:$PATH" bash "$INSTALL" > "$ERROR_LOG" 2>&1; then
    fail "install must reject a missing trusted Termux command"
fi
grep -Fq "termux-wake-lock" "$ERROR_LOG" || fail "missing command error must name the command"
rm -f "$BAD_BIN/python"
rmdir "$BAD_BIN"
rmdir "$BAD_PREFIX"

if run_install --unknown > "$ERROR_LOG" 2>&1; then
    fail "install must refuse unknown arguments"
fi

mkdir -p "$NODE_HOME/logs"
: > "$NODE_HOME/state.json"
: > "$NODE_HOME/monitor.lock"
: > "$NODE_HOME/logs/monitor.log"
cat > "$NODE_HOME/boot.sh" <<'SH'
#!/usr/bin/env bash
trap 'exit 0' TERM
while :; do
    printf '%s\n' restart >> "$RESTART_LOG"
    sleep 0.1
done
SH
chmod +x "$NODE_HOME/boot.sh"
RESTART_LOG="$TEMP_DIR/restarts.log" bash "$NODE_HOME/boot.sh" &
SUPERVISOR_PID=$!
for attempt in 1 2 3 4 5; do
    [ -s "$TEMP_DIR/restarts.log" ] && break
    sleep 0.1
done
[ -s "$TEMP_DIR/restarts.log" ] || fail "test supervisor did not start"
kill() {
    if [ "$1" = -TERM ] && [ "$2" = "-$SUPERVISOR_PID" ]; then
        command kill -TERM "$SUPERVISOR_PID"
        return
    fi
    command kill "$@"
}
export -f kill
RESTART_LOG="$TEMP_DIR/restarts.log" VERIFY_GROUP="$SUPERVISOR_PID" run_uninstall
restart_count="$(wc -l < "$TEMP_DIR/restarts.log")"
sleep 0.3
[ "$(wc -l < "$TEMP_DIR/restarts.log")" -eq "$restart_count" ] || fail "uninstall must stop the verified supervisor group before removing files"
if kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
    kill -TERM "$SUPERVISOR_PID" 2>/dev/null || :
    fail "uninstall must terminate the verified supervisor"
fi
[ -f "$NODE_HOME/config.json" ] || fail "default uninstall must preserve config"
[ -f "$NODE_HOME/state.json" ] || fail "default uninstall must preserve state"
[ -f "$NODE_HOME/logs/monitor.log" ] || fail "default uninstall must preserve logs"
[ ! -e "$WRAPPER" ] || fail "uninstall must remove only its Boot wrapper"
[ ! -e "$NODE_HOME/monitor_node.py" ] || fail "uninstall must remove deployed program files"
grep -Fxq "termux-wake-unlock" "$TERMUX_LOG" || fail "uninstall must release the wake lock"

run_install
: > "$NODE_HOME/keep.txt"
run_uninstall --purge-data
[ ! -e "$NODE_HOME/config.json" ] || fail "purge must remove config"
[ ! -e "$NODE_HOME/state.json" ] || fail "purge must remove state"
[ ! -e "$NODE_HOME/logs/monitor.log" ] || fail "purge must remove known logs"
[ -f "$NODE_HOME/keep.txt" ] || fail "purge must not remove unknown files"

if run_uninstall --unknown > "$ERROR_LOG" 2>&1; then
    fail "uninstall must refuse unknown arguments"
fi
