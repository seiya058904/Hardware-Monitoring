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

copy_atomic() {
    source_path="$1"
    destination_path="$2"
    mode="$3"
    temporary_path="$(mktemp "$NODE_HOME/.hardware-monitor-node.XXXXXX")"
    if ! cp "$source_path" "$temporary_path"; then
        rm -f "$temporary_path"
        return 1
    fi
    chmod "$mode" "$temporary_path"
    if ! mv -f "$temporary_path" "$destination_path"; then
        rm -f "$temporary_path"
        return 1
    fi
}

BACKUP_DIR=""

backup_programs() {
    BACKUP_DIR="$(mktemp -d "$NODE_HOME/.hardware-monitor-node-backup.XXXXXX")"
    for filename in monitor_node.py node_config.py node_checks.py node_state.py node_runtime.py boot.sh; do
        if [ -f "$NODE_HOME/$filename" ]; then
            cp -p "$NODE_HOME/$filename" "$BACKUP_DIR/$filename"
            : > "$BACKUP_DIR/$filename.present"
        fi
    done
    if [ -f "$NODE_CONFIG" ]; then
        cp -p "$NODE_CONFIG" "$BACKUP_DIR/config.json"
        : > "$BACKUP_DIR/config.json.present"
    fi
}

remove_backup() {
    [ -n "$BACKUP_DIR" ] || return 0
    rm -f "$BACKUP_DIR/monitor_node.py"
    rm -f "$BACKUP_DIR/node_config.py"
    rm -f "$BACKUP_DIR/node_checks.py"
    rm -f "$BACKUP_DIR/node_state.py"
    rm -f "$BACKUP_DIR/node_runtime.py"
    rm -f "$BACKUP_DIR/boot.sh"
    rm -f "$BACKUP_DIR/config.json"
    rm -f "$BACKUP_DIR/monitor_node.py.present"
    rm -f "$BACKUP_DIR/node_config.py.present"
    rm -f "$BACKUP_DIR/node_checks.py.present"
    rm -f "$BACKUP_DIR/node_state.py.present"
    rm -f "$BACKUP_DIR/node_runtime.py.present"
    rm -f "$BACKUP_DIR/boot.sh.present"
    rm -f "$BACKUP_DIR/config.json.present"
    rmdir "$BACKUP_DIR" 2>/dev/null || :
    BACKUP_DIR=""
}

restore_programs() {
    for filename in monitor_node.py node_config.py node_checks.py node_state.py node_runtime.py boot.sh; do
        if [ -f "$BACKUP_DIR/$filename.present" ]; then
            mv -f "$BACKUP_DIR/$filename" "$NODE_HOME/$filename"
        else
            rm -f "$NODE_HOME/$filename"
        fi
    done
}

restore_config() {
    if [ -f "$BACKUP_DIR/config.json.present" ]; then
        mv -f "$BACKUP_DIR/config.json" "$NODE_CONFIG"
    else
        rm -f "$NODE_CONFIG"
    fi
}

write_wrapper() {
    temporary_path="$(mktemp "$BOOT_DIR/.start-hardware-monitor-node.XXXXXX")"
    {
        printf '%s\n' '#!/data/data/com.termux/files/usr/bin/sh'
        printf 'PREFIX=%s\n' "$PREFIX"
        printf '%s\n' 'unset NODE_HOME NODE_CONFIG NODE_SCRIPT PYTHON_BIN FLOCK_BIN'
        printf '%s\n' 'exec "$PREFIX/bin/setsid" "$HOME/.local/share/hardware-monitor-node/boot.sh"'
    } > "$temporary_path"
    chmod 700 "$temporary_path"
    if ! mv -f "$temporary_path" "$BOOT_WRAPPER"; then
        rm -f "$temporary_path"
        exit 1
    fi
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

backup_programs
if ! {
    for filename in monitor_node.py node_config.py node_checks.py node_state.py node_runtime.py; do
        copy_atomic "$SCRIPT_DIR/$filename" "$NODE_HOME/$filename" 600
    done
    copy_atomic "$SCRIPT_DIR/boot.sh" "$NODE_HOME/boot.sh" 700
}; then
    restore_programs
    remove_backup
    exit 1
fi

if [ -n "$CONFIG_SOURCE" ]; then
    if ! copy_atomic "$CONFIG_SOURCE" "$NODE_CONFIG" 600; then
        restore_programs
        remove_backup
        exit 1
    fi
elif [ ! -f "$NODE_CONFIG" ] || ! validate_config "$NODE_CONFIG" "$NODE_HOME" >/dev/null 2>&1; then
    if ! copy_atomic "$SCRIPT_DIR/config.example.json" "$NODE_CONFIG" 600; then
        restore_programs
        remove_backup
        exit 1
    fi
fi

if ! validate_config "$NODE_CONFIG" "$NODE_HOME"; then
    restore_programs
    remove_backup
    printf 'configuration error\n' >&2
    exit 2
fi
chmod 600 "$NODE_CONFIG"
if PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" "$NODE_HOME/monitor_node.py" --once --config "$NODE_CONFIG"; then
    remove_backup
else
    diagnostic_status=$?
    restore_programs
    restore_config
    remove_backup
    exit "$diagnostic_status"
fi
write_wrapper
printf '%s\n' 'hardware-monitor-node installed'
