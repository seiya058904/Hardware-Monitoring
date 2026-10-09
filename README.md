<h1 align="center">🖥️ Hardware Monitoring</h1>

<p align="center">
  <strong>Know what your PC is doing. At a glance.</strong>
</p>

<p align="center">
  A lightweight Windows monitoring overlay for hardware metrics, game performance,<br>
  and a clear view of your system—right where you need it.
</p>

<p align="center">
  <a href="https://github.com/seiya058904/Hardware-Monitoring/releases/latest"><strong>⬇️ Download for Windows</strong></a>
  &nbsp;·&nbsp;
  <a href="#get-started">🚀 Get Started</a>
  &nbsp;·&nbsp;
  <a href="#at-a-glance">📊 Features</a>
  &nbsp;·&nbsp;
  <a href="#on-another-screen">📱 LAN Dashboard</a>
  &nbsp;·&nbsp;
  <a href="#for-developers">⚙️ Development</a>
</p>

<p align="center">
  <sub>WINDOWS OVERLAY &nbsp;·&nbsp; LIVE METRICS &nbsp;·&nbsp; GAME FPS &nbsp;·&nbsp; OPTIONAL LAN VIEW</sub><br>
  <sub>ENGLISH / SIMPLIFIED CHINESE &nbsp;·&nbsp; LATEST RELEASE v1.0.14</sub>
</p>

<p align="center">
  <img width="740" alt="Hardware Monitoring — original project overview" src="https://github.com/user-attachments/assets/11b6ff6b-830c-418a-89f9-98d1758eaa25" />
</p>

---

> **Useful readings. Honest status. Less visual noise.**
>
> Hardware Monitoring keeps the important numbers within reach, without turning your desktop into a full analytics dashboard. When a sensor cannot provide a reliable reading, the application distinguishes missing or stale data from a real zero.

<a id="at-a-glance"></a>
## ✨ At a Glance

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>⚡ Live Hardware</h3>
      <p><sub>CPU · GPU · MEMORY · TEMPERATURES</sub></p>
      <p>Observe utilization, clocks, power, thermals, and memory-related readings from the devices and sensors that support them.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🎮 Game Performance</h3>
      <p><sub>FPS · 1% LOW · TARGET PROCESS</sub></p>
      <p>Enable frame-rate monitoring when needed, choose the target game process, and inspect FPS or available 1% Low measurements.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>🪟 A Desktop-First Overlay</h3>
      <p><sub>COMPACT VIEW · OPACITY · ALWAYS ON TOP</sub></p>
      <p>Keep a small, configurable window nearby. Adjust which metrics appear, their order, the refresh interval, and the overlay's appearance.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🛡️ Sampling Health</h3>
      <p><sub>FRESH · DEGRADED · STALE · UNAVAILABLE</sub></p>
      <p>See whether a measurement is current, partially degraded, out of date, or unavailable instead of mistaking an old value for a live one.</p>
    </td>
  </tr>
</table>

### 📈 What Can Be Monitored?

| Area | Examples |
| --- | --- |
| **Processor & graphics** | CPU/GPU load, temperatures, clocks, power, fans, and VRAM where supported |
| **Memory & system** | RAM usage, memory frequency, battery status, and supported sensor readings |
| **Game performance** | FPS, 1% Low, and the selected target process |
| **Storage & network** | Disk activity, network throughput, latency, and available SSD temperature |

> [!NOTE]
> **Available metrics depend on your hardware, drivers, permissions, and capture tools.** Missing data is shown as unavailable; not every PC can expose every sensor or provide frame-time statistics.

<a id="get-started"></a>
## 🚀 Get Started

### 1. Download and install

Get the Windows installer from **[GitHub Releases](https://github.com/seiya058904/Hardware-Monitoring/releases/latest)**.

**Current release:** [v1.0.14](https://github.com/seiya058904/Hardware-Monitoring/releases/tag/v1.0.14) · [Direct installer download](https://github.com/seiya058904/Hardware-Monitoring/releases/download/v1.0.14/HardwareMonitoring_Setup_v1.0.14.exe)

The installer may request administrator approval. Normal monitoring is designed for the Windows desktop; some capture capabilities can depend on system permissions.

### 2. Set up your overlay

Launch **Hardware Monitoring**, check the available measurements, and customize the window for your desktop.

- Choose the metrics you want to see and their order.
- Adjust compact mode, opacity, theme, and refresh frequency.
- Enable game FPS collection or the LAN dashboard only when you need them.
- Use **Save** to apply persistent settings; **Cancel** discards an unfinished settings preview.

### 3. Leave it within reach

Use the overlay alongside your work or games, with tray access and window-position controls designed for normal desktop use.

Your local configuration and logs are stored under:

```text
%LOCALAPPDATA%\Hardware Monitoring
```

Ordinary uninstall is designed to preserve that user data rather than silently deleting personal settings and logs.

<a id="on-another-screen"></a>
## 📱 On Another Screen

You can optionally open a **read-only LAN dashboard** on a phone, tablet, or another computer while Hardware Monitoring runs on Windows. It uses the same monitoring data as the desktop overlay.

<table>
  <tr>
    <td width="50%" valign="top">
      <img width="100%" alt="Hardware Monitoring — existing mobile LAN dashboard screenshot" src="https://github.com/user-attachments/assets/8b3a7b37-8b3b-4df3-8617-d46968ff386f" />
      <p align="center"><sub>MOBILE VIEW</sub></p>
    </td>
    <td width="50%" valign="top">
      <img width="100%" alt="Hardware Monitoring — existing LAN metrics screenshot" src="https://github.com/user-attachments/assets/bc32c3e2-4bfd-4ec3-b402-3ca316fc8b86" />
      <p align="center"><sub>METRICS VIEW</sub></p>
    </td>
  </tr>
</table>

**To use it:**

1. Open **Advanced Settings** in the Windows application and explicitly enable the LAN dashboard. It is **off by default**.
2. Put the viewing device and your PC on the **same trusted private network**.
3. Open the LAN address shown by the application in the other device's browser (default port **`8765`**).

The dashboard provides a responsive metrics view with English / Simplified Chinese and light / dark display options. Its exposed HTTP routes are limited to `GET /`, `GET /api/metrics`, and `GET /healthz`; it does **not** offer remote PC control or file access.

> [!WARNING]
> **Private networks only.** The optional LAN server has **no authentication** and must not be exposed to the public internet, a port-forward, or a public tunnel. Hardware Monitoring does not automatically change your firewall or router settings.

### 📡 Optional Android Companion

The [Termux monitoring node](android/termux/README.md) can perform **outbound-only health checks** from Android against your trusted Windows dashboard and configured network targets. It opens no incoming port on the phone and is **not required** for ordinary Windows monitoring.

## 🔍 Trust the Reading, Not Just the Number

The application tracks the state of its sampling pipeline, not just the last value it received.

| State | What it tells you |
| --- | --- |
| `ok` | Fresh readings are available. |
| `degraded` | Updated data is available, but one or more device sources had a problem. |
| `stale` | The last sample is too old to treat as current. |
| `unavailable` | A reliable sample is not currently available. |

On the LAN dashboard, sample state and age matter **in addition to** whether the HTTP service responds. A healthy network response alone does not mean that the underlying hardware measurements are fresh.

<a id="for-developers"></a>
## ⚙️ For Developers

The application uses **Python / Tkinter** for the desktop interface, **LibreHardwareMonitor** for supported sensor access, and **PresentMon** for game-frame capture. The optional LAN service is a bounded, read-only HTTP server.

<details>
<summary><strong>🛠️ Expand source layout, local verification &amp; packaging</strong></summary>

### Source map

| Path | Purpose |
| --- | --- |
| [`app.py`](app.py) | Windows overlay, settings, tray, and dashboard integration |
| [`sensor_runtime.py`](sensor_runtime.py) | Sampling pipeline and freshness reporting |
| [`fps_stream.py`](fps_stream.py) · [`fps_sessions.py`](fps_sessions.py) | Frame capture and active session ownership |
| [`service_runtime.py`](service_runtime.py) | Background service changes without blocking Tk |
| [`dashboard_server.py`](dashboard_server.py) | Bounded LAN request handling and shutdown |
| [`android/termux/`](android/termux/) | Optional, outbound-only Android monitoring node |
| [`tests/`](tests/) | Core, desktop, sampling, and installer regressions |

### Run and verify

On Windows, install the pinned Python dependencies from [`requirements-runtime.txt`](requirements-runtime.txt), then run the application and its tests from the repository root:

```powershell
python -m pip install -r requirements-runtime.txt
python app.py
python -m unittest discover -s tests -v
```

A fresh checkout may also need the exact pinned PresentMon and LibreHardwareMonitor build inputs. With network acquisition explicitly intended, [`scripts/fetch-dependencies.ps1`](scripts/fetch-dependencies.ps1) downloads and SHA-256-verifies them. Do not substitute arbitrary binaries or remove ignored canonical inputs during cleanup.

### Packaging

PyInstaller (listed in [`requirements-build.txt`](requirements-build.txt)) and NSIS are required for Windows installer builds:

```powershell
python -m pip install -r requirements-build.txt
pyinstaller "Hardware Monitoring.spec" --noconfirm
makensis "Hardware Monitoring.nsi"
```

The PyInstaller specification checks the pinned binary hashes. CI runs Python syntax and Windows core tests plus Linux-based Termux contracts; those checks do **not** by themselves prove physical Android behavior, multi-monitor hardware scenarios, or successful ETW/FPS capture on every machine.

**Further reading:** [Engineering upgrade](docs/engineering-upgrade-1.0.13.md) · [Release audit](docs/release-audit-1.0.13.md) · [Repository guidelines](AGENTS.md)

</details>

## 📜 Rights & Notices

Hardware Monitoring is an observation tool, **not a substitute for professional hardware diagnostics**. Sensor availability and refresh behavior depend on the system being monitored.

Third-party component licenses and provenance are recorded in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`third_party/licenses/`](third_party/licenses/). Public source access should not be mistaken for a project-wide license that has not been declared.

---

<p align="center">
  <sub>THE RIGHT NUMBERS. THE RIGHT PLACE. THE RIGHT CONTEXT.</sub><br>
  <sub>Hardware Monitoring · A quieter view of your Windows PC.</sub>
</p>
