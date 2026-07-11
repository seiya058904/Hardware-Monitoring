# Third-party notices

The packaged application includes these externally maintained components:

| Component | Version | Source | License | SHA-256 |
| --- | --- | --- | --- | --- |
| LibreHardwareMonitorLib.dll | 0.9.4 (`b8077435b898d57539956388cddf49f7dacb86f7`) | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/tag/v0.9.4 | MPL-2.0 | `A0F2728F1734C236A9D02D9E25A88BC4F8CB7BD1FAFF1770726BEB7AF06BF8DC` |
| PresentMon.exe | 2.3.1 | https://github.com/GameTechDev/PresentMon/releases/tag/v2.3.1 | MIT | `364E5D98D4D134BD54DD25C22ED2CA2F4883F8BC3ED6502BEE0C151E3436D30C` |

`scripts/fetch-dependencies.ps1` downloads the pinned PresentMon 2.3.1 and LibreHardwareMonitor 0.9.4 inputs and verifies their hashes before replacing the canonical build inputs. The PyInstaller spec repeats the file hash checks and fails the build if either canonical input differs. Keep the upstream license files with the downloaded packages when redistributing them.

PresentMon 2.3.1 EXE SHA-256: `364E5D98D4D134BD54DD25C22ED2CA2F4883F8BC3ED6502BEE0C151E3436D30C`.
LibreHardwareMonitor-net472.zip SHA-256: `D2E397CC4D33D65C6493DFF83B9335BC341A3AF31CAAFCEEF83F717FDAB37448`.
