# Android Termux Monitoring Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Each task requires implementation review and specification review before proceeding. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, self-recovering Termux monitoring node that checks the Windows LAN dashboard, the current gateway, and public internet connectivity, with local Android fault and recovery notifications.

**Architecture:** A small set of focused Python standard-library modules performs configuration, probes, state transitions, persistence, locking, logging, and notifications. A POSIX shell supervisor integrates with Termux:Boot, wake lock, crash backoff, installation, and reversible removal. The Windows application remains unchanged.

**Tech Stack:** Python 3 standard library, POSIX shell, Termux, Termux:Boot, Termux:API, Android ADB for deployment and test orchestration.

## Global Constraints

- First version is read-only: no phone listener, SSH, remote command execution, or control of the PC/router.
- Do not upload logs or use tokens, cloud databases, telemetry, or third-party notification services.
- Do not access contacts, SMS, photos, location, microphone, or camera.
- Runtime Python code uses only the Python standard library.
- Defaults are 60-second checks, 5-second request timeout, failure threshold 3, recovery threshold 2, reminder interval 3600 seconds, and 30-second boot delay.
- Logs default to 1 MiB with 5 backups; configuration and state remain in Termux private storage.
- Installation and uninstallation must not recursively delete user files; do not use `rm -rf`, wildcards for deletion, or `eval` for configuration.
- The node must work without continuous USB or ADB connectivity. Android authorization, install, notification, battery, and Vivo background-permission dialogs cannot be bypassed.
- Multi-hour, screen-off, deep-sleep, USB-disconnect, and reboot behavior are observation items, not instant test claims.
- No Windows application changes, router changes, firewall changes, APK downloads, deployment, PR creation, or release publishing are authorized until their respective future tasks explicitly permit them.

## Locked File Structure

```text
android/termux/
├── monitor_node.py
├── node_config.py
├── node_checks.py
├── node_state.py
├── node_runtime.py
├── config.example.json
├── boot.sh
├── install.sh
├── uninstall.sh
├── README.md
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_checks.py
    ├── test_state.py
    ├── test_runtime.py
    ├── test_monitor_node.py
    └── fixtures/
```

`monitor_node.py` is only CLI/scheduling composition. `node_config.py` owns immutable validated configuration. `node_checks.py` owns stateless network probes. `node_state.py` owns target transitions and notification-event generation. `node_runtime.py` owns files, lock, logging, and Termux notification adaptation. Shell scripts own lifecycle only and never duplicate Python probe/state rules.

## Locked Interfaces

All later tasks use these names and types.

```python
@dataclass(frozen=True)
class NodeConfig:
    dashboard_base_url: str
    check_interval_seconds: int
    request_timeout_seconds: int
    failure_threshold: int
    recovery_threshold: int
    reminder_interval_seconds: int
    startup_delay_seconds: int
    log_max_bytes: int
    log_backup_count: int
    check_gateway: bool
    check_internet: bool
    internet_probe_urls: tuple[str, str]

@dataclass(frozen=True)
class CheckResult:
    target: str
    success: bool | None
    category: str
    checked_at: datetime
    duration_ms: int
    detail: str = ""

@dataclass
class TargetState:
    status: str
    consecutive_failures: int
    consecutive_successes: int
    failure_started_at: str | None
    last_notification_at: str | None
    last_success_at: str | None
    last_category: str | None

@dataclass(frozen=True)
class NotificationEvent:
    target: str
    kind: str
    notification_id: str
    title: str
    content: str

def advance_state(current: TargetState, result: CheckResult,
                  config: NodeConfig, now: datetime) -> tuple[TargetState, list[NotificationEvent]]: ...
def check_dashboard(config: NodeConfig, now: datetime) -> CheckResult: ...
def check_gateway(config: NodeConfig, command_runner: CommandRunner) -> CheckResult: ...
def check_internet(config: NodeConfig) -> CheckResult: ...

class InstanceLock:
    def acquire(self) -> bool: ...
    def release(self) -> None: ...

class NotificationClient:
    def send(self, event: NotificationEvent) -> bool: ...
    def cancel(self, notification_id: str) -> bool: ...
```

`CheckResult.success=True` is confirmed healthy, `False` is confirmed failed, and `None` means unknown/unverified and never increments a failure counter.

The config template must set:

```json
"internet_probe_urls": [
  "https://connectivitycheck.gstatic.com/generate_204",
  "https://www.cloudflare.com/cdn-cgi/trace"
]
```

Implementation must first live-check these endpoints. Google must return HTTP 204; Cloudflare must return HTTP 200, read no more than 2048 bytes, and contain `visit_scheme=https`. Any one valid response means internet healthy. TLS verification remains enabled; redirects, TLS, DNS, timeout, and unexpected HTTP/body results receive separate classifications without logging query strings or response bodies.

## Task 1: Create the package skeleton and configuration contract

**Files:** `android/termux/node_config.py`, `android/termux/config.example.json`, `android/termux/tests/__init__.py`, `android/termux/tests/test_config.py`

**Interfaces:** `NodeConfig`; `load_config(path: Path) -> NodeConfig`; `validate_base_url(value: str) -> str`.

- [ ] Write failing tests for exact defaults, both probe URLs, immutable config, invalid numeric values, non-HTTP dashboard URLs, credentials in URLs, and invalid probe URL count.
- [ ] Run `python -m unittest android.termux.tests.test_config -v`; confirm imports/functions are initially absent.
- [ ] Implement frozen `NodeConfig`, strict JSON load, URL normalization without secrets, and numeric/bool validation. Require exactly two HTTPS probe URLs only when `check_internet` is true.
- [ ] Add the approved editable dashboard example and fixed public probe defaults to `config.example.json`.
- [ ] Re-run focused tests and `python -m py_compile android/termux/node_config.py`.
- [ ] Review configuration values against this plan; commit only this coherent contract after `git diff --check`.

## Task 2: Implement configuration-driven target state transitions

**Files:** `android/termux/node_state.py`, `android/termux/tests/test_state.py`

**Interfaces:** `TargetState`, `NotificationEvent`, `advance_state`, `default_target_state() -> TargetState`.

- [ ] Write failing literal tests for unknown-to-healthy, suspected failure, confirmed failure, failed-to-recovering, confirmed recovery, reminder throttling, and `success=None` preserving failure counts.
- [ ] Include a non-default `NodeConfig(failure_threshold=2, recovery_threshold=3, reminder_interval_seconds=120, ...)` fixture; prove the transition function follows those fields rather than hardcoded 3/2/3600.
- [ ] Implement pure state transition logic. Confirmed failures create one fixed-ID event per target; same-target failure reminders obey `config.reminder_interval_seconds`; recovery creates one recovery event.
- [ ] Serialize timestamps as ISO-8601 strings and keep no I/O in this module.
- [ ] Run `python -m unittest android.termux.tests.test_state -v`, then review state/notification semantics and commit.

## Task 3: Implement dashboard probe and JSON freshness validation

**Files:** `android/termux/node_checks.py`, `android/termux/tests/test_checks.py`, `android/termux/tests/fixtures/`

**Interfaces:** `check_dashboard`; injectable private opener/clock helpers used only to make tests deterministic.

- [ ] Write failing local-server or injected-opener tests for unreachable, timeout, non-success health response, invalid health body, invalid metrics JSON, wrong status, missing/invalid/stale `updated_at`, non-object metrics, and fresh valid metrics.
- [ ] Define stale age as `max(2 * config.check_interval_seconds + config.request_timeout_seconds, 125)` seconds.
- [ ] Implement sequential `GET /healthz` then `GET /api/metrics` using `urllib.request`, bounded reads, and category-only detail text. Treat health success plus stale metrics as `success=False, category="metrics_stale"`.
- [ ] Run focused checks without external network and commit after tests, compile, and diff review.

## Task 4: Implement gateway and internet checks without false router failures

**Files:** `android/termux/node_checks.py`, `android/termux/tests/test_checks.py`

**Interfaces:** `CommandRunner = Callable[[list[str]], CompletedCommand]`; `check_gateway`; `check_internet`.

- [ ] Write failing tests for `ip route` parsing, absent gateway, all accepted neighbor states, neighbor absence, TCP success, `ConnectionRefusedError`, `EHOSTUNREACH`, `ENETUNREACH`, timeout, missing tool, Google 204, Cloudflare valid trace, and both internet targets failing.
- [ ] Implement gateway order: parse `ip route`; return `gateway_unknown` with `success=None` if absent; accept `REACHABLE`, `STALE`, `DELAY`, `PROBE`, or `PERMANENT` from `ip neigh show`; otherwise make one TCP/53 attempt.
- [ ] Map TCP refusal to `success=True` because the gateway replied. Map host/network unreachable to `False`; timeout to `gateway_unverified` and unavailable tools/permission to `gateway_probe_unavailable`, both `None`. Never scan ports or use ICMP.
- [ ] Implement internet requests with verified TLS and bounded Cloudflare reads; classify redirect, TLS, DNS, timeout, HTTP and trace mismatch separately. Any valid endpoint succeeds.
- [ ] Run focused tests with injected runners/openers, then commit.

## Task 5: Add durable state, bounded logs, and safe notification adaptation

**Files:** `android/termux/node_runtime.py`, `android/termux/tests/test_runtime.py`

**Interfaces:** `load_state(path: Path) -> dict[str, TargetState]`; `save_state_atomic(path: Path, states: dict[str, TargetState]) -> None`; `configure_logging(log_path: Path, max_bytes: int, backup_count: int) -> Logger`; `NotificationClient`.

- [ ] Write failing tests for state round trip, corrupt-state fallback, atomic replacement, 1 MiB/5-backup rotation arguments, notification success, absent command, non-zero notification command, and error-rate limiting.
- [ ] Implement JSON-only state parsing and same-directory temporary-file plus `fsync` and `os.replace` write. Preserve corrupt state as a timestamped sibling for inspection; do not execute it.
- [ ] Use `RotatingFileHandler`; log outcome/category/duration with limited error text and periodic summaries, never full metrics or response bodies.
- [ ] Implement `termux-notification` calls with fixed event IDs and `termux-notification-remove` cancel. A notification error returns false and logs a throttled local error only.
- [ ] Run runtime tests, compile, and commit.

## Task 6: Add a PID-reuse-safe instance lock

**Files:** `android/termux/node_runtime.py`, `android/termux/tests/test_runtime.py`

**Interfaces:** `InstanceLock(lock_path: Path, script_path: Path)`; `acquire`; `release`.

- [ ] Write failing tests for exclusive creation, active matching node, dead PID, corrupt lock, mismatched cmdline, and reused PID with differing `/proc/<pid>/stat` start ticks.
- [ ] Require lock JSON fields `pid`, `started_at`, `process_start_ticks`, and absolute `script_path`.
- [ ] Implement active-process verification using `os.kill(pid, 0)`, `/proc/<pid>/cmdline`, and `/proc/<pid>/stat`; only recognize an exact script-path/start-tick match as this node.
- [ ] Never signal another process. Replace only the exact node lock after a dead, corrupt, mismatched, or reused-PID determination; release only a lock owned by this instance.
- [ ] Run lock tests and commit.

## Task 7: Compose CLI, one-shot diagnostics, scheduling, and graceful exit

**Files:** `android/termux/monitor_node.py`, `android/termux/tests/test_monitor_node.py`

**Interfaces:** `run_once(config: NodeConfig, now: datetime) -> list[CheckResult]`; `run_forever(config_path: Path) -> int`; `main(argv: Sequence[str] | None = None) -> int`.

- [ ] Write failing tests for `--once`, disabled gateway/internet paths, one target exception not ending a round, lock contention exit, SIGTERM state save/release, and configuration error exit.
- [ ] Implement CLI modes `--once` and default loop. Compose checks, advance each target state, persist state after each round, dispatch resulting events, and wait with an interruptible event for `check_interval_seconds`.
- [ ] Catch per-target exceptions into classified `CheckResult` values; never let one network error terminate the process.
- [ ] Run CLI tests and all Python tests; commit.

## Task 8: Implement the Termux:Boot supervisor

**Files:** `android/termux/boot.sh`

**Interfaces:** environment variables `NODE_HOME`, `NODE_CONFIG`, `NODE_SCRIPT`; exit code 0 for normal stop, non-zero for supervisor failure.

- [ ] Add a shell test harness or Termux integration assertions before script behavior.
- [ ] Use `set -eu`, quote every path, sleep `startup_delay_seconds` from validated config, request wake lock, and start only the deployed Python script.
- [ ] Rely on `InstanceLock` for duplicate prevention; do not parse JSON with `eval` or create a second business-state machine in shell.
- [ ] Apply `5, 15, 30, 60, 300` second crash backoff; reset after one stable check window. After the documented crash limit, emit one local crash notification and stop rapid restarting.
- [ ] Validate with `bash -n android/termux/boot.sh` when Bash exists; otherwise run `sh -n` in Termux and record Windows omission. Commit.

## Task 9: Implement idempotent install and reversible uninstall

**Files:** `android/termux/install.sh`, `android/termux/uninstall.sh`

**Interfaces:** `install.sh [--config PATH]`; `uninstall.sh [--purge-data]`.

- [ ] Write shell/Termux integration checks for repeated installation, valid-config preservation, missing command error, default uninstall retention, explicit purge scope, and unknown argument refusal.
- [ ] `install.sh` checks trusted local commands, creates exact paths/permissions, copies a template only when config is missing or invalid, validates config, runs one foreground diagnostic, and writes `~/.termux/boot/start-hardware-monitor-node` as a tiny wrapper calling deployed `boot.sh`.
- [ ] Use temporary file plus atomic move for generated files. Do not download APKs or overwrite a valid configuration.
- [ ] `uninstall.sh` stops only a verified node, releases wake lock, removes only the known wrapper and program paths, preserves config/log/state by default, and accepts only `--purge-data` for exact node data removal. Never recursively delete or remove Termux home.
- [ ] Run syntax/integration checks and commit.

## Task 10: Write Termux-specific operator documentation

**Files:** `android/termux/README.md`

**Interfaces:** documented commands must match Tasks 7–9 exactly.

- [ ] Document compatible-signature Termux/Termux:Boot/Termux:API installation, private configuration, dashboard address editing, foreground diagnostic, status/log inspection, safe uninstall, and known Android/Vivo limits.
- [ ] Separate automatable ADB actions from mandatory human confirmations: APK install, USB RSA, notification permission, battery optimization, self-start, and background permission.
- [ ] Document that no incoming phone port, remote control, or log upload exists.
- [ ] Review command names against actual script interfaces and commit.

## Task 11: Run Windows-local complete verification

**Files:** no new product files unless a deterministic test defect is found.

**Interfaces:** validates the Task 1–9 public interfaces without changing their signatures.

- [ ] Run:

```text
python -m py_compile android/termux/monitor_node.py
python -m py_compile android/termux/node_config.py
python -m py_compile android/termux/node_checks.py
python -m py_compile android/termux/node_state.py
python -m py_compile android/termux/node_runtime.py
python -m unittest discover -s android/termux/tests -v
git diff --check
```

- [ ] Run `bash -n` for all three shell scripts if Bash is available; otherwise do not install Bash and defer `sh -n` to Termux.
- [ ] Inspect `git status --short`, changed-file list, secrets, local config, logs, screenshots, artifacts, and line endings. Fix only demonstrated defects; commit a narrowly scoped correction if needed.

## Task 12: Deploy to Termux and run controlled integration checks

**Files:** no repository changes by default; deployment copies only the implemented `android/termux/` files.

**Interfaces:** invokes `install.sh [--config PATH]`, `main(["--once"])`, `InstanceLock.acquire()`, and `NotificationClient` only through the implemented CLI.

- [ ] Require `C:\Users\admin\AppData\Local\Android\CodexPlatformTools\platform-tools\adb.exe devices -l` to report the Vivo V2158A / PD2158 as `device`; otherwise stop this task without faking results.
- [ ] Inspect installed Termux, Termux:Boot, and Termux:API package names/versions and verify compatible signing sources before any installation. Record source and SHA-256 for any future approved APK; never install an unknown APK or bypass confirmation.
- [ ] Push ordinary node files, create an editable device config, run `install.sh`, `monitor_node.py --once`, and limited-log checks. Confirm one PID and no phone listener.
- [ ] If Android UI control is denied by the environment, record that limitation; do not claim notification visual inspection passed.

## Task 13: Perform reversible device fault injection

**Files:** temporary device configuration only; restore atomically before task completion.

**Interfaces:** uses `run_once`, `advance_state`, `save_state_atomic`, and the documented install/uninstall commands; it does not introduce test-only production APIs.

- [ ] Back up the device configuration, then use a temporary test config: 5-second checks, 2-second timeout, failure threshold 3, recovery threshold 2, and 30-second reminder interval.
- [ ] Verify real `/healthz` and `/api/metrics`, then switch only dashboard port to an unlistened local port. Confirm three confirmed failures produce one dashboard event; restore the correct port and confirm two successes produce one recovery event.
- [ ] Test internet classification with injected local fake opener/test configuration, never by changing the router, Windows firewall, or household network.
- [ ] Confirm log/state bounds and single process. Run uninstall only in an isolated test directory so real config is not deleted; validate default retention and scoped `--purge-data`.
- [ ] Restore the original config, wake-lock state, and any test process; retain only bounded result summaries.

## Task 14: Record long-running observation and prepare review

**Files:** bounded test-result summary only if the repository's approved testing convention allows it; otherwise issue/PR notes, not product code.

**Interfaces:** consumes existing log/state files and CLI status output read-only; no new runtime interface is introduced.

- [ ] Record start/end time, check count, last-success time, PID, Boot-start record, log size, duplicate-process count, and any battery-temperature/manual heat observation.
- [ ] Observe USB disconnect, screen-off, several hours of operation, Android deep sleep, Vivo cleanup behavior, and reboot/Termux:Boot recovery as separate observation cases. Do not represent them as instant tests or wait indefinitely in one agent session.
- [ ] Re-run full local checks and verify no secret, runtime log, APK, screenshot, or temporary configuration is tracked.
- [ ] Before opening a future Draft PR, perform implementation review and specification review for every completed task; keep the PR draft until observations and required approvals are accurately represented.

## Per-Task Review Gate

For every implementation task: (1) run the named failing test and verify it fails for the missing behavior, (2) implement the smallest code to pass, (3) run targeted and relevant regression tests, (4) inspect `git diff --check` and changed paths, (5) review implementation against this plan and the approved design specification, and (6) create one purposeful commit only when that review passes.

## Plan Self-Review

Coverage maps directly to all approved design requirements: configuration, dashboard/gateway/internet semantics, configuration-driven state transitions, notification failure isolation, bounded persistence/logging, PID-safe locking, Boot recovery, reversible scripts, Android lifecycle, security boundaries, unit/integration/device testing, and long-run observations. All later function/type names match the locked interfaces. `success=None` never increments failures; TCP refusal proves gateway response; destructive shell patterns are prohibited; fault injection restores configuration; multi-hour behavior is explicitly observational.

Implementation begins only after this plan receives its own review and an explicit implementation authorization.
