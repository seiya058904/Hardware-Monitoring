# Repository Guidelines

## Product and paths

Hardware Monitoring is a Windows `tkinter` overlay. `app.py` is the application entry in this Git root, covering metrics, PresentMon FPS capture, tray, settings and opt-in LAN dashboard. User configuration/logs live in `%LOCALAPPDATA%\Hardware Monitoring`; installer version/checksum live in `Hardware Monitoring.nsi` and `README.md`.

- `sensor_runtime.py`, `fps_stream.py`, `fps_sessions.py`, `dashboard_server.py`: sampling, FPS streaming/session ownership and bounded LAN serving.
- `tests/`: Windows/core regressions, including installation transactions.
- `android/termux/`: optional outbound-only node; follow its README. It is not required for the Windows overlay.
- `Hardware Monitoring.spec`, `Hardware Monitoring.nsi`, `scripts/install-transaction.ps1`: PyInstaller, NSIS and manifest-based installation.
- `assets/app.ico`, `third_party/licenses/`, `THIRD_PARTY_NOTICES.md`, `用户须知.txt`: formal package resources.

## Run, package and validate

Run from the Git root with versions in `requirements-runtime.txt` / `requirements-build.txt`; do not upgrade dependencies incidentally.

```powershell
python app.py
python -m py_compile app.py sensor_runtime.py fps_stream.py fps_sessions.py dashboard_server.py
python -m unittest discover -s tests -v
pyinstaller "Hardware Monitoring.spec" --noconfirm
makensis "Hardware Monitoring.nsi"
```

Packaging needs PyInstaller and NSIS; NSIS consumes `dist\Hardware Monitoring`. `--force-admin` is optional. Desktop, tray or packaging changes also require real Windows startup/exit verification of the affected source or EXE.

`.github/workflows/ci.yml` runs syntax/core tests on Windows with Python 3.12. Its Ubuntu job runs `python -m unittest discover -s android/termux/tests -v` and `bash android/termux/tests/test_boot.sh`. Use compatible Linux/Bash for these contracts; they do not establish Android-device acceptance. CI does not build installers, publish Releases or deploy Pages.

## Build inputs and cleanup

`tools/PresentMon/PresentMon.exe` and `_internal/libs/LibreHardwareMonitorLib.dll` are pinned inputs checked by SHA-256 in the spec. **The ignored `_internal/libs` DLL is a canonical build input; preserve it during cache cleanup.** `scripts/fetch-dependencies.ps1` downloads/verifies those binaries when acquisition is authorized.

`build/`, `dist/` and `__pycache__/` are generated. Ignored installers/root EXE still require version, uniqueness and historical-value checks before deletion. Local historical installers are retained in ignored `archive/installers/` as documented in README; they are not build inputs and may be absent in a fresh clone. Preserve personal config, local notes and uncertain files; do not commit secrets, logs or generated output.

## Invariants

- Preserve config keys, metric names, defaults and Windows behavior. Settings save/cancel stays transactional; uninstall retains the user's runtime directory.
- Workers publish synchronized state; only Tkinter's thread updates widgets. Do not release native sensors from another thread while sampling is blocked.
- LAN is default-off and read-only with bounded connections/shutdown. Do not introduce remote control, public exposure or automatic firewall changes.
- PresentMon ownership is scoped to this application's sessions. Upgrade/uninstall manages manifest-listed files, never unrelated processes or user data.
- Termux stays outbound-only; `config.example.json` and tracked files must contain no secrets.
- Use four-space Python, standard-library-first imports and `tr(zh, en)` for visible desktop text.

## Changes and commits

Read affected code/callers, preserve existing work and avoid unrelated refactors. Changes to pinned binaries, checksums or installer behavior need packaging review and verification. Run proportionate checks; inspect `git diff --check`, staged diff and status. Keep commits single-purpose. External side effects and destructive cleanup require user authorization; hygiene work must preserve Git history and formal tags/Releases.
