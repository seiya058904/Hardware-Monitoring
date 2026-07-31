# Termux monitoring node

This is a read-only Android monitor for a Hardware Monitoring LAN dashboard. It makes outbound checks to the configured dashboard, gateway, and approved public HTTPS probes; it does not expose a phone port.

The Windows dashboard binds `0.0.0.0` and has no authentication. Keep it on a trusted private LAN only: do not create a router port-forward, public DNS/tunnel, or other Internet exposure for its port.

## Before installation

Install **Termux**, **Termux:Boot**, and **Termux:API** from one trusted source family and never mix signatures. The Termux project's [installation guide](https://github.com/termux/termux-app#installation) explains the same-signing-key requirement; its [Boot](https://github.com/termux/termux-boot) and [API](https://github.com/termux/termux-api) repositories identify the matching add-ons. A simple consistent choice is the three F-Droid package pages: [Termux](https://f-droid.org/packages/com.termux/), [Termux:Boot](https://f-droid.org/packages/com.termux.boot/), and [Termux:API](https://f-droid.org/packages/com.termux.api/). Confirm the page package IDs before downloading.

If APK files are supplied outside that path, use a computer with Android SDK Build Tools to inspect all three before installing and confirm that the signer certificate SHA-256 is identical for every file:

```sh
apksigner verify --print-certs Termux.apk
apksigner verify --print-certs Termux-Boot.apk
apksigner verify --print-certs Termux-API.apk
```

The following commands can be automated from a trusted computer after the APK files have been obtained. They do not approve Android prompts:

```sh
adb install -r Termux.apk
adb install -r Termux-Boot.apk
adb install -r Termux-API.apk
```

The following confirmations must be performed by the person holding the phone:

1. Accept the Android USB-debugging/RSA prompt before any `adb` command can run.
2. Open Termux once, then grant Termux:API notification permission when Android asks (or enable it in Android Settings). Notifications are best-effort; monitoring continues if they fail.
3. In Android battery settings, set Termux, Termux:Boot, and Termux:API to unrestricted / not optimized.
4. On Vivo/Funtouch OS, enable the equivalent **self-start/autostart** and **background activity** permissions for all three apps. Names and availability vary by Android and Vivo version.

Those vendor settings, reboot persistence, wake locks, notification delivery, and the `setsid` process group have not been verified on a physical device yet.

## Install and configure

Open Termux and install the packages the scripts require:

```sh
pkg update
pkg install python util-linux termux-api nano
```

From this repository's `android/termux` directory, make a private configuration outside the repository and edit only its dashboard address first:

```sh
mkdir -p "$HOME/.config/hardware-monitor-node"
cp config.example.json "$HOME/.config/hardware-monitor-node/config.json"
chmod 600 "$HOME/.config/hardware-monitor-node/config.json"
nano "$HOME/.config/hardware-monitor-node/config.json"
./install.sh --config "$HOME/.config/hardware-monitor-node/config.json"
```

Set `dashboard_base_url` to the Windows dashboard's LAN address, for example `http://192.168.2.249:8765`; use no credentials, query, or fragment. The address must serve both `/healthz` and `/api/metrics`. Keep every other required key from `config.example.json`: the configuration validator rejects missing or unknown keys. The installer copies it to `$HOME/.local/share/hardware-monitor-node/config.json` with owner-only permissions, runs one diagnostic round, then creates the Termux:Boot wrapper.

To change the dashboard address later, edit the deployed private file and run the same foreground diagnostic:

```sh
nano "$HOME/.local/share/hardware-monitor-node/config.json"
python "$HOME/.local/share/hardware-monitor-node/monitor_node.py" --once --config "$HOME/.local/share/hardware-monitor-node/config.json"
```

Do not use `install.sh` without `--config` after manually changing the deployed file unless it remains valid: a valid existing configuration is retained, while an absent or invalid one is replaced from `config.example.json`.

## Inspect status and logs

Run a foreground diagnostic at any time:

```sh
python "$HOME/.local/share/hardware-monitor-node/monitor_node.py" --once --config "$HOME/.local/share/hardware-monitor-node/config.json"
```

Inspect the local state and rotating logs:

```sh
cat "$HOME/.local/share/hardware-monitor-node/state.json"
tail -n 100 "$HOME/.local/share/hardware-monitor-node/logs/monitor.log"
ls -l "$HOME/.local/share/hardware-monitor-node/logs/"
```

After reboot, Termux:Boot starts `$HOME/.termux/boot/start-hardware-monitor-node`; the supervisor obtains a wake lock and restarts rapid failures with 5, 15, 30, 60, and 300 second backoff. It posts a best-effort local notification after five rapid crashes.

## Safe uninstall

From the repository's `android/termux` directory, remove the installed program and its Boot wrapper while preserving configuration, state, and logs:

```sh
./uninstall.sh
```

Only after saving anything needed, permanently remove the known configuration, state, and log files too:

```sh
./uninstall.sh --purge-data
```

Uninstall attempts to stop only the verified monitor process group and releases its wake lock. It does not remove unrelated files in the node directory. Remove the Android apps manually only after the script has completed.

## Boundaries

The node has no incoming phone port, remote-control endpoint, file access endpoint, or log-upload feature. It cannot repair the Windows dashboard, bypass Android permissions, guarantee Vivo background execution, or make a device stay online. Device-specific behavior needs an authorized on-device check.
