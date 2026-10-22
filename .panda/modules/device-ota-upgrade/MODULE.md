# Device OTA Upgrade

## 职责边界

设备端与管理端 OTA 自动升级的配套设计及生命周期约束，覆盖发布审批、逐设备授权、下载、安装编排、重启确认及恢复。管理端已实现独立 OTA 存储、受控导入、隔离签名、逐基线候选、设备接口及灰度页面，默认关闭；设备端 worker/helper 仍须按配套设计实现并通过真机核验；不负责内核、bootloader、GPT、分区布局或原始块升级。

## 关联源码路径

- 详细设计：`apps/reader-shell/docs/OTA-DESIGN.md`；部署入口：`apps/reader-shell/docs/DEPLOYMENT.md`。
- 管理端详细设计：`apps/manager/docs/OTA-DESIGN.md`；管理与设备认证边界：`apps/manager/manager/{app.py,cloud_auth.py,reader.py,cloud.py,fleet.py,device_api.py}`。
- 现有 NORMAL 事务：`apps/reader-shell/deploy/normal_boot/{normal_upgrade.py,upgrade_profile.py,apply_tool.c,upgrade_wire.h,upgrade_target.h}`。
- 启动与休眠：`apps/reader-shell/deploy/normal_boot/{service.in,early.in,policy.in,suspend.in,build.py}`。
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

## 接口与测试

- 管理端定向测试：`tests/test_ota_{store,publish,reports,api,signer}.py`；前端 `src/ota.test.tsx`。主机两轮合成完整闭包与签名向量不代表真实闪存、重启或恢复验收。
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
last_used_ts: 1792692913603
---
<!-- panda:module-meta:end -->

<!-- panda:module-knowledge:start -->
（本区块由 PandaDOS 引擎在每条 issue 结束时自动维护，只保留最近若干条，手工修改会被覆盖。）
- #20261022-377291c done · 在设备端研究一下如何实现 ota 自动升级 —— 目标：研究设备端 OTA 自动升级并输出可执行详细设计文档；改动 10 个文件
- #20261022-ff3291c done · 设计管理端 ota 升级 —— 目标：完成管理端 OTA 升级详细设计；改动 9 个文件
<!-- panda:module-knowledge:end -->
