# 架构与数据边界

管理服务以 `apps/manager/manager/app.py` 为本地入口；云角色入口是 `cloud.py`，其私有配置不进入公开仓库。`service.py` 协调业务，`sync.py` 管理同步，`store.py` 保存状态与版本，`content.py` 处理内容格式，`caldav_provider.py` 与 `caldav_expand.py` 处理日历来源和重复事件。

前端源码在 `apps/manager/frontend/src/`，构建输出进入 `manager/static/`。静态产物必须由对应源码重新构建；发布审查同时覆盖源码、生成 JavaScript、图片与 source map。

共享契约位于 `apps/shared/FORMAT.txt`、`BRIDGE.txt`、`DEVICE_HTTP_V1.txt`。合成测试夹具属于候选公开内容，但必须排除真实事件、账号、个人图片与生产配置。

运行数据包括 SQLite、来源快照、日历内容、设备身份和访问凭证。它们不能作为静态资源暴露或进入发行包。测试中出现的假 token 或测试专用密钥需逐项确认用途；不应靠全目录豁免绕过秘密扫描。

设备端实现位于 apps/reader-shell，包含原生界面、同步、显示、电源管理与无线辅助组件。原厂固件和提取运行库仍排除于公开发行；完整交叉构建需要单独准备并验证外部输入。
