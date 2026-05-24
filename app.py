import ctypes
import ctypes.wintypes
import csv
import json
import logging
import shutil
import tempfile
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from collections import deque
from pathlib import Path
from typing import Dict, Optional

import psutil
try:
    import winreg
except Exception:
    winreg = None

try:
    import clr  # type: ignore
except Exception:
    clr = None

APP_NAME = "Hardware Monitoring"


def setup_logger(app_dir: Path) -> logging.Logger:
    logger = logging.getLogger("hardware_monitor")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_path = app_dir / "hardware_monitor.log"
    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "hardware_monitor.log"
        handler = logging.FileHandler(fallback, encoding="utf-8")
        log_path = fallback
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.info("Log file path: %s", str(log_path))
    return logger


DEFAULT_CONFIG = {
    "refresh_interval_ms": 1000,
    "window_opacity": 0.96,
    "always_on_top": False,
    "minimize_to_tray": True,
    "theme": "深色蓝",
    "ui_language": "zh",
    "font_scale": 1.0,
    "display_mode": "标准",
    "compact_mode": False,
    "show_group_titles": True,
    "fps_enabled": False,
    "fps_target_process": "",
    "show_cpu_usage": True,
    "show_memory_usage": True,
    "show_gpu_usage": True,
    "show_vram_usage": True,
    "show_cpu_temperature": True,
    "show_gpu_temperature": True,
    "show_cpu_fan": False,
    "show_gpu_fan": False,
    "show_cpu_power": False,
    "show_gpu_power": False,
    "show_cpu_freq": True,
    "show_gpu_freq": True,
    "show_vram_freq": False,
    "show_memory_freq": False,
    "show_ssd_temperature": False,
    "show_network_latency": False,
    "show_disk_speed": True,
    "show_network_speed": True,
    "show_disk_read": False,
    "show_disk_write": False,
    "show_net_up": False,
    "show_net_down": False,
    "show_battery": False,
    "show_fps": True,
    "show_fps_low_1": True,
    "show_target_process": True,
    "metric_order": [],
    "autostart": False,
    "close_action": "exit",
    "log_level": "INFO",
}

THEMES = {
    "深色蓝": {"bg": "#0f1115", "panel": "#151b28", "border": "#2b3550", "text": "#f5f7fa", "sub": "#cfd6e6", "hint": "#8190ac", "accent": "#4f8cff"},
    "苹果浅色": {"bg": "#f5f7fb", "panel": "#ffffff", "border": "#d5dcea", "text": "#1f2937", "sub": "#475569", "hint": "#64748b", "accent": "#2f7cff"},
    "石墨灰": {"bg": "#171717", "panel": "#242424", "border": "#3a3a3a", "text": "#f1f5f9", "sub": "#d4d4d8", "hint": "#a1a1aa", "accent": "#6ea8fe"},
    "炫彩红": {"bg": "#1a0a0a", "panel": "#2a1010", "border": "#4a2020", "text": "#fff0f0", "sub": "#e8c0c0", "hint": "#a87070", "accent": "#ff4040"},
    "极光绿": {"bg": "#0a1a0f", "panel": "#102a18", "border": "#204a30", "text": "#f0fff5", "sub": "#c0e8d0", "hint": "#70a880", "accent": "#40ff80"},
}
THEME_EN_LABEL = {
    "深色蓝": "Deep Blue",
    "苹果浅色": "Light",
    "石墨灰": "Graphite",
    "炫彩红": "Vibrant Red",
    "极光绿": "Aurora Green",
}

METRIC_LAYOUT = [
    ("游戏", "fps", "FPS", "show_fps"),
    ("游戏", "fps_low_1", "1% Low", "show_fps_low_1"),
    ("游戏", "target_process", "目标进程", "show_target_process"),
    ("系统", "cpu_usage", "CPU", "show_cpu_usage"),
    ("系统", "memory_usage", "内存", "show_memory_usage"),
    ("显卡", "gpu_usage", "GPU", "show_gpu_usage"),
    ("显卡", "gpu_memory", "显存", "show_vram_usage"),
    ("温度与功耗", "cpu_temp", "CPU 温度", "show_cpu_temperature"),
    ("温度与功耗", "gpu_temp", "GPU 温度", "show_gpu_temperature"),
    ("温度与功耗", "cpu_fan", "CPU 风扇", "show_cpu_fan"),
    ("温度与功耗", "gpu_fan", "GPU 风扇", "show_gpu_fan"),
    ("温度与功耗", "cpu_power", "CPU 功耗", "show_cpu_power"),
    ("温度与功耗", "gpu_power", "GPU 功耗", "show_gpu_power"),
    ("温度与功耗", "ssd_temp", "SSD 温度", "show_ssd_temperature"),
    ("频率", "cpu_freq", "CPU 频率", "show_cpu_freq"),
    ("频率", "gpu_clock", "GPU 频率", "show_gpu_freq"),
    ("频率", "vram_freq", "显存频率", "show_vram_freq"),
    ("频率", "memory_freq", "内存频率", "show_memory_freq"),
    ("系统状态", "disk_speed", "磁盘", "show_disk_speed"),
    ("系统状态", "disk_read", "磁盘读取", "show_disk_read"),
    ("系统状态", "disk_write", "磁盘写入", "show_disk_write"),
    ("系统状态", "network_speed", "网络", "show_network_speed"),
    ("系统状态", "network_latency", "网络延迟", "show_network_latency"),
    ("系统状态", "network_up", "网络上传", "show_net_up"),
    ("系统状态", "network_down", "网络下载", "show_net_down"),
    ("系统状态", "battery_status", "电池", "show_battery"),
]

METRIC_MAP = {key: (group, label, cfg_key) for group, key, label, cfg_key in METRIC_LAYOUT}
DEFAULT_METRIC_ORDER = [key for _, key, _, _ in METRIC_LAYOUT]
METRIC_LABEL_EN = {
    "fps": "FPS",
    "fps_low_1": "1% Low",
    "target_process": "Target",
    "cpu_usage": "CPU",
    "memory_usage": "Memory",
    "gpu_usage": "GPU",
    "gpu_memory": "VRAM",
    "cpu_temp": "CPU Temp",
    "gpu_temp": "GPU Temp",
    "cpu_fan": "CPU Fan",
    "gpu_fan": "GPU Fan",
    "cpu_power": "CPU Power",
    "gpu_power": "GPU Power",
    "cpu_freq": "CPU Clock",
    "gpu_clock": "GPU Clock",
    "vram_freq": "VRAM Clock",
    "memory_freq": "Memory Clock",
    "disk_speed": "Disk",
    "disk_read": "Disk Read",
    "disk_write": "Disk Write",
    "network_speed": "Network",
    "network_latency": "Latency",
    "ssd_temp": "SSD Temp",
    "network_up": "Upload",
    "network_down": "Download",
    "battery_status": "Battery",
}
GROUP_LABEL_EN = {
    "游戏": "Game",
    "系统": "System",
    "显卡": "GPU",
    "温度与功耗": "Thermal/Power",
    "频率": "Clocks",
    "系统状态": "System Status",
}


@dataclass
class Metrics:
    cpu_usage: str = "N/A"
    cpu_freq: str = "N/A"
    cpu_temp: str = "N/A"
    gpu_usage: str = "N/A"
    gpu_temp: str = "N/A"
    cpu_fan: str = "--"
    gpu_fan: str = "--"
    gpu_clock: str = "N/A"
    vram_freq: str = "--"
    gpu_memory: str = "N/A"
    memory_usage: str = "N/A"
    memory_freq: str = "N/A"
    cpu_power: str = "--"
    gpu_power: str = "--"
    disk_speed: str = "--"
    disk_read: str = "--"
    disk_write: str = "--"
    network_speed: str = "--"
    network_up: str = "--"
    network_down: str = "--"
    battery_status: str = "--"
    fps: str = "--"
    fps_low_1: str = "--"
    target_process: str = "--"
    ssd_temp: str = "--"
    network_latency: str = "--"
    temp_hint: str = ""
    source_status: str = ""


class SensorReader:
    class _CoreTempSharedData(ctypes.Structure):
        _pack_ = 4
        _fields_ = [
            ("uiLoad", ctypes.c_uint32 * 256),
            ("uiTjMax", ctypes.c_uint32 * 128),
            ("uiCoreCnt", ctypes.c_uint32),
            ("uiCPUCnt", ctypes.c_uint32),
            ("fTemp", ctypes.c_float * 256),
            ("fVID", ctypes.c_float),
            ("fCPUSpeed", ctypes.c_float),
            ("fFSBSpeed", ctypes.c_float),
            ("fMultiplier", ctypes.c_float),
            ("sCPUName", ctypes.c_char * 100),
            ("ucFahrenheit", ctypes.c_ubyte),
            ("ucDeltaToTjMax", ctypes.c_ubyte),
        ]

    class _CoreTempSharedDataEx(ctypes.Structure):
        _pack_ = 4
        _fields_ = [
            ("uiLoad", ctypes.c_uint32 * 256),
            ("uiTjMax", ctypes.c_uint32 * 128),
            ("uiCoreCnt", ctypes.c_uint32),
            ("uiCPUCnt", ctypes.c_uint32),
            ("fTemp", ctypes.c_float * 256),
            ("fVID", ctypes.c_float),
            ("fCPUSpeed", ctypes.c_float),
            ("fFSBSpeed", ctypes.c_float),
            ("fMultiplier", ctypes.c_float),
            ("sCPUName", ctypes.c_char * 100),
            ("ucFahrenheit", ctypes.c_ubyte),
            ("ucDeltaToTjMax", ctypes.c_ubyte),
            ("ucTdpSupported", ctypes.c_ubyte),
            ("ucPowerSupported", ctypes.c_ubyte),
            ("uiStructVersion", ctypes.c_uint32),
            ("uiTdp", ctypes.c_uint32 * 128),
            ("fPower", ctypes.c_float * 128),
            ("fMultipliers", ctypes.c_float * 256),
        ]

    def __init__(self) -> None:
        self._lhm_computer = None
        self._lhm_hardware = None
        self._lhm_error = ""
        self._lhm_retry_count = 0
        self._last_fallback_ts = 0.0
        self._fallback_cache: Dict[str, Optional[float]] = {
            "cpu_coretemp": None,
            "cpu_temp": None,
            "gpu_temp": None,
            "memory_freq": None,
        }
        self._last_status: Dict[str, str] = {}
        self._external_lhm_proc = None
        self._last_disk = None
        self._last_net = None
        self._last_io_ts = 0.0
        self._ping_cache: Optional[float] = None
        self._ping_cache_ts = 0.0
        self._init_lhm()

    def _runtime_base_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS)  # type: ignore[attr-defined]
        return Path(__file__).resolve().parent

    def _app_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _init_lhm(self) -> None:
        if clr is None:
            self._lhm_error = "pythonnet 未加载"
            return

        dll_path = self._runtime_base_dir() / "libs" / "LibreHardwareMonitorLib.dll"
        if not dll_path.exists():
            self._lhm_error = f"缺少 DLL: {dll_path}"
            return

        try:
            clr.AddReference(str(dll_path))
            from LibreHardwareMonitor import Hardware  # type: ignore

            computer = Hardware.Computer()
            computer.IsCpuEnabled = True
            computer.IsGpuEnabled = True
            computer.IsMemoryEnabled = True
            computer.IsMotherboardEnabled = True
            computer.IsControllerEnabled = False
            computer.IsStorageEnabled = True
            computer.Open()

            self._lhm_computer = computer
            self._lhm_hardware = Hardware
        except Exception:
            self._lhm_computer = None
            self._lhm_hardware = None
            self._lhm_error = "LHM 初始化失败(运行库兼容性或驱动限制)"

    def _start_external_lhm_if_available(self) -> None:
        base = self._app_dir()
        candidates = [
            base / "tools" / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe",
            base / "LibreHardwareMonitor.exe",
        ]
        for exe in candidates:
            if not exe.exists():
                continue
            try:
                self._external_lhm_proc = subprocess.Popen(
                    [str(exe)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                )
                break
            except Exception:
                self._external_lhm_proc = None

    def close(self) -> None:
        try:
            if self._lhm_computer is not None:
                self._lhm_computer.Close()
        except Exception:
            pass
        try:
            if self._external_lhm_proc is not None and self._external_lhm_proc.poll() is None:
                self._external_lhm_proc.terminate()
        except Exception:
            pass

    def _walk_sensors(self):
        if self._lhm_computer is None:
            return []

        entries = []
        for hw in self._lhm_computer.Hardware:
            hw.Update()
            entries.append(hw)
            for sub_hw in hw.SubHardware:
                sub_hw.Update()
                entries.append(sub_hw)
        return entries

    @staticmethod
    def _pick_max(current: Optional[float], candidate: float) -> float:
        if current is None:
            return candidate
        return max(current, candidate)

    def _read_coretemp_shared_memory(self) -> Optional[float]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        file_map_read = 0x0004
        names = [
            ("CoreTempMappingObjectEx", self._CoreTempSharedDataEx),
            ("Global\\CoreTempMappingObjectEx", self._CoreTempSharedDataEx),
            ("CoreTempMappingObject", self._CoreTempSharedData),
            ("Global\\CoreTempMappingObject", self._CoreTempSharedData),
        ]

        kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.OpenFileMappingW.restype = ctypes.c_void_p
        kernel32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        kernel32.UnmapViewOfFile.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        for mapping_name, struct_type in names:
            handle = kernel32.OpenFileMappingW(file_map_read, False, mapping_name)
            if not handle:
                continue

            view = None
            try:
                view = kernel32.MapViewOfFile(handle, file_map_read, 0, 0, ctypes.sizeof(struct_type))
                if not view:
                    continue

                data = struct_type.from_address(view)
                core_count = int(data.uiCoreCnt) * max(1, int(data.uiCPUCnt))
                core_count = min(core_count, 256)
                temps = []
                for idx in range(core_count):
                    val = float(data.fTemp[idx])
                    if data.ucFahrenheit:
                        val = (val - 32.0) * 5.0 / 9.0
                    if data.ucDeltaToTjMax:
                        tjmax = float(data.uiTjMax[idx % 128])
                        val = tjmax - val
                    if 0 < val < 130:
                        temps.append(val)
                if temps:
                    return max(temps)
            except Exception:
                continue
            finally:
                if view:
                    kernel32.UnmapViewOfFile(view)
                kernel32.CloseHandle(handle)

        return None

    def _read_lhm_values(self) -> Dict[str, Optional[float]]:
        values: Dict[str, Optional[float]] = {
            "cpu_usage": None,
            "cpu_freq": None,
            "cpu_temp": None,
            "gpu_usage": None,
            "gpu_temp": None,
            "gpu_clock": None,
            "gpu_memory_used": None,
            "gpu_memory_total": None,
            "memory_freq": None,
            "cpu_power": None,
            "gpu_power": None,
            "vram_freq": None,
            "cpu_fan": None,
            "gpu_fan": None,
            "ssd_temp": None,
        }

        if self._lhm_computer is None or self._lhm_hardware is None:
            if self._lhm_retry_count < 3:
                self._lhm_retry_count += 1
                self._init_lhm()
            return values

        sensor_type = self._lhm_hardware.SensorType
        cpu_fallback: Optional[float] = None
        gpu_fallback: Optional[float] = None

        try:
            for hw in self._walk_sensors():
                hw_type_name = str(hw.HardwareType)
                for sensor in hw.Sensors:
                    if sensor.Value is None:
                        continue

                    s_name = str(sensor.Name).lower()
                    sensor_value = float(sensor.Value)

                    if sensor.SensorType == sensor_type.Load and "Cpu" in hw_type_name:
                        if "total" in s_name:
                            values["cpu_usage"] = sensor_value
                    elif sensor.SensorType == sensor_type.Load and "Gpu" in hw_type_name:
                        if s_name == "gpu core":
                            values["gpu_usage"] = sensor_value

                    if sensor.SensorType == sensor_type.Temperature:
                        if "Cpu" in hw_type_name:
                            if "tctl" in s_name or "tdie" in s_name or "package" in s_name:
                                values["cpu_temp"] = self._pick_max(values["cpu_temp"], sensor_value)
                            else:
                                cpu_fallback = self._pick_max(cpu_fallback, sensor_value)
                        elif "Gpu" in hw_type_name:
                            if "core" in s_name and "hot" not in s_name:
                                values["gpu_temp"] = self._pick_max(values["gpu_temp"], sensor_value)
                            else:
                                gpu_fallback = self._pick_max(gpu_fallback, sensor_value)
                        elif "Storage" in hw_type_name or "Hdd" in hw_type_name:
                            values["ssd_temp"] = self._pick_max(values.get("ssd_temp"), sensor_value)
                        else:
                            if values["cpu_temp"] is None and "cpu" in s_name:
                                values["cpu_temp"] = sensor_value
                            if values["gpu_temp"] is None and "gpu" in s_name:
                                values["gpu_temp"] = sensor_value

                    if sensor.SensorType == sensor_type.Clock:
                        if "Cpu" in hw_type_name and s_name.startswith("core #"):
                            values["cpu_freq"] = self._pick_max(values["cpu_freq"], sensor_value)
                        elif "Gpu" in hw_type_name and s_name == "gpu core":
                            values["gpu_clock"] = sensor_value
                        elif "Gpu" in hw_type_name and "memory" in s_name:
                            values["vram_freq"] = self._pick_max(values["vram_freq"], sensor_value)
                        elif "Memory" in hw_type_name and "memory" in s_name:
                            values["memory_freq"] = self._pick_max(values["memory_freq"], sensor_value)

                    if str(sensor.SensorType) == "Power":
                        if "Cpu" in hw_type_name and ("package" in s_name or "cpu" in s_name):
                            values["cpu_power"] = self._pick_max(values["cpu_power"], sensor_value)
                        elif "Gpu" in hw_type_name and ("package" in s_name or "total" in s_name or "gpu" in s_name):
                            values["gpu_power"] = self._pick_max(values["gpu_power"], sensor_value)

                    if str(sensor.SensorType) == "Fan":
                        if "Cpu" in hw_type_name:
                            values["cpu_fan"] = self._pick_max(values["cpu_fan"], sensor_value)
                        elif "Gpu" in hw_type_name:
                            values["gpu_fan"] = self._pick_max(values["gpu_fan"], sensor_value)

                    if str(sensor.SensorType) in ("SmallData", "Data") and "Gpu" in hw_type_name:
                        if s_name == "gpu memory used":
                            values["gpu_memory_used"] = sensor_value
                        elif s_name == "gpu memory total":
                            values["gpu_memory_total"] = sensor_value
        except Exception:
            return values

        if values["cpu_temp"] is None:
            values["cpu_temp"] = cpu_fallback
        if values["gpu_temp"] is None:
            values["gpu_temp"] = gpu_fallback

        return values

    @staticmethod
    def _run_cmd(cmd: list[str], timeout: float = 0.8) -> str:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=0x08000000)
            if result.returncode != 0:
                return ""
            return result.stdout.strip()
        except Exception:
            return ""

    def _fallback_cpu_temp(self) -> Optional[float]:
        out = self._run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | Select-Object -ExpandProperty CurrentTemperature",
        ])
        if not out:
            return None
        temps = []
        for line in out.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            raw = int(line)
            celsius = (raw / 10.0) - 273.15
            if 0 < celsius < 130:
                temps.append(celsius)
        return max(temps) if temps else None

    def _fallback_ohm_wmi_cpu_temp(self) -> Optional[float]:
        out = self._run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance -Namespace root/OpenHardwareMonitor -ClassName Sensor | Where-Object { $_.SensorType -eq 'Temperature' -and ($_.Name -like '*CPU*' -or $_.Identifier -like '*cpu*') } | Select-Object -ExpandProperty Value",
        ])
        if not out:
            return None
        temps = []
        for line in out.splitlines():
            line = line.strip().replace(",", ".")
            try:
                val = float(line)
            except Exception:
                continue
            if 0 < val < 130:
                temps.append(val)
        return max(temps) if temps else None

    def _fallback_lhm_wmi_cpu_temp(self) -> Optional[float]:
        out = self._run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor | Where-Object { $_.SensorType -eq 'Temperature' -and ($_.Name -like '*CPU*' -or $_.Identifier -like '*cpu*') } | Select-Object -ExpandProperty Value",
        ])
        if not out:
            return None
        temps = []
        for line in out.splitlines():
            line = line.strip().replace(",", ".")
            try:
                val = float(line)
            except Exception:
                continue
            if 0 < val < 130:
                temps.append(val)
        return max(temps) if temps else None

    def _fallback_gpu_temp(self) -> Optional[float]:
        out = self._run_cmd([
            "nvidia-smi",
            "--query-gpu=temperature.gpu",
            "--format=csv,noheader,nounits",
        ])
        if not out:
            return None
        temps = []
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                val = float(line)
                if 0 < val < 130:
                    temps.append(val)
        return max(temps) if temps else None

    def _fallback_gpu_vram(self) -> Optional[dict]:
        out = self._run_cmd([
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ])
        if not out:
            return None
        parts = out.split(",")
        if len(parts) >= 2:
            try:
                return {"used": float(parts[0].strip()), "total": float(parts[1].strip())}
            except ValueError:
                return None
        return None

    def _fallback_ohm_wmi_gpu_temp(self) -> Optional[float]:
        out = self._run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance -Namespace root/OpenHardwareMonitor -ClassName Sensor | Where-Object { $_.SensorType -eq 'Temperature' -and ($_.Name -like '*GPU*' -or $_.Identifier -like '*gpu*') } | Select-Object -ExpandProperty Value",
        ])
        if not out:
            return None
        temps = []
        for line in out.splitlines():
            line = line.strip().replace(",", ".")
            try:
                val = float(line)
            except Exception:
                continue
            if 0 < val < 130:
                temps.append(val)
        return max(temps) if temps else None

    def _fallback_lhm_wmi_gpu_temp(self) -> Optional[float]:
        out = self._run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor | Where-Object { $_.SensorType -eq 'Temperature' -and ($_.Name -like '*GPU*' -or $_.Identifier -like '*gpu*') } | Select-Object -ExpandProperty Value",
        ])
        if not out:
            return None
        temps = []
        for line in out.splitlines():
            line = line.strip().replace(",", ".")
            try:
                val = float(line)
            except Exception:
                continue
            if 0 < val < 130:
                temps.append(val)
        return max(temps) if temps else None

    def _fallback_memory_freq(self) -> Optional[float]:
        out = self._run_cmd([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_PhysicalMemory | Select-Object -ExpandProperty Speed",
        ])
        if not out:
            return None
        speeds = []
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                val = float(line)
                if 100 < val < 10000:
                    speeds.append(val)
        return max(speeds) if speeds else None

    def _read_ping(self) -> Optional[float]:
        out = self._run_cmd(["ping", "-n", "1", "-w", "500", "8.8.8.8"])
        if not out:
            return None
        import re
        m = re.search(r"(?:time|时间)[=<](\d+)ms", out)
        if m:
            return float(m.group(1))
        return None

    def _read_fallback_values(self) -> Dict[str, Optional[float]]:
        now = time.time()
        if now - self._last_fallback_ts < 2:
            return self._fallback_cache

        self._last_fallback_ts = now
        cpu_coretemp = self._read_coretemp_shared_memory()
        cpu_wmi = self._fallback_cpu_temp()
        cpu_ohm = self._fallback_ohm_wmi_cpu_temp()
        cpu_lhm_wmi = self._fallback_lhm_wmi_cpu_temp()
        gpu_smi = self._fallback_gpu_temp()
        gpu_ohm = self._fallback_ohm_wmi_gpu_temp()
        gpu_lhm_wmi = self._fallback_lhm_wmi_gpu_temp()
        mem_wmi = self._fallback_memory_freq()

        gpu_vram = self._fallback_gpu_vram()

        self._fallback_cache = {
            "cpu_coretemp": cpu_coretemp,
            "cpu_temp": cpu_coretemp if cpu_coretemp is not None else (cpu_ohm if cpu_ohm is not None else cpu_lhm_wmi),
            "gpu_temp": gpu_smi if gpu_smi is not None else (gpu_ohm if gpu_ohm is not None else gpu_lhm_wmi),
            "memory_freq": mem_wmi,
            "gpu_vram": gpu_vram,
        }
        acpi_status = "失败"
        if cpu_wmi is not None:
            acpi_status = f"{cpu_wmi:.1f}C(系统热区,非核心温度)"
        self._last_status = {
            "LHM": "OK" if self._lhm_computer is not None else f"不可用({self._lhm_error})",
            "外部LHM": "已禁用(避免弹出驱动安装提示)",
            "CoreTemp共享内存": "OK" if cpu_coretemp is not None else "未运行/未开放",
            "ACPI热区": acpi_status,
            "CPU共享WMI": "OK" if cpu_ohm is not None else "失败",
            "CPU-LHM-WMI": "OK" if cpu_lhm_wmi is not None else "失败",
            "GPU nvidia-smi": "OK" if gpu_smi is not None else "失败",
            "GPU共享WMI": "OK" if gpu_ohm is not None else "失败",
            "GPU-LHM-WMI": "OK" if gpu_lhm_wmi is not None else "失败",
            "内存频率WMI": "OK" if mem_wmi is not None else "失败",
        }
        return self._fallback_cache

    def read_metrics(self) -> Metrics:
        metrics = Metrics()
        try:
            metrics.cpu_usage = f"{psutil.cpu_percent(interval=0.15):.0f}%"
            vm = psutil.virtual_memory()
            used_gb = (vm.total - vm.available) / (1024.0 ** 3)
            total_gb = vm.total / (1024.0 ** 3)
            metrics.memory_usage = f"{used_gb:.1f} / {total_gb:.1f} GB"
            cpu_freq = psutil.cpu_freq()
            if cpu_freq and cpu_freq.current:
                metrics.cpu_freq = f"{cpu_freq.current:.0f} MHz"
        except Exception:
            pass

        lhm = self._read_lhm_values()
        fb = self._read_fallback_values()

        if lhm.get("cpu_usage") is not None:
            metrics.cpu_usage = f"{lhm['cpu_usage']:.0f}%"
        if lhm.get("cpu_freq") is not None and lhm["cpu_freq"] > 1000:
            metrics.cpu_freq = f"{lhm['cpu_freq']:.0f} MHz"
        if lhm.get("gpu_usage") is not None:
            metrics.gpu_usage = f"{lhm['gpu_usage']:.0f}%"
        if lhm.get("gpu_clock") is not None:
            metrics.gpu_clock = f"{lhm['gpu_clock']:.0f} MHz"
        if lhm.get("vram_freq") is not None:
            metrics.vram_freq = f"{lhm['vram_freq']:.0f} MHz"
        if lhm.get("gpu_memory_used") is not None and lhm.get("gpu_memory_total") is not None:
            used_gb = lhm["gpu_memory_used"] / 1024.0
            total_gb = lhm["gpu_memory_total"] / 1024.0
            metrics.gpu_memory = f"{used_gb:.1f}/{total_gb:.1f} GB"
        elif fb.get("gpu_vram") is not None:
            vram = fb["gpu_vram"]
            metrics.gpu_memory = f"{vram['used']/1024:.1f}/{vram['total']/1024:.1f} GB"
        if lhm.get("cpu_power") is not None:
            metrics.cpu_power = f"{lhm['cpu_power']:.1f} W"
        if lhm.get("gpu_power") is not None:
            metrics.gpu_power = f"{lhm['gpu_power']:.1f} W"
        if lhm.get("cpu_fan") is not None:
            metrics.cpu_fan = f"{lhm['cpu_fan']:.0f} RPM"
        if lhm.get("gpu_fan") is not None:
            metrics.gpu_fan = f"{lhm['gpu_fan']:.0f} RPM"
        if lhm.get("ssd_temp") is not None:
            metrics.ssd_temp = f"{lhm['ssd_temp']:.1f} °C"

        cpu_temp = lhm["cpu_temp"] if lhm["cpu_temp"] is not None else fb["cpu_temp"]
        gpu_temp = lhm["gpu_temp"] if lhm["gpu_temp"] is not None else fb["gpu_temp"]
        memory_freq = lhm["memory_freq"] if lhm["memory_freq"] is not None else fb["memory_freq"]

        if cpu_temp is not None:
            metrics.cpu_temp = f"{cpu_temp:.1f} °C"
        if gpu_temp is not None:
            metrics.gpu_temp = f"{gpu_temp:.1f} °C"
        if memory_freq is not None:
            metrics.memory_freq = f"{memory_freq:.0f} MHz"
        if metrics.cpu_temp == "N/A" and metrics.gpu_temp == "N/A":
            metrics.temp_hint = "未拿到核心温度(驱动/接口受限)"
        elif metrics.cpu_temp == "N/A":
            metrics.temp_hint = "CPU核心温度接口不可用"

        try:
            now = time.time()
            disk = psutil.disk_io_counters()
            net = psutil.net_io_counters()
            if self._last_disk is not None and self._last_net is not None and self._last_io_ts > 0:
                dt = max(0.1, now - self._last_io_ts)
                disk_bps = ((disk.read_bytes - self._last_disk.read_bytes) + (disk.write_bytes - self._last_disk.write_bytes)) / dt
                read_bps = (disk.read_bytes - self._last_disk.read_bytes) / dt
                write_bps = (disk.write_bytes - self._last_disk.write_bytes) / dt
                up_bps = (net.bytes_sent - self._last_net.bytes_sent) / dt
                down_bps = (net.bytes_recv - self._last_net.bytes_recv) / dt
                metrics.disk_speed = f"{disk_bps / (1024.0 * 1024.0):.1f} MB/s"
                metrics.disk_read = f"{read_bps / (1024.0 * 1024.0):.1f} MB/s"
                metrics.disk_write = f"{write_bps / (1024.0 * 1024.0):.1f} MB/s"
                metrics.network_speed = f"↑ {up_bps / (1024.0 * 1024.0):.1f} MB/s  ↓ {down_bps / (1024.0 * 1024.0):.1f} MB/s"
                metrics.network_up = f"{up_bps / (1024.0 * 1024.0):.1f} MB/s"
                metrics.network_down = f"{down_bps / (1024.0 * 1024.0):.1f} MB/s"
            self._last_disk = disk
            self._last_net = net
            self._last_io_ts = now
        except Exception:
            pass

        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                state = "充电中" if batt.power_plugged else "使用中"
                metrics.battery_status = f"{int(round(batt.percent))}% ({state})"
        except Exception:
            pass

        # Network latency (cached for 2 seconds)
        try:
            now = time.time()
            if now - self._ping_cache_ts >= 2:
                self._ping_cache = self._read_ping()
                self._ping_cache_ts = now
            if self._ping_cache is not None:
                metrics.network_latency = f"{self._ping_cache:.0f} ms"
        except Exception:
            pass

        metrics.source_status = " | ".join([f"{k}:{v}" for k, v in self._last_status.items()])
        return metrics


class FpsService:
    def __init__(self, app_dir: Path, runtime_base_dir: Path, logger: logging.Logger) -> None:
        self._app_dir = app_dir
        self._runtime_base_dir = runtime_base_dir
        self._logger = logger
        self._enabled = False
        self._target_process = ""
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._display_text = "关闭"
        self._low_display_text = "关闭"
        self._last_value_ts = 0.0
        self._csv_headers: list[str] = []
        self._csv_index: Dict[str, int] = {}
        self._active_presentmon_path: Optional[Path] = None
        self._presentmon_available = False
        self._frame_ms_samples = deque(maxlen=600)

    def configure(self, enabled: bool, target_process: str, force_restart: bool = False) -> None:
        target_process = (target_process or "").strip()
        need_restart = False
        with self._lock:
            prev_enabled = self._enabled
            prev_target = self._target_process
            self._enabled = bool(enabled)
            self._target_process = target_process

            if not self._enabled:
                self._display_text = "关闭"
                self._low_display_text = "关闭"
            elif not self._target_process:
                self._display_text = "未选择"
                self._low_display_text = "未选择"
            elif self._resolve_presentmon_path() is None:
                self._display_text = "不可用"
                self._low_display_text = "不可用"
            elif force_restart:
                need_restart = True
            elif (not prev_enabled and self._enabled) or (prev_target != self._target_process):
                need_restart = True

        if not self._enabled or not self._target_process:
            self.stop()
            return
        resolved = self._resolve_presentmon_path()
        if resolved is None:
            self._presentmon_available = False
            self.stop()
            with self._lock:
                self._display_text = "不可用"
                self._low_display_text = "不可用"
            return
        self._presentmon_available = True
        self._active_presentmon_path = resolved
        if need_restart:
            self.restart()

    def _presentmon_candidates(self) -> list[Path]:
        candidates = [
            self._app_dir / "tools" / "PresentMon" / "PresentMon.exe",
            self._runtime_base_dir / "tools" / "PresentMon" / "PresentMon.exe",
        ]
        # Also check system PATH
        system_path = shutil.which("PresentMon")
        if system_path:
            candidates.append(Path(system_path))
        # 去重并保持顺序
        dedup: list[Path] = []
        seen = set()
        for p in candidates:
            s = str(p.resolve()) if p.exists() else str(p)
            if s in seen:
                continue
            seen.add(s)
            dedup.append(p)
        return dedup

    def _resolve_presentmon_path(self) -> Optional[Path]:
        candidates = self._presentmon_candidates()
        for p in candidates:
            self._logger.info("PresentMon path: %s", str(p))
            if p.exists():
                return p
        return None

    def _spawn(self) -> Optional[subprocess.Popen]:
        exe = self._active_presentmon_path or self._resolve_presentmon_path()
        if exe is None or not exe.exists():
            self._logger.warning("PresentMon not found. FPS unavailable.")
            return None

        args = [
            str(exe),
            "--process_name",
            self._target_process,
            "--output_stdout",
            "--no_console_stats",
            "--v1_metrics",
            "--stop_existing_session",
        ]
        try:
            self._logger.info("Starting PresentMon: %s", " ".join(args))
            return subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=0x08000000,
                bufsize=1,
            )
        except Exception as exc:
            self._logger.exception("Failed to start PresentMon: %s", exc)
            return None

    def restart(self) -> None:
        self.stop()
        self._stop_event.clear()
        with self._lock:
            self._csv_headers = []
            self._csv_index = {}
            self._last_value_ts = 0.0
            self._display_text = "--"
            self._low_display_text = "--"
            self._frame_ms_samples.clear()

        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.2)
                    except Exception:
                        proc.kill()
            except Exception:
                pass

    def close(self) -> None:
        self.stop()

    def get_display_text(self) -> str:
        with self._lock:
            if self._enabled and self._target_process and self._presentmon_available:
                if self._last_value_ts > 0 and (time.time() - self._last_value_ts) > 4.0:
                    return "--"
            return self._display_text

    def get_low_display_text(self) -> str:
        with self._lock:
            if self._enabled and self._target_process and self._presentmon_available:
                if self._last_value_ts > 0 and (time.time() - self._last_value_ts) > 4.0:
                    return "--"
            return self._low_display_text

    def _run_worker(self) -> None:
        proc = self._spawn()
        self._proc = proc
        if proc is None or proc.stdout is None:
            with self._lock:
                if self._enabled and self._target_process:
                    self._display_text = "--"
            return

        try:
            if proc.stderr is not None:
                threading.Thread(target=self._read_stderr, args=(proc.stderr,), daemon=True).start()
            while not self._stop_event.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                self._consume_line(line.strip())
        except Exception:
            pass
        finally:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
            with self._lock:
                if self._enabled and self._target_process and self._display_text not in ("不可用", "未选择", "关闭"):
                    self._display_text = "--"
                    self._low_display_text = "--"
            try:
                self._logger.info("PresentMon exited with code: %s", proc.poll())
            except Exception:
                pass

    def _read_stderr(self, stderr_pipe) -> None:
        try:
            while not self._stop_event.is_set():
                line = stderr_pipe.readline()
                if not line:
                    break
                self._logger.warning("PresentMon stderr: %s", line.strip())
        except Exception:
            pass

    def _consume_line(self, line: str) -> None:
        if not line:
            return
        try:
            row = next(csv.reader([line]))
        except Exception:
            return
        if not row:
            return
        if not self._csv_headers:
            lowered = [s.strip().lower() for s in row]
            known_cols = {"application", "processid", "runtime", "msbetweenpresents", "fps", "avgfps"}
            matches = sum(1 for c in lowered if c in known_cols)
            if matches >= 2:
                self._csv_headers = row
                self._csv_index = {name.strip().lower(): idx for idx, name in enumerate(row)}
                return
        fps_value = self._extract_fps_from_row(row)
        if fps_value is None:
            return
        frame_ms = self._extract_frame_ms_from_row(row)
        with self._lock:
            self._display_text = str(int(round(fps_value)))
            if frame_ms is not None and frame_ms > 0:
                self._frame_ms_samples.append(frame_ms)
            elif fps_value > 0:
                self._frame_ms_samples.append(1000.0 / fps_value)
            self._low_display_text = self._calc_low_1_text()
            self._last_value_ts = time.time()

    def _calc_low_1_text(self) -> str:
        if len(self._frame_ms_samples) < 30:
            return "--"
        ordered = sorted(self._frame_ms_samples)
        idx = int(len(ordered) * 0.99) - 1
        idx = max(0, min(len(ordered) - 1, idx))
        worst_1pct_ms = ordered[idx]
        if worst_1pct_ms <= 0:
            return "--"
        return str(int(round(1000.0 / worst_1pct_ms)))

    def _extract_fps_from_row(self, row: list[str]) -> Optional[float]:
        def get_by_name(*names: str) -> Optional[str]:
            for name in names:
                idx = self._csv_index.get(name.lower())
                if idx is not None and idx < len(row):
                    return row[idx]
            return None

        def to_float(raw: Optional[str]) -> Optional[float]:
            if raw is None:
                return None
            try:
                return float(raw.strip())
            except Exception:
                return None

        fps_raw = get_by_name("fps", "avgfps")
        fps = to_float(fps_raw)
        if fps is not None and fps > 0:
            return fps

        ms_raw = get_by_name("msbetweenpresents", "msbetweenpresent", "msuntildisplayed")
        ms_val = to_float(ms_raw)
        if ms_val is not None and ms_val > 0:
            return 1000.0 / ms_val
        return None

    def _extract_frame_ms_from_row(self, row: list[str]) -> Optional[float]:
        def get_by_name(*names: str) -> Optional[str]:
            for name in names:
                idx = self._csv_index.get(name.lower())
                if idx is not None and idx < len(row):
                    return row[idx]
            return None

        def to_float(raw: Optional[str]) -> Optional[float]:
            if raw is None:
                return None
            try:
                return float(raw.strip())
            except Exception:
                return None

        ms_raw = get_by_name("msbetweenpresents", "msbetweenpresent", "msuntildisplayed")
        ms_val = to_float(ms_raw)
        if ms_val is not None and ms_val > 0:
            return ms_val
        return None


class TrayIconService:
    WM_APP = 0x8000
    WM_TRAYICON = WM_APP + 1
    WM_COMMAND = 0x0111
    WM_DESTROY = 0x0002
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONDBLCLK = 0x0203
    WM_LBUTTONUP = 0x0202
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    TPM_RIGHTBUTTON = 0x0002
    MF_STRING = 0x0000
    ID_SHOW = 1001
    ID_EXIT = 1002

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint),
            ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
        ]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint32),
            ("hWnd", ctypes.c_void_p),
            ("uID", ctypes.c_uint32),
            ("uFlags", ctypes.c_uint32),
            ("uCallbackMessage", ctypes.c_uint32),
            ("hIcon", ctypes.c_void_p),
            ("szTip", ctypes.c_wchar * 128),
            ("dwState", ctypes.c_uint32),
            ("dwStateMask", ctypes.c_uint32),
            ("szInfo", ctypes.c_wchar * 256),
            ("uVersion", ctypes.c_uint32),
            ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", ctypes.c_uint32),
            ("guidItem", ctypes.c_ubyte * 16),
            ("hBalloonIcon", ctypes.c_void_p),
        ]

    def __init__(self, app_title: str, icon_path: Optional[Path], on_show, on_exit) -> None:
        self._app_title = app_title
        self._icon_path = icon_path
        self._on_show = on_show
        self._on_exit = on_exit
        self._enabled = False
        self._visible = False
        self._thread: Optional[threading.Thread] = None
        self._hwnd = None
        self._menu = None
        self._nid: Optional[TrayIconService.NOTIFYICONDATAW] = None
        self._running = threading.Event()
        self._ready = threading.Event()

    def start(self) -> bool:
        if self._enabled:
            return True
        try:
            self._running.set()
            self._thread = threading.Thread(target=self._thread_proc, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=1.5)
            self._enabled = bool(self._hwnd)
        except Exception:
            self._enabled = False
        return self._enabled

    def show(self) -> bool:
        if not self._enabled and not self.start():
            return False
        if not self._nid:
            return False
        try:
            ctypes.windll.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(self._nid))
            self._visible = True
            return True
        except Exception:
            return False

    def hide(self) -> None:
        if self._nid is None:
            return
        try:
            ctypes.windll.shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        self._visible = False

    def close(self) -> None:
        self.hide()
        self._running.clear()
        if self._hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._hwnd, self.WM_DESTROY, 0, 0)
            except Exception:
                pass

    def _thread_proc(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        lresult_t = ctypes.c_ssize_t
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "HardwareMonitorTrayClass"

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = lresult_t
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = ctypes.c_ushort
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = ctypes.c_void_p

        wndproc_type = ctypes.WINFUNCTYPE(lresult_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @wndproc_type
        def wndproc(hwnd, msg, wparam, lparam):
            if msg == self.WM_TRAYICON:
                if lparam in (self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK):
                    self._on_show()
                elif lparam == self.WM_RBUTTONUP:
                    self._show_context_menu(hwnd)
                return 0
            if msg == self.WM_COMMAND:
                cmd = int(wparam & 0xFFFF)
                if cmd == self.ID_SHOW:
                    self._on_show()
                elif cmd == self.ID_EXIT:
                    self._on_exit()
                return 0
            if msg == self.WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = wndproc
        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc = ctypes.cast(wndproc, ctypes.c_void_p).value
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(wndclass))
        if atom == 0 and kernel32.GetLastError() not in (0, 1410):
            self._ready.set()
            return

        hwnd = user32.CreateWindowExW(0, class_name, class_name, 0, 0, 0, 0, 0, 0, 0, hinstance, None)
        if not hwnd:
            self._ready.set()
            return
        self._hwnd = hwnd
        self._menu = user32.CreatePopupMenu()
        user32.AppendMenuW(self._menu, self.MF_STRING, self.ID_SHOW, "显示窗口")
        user32.AppendMenuW(self._menu, self.MF_STRING, self.ID_EXIT, "退出")

        nid = TrayIconService.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(TrayIconService.NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAYICON
        nid.szTip = self._app_title
        nid.hIcon = self._load_icon_handle()
        self._nid = nid
        self._ready.set()

        msg = ctypes.wintypes.MSG()
        while self._running.is_set() and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._menu:
            user32.DestroyMenu(self._menu)
        if hwnd:
            user32.DestroyWindow(hwnd)

    def _load_icon_handle(self):
        user32 = ctypes.windll.user32
        LR_LOADFROMFILE = 0x0010
        IMAGE_ICON = 1
        if self._icon_path and self._icon_path.exists():
            try:
                return user32.LoadImageW(None, str(self._icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            except Exception:
                pass
        return user32.LoadIconW(None, 32512)

    def _show_context_menu(self, hwnd):
        user32 = ctypes.windll.user32
        pt = TrayIconService.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(self._menu, self.TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)


class OverlayApp:
    def __init__(self, root: tk.Tk, config: dict) -> None:
        self.root = root
        self.config = config
        self.logger = setup_logger(self._app_dir())
        self.config["autostart"] = self._is_autostart_enabled()
        self.sensor_reader = SensorReader()
        self.fps_service = FpsService(self._app_dir(), self._runtime_base_dir(), self.logger)
        self.labels: Dict[str, tk.Label] = {}
        self.last_metrics = Metrics()
        self.diag_window: Optional[tk.Toplevel] = None
        self.diag_label: Optional[tk.Label] = None
        self.settings_window: Optional[tk.Toplevel] = None
        self.tray_service: Optional[TrayIconService] = None

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._stop_event = threading.Event()
        self._metrics_lock = threading.Lock()
        self._latest_metrics = Metrics()
        self._ui_timer_id: Optional[str] = None

        self._setup_window()
        self._build_ui()
        self._bind_events()
        self._bind_drag_recursive(self.container)
        self._setup_tray()
        self._apply_fps_config(force_restart=True)
        self._start_metrics_thread()
        self._update_metrics_loop()

    def _app_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _runtime_base_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS)  # type: ignore[attr-defined]
        return Path(__file__).resolve().parent

    def _resolve_icon_path(self) -> Optional[Path]:
        candidates = [
            self._app_dir() / "app.ico",
            self._runtime_base_dir() / "app.ico",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def _setup_window(self) -> None:
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.config["always_on_top"]))
        self.root.attributes("-alpha", float(self.config["window_opacity"]))
        self.root.geometry("340x330+80+80")
        self.root.minsize(320, 220)
        self.root.configure(bg=THEMES[self.config["theme"]]["bg"])
        icon_path = self._resolve_icon_path()
        if icon_path is not None:
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _build_ui(self) -> None:
        theme = THEMES[self.config["theme"]]
        scale = float(self.config["font_scale"])
        compact = bool(self.config.get("compact_mode", False))
        show_groups = bool(self.config.get("show_group_titles", True))
        is_en = str(self.config.get("ui_language", "zh")) == "en"

        def ui_text(value: str) -> str:
            if not is_en:
                return value
            if value in ("关闭", "未选择", "不可用"):
                return {"关闭": "Off", "未选择": "Not Selected", "不可用": "Unavailable"}[value]
            return value

        self.container = tk.Frame(self.root, bg=theme["bg"], bd=0, highlightthickness=1, highlightbackground=theme["border"])
        self.container.pack(fill="both", expand=True)

        self.header = tk.Frame(self.container, bg=theme["panel"], height=32)
        self.header.pack(fill="x")

        self.title = tk.Label(self.header, text=APP_NAME, fg=theme["text"], bg=theme["panel"], font=("Microsoft YaHei UI", int(11 * scale), "bold"), anchor="w", padx=10)
        self.title.pack(side="left", fill="y")
        self.title.bind("<Button-3>", self._toggle_diagnostics)

        self.settings_btn = tk.Label(self.header, text="⚙", fg="#c6cfdf", bg=theme["panel"], font=("Segoe UI", int(11 * scale), "bold"), width=3, cursor="hand2")
        self.settings_btn.pack(side="right", fill="y")

        self.min_btn = tk.Label(self.header, text="—", fg="#c6cfdf", bg=theme["panel"], font=("Segoe UI", int(11 * scale), "bold"), width=3, cursor="hand2")
        self.min_btn.pack(side="right", fill="y")

        self.close_btn = tk.Label(self.header, text="✕", fg="#c6cfdf", bg=theme["panel"], font=("Segoe UI", int(11 * scale), "bold"), width=3, cursor="hand2")
        self.close_btn.pack(side="right", fill="y")

        self.body = tk.Frame(self.container, bg=theme["bg"])
        self.body.pack(fill="both", expand=True, padx=10, pady=8)

        visible_rows = []
        order_keys = list(self.config.get("metric_order", []))
        for key in DEFAULT_METRIC_ORDER:
            if key not in order_keys:
                order_keys.append(key)
        for key in order_keys:
            meta = METRIC_MAP.get(key)
            if not meta:
                continue
            group, label, cfg_key = meta
            if key == "fps" and not bool(self.config.get("show_fps", True)):
                continue
            if bool(self.config.get(cfg_key, True)):
                visible_rows.append((group, key, label))
        if not visible_rows:
            visible_rows = [("系统", "cpu_usage", "CPU")]

        last_group = None
        for group, key, text in visible_rows:
            display_group = GROUP_LABEL_EN.get(group, group) if is_en else group
            display_text = METRIC_LABEL_EN.get(key, text) if is_en else text
            if show_groups and group != last_group:
                g = tk.Label(
                    self.body,
                    text=display_group,
                    fg=theme["hint"],
                    bg=theme["bg"],
                    font=("Microsoft YaHei UI", int((8 if compact else 9) * scale), "bold"),
                    anchor="w",
                )
                g.pack(fill="x", pady=((4 if last_group else 0), 1))
                last_group = group

            row = tk.Frame(self.body, bg=theme["bg"])
            row.pack(fill="x", pady=(0 if compact else 1))
            left = tk.Label(
                row,
                text=display_text,
                fg=theme["sub"],
                bg=theme["bg"],
                font=("Microsoft YaHei UI", int((10 if compact else 11) * scale)),
                anchor="w",
            )
            left.pack(side="left")
            initial_text = "关闭" if key == "fps" and not bool(self.config.get("fps_enabled", False)) else "--"
            right = tk.Label(
                row,
                text=ui_text(initial_text),
                fg=theme["text"],
                bg=theme["bg"],
                font=("Segoe UI Semibold", int((10 if compact else 11) * scale)),
                anchor="e",
            )
            right.pack(side="right")
            self.labels[key] = right

        self.hint_label = tk.Label(self.body, text="", fg=theme["hint"], bg=theme["bg"], font=("Microsoft YaHei UI", int(9 * scale)), anchor="w")
        self.hint_label.pack(fill="x", pady=(5, 0))

        self.root.update_idletasks()
        needed_h = self.container.winfo_reqheight() + 2
        needed_w = self.container.winfo_reqwidth() + 2
        self.root.geometry(f"{max(320, needed_w)}x{max(220, needed_h)}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _bind_events(self) -> None:
        self.close_btn.bind("<Button-1>", lambda _: self._on_close_clicked())
        self.close_btn.bind("<Enter>", lambda _: self._set_close_hover(True))
        self.close_btn.bind("<Leave>", lambda _: self._set_close_hover(False))

        self.min_btn.bind("<Button-1>", lambda _: self._hide_to_tray())
        self.min_btn.bind("<Enter>", lambda _: self.min_btn.configure(fg="#8bd3ff"))
        self.min_btn.bind("<Leave>", lambda _: self.min_btn.configure(fg="#c6cfdf"))

        self.settings_btn.bind("<Button-1>", self._toggle_settings)
        self.settings_btn.bind("<Enter>", lambda _: self.settings_btn.configure(fg="#8bd3ff"))
        self.settings_btn.bind("<Leave>", lambda _: self.settings_btn.configure(fg="#c6cfdf"))

        self.root.bind("<Button-3>", self._toggle_diagnostics)

    def _make_draggable(self, widget) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_move)

    def _bind_drag_recursive(self, widget) -> None:
        if widget not in (self.close_btn, self.settings_btn, self.min_btn):
            self._make_draggable(widget)
        for child in widget.winfo_children():
            if child in (self.close_btn, self.settings_btn, self.min_btn):
                continue
            self._bind_drag_recursive(child)

    def _on_drag_start(self, event) -> None:
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root

    def _on_drag_move(self, event) -> None:
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self.root.geometry(f"+{x}+{y}")
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root

    def _set_close_hover(self, is_hover: bool) -> None:
        if is_hover:
            self.close_btn.configure(fg="#ffffff", bg="#ff4d4f")
        else:
            self.close_btn.configure(fg="#c6cfdf", bg=THEMES[self.config["theme"]]["panel"])

    def _start_metrics_thread(self) -> None:
        def worker() -> None:
            while not self._stop_event.is_set():
                metrics = self.sensor_reader.read_metrics()
                with self._metrics_lock:
                    self._latest_metrics = metrics
                self._stop_event.wait(max(0.25, int(self.config["refresh_interval_ms"]) / 1000.0))

        threading.Thread(target=worker, daemon=True).start()

    def _update_metrics_loop(self) -> None:
        with self._metrics_lock:
            metrics = self._latest_metrics
        is_en = str(self.config.get("ui_language", "zh")) == "en"
        metrics.fps = self.fps_service.get_display_text()
        metrics.fps_low_1 = self.fps_service.get_low_display_text()
        target_name = str(self.config.get("fps_target_process", "") or "").strip()
        metrics.target_process = target_name if target_name else "--"
        self.last_metrics = metrics
        for key, label in self.labels.items():
            try:
                val = getattr(metrics, key, "--")
                if val in (None, "", "N/A"):
                    val = "--"
                if is_en and key == "battery_status":
                    val = str(val).replace("充电中", "Charging").replace("使用中", "On Battery")
                if is_en and key in ("fps", "fps_low_1"):
                    val = str(val).replace("关闭", "Off").replace("未选择", "Not Selected").replace("不可用", "Unavailable")
                label.configure(text=str(val))
            except Exception:
                label.configure(text="--")
        hint_text = metrics.temp_hint
        if is_en:
            hint_text = str(hint_text).replace("CPU核心温度接口不可用", "CPU core temperature sensor unavailable")
        self.hint_label.configure(text=hint_text)
        self._refresh_diag_text()
        self._ui_timer_id = self.root.after(300, self._update_metrics_loop)

    @staticmethod
    def _is_admin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _toggle_diagnostics(self, _event=None) -> None:
        if self.diag_window is not None and self.diag_window.winfo_exists():
            self.diag_window.destroy()
            self.diag_window = None
            self.diag_label = None
            return

        self.diag_window = tk.Toplevel(self.root)
        self.diag_window.title("温度诊断")
        self.diag_window.attributes("-topmost", True)
        self.diag_window.geometry("+430+80")
        self.diag_window.configure(bg="#0f1115")
        self.diag_window.resizable(False, False)

        self.diag_label = tk.Label(self.diag_window, text="诊断中...", fg="#d8deea", bg="#0f1115", justify="left", anchor="nw", font=("Microsoft YaHei UI", 10), padx=10, pady=10)
        self.diag_label.pack(fill="both", expand=True)
        self._refresh_diag_text()

    def _refresh_diag_text(self) -> None:
        if self.diag_label is None or self.diag_window is None or not self.diag_window.winfo_exists():
            return
        admin_text = "管理员权限: 是" if self._is_admin() else "管理员权限: 否（可能影响温度读取）"
        lines = [
            admin_text,
            f"CPU 占用: {self.last_metrics.cpu_usage}",
            f"CPU 核心温度: {self.last_metrics.cpu_temp}",
            f"CPU 频率: {self.last_metrics.cpu_freq}",
            f"GPU 占用: {self.last_metrics.gpu_usage}",
            f"GPU 温度: {self.last_metrics.gpu_temp}",
            f"GPU 频率: {self.last_metrics.gpu_clock}",
            f"显存频率: {self.last_metrics.vram_freq}",
            f"显存占用: {self.last_metrics.gpu_memory}",
            f"内存占用: {self.last_metrics.memory_usage}",
            f"内存频率: {self.last_metrics.memory_freq}",
            f"CPU 功耗: {self.last_metrics.cpu_power}",
            f"GPU 功耗: {self.last_metrics.gpu_power}",
            f"磁盘: {self.last_metrics.disk_speed}",
            f"网络: {self.last_metrics.network_speed}",
            f"网络延迟: {self.last_metrics.network_latency}",
            f"SSD温度: {self.last_metrics.ssd_temp}",
            f"电池: {self.last_metrics.battery_status}",
            f"FPS: {self.last_metrics.fps}",
            f"1% Low: {self.last_metrics.fps_low_1}",
            f"目标进程: {self.last_metrics.target_process}",
            "",
            "数据源状态:",
            self.last_metrics.source_status if self.last_metrics.source_status else "尚未采集",
            "",
            "提示: 右键主窗口可关闭此诊断页",
        ]
        self.diag_label.configure(text="\n".join(lines))

    def _toggle_settings(self, _event=None) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
            self.settings_window = None
            return
        try:
            self.settings_window = tk.Toplevel(self.root)
        except Exception:
            self.logger.exception("Create settings window failed")
            return
        current_en = str(self.config.get("ui_language", "zh")) == "en"
        self.settings_window.title("Settings" if current_en else "设置")
        self.settings_window.attributes("-topmost", True)
        self.settings_window.update_idletasks()
        win_w, win_h = 760, 640
        try:
            pos_x = self.root.winfo_x() + (self.root.winfo_width() - win_w) // 2
            pos_y = self.root.winfo_y() + (self.root.winfo_height() - win_h) // 2
        except Exception:
            pos_x, pos_y = 360, 120
        self.settings_window.geometry(f"{win_w}x{win_h}+{max(0, pos_x)}+{max(0, pos_y)}")
        self.settings_window.resizable(False, False)

        frame = tk.Frame(self.settings_window, bg="#151b28", padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg="#151b28", highlightthickness=1, highlightbackground="#2b3550")
        card.pack(fill="both", expand=True)


        state = {
            "theme": self.config["theme"],
            "ui_language": str(self.config.get("ui_language", "zh")),
            "refresh_interval_ms": int(self.config.get("refresh_interval_ms", 1000)),
            "window_opacity": float(self.config["window_opacity"]),
            "always_on_top": bool(self.config["always_on_top"]),
            "minimize_to_tray": bool(self.config.get("minimize_to_tray", True)),
            "autostart": bool(self.config.get("autostart", False)),
            "close_action": str(self.config.get("close_action", "exit")),
            "compact_mode": bool(self.config.get("compact_mode", False)),
            "show_group_titles": bool(self.config.get("show_group_titles", True)),
            "fps_enabled": bool(self.config.get("fps_enabled", False)),
            "fps_target_process": str(self.config.get("fps_target_process", "")),
            "log_level": str(self.config.get("log_level", "INFO")),
            "show_cpu_usage": bool(self.config.get("show_cpu_usage", True)),
            "show_memory_usage": bool(self.config.get("show_memory_usage", True)),
            "show_gpu_usage": bool(self.config.get("show_gpu_usage", True)),
            "show_vram_usage": bool(self.config.get("show_vram_usage", True)),
            "show_cpu_temperature": bool(self.config.get("show_cpu_temperature", True)),
            "show_gpu_temperature": bool(self.config.get("show_gpu_temperature", True)),
            "show_ssd_temperature": bool(self.config.get("show_ssd_temperature", False)),
            "show_cpu_fan": bool(self.config.get("show_cpu_fan", False)),
            "show_gpu_fan": bool(self.config.get("show_gpu_fan", False)),
            "show_cpu_power": bool(self.config.get("show_cpu_power", False)),
            "show_gpu_power": bool(self.config.get("show_gpu_power", False)),
            "show_cpu_freq": bool(self.config.get("show_cpu_freq", True)),
            "show_gpu_freq": bool(self.config.get("show_gpu_freq", True)),
            "show_vram_freq": bool(self.config.get("show_vram_freq", False)),
            "show_memory_freq": bool(self.config.get("show_memory_freq", False)),
            "show_disk_speed": bool(self.config.get("show_disk_speed", True)),
            "show_disk_read": bool(self.config.get("show_disk_read", False)),
            "show_disk_write": bool(self.config.get("show_disk_write", False)),
            "show_network_speed": bool(self.config.get("show_network_speed", True)),
            "show_network_latency": bool(self.config.get("show_network_latency", False)),
            "show_net_up": bool(self.config.get("show_net_up", False)),
            "show_net_down": bool(self.config.get("show_net_down", False)),
            "show_battery": bool(self.config.get("show_battery", False)),
            "show_fps": bool(self.config.get("show_fps", True)),
            "show_fps_low_1": bool(self.config.get("show_fps_low_1", True)),
            "show_target_process": bool(self.config.get("show_target_process", True)),
            "metric_order": list(self.config.get("metric_order", [])),
        }
        lang_is_en = str(state.get("ui_language", "zh")) == "en"
        # Keep settings page high-contrast and stable across Windows themes.
        card_bg = "#ffffff"
        win_bg = "#f5f7fb"
        border = "#d5dcea"
        text_fg = "#0f172a"
        sub_fg = "#334155"
        hint_fg = "#64748b"
        accent = "#2563eb"
        def tr(zh: str, en: str) -> str:
            return en if lang_is_en else zh

        def apply_live(rebuild: bool = True, apply_fps: bool = False, force_fps_restart: bool = False) -> None:
            self.config.update(state)
            self._save_config()
            self.root.attributes("-topmost", bool(self.config["always_on_top"]))
            self.root.attributes("-alpha", float(self.config["window_opacity"]))
            if apply_fps:
                self._apply_fps_config(force_restart=force_fps_restart)
            if rebuild:
                self._rebuild_ui_fast()

        self.settings_window.configure(bg=win_bg)

        frame.configure(bg=win_bg)
        card.configure(bg=card_bg, highlightbackground=border)
        scroll_wrap = tk.Frame(card, bg=card_bg)
        scroll_wrap.pack(fill="both", expand=True, padx=16, pady=(10, 8))
        scroll_canvas = tk.Canvas(scroll_wrap, bg=card_bg, highlightthickness=0, bd=0)
        scroll_bar = tk.Scrollbar(scroll_wrap, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scroll_bar.set)
        scroll_bar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)
        scroll_inner = tk.Frame(scroll_canvas, bg=card_bg)
        scroll_window = scroll_canvas.create_window((0, 0), window=scroll_inner, anchor="nw")

        def _on_inner_configure(_event=None):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def _on_canvas_configure(event):
            scroll_canvas.itemconfigure(scroll_window, width=event.width)

        scroll_inner.bind("<Configure>", _on_inner_configure)
        scroll_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            try:
                scroll_canvas.yview_scroll(int(-event.delta / 120), "units")
            except Exception:
                pass

        scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.settings_window.bind("<Destroy>", lambda _e: scroll_canvas.unbind_all("<MouseWheel>"))

        notebook = ttk.Notebook(scroll_inner)
        notebook.pack(fill="both", expand=True)

        tab_appearance = tk.Frame(notebook, bg=card_bg)
        tab_metrics = tk.Frame(notebook, bg=card_bg)
        tab_window = tk.Frame(notebook, bg=card_bg)
        tab_fps = tk.Frame(notebook, bg=card_bg)
        tab_advanced = tk.Frame(notebook, bg=card_bg)

        notebook.add(tab_appearance, text=tr("外观", "Appearance"))
        notebook.add(tab_metrics, text=tr("监控项", "Metrics"))
        notebook.add(tab_window, text=tr("窗口行为", "Window"))
        notebook.add(tab_fps, text=tr("游戏/FPS", "Game/FPS"))
        notebook.add(tab_advanced, text=tr("高级", "Advanced"))

        def row(parent, title):
            r = tk.Frame(parent, bg=card_bg)
            r.pack(fill="x", pady=6)
            tk.Label(r, text=title, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), width=12, anchor="w").pack(side="left")
            holder = tk.Frame(r, bg=win_bg, highlightthickness=1, highlightbackground=border)
            holder.pack(side="right", fill="x", expand=True)
            return holder

        def segment(parent, key, options, rebuild=True):
            btns=[]
            def refresh():
                for b,v in btns:
                    active = state[key] == v
                    b.configure(bg=accent if active else win_bg, fg=("#ffffff" if active else sub_fg), font=("Segoe UI", 9, "bold" if active else "normal"))
            def choose(v):
                state[key]=v
                refresh()
                if key == "ui_language":
                    apply_live(rebuild=True)
                    if self.settings_window is not None and self.settings_window.winfo_exists():
                        self.settings_window.destroy()
                        self.settings_window = None
                    self._toggle_settings()
                    return
                apply_live(rebuild=rebuild)
            for txt,v in options:
                b=tk.Button(parent,text=txt,relief="flat",bd=0,padx=12,pady=7,cursor="hand2",highlightthickness=0,command=lambda vv=v: choose(vv))
                b.pack(side="left",fill="x",expand=True,padx=1,pady=1)
                btns.append((b,v))
            refresh()

        segment(row(tab_appearance, tr("语言", "Language")), "ui_language", [("中文", "zh"), ("English", "en")], rebuild=True)
        segment(row(tab_appearance, tr("主题", "Theme")), "theme", [(name, name) if not lang_is_en else (THEME_EN_LABEL.get(name, name), name) for name in THEMES.keys()], rebuild=True)
        segment(row(tab_appearance, tr("刷新间隔", "Refresh")), "refresh_interval_ms", [(tr("低功耗 2秒", "Low 2s"), 2000), (tr("标准 1秒", "Standard 1s"), 1000), (tr("高性能 0.5秒", "High 0.5s"), 500)], rebuild=False)

        op = row(tab_appearance, tr("透明度", "Opacity"))
        op_val = tk.Label(op, text="", fg=text_fg, bg=card_bg, font=("Segoe UI", 9, "bold"))
        op_val.pack(side="right", padx=(0, 6))
        op_var = tk.DoubleVar(value=float(state["window_opacity"]) * 100.0)
        op_scale = tk.Scale(op, from_=0, to=100, orient="horizontal", showvalue=False, resolution=1, variable=op_var, bg=win_bg, highlightthickness=0, troughcolor=border, bd=0, length=220)
        op_scale.pack(side="right", fill="x", expand=True, padx=(2, 6), pady=3)
        def on_opacity(_=None):
            v=max(0.0,min(100.0,float(op_var.get())))
            state["window_opacity"]=round(v/100.0,2)
            op_val.configure(text=f"{int(v)}%")
            apply_live(rebuild=False)
        op_scale.configure(command=on_opacity)
        on_opacity()
        tk.Label(tab_appearance, text=tr("刷新越快，占用越高。", "Higher refresh may use more resources."), bg=card_bg, fg=hint_fg, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0), padx=6)

        groups = [
            (tr("CPU", "CPU"), [(tr("占用", "Usage"), "show_cpu_usage"), (tr("温度", "Temp"), "show_cpu_temperature"), (tr("风扇", "Fan"), "show_cpu_fan"), (tr("功耗", "Power"), "show_cpu_power"), (tr("频率", "Clock"), "show_cpu_freq")]),
            (tr("GPU", "GPU"), [(tr("占用", "Usage"), "show_gpu_usage"), (tr("温度", "Temp"), "show_gpu_temperature"), (tr("风扇", "Fan"), "show_gpu_fan"), (tr("功耗", "Power"), "show_gpu_power"), (tr("频率", "Clock"), "show_gpu_freq"), (tr("显存占用", "VRAM Used"), "show_vram_usage"), (tr("显存频率", "VRAM Clock"), "show_vram_freq")]),
            (tr("内存", "Memory"), [(tr("内存占用", "Usage"), "show_memory_usage"), (tr("内存频率", "Clock"), "show_memory_freq")]),
            (tr("磁盘", "Disk"), [(tr("读写速度", "Read+Write"), "show_disk_speed"), (tr("读取", "Read"), "show_disk_read"), (tr("写入", "Write"), "show_disk_write"), (tr("SSD温度", "SSD Temp"), "show_ssd_temperature")]),
            (tr("网络", "Network"), [(tr("网络速度", "Speed"), "show_network_speed"), (tr("上传", "Upload"), "show_net_up"), (tr("下载", "Download"), "show_net_down"), (tr("延迟", "Latency"), "show_network_latency")]),
            (tr("游戏性能", "Game"), [("FPS", "show_fps"), ("1% Low", "show_fps_low_1")]),
            (tr("其他", "Other"), [(tr("电池状态", "Battery"), "show_battery"), (tr("目标进程", "Target Process"), "show_target_process")]),
        ]

        show_vars = {}
        preset = tk.Frame(tab_metrics, bg=card_bg)
        preset.pack(fill="x", pady=(0, 8))

        def apply_preset(name: str):
            keys = {k: False for _g, items in groups for _t, k in items}
            if name == tr("游戏模式", "Game Mode"):
                for k in ("show_fps", "show_fps_low_1", "show_gpu_usage", "show_gpu_temperature", "show_vram_usage"):
                    keys[k] = True
            elif name == tr("简洁模式", "Simple Mode"):
                for k in ("show_cpu_usage", "show_memory_usage", "show_gpu_usage", "show_fps"):
                    keys[k] = True
            elif name == tr("全部显示", "Show All"):
                for k in keys:
                    keys[k] = True
            else:
                for k in keys:
                    keys[k] = bool(DEFAULT_CONFIG.get(k, True))
            for k, v in keys.items():
                state[k] = v
                if k in show_vars:
                    show_vars[k].set(v)
            apply_live(rebuild=True)

        for t in (tr("游戏模式", "Game Mode"), tr("简洁模式", "Simple Mode"), tr("全部显示", "Show All"), tr("恢复默认", "Reset Default")):
            tk.Button(preset, text=t, relief="flat", bd=0, padx=12, pady=7, cursor="hand2", bg=win_bg, fg=sub_fg, highlightthickness=0, font=("Segoe UI", 9), command=lambda n=t: apply_preset(n)).pack(side="left", padx=(0, 6))

        for gname, items in groups:
            box = tk.Frame(tab_metrics, bg=card_bg, highlightthickness=1, highlightbackground=border)
            box.pack(fill="x", pady=(0, 6))
            tk.Label(box, text=gname, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=8, pady=(6, 2))
            inner = tk.Frame(box, bg=card_bg)
            inner.pack(fill="x", padx=8, pady=(0, 6))
            for i, (txt, key) in enumerate(items):
                v = tk.BooleanVar(value=bool(state.get(key, True)))
                show_vars[key] = v
                cb = tk.Checkbutton(inner, text=txt, variable=v, onvalue=True, offvalue=False, bg=card_bg, fg=sub_fg, activebackground=card_bg, selectcolor=card_bg, anchor="w", relief="flat", font=("Segoe UI", 9), command=lambda kk=key, vv=v: (state.__setitem__(kk, bool(vv.get())), apply_live(rebuild=True)))
                cb.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 10), pady=1)

        def make_switch(parent, text, key, rebuild=False):
            r = tk.Frame(parent, bg=card_bg)
            r.pack(fill="x", pady=6)
            tk.Label(r, text=text, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")
            can = tk.Canvas(r, width=44, height=22, highlightthickness=0, bg=card_bg, cursor="hand2")
            can.pack(side="right", padx=(0, 2))
            def draw(v):
                can.delete("all")
                if v:
                    can.create_rectangle(2, 2, 42, 20, fill=accent, outline="", tags="track")
                    can.create_oval(25, 3, 40, 19, fill="#ffffff", outline="", tags="thumb")
                else:
                    can.create_rectangle(2, 2, 42, 20, fill="#ccd5e0", outline="", tags="track")
                    can.create_oval(5, 3, 20, 19, fill="#f8fafc", outline="", tags="thumb")
            def toggle(_=None):
                state[key] = not bool(state[key])
                draw(state[key])
                apply_live(rebuild=rebuild)
            can.bind("<Button-1>", toggle)
            draw(bool(state.get(key, False)))

        make_switch(tab_window, tr("始终置顶", "Always on Top"), "always_on_top", rebuild=False)
        make_switch(tab_window, tr("最小化到通知区域", "Minimize to Tray"), "minimize_to_tray", rebuild=False)
        make_switch(tab_window, tr("开机自启动", "Start with Windows"), "autostart", rebuild=False)
        make_switch(tab_window, tr("紧凑模式", "Compact Mode"), "compact_mode", rebuild=True)
        make_switch(tab_window, tr("显示分组标题", "Show Group Titles"), "show_group_titles", rebuild=True)

        close_row = tk.Frame(tab_window, bg=card_bg)
        close_row.pack(fill="x", pady=6)
        tk.Label(close_row, text=tr("关闭按钮行为", "Close Button"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")
        close_holder = tk.Frame(close_row, bg=win_bg, highlightthickness=1, highlightbackground=border)
        close_holder.pack(side="right", fill="x", expand=True)
        close_var = tk.StringVar(value=tr("最小化到通知区域", "Minimize to Tray") if state.get("close_action", "exit") == "tray" else tr("退出程序", "Exit"))
        close_combo = ttk.Combobox(close_holder, textvariable=close_var, state="readonly", font=("Segoe UI", 9), style="Settings.TCombobox")
        close_combo["values"] = (tr("退出程序", "Exit"), tr("最小化到通知区域", "Minimize to Tray"))
        close_combo.pack(fill="x", padx=4, pady=4)
        close_combo.bind("<<ComboboxSelected>>", lambda _e=None: (state.__setitem__("close_action", "tray" if close_var.get() == tr("最小化到通知区域", "Minimize to Tray") else "exit"), apply_live(rebuild=False)))

        fps_top = tk.Frame(tab_fps, bg=card_bg)
        fps_top.pack(fill="x", pady=(0, 8))
        tk.Label(fps_top, text=tr("FPS 监测", "FPS Monitor"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold")).pack(side="left")
        fps_can = tk.Canvas(fps_top, width=44, height=22, highlightthickness=0, bg=card_bg, cursor="hand2")
        fps_can.pack(side="right", padx=(0, 2))

        fps_state = tk.Label(tab_fps, text="", bg=card_bg, fg=hint_fg, font=("Segoe UI", 9), anchor="w")
        fps_state.pack(fill="x", pady=(0, 6))

        proc_row = tk.Frame(tab_fps, bg=card_bg)
        proc_row.pack(fill="x", pady=(0, 8))
        tk.Label(proc_row, text=tr("目标进程", "Target Process"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), width=12, anchor="w").pack(side="left")
        proc_holder = tk.Frame(proc_row, bg=win_bg, highlightthickness=1, highlightbackground=border)
        proc_holder.pack(side="right", fill="x", expand=True)
        process_var = tk.StringVar(value=state["fps_target_process"])
        process_combo = ttk.Combobox(proc_holder, textvariable=process_var, state="readonly", font=("Segoe UI", 9), style="Settings.TCombobox")
        process_combo.pack(side="left", fill="x", expand=True, padx=(4, 2), pady=4)

        def refresh_process_list() -> None:
            try:
                names = self._list_process_names()
                values = [""] + names
            except Exception:
                names = []
                values = [""]
            process_combo["values"] = values
            if process_var.get() not in values:
                process_var.set("")
                state["fps_target_process"] = ""
            refresh_fps_state(process_names=set(names))

        def refresh_fps_state(process_names=None) -> None:
            if not state["fps_enabled"]:
                fps_state.configure(text=tr("状态：已关闭", "Status: Off"))
                return
            if not state["fps_target_process"]:
                fps_state.configure(text=tr("状态：未选择目标", "Status: No target selected"))
                return
            if process_names is None:
                process_names = set(self._list_process_names())
            if state["fps_target_process"] not in process_names:
                fps_state.configure(text=tr("状态：未检测到进程", "Status: Process not found"))
                return
            current = self.fps_service.get_display_text()
            if current in ("--", "不可用"):
                fps_state.configure(text=tr("状态：正在获取 FPS 数据", "Status: Getting FPS data"))
            else:
                fps_state.configure(text=tr("状态：已检测到进程", "Status: Process detected"))

        def draw_fps_toggle(v):
            fps_can.delete("all")
            if v:
                fps_can.create_rectangle(2, 2, 42, 20, fill=accent, outline="", tags="track")
                fps_can.create_oval(25, 3, 40, 19, fill="#ffffff", outline="", tags="thumb")
            else:
                fps_can.create_rectangle(2, 2, 42, 20, fill="#ccd5e0", outline="", tags="track")
                fps_can.create_oval(5, 3, 20, 19, fill="#f8fafc", outline="", tags="thumb")

        def toggle_fps(_=None):
            state["fps_enabled"] = not bool(state["fps_enabled"])
            draw_fps_toggle(state["fps_enabled"])
            apply_live(rebuild=False, apply_fps=True)
            refresh_fps_state()

        fps_can.bind("<Button-1>", toggle_fps)
        draw_fps_toggle(bool(state.get("fps_enabled", False)))

        process_combo.bind("<<ComboboxSelected>>", lambda _e=None: (state.__setitem__("fps_target_process", process_var.get()), apply_live(rebuild=False, apply_fps=True), refresh_fps_state()))
        tk.Button(proc_holder, text=tr("刷新列表", "Refresh"), relief="flat", bd=0, padx=8, pady=6, cursor="hand2", bg=win_bg, fg=sub_fg, font=("Segoe UI", 9), highlightthickness=0, command=refresh_process_list).pack(side="right", padx=(2, 4), pady=4)
        refresh_process_list()

        # --- 高级设置页内容 ---
        adv_card = tk.Frame(tab_advanced, bg=card_bg, highlightthickness=1, highlightbackground=border)
        adv_card.pack(fill="x", pady=(8, 0))

        # 重置所有设置
        def reset_all():
            if tk.messagebox.askyesno(tr("确认", "Confirm"), tr("确定要重置所有设置吗？\n需要重启生效。", "Reset all settings?\nRestart required.")):
                self.config.update(DEFAULT_CONFIG.copy())
                self._save_config()
                if self.settings_window is not None and self.settings_window.winfo_exists():
                    self.settings_window.destroy()
                    self.settings_window = None
                self._rebuild_ui_fast()

        reset_frame = tk.Frame(adv_card, bg=card_bg)
        reset_frame.pack(fill="x", padx=8, pady=8)
        tk.Label(reset_frame, text=tr("重置设置", "Reset Settings"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10)).pack(side="left")
        tk.Button(reset_frame, text=tr("重置所有设置", "Reset All"), relief="flat", bd=0, padx=12, pady=6, cursor="hand2", bg="#dc3545", fg="#ffffff", font=("Segoe UI", 9, "bold"), highlightthickness=0, command=reset_all).pack(side="right")

        # 打开配置文件目录
        def open_config_dir():
            import os
            try:
                os.startfile(str(self._app_dir()))
            except Exception:
                pass

        dir_frame = tk.Frame(adv_card, bg=card_bg)
        dir_frame.pack(fill="x", padx=8, pady=8)
        tk.Label(dir_frame, text=tr("配置文件", "Config File"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10)).pack(side="left")
        tk.Button(dir_frame, text=tr("打开目录", "Open Folder"), relief="flat", bd=0, padx=12, pady=6, cursor="hand2", bg=win_bg, fg=sub_fg, font=("Segoe UI", 9), highlightthickness=0, command=open_config_dir).pack(side="right")

        # 日志级别
        log_frame = tk.Frame(adv_card, bg=card_bg)
        log_frame.pack(fill="x", padx=8, pady=8)
        tk.Label(log_frame, text=tr("日志级别", "Log Level"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10)).pack(side="left")
        log_var = tk.StringVar(value=str(state.get("log_level", "INFO")))
        log_combo = ttk.Combobox(log_frame, textvariable=log_var, values=["DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", width=12)
        log_combo.pack(side="right")
        log_combo.bind("<<ComboboxSelected>>", lambda _e=None: state.__setitem__("log_level", log_var.get()))

        # 传感器源状态
        src_frame = tk.Frame(adv_card, bg=card_bg)
        src_frame.pack(fill="x", padx=8, pady=8)
        tk.Label(src_frame, text=tr("传感器源", "Sensor Sources"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        lhm_ok = self.sensor_reader._lhm_computer is not None
        smi_ok = shutil.which("nvidia-smi") is not None
        src_text = f"LHM: {'OK' if lhm_ok else 'N/A'}\nnvidia-smi: {'OK' if smi_ok else 'N/A'}"
        tk.Label(src_frame, text=src_text, bg=card_bg, fg=hint_fg, font=("Consolas", 9), justify="left").pack(anchor="w", padx=(16, 0))

        btn_row = tk.Frame(frame, bg=win_bg)
        btn_row.pack(fill="x", pady=(10, 0))

        tk.Button(btn_row, text=tr("取消", "Cancel"), relief="flat", bd=0, padx=0, pady=10, cursor="hand2", bg=win_bg, fg=sub_fg, activebackground=border, activeforeground=text_fg, font=("Segoe UI", 11, "bold"), highlightthickness=0, command=lambda: (self.settings_window.destroy() if self.settings_window and self.settings_window.winfo_exists() else None)).pack(side="left", fill="x", expand=True, padx=(0, 6))

        def save_and_close() -> None:
            state["fps_target_process"] = process_var.get()
            apply_live(rebuild=False, apply_fps=True, force_fps_restart=True)
            self._set_autostart(bool(state.get("autostart", False)))
            # Apply log level
            try:
                log_lv = getattr(logging, str(state.get("log_level", "INFO")), logging.INFO)
                self.logger.setLevel(log_lv)
            except Exception:
                pass
            if self.settings_window is not None and self.settings_window.winfo_exists():
                self.settings_window.destroy()

        tk.Button(btn_row, text=tr("保存", "Save"), relief="flat", bd=0, padx=0, pady=10, cursor="hand2", bg=accent, fg="#ffffff", activebackground=accent, activeforeground="#ffffff", font=("Segoe UI", 11, "bold"), highlightthickness=0, command=save_and_close).pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _rebuild_ui_fast(self) -> None:
        if self._ui_timer_id is not None:
            try:
                self.root.after_cancel(self._ui_timer_id)
            except Exception:
                pass
            self._ui_timer_id = None
        self.root.attributes("-topmost", bool(self.config["always_on_top"]))
        self.root.attributes("-alpha", float(self.config["window_opacity"]))
        self.root.configure(bg=THEMES[self.config["theme"]]["bg"])
        self.container.destroy()
        self.labels = {}
        self._build_ui()
        self._bind_events()
        self._bind_drag_recursive(self.container)
        self._ui_timer_id = self.root.after(300, self._update_metrics_loop)

    def _save_config(self) -> None:
        app_dir = self._app_dir()
        config_path = app_dir / "config.json"
        try:
            tmp_path = config_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(config_path)
        except Exception as exc:
            self.logger.error("Failed to save config: %s", exc)

    def _apply_fps_config(self, force_restart: bool = False) -> None:
        enabled = bool(self.config.get("fps_enabled", False))
        target = str(self.config.get("fps_target_process", "") or "")
        self.logger.info("Apply FPS config: enabled=%s target=%s force_restart=%s", enabled, target, force_restart)
        self.fps_service.configure(enabled=enabled, target_process=target, force_restart=force_restart)

    def _list_process_names(self) -> list[str]:
        names = set()
        for proc in psutil.process_iter(attrs=["name"]):
            try:
                name = (proc.info.get("name") or "").strip()
            except Exception:
                continue
            if not name:
                continue
            if not name.lower().endswith(".exe"):
                continue
            names.add(name)
        return sorted(names, key=str.lower)

    def _setup_tray(self) -> None:
        icon_path = self._resolve_icon_path()
        try:
            self.tray_service = TrayIconService(
                app_title=APP_NAME,
                icon_path=icon_path,
                on_show=lambda: self.root.after(0, self._show_from_tray),
                on_exit=lambda: self.root.after(0, self._close_now),
            )
            if self.tray_service.start():
                self.tray_service.show()
        except Exception:
            self.tray_service = None

    def _hide_to_tray(self) -> None:
        if not bool(self.config.get("minimize_to_tray", True)):
            return
        if self.tray_service is None:
            return
        try:
            shown = self.tray_service.show()
            if shown:
                self.root.withdraw()
        except Exception:
            pass

    def _show_from_tray(self) -> None:
        try:
            self.root.deiconify()
            self.root.attributes("-topmost", bool(self.config["always_on_top"]))
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _on_close_clicked(self) -> None:
        action = str(self.config.get("close_action", "exit"))
        if action == "tray" and bool(self.config.get("minimize_to_tray", True)):
            self._hide_to_tray()
            return
        self._close_now()

    def _set_autostart(self, enabled: bool) -> bool:
        if winreg is None:
            return False
        if self._is_autostart_enabled() == enabled:
            return True
        app_name = "HardwareMonitorMini"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    target = str(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, target)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
            return True
        except Exception:
            return False

    def _is_autostart_enabled(self) -> bool:
        if winreg is None:
            return False
        app_name = "HardwareMonitorMini"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                _val, _typ = winreg.QueryValueEx(key, app_name)
                return True
        except Exception:
            return False

    def _close_now(self) -> None:
        self._stop_event.set()
        if self._ui_timer_id is not None:
            try:
                self.root.after_cancel(self._ui_timer_id)
            except Exception:
                pass
        if self.diag_window is not None and self.diag_window.winfo_exists():
            self.diag_window.destroy()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.fps_service.close()
        if self.tray_service is not None:
            self.tray_service.close()
        self.sensor_reader.close()
        self.root.destroy()


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    _logger = logging.getLogger("hardware_monitor")

    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    config_path = app_dir / "config.json"

    _has_refresh_in_file = False
    if config_path.exists():
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8"))
            _has_refresh_in_file = "refresh_interval_ms" in file_config
            known_keys = set(DEFAULT_CONFIG.keys())
            # Also accept legacy update_interval_ms for migration
            known_keys.add("update_interval_ms")
            filtered = {k: v for k, v in file_config.items() if k in known_keys}
            config.update(filtered)
        except Exception as exc:
            _logger.warning("Failed to load config: %s", exc)

    # Migrate legacy update_interval_ms to refresh_interval_ms
    if "update_interval_ms" in config:
        if not _has_refresh_in_file:
            try:
                config["refresh_interval_ms"] = int(config.pop("update_interval_ms"))
            except Exception:
                config.pop("update_interval_ms", None)
        else:
            config.pop("update_interval_ms", None)

    try:
        config["refresh_interval_ms"] = max(300, int(config["refresh_interval_ms"]))
    except Exception:
        config["refresh_interval_ms"] = DEFAULT_CONFIG["refresh_interval_ms"]

    try:
        opacity = float(config["window_opacity"])
        config["window_opacity"] = min(1.0, max(0.0, opacity))
    except Exception:
        config["window_opacity"] = DEFAULT_CONFIG["window_opacity"]

    try:
        config["always_on_top"] = bool(config["always_on_top"])
    except Exception:
        config["always_on_top"] = DEFAULT_CONFIG["always_on_top"]

    legacy_theme_map = {
        "娣辫壊钃?": "深色蓝",
        "娣辫壊钃�": "深色蓝",
        "鑻规灉娴呰壊": "苹果浅色",
        "鐭冲ⅷ鐏?": "石墨灰",
        "鐭冲ⅷ鐏�": "石墨灰",
    }
    legacy_mode_map = {
        "鏍囧噯": "标准",
        "绮剧畝": "精简",
    }
    raw_theme = str(config.get("theme", "") or "")
    raw_mode = str(config.get("display_mode", "") or "")
    if raw_theme in legacy_theme_map:
        config["theme"] = legacy_theme_map[raw_theme]
    if raw_mode in legacy_mode_map:
        config["display_mode"] = legacy_mode_map[raw_mode]

    if config.get("theme") not in THEMES:
        config["theme"] = DEFAULT_CONFIG["theme"]


    lang = str(config.get("ui_language", DEFAULT_CONFIG["ui_language"])).strip().lower()
    config["ui_language"] = "en" if lang == "en" else "zh"

    try:
        fs = float(config["font_scale"])
        config["font_scale"] = min(1.4, max(0.9, fs))
    except Exception:
        config["font_scale"] = DEFAULT_CONFIG["font_scale"]

    try:
        config["fps_enabled"] = bool(config["fps_enabled"])
    except Exception:
        config["fps_enabled"] = DEFAULT_CONFIG["fps_enabled"]

    try:
        config["fps_target_process"] = str(config.get("fps_target_process", "") or "").strip()
    except Exception:
        config["fps_target_process"] = DEFAULT_CONFIG["fps_target_process"]

    raw_order = config.get("metric_order", [])
    if not isinstance(raw_order, list):
        raw_order = []
    metric_order = [str(x) for x in raw_order if isinstance(x, str) and x in METRIC_MAP]
    for key in DEFAULT_METRIC_ORDER:
        if key not in metric_order:
            metric_order.append(key)
    config["metric_order"] = metric_order

    bool_keys = [
        "minimize_to_tray",
        "autostart",
        "compact_mode",
        "show_group_titles",
        "show_cpu_usage",
        "show_memory_usage",
        "show_gpu_usage",
        "show_vram_usage",
        "show_cpu_temperature",
        "show_gpu_temperature",
        "show_cpu_fan",
        "show_gpu_fan",
        "show_cpu_power",
        "show_gpu_power",
        "show_cpu_freq",
        "show_gpu_freq",
        "show_vram_freq",
        "show_memory_freq",
        "show_ssd_temperature",
        "show_network_latency",
        "show_disk_speed",
        "show_network_speed",
        "show_disk_read",
        "show_disk_write",
        "show_net_up",
        "show_net_down",
        "show_battery",
        "show_fps",
        "show_fps_low_1",
        "show_target_process",
    ]
    for key in bool_keys:
        try:
            config[key] = bool(config.get(key, DEFAULT_CONFIG[key]))
        except Exception:
            config[key] = DEFAULT_CONFIG[key]

    close_action = str(config.get("close_action", DEFAULT_CONFIG["close_action"])).strip().lower()
    config["close_action"] = "tray" if close_action == "tray" else "exit"

    log_level = str(config.get("log_level", "INFO")).strip().upper()
    config["log_level"] = log_level if log_level in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"

    return config


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def ensure_admin() -> None:
    if "--force-admin" not in sys.argv:
        return
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    if is_admin:
        return
    try:
        params = " ".join([f'"{a}"' for a in sys.argv] + ["--elevated"])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit(0)
    except Exception:
        return


def main() -> None:
    ensure_admin()
    enable_dpi_awareness()

    root = tk.Tk()
    OverlayApp(root, load_config())
    root.mainloop()


if __name__ == "__main__":
    main()

