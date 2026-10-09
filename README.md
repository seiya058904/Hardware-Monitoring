# Hardware Monitoring

**A quieter way to see what your Windows PC is doing.**

轻量 Windows 实时硬件监控悬浮窗，专注于清楚、稳定地呈现关键性能指标。

**[⬇️ Download for Windows](https://github.com/seiya058904/Hardware-Monitoring/releases/latest)** · [Features](#what-it-monitors) · [LAN dashboard](#on-another-screen) · [Android node](android/termux/README.md) · [For developers](#development-and-verification)

<img width="680" alt="Hardware Monitoring — project overview" src="https://github.com/user-attachments/assets/11b6ff6b-830c-418a-89f9-98d1758eaa25" />


## What it monitors

| Monitor / 监控 | Experience / 使用体验 |
| --- | --- |
| **CPU · GPU · VRAM · RAM** | 温度、频率、功耗与资源负载，根据传感器能力展示 |
| **Game performance** | FPS 与可用的 1% Low 数据；可选择目标进程 |
| **Storage · Network** | 磁盘及网络活动实时观察 |
| **Desktop overlay** | 紧凑悬浮窗、透明度、置顶、托盘、监控项与刷新周期设置 |
| **Health-aware readings** | 区分正常、部分故障、过期和不可用数据，不以旧值假冒实时读数 |
| **English / 中文** | 应用及局域网看板的双语言界面 |

> 不同硬件、驱动和采样工具能够提供的数据并不相同。不可用的指标会明确呈现状态，不应被视作零值。

## Download and setup · 下载与使用

1. 从 [Releases](https://github.com/seiya058904/Hardware-Monitoring/releases/latest) 下载面向 Windows 的正式安装包（历史版本：[v1.0.14](https://github.com/seiya058904/Hardware-Monitoring/releases/download/v1.0.14/HardwareMonitoring_Setup_v1.0.14.exe)）。
2. 启动悬浮窗，确认采样状态。某些传感器不可用时，界面会区分缺失和过期数据。
3. 在设置中按需启用 FPS、选择显卡、调整刷新周期和窗口外观。**保存**才应用持久配置；取消则回滚预览。

用户配置与日志保存在 `%LOCALAPPDATA%\Hardware Monitoring`。卸载默认保留这些数据，以免意外丢失配置。

## On another screen

Hardware Monitoring 以 Windows 本机悬浮窗为主。需要在手机查看时，再到高级设置**主动启用**局域网仪表盘；手机与电脑须在同一可信网络下，使用应用显示的地址（默认端口 `8765`）。

<table>
<tr>
<td width="42%"><img width="310" alt="LAN dashboard mobile view" src="https://github.com/user-attachments/assets/8b3a7b37-8b3b-4df3-8617-d46968ff386f" /></td>
<td width="58%"><img width="450" alt="LAN dashboard metrics view" src="https://github.com/user-attachments/assets/bc32c3e2-4bfd-4ec3-b402-3ca316fc8b86" /></td>
</tr>
</table>

- 重点呈现 CPU、GPU、内存、GPU 温度、FPS 与 1% Low；详细指标按类别组织。
- 只开放 `GET /`、`GET /api/metrics`、`GET /healthz`；**不提供远程控制或文件访问**。
- 默认关闭；不会自行修改路由器或 Windows 防火墙。仅建议在可信的专用网络中使用。
- 桌面和看板共用采样健康状态，`status=ok` 不代表样本一定新鲜，需同时查看 `sample_state`。

可选的 [Android Termux 节点](android/termux/README.md) 用于 Android 端监控场景。**仅使用 Windows 悬浮窗时无需安装。**

## Development and verification

| Location | Responsibility |
| --- | --- |
| [`app.py`](app.py) | 桌面程序和 Tk 界面入口 |
| [`sensor_runtime.py`](sensor_runtime.py), [`fps_stream.py`](fps_stream.py) | 传感器采样与 FPS 流 |
| [`dashboard_server.py`](dashboard_server.py) | 可选的 LAN 指标服务 |
| [`tests/`](tests/) | 回归测试 |
| [`Hardware Monitoring.spec`](Hardware%20Monitoring.spec), [`Hardware Monitoring.nsi`](Hardware%20Monitoring.nsi) | PyInstaller / NSIS 打包配置 |

在适当配置的 Windows Python 环境运行核心回归：

```powershell
python -m unittest discover -s tests -v
```

固定的直接依赖和第三方来源见 [`requirements-runtime.txt`](requirements-runtime.txt)、[`requirements-build.txt`](requirements-build.txt) 与 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。必要的二进制依赖可以按仓库脚本获取及校验；不要将 requirements 误认为完整的传递依赖哈希锁文件。

**Further reading:** [1.0.13 engineering upgrade](docs/engineering-upgrade-1.0.13.md) · [Release candidate audit](docs/release-audit-1.0.13.md) · [Agent guide](AGENTS.md)。

## Data boundaries and notices

Hardware Monitoring 是面向本机观察的工具，不代替专业硬件诊断。请勿将局域网接口直接暴露到公网。第三方组件的许可与来源以仓库内的实际 notices 为准；不要推断整个项目具有未声明的许可证。
