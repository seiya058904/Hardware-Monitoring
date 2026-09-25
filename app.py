import ctypes
import ctypes.wintypes
import csv
import hashlib
import ipaddress
import uuid
import json
import logging
import math
import os
import socket
import shutil
import tempfile
import subprocess
import sys
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import ttk, messagebox
from dataclasses import asdict, dataclass
from collections import deque
from pathlib import Path
from typing import Dict, Optional

from fps_sessions import SessionRegistry
from fps_stream import CaptureStream
from sensor_runtime import SensorRuntime
from dashboard_server import DashboardHTTPServer

import psutil
try:
    import winreg
except Exception:
    winreg = None

try:
    import pythonnet  # type: ignore

    pythonnet.load()
    import clr  # type: ignore
    if not hasattr(clr, "AddReference"):
        clr = None
except Exception:
    clr = None

APP_NAME = "Hardware Monitoring"
AUTOSTART_VALUE_NAME = APP_NAME
LEGACY_AUTOSTART_VALUE_NAME = "HardwareMonitorMini"


def runtime_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(root) / APP_NAME if root else Path.home() / "AppData" / "Local" / APP_NAME


def setup_logger(app_dir: Path) -> logging.Logger:
    logger = logging.getLogger("hardware_monitor")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_path = app_dir / "hardware_monitor.log"
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
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
    "gpu_device_id": None,
    "lan_dashboard_enabled": False,
    "lan_dashboard_port": 8765,
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
    "window_x": None,
    "window_y": None,
}

# Semantic theme tokens. The legacy keys (panel/sub/hint) are kept as aliases so
# existing callers keep working; new UI should prefer the semantic names.
THEMES = {
    "深色蓝": {
        "bg": "#0f1115", "surface": "#151b28", "surface_alt": "#1c2436",
        "border": "#2b3550", "border_hover": "#40507e",
        "text": "#f5f7fa", "text_secondary": "#cfd6e6", "text_muted": "#8190ac",
        "accent": "#4f8cff", "accent_hover": "#6fa3ff", "on_accent": "#ffffff",
        "danger": "#ff5d5d", "control_hover": "#1e2841",
        "status_ok": "#3ecf7a", "status_degraded": "#e8c268", "status_stale": "#8a94ab",
        "panel": "#151b28", "sub": "#cfd6e6", "hint": "#8190ac",
    },
    "苹果浅色": {
        "bg": "#f5f7fb", "surface": "#ffffff", "surface_alt": "#eef2f8",
        "border": "#d5dcea", "border_hover": "#b9c6de",
        "text": "#1f2937", "text_secondary": "#475569", "text_muted": "#64748b",
        "accent": "#2f7cff", "accent_hover": "#1f66e0", "on_accent": "#ffffff",
        "danger": "#dc2626", "control_hover": "#e6ecf6",
        "status_ok": "#16a34a", "status_degraded": "#b45309", "status_stale": "#64748b",
        "panel": "#ffffff", "sub": "#475569", "hint": "#64748b",
    },
    "石墨灰": {
        "bg": "#171717", "surface": "#242424", "surface_alt": "#2d2d2d",
        "border": "#3a3a3a", "border_hover": "#555555",
        "text": "#f1f5f9", "text_secondary": "#d4d4d8", "text_muted": "#a1a1aa",
        "accent": "#6ea8fe", "accent_hover": "#8dbcff", "on_accent": "#ffffff",
        "danger": "#f87171", "control_hover": "#303030",
        "status_ok": "#4ade80", "status_degraded": "#fbbf24", "status_stale": "#a1a1aa",
        "panel": "#242424", "sub": "#d4d4d8", "hint": "#a1a1aa",
    },
    "炫彩红": {
        "bg": "#1a0a0a", "surface": "#2a1010", "surface_alt": "#341717",
        "border": "#4a2020", "border_hover": "#6b3030",
        "text": "#fff0f0", "text_secondary": "#e8c0c0", "text_muted": "#a87070",
        "accent": "#ff4040", "accent_hover": "#ff6b6b", "on_accent": "#ffffff",
        "danger": "#ff6b6b", "control_hover": "#3a1a1a",
        "status_ok": "#4ade80", "status_degraded": "#fbbf24", "status_stale": "#a87070",
        "panel": "#2a1010", "sub": "#e8c0c0", "hint": "#a87070",
    },
    "极光绿": {
        "bg": "#0a1a0f", "surface": "#102a18", "surface_alt": "#16331f",
        "border": "#204a30", "border_hover": "#2e6b45",
        "text": "#f0fff5", "text_secondary": "#c0e8d0", "text_muted": "#70a880",
        "accent": "#40ff80", "accent_hover": "#6bffa0", "on_accent": "#08331a",
        "danger": "#ff6b6b", "control_hover": "#1a3a26",
        "status_ok": "#4ade80", "status_degraded": "#fbbf24", "status_stale": "#70a880",
        "panel": "#102a18", "sub": "#c0e8d0", "hint": "#70a880",
    },
}
MIN_WINDOW_OPACITY = 0.35
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

# Settings keys that only shape the overlay preview and may be applied in memory
# while the dialog is open. Everything else (FPS, LAN, autostart, log level,
# window behaviors with side effects) commits only on Save.
PREVIEW_KEYS = frozenset(
    ["theme", "ui_language", "font_scale", "window_opacity", "compact_mode", "show_group_titles",
     "refresh_interval_ms", "metric_order", "window_x", "window_y"]
    + [key for key in DEFAULT_CONFIG if key.startswith("show_")]
)


def clamp_window_position(x, y, width, height, bounds):
    """Keep a remembered window position reachable on the current monitors."""
    left, top, right, bottom = bounds
    if right <= left or bottom <= top:
        return x, y
    margin = 48
    span_x, span_y = right - left, bottom - top
    # Fully inside when it fits; otherwise keep at least `margin` px visible.
    min_x = left if width <= span_x else left - width + margin
    max_x = right - width if width <= span_x else right - margin
    min_y = top if height <= span_y else top - height + margin
    max_y = bottom - height if height <= span_y else bottom - margin
    nx = min(max(int(x), min_x), max_x)
    ny = min(max(int(y), min_y), max_y)
    return int(nx), int(ny)


def virtual_screen_bounds():
    """Bounding box of every attached monitor in virtual-screen coordinates."""
    try:
        user32 = ctypes.windll.user32
        left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        if width > 0 and height > 0:
            return left, top, left + width, top + height
    except Exception:
        pass
    return 0, 0, 0, 0


def status_text(code, en=False):
    translations = {
        "ok": ("正常", "OK"), "degraded": ("部分设备不可用", "Some devices unavailable"),
        "stale": ("数据已过期", "Data stale"), "unavailable": ("尚无可用数据", "Data unavailable"),
        "stopping": ("正在停止", "Stopping"), "not_sampled": ("尚未采集", "Not sampled"),
        "no_sensor_data": ("尚无可用数据", "No sensor data"),
        "sample_read_failed": ("采样失败", "Sampling failed"), "sample_stale": ("数据已过期", "Data stale"),
        "device_read_failed": ("设备读取失败", "Device read failed"),
        "temperatures_unavailable": ("CPU/GPU 温度接口不可用", "CPU/GPU temperature sensors unavailable"),
        "cpu_temperature_unavailable": ("CPU 温度接口不可用", "CPU temperature sensor unavailable"),
        "gpu_temperature_unavailable": ("GPU 温度接口不可用", "GPU temperature sensor unavailable"),
        "关闭": ("关闭", "Off"), "未选择": ("未选择", "Not selected"), "不可用": ("不可用", "Unavailable"),
        "充电中": ("充电中", "Charging"), "使用中": ("使用中", "On battery"),
    }
    return translations.get(code, (code, code))[int(en)]


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
    battery_percent: Optional[float] = None


def format_metric(key, metrics, en=False):
    value = status_text(str(getattr(metrics, key, "--")), en)
    if key == "battery_status" and metrics.battery_percent is not None:
        value = f"{metrics.battery_percent:.0f}% ({value})"
    return "--" if value in ("", "N/A", "None") else value


PUBLIC_METRIC_FIELDS = ('cpu_usage', 'cpu_freq', 'cpu_temp', 'gpu_usage', 'gpu_temp', 'cpu_fan', 'gpu_fan', 'gpu_clock', 'vram_freq', 'gpu_memory', 'memory_usage', 'memory_freq', 'cpu_power', 'gpu_power', 'disk_speed', 'disk_read', 'disk_write', 'network_speed', 'network_up', 'network_down', 'battery_status', 'fps', 'fps_low_1', 'target_process', 'ssd_temp', 'network_latency', 'temp_hint', 'source_status')

class _DashboardHTTPServer(DashboardHTTPServer):
    pass


class LanDashboardService:
    """Small read-only HTTP server for a LAN dashboard."""

    _PAGE = """<!doctype html><html lang=zh-CN data-theme=dark><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Hardware Monitoring</title><style>*{box-sizing:border-box}:root{--bg:#0b0f17;--card:#141b28;--line:#24304a;--tx:#e8eef8;--dim:#93a4bf;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--accent:#5b9dff}:root[data-theme=light]{--bg:#f2f5fa;--card:#ffffff;--line:#dbe3ef;--tx:#1f2937;--dim:#5b6b82;--ok:#16a34a;--warn:#b45309;--bad:#dc2626;--accent:#2563eb}html,body{margin:0}body{background:var(--bg);color:var(--tx);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}header{display:flex;align-items:center;justify-content:space-between;gap:8px;max-width:860px;margin:0 auto;padding:14px 16px 2px}.brand{font-size:17px;font-weight:650;letter-spacing:.2px}.tools{display:flex;gap:8px}.tool{background:var(--card);border:1px solid var(--line);color:var(--dim);border-radius:8px;padding:5px 11px;font-size:13px;cursor:pointer;line-height:1.3;white-space:nowrap;flex:none}.tool:hover{color:var(--tx)}main{max-width:860px;margin:0 auto;padding:6px 16px 28px}.state{display:flex;align-items:center;gap:8px;padding:10px 2px 12px;font-size:14px;color:var(--dim)}#dot{width:8px;height:8px;border-radius:50%;background:var(--dim);flex:none}.state.ok #dot{background:var(--ok)}.state.warn #dot{background:var(--warn)}.state.bad #dot{background:var(--bad)}.state.ok #stateText{color:var(--tx)}.state.bad #stateText{color:var(--bad)}.age{margin-left:auto;font-size:12.5px;color:var(--dim);font-variant-numeric:tabular-nums}.hero{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 13px;min-width:0}.card .k{font-size:12.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card .v{font-size:19px;margin-top:6px;font-variant-numeric:tabular-nums;word-break:break-word}.hero .v{font-size:23px;font-weight:600}.card.small .v{font-size:16px}.card.dim .v{color:var(--dim);opacity:.8}.group{margin-top:18px}.group h2{font-size:12.5px;color:var(--dim);font-weight:650;margin:0 0 8px;letter-spacing:.5px;text-transform:uppercase}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}@media(max-width:480px){.hero{grid-template-columns:repeat(2,1fr)}.hero .v{font-size:21px}body{font-size:15px}}@media(max-width:340px){.hero{grid-template-columns:1fr 1fr;gap:8px}.card{padding:10px}}</style></head><body><header><div class=brand>Hardware Monitoring</div><div class=tools><button id=langBtn class=tool type=button>EN</button><button id=themeBtn class=tool type=button>&#9788;</button></div></header><main><div id=state class=state><i id=dot></i><span id=stateText>...</span><span id=age class=age></span></div><section class=hero id=hero></section><div id=groups></div></main><script>
const HERO=[['cpu_usage','CPU','CPU'],['gpu_usage','GPU','GPU'],['memory_usage','\u5185\u5b58','RAM'],['gpu_temp','GPU \u6e29\u5ea6','GPU Temp'],['fps','FPS','FPS'],['fps_low_1','1% Low','1% Low']];
const GROUPS=[
 {title:['\u7cfb\u7edf','System'],keys:[['cpu_temp','CPU \u6e29\u5ea6','CPU Temp'],['cpu_freq','CPU \u9891\u7387','CPU Clock'],['cpu_power','CPU \u529f\u8017','CPU Power']]},
 {title:['\u663e\u5361','GPU'],keys:[['gpu_memory','\u663e\u5b58','VRAM'],['gpu_clock','GPU \u9891\u7387','GPU Clock'],['gpu_power','GPU \u529f\u8017','GPU Power']]},
 {title:['\u6027\u80fd','Performance'],keys:[['target_process','\u76ee\u6807\u8fdb\u7a0b','Target Process']]},
 {title:['\u8f93\u5165 / \u8f93\u51fa','I/O'],keys:[['disk_speed','\u78c1\u76d8','Disk'],['network_up','\u7f51\u7edc\u4e0a\u4f20','Upload'],['network_down','\u7f51\u7edc\u4e0b\u8f7d','Download'],['network_latency','\u7f51\u7edc\u5ef6\u8fdf','Latency']]},
 {title:['\u5176\u4ed6','Other'],keys:[['ssd_temp','SSD \u6e29\u5ea6','SSD Temp'],['battery_status','\u7535\u6c60','Battery']]}];
const L={
 zh:{states:{ok:'\u7535\u8111\u8fd0\u884c\u4e2d',degraded:'\u90e8\u5206\u8bbe\u5907\u4e0d\u53ef\u7528',stale:'\u6570\u636e\u5df2\u8fc7\u671f',unavailable:'\u5c1a\u65e0\u53ef\u7528\u6570\u636e',stopping:'\u6b63\u5728\u505c\u6b62',clock_skew:'\u65f6\u949f\u504f\u5dee',invalid:'\u6570\u636e\u534f\u8bae\u5f02\u5e38',offline:'\u8fde\u63a5\u4e2d\u65ad'},fresh:'\u521a\u521a\u66f4\u65b0',last:'\u6700\u540e\u66f4\u65b0',connecting:'\u8fde\u63a5\u4e2d\u2026'},
 en:{states:{ok:'PC running',degraded:'Some devices unavailable',stale:'Data stale',unavailable:'Data unavailable',stopping:'Stopping',clock_skew:'Clock skew',invalid:'Protocol error',offline:'Disconnected'},fresh:'Updated just now',last:'Last update',connecting:'Connecting\u2026'}};
const ALL_KEYS=(function(){const seen=[],add=function(k){if(seen.indexOf(k)<0)seen.push(k)};HERO.forEach(function(k){add(k[0])});GROUPS.forEach(function(g){g.keys.forEach(function(k){add(k[0])})});return seen})();
const heroEl=document.querySelector('#hero'),groupsEl=document.querySelector('#groups'),stateEl=document.querySelector('#state'),stateText=document.querySelector('#stateText'),ageEl=document.querySelector('#age');
let lang=null,theme=null;
function heroCard(k){const c=document.createElement('div');c.className='card';c.id='c-'+k[0];c.innerHTML='<div class=k></div><div class=v>--</div>';return c}
function build(){heroEl.innerHTML='';groupsEl.innerHTML='';HERO.forEach(k=>heroEl.appendChild(heroCard(k)));GROUPS.forEach(g=>{const s=document.createElement('section');s.className='group';const h=document.createElement('h2');s.appendChild(h);const grid=document.createElement('div');grid.className='grid';g.keys.forEach(k=>{const c=document.createElement('div');c.className='card small';c.id='c-'+k[0];if(k[0]==='network_latency'){c.title='Ping 8.8.8.8'}c.innerHTML='<div class=k></div><div class=v>--</div>';grid.appendChild(c)});s.appendChild(grid);groupsEl.appendChild(s)});applyLang()}
function applyLang(){const t=L[lang];document.documentElement.lang=lang==='en'?'en':'zh-CN';document.querySelector('#langBtn').textContent=lang==='en'?'\u4e2d\u6587':'EN';HERO.forEach(k=>{const c=document.getElementById('c-'+k[0]);c.querySelector('.k').textContent=lang==='en'?k[2]:k[1]});const heads=groupsEl.querySelectorAll('.group h2');GROUPS.forEach((g,i)=>{heads[i].textContent=lang==='en'?g.title[1]:g.title[0]});const ks=[].concat(...GROUPS.map(g=>g.keys));ks.forEach(k=>{const c=document.getElementById('c-'+k[0]);if(c){c.querySelector('.k').textContent=lang==='en'?k[2]:k[1]}})}
function applyTheme(v){theme=v;document.documentElement.dataset.theme=v;document.querySelector('#themeBtn').innerHTML=v==='dark'?'&#9788;':'&#9790;';try{localStorage.setItem('hwmon-lan-theme',v)}catch(e){}}
function sampleHealth(d){const keys=['sample_state','sample_age_ms','sample_generation','error_code'];if(keys.some(k=>k in d)){const state=d.sample_state,age=d.sample_age_ms;if(!keys.every(k=>k in d)||!['ok','degraded','stale','unavailable','stopping'].includes(state)||!Number.isInteger(d.sample_generation)||d.sample_generation<0||typeof d.error_code!=='string'||!(age===null||(Number.isInteger(age)&&age>=0))||(['ok','degraded'].includes(state)&&(age===null||d.sample_generation===0)))return 'invalid';return state}let stamp=Date.parse(d.updated_at),age=Date.now()-stamp;if(!Number.isFinite(stamp))return 'invalid';if(age<-5000)return 'clock_skew';return age>5000?'stale':'ok'}
function renderValues(metrics){ALL_KEYS.forEach(key=>{const c=document.getElementById('c-'+key);if(!c)return;const v=c.querySelector('.v');const good=['ok','degraded'].includes(current);const val=good?(metrics[key]??'--'):'--';v.textContent=val;c.classList.toggle('dim',val==='--')})}
let current='unavailable';
async function tick(){try{const r=await fetch('/api/metrics',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!r.ok)throw 0;const d=await r.json(),m=d.metrics;if(d.status!=='ok'||!m||typeof m!=='object'||Array.isArray(m))throw 0;current=sampleHealth(d);const good=['ok','degraded'].includes(current);const t=L[lang];stateText.textContent=t.states[current]||current;stateEl.className='state '+(current==='ok'?'ok':current==='degraded'?'warn':'bad');if(good){const age=d.sample_age_ms;ageEl.textContent=(age!==null&&age<5000)?t.fresh:t.last+' '+(d.updated_at||'--').slice(11,19)}else{ageEl.textContent=''}renderValues(m)}catch(e){current='offline';const t=L[lang];stateText.textContent=t.states.offline;stateEl.className='state bad';ageEl.textContent='';renderValues({})}finally{setTimeout(tick,1000)}}
(function init(){try{lang=localStorage.getItem('hwmon-lan-lang')}catch(e){}if(lang!=='zh'&&lang!=='en'){lang=(navigator.language||'').toLowerCase().indexOf('zh')===0?'zh':'en'}try{theme=localStorage.getItem('hwmon-lan-theme')}catch(e){}if(theme!=='dark'&&theme!=='light'){theme=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'}applyTheme(theme);document.querySelector('#themeBtn').addEventListener('click',()=>applyTheme(theme==='dark'?'light':'dark'));document.querySelector('#langBtn').addEventListener('click',()=>{lang=lang==='en'?'zh':'en';try{localStorage.setItem('hwmon-lan-lang',lang)}catch(e){}applyLang()});build();tick()})();
</script></body></html>"""

    def __init__(self, snapshot_provider, updated_at_provider, logger: Optional[logging.Logger] = None, payload_provider=None) -> None:
        self._payload_provider = payload_provider
        self._snapshot_provider = snapshot_provider
        self._updated_at_provider = updated_at_provider
        self._logger = logger or logging.getLogger("hardware_monitor")
        self._lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port = 0

    @staticmethod
    def _safe_json_value(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {str(key): LanDashboardService._safe_json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [LanDashboardService._safe_json_value(item) for item in value]
        return value

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._server is not None and self._server.active.is_set()

    @property
    def is_alive(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self, port: int = 8765) -> bool:
        with self._lock:
            if self._server is not None:
                return False
            service = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, _format, *_args) -> None:
                    return

                def _send(self, code: int, body: bytes, content_type: str) -> None:
                    if not self.server.active.is_set():
                        return
                    self.send_response(code)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    if self.server.active.is_set():
                        self.wfile.write(body)

                def do_GET(self) -> None:
                    if not self.server.active.is_set():
                        return
                    if len(self.path) > 2048:
                        self._send(414, b"Request URI Too Long", "text/plain; charset=utf-8")
                    elif self.path.split("?", 1)[0] == "/":
                        self._send(200, service._PAGE.encode("utf-8"), "text/html; charset=utf-8")
                    elif self.path.split("?", 1)[0] == "/healthz":
                        self._send(200, b'{"status":"ok"}', "application/json; charset=utf-8")
                    elif self.path.split("?", 1)[0] == "/api/metrics":
                        try:
                            if not self.server.active.is_set():
                                return
                            payload = service._payload_provider() if service._payload_provider else {"status": "ok", "updated_at": service._updated_at_provider(), "metrics": service._snapshot_provider()}
                            body = json.dumps(service._safe_json_value(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
                            self._send(200, body, "application/json; charset=utf-8")
                        except Exception:
                            self._send(503, b'{"status":"unavailable"}', "application/json; charset=utf-8")
                    else:
                        self._send(404, b"Not Found", "text/plain; charset=utf-8")

                def do_POST(self) -> None:
                    self._send(405, b"Method Not Allowed", "text/plain; charset=utf-8")

                do_PUT = do_POST
                do_DELETE = do_POST
                do_PATCH = do_POST

            try:
                server = _DashboardHTTPServer(("0.0.0.0", int(port)), Handler)
                server.daemon_threads = True
            except (OSError, ValueError) as exc:
                self._logger.warning("LAN dashboard did not start on port %s: %s", port, exc)
                return False
            self._server = server
            self.port = server.server_address[1]
            self._thread = threading.Thread(target=server.serve_forever, name="lan-dashboard", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            server, thread = self._server, self._thread
            if server is not None:
                server.revoke()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        clean = (server is None or server.join_clients()) and not (thread and thread.is_alive())
        if clean:
            with self._lock:
                if self._server is server:
                    self._server = None
                    self._thread = None
                    self.port = 0
        else:
            self._logger.error("LAN shutdown incomplete")
        return clean


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
        self._identifier_reader = None
        self.device_outcomes = {}
        self.gpu_devices = []
        self._selected_gpu = None
        self._requested_gpu = None
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
        self._nvidia_smi = shutil.which("nvidia-smi")
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
        self._lhm_computer = None
        self._lhm_hardware = None
        self._lhm_error = ""
        if clr is None:
            self._lhm_error = "pythonnet unavailable"
            return

        candidates = [
            self._runtime_base_dir() / "libs" / "LibreHardwareMonitorLib.dll",
            self._app_dir() / "_internal" / "libs" / "LibreHardwareMonitorLib.dll",
            self._app_dir() / "libs" / "LibreHardwareMonitorLib.dll",
        ]
        dll_path = next((path for path in candidates if path.exists()), candidates[0])
        if not dll_path.exists():
            self._lhm_error = f"Missing DLL: {dll_path}"
            logging.getLogger("hardware_monitor").warning("LibreHardwareMonitor DLL missing: %s", dll_path)
            return

        computer = None
        try:
            clr.AddReference(str(dll_path))
            from LibreHardwareMonitor import Hardware  # type: ignore
            # Keep Identifier inside the CLR. Wrapping its concrete type in pythonnet
            # reflects an unused HidSharp constructor absent from the pinned package.
            clr.AddReference("System.Core")
            from System import Func, String, Array, Type
            from System.Linq.Expressions import Expression, ParameterExpression
            parameter = Expression.Parameter(clr.GetClrType(Hardware.IHardware), "hardware")
            member = Expression.Property(parameter, "Identifier")
            call = Expression.Call(member, member.Type.GetMethod("ToString", Array[Type]([])))
            self._identifier_reader = Expression.Lambda[Func[Hardware.IHardware, String]](call, Array[ParameterExpression]([parameter])).Compile()

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
            if computer is not None:
                try:
                    computer.Close()
                except Exception:
                    pass
            self._lhm_computer = None
            self._lhm_hardware = None
            self._lhm_error = "LHM initialization failed (runtime or driver)"
            logging.getLogger("hardware_monitor").exception("LibreHardwareMonitor initialization failed")

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
            logging.getLogger("hardware_monitor").exception("LHM close failed")
            raise
        finally:
            self._lhm_computer = None
            self._lhm_hardware = None
        try:
            if self._external_lhm_proc is not None and self._external_lhm_proc.poll() is None:
                self._external_lhm_proc.terminate()
        except Exception:
            pass

    def _hardware_identity(self, hardware):
        if self._identifier_reader is not None:
            return str(self._identifier_reader(hardware))
        return str(hardware.Identifier)

    def _walk_sensors(self):
        self.device_outcomes = {}
        self.gpu_devices = []
        if self._lhm_computer is None:
            self.device_outcomes["lhm"] = False
            return []
        self.device_outcomes["lhm"] = True
        entries = []
        def visit(hw, gpu_parent=None):
            try:
                identity = self._hardware_identity(hw)
            except Exception:
                self.device_outcomes["unidentified_device"] = False
                return
            try:
                kind = str(hw.HardwareType)
                if "Gpu" in kind and gpu_parent is None:
                    gpu_parent = identity
                    self.gpu_devices.append((identity, str(hw.Name)))
                hw.Update()
                entries.append((hw, gpu_parent))
                self.device_outcomes[identity] = True
            except Exception:
                self.device_outcomes[identity] = False
            try:
                children = list(hw.SubHardware)
            except Exception:
                self.device_outcomes[identity] = False
                children = []
            for child in children:
                visit(child, gpu_parent)
        try:
            for hw in self._lhm_computer.Hardware:
                visit(hw)
        except Exception:
            self.device_outcomes["lhm"] = False
        identities = sorted(identity for identity, name in self.gpu_devices)
        self._selected_gpu = self._requested_gpu if self._requested_gpu is not None else (identities[0] if identities else None)
        return [hw for hw, gpu in entries if gpu is None or gpu == self._selected_gpu]

    def _safe_sensors(self, hw):
        from types import SimpleNamespace
        identity = self._hardware_identity(hw)
        try:
            sensors = hw.Sensors
            for sensor in sensors:
                try:
                    if sensor.Value is None:
                        continue
                    value = float(sensor.Value)
                    if math.isfinite(value):
                        yield SimpleNamespace(Value=value, Name=str(sensor.Name), SensorType=sensor.SensorType)
                except Exception:
                    self.device_outcomes[identity] = False
        except Exception:
            self.device_outcomes[identity] = False

    @staticmethod
    def _pick_max(current: Optional[float], candidate: float) -> Optional[float]:
        if not math.isfinite(candidate):
            return current
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
            self.device_outcomes = {"lhm": False}
            return values

        sensor_type = self._lhm_hardware.SensorType
        cpu_fallback: Optional[float] = None
        gpu_fallback: Optional[float] = None

        try:
            for hw in self._walk_sensors():
                hw_type_name = str(hw.HardwareType)
                for sensor in self._safe_sensors(hw):
                    if sensor.Value is None:
                        continue

                    s_name = str(sensor.Name).lower()
                    sensor_value = float(sensor.Value)
                    if not math.isfinite(sensor_value):
                        continue

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

    def _read_smi_devices(self):
        if not self._nvidia_smi:
            return {}
        output = self._run_cmd([self._nvidia_smi, "--query-gpu=uuid,name,utilization.gpu,temperature.gpu,clocks.current.graphics,power.draw,memory.used,memory.total", "--format=csv,noheader,nounits"])
        devices = {}
        for row in csv.reader(output.splitlines()):
            if len(row) != 8 or not row[0].strip().startswith("GPU-"):
                continue
            values = {}
            for key, raw in zip(("gpu_usage", "gpu_temp", "gpu_clock", "gpu_power", "gpu_memory_used", "gpu_memory_total"), row[2:]):
                try:
                    value = float(raw.strip())
                    values[key] = value if math.isfinite(value) and value >= 0 else None
                except ValueError:
                    values[key] = None
            devices["nvidia:" + row[0].strip()] = (row[1].strip(), values)
        return devices

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
        if not self._nvidia_smi:
            return None
        out = self._run_cmd([
            self._nvidia_smi,
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
        if not self._nvidia_smi:
            return None
        out = self._run_cmd([
            self._nvidia_smi,
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

    def _read_fallback_values(self, lhm: Dict[str, Optional[float]], config: dict) -> Dict[str, Optional[float]]:
        now = time.time()
        needs_cpu_temp = bool(config.get("show_cpu_temperature", True)) and lhm.get("cpu_temp") is None
        needs_gpu_temp = False  # No verified cross-provider device identity.
        needs_memory_freq = bool(config.get("show_memory_freq", False)) and lhm.get("memory_freq") is None
        needs_vram = False
        self._fallback_cache["gpu_temp"] = None
        self._fallback_cache["gpu_vram"] = None
        needs_fallback = needs_cpu_temp or needs_gpu_temp or needs_memory_freq or needs_vram
        if not needs_fallback:
            return self._fallback_cache
        if now - self._last_fallback_ts < 10:
            return self._fallback_cache

        self._last_fallback_ts = now
        cpu_coretemp = self._read_coretemp_shared_memory() if needs_cpu_temp else None
        cpu_ohm = self._fallback_ohm_wmi_cpu_temp() if needs_cpu_temp and cpu_coretemp is None else None
        cpu_lhm_wmi = self._fallback_lhm_wmi_cpu_temp() if needs_cpu_temp and cpu_coretemp is None and cpu_ohm is None else None
        cpu_wmi = self._fallback_cpu_temp() if needs_cpu_temp and cpu_coretemp is None and cpu_ohm is None and cpu_lhm_wmi is None else None
        gpu_smi = self._fallback_gpu_temp() if needs_gpu_temp else None
        gpu_ohm = self._fallback_ohm_wmi_gpu_temp() if needs_gpu_temp and gpu_smi is None else None
        gpu_lhm_wmi = self._fallback_lhm_wmi_gpu_temp() if needs_gpu_temp and gpu_smi is None and gpu_ohm is None else None
        mem_wmi = self._fallback_memory_freq() if needs_memory_freq else None
        gpu_vram = self._fallback_gpu_vram() if needs_vram else None

        self._fallback_cache = {
            "cpu_coretemp": cpu_coretemp,
            "cpu_temp": cpu_coretemp if cpu_coretemp is not None else (cpu_ohm if cpu_ohm is not None else cpu_lhm_wmi),
            "gpu_temp": gpu_smi if gpu_smi is not None else (gpu_ohm if gpu_ohm is not None else gpu_lhm_wmi),
            "memory_freq": mem_wmi,
            "gpu_vram": gpu_vram,
        }
        acpi_status = "unavailable"
        if cpu_wmi is not None:
            acpi_status = f"{cpu_wmi:.1f}C (ACPI zone, not CPU core)"
        self._last_status = {
            "LHM": "OK" if self._lhm_computer is not None else f"unavailable ({self._lhm_error})",
            "External LHM": "disabled",
            "CoreTemp": "OK" if cpu_coretemp is not None else "unavailable",
            "ACPI": acpi_status,
            "CPU WMI": "OK" if cpu_ohm is not None else "unavailable",
            "CPU-LHM-WMI": "OK" if cpu_lhm_wmi is not None else "unavailable",
            "GPU nvidia-smi": "OK" if gpu_smi is not None else "unavailable",
            "GPU WMI": "OK" if gpu_ohm is not None else "unavailable",
            "GPU-LHM-WMI": "OK" if gpu_lhm_wmi is not None else "unavailable",
            "Memory WMI": "OK" if mem_wmi is not None else "unavailable",
        }
        return self._fallback_cache

    def read_metrics(self, config: Optional[dict] = None) -> Metrics:
        config = config or DEFAULT_CONFIG
        self._requested_gpu = config.get("gpu_device_id")
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
        if not self.gpu_devices:
            devices = self._read_smi_devices()
            self.gpu_devices = [(identity, item[0]) for identity, item in sorted(devices.items())]
            chosen = self._requested_gpu if self._requested_gpu is not None else next(iter(sorted(devices)), None)
            if chosen in devices:
                lhm.update(devices[chosen][1])
                self._selected_gpu = chosen
        fb = self._read_fallback_values(lhm, config)

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
            metrics.temp_hint = "temperatures_unavailable"
        elif metrics.cpu_temp == "N/A":
            metrics.temp_hint = "cpu_temperature_unavailable"
        elif metrics.gpu_temp == "N/A":
            metrics.temp_hint = "gpu_temperature_unavailable"

        now = time.monotonic()
        for category, getter, keys, output_keys in (
            ("disk", lambda: psutil.disk_io_counters(perdisk=True, nowrap=False), ("read_bytes", "write_bytes"), ("disk_read", "disk_write")),
            ("net", lambda: psutil.net_io_counters(pernic=True, nowrap=False), ("bytes_sent", "bytes_recv"), ("network_up", "network_down")),
        ):
            attribute = "_baseline_" + category
            try:
                counters = getter() or {}
                current = {name: tuple(getattr(value, key) for key in keys) for name, value in counters.items()}
                previous = getattr(self, attribute, None)
                setattr(self, attribute, (now, current))
                if not previous or not current or set(previous[1]) != set(current):
                    continue
                dt = now - previous[0]
                if dt <= 0 or dt > max(10, 3 * config["refresh_interval_ms"] / 1000):
                    continue
                deltas = [tuple(value[i] - previous[1][name][i] for i in range(2)) for name, value in current.items()]
                if any(delta < 0 for pair in deltas for delta in pair):
                    continue
                rates = [sum(pair[i] for pair in deltas) / dt / (1024 * 1024) for i in range(2)]
                for key, value in zip(output_keys, rates):
                    setattr(metrics, key, f"{value:.1f} MB/s")
                if category == "disk":
                    metrics.disk_speed = f"{sum(rates):.1f} MB/s"
                else:
                    metrics.network_speed = f"↑ {rates[0]:.1f} MB/s  ↓ {rates[1]:.1f} MB/s"
            except Exception:
                setattr(self, attribute, None)

        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                metrics.battery_status = "充电中" if batt.power_plugged else "使用中"
                metrics.battery_percent = batt.percent
        except Exception:
            pass

        # Network latency (cached for 2 seconds)
        try:
            now = time.time()
            if not bool(config.get("show_network_latency", False)):
                self._ping_cache = None
            elif now - self._ping_cache_ts >= 10:
                self._ping_cache = self._read_ping()
                self._ping_cache_ts = now
            if self._ping_cache is not None:
                metrics.network_latency = f"{self._ping_cache:.0f} ms"
        except Exception:
            pass

        self._last_status["LHM"] = "device_read_failed" if any(not ok for ok in self.device_outcomes.values()) else "ok"
        metrics.source_status = " | ".join([f"{k}:{v}" for k, v in self._last_status.items()])
        if self._lhm_error:
            metrics.source_status += " | " + self._lhm_error
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
        self._generation = 0
        self._session_identity = uuid.uuid4().hex
        self._spawn_context = threading.local()
        self._workers = []
        self._stderr_workers = []
        self._capture = CaptureStream()
        self._capture_identity = None

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
            getattr(self._spawn_context, "target", self._target_process),
            "--output_stdout",
            "--no_console_stats",
            "--v1_metrics",
            "--session_name",
            getattr(self._spawn_context, "session", "HardwareMonitoring-" + self._session_identity + "-" + str(self._generation)),
        ]
        try:
            self._logger.info("Starting PresentMon: %s", " ".join(args))
            registry = SessionRegistry(runtime_data_dir() / "fps-sessions", exe, self._logger)
            registry.reclaim()
            name = args[-1]
            record = registry.register(name)
            proc = subprocess.Popen(
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
            proc._owned_session = (registry, name, record)
            return proc
        except Exception as exc:
            self._logger.exception("Failed to start PresentMon: %s", exc)
            return None

    def restart(self) -> None:
        self.stop()
        with self._lock:
            self._stop_event.clear()
            self._generation += 1
            generation = self._generation
            self._capture = CaptureStream()
            self._capture_identity = None
            self._csv_headers = []
            self._csv_index = {}
            self._last_value_ts = 0.0
            self._display_text = "--"
            self._low_display_text = "--"
            self._frame_ms_samples.clear()

        self._worker_thread = threading.Thread(target=self._run_worker, args=(generation,), daemon=True)
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        self._workers.append(self._worker_thread)
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._generation += 1
            proc = self._proc
            self._proc = None
        if proc is not None:
            self._terminate_process(proc)
        deadline = time.monotonic() + 1.5
        for worker in self._workers + self._stderr_workers:
            if worker is not threading.current_thread():
                worker.join(max(0, deadline - time.monotonic()))

    def _terminate_process(self, proc):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1.2)
        except Exception:
            self._logger.warning("PresentMon process cleanup incomplete", exc_info=True)

    def close(self) -> None:
        self.stop()

    def get_display_text(self) -> str:
        with self._lock:
            if self._enabled and self._target_process and self._presentmon_available:
                if self._last_value_ts > 0 and (time.monotonic() - self._last_value_ts) > 4.0:
                    return "--"
            return self._display_text

    def get_low_display_text(self) -> str:
        with self._lock:
            if self._enabled and self._target_process and self._presentmon_available:
                if self._last_value_ts > 0 and (time.monotonic() - self._last_value_ts) > 4.0:
                    return "--"
            return self._low_display_text

    def _run_worker(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or self._stop_event.is_set():
                return
        with self._lock:
            capture = self._capture
            self._spawn_context.target = self._target_process
            self._spawn_context.session = "HardwareMonitoring-" + self._session_identity + "-" + str(generation)
        proc = self._spawn()
        with self._lock:
            stale = generation != self._generation or self._stop_event.is_set()
            if not stale:
                self._proc = proc
        if stale:
            if proc is not None:
                self._terminate_process(proc)
                self._finish_process(proc)
            return
        if proc is None or proc.stdout is None:
            with self._lock:
                if self._enabled and self._target_process:
                    self._display_text = "--"
            return

        try:
            if proc.stderr is not None:
                stderr_worker = threading.Thread(target=self._read_stderr, args=(proc.stderr, generation), daemon=True)
                self._stderr_workers = [worker for worker in self._stderr_workers if worker.is_alive()]
                self._stderr_workers.append(stderr_worker)
                stderr_worker.start()
            while not self._stop_event.is_set() and generation == self._generation:
                line = proc.stdout.readline()
                if not line:
                    break
                self._consume_line(line.strip(), generation, capture)
        except Exception:
            pass
        finally:
            self._terminate_process(proc)
            self._finish_process(proc)
            with self._lock:
                if generation == self._generation and self._enabled and self._target_process and self._display_text not in ("不可用", "未选择", "关闭"):
                    self._display_text = "--"
                    self._low_display_text = "--"
            try:
                self._logger.info("PresentMon exited with code: %s", proc.poll())
            except Exception:
                pass

    def _finish_process(self, proc):
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None and hasattr(pipe, "close"):
                try:
                    pipe.close()
                except OSError:
                    pass
        owned = getattr(proc, "_owned_session", None)
        if owned:
            registry, name, record = owned
            registry.finish(name, record)

    def _read_stderr(self, stderr_pipe, generation) -> None:
        try:
            last_log = 0.0
            while not self._stop_event.is_set() and generation == self._generation:
                line = stderr_pipe.readline()
                if not line:
                    break
                if generation == self._generation and time.monotonic() - last_log > 10:
                    self._logger.warning("PresentMon stderr: %s", line.strip()[:500])
                    last_log = time.monotonic()
        except Exception:
            pass

    def _consume_line(self, line: str, generation=None, capture=None) -> None:
        with self._lock:
            generation = self._generation if generation is None else generation
            if generation != self._generation or self._stop_event.is_set():
                return
            capture = capture or self._capture
        parsed = capture.consume(line)
        if parsed is None:
            return
        fps, frame_ms, changed = parsed
        with self._lock:
            if generation != self._generation or self._stop_event.is_set() or capture is not self._capture:
                return
            if changed:
                self._frame_ms_samples.clear()
                self._last_value_ts = 0
                self._display_text = self._low_display_text = "--"
            self._capture_identity = capture.selected
            if fps is None:
                return
            self._display_text = str(int(round(fps)))
            self._frame_ms_samples.append(frame_ms)
            self._low_display_text = self._calc_low_1_text()
            self._last_value_ts = time.monotonic()

    def _calc_low_1_text(self) -> str:
        if len(self._frame_ms_samples) < 30:
            return "--"
        ordered = sorted(self._frame_ms_samples)
        idx = int(len(ordered) * 0.99) - 1
        idx = max(0, min(len(ordered) - 1, idx))
        worst_1pct_ms = ordered[idx]
        if not math.isfinite(worst_1pct_ms) or worst_1pct_ms <= 0:
            return "--"
        result = 1000.0 / worst_1pct_ms
        return str(int(round(result))) if math.isfinite(result) else "--"

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
                value = float(raw.strip())
                return value if math.isfinite(value) else None
            except Exception:
                return None

        fps_raw = get_by_name("fps", "avgfps")
        fps = to_float(fps_raw)
        if fps is not None and fps > 0:
            return fps

        ms_raw = get_by_name("msbetweenpresents", "msbetweenpresent", "msuntildisplayed")
        ms_val = to_float(ms_raw)
        if ms_val is not None and ms_val > 0:
            value = 1000.0 / ms_val
            return value if math.isfinite(value) and value > 0 else None
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
                value = float(raw.strip())
                return value if math.isfinite(value) else None
            except Exception:
                return None

        ms_raw = get_by_name("msbetweenpresents", "msbetweenpresent", "msuntildisplayed")
        ms_val = to_float(ms_raw)
        if ms_val is not None and ms_val > 0:
            return ms_val
        return None


def configure_tray_abi():
    pointer, uint, boolean = ctypes.c_void_p, ctypes.c_uint, ctypes.wintypes.BOOL
    user = ctypes.windll.user32
    signatures = {
        "CreatePopupMenu": ([], pointer), "DestroyMenu": ([pointer], boolean),
        "AppendMenuW": ([pointer, uint, ctypes.c_size_t, ctypes.c_wchar_p], boolean),
        "LoadImageW": ([pointer, ctypes.c_wchar_p, uint, ctypes.c_int, ctypes.c_int, uint], pointer),
        "LoadIconW": ([pointer, pointer], pointer), "DestroyIcon": ([pointer], boolean),
        "GetCursorPos": ([pointer], boolean), "SetForegroundWindow": ([pointer], boolean),
        "TrackPopupMenu": ([pointer, uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, pointer, pointer], boolean),
        "PostMessageW": ([pointer, uint, ctypes.c_size_t, ctypes.c_ssize_t], boolean),
        "DestroyWindow": ([pointer], boolean), "PostQuitMessage": ([ctypes.c_int], None),
        "GetMessageW": ([pointer, pointer, uint, uint], ctypes.c_int),
        "TranslateMessage": ([pointer], boolean), "DispatchMessageW": ([pointer], ctypes.c_ssize_t),
        "UnregisterClassW": ([ctypes.c_wchar_p, pointer], boolean),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(user, name)
        function.argtypes, function.restype = arguments, result
    ctypes.windll.kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    ctypes.windll.kernel32.GetModuleHandleW.restype = pointer
    ctypes.windll.kernel32.GetLastError.argtypes = []
    ctypes.windll.kernel32.GetLastError.restype = ctypes.wintypes.DWORD
    ctypes.windll.shell32.Shell_NotifyIconW.argtypes = [ctypes.wintypes.DWORD, pointer]
    ctypes.windll.shell32.Shell_NotifyIconW.restype = boolean


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
    ID_SETTINGS = 1003

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

    def __init__(self, app_title: str, icon_path: Optional[Path], on_show, on_exit, on_settings=None) -> None:
        self._app_title = app_title
        self._icon_path = icon_path
        self._on_show = on_show
        self._on_exit = on_exit
        self._on_settings = on_settings
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
            if self._visible:
                return True
            if not ctypes.windll.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(self._nid)):
                logging.getLogger("hardware_monitor").warning("Tray registration failed")
                return False
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
        configure_tray_abi()
        self._owned_icon = None
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        lresult_t = ctypes.c_ssize_t
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "HardwareMonitorTrayClass-" + str(os.getpid())

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
                elif cmd == self.ID_SETTINGS and self._on_settings is not None:
                    self._on_settings()
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
        if self._on_settings is not None:
            user32.AppendMenuW(self._menu, self.MF_STRING, self.ID_SETTINGS, "设置")
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
        while self._running.is_set() and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._menu:
            user32.DestroyMenu(self._menu)
        if self._owned_icon:
            user32.DestroyIcon(self._owned_icon)
        if hwnd:
            user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(class_name, hinstance)
        self._hwnd = None
        self._nid = None
        self._visible = False

    def _load_icon_handle(self):
        user32 = ctypes.windll.user32
        LR_LOADFROMFILE = 0x0010
        IMAGE_ICON = 1
        if self._icon_path and self._icon_path.exists():
            try:
                self._owned_icon = user32.LoadImageW(None, str(self._icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
                if self._owned_icon:
                    return self._owned_icon
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
        self.logger = setup_logger(runtime_data_dir())
        self.config["autostart"] = self._is_autostart_enabled()
        self.sensor_runtime = SensorRuntime(SensorReader, lambda: dict(self.config), Metrics, self.logger)
        self.fps_service = FpsService(self._app_dir(), self._runtime_base_dir(), self.logger)
        self.labels: Dict[str, tk.Label] = {}
        self.bars: Dict[str, tk.Canvas] = {}
        self.last_metrics = Metrics()
        self._active_theme = THEMES[config["theme"]]
        self._render_signature = None
        self._label_render: Dict[str, tuple] = {}
        self._bar_pct: Dict[str, int] = {}
        self._last_hint = None
        self._status_view = None
        self._last_sample_state = None
        self._settings_original: Optional[dict] = None
        self._settings_working: Optional[dict] = None
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
        self._metrics_updated_at = 0.0
        self.lan_dashboard = LanDashboardService(self._dashboard_snapshot, self._dashboard_updated_at, self.logger, self._dashboard_payload)
        self._ui_timer_id: Optional[str] = None

        self._setup_window()
        self._build_ui()
        self._bind_events()
        self._bind_drag_recursive(self.container)
        self._setup_tray()
        self._apply_fps_config(force_restart=True)
        self._start_metrics_thread()
        self._apply_lan_dashboard_config()
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
        # Every user-visible close path (custom button, WM_DELETE_WINDOW, tray
        # fallback) must honor close_action the same way.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_clicked)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.config["always_on_top"]))
        self.root.attributes("-alpha", float(self.config["window_opacity"]))
        width, height = 340, 330
        pos_x, pos_y = self.config.get("window_x"), self.config.get("window_y")
        if type(pos_x) is int and type(pos_y) is int:
            pos_x, pos_y = clamp_window_position(pos_x, pos_y, width, height, virtual_screen_bounds())
        else:
            pos_x, pos_y = 80, 80
        self.root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        self.root.minsize(320, 220)
        self.root.configure(bg=THEMES[self.config["theme"]]["bg"])
        icon_path = self._resolve_icon_path()
        if icon_path is not None:
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _monitor_workarea(self, x: int, y: int):
        """Work area of the monitor containing the given point, if available."""
        try:
            user32 = ctypes.windll.user32
            point = ctypes.wintypes.POINT(max(0, int(x)), max(0, int(y)))
            monitor = user32.MonitorFromPoint(point, 1)  # MONITOR_DEFAULTTONEAREST
            info = ctypes.wintypes.MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
        except Exception:
            pass
        return None

    def _build_ui(self) -> None:
        theme = THEMES.get(self.config["theme"], THEMES["深色蓝"])
        self._active_theme = theme
        scale = float(self.config["font_scale"])
        dpi = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        compact = bool(self.config.get("compact_mode", False))
        show_groups = bool(self.config.get("show_group_titles", True))
        is_en = str(self.config.get("ui_language", "zh")) == "en"
        self._render_signature = None
        self.labels = {}
        self.bars = {}
        self._label_render = {}

        def ui_text(value: str) -> str:
            if not is_en:
                return value
            if value in ("关闭", "未选择", "不可用"):
                return {"关闭": "Off", "未选择": "Not Selected", "不可用": "Unavailable"}[value]
            return value

        self.container = tk.Frame(self.root, bg=theme["bg"], bd=0, highlightthickness=1, highlightbackground=theme["border"])
        self.container.pack(fill="both", expand=True)

        header_h = int(34 * scale * dpi) if scale > 1.05 else int(34 * dpi)
        self.header = tk.Frame(self.container, bg=theme["surface"], height=header_h)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.title = tk.Label(self.header, text=APP_NAME, fg=theme["text"], bg=theme["surface"], font=("Microsoft YaHei UI", int(11 * scale), "bold"), anchor="w", padx=10)
        self.title.pack(side="left", fill="y")
        self.title.bind("<Button-3>", self._toggle_diagnostics)

        self.status_dot = tk.Canvas(self.header, width=int(12 * dpi), height=int(12 * dpi), bg=theme["surface"], highlightthickness=0)
        self.status_dot.pack(side="left", fill="y", padx=(0, 0))
        self.status_text = tk.Label(self.header, text="", fg=theme["text_muted"], bg=theme["surface"], font=("Microsoft YaHei UI", int(8 * scale)), anchor="w")
        self.status_text.pack(side="left", fill="y", padx=(1, 6))
        self._status_view = None

        button_fg = theme["text_secondary"]
        self.settings_btn = tk.Label(self.header, text="⚙", fg=button_fg, bg=theme["surface"], font=("Segoe UI", int(11 * scale), "bold"), width=3, cursor="hand2")
        self.settings_btn.pack(side="right", fill="y")

        self.min_btn = tk.Label(self.header, text="—", fg=button_fg, bg=theme["surface"], font=("Segoe UI", int(11 * scale), "bold"), width=3, cursor="hand2")
        self.min_btn.pack(side="right", fill="y")

        self.close_btn = tk.Label(self.header, text="✕", fg=button_fg, bg=theme["surface"], font=("Segoe UI", int(11 * scale), "bold"), width=3, cursor="hand2")
        self.close_btn.pack(side="right", fill="y")

        self.body = tk.Frame(self.container, bg=theme["bg"])
        self.body.pack(fill="both", expand=True, padx=10, pady=(6 if compact else 8, 7 if compact else 8))

        # Try normal spacing first; if the content cannot fit the monitor work
        # area, rebuild once with tight spacing before clamping the height.
        available_h = None
        area = self._monitor_workarea(self.root.winfo_x(), self.root.winfo_y())
        if area is not None:
            available_h = area[3] - area[1] - 24
        needed_h = 0
        for tight in (False, True):
            for child in self.body.winfo_children():
                child.destroy()
            self.labels.clear()
            self.bars.clear()
            self._label_render.clear()
            needed_h = self._build_rows(theme, scale, dpi, compact or tight, show_groups, is_en, ui_text, tight)
            if available_h is None or needed_h <= available_h:
                break

        self.hint_label = tk.Label(self.body, text="", fg=theme["text_muted"], bg=theme["bg"], font=("Microsoft YaHei UI", int(9 * scale)), anchor="w")
        self.hint_label.pack(fill="x", pady=(4, 0))
        self._last_hint = None

        self.root.update_idletasks()
        needed_w = self.container.winfo_reqwidth() + 2
        final_h = needed_h
        if area is not None:
            final_h = min(needed_h, area[3] - area[1] - 24)
            final_w = min(needed_w, area[2] - area[0] - 24)
            final_w = max(320, final_w)
        else:
            final_w = max(320, needed_w)
        self.root.geometry(f"{max(320, final_w)}x{max(220, final_h)}+{self.root.winfo_x()}+{self.root.winfo_y()}")

        # Render the last known values immediately so a rebuild never flashes "--".
        self._render_metrics(self.last_metrics, is_en, force=True)
        self._update_status_indicator(self.last_state_hint(), is_en)
        self._update_usage_bars(self.last_metrics)

    def last_state_hint(self) -> str:
        state = getattr(self, "_last_sample_state", None)
        if state is None:
            snapshot_state = ""
            try:
                snapshot_state = self.sensor_runtime.snapshot()["sample_state"]
            except Exception:
                pass
            return snapshot_state or "unavailable"
        return state

    def _build_rows(self, theme, scale, dpi, compact, show_groups, is_en, ui_text, tight) -> int:
        """Build the metric rows; returns the required container height."""
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

        group_gap = (2, 1) if tight else ((3, 1) if compact else (4, 1))
        row_gap = 0 if tight else (0 if compact else 1)
        bar_gap = 0 if tight else 1
        last_group = None
        for group, key, text in visible_rows:
            display_group = GROUP_LABEL_EN.get(group, group) if is_en else group
            display_text = METRIC_LABEL_EN.get(key, text) if is_en else text
            if show_groups and group != last_group:
                g = tk.Label(
                    self.body,
                    text=display_group,
                    fg=theme["text_muted"],
                    bg=theme["bg"],
                    font=("Microsoft YaHei UI", int((8 if compact else 9) * scale), "bold"),
                    anchor="w",
                )
                g.pack(fill="x", pady=group_gap if last_group else (0, 1))
                last_group = group

            row = tk.Frame(self.body, bg=theme["bg"])
            row.pack(fill="x", pady=(0, row_gap))
            left = tk.Label(
                row,
                text=display_text,
                fg=theme["text_secondary"],
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
                font=("Consolas", int((10 if compact else 11) * scale)),
                anchor="e",
            )
            right.pack(side="right")
            self.labels[key] = right

            if key in ("cpu_usage", "gpu_usage"):
                bar = tk.Canvas(self.body, height=max(2, int(2 * dpi)), bg=theme["control_hover"], highlightthickness=0, bd=0)
                bar.pack(fill="x", pady=(bar_gap, 0))
                bar.bind("<Configure>", lambda _event, canvas=bar, metric=key: self._draw_bar(canvas, metric))
                self.bars[key] = bar

        self.root.update_idletasks()
        return self.container.winfo_reqheight() + 2

    def _bind_events(self) -> None:
        self.close_btn.bind("<Button-1>", lambda _: self._on_close_clicked())
        self.close_btn.bind("<Enter>", lambda _: self._set_close_hover(True))
        self.close_btn.bind("<Leave>", lambda _: self._set_close_hover(False))

        self.min_btn.bind("<Button-1>", lambda _: self._minimize_clicked())
        self.min_btn.bind("<Enter>", lambda _: self.min_btn.configure(fg=self._active_theme["text"]))
        self.min_btn.bind("<Leave>", lambda _: self.min_btn.configure(fg=self._active_theme["text_secondary"]))

        self.settings_btn.bind("<Button-1>", self._toggle_settings)
        self.settings_btn.bind("<Enter>", lambda _: self.settings_btn.configure(fg=self._active_theme["text"]))
        self.settings_btn.bind("<Leave>", lambda _: self.settings_btn.configure(fg=self._active_theme["text_secondary"]))

        self.root.bind("<Button-3>", self._toggle_diagnostics)

    def _make_draggable(self, widget) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_move)
        widget.bind("<ButtonRelease-1>", self._on_drag_end)

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

    def _on_drag_end(self, _event) -> None:
        self._persist_window_position()

    def _persist_window_position(self) -> None:
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if getattr(self, "_settings_original", None) is not None:
            # A settings transaction is open: let the position ride along with
            # it instead of writing preview values to disk.
            if self._settings_working is not None:
                self._settings_working["window_x"] = x
                self._settings_working["window_y"] = y
            return
        if self.config.get("window_x") == x and self.config.get("window_y") == y:
            return
        self.config["window_x"] = x
        self.config["window_y"] = y
        self._save_config()

    def _set_close_hover(self, is_hover: bool) -> None:
        theme = self._active_theme
        if is_hover:
            self.close_btn.configure(fg=theme["on_accent"], bg=theme["danger"])
        else:
            self.close_btn.configure(fg=theme["text_secondary"], bg=theme["surface"])

    def _start_metrics_thread(self) -> None:
        self.sensor_runtime.start()

    def _dashboard_payload(self) -> dict:
        snapshot = self.sensor_runtime.snapshot()
        metrics = {key: snapshot["metrics"][key] for key in PUBLIC_METRIC_FIELDS}
        metrics["battery_status"] = format_metric("battery_status", Metrics(**snapshot["metrics"]), self.config.get("ui_language") == "en")
        metrics["source_status"] = snapshot["sample_state"]
        metrics["temp_hint"] = snapshot["error_code"]
        if snapshot["sample_state"] not in ("ok", "degraded"):
            metrics = {key: "--" for key in PUBLIC_METRIC_FIELDS}
            metrics["source_status"] = snapshot["sample_state"]
        metrics["fps"] = self.fps_service.get_display_text()
        metrics["fps_low_1"] = self.fps_service.get_low_display_text()
        return {key: snapshot[key] for key in ("updated_at", "sample_state", "sample_age_ms", "sample_generation", "error_code")} | {"status": "ok", "metrics": metrics}

    def _dashboard_snapshot(self) -> dict:
        return self._dashboard_payload()["metrics"]

    def _dashboard_updated_at(self) -> str:
        return self.sensor_runtime.snapshot()["updated_at"]

    def _render_metrics(self, metrics, is_en, force=False) -> None:
        theme = self._active_theme
        for key, label in self.labels.items():
            text = format_metric(key, metrics, is_en)
            fg = theme["text_muted"] if text == "--" else theme["text"]
            previous = None if force else self._label_render.get(key)
            if previous != (text, fg):
                label.configure(text=text, fg=fg)
                self._label_render[key] = (text, fg)
        hint = status_text(metrics.temp_hint, is_en)
        if force or self._last_hint != hint:
            self.hint_label.configure(text=hint)
            self._last_hint = hint

    STATUS_SHORT = {
        "ok": ("实时", "Live"), "degraded": ("部分不可用", "Degraded"),
        "stale": ("已过期", "Stale"), "unavailable": ("无数据", "No data"),
        "stopping": ("停止中", "Stopping"), "not_sampled": ("启动中", "Starting"),
    }

    def _update_status_indicator(self, state: str, is_en: bool) -> None:
        theme = self._active_theme
        color = theme["status_ok"] if state == "ok" else theme["status_degraded"] if state == "degraded" else theme["status_stale"]
        text = self.STATUS_SHORT.get(state, (state, state))[int(is_en)]
        view = (color, text, theme["surface"])
        if self._status_view == view:
            return
        self._status_view = view
        dpi = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.status_dot.delete("all")
        inset = max(2, int(2 * dpi))
        size = max(4, int(6 * dpi))
        self.status_dot.create_oval(inset, inset, inset + size, inset + size, fill=color, outline="")
        self.status_text.configure(text=text, fg=theme["text_muted"] if state == "ok" else color)

    def _update_usage_bars(self, metrics) -> None:
        for key in ("cpu_usage", "gpu_usage"):
            canvas = self.bars.get(key)
            if canvas is None:
                continue
            raw = str(getattr(metrics, key, "--")).strip().rstrip("%").strip()
            try:
                pct = int(float(raw))
            except ValueError:
                pct = 0
            pct = max(0, min(100, pct))
            if self._bar_pct.get(key) != pct:
                self._bar_pct[key] = pct
                self._draw_bar(canvas, key)

    def _draw_bar(self, canvas, key) -> None:
        canvas.delete("fill")
        pct = self._bar_pct.get(key, 0)
        width = int(canvas.winfo_width())
        if pct > 0 and width > 1:
            canvas.create_rectangle(0, 0, max(2, int(width * pct / 100)), int(canvas.winfo_height()), fill=self._active_theme["accent"], outline="", tags="fill")

    def _update_metrics_loop(self) -> None:
        if self._stop_event.is_set():
            return
        if self._ui_timer_id is not None:
            self.root.after_cancel(self._ui_timer_id)
            self._ui_timer_id = None
        snapshot = self.sensor_runtime.snapshot()
        metrics = Metrics(**snapshot["metrics"])
        state = snapshot["sample_state"]
        if state not in ("ok", "degraded"):
            metrics = Metrics()
            metrics.temp_hint = state
        is_en = str(self.config.get("ui_language", "zh")) == "en"
        metrics.fps = self.fps_service.get_display_text()
        metrics.fps_low_1 = self.fps_service.get_low_display_text()
        target_name = str(self.config.get("fps_target_process", "") or "").strip()
        metrics.target_process = target_name if target_name else "--"
        self.last_metrics = metrics
        self._last_sample_state = state
        # Widgets only need touching when the sample generation, FPS text,
        # freshness state, or language actually changed.
        signature = (snapshot["sample_generation"], state, snapshot["error_code"], metrics.fps, metrics.fps_low_1, target_name, is_en)
        if signature != self._render_signature:
            self._render_signature = signature
            self._render_metrics(metrics, is_en)
            self._update_status_indicator(state, is_en)
            self._update_usage_bars(metrics)
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

        theme = self._active_theme
        self.diag_window = tk.Toplevel(self.root)
        self.diag_window.title("传感器诊断")
        self.diag_window.attributes("-topmost", True)
        self.diag_window.geometry("+430+80")
        self.diag_window.configure(bg=theme["bg"])
        self.diag_window.resizable(False, False)

        self.diag_label = tk.Label(self.diag_window, text="...", fg=theme["text_secondary"], bg=theme["bg"], justify="left", anchor="nw", font=("Microsoft YaHei UI", 10), padx=12, pady=10)
        self.diag_label.pack(fill="both", expand=True)
        self._refresh_diag_text()

    def _refresh_diag_text(self) -> None:
        if self.diag_label is None or self.diag_window is None or not self.diag_window.winfo_exists():
            return
        en = self.config.get("ui_language") == "en"
        theme = self._active_theme

        def section(title):
            return "\n" + ("─" * 30) + "\n" + title + "\n"

        snapshot = self.sensor_runtime.snapshot()
        state = snapshot["sample_state"]
        lines = []
        if en:
            lines.append("Sampling")
            lines.append(f"State: {status_text(state, True)}   Age: {snapshot['sample_age_ms']} ms   Generation: {snapshot['sample_generation']}")
            lines.append("Administrator: " + ("Yes" if self._is_admin() else "No (sensor access may be limited)"))
            lines.append(section("Sensor sources"))
            lines.append(f"FPS stream: {self.fps_service._capture_identity}")
            lines.append(section("GPU devices"))
            lines.append(str(snapshot["gpu_devices"]))
            lines.append(section("Current metrics"))
        else:
            lines.append("采样状态")
            lines.append(f"状态：{status_text(state, False)}   样本年龄：{snapshot['sample_age_ms']} ms   第 {snapshot['sample_generation']} 代")
            lines.append("管理员权限：" + ("是" if self._is_admin() else "否（传感器访问可能受限）"))
            lines.append(section("传感器源"))
            lines.append(f"FPS 捕获流：{self.fps_service._capture_identity}")
            lines.append(section("显卡设备"))
            lines.append(str(snapshot["gpu_devices"]))
            lines.append(section("当前指标"))
        for key in PUBLIC_METRIC_FIELDS:
            if key in ("source_status", "temp_hint"):
                continue
            label = METRIC_LABEL_EN.get(key, key) if en else next((item[2] for item in METRIC_LAYOUT if item[1] == key), key)
            lines.append(f"{label}: {format_metric(key, self.last_metrics, en)}")
        lines.append(section("Diagnostics" if en else "诊断"))
        lines.append(status_text(self.last_metrics.temp_hint, en))
        lines.append(("Error: " if en else "错误：") + status_text(snapshot["error_code"], en))
        lines.append(("Local detail: " if en else "本地详情：") + snapshot["metrics"]["source_status"])
        self.diag_window.title("Sensor diagnostics" if en else "传感器诊断")
        self.diag_label.configure(text="\n".join(lines), fg=theme["text_secondary"])

    def _toggle_settings(self, _event=None) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            # Toggling the gear while the dialog is open counts as Cancel: the
            # pending transaction is dropped instead of silently kept.
            self._cancel_settings()
            return
        self._settings_original = dict(self.config)
        self._settings_working = None
        self._open_settings_dialog()

    def _close_settings_dialog(self) -> None:
        self._settings_original = None
        self._settings_working = None
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None

    def _cancel_settings(self) -> None:
        original = self._settings_original
        if original is None:
            self._close_settings_dialog()
            return
        self.config.clear()
        self.config.update(original)
        self._rebuild_ui_fast()
        pos_x, pos_y = original.get("window_x"), original.get("window_y")
        if type(pos_x) is int and type(pos_y) is int:
            try:
                self.root.geometry(f"+{pos_x}+{pos_y}")
            except Exception:
                pass
        self._close_settings_dialog()

    def _open_settings_dialog(self) -> None:
        if self._settings_working is None:
            self._settings_working = {key: (list(value) if isinstance(value, list) else value) for key, value in self.config.items()}
        working = self._settings_working
        try:
            self.settings_window = tk.Toplevel(self.root)
        except Exception:
            self.logger.exception("Create settings window failed")
            return
        current_en = str(working.get("ui_language", "zh")) == "en"

        def tr(zh: str, en: str) -> str:
            return en if current_en else zh

        # The dialog follows the (previewed) overlay theme instead of a fixed
        # light palette, so both windows always read as one product.
        theme = THEMES.get(working.get("theme"), THEMES["深色蓝"])
        win_bg = theme["bg"]
        card_bg = theme["surface"]
        row_bg = theme["surface_alt"]
        border = theme["border"]
        text_fg = theme["text"]
        sub_fg = theme["text_secondary"]
        hint_fg = theme["text_muted"]
        accent = theme["accent"]
        on_accent = theme["on_accent"]
        danger = theme["danger"]
        control_bg = theme["control_hover"]
        dpi = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        px = lambda value: max(1, int(round(value * dpi)))

        def preview(rebuild: bool = True) -> None:
            # Preview only shapes the overlay in memory; config.json is written
            # exactly once, when Save is pressed.
            self.config.update({key: working[key] for key in PREVIEW_KEYS if key in working})
            if not rebuild:
                self.root.attributes("-alpha", float(working["window_opacity"]))
                return
            self._rebuild_ui_fast()

        def apply_and_reopen(rebuild: bool = True) -> None:
            preview(rebuild=rebuild)
            if self.settings_window is not None and self.settings_window.winfo_exists():
                self.settings_window.destroy()
            self._open_settings_dialog()

        self.settings_window.update_idletasks()
        screen_w = self.settings_window.winfo_screenwidth()
        screen_h = self.settings_window.winfo_screenheight()
        # Scale the dialog with DPI so tab labels and rows keep room on
        # 125-200% scaling instead of being clipped into a fixed 780px frame.
        win_w = max(560, min(int(780 * dpi), int(screen_w * 0.94)))
        win_h = max(430, min(int(660 * dpi), int(screen_h * 0.88)))
        # Center on the monitor the overlay lives on; the overlay itself is far
        # too small to center a wide dialog on.
        area = self._monitor_workarea(self.root.winfo_x(), self.root.winfo_y()) or (0, 0, screen_w, screen_h)
        pos_x = area[0] + max(0, ((area[2] - area[0]) - win_w) // 2)
        pos_y = area[1] + max(0, ((area[3] - area[1]) - win_h) // 2)
        self.settings_window.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.settings_window.minsize(int(min(560 * dpi, win_w)), int(min(430 * dpi, win_h)))
        self.settings_window.resizable(True, True)

        style = ttk.Style(self.settings_window)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Settings.TNotebook", background=card_bg, bordercolor=border, lightcolor=border, darkcolor=border, tabmargins=(0, 0, 0, 0))
        style.configure("Settings.TNotebook.Tab", background=card_bg, foreground=sub_fg, bordercolor=border,
                        lightcolor=border, darkcolor=border, padding=(px(14), px(8)))
        style.map("Settings.TNotebook.Tab",
                  background=[("selected", row_bg)], foreground=[("selected", text_fg)],
                  bordercolor=[("selected", border)], lightcolor=[("selected", row_bg)], darkcolor=[("selected", border)],
                  padding=[("selected", (px(14), px(9)))])
        style.configure("Settings.TCombobox", fieldbackground=row_bg, background=row_bg, foreground=text_fg,
                        arrowcolor=sub_fg, bordercolor=border, lightcolor=row_bg, darkcolor=row_bg)
        style.map("Settings.TCombobox", fieldbackground=[("readonly", row_bg)], foreground=[("readonly", text_fg)])
        style.configure("Settings.Vertical.TScrollbar", background=row_bg, troughcolor=win_bg,
                        bordercolor=win_bg, arrowcolor=sub_fg, lightcolor=row_bg, darkcolor=row_bg)
        self.settings_window.option_add("*TCombobox*Listbox*Background", row_bg)
        self.settings_window.option_add("*TCombobox*Listbox*Foreground", text_fg)
        self.settings_window.option_add("*TCombobox*Listbox*selectBackground", accent)
        self.settings_window.option_add("*TCombobox*Listbox*selectForeground", on_accent)
        self.settings_window.configure(bg=win_bg)

        frame = tk.Frame(self.settings_window, bg=win_bg, padx=px(14), pady=px(12))
        frame.pack(fill="both", expand=True)

        card = tk.Frame(frame, bg=card_bg, highlightthickness=1, highlightbackground=border)
        card.pack(fill="both", expand=True)

        scroll_wrap = tk.Frame(card, bg=card_bg)
        scroll_wrap.pack(fill="both", expand=True, padx=px(16), pady=(px(10), px(8)))
        scroll_canvas = tk.Canvas(scroll_wrap, bg=card_bg, highlightthickness=0, bd=0)
        scroll_bar = ttk.Scrollbar(scroll_wrap, orient="vertical", command=scroll_canvas.yview, style="Settings.Vertical.TScrollbar")
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

        notebook = ttk.Notebook(scroll_inner, style="Settings.TNotebook")
        notebook.pack(fill="both", expand=True)
        notebook.bind("<<NotebookTabChanged>>", lambda _e: scroll_canvas.yview_moveto(0))

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
            r.pack(fill="x", pady=px(6))
            tk.Label(r, text=title, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), width=12, anchor="w").pack(side="left")
            holder = tk.Frame(r, bg=row_bg, highlightthickness=1, highlightbackground=border)
            holder.pack(side="right", fill="x", expand=True)
            return holder

        def section_title(parent, text):
            label = tk.Label(parent, text=text, bg=card_bg, fg=hint_fg, font=("Segoe UI", 8, "bold"), anchor="w")
            label.pack(fill="x")
            return label

        def segment(parent, key, options, rebuild=True):
            btns = []

            def refresh():
                for b, v in btns:
                    active = working[key] == v
                    b.configure(bg=accent if active else row_bg, fg=(on_accent if active else sub_fg),
                                font=("Segoe UI", 9, "bold" if active else "normal"))

            def choose(v):
                working[key] = v
                refresh()
                if key in ("ui_language", "theme"):
                    # Both re-theme the dialog itself: rebuild it in place
                    # while keeping the pending working state.
                    apply_and_reopen(rebuild=True)
                    return
                preview(rebuild=rebuild)

            for txt, v in options:
                b = tk.Button(parent, text=txt, relief="flat", bd=0, padx=px(12), pady=px(7), cursor="hand2",
                              highlightthickness=0, bg=row_bg, fg=sub_fg, activebackground=row_bg, activeforeground=text_fg,
                              font=("Segoe UI", 9), command=lambda vv=v: choose(vv))
                b.pack(side="left", fill="x", expand=True, padx=1, pady=1)
                btns.append((b, v))
            refresh()

        segment(row(tab_appearance, tr("语言", "Language")), "ui_language", [("中文", "zh"), ("English", "en")])
        segment(row(tab_appearance, tr("主题", "Theme")), "theme",
                [(name, name) if not current_en else (THEME_EN_LABEL.get(name, name), name) for name in THEMES.keys()])
        segment(row(tab_appearance, tr("文字大小", "Text Size")), "font_scale",
                [("90%", 0.9), ("100%", 1.0), ("115%", 1.15), ("130%", 1.3), ("140%", 1.4)])
        segment(row(tab_appearance, tr("刷新间隔", "Refresh")), "refresh_interval_ms",
                [(tr("低功耗 2秒", "Low 2s"), 2000), (tr("标准 1秒", "Standard 1s"), 1000), (tr("高性能 0.5秒", "High 0.5s"), 500)], rebuild=False)

        op = row(tab_appearance, tr("透明度", "Opacity"))
        op_val = tk.Label(op, text="", fg=text_fg, bg=row_bg, font=("Segoe UI", 9, "bold"))
        op_val.pack(side="right", padx=(0, px(6)))
        op_var = tk.DoubleVar(value=float(working["window_opacity"]) * 100.0)
        op_scale = tk.Scale(op, from_=int(MIN_WINDOW_OPACITY * 100), to=100, orient="horizontal", showvalue=False,
                            resolution=1, variable=op_var, bg=row_bg, highlightthickness=0, troughcolor=control_bg,
                            bd=0, length=220, activebackground=accent)
        op_scale.pack(side="right", fill="x", expand=True, padx=(2, px(6)), pady=3)

        def on_opacity(_=None):
            v = max(MIN_WINDOW_OPACITY * 100.0, min(100.0, float(op_var.get())))
            working["window_opacity"] = round(v / 100.0, 2)
            op_val.configure(text=f"{int(v)}%")
            preview(rebuild=False)

        op_scale.configure(command=on_opacity)
        on_opacity()
        tk.Label(tab_appearance, text=tr("刷新越快，占用越高。", "Higher refresh may use more resources."),
                 bg=card_bg, fg=hint_fg, font=("Segoe UI", 9)).pack(anchor="w", pady=(px(4), 0), padx=px(6))

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
        section_title(tab_metrics, tr("快捷方案", "Presets")).pack_configure(pady=(px(2), px(4)))
        preset = tk.Frame(tab_metrics, bg=card_bg)
        preset.pack(fill="x", pady=(0, px(4)))

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
                working[k] = v
                if k in show_vars:
                    show_vars[k].set(v)
            preview(rebuild=True)

        for t in (tr("游戏模式", "Game Mode"), tr("简洁模式", "Simple Mode"), tr("全部显示", "Show All"), tr("恢复默认", "Reset Default")):
            tk.Button(preset, text=t, relief="flat", bd=0, padx=px(12), pady=px(7), cursor="hand2", bg=row_bg, fg=sub_fg,
                      activebackground=control_bg, activeforeground=text_fg, highlightthickness=0, font=("Segoe UI", 9),
                      command=lambda n=t: apply_preset(n)).pack(side="left", padx=(0, px(6)))

        section_title(tab_metrics, tr("自定义监控项", "Custom metrics")).pack_configure(pady=(px(10), px(4)))
        for gname, items in groups:
            box = tk.Frame(tab_metrics, bg=card_bg, highlightthickness=1, highlightbackground=border)
            box.pack(fill="x", pady=(0, px(6)))
            tk.Label(box, text=gname, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=px(8), pady=(px(6), px(2)))
            inner = tk.Frame(box, bg=card_bg)
            inner.pack(fill="x", padx=px(8), pady=(0, px(6)))
            for i, (txt, key) in enumerate(items):
                v = tk.BooleanVar(value=bool(working.get(key, True)))
                show_vars[key] = v
                cb = tk.Checkbutton(inner, text=txt, variable=v, onvalue=True, offvalue=False, bg=card_bg, fg=text_fg,
                                    activebackground=card_bg, selectcolor=accent, anchor="w", relief="flat",
                                    font=("Segoe UI", 9), command=lambda kk=key, vv=v: (working.__setitem__(kk, bool(vv.get())), preview(rebuild=True)))
                cb.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, px(10)), pady=1)

        section_title(tab_metrics, tr("监控项顺序", "Metric Order")).pack_configure(pady=(px(10), px(4)))
        order_box = tk.Frame(tab_metrics, bg=card_bg, highlightthickness=1, highlightbackground=border)
        order_box.pack(fill="x", pady=(0, px(6)))
        order_inner = tk.Frame(order_box, bg=card_bg)
        order_inner.pack(fill="both", padx=px(8), pady=px(8))

        def normalized_order():
            keys = [k for k in working.get("metric_order", []) if k in METRIC_MAP]
            for key in DEFAULT_METRIC_ORDER:
                if key not in keys:
                    keys.append(key)
            return keys

        order_list = tk.Listbox(order_inner, bg=row_bg, fg=text_fg, selectbackground=accent, selectforeground=on_accent,
                                relief="flat", highlightthickness=0, height=min(8, len(DEFAULT_METRIC_ORDER)),
                                font=("Segoe UI", 9), activestyle="none", exportselection=False)
        order_list.pack(side="left", fill="both", expand=True)
        order_buttons = tk.Frame(order_inner, bg=card_bg)
        order_buttons.pack(side="right", padx=(px(6), 0))

        def refresh_order_list(keep=None):
            keys = normalized_order()
            order_list.delete(0, "end")
            for key in keys:
                order_list.insert("end", METRIC_LABEL_EN.get(key, key) if current_en else METRIC_MAP[key][1])
            if keep is not None and 0 <= keep < order_list.size():
                order_list.selection_clear(0, "end")
                order_list.selection_set(keep)
                order_list.see(keep)

        def move_order(delta):
            selection = order_list.curselection()
            if not selection:
                return
            keys = normalized_order()
            index = selection[0]
            new_index = index + delta
            if not 0 <= new_index < len(keys):
                return
            keys[index], keys[new_index] = keys[new_index], keys[index]
            working["metric_order"] = keys
            preview(rebuild=True)
            refresh_order_list(keep=new_index)

        for glyph, delta in (("↑", -1), ("↓", 1)):
            tk.Button(order_buttons, text=glyph, relief="flat", bd=0, width=3, pady=px(6), cursor="hand2", bg=row_bg,
                      fg=sub_fg, activebackground=control_bg, activeforeground=text_fg, highlightthickness=0,
                      font=("Segoe UI", 10, "bold"), command=lambda d=delta: move_order(d)).pack(pady=(0, px(4)))
        refresh_order_list()

        def make_switch(parent, text, key, preview_key=False, rebuild=True):
            r = tk.Frame(parent, bg=card_bg)
            r.pack(fill="x", pady=px(6))
            tk.Label(r, text=text, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")
            track_w, track_h = px(44), px(22)
            can = tk.Canvas(r, width=track_w, height=track_h, highlightthickness=0, bg=card_bg, cursor="hand2")
            can.pack(side="right", padx=(0, 2))

            def draw(v):
                can.delete("all")
                if v:
                    can.create_rectangle(px(2), px(2), track_w - px(2), track_h - px(2), fill=accent, outline="", tags="track")
                    can.create_oval(track_w - track_h + px(3), px(3), track_w - px(3), track_h - px(3), fill=on_accent, outline="", tags="thumb")
                else:
                    can.create_rectangle(px(2), px(2), track_w - px(2), track_h - px(2), fill=control_bg, outline="", tags="track")
                    can.create_oval(px(3), px(3), track_h - px(3), track_h - px(3), fill=row_bg, outline="", tags="thumb")

            def toggle(_=None):
                working[key] = not bool(working.get(key, False))
                draw(working[key])
                if preview_key:
                    preview(rebuild=rebuild)

            can.bind("<Button-1>", toggle)
            draw(bool(working.get(key, False)))

        make_switch(tab_window, tr("始终置顶", "Always on Top"), "always_on_top")
        make_switch(tab_window, tr("最小化到通知区域", "Minimize to Tray"), "minimize_to_tray")
        make_switch(tab_window, tr("开机自启动", "Start with Windows"), "autostart")
        make_switch(tab_window, tr("紧凑模式", "Compact Mode"), "compact_mode", preview_key=True)
        make_switch(tab_window, tr("显示分组标题", "Show Group Titles"), "show_group_titles", preview_key=True)

        reset_pos_row = tk.Frame(tab_window, bg=card_bg)
        reset_pos_row.pack(fill="x", pady=px(6))
        tk.Label(reset_pos_row, text=tr("窗口位置", "Window Position"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")

        def reset_window_position():
            working["window_x"] = 80
            working["window_y"] = 80
            preview(rebuild=False)
            self.root.geometry("+80+80")

        tk.Button(reset_pos_row, text=tr("重置窗口位置", "Reset Position"), relief="flat", bd=0, padx=px(12), pady=px(6),
                  cursor="hand2", bg=row_bg, fg=sub_fg, activebackground=control_bg, activeforeground=text_fg,
                  highlightthickness=0, font=("Segoe UI", 9), command=reset_window_position).pack(side="right")

        close_row = tk.Frame(tab_window, bg=card_bg)
        close_row.pack(fill="x", pady=px(6))
        tk.Label(close_row, text=tr("关闭按钮行为", "Close Button"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")
        close_holder = tk.Frame(close_row, bg=row_bg, highlightthickness=1, highlightbackground=border)
        close_holder.pack(side="right", fill="x", expand=True)
        close_var = tk.StringVar(value=tr("最小化到通知区域", "Minimize to Tray") if working.get("close_action", "exit") == "tray" else tr("退出程序", "Exit"))
        close_combo = ttk.Combobox(close_holder, textvariable=close_var, state="readonly", font=("Segoe UI", 9), style="Settings.TCombobox")
        close_combo["values"] = (tr("退出程序", "Exit"), tr("最小化到通知区域", "Minimize to Tray"))
        close_combo.pack(fill="x", padx=px(4), pady=px(4))
        close_combo.bind("<<ComboboxSelected>>", lambda _e=None: working.__setitem__("close_action", "tray" if close_var.get() == tr("最小化到通知区域", "Minimize to Tray") else "exit"))

        fps_top = tk.Frame(tab_fps, bg=card_bg)
        fps_top.pack(fill="x", pady=(0, px(8)))
        tk.Label(fps_top, text=tr("FPS 监测", "FPS Monitor"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold")).pack(side="left")
        fps_can = tk.Canvas(fps_top, width=px(44), height=px(22), highlightthickness=0, bg=card_bg, cursor="hand2")
        fps_can.pack(side="right", padx=(0, 2))

        fps_state = tk.Label(tab_fps, text="", bg=card_bg, fg=hint_fg, font=("Segoe UI", 9), anchor="w")
        fps_state.pack(fill="x", pady=(0, px(6)))

        proc_row = tk.Frame(tab_fps, bg=card_bg)
        proc_row.pack(fill="x", pady=(0, px(8)))
        tk.Label(proc_row, text=tr("目标进程", "Target Process"), bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), width=12, anchor="w").pack(side="left")
        proc_holder = tk.Frame(proc_row, bg=row_bg, highlightthickness=1, highlightbackground=border)
        proc_holder.pack(side="right", fill="x", expand=True)
        process_var = tk.StringVar(value=working["fps_target_process"])
        process_combo = ttk.Combobox(proc_holder, textvariable=process_var, state="readonly", font=("Segoe UI", 9), style="Settings.TCombobox")
        process_combo.pack(side="left", fill="x", expand=True, padx=(px(4), 2), pady=px(4))

        presentmon_checked: dict = {}

        def presentmon_ok() -> bool:
            if "ok" not in presentmon_checked:
                presentmon_checked["ok"] = bool(self.fps_service._presentmon_available) or self.fps_service._resolve_presentmon_path() is not None
            return presentmon_checked["ok"]

        def refresh_fps_state(process_names=None) -> None:
            if not working["fps_enabled"]:
                fps_state.configure(text=tr("状态：已关闭", "Status: Off"))
                return
            if not working["fps_target_process"]:
                fps_state.configure(text=tr("状态：未选择目标", "Status: No target selected"))
                return
            if not presentmon_ok():
                fps_state.configure(text=tr("状态：PresentMon 不可用", "Status: PresentMon unavailable"))
                return
            if process_names is None:
                process_names = set(self._list_process_names())
            if working["fps_target_process"] not in process_names:
                fps_state.configure(text=tr("状态：等待目标进程启动", "Status: Waiting for the target process"))
                return
            current = self.fps_service.get_display_text()
            if current in ("--", "不可用"):
                fps_state.configure(text=tr("状态：正在捕获帧数据", "Status: Capturing frames"))
            else:
                fps_state.configure(text=tr("状态：捕获中", "Status: Capturing"))

        def refresh_process_list() -> None:
            try:
                names = self._list_process_names()
                values = [""] + names
            except Exception:
                names = []
                values = [""]
            if process_var.get() and process_var.get() not in values:
                values.append(process_var.get())
            process_combo["values"] = values
            refresh_fps_state(process_names=set(names))

        def draw_fps_toggle(v):
            fps_can.delete("all")
            if v:
                fps_can.create_rectangle(px(2), px(2), px(42), px(20), fill=accent, outline="", tags="track")
                fps_can.create_oval(px(25), px(3), px(40), px(19), fill=on_accent, outline="", tags="thumb")
            else:
                fps_can.create_rectangle(px(2), px(2), px(42), px(20), fill=control_bg, outline="", tags="track")
                fps_can.create_oval(px(5), px(3), px(20), px(19), fill=row_bg, outline="", tags="thumb")

        def toggle_fps(_=None):
            working["fps_enabled"] = not bool(working["fps_enabled"])
            draw_fps_toggle(working["fps_enabled"])
            refresh_fps_state()

        fps_can.bind("<Button-1>", toggle_fps)
        draw_fps_toggle(bool(working.get("fps_enabled", False)))

        process_combo.bind("<<ComboboxSelected>>", lambda _e=None: (working.__setitem__("fps_target_process", process_var.get()), refresh_fps_state()))
        tk.Button(proc_holder, text=tr("刷新列表", "Refresh"), relief="flat", bd=0, padx=px(8), pady=px(6), cursor="hand2",
                  bg=row_bg, fg=sub_fg, activebackground=control_bg, activeforeground=text_fg, font=("Segoe UI", 9),
                  highlightthickness=0, command=refresh_process_list).pack(side="right", padx=(2, px(4)), pady=px(4))
        refresh_process_list()

        def adv_section(title):
            box = tk.Frame(tab_advanced, bg=card_bg, highlightthickness=1, highlightbackground=border)
            box.pack(fill="x", pady=(0, px(8)))
            tk.Label(box, text=title, bg=card_bg, fg=text_fg, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=px(10), pady=(px(8), px(2)))
            inner = tk.Frame(box, bg=card_bg)
            inner.pack(fill="x", padx=px(10), pady=(0, px(10)))
            return inner

        lan_section = adv_section(tr("局域网仪表盘", "LAN Dashboard"))
        dashboard_enabled_var = tk.BooleanVar(value=working["lan_dashboard_enabled"])
        tk.Checkbutton(lan_section, text=tr("启用局域网仪表盘", "Enable LAN Dashboard"), variable=dashboard_enabled_var,
                       bg=card_bg, fg=text_fg, activebackground=card_bg, selectcolor=accent, font=("Segoe UI", 9),
                       command=lambda: working.__setitem__("lan_dashboard_enabled", bool(dashboard_enabled_var.get()))).grid(row=0, column=0, sticky="w")
        dashboard_port_var = tk.StringVar(value=str(working["lan_dashboard_port"]))
        tk.Label(lan_section, text=tr("端口", "Port"), bg=card_bg, fg=sub_fg, font=("Segoe UI", 9)).grid(row=0, column=1, sticky="e", padx=(px(12), px(4)))
        tk.Entry(lan_section, textvariable=dashboard_port_var, width=7, bg=row_bg, fg=text_fg, insertbackground=text_fg,
                 relief="solid", bd=1, highlightthickness=0).grid(row=0, column=2, sticky="w")
        dashboard_address = self._lan_dashboard_address(working["lan_dashboard_port"])
        tk.Label(lan_section, text=tr(f"保存后生效。当前访问地址：{dashboard_address}\n手机须与电脑处于同一 Wi-Fi。",
                                     f"Applies after Save. Current address: {dashboard_address}\nPhone and PC must use the same Wi-Fi."),
                 bg=card_bg, fg=hint_fg, font=("Segoe UI", 8), justify="left", wraplength=620).grid(row=1, column=0, columnspan=3, sticky="w", pady=(px(5), 0))

        diag_section = adv_section(tr("诊断", "Diagnostics"))
        tk.Label(diag_section, text=tr("温度、功耗等显示 “—” 时，可在这里查看传感器原因。", "If temperature or power shows “—”, check the sensor reasons here."),
                 bg=card_bg, fg=hint_fg, font=("Segoe UI", 8)).pack(side="left")
        tk.Button(diag_section, text=tr("打开传感器诊断", "Open Sensor Diagnostics"), relief="flat", bd=0, padx=px(12), pady=px(6),
                  cursor="hand2", bg=row_bg, fg=sub_fg, activebackground=control_bg, activeforeground=text_fg,
                  highlightthickness=0, font=("Segoe UI", 9), command=self._toggle_diagnostics).pack(side="right")

        gpu_section = adv_section(tr("监控显卡", "Monitored GPU"))
        devices = self.sensor_runtime.snapshot()["gpu_devices"]
        selected_gpu = working.get("gpu_device_id")
        if selected_gpu is not None and selected_gpu not in [item[0] for item in devices]:
            devices.append((selected_gpu, tr("离线设备", "Offline device")))
        gpu_ids = [None] + [item[0] for item in devices]
        gpu_labels = [tr("自动（按设备标识）", "Automatic (device ID)")] + [name + " [" + identity + "]" for identity, name in devices]
        gpu_combo = ttk.Combobox(gpu_section, values=gpu_labels, state="readonly", width=34, style="Settings.TCombobox")
        gpu_combo.current(gpu_ids.index(selected_gpu) if selected_gpu in gpu_ids else 0)
        gpu_combo.pack(side="right")

        def select_gpu(_event=None):
            working["gpu_device_id"] = gpu_ids[gpu_combo.current()]

        gpu_combo.bind("<<ComboboxSelected>>", select_gpu)

        log_section = adv_section(tr("日志", "Logging"))
        log_var = tk.StringVar(value=str(working.get("log_level", "INFO")))
        log_combo = ttk.Combobox(log_section, textvariable=log_var, values=["DEBUG", "INFO", "WARNING", "ERROR"],
                                 state="readonly", width=12, style="Settings.TCombobox")
        log_combo.pack(side="right")
        log_combo.bind("<<ComboboxSelected>>", lambda _e=None: working.__setitem__("log_level", log_var.get()))

        data_section = adv_section(tr("数据", "Data"))
        tk.Label(data_section, text=tr("配置与日志保存在本地数据目录。", "Config and logs live in the local data folder."),
                 bg=card_bg, fg=hint_fg, font=("Segoe UI", 8)).pack(side="left")

        def open_config_dir():
            try:
                os.startfile(str(runtime_data_dir()))
            except Exception:
                pass

        tk.Button(data_section, text=tr("打开数据目录", "Open Data Folder"), relief="flat", bd=0, padx=px(12), pady=px(6),
                  cursor="hand2", bg=row_bg, fg=sub_fg, activebackground=control_bg, activeforeground=text_fg,
                  highlightthickness=0, font=("Segoe UI", 9), command=open_config_dir).pack(side="right", padx=(px(6), 0))

        def reset_all():
            if messagebox.askyesno(tr("确认", "Confirm"), tr("确定要恢复默认设置吗？\n点击“保存”后生效。", "Reset all settings to defaults?\nTakes effect after Save.")):
                for key, value in DEFAULT_CONFIG.items():
                    working[key] = list(value) if isinstance(value, list) else value
                apply_and_reopen(rebuild=True)

        tk.Button(data_section, text=tr("重置所有设置", "Reset All"), relief="flat", bd=0, padx=px(12), pady=px(6),
                  cursor="hand2", bg=danger, fg=on_accent, activebackground=danger, activeforeground=on_accent,
                  font=("Segoe UI", 9, "bold"), highlightthickness=0, command=reset_all).pack(side="right")

        btn_row = tk.Frame(frame, bg=win_bg)
        btn_row.pack(fill="x", pady=(px(10), 0))

        tk.Button(btn_row, text=tr("取消", "Cancel"), relief="flat", bd=0, padx=0, pady=px(10), cursor="hand2", bg=win_bg,
                  fg=sub_fg, activebackground=control_bg, activeforeground=text_fg, font=("Segoe UI", 11, "bold"),
                  highlightthickness=0, command=self._cancel_settings).pack(side="left", fill="x", expand=True, padx=(0, px(6)))

        def save_and_close() -> None:
            working["fps_target_process"] = process_var.get()
            try:
                working["lan_dashboard_port"] = int(str(dashboard_port_var.get()).strip())
            except (TypeError, ValueError):
                working["lan_dashboard_port"] = DEFAULT_CONFIG["lan_dashboard_port"]
            if not 1024 <= working["lan_dashboard_port"] <= 65535:
                working["lan_dashboard_port"] = DEFAULT_CONFIG["lan_dashboard_port"]
            self.config.update(working)
            self._save_config()
            self.root.attributes("-topmost", bool(self.config["always_on_top"]))
            self.root.attributes("-alpha", float(self.config["window_opacity"]))
            pos_x, pos_y = self.config.get("window_x"), self.config.get("window_y")
            if type(pos_x) is int and type(pos_y) is int:
                self.root.geometry(f"+{pos_x}+{pos_y}")
            self._apply_fps_config(force_restart=True)
            self._apply_lan_dashboard_config()
            self._set_autostart(bool(working.get("autostart", False)))
            try:
                self.logger.setLevel(getattr(logging, str(working.get("log_level", "INFO")), logging.INFO))
            except Exception:
                pass
            self._rebuild_ui_fast()
            self._close_settings_dialog()

        tk.Button(btn_row, text=tr("保存", "Save"), relief="flat", bd=0, padx=0, pady=px(10), cursor="hand2", bg=accent,
                  fg=on_accent, activebackground=accent, activeforeground=on_accent, font=("Segoe UI", 11, "bold"),
                  highlightthickness=0, command=save_and_close).pack(side="left", fill="x", expand=True, padx=(px(6), 0))

        self.settings_window.protocol("WM_DELETE_WINDOW", self._cancel_settings)

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
        app_dir = runtime_data_dir()
        config_path = app_dir / "config.json"
        try:
            app_dir.mkdir(parents=True, exist_ok=True)
            preserve_invalid_config(config_path)
            tmp_path = config_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(config_path)
        except Exception as exc:
            self.logger.error("Failed to save config: %s", exc)
            messagebox.showerror(APP_NAME, "配置未保存 / Configuration was not saved", parent=self.root)

    def _apply_fps_config(self, force_restart: bool = False) -> None:
        enabled = bool(self.config.get("fps_enabled", False))
        target = str(self.config.get("fps_target_process", "") or "")
        self.logger.info("Apply FPS config: enabled=%s target=%s force_restart=%s", enabled, target, force_restart)
        self.fps_service.configure(enabled=enabled, target_process=target, force_restart=force_restart)

    def _apply_lan_dashboard_config(self) -> None:
        if not bool(self.config.get("lan_dashboard_enabled", False)):
            self.lan_dashboard.stop()
            return
        port = int(self.config.get("lan_dashboard_port", 8765))
        if self.lan_dashboard.is_running and self.lan_dashboard.port == port:
            return
        self.lan_dashboard.stop()
        if not self.lan_dashboard.start(port):
            self.logger.warning("LAN dashboard remains disabled because port %s is unavailable", port)

    def _lan_dashboard_address(self, port: int) -> str:
        en = self.config.get("ui_language") == "en"
        if not self.lan_dashboard.is_running:
            return "Not running" if en else "未运行"
        candidates = []
        try:
            stats = psutil.net_if_stats()
            for name, addresses in sorted(psutil.net_if_addrs().items()):
                if name not in stats or not stats[name].isup:
                    continue
                for item in addresses:
                    if item.family != socket.AF_INET:
                        continue
                    address = ipaddress.ip_address(item.address)
                    if not (address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast):
                        candidates.append(f"{name}: http://{address}:{self.lan_dashboard.port}")
        except (OSError, ValueError):
            pass
        return ("IPv4 candidates (reachability depends on network): " if en else "IPv4 候选（能否访问取决于网络）：") + ("; ".join(candidates) or ("None" if en else "无"))

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
                on_settings=lambda: self.root.after(0, self._toggle_settings),
            )
            if self.tray_service.start():
                self.tray_service.show()
        except Exception:
            self.tray_service = None

    def _minimize_clicked(self) -> None:
        """The minimize button must always do something visible."""
        if bool(self.config.get("minimize_to_tray", True)):
            self._hide_to_tray()
            return
        try:
            self.root.iconify()
        except Exception:
            self.root.withdraw()

    def _hide_to_tray(self) -> None:
        if self.tray_service is None:
            return
        try:
            shown = self.tray_service.show()
            if shown:
                self.root.withdraw()
            else:
                self.root.deiconify()
                self.hint_label.configure(text="Tray unavailable; window kept open" if self.config.get("ui_language") == "en" else "托盘不可用，窗口保持显示")
        except Exception:
            self.logger.exception("Tray operation failed")

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
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    target = f'"{Path(sys.executable).resolve()}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
                    winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, target)
                    try:
                        winreg.DeleteValue(key, LEGACY_AUTOSTART_VALUE_NAME)
                    except FileNotFoundError:
                        pass
                else:
                    for value_name in (AUTOSTART_VALUE_NAME, LEGACY_AUTOSTART_VALUE_NAME):
                        try:
                            winreg.DeleteValue(key, value_name)
                        except FileNotFoundError:
                            pass
            return True
        except Exception:
            return False

    def _is_autostart_enabled(self) -> bool:
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                for value_name in (AUTOSTART_VALUE_NAME, LEGACY_AUTOSTART_VALUE_NAME):
                    try:
                        winreg.QueryValueEx(key, value_name)
                        return True
                    except FileNotFoundError:
                        pass
                return False
        except Exception:
            return False

    def _close_now(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self.sensor_runtime.stop()
        shutdown_deadline = time.monotonic() + 3
        if self._ui_timer_id is not None:
            try:
                self.root.after_cancel(self._ui_timer_id)
            except Exception:
                pass
        if self.diag_window is not None and self.diag_window.winfo_exists():
            self.diag_window.destroy()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        def stop_services():
            self.fps_service.close()
            self.lan_dashboard.stop()
            if self.tray_service is not None:
                self.tray_service.close()
        cleanup = threading.Thread(target=stop_services, name="service-shutdown", daemon=True)
        cleanup.start()
        def finish():
            worker = self.sensor_runtime.thread
            if ((worker is not None and worker.is_alive()) or cleanup.is_alive()) and time.monotonic() < shutdown_deadline:
                self.root.after(50, finish)
                return
            if worker is not None and worker.is_alive():
                self.logger.error("unclean sampler shutdown")
            if cleanup.is_alive():
                self.logger.error("unclean service shutdown")
            self.root.destroy()
        finish()


def validate_config(raw):
    """Normalize only known fields, without coercing unsafe truthy values."""
    errors = []
    if not isinstance(raw, dict):
        return DEFAULT_CONFIG.copy(), ["root"]
    raw = dict(raw)
    if "refresh_interval_ms" not in raw and "update_interval_ms" in raw:
        raw["refresh_interval_ms"] = raw["update_interval_ms"]
    result = DEFAULT_CONFIG.copy()
    enums = {"theme": THEMES, "display_mode": ("标准", "精简"),
             "ui_language": ("zh", "en"), "close_action": ("tray", "exit"),
             "log_level": ("DEBUG", "INFO", "WARNING", "ERROR")}
    for key, default in DEFAULT_CONFIG.items():
        if key not in raw:
            continue
        value = raw[key]
        valid = True
        if type(default) is bool:
            valid = type(value) is bool
        elif key == "gpu_device_id":
            valid = value is None or isinstance(value, str)
        elif key in enums:
            valid = isinstance(value, str) and value in enums[key]
        elif key == "metric_order":
            valid = isinstance(value, list) and all(isinstance(x, str) and x in METRIC_MAP for x in value)
            if valid:
                value = list(dict.fromkeys(value + DEFAULT_METRIC_ORDER))
        elif key in ("window_x", "window_y"):
            valid = value is None or type(value) is int
        elif isinstance(default, (int, float)):
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            if valid:
                if key == "refresh_interval_ms":
                    valid = type(value) is int and 300 <= value <= 2147483647
                elif key == "lan_dashboard_port":
                    valid = type(value) is int and 1024 <= value <= 65535
                elif key == "window_opacity":
                    # Keep the overlay recoverable: never persist a fully invisible window.
                    value = min(1.0, max(MIN_WINDOW_OPACITY, value))
                elif key == "font_scale":
                    value = min(1.4, max(.9, value))
        else:
            valid = isinstance(value, str)
        if valid:
            result[key] = value
        else:
            errors.append(key)
    if not result["metric_order"]:
        result["metric_order"] = list(DEFAULT_METRIC_ORDER)
    return result, errors


def preserve_invalid_config(path):
    if not path.exists():
        return
    contents = path.read_bytes()
    try:
        _, errors = validate_config(json.loads(contents))
    except (ValueError, UnicodeError):
        errors = ["json"]
    if errors:
        digest = hashlib.sha256(contents).hexdigest()
        backup = path.with_name("config.invalid-" + digest + ".json")
        try:
            with backup.open("xb") as output:
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if backup.read_bytes() != contents:
                raise OSError("Configuration backup does not match original")


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    _logger = logging.getLogger("hardware_monitor")

    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    data_dir = runtime_data_dir()
    config_path = data_dir / "config.json"
    legacy_config_path = app_dir / "config.json"
    if not config_path.exists() and legacy_config_path.exists() and legacy_config_path != config_path:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_config_path, config_path)
            _logger.info("Migrated config to %s", config_path)
        except Exception as exc:
            _logger.warning("Failed to migrate config: %s", exc)

    if not config_path.exists():
        return validate_config({})[0]
    try:
        contents = config_path.read_bytes()
        raw = json.loads(contents)
        if isinstance(raw, dict):
            for key, translations in {
                "theme": {"娣辫壊钃?": "深色蓝", "娣辫壊钃�": "深色蓝", "鑻规灉娴呰壊": "苹果浅色", "鐭冲ⅷ鐏?": "石墨灰", "鐭冲ⅷ鐏�": "石墨灰"},
                "display_mode": {"鏍囧噯": "标准", "绮剧畝": "精简"},
            }.items():
                value = raw.get(key)
                if isinstance(value, str) and value in translations:
                    raw[key] = translations[value]
        config, errors = validate_config(raw)
        if errors:
            _logger.warning("Invalid config fields %s; original sha256=%s", errors, hashlib.sha256(contents).hexdigest())
        return config
    except (ValueError, UnicodeError, OSError) as exc:
        _logger.warning("Failed to load config: %s", exc)
        return validate_config({})[0]


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

