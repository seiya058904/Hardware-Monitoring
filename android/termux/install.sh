#!/data/data/com.termux/files/usr/bin/sh
set -eu
umask 077

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
NODE_HOME="$HOME/.local/share/hardware-monitor-node"
NODE_CONFIG="$NODE_HOME/config.json"
BOOT_DIR="$HOME/.termux/boot"
BOOT_WRAPPER="$BOOT_DIR/start-hardware-monitor-node"
SCRIPT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"
CONFIG_SOURCE=""

usage() {
    printf '%s\n' 'usage: install.sh [--config PATH]' >&2
    exit 2
}

trusted_command() {
    command_path="$(command -v "$1" 2>/dev/null || :)"
    case "$command_path" in
        "$PREFIX"/bin/*) printf '%s\n' "$command_path" ;;
        *)
            printf 'required trusted Termux command is unavailable: %s\n' "$1" >&2
            exit 127
            ;;
    esac
}

# Only these paths belong to this installation transaction.
MANAGED_FILES="monitor_node.py node_config.py node_checks.py node_state.py node_runtime.py boot.sh config.json start-hardware-monitor-node"
BACKUP_DIR=""
managed_path() {
    case "$1" in
        start-hardware-monitor-node) printf '%s\n' "$BOOT_WRAPPER" ;;
        monitor_node.py|node_config.py|node_checks.py|node_state.py|node_runtime.py|boot.sh|config.json) printf '%s\n' "$NODE_HOME/$1" ;;
        *) return 1 ;;
    esac
}
backup_programs() {
    BACKUP_DIR="$(mktemp -d "$NODE_HOME/.hardware-monitor-node-backup.XXXXXX")" || return 1
    for filename in $MANAGED_FILES; do
        target="$(managed_path "$filename")" || return 1
        if [ -e "$target" ]; then
            [ -f "$target" ] && [ ! -L "$target" ] || return 1
            cp -p "$target" "$BACKUP_DIR/$filename" || return 1
            : > "$BACKUP_DIR/$filename.present" || return 1
        fi
    done
}
remove_backup() {
    [ -n "$BACKUP_DIR" ] || return 0
    for filename in $MANAGED_FILES; do
        rm -f "$BACKUP_DIR/$filename" "$BACKUP_DIR/$filename.present" "$BACKUP_DIR/$filename.expected" "$BACKUP_DIR/$filename.changed" || return 1
    done
    rmdir "$BACKUP_DIR" || return 1
    BACKUP_DIR=""
}
copy_atomic() {
    source_path="$1"
    destination_path="$2"
    mode="$3"
    filename="${destination_path##*/}"
    [ "$(managed_path "$filename")" = "$destination_path" ] || return 1
    temporary_path="$(mktemp "${destination_path%/*}/.hardware-monitor-node.XXXXXX")" || return 1
    if ! cp "$source_path" "$temporary_path" || ! chmod "$mode" "$temporary_path" || ! cp -p "$temporary_path" "$BACKUP_DIR/$filename.expected"; then
        rm -f "$temporary_path"
        return 1
    fi
    # Record intent before publication; rollback also recognizes an untouched original.
    : > "$BACKUP_DIR/$filename.changed" || return 1
    if ! mv -f "$temporary_path" "$destination_path"; then
        rm -f "$temporary_path"
        return 1
    fi
}
restore_programs() {
    rollback_failed=0
    for filename in $MANAGED_FILES; do
        [ -f "$BACKUP_DIR/$filename.changed" ] || continue
        target="$(managed_path "$filename")" || return 1
        if [ -f "$BACKUP_DIR/$filename.present" ] && cmp -s "$target" "$BACKUP_DIR/$filename"; then
            continue
        fi
        if [ ! -e "$target" ] && [ ! -f "$BACKUP_DIR/$filename.present" ]; then
            continue
        fi
        if [ -L "$target" ] || ! cmp -s "$target" "$BACKUP_DIR/$filename.expected"; then
            printf 'rollback conflict: %s; backup retained: %s\n' "$target" "$BACKUP_DIR" >&2
            rollback_failed=1
            continue
        fi
        if [ -f "$BACKUP_DIR/$filename.present" ]; then
            mv -f "$BACKUP_DIR/$filename" "$target" || rollback_failed=1
        else
            rm -f "$target" || rollback_failed=1
        fi
    done
    [ "$rollback_failed" -eq 0 ]
}
transaction_failed() {
    status="$1"
    if restore_programs; then
        remove_backup || printf 'backup cleanup incomplete: %s\n' "$BACKUP_DIR" >&2
    else
        printf 'rollback incomplete; backup retained: %s\n' "$BACKUP_DIR" >&2
    fi
    exit "$status"
}
write_wrapper() {
    wrapper_source="$(mktemp "$BOOT_DIR/.start-hardware-monitor-node.XXXXXX")" || return 1
    if ! {
        printf '%s\n' '#!/data/data/com.termux/files/usr/bin/sh' &&
        printf 'PREFIX=%s\n' "$PREFIX" &&
        printf '%s\n' 'unset NODE_HOME NODE_CONFIG NODE_SCRIPT PYTHON_BIN FLOCK_BIN' &&
        printf '%s\n' 'exec "$PREFIX/bin/setsid" "$HOME/.local/share/hardware-monitor-node/boot.sh"'
    } > "$wrapper_source"; then
        rm -f "$wrapper_source"
        return 1
    fi
    wrapper_status=0
    copy_atomic "$wrapper_source" "$BOOT_WRAPPER" 700 || wrapper_status=$?
    rm -f "$wrapper_source"
    return "$wrapper_status"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --config)
            [ "$#" -eq 2 ] || usage
            CONFIG_SOURCE="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done

PYTHON_BIN="$(trusted_command python)"
trusted_command termux-wake-lock >/dev/null
trusted_command termux-wake-unlock >/dev/null
trusted_command setsid >/dev/null
trusted_command flock >/dev/null

for filename in monitor_node.py node_config.py node_checks.py node_state.py node_runtime.py boot.sh config.example.json; do
    [ -f "$SCRIPT_DIR/$filename" ] || {
        printf 'required local file is unavailable: %s\n' "$filename" >&2
        exit 1
    }
done

validate_config() {
    "$PYTHON_BIN" - "$1" "$2" <<'PY'
import sys
from pathlib import Path

node_home = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(node_home))
from node_config import load_config

load_config(Path(sys.argv[1]))
PY
}

if [ -n "$CONFIG_SOURCE" ]; then
    [ -f "$CONFIG_SOURCE" ] || {
        printf 'configuration file is unavailable\n' >&2
        exit 2
    }
    validate_config "$CONFIG_SOURCE" "$SCRIPT_DIR" || {
        printf 'configuration error\n' >&2
        exit 2
    }
fi

mkdir -p "$NODE_HOME" "$NODE_HOME/logs" "$BOOT_DIR"
chmod 700 "$NODE_HOME" "$NODE_HOME/logs" "$BOOT_DIR"

if ! backup_programs; then
    printf 'backup failed; no program changes made: %s\n' "$BACKUP_DIR" >&2
    exit 1
fi
for filename in monitor_node.py node_config.py node_checks.py node_state.py node_runtime.py; do
    copy_atomic "$SCRIPT_DIR/$filename" "$NODE_HOME/$filename" 600 || transaction_failed 1
done
copy_atomic "$SCRIPT_DIR/boot.sh" "$NODE_HOME/boot.sh" 700 || transaction_failed 1

if [ -n "$CONFIG_SOURCE" ]; then
    copy_atomic "$CONFIG_SOURCE" "$NODE_CONFIG" 600 || transaction_failed 1
elif [ ! -f "$NODE_CONFIG" ] || ! validate_config "$NODE_CONFIG" "$NODE_HOME" >/dev/null 2>&1; then
    copy_atomic "$SCRIPT_DIR/config.example.json" "$NODE_CONFIG" 600 || transaction_failed 1
fi
validate_config "$NODE_CONFIG" "$NODE_HOME" || transaction_failed 2
if PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" "$NODE_HOME/monitor_node.py" --once --config "$NODE_CONFIG"; then
    :
else
    transaction_failed "$?"
fi
write_wrapper || transaction_failed 1
remove_backup || exit 1
printf '%s\n' 'hardware-monitor-node installed'
