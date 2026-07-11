# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Runtime Dependencies

- **psutil** — CPU, memory, disk, network, battery metrics
- **pythonnet** (optional) — .NET interop for LibreHardwareMonitorLib.dll sensor reading; degrades gracefully if missing
- **LibreHardwareMonitorLib.dll** — .NET DLL loaded via pythonnet for hardware sensor data (CPU/GPU temp, fan, power, clocks)
- **PresentMon.exe** — Microsoft's frame capture tool, used as subprocess for FPS/1% Low measurement

No test suite exists. Verify code changes with `python -m py_compile app.py`; when runtime behavior changes, also validate on a Windows machine with `python app.py` or the built EXE.

## UI Language

The app defaults to Chinese (`ui_language: "zh"`). English is supported via `ui_language: "en"`. All UI strings are inline-translated in `_build_ui()` and `_toggle_settings()`. When adding new UI text, always provide both zh and en variants using the `tr(zh, en)` helper. For dynamic values, use string replacement after `tr()` returns.

## Build & Run

```bash
# Build EXE (PyInstaller 6.13)
pyinstaller "Hardware Monitoring.spec" --noconfirm

# Built EXE at: dist/Hardware Monitoring/Hardware Monitoring.exe

# Run directly (Python)
python app.py

# Run with admin elevation (prompts UAC if not already admin)
python app.py --force-admin

# Run built EXE
./"Hardware Monitoring.exe"
```

## Build Installer (NSIS)

```bash
# Requires NSIS installed. Run from project root.
makensis "Hardware Monitoring.nsi"
```

## Project Architecture

Single-file tkinter application (~2286 lines) that renders a hardware monitoring overlay on Windows.

### Class Overview

- **`Metrics`** (dataclass, ~line 189): All hardware metric fields (cpu_usage, gpu_temp, fps, etc.). Includes `target_process` and `source_status` for diagnostics.
- **`SensorReader`** (~line 219): Reads hardware data via LibreHardwareMonitorLib (.NET DLL via pythonnet) and psutil. Tiered fallback: LHM direct sensors → CoreTemp shared memory (ctypes) → nvidia-smi CLI → WMI ACPI thermal zone → OpenHardwareMonitor/LibreHardwareMonitor WMI. Fallback values cached for 5 seconds.
- **`FpsService`** (~line 791): Manages PresentMon process (subprocess) to read FPS/1% Low from a target game process. CSV-based stdout parsing. Calculates 1% Low from rolling deque of 600 frame-time samples (99th percentile).
- **`TrayIconService`** (~line 1085): Windows system tray icon via Win32 API (Shell_NotifyIconW). Pure ctypes, no third-party dependency. Own daemon thread for Win32 message loop.
- **`OverlayApp`** (~line 1319): Main application class. Creates the tkinter overlay window (`overrideredirect(True)`), builds the UI, manages settings, handles drag/mouse events, and runs the update loop. Entry point calls `ensure_admin()` and `SetProcessDpiAwareness(2)` before creating the root window.

### Data Flow

1. `SensorReader.read_metrics()` runs in a background daemon thread (configurable interval, default 500ms)
2. `FpsService._run_worker()` runs in its own daemon thread, parsing PresentMon CSV stdout
3. Both write to lock-protected shared state (`_latest_metrics` / `_display_text`)
4. `_update_metrics_loop()` (tkinter `after` timer, 300ms) reads latest values and updates label widgets
5. `_rebuild_ui_fast()` destroys and recreates the overlay when settings change (live preview)

### Key Design Decisions

- **Window**: `overrideredirect(True)` — no title bar. Acrylic blur via `SetWindowCompositionAttribute` (AccentState=4, AccentFlags=2). Draggable via custom mouse handlers.
- **Settings**: Inline tkinter.Toplevel with ttk.Notebook, scrollable canvas, live preview (apply changes immediately to overlay while settings open).
- **Themes**: 3 themes defined in `THEMES` dict (line 93). Theme colors: bg, panel, border, text, sub, hint, accent.
- **FPS**: PresentMon CLI subprocess for FPS/1% Low. Restarts on target process change.
- **Tray icon**: Pure Win32 API via ctypes — no pystray dependency. Right-click context menu with Show/Exit.
- **Config / logs**: Runtime config and logs live under `%LOCALAPPDATA%\Hardware Monitoring`. `load_config()` handles defaults, validation (opacity clamp, min refresh 300ms, font scale [0.9,1.4]), and migration from one legacy install-local `config.json` when present.
- **Packaging**: PyInstaller `onedir` mode. External dependencies: `tools/PresentMon/PresentMon.exe`, `_internal/libs/LibreHardwareMonitorLib.dll`.

### Metrics Display

The overlay builds rows from `METRIC_LAYOUT` (~line 126) which maps metric keys to display labels and config enable-flags. `metric_order` in config controls display order. Group headers shown when multiple metrics from same group appear consecutively.

### Settings Page Structure

`_toggle_settings()` (~line 1628) creates a modal dialog with:
- Scrollable notebook with 5 tabs: Appearance, Metrics, Window, Game/FPS, Advanced
- Each tab has row/segment/make_switch helpers for layout
- Changes apply live (via `apply_live()` → calls `_rebuild_ui_fast()` to rebuild overlay)
- Save/Cancel buttons; Cancel simply closes without extra save, but live preview already applied changes

### Common Config Keys

Boolean metric visibility keys: `show_cpu_usage`, `show_memory_usage`, `show_gpu_usage`, `show_vram_usage`, `show_cpu_temperature`, `show_gpu_temperature`, `show_cpu_fan`, `show_gpu_fan`, `show_cpu_power`, `show_gpu_power`, `show_cpu_freq`, `show_gpu_freq`, `show_vram_freq`, `show_disk_speed`, `show_network_speed`, `show_fps`, `show_fps_low_1`. `metric_order` (list) controls display sequence; `load_config()` auto-appends any missing keys.

### NSIS Installer

- 4 user-selectable components: core files, start menu shortcut, desktop shortcut, autostart
- Admin-level install to `$PROGRAMFILES`
- Uninstaller removes installed program files, shortcuts, and registry entries, but keeps `%LOCALAPPDATA%\Hardware Monitoring` user data by default
