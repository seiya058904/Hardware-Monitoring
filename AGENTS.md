# Repository Guidelines

## Project Overview

`Hardware Monitoring` is a Windows desktop hardware overlay written in Python with `tkinter`. `app.py` is the single application entry point: it collects metrics, manages PresentMon FPS capture, the tray icon, settings UI, and the opt-in LAN dashboard. Runtime configuration and logs live in `%LOCALAPPDATA%\Hardware Monitoring`.

The project packages with PyInstaller (`Hardware Monitoring.spec`) and NSIS (`Hardware Monitoring.nsi`). `android/termux/` is an optional, outbound-only Android Termux monitoring node; it is not needed for normal Windows overlay use.

## Structure and Architecture

- `app.py`: `SensorReader`, `FpsService`, `TrayIconService`, `LanDashboardService`, and `OverlayApp`. Background workers write locked shared state; Tkinter's timer renders it.
- `tests/`: standard-library `unittest` coverage for sensor-value filtering, PresentMon restart ownership, and the read-only LAN dashboard.
- `android/termux/`: node scripts, JSON example configuration, Bash integration tests, and its operational README.
- `tools/PresentMon/PresentMon.exe` and `_internal/libs/LibreHardwareMonitorLib.dll`: pinned package inputs. Keep their paths and hashes compatible with the spec file.
- `assets/`, `third_party/licenses/`, and `THIRD_PARTY_NOTICES.md`: bundled application and license materials.
- `scripts/fetch-dependencies.ps1`: downloads and verifies the pinned binary dependencies.

Generated `build/`, `dist/`, `_internal/`, `__pycache__/`, installers, logs, and local configuration are not source. Do not hand-edit generated package output.

## Development, Build, and Tests

Run commands from the repository root:

```powershell
python app.py
python app.py --force-admin
python -m py_compile app.py
python -m unittest discover -s tests -v
pyinstaller "Hardware Monitoring.spec" --noconfirm
makensis "Hardware Monitoring.nsi"
powershell -ExecutionPolicy Bypass -File scripts\fetch-dependencies.ps1
```

- Use `python -m py_compile app.py` as the minimum syntax check after Python changes.
- Run the relevant `unittest` suite for FPS, sensor, or LAN-dashboard behavior. UI, tray, packaging, or Windows-path changes also need a manual Windows run of `python app.py` or the packaged EXE.
- Termux scripts are Bash-based; run their matching files under `android/termux/tests/` only in a compatible Bash/Termux environment.
- There is no repository CI configuration. Do not infer deployment or release automation.

## Coding and Data Rules

- Follow the existing Python style: four-space indentation, standard library first, small local changes, and `tr(zh, en)` for new visible UI text.
- Preserve config keys, metric names, defaults, and the Windows behavior unless the requested change explicitly alters them. Keep `lan_dashboard_enabled` default-off; its HTTP endpoints are read-only and must not become remote control or public exposure.
- Keep worker-owned state synchronized; do not update Tkinter widgets from a background thread.
- Preserve the Termux node's private configuration and outbound-only boundary. Never add credentials to `config.example.json` or repository files.

## Packaging and Security

- Do not change pinned binaries, their checksums, the PyInstaller spec, or NSIS installer behavior without a packaging-specific review and verification.
- Never commit credentials, private keys, keystores, local config, logs, build outputs, or temporary files. Treat network exposure, permissions, signing, release publication, and destructive cleanup as high-risk actions requiring explicit authorization.
- The uninstaller intentionally preserves `%LOCALAPPDATA%\Hardware Monitoring`; do not change user-data retention without explicit approval.

## Commits, PRs, and Agent Boundaries

- Recent history uses short imperative, single-purpose commit subjects. Keep commits scoped and describe the behavior changed.
- Before editing, read the affected code and trace its callers. Do not refactor unrelated code or overwrite existing user changes.
- Before committing, run only the relevant checks, inspect `git diff --check`, `git diff --stat`, and `git status --short`, and verify that staging contains only intended files.
- Do not install or update dependencies, commit, push, deploy, publish, merge, rebase, alter production settings, or perform bulk deletion unless the user explicitly authorizes that action.
