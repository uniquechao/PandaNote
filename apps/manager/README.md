# PandaNote 966U2 服务端

服务端负责日历读取、来源与设备范围、配置、背景图处理、不可变内容包、同步协调和设备 HTTP 接口。支持本地管理入口及分离的云管理/设备读取角色。

## 入口

- [开发与测试](docs/DEVELOPMENT.md)
- [本地与云角色部署](docs/DEPLOYMENT.md)
- [Web 端源码与构建](frontend/README.md)
- [共享协议](../shared/README.md)
- [项目总览](../../README.md)

## 代码结构

`manager/` 为 Python 源码：`app.py` 是本地管理入口，`cloud.py` 是云角色入口，`service.py`/`sync.py` 协调业务和同步，`store.py` 保存状态，`content.py` 生成内容，`caldav_provider.py` 负责来源读取，`reader.py`/`device_api.py` 提供设备相关边界。`tests/` 为回归测试，`requirements*.lock` 固定依赖版本。

Web 构建产物位于 `manager/static/`，由 Python 服务提供，不需要生产 Node 服务。私有数据目录、凭证和部署 profile 不属于源码。
