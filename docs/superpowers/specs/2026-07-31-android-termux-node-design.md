# Android Termux 监测节点：第二阶段设计规格

## 1. 范围与决定

本规格定义一个运行在闲置 Vivo Android 手机上的 24 小时 Termux 监测节点。它每分钟独立检查 Windows Hardware Monitoring 局域网仪表盘、当前默认网关和公网连通性，并仅以本机通知提示故障和恢复。

本阶段的批准方案是 **方案 B：Python 监测进程 + Shell 守护循环 + Termux:Boot**。它比单一常驻进程更能从 Python 意外退出和手机重启中恢复，同时不引入进程管理器或自建 Android 应用。

第一版严格排除远程控制、手机入站服务、SSH、电脑命令执行、文件访问、云端上传、主手机推送、Token、数据库、遥测和路由器配置。网络请求仅用于健康检测；配置不得含密码、Token 或私钥。

## 2. 预期目录与职责

未来实现位于独立目录，不能污染 Windows 应用主逻辑：

```text
android/termux/
├── monitor_node.py
├── config.example.json
├── install.sh
├── uninstall.sh
├── boot.sh
├── tests/
└── README.md
```

| 组件 | 输入 | 输出 | 依赖与职责 |
| --- | --- | --- | --- |
| `monitor_node.py` | JSON 配置、持久状态、网络响应、信号 | 状态 JSON、轮转日志、本地通知命令 | Python 标准库；执行单轮检测或常驻循环；验证数据、维护状态机/锁/计数、处理 SIGTERM/SIGINT。 |
| `config.example.json` | 用户编辑的非秘密配置 | 节点运行参数 | 仅模板；IP/端口可编辑，绝不硬编码到 Python 逻辑。 |
| `boot.sh` | Termux:Boot 调用、节点退出码 | wake lock、单一守护循环、崩溃通知 | POSIX shell、`termux-wake-lock`、`termux-notification`（若可用）；开机延迟、退避和重复启动防护。 |
| `install.sh` | 已安装的可信 Termux 环境、用户确认的配置 | 私有目录、模板、Boot 入口 | 幂等安装和前台诊断；不下载 APK、不覆盖有效配置。 |
| `uninstall.sh` | 可选彻底删除参数 | 停止节点、移除本阶段入口/程序 | 默认保留配置和日志；只删除本阶段精确路径。 |
| `tests/` | 本地 fixture 与受控假响应 | 单元/集成测试结果 | 不依赖真实公网。 |
| `README.md` | 安装、限制和验收说明 | 用户操作说明 | 如实区分可自动执行与必须由 Android 确认的动作。 |

运行数据使用私有目录 `~/.local/share/hardware-monitor-node/`：

```text
config.json              # 用户配置；安装不覆盖有效文件
logs/monitor.log          # 轮转日志
state.json                # 原子写入的持久状态
monitor.lock              # 单实例锁/PID 元数据
```

## 3. 配置契约

默认模板采用以下值；`dashboard_base_url` 是示例，用户必须按当前 LAN IPv4 修改。实现前将再次确认两个公网 HTTPS 探测端点是否仍适合使用，故本规格不把任何未经实时核查的第三方域名固化为默认事实。

```json
{
  "dashboard_base_url": "http://192.168.2.249:8765",
  "check_interval_seconds": 60,
  "request_timeout_seconds": 5,
  "failure_threshold": 3,
  "recovery_threshold": 2,
  "reminder_interval_seconds": 3600,
  "startup_delay_seconds": 30,
  "log_max_bytes": 1048576,
  "log_backup_count": 5,
  "check_gateway": true,
  "check_internet": true,
  "internet_probe_urls": []
}
```

验证规则：基础 URL 必须为 `http` 或 `https` 且不含认证信息；周期、超时、阈值、日志上限和保留数均为正整数；`failure_threshold` 和 `recovery_threshold` 不得为零；开启公网检查时 `internet_probe_urls` 必须恰有两个 HTTPS URL。实施时选定并实时核查目标后，模板将填入两个独立、轻量、无账号需求的端点；任意一个成功即视为公网可用。空列表只在公网检查关闭时有效。

## 4. 检测语义

### 4.1 仪表盘

每轮按顺序检查：TCP/HTTP 建连、`GET /healthz`、`GET /api/metrics`、HTTP 成功状态、JSON 解析、顶层 `status == "ok"`、非空 `updated_at`、未过期时间戳和对象类型的 `metrics`。数据新鲜度上限为 `max(2 * check_interval_seconds + request_timeout_seconds, 125)` 秒，避免手机短暂调度延迟误报。

结果分类为 `unreachable`、`timeout`、`health_http_error`、`health_invalid`、`metrics_http_error`、`metrics_json_invalid`、`metrics_status_invalid`、`metrics_stale`、`metrics_shape_invalid` 与 `ok`。`/healthz` 成功而 `metrics_stale` 仍是仪表盘数据故障，不能视为健康。

### 4.2 默认网关

节点优先读取 Android 路由表的默认路由，例如 `ip route` 中的 `default via <gateway>`；解析失败时记录 `gateway_unknown`，并把网关检查标为 `unknown`，而非臆测 `192.168.1.1`。取得网关后，优先尝试一个短超时 TCP connect（默认端口 53，失败后不扫描端口）；若 Android 工具/权限使该方法不可用，记录 `gateway_probe_unavailable`，不令整个节点退出。传统 ICMP `ping` 不是健康判据，因为 Android/Termux 可能没有对应权限或工具。

### 4.3 公网

对两个配置 HTTPS URL 进行小型 `HEAD` 或可回退的 `GET` 请求，不下载大文件、不持久化响应体、不记录完整 URL 查询参数。任何一个成功即为 `ok`；两个都失败才计入公网失败。DNS 失败、TLS/HTTP 异常和超时应分类日志化，但不输出隐私请求信息。

## 5. 独立故障状态机

仪表盘、网关和公网各自拥有以下状态与计数，互不影响：

| 当前状态 | 本轮结果 | 条件 | 下一状态 | 动作 |
| --- | --- | --- | --- | --- |
| `unknown` | 成功 | 1 次 | `healthy` | 保存成功时间，不通知。 |
| `unknown`/`healthy` | 失败 | 少于 3 次连续失败 | `suspected_failure` | 仅计数。 |
| `suspected_failure` | 失败 | 第 3 次连续失败 | `failed` | 记录首次故障并发送一次故障通知。 |
| `suspected_failure` | 成功 | 1 次 | `healthy` | 清除失败计数，不通知。 |
| `failed` | 失败 | 距上次提醒少于 3600 秒 | `failed` | 更新状态，不通知。 |
| `failed` | 失败 | 已到提醒间隔 | `failed` | 更新同一通知 ID。 |
| `failed` | 成功 | 第 1 次连续成功 | `recovering` | 记录恢复候选。 |
| `recovering` | 成功 | 第 2 次连续成功 | `healthy` | 发送恢复通知并清除/更新故障通知。 |
| `recovering` | 失败 | 任意一次 | `failed` | 重置成功计数；按提醒节流。 |

重启后从 `state.json` 恢复状态、连续计数、首次故障、上次通知和上次成功。旧 `failed` 状态不会被当作新故障立即重报；它继续遵守既有提醒间隔。单次抖动不会触发通知。

## 6. 通知、日志和状态

第一版仅通过 Termux:API 的 `termux-notification` 产生本地通知。每个目标使用稳定固定 ID；同一故障更新而非堆积，恢复时取消或更新同 ID。通知标题简洁，正文只含故障类别、持续时间与最近检测时间，不含完整 metrics、路径、账号或秘密。可通知类别包括仪表盘不可达/响应异常/数据过期、网关不可达、公网不可达、各自恢复和守护循环反复崩溃。

若 Termux:API 或通知命令不可用，节点继续监测；以受限频率写 `notification_unavailable` 日志，且不得把通知失败计为目标失败。

Python 使用标准库轮转日志：每文件最多 1 MiB、最多 5 个备份。故障、恢复、配置错误和周期性摘要记录时间、目标、分类、耗时和有限错误文本；正常健康检查不每分钟产生详细 INFO。不得记录完整 metrics JSON、联系人、相册、账号或文件列表。

`state.json` 是 JSON 数据，不含可执行内容。通过写入同目录临时文件、`fsync` 后原子替换保存；读取损坏文件时记录错误并从安全的 `unknown` 状态重新开始，保留损坏文件以供人工检查而不解析执行。

## 7. 单实例、退出与崩溃恢复

`monitor_node.py` 使用原子创建的锁文件（包含 PID 和启动时间）确保手动运行与 Boot 启动不能并存。获取锁失败时读取 PID：若进程存在则安全退出；若 PID 不存在或元数据无效，则把锁认定为陈旧并仅替换该节点的锁。进程注册 SIGTERM/SIGINT，停止新一轮检查、保存状态、释放锁后退出。

`boot.sh` 是 Termux:Boot 的 `~/.termux/boot/` 入口。它先等待配置的 30 秒，获取 wake lock，再启动单一守护循环。每次启动前依赖 Python 锁判断是否已有节点；子进程非正常退出时采用 `5 → 15 → 30 → 60 → 300` 秒退避。连续稳定运行一个检查窗口后重置退避。达到连续崩溃上限时发送一条崩溃通知并停止快速重试，等待下一次 Boot 或人工启动，避免耗电死循环。正常 `uninstall.sh` 会先请求终止、等待有限时间、释放 wake lock，再移除本阶段 Boot 入口。

## 8. 安装、卸载与 Android 生命周期

`install.sh` 检查所需 Termux 命令、创建精确私有目录、复制模板（只在配置不存在或无效时）、建立 Boot 入口、设置合理私有权限、验证配置并运行一次前台诊断。它可重复执行且不从不可信来源下载 APK。

`uninstall.sh` 默认只停止节点、释放 wake lock、删除本阶段程序和 Boot 入口，并保留配置、日志和状态。显式彻底删除参数只允许删除 `~/.local/share/hardware-monitor-node/` 及本阶段精确脚本路径；绝不删除整个 Termux home、其他脚本或目录。

Termux 与 Termux:Boot 必须来自兼容签名来源，不能混装。wake lock 仅降低休眠风险，不保证进程永存；Vivo 的电池优化、自启动和后台活动限制仍可能终止 Termux。因此依赖 Boot 恢复、守护循环和受限日志，而非假定永久后台运行。节点在 USB 断开、无 ADB 连接和屏幕关闭后仍应独立运行。APK 安装确认、USB 调试 RSA、通知权限、电池优化豁免以及 Vivo 自启动/后台权限可能需要用户在手机上确认；自动化不得宣称可以绕过这些系统弹窗。

## 9. 安全边界与部署分工

未来已授权 ADB 可以检测设备与已安装包、推送普通文件、执行允许的 Termux 命令、生成配置、运行诊断、读取有限日志、注入受控故障并恢复临时配置。它不能绕过 Android 安装确认、RSA 授权、通知权限、电池优化或厂商后台权限。

节点不监听任何端口，不启动 SSH，不控制电脑/路由器，不上传日志，不访问联系人、短信、相册、麦克风、摄像头或位置，也不建立公网端口映射。Windows 防火墙与路由器配置保持由用户控制。

## 10. 测试与验收计划

| 层级 | 覆盖 |
| --- | --- |
| Python 单元测试 | 配置默认/校验、URL 构造、metrics JSON、时间戳过期、状态机、阈值、提醒节流、损坏状态回退、原子保存、日志轮转、网关解析、单实例锁、通知失败和超时分类；全部使用本地 fixture。 |
| Termux 集成测试 | 安装幂等、前台/后台启动、单实例、终止与重启、错误配置、日志轮转、状态持久化、缺失 Termux:API、Boot 入口及 wake lock 获取/释放。 |
| 真机验收 | 真实 healthz/metrics、连续 3 次故障通知、连续 2 次恢复、仅阻断公网的分类、USB 断开、屏幕关闭、手机重启恢复、无重复进程、日志上限和两种卸载行为。 |

数小时持续运行、深度休眠表现和厂商后台策略只能记录为后续观察，不得在即时验收中伪装为已完成。

## 11. 设计自审

已核对：目录职责与状态文件一致；默认周期/超时/阈值在各章节一致；公网端点未被伪装为已验证默认值；通知失败不影响目标健康；锁、退避和卸载均具有限定范围；安全边界未被安装或 ADB 自动化章节绕开；本文没有未决条目或实现脚本。

本规格仅为第二阶段实现前的设计基线，不授权安装手机应用、修改 Android、创建实现文件、部署或发布。
