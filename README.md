# PandaNote 966U2

面向电子墨水设备的日程终端与内容管理系统。服务端读取日历并生成可校验的内容包，Web 端提供配置与预览，设备端负责同步、展示和低功耗交互。

**当前阶段：开发预览版。** 仓库包含三端源码、共享协议及测试；完整设备构建仍依赖外部工具链、目标 Qt 头文件和运行库，公开源码不能单独从零生成完整固件。

## 主要功能

- 日历接入：通过 CalDAV 读取日历，处理重复事件、来源配置与设备范围。
- 配置与预览：管理日历来源、裁剪背景图、预览内容并查看设备工作区。
- 内容发布与同步：生成不可变版本，经设备 HTTP 接口分发并校验；分别记录获取、显示和确认状态，同步失败时保留旧内容。
- 设备运行：原生界面与导航、电子墨水刷新、物理按键、电池与休眠管理、系统校时、Wi-Fi 和蓝牙辅助组件。
- 服务部署：支持本地管理，以及分离的云管理与设备读取角色。

## 技术栈与目录

| 目录 | 技术与职责 | 文档入口 |
| --- | --- | --- |
| `apps/reader-shell/` | C++ / Qt，MIPS 设备界面、同步与运行组件 | [设备端说明](apps/reader-shell/README.md) |
| `apps/manager/manager/` | Python 3.11+、FastAPI、Uvicorn、SQLite、Pillow，日历接入与内容管理 | [服务端说明](apps/manager/README.md) |
| `apps/manager/frontend/` | React、TypeScript、Vite、Tailwind CSS、Zustand，配置与预览 | [Web 端说明](apps/manager/frontend/README.md) |
| `apps/shared/` | 内容包、日历桥接及设备 HTTP 契约，合成测试数据 | [共享协议](apps/shared/README.md) |
| `docs/` | 架构、发行、复核及第三方说明 | [架构文档](docs/ARCHITECTURE.md) |
| `.github/workflows/` | 持续集成与秘密扫描 | [贡献规范](CONTRIBUTING.md) |

## 数据流与运行边界

日历数据源 → 服务端 → 不可变内容包 → 设备校验、展示与确认；Web 端负责配置和预览。

内容包由 `content.ini`、`background.png` 和 `SHA256SUMS` 组成。服务端发布成功不等于设备已经刷新。协议变化需同时核对服务端生产者、Web 预览和设备消费者。

Web 生产构建输出到 `apps/manager/manager/static/`，由 Python 服务提供，无需独立的生产 Node 服务。运行数据、SQLite、来源快照、设备身份和凭证应与静态资源隔离。

## 开发与验证

具体依赖、命令和环境条件以各端文档为准：

- 服务端：[开发与测试](apps/manager/docs/DEVELOPMENT.md) · [部署](apps/manager/docs/DEPLOYMENT.md)。依赖由 `requirements*.lock` 固定，测试使用 pytest。
- Web 端：[开发与测试](apps/manager/frontend/docs/DEVELOPMENT.md) · [部署](apps/manager/frontend/docs/DEPLOYMENT.md)。依赖由 `package-lock.json` 固定，提供 Vitest、类型检查和生产构建命令。
- 设备端：[开发与测试](apps/reader-shell/docs/DEVELOPMENT.md) · [部署与迁移](apps/reader-shell/docs/DEPLOYMENT.md)。部分策略测试可在主机运行，其他测试依赖 Qt、交叉工具链或专用环境。

既有公开整理记录记载服务端 221 项测试、Web 端 28 项测试及类型检查和生产构建通过；设备主机验证范围见[发行记录](docs/RELEASE.md)。这些是历史记录，本次文档总结未重跑测试、完整交叉编译或真机验收。CI 状态应以当前工作流运行结果为准。

## 当前进展与注意事项

三端已有实现及测试，设备端包含安装、回退与运行保护辅助程序。近期任务涉及设备 OTA 自动升级研究与详细设计；当前模块和过程页尚未记录完成结果，不能视为已经具备完整 OTA 自动升级能力。

设备目标 ABI 为 MIPS32r2、小端、o32、NaN2008。原厂固件、提取运行库、设备镜像和生产配置不随源码发布。已有设备目录与配置需要按部署文档迁移；真机加载、刷写和恢复前应核对目标设备、外部输入与回退条件。

生产密钥、设备凭证、日历账号、个人事件、原厂镜像和原始运行日志不得提交。测试使用合成数据；TLS 测试密钥在运行时临时生成。

## 参与、许可与安全

[贡献规范](CONTRIBUTING.md) · [安全政策](SECURITY.md) · [维护规则](GOVERNANCE.md) · [第三方说明](THIRD_PARTY.md) · [发行记录](docs/RELEASE.md) · [仓库复核记录](docs/REPOSITORY_AUDIT.md)

自有代码采用 [MIT](LICENSE)。第三方字体、启动适配、组件和库保留各自许可，见 [THIRD_PARTY.md](THIRD_PARTY.md) 与 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。
