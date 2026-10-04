<img width="1254" height="1254" alt="Hardware monitoring" src="https://github.com/user-attachments/assets/11b6ff6b-830c-418a-89f9-98d1758eaa25" />





产品介绍（中文）
Hardware Monitoring 是一款面向 Windows 的轻量级实时性能监控工具，专注于以清晰、稳定、低干扰的方式展示关键硬件状态。软件可持续读取并展示 CPU、内存、GPU、显存、温度、频率、功耗、磁盘、网络及游戏帧率（FPS）等核心指标，帮助用户快速判断设备运行负载与健康状态。
在交互设计上，产品采用小窗极简布局与分组化信息展示，支持按需显示/隐藏监控项、刷新频率调节、透明度调节、置顶显示、最小化到系统托盘、关闭按钮行为自定义等常用能力。针对游戏场景，软件提供目标进程选择与 FPS 状态展示，并在组件缺失或无数据时以友好状态文本提示，不以弹窗打断使用流程。
产品支持中文/英文双语言切换，适用于日常办公、游戏运行观察、硬件状态巡检等场景。整体方案强调“开箱即用、配置直观、运行稳定”，在保留专业监控信息的同时，尽可能降低学习与使用门槛。

Product Introduction (English)
Hardware Monitoring is a lightweight, real-time performance monitoring tool for Windows, designed to present critical hardware data in a clear, stable, and low-distraction way. It continuously displays key metrics such as CPU, memory, GPU, VRAM, temperature, frequency, power, disk activity, network throughput, and in-game FPS, enabling users to quickly understand system load and device condition.
The product uses a compact window with grouped information for fast readability, and provides practical controls including metric visibility toggles, refresh interval options, opacity adjustment, always-on-top mode, minimize-to-tray behavior, and customizable close-button actions. For gaming use cases, it supports target-process selection and FPS status display, while handling missing components or unavailable data gracefully through inline status text instead of intrusive popups.
With built-in Chinese/English language switching, Hardware Monitoring fits daily productivity, gaming observation, and routine hardware health checks. The overall experience focuses on out-of-box usability, intuitive configuration, and reliable operation, delivering professional monitoring insights with a low learning curve.

## 下载 / Downloads

当前正式版本：v1.0.12
Current stable release: v1.0.12

- Release notes / 发布说明：https://github.com/seiya058904/Hardware-Monitoring/releases/tag/v1.0.12
- Windows installer / Windows 安装包：`HardwareMonitoring_Setup_v1.0.12.exe`

安装包 SHA-256 / Installer SHA-256：`A7CD3EC21B5B476C1067F174F3F9637D0CCC2AAF8AB6C7D0A093A571E87C2F9E`

本地工程候选版本为 v1.0.13，安装包 `HardwareMonitoring_Setup_v1.0.13.exe` 尚未发布到 GitHub。首轮 Windows 实测对照见 [before / after 报告](docs/engineering-upgrade-1.0.13.md)，当前安装包校验值、正式升级和稳定性结果及剩余风险见 [RC 验收报告](docs/release-audit-1.0.13.md)。主要改进为采样节拍、FPS 处理成本、设置与 native 服务的线程边界、设备故障状态及多文件升级清单，默认配置保持不变。

`python -m unittest discover -s tests -v` 中的快速桌面回归默认隐藏真实 Tk 窗口，并屏蔽恢复窗口和抢焦点操作；可见桌面、托盘和安装器验收采用少量持续运行，避免密集弹窗/关闭。

运行时配置和日志保存在 `%LOCALAPPDATA%\Hardware Monitoring`。设置窗口采用“保存 / 取消”事务语义：主题、透明度、文字大小、监控项等改动先在窗口上实时预览，只有点击“保存”才写入配置并应用 FPS / 局域网 / 开机自启动等系统级设置；点击“取消”或关闭设置窗口会完整还原。高级设置中的“打开数据目录”直达上述配置目录。悬浮窗位置会被记忆，并在下次启动时自动拉回可见屏幕范围；透明度存在 35% 的下限，避免窗口被调到完全不可见。主窗口标题栏提供采样状态指示：绿色表示实时，黄色表示部分传感器不可用，灰色表示数据过期或暂无数据。固定直接依赖版本、第三方来源和 SHA-256 记录见 `requirements-*.txt`、`THIRD_PARTY_NOTICES.md`；可运行 `powershell -ExecutionPolicy Bypass -File scripts\fetch-dependencies.ps1` 获取并校验固定版本的二进制依赖。requirements 文件不是包含传递依赖哈希的完整 lock 文件。
卸载程序默认保留 `%LOCALAPPDATA%\Hardware Monitoring` 中的用户配置和日志；如需彻底清理，请在卸载后手动删除该目录。

## 本地历史安装包 / Local historical installers

本地保留的 v1.0.3–v1.0.9 安装包集中在 `archive/installers/`，用于版本追溯，仍由 `.gitignore` 排除。它们不参与当前构建；正式下载和版本以以上 Release 为准。该目录只在保留了历史安装包的本地工作区中存在。

Local retained v1.0.3–v1.0.9 installers live in `archive/installers/` for version history and remain excluded by `.gitignore`. They are not build inputs. Use the release above for current downloads; this directory exists only in workspaces retaining those local installers.

## 局域网仪表盘 / LAN dashboard

在“高级设置”中主动启用“局域网仪表盘”后，手机可在同一 Wi-Fi 下访问设置中显示的地址（默认端口 `8765`）。页面每秒刷新一次，仅提供 `GET /`、`GET /api/metrics` 和 `GET /healthz`；不含远程控制、文件访问或公网/防火墙自动配置。关闭该开关或退出程序会停止服务并释放端口。Windows 防火墙提示时仅允许专用网络。

页面首屏突出 CPU、GPU、内存、GPU 温度、FPS 与 1% Low 六个核心指标，其余数据按系统 / 显卡 / 性能 / I/O 分组展示；支持中英文切换与深色 / 浅色主题（保存在浏览器本地）。页面严格跟随采样健康状态：数据过期或断开后不再把旧数字当作实时值显示。

<img width="475" height="902" alt="image" src="https://github.com/user-attachments/assets/8b3a7b37-8b3b-4df3-8617-d46968ff386f" />

<img width="764" height="694" alt="image" src="https://github.com/user-attachments/assets/bc32c3e2-4bfd-4ec3-b402-3ca316fc8b86" />

## Android Termux 监控节点 / Android Termux Monitoring Node

v1.0.11 提供可选的 Android Termux 监控节点，包含配置示例、安装与卸载脚本、启动脚本和健康检查。它适合需要从 Android 设备采集或上报监控状态的场景；仅使用 Windows 桌面悬浮监控时无需安装或配置此组件。

v1.0.11 includes an optional Android Termux monitoring node with configuration examples, install/uninstall scripts, startup scripts, and health checks. It is intended for Android-based monitoring scenarios; no setup is required for normal Windows desktop overlay use.


## 运行时可靠性与兼容性 / Runtime reliability

高级设置中的“监控显卡”保留一个设备的完整指标组。选择保存的是不透明设备 ID，名称只用于展示；设备离线时保留选择。未选择时按设备 ID 确定默认设备。LHM 与 nvidia-smi 的身份不能验证一致时，不跨设备补齐缺失字段。

桌面与 LAN API 共用采样健康状态。`/api/metrics` 保留 `status`、`updated_at`、`metrics`，新增 `sample_state`、`sample_age_ms`、`sample_generation`、`error_code`；`status=ok` 表示响应有效，采样是否可用由 `sample_state` 表达。`ok/degraded` 为新鲜数据（后者有部分故障），`stale/unavailable/stopping` 不代表实时指标。`sample_generation` 在本次运行内随有效样本递增；`sample_age_ms` 使用服务器单调时间。详细本地诊断不通过 API 公开。新版网页及 Termux 不依赖设备间墙钟同步，旧协议才检查时间戳与有限时钟偏差。

v1.0.13 增加可选 `sample_stale_after_ms`，使网页在请求等待期间也按服务端采样期限隐藏旧值；旧服务响应缺少该字段时回退到 5 秒。显示与采样使用已提交的配置，设置预览及取消不改变后台采样。

LAN 默认关闭。启用后最多接受 16 个并发连接，每个连接从接受起有 5 秒总期限；关闭会撤销并回收已接入连接。多网卡地址以 IPv4 候选列表显示，不保证任意手机均可访问。采样停止推进时桌面显示过期；退出最多等待 3 秒，无法取消的 native 调用可能记录 `unclean sampler shutdown`，此时不再从其他线程释放传感器。

错误类型的配置不会启用 LAN。对语法或字段类型损坏的配置，首次保存前在配置目录创建按内容摘要命名的 `config.invalid-*.json` 原文备份；备份失败则拒绝覆盖。Windows 安装器使用 `managed-files.json` 管理自身文件，升级/卸载遇到本安装目录程序占用会失败并允许重试，不终止其他 PresentMon。升级失败保留必要恢复材料，不删除用户数据。没有清单的旧安装需要先用新版安装器修复后再按清单卸载。
