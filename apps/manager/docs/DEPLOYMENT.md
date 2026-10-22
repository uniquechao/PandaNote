# 服务端部署

## 本地运行

完成开发文档中的依赖安装后，在仓库根目录执行：

```sh
PYTHONPATH=apps/manager apps/manager/.venv/bin/python -m manager.app --port 8767 --data-root apps/manager/data
```

访问 `http://127.0.0.1:8767/`，Ctrl-C 停止。入口绑定本机，默认提供者未配置时应显示不可用状态；本地启动不意味着真实日历账号已连接。

## 云角色

云管理和设备读取使用同一代码库的不同角色。以下仅是参数形式，不能直接作为生产部署配置：

```sh
PYTHONPATH=apps/manager apps/manager/.venv/bin/python -m manager.cloud --profile /absolute/private/profile.json --data-root /absolute/private/data --role admin --port 8767
PYTHONPATH=apps/manager apps/manager/.venv/bin/python -m manager.cloud --profile /absolute/private/profile.json --data-root /absolute/private/data --role reader --port 8768
```

必须先按 `manager/cloud_auth.py` 中的字段和校验准备私有 profile。配置父目录权限要求 0700，配置文件要求 0600；账号、密码哈希和设备凭证哈希不可入库。生产域名、HTTPS 终止、反向代理 Host/Origin 与专用客户端地址头须与代码中的信任约束匹配。不要直接向公网开放未配置的本地管理入口。

发布前备份私有数据，确认回退版本和静态资源一致；发布后分别验证管理登录、日历读取、设备读取和显示确认。此文档没有提供真实生产 profile、服务器地址或自动部署凭证。

## 私有 profile 字段

| 字段 | 要求 |
| --- | --- |
| `origin` | 自有 HTTPS origin，只有 scheme 与主机名，不附路径或用户名 |
| `prefix` | `/pandanote` |
| `admin_username` | 1–64 字符的字母、数字、下划线、点或连字符 |
| `admin_password_hash` | 由 `manager.cloud_auth.hash_password` 生成，不能填明文密码 |
| `device_credentials` | 设备标识到 SHA-256 凭证摘要的映射；原始 token 仅私有保存并配置到目标设备 |
| `session_seconds` | 300–28800 秒 |

`CloudProfile` 可进行结构验证，`CloudProfile.from_file` 同时检查路径和文件权限。不要在 shell 命令参数、日志、截图或公开配置中暴露原始密码及 token。为每个设备使用不同凭证，撤销时同时更新服务端和目标设备。

## 验收与回退

- 本机服务：页面与同源 API 可访问，未配置来源时显示真实不可用状态。
- 云管理：HTTPS 登录、来源配置、事件读取和旧版本保留行为分别验证。
- 设备角色：以目标设备凭证读取 manifest、校验资源并回报 ACK；不使用浏览器管理会话替代设备凭证。
- 回退：停止本次进程，恢复兼容的代码、静态资源和私有数据备份，再核对版本与来源读取时间。

本次 Cookie 命名统一后，本机浏览器需要重新建立会话；不迁移旧浏览器会话。云 profile 的秘密字段不会因品牌更名自动轮换。
