# CLAUDE.md

This file provides Claude-specific working notes. The canonical repository rules,
architecture overview, build/test commands, and packaging boundaries live in
`AGENTS.md` — read that file first and do not duplicate it here.

## Quick Facts

- Single Windows tkinter app; entry point `app.py`. Runtime modules: `sensor_runtime.py`
  (thread-owned sampler), `fps_stream.py` / `fps_sessions.py` (PresentMon capture and ETW
  session ownership), `dashboard_server.py` (read-only LAN HTTP server).
- A full `unittest` suite exists under `tests/` (including Windows GUI tests).
  Run: `python -m unittest discover -s tests -v`.
- Runtime config and logs live in `%LOCALAPPDATA%\Hardware Monitoring` (`runtime_data_dir()`),
  NOT next to the EXE. `config.json` is written atomically; broken configs are backed up as
  `config.invalid-<hash>.json`.
- UI strings are inline bilingual via the `tr(zh, en)` helper; default language is Chinese.
- Themes are defined in `THEMES` (5 themes with semantic tokens: bg/surface/border/text/
  accent/status_* …). The settings dialog follows the current theme.
- Settings use an explicit transaction model: appearance and metric toggles preview in
  memory only; nothing touches `config.json` until 保存/Save. Cancel (and closing the
  dialog) restores the original config. FPS/LAN/autostart/log level apply only on Save.
- `window_opacity` is clamped to [0.35, 1.0] so the overlay can never be configured fully
  invisible. Overlay position persists as `window_x`/`window_y` and is clamped back into
  the visible monitor area at startup.
- The LAN dashboard page is a single self-contained HTML string (`LanDashboardService._PAGE`):
  vanilla JS only, no external resources, bilingual with theme toggle, strict
  `sample_state`/`sample_generation` freshness handling. Endpoints stay read-only.
- Packaging: PyInstaller `Hardware Monitoring.spec` (hash-checks pinned PresentMon and
  LibreHardwareMonitorLib inputs) and NSIS `Hardware Monitoring.nsi`. CI (`.github/workflows/ci.yml`)
  runs py_compile + unittest on a Windows runner; it does not build releases.
