# Device OTA Upgrade

## 职责边界

设备端 OTA 自动升级的设计与生命周期约束，覆盖发布验证、下载、安装编排、重启确认及恢复。当前交付为设计文档，OTA 自动化组件尚未实现；不负责内核、bootloader、GPT、分区布局或原始块升级。

## 关联源码路径

- 详细设计：`apps/reader-shell/docs/OTA-DESIGN.md`；部署入口：`apps/reader-shell/docs/DEPLOYMENT.md`。
- 现有 NORMAL 事务：`apps/reader-shell/deploy/normal_boot/{normal_upgrade.py,upgrade_profile.py,apply_tool.c,upgrade_wire.h,upgrade_target.h}`。
- 启动与休眠：`apps/reader-shell/deploy/normal_boot/{service.in,early.in,policy.in,suspend.in,build.py}`。
- 设备网络及电源：`apps/reader-shell/{sync.h,sync.cpp,tls.cpp,main.cpp,standbypolicy.h,battery.h,battery_posix.cpp}`。
- 服务端内容接口：`apps/manager/manager/{reader.py,cloud.py,store.py}`；共享协议：`apps/shared/DEVICE_HTTP_V1.txt`。

## 长期设计约束

- `normal_release` 绑定固定 native SHA 和 release 索引，单改 `current` 不能激活任意新版；精确普通文件事务先提交 current，再提交 inittab，恢复根分区只读。
- NORMAL 候选绑定完整旧包闭包与新鲜根超级块 SHA；不能将一台设备的事务包或历史安装 pin 直接用于另一实际基线。
- helper 独立核验进程身份并只停止准确 native；保留服务和 USB。现有 helper 不重启、不提供自动跨启动回滚。
- 安装和休眠共用 `/user/pandanote/state/normal-install.lock`；独立编排者不能预先持锁后让 helper 再取同一锁。
- 当前 `/tmp` 为 20 MiB、`/run` 为 4 MiB；wire 上限 24 MiB、128 文件。下载应持久化到 `/user`，内容维护窗口为 30 秒。
- 电量为可选工厂曲线估计，充电状态可能未知；USB 连接不是充电证据。
- OTA 签名、worker、设备协议和健康确认是拟新增能力，不能作为现有部署事实。历史安装记录与当前公开命名迁移分别解释。

## 接口与测试

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
last_used_ts: 1792689051019
---
<!-- panda:module-meta:end -->
