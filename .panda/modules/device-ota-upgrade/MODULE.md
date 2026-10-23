# Device OTA Upgrade

## 职责边界

设备端与管理端 OTA 自动升级的配套设计及生命周期约束，覆盖发布审批、逐设备授权、下载、安装编排、重启确认及恢复。管理端已实现独立 OTA 存储、受控导入、隔离签名、逐基线候选、设备接口及灰度页面，默认关闭；设备端已实现手动/每日检测、逐次确认、独立 worker/授权 helper、安装重启及健康上报，仍须完成目标构建与真机核验后才能启用；不负责内核、bootloader、GPT、分区布局或原始块升级。

## 关联源码路径

- 详细设计：`apps/reader-shell/docs/OTA-DESIGN.md`；部署入口：`apps/reader-shell/docs/DEPLOYMENT.md`。
- 管理端详细设计：`apps/manager/docs/OTA-DESIGN.md`；管理与设备认证边界：`apps/manager/manager/{app.py,cloud_auth.py,reader.py,cloud.py,fleet.py,device_api.py}`。
- 现有 NORMAL 事务：`apps/reader-shell/deploy/normal_boot/{normal_upgrade.py,upgrade_profile.py,apply_tool.c,upgrade_wire.h,upgrade_target.h}`。
- 启动与休眠：`apps/reader-shell/deploy/normal_boot/{service.in,early.in,policy.in,suspend.in,build.py}`。
- 设备 OTA：`apps/reader-shell/ota/`、`ota_worker.cpp`、`ota_ui.cpp`；首次接入材料：`deploy/normal_boot/prepare_ota.py`；受限服务接线：`deploy/normal_boot/ota.in`（均位于 reader-shell 下）。
- 设备网络及电源：`apps/reader-shell/{sync.h,sync.cpp,tls.cpp,main.cpp,standbypolicy.h,battery.h,battery_posix.cpp}`。
- 管理端实现：`apps/manager/manager/{ota_store.py,ota.py,ota_api.py,ota_publish.py,ota_worker.py,ota_signer.py,ota_verify.py}`；共享 OTA 协议：`apps/shared/DEVICE_OTA_V1.txt`；受控维护入口：`apps/manager/docs/OTA-OPERATIONS.md`。
- 服务端内容接口：`apps/manager/manager/{reader.py,cloud.py,store.py}`；共享协议：`apps/shared/DEVICE_HTTP_V1.txt`。

## 长期设计约束

- `normal_release` 绑定固定 native SHA 和 release 索引，单改 `current` 不能激活任意新版；精确普通文件事务先提交 current，再提交 inittab，恢复根分区只读。
- NORMAL 候选绑定完整旧包闭包与新鲜根超级块 SHA；不能将一台设备的事务包或历史安装 pin 直接用于另一实际基线。
- helper 独立核验进程身份并只停止准确 native；保留服务和 USB。现有 helper 不重启、不提供自动跨启动回滚。
- 安装和休眠共用 `/user/pandanote/state/normal-install.lock`；独立编排者不能预先持锁后让 helper 再取同一锁。
- 当前 `/tmp` 为 20 MiB、`/run` 为 4 MiB；wire 上限 24 MiB、128 文件。下载应持久化到 `/user`，内容维护窗口为 30 秒。
- 电量为可选工厂曲线估计，充电状态可能未知；USB 连接不是充电证据。
- 管理端实现可生成签名并接收健康报告，但不代表真实设备已经接入或通过验收。设备端自动化和生产启用须分别核实；历史安装记录与当前公开命名迁移分别解释。
- 管理端 OTA 使用独立 OtaStore 和 schema 1 数据库，保持内容版本与显示 ACK 独立；云端凭证映射稳定设备 ID，本地单 token 须显式核验唯一绑定后才允许 OTA。
- 完整候选 manifest 及全部文件须留存为下一轮精确旧包；相同目标 native 不代表相同候选基线。事件按认证设备与 event_id 幂等，乱序不倒退，矛盾终态保留证据并暂停。
- 撤回停止新增授权与下载，不能即时撤销离线有效授权；服务端默认有效期 1 小时、协议上限 24 小时。取消任务不能释放未核对完成的设备事务，失败发布以更高 sequence 修复。

- API 与构建进程不能读取私钥；签名服务通过 Unix socket 和 SO_PEERCRED 核验独立身份，使用自己的闭包/wire 校验实现，不执行输入快照脚本。固定输入离线导入，worker 最终提交复核租约代次及发布/任务 revision。
- OTA 初始化、导入、接入、备份与恢复均通过 `python3 -m manager.ota_publish` 显式执行；未知版本关闭 OTA，reader 请求不自动建库。恢复副本须与独立签名账本核对 sequence 高水位；完整基线与恢复对象首版不自动删除。
- 灰度无报告期限从当前批次放行或显式恢复时计时，未来批次不提前超时；恢复未知目标保留 attempt 阶段和设备占用。本地已接入设备的配置与预览通过同一内容服务提供，不新增设备内容根或发布器。
- 受控恢复核对只由维护入口 `reconcile` 释放设备目标，保留事件和审计，不提供 Web 强制回退。对象读取校验摘要，chunk 对照文件属性封存防止同长度替换，异常触发全局隔离。

- 设备每日检测以持久化成功时间计时，离线不计为检查完成；安装须按下时已显示的同一 attempt/generation 的完整短点击确认，授权续期不能恢复已清除的确认。过期或冲突 nonce 清除后重新采集请求；未启用设备不启动 OTA 快速定时器，迟到接入复用已有刷新周期。最高接受序号同时绑定发布原文摘要，同序号只续期同一发布。
- OTA helper 的路径和摘要固定在首次受控接入配置，须与管理端登记一致；升级后的 worker 继续执行这份预安装 helper，不能自动选择下载包的新 helper。对应引导 release 必须保留，更换 helper 走受控接入。
- native 完整产物包含无 QtGui 的 worker、独立授权 helper 及 helper 来源清单，复用管理端原有 native 输入树；首次接入材料不能覆盖在用状态或重置高水位。跨启动保留 APPLYING 不确定性，健康预算不因同次启动 worker 重启而重置。

- 授权续期保留同一安装 attempt，并轮换 nonce/generation、清除确认；重启后的未安装阶段也须重新确认。`authorization.json` 原子绑定 request/offer，固定旧 helper 通过匹配的兼容导出读取；权威快照损坏不退读旧快照，历史已丢失 ID 的设备走受控核对。
- 准备交接为绑定 attempt、generation、boot_generation、native 身份的 90 秒租期；UI 撤销与 APPLYING 提交共用短时 `prepare.lock`，持久化取消证据防止 worker 复活后重放 ready。超时处理必须先于电源、唤醒与网络退避返回；不确定安装不得解锁、杀组或重装。服务只对已退出且持久态安全的 worker 每次启动最多重启三次。
- 管理端概览与任务详情共用有效事件选择，`observed` 与 `last_event` 分离；报告接收时间不代表执行顺序。有效阶段不因旧任务或迟到事件倒退，矛盾终态仍暂停；软件版本只从已确认完整基线对应的发布或同一首次接入基线取值，缺失不猜测。

- `apps/reader-shell/toolchain.py` 为 Mac/Linux 编译准备入口：固定基础镜像建立交叉编译器，编译物件核验 ABI，独立构建 MIPS TLS，再核验私有 Qt/原厂 SDK 后调用既有完整构建器。编译容器无设备、无网络、根只读，按当前用户运行；复制需保留属主，避免能力移除后无权访问工作目录。生成的 native 白名单包不能直接作为完整 NORMAL 固件派发；Web 制品上传仍需明确与受控输入、基线和签名的绑定。

## 接口与测试

- 编译准备定向入口：`python3 -m unittest discover -s apps/reader-shell/tests -p test_toolchain.py -v`，验证 SDK 摘要/路径、容器挂载/身份、并发互斥与 native 包边界；合成 SDK 夹具不代表真实原厂材料。
- 设备 OTA 主机定向入口：`python3 apps/reader-shell/tests/run_ota_host.py`，预置固定 MbedTLS 3.6.7 源码与 Qt5 Core/Gui/Widgets 开发库及 GUI 运行依赖（含 libmd4c）；运行生产验签、存储、恢复判定、worker 确认/推迟及真实 ReaderShell 准备交接状态机，不能代替目标 Qt4/MIPS 或真实闪存验收。
- 管理端定向测试：`tests/test_ota_{store,publish,reports,api,signer}.py`；前端 `src/ota.test.tsx`；`tests/test_ota_lifecycle.py` 在生成 worker 主机夹具后接入真实 P-256 签名向量，验证续期、重启恢复和两轮完整基线的合成报告闭环。主机两轮合成完整闭包与签名向量不代表真实闪存、重启或恢复验收。
- 现有 `normal-exact-upgrade-v1`、`PANDANOTE-UPGRADE-1` 与 `PANDANOTE-NORMAL-PROOF-1` 保持独立于 RAM 模式。
- 定向主机测试：`python3 -m unittest discover -s apps/reader-shell/deploy/normal_boot/tests -p test_upgrade_boundaries.py -v`，覆盖精确交接与超级块/remount 边界，测试前需存在该目录下的 `build/`。
- `test_upgrade.py` 依赖完整外部旧包 `PANDANOTE_UPGRADE_BASELINE`，公开源码不提供该输入；主机夹具不证明真实闪存断电持久性。

<!-- panda:module-meta:start -->
---
sync_uid: 01a1648c-d68d-7c85-867f-3eac238f1d28
module_id: 77
project_id: 19
slug: device-ota-upgrade
display_name: "Device OTA Upgrade"
agent: codex
source: auto
status: active
created_ts: 1792688313997
last_used_ts: 1792733323334
---
<!-- panda:module-meta:end -->

<!-- panda:module-knowledge:start -->
（本区块由 PandaDOS 引擎在每条 issue 结束时自动维护，只保留最近若干条，手工修改会被覆盖。）
- #20261022-377291c done · 在设备端研究一下如何实现 ota 自动升级 —— 目标：研究设备端 OTA 自动升级并输出可执行详细设计文档；改动 10 个文件
- #20261022-ff3291c done · 设计管理端 ota 升级 —— 目标：完成管理端 OTA 升级详细设计；改动 9 个文件
- #20261022-dc2691c done · ota 管理端实现 —— 目标：基于 apps/manager/docs/OTA-DESIGN.md 的设计实现全部任务 记住页面布局合理；改动 42 个文件
- #20261022-760591c done · 设备端ota 实现 —— 目标：实现设备端手动及每日版本检测、新版本确认提示和 OTA 升级闭环；改动 32 个文件
- #20261022-058b91c paused · 依次完成以下任务
<!-- panda:module-knowledge:end -->
