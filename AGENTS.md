# Repository Guidelines

## Project Overview

`Hardware Monitoring` is a Windows-only hardware overlay written in Python with `tkinter`. The main entry point is `D:\xia zai\AI project\5.11\Hardware Monitoring\app.py`, which loads hardware metrics, FPS data, the tray icon, and the settings window in one process.

The project is packaged with PyInstaller using `D:\xia zai\AI project\5.11\Hardware Monitoring\Hardware Monitoring.spec` and an NSIS installer in `D:\xia zai\AI project\5.11\Hardware Monitoring\Hardware Monitoring.nsi`. Runtime data is stored under `%LOCALAPPDATA%\Hardware Monitoring`; the repo root also contains pinned binaries and release artifacts used for packaging.

## Project Structure & Module Organization

- `D:\xia zai\AI project\5.11\Hardware Monitoring\app.py`: single-file application with metrics collection, FPS capture, tray icon, settings UI, and config loading.
- `D:\xia zai\AI project\5.11\Hardware Monitoring\assets`: bundled app icon and UI assets.
- `D:\xia zai\AI project\5.11\Hardware Monitoring\tools\PresentMon`: bundled PresentMon executable used for FPS data.
- `D:\xia zai\AI project\5.11\Hardware Monitoring\_internal\libs`: pinned `LibreHardwareMonitorLib.dll` used when `pythonnet` is available.
- `D:\xia zai\AI project\5.11\Hardware Monitoring\scripts`: helper scripts, including dependency download/verification.
- `D:\xia zai\AI project\5.11\Hardware Monitoring\third_party`: third-party license files for the installer.
- `D:\xia zai\AI project\5.11\Hardware Monitoring\docs`: planning notes and superpowers plans only; do not treat it as product docs.

Generated folders such as `build/`, `dist/`, `__pycache__/`, the built EXE, installer EXEs, and local logs are build outputs, not source.

## Architecture Notes

`app.py` is intentionally monolithic. Key responsibilities are split by class: `SensorReader` gathers hardware data, `FpsService` manages PresentMon, `TrayIconService` owns the Windows tray icon, and `OverlayApp` builds the UI and main loop.

Data flows from background worker threads into locked shared state, then the Tkinter timer refreshes visible labels. Config loading normalizes values and keeps the UI language, theme, and metric order consistent. Packaging depends on the exact bundled `tools` and `_internal/libs` inputs remaining in place.

## Build, Test & Development Commands

```bash
python app.py
python app.py --force-admin
python -m py_compile app.py
pyinstaller "Hardware Monitoring.spec" --noconfirm
makensis "Hardware Monitoring.nsi"
powershell -ExecutionPolicy Bypass -File scripts\fetch-dependencies.ps1
```

- `python -m py_compile app.py` is the minimum static check.
- `python app.py` or the built EXE is the runtime check when behavior changes.
- `pyinstaller` builds the onedir distribution into `dist/Hardware Monitoring/`.
- `makensis` builds the installer.
- `scripts/fetch-dependencies.ps1` downloads and verifies pinned binary dependencies.

Do not run deploy, publish, release, commit, push, or database-changing commands unless the user explicitly authorizes them.

## Coding Style & Naming Conventions

Follow the existing file’s style: Python 3, 4-space indentation, standard library first, and explicit `tr(zh, en)` pairs for UI text. Keep changes small and local. Preserve existing config keys, metric names, and Windows-specific behavior unless a change is requested.

## Testing & Verification

There is no dedicated automated test suite. Use `python -m py_compile app.py` for syntax verification, then inspect the changed files and any generated diff noise with `git status --short`, `git diff --stat`, and `git diff --check`.

If UI, tray, FPS, packaging, or runtime paths change, validate the behavior on Windows with `python app.py` or the packaged EXE. Browser-based visual inspection is not part of the default workflow here.

## Commit & Pull Request Guidelines

Recent commits are short, imperative, and scoped, for example `Add repo agent guidance`, `Fix runtime loading`, and `Harden first release packaging`. Keep future commits single-purpose and describe the actual behavior change. If a UI change needs review, include the validation result and any manual checks the user should perform.

## Security & Configuration

- Never commit `.env`, local config files, tokens, passwords, private keys, database strings, or other secrets.
- Do not expose sensitive values in docs, replies, commit messages, or sample commands.
- Do not check in local caches, logs, build output, or temporary files.
- Treat auth, permissions, signing, billing, production config, and data-integrity changes as high risk and get explicit authorization first.

## Agent-Specific Instructions

- Read the relevant files before editing and state a brief plan.
- Prefer the smallest reviewable diff that fixes the real cause.
- Do not change unrelated code, formatting, or behavior.
- Do not overwrite user edits or assume stale line numbers are still valid.
- Do not install dependencies, auto-fix, format the whole repo, commit, push, deploy, or publish without explicit permission.
- If a check was not run, say so plainly.

## Pre-Commit Checklist

- `git status --short`
- `git diff --stat`
- `git diff -- AGENTS.md`
- Only the intended files changed
- No secrets or local runtime files
- Required checks run, or their absence stated clearly
- Commit or push only after explicit authorization
