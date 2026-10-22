# OTA 管理端维护

实现入口为 `manager/ota_store.py`、`ota.py`、`ota_api.py`、`ota_publish.py`、`ota_worker.py`、`ota_signer.py`、`ota_verify.py`。设备协议见 `apps/shared/DEVICE_OTA_V1.txt`。OTA 默认关闭，已有内容库不迁移、不合并。本文是可执行维护接口说明，不代表生产已启用或真机验收已完成。

## 进程和权限

admin、reader、worker 使用同一个显式 `<data-root>/ota`，目录 0700、普通文件 0600、拒绝链接。API 与构建 worker 使用无私钥权限的服务身份。签名服务必须使用不同 UID，启动时禁止把自己的 UID 列为客户端；私钥及独立签名审计账本保存在签名身份的 0700 目录中，均为 0600。

在当前 0700 对象布局下，可由受约束的 root 签名服务读取无特权 API 用户拥有的 OTA 根；签名服务自身代码与 Python 环境必须由维护者控制，不能由 API 或构建用户修改。签名服务只读取数据库与对象，使用独立协议代码校验完整闭包，不执行发布输入中的快照脚本。若使用专门的非 root 签名身份，需由运维配置等效的只读挂载与访问权限，并验证目录约束，不能直接把对象目录放宽为共享可写目录。

Unix socket 放在独立的受控运行目录，目录禁止其他用户访问，组允许 API/worker 连接，socket 为 0660。双方使用 SO_PEERCRED 核验 UID；API 还核验 socket 类型、属主和权限。OpenSSL 是签名服务的运行依赖，固定算法为 P-256；不使用 HTTP 进程内私钥或浏览器导入私钥。

以下命令从 `apps/manager` 执行；路径替换为维护者实际受控目录，示例不自动创建真实凭据。

```sh
python3 -m manager.ota_publish --root <data-root>/ota init
python3 -m manager.ota_publish --root <data-root>/ota baseline <完整旧包目录> --snapshot <受审仓库快照>
python3 -m manager.ota_publish --root <data-root>/ota import <固定输入目录>
python3 -m manager.ota_publish --root <data-root>/ota enroll <接入配置文件>
python3 -m manager.ota_publish --root <data-root>/ota verify
python3 -m manager.ota_signer --root <data-root>/ota --key <签名私钥> --key-id <引导公钥ID> --ledger <私钥目录>/ledger.sqlite3 --socket <运行目录>/signer.sock --client-uid <API用户UID> --client-uid <worker用户UID> --socket-gid <客户端组GID>
python3 -m manager.ota_worker --root <data-root>/ota
```

`init` 是 schema 1 的显式初始化/版本核验入口；只有新 OTA 库，没有旧内容库迁移路径。未知 schema 禁用 OTA，不猜测迁移。启动 reader 不自动建库。worker 启动先核验对象，单次运行可加 `--once`；构建子进程预算 10 分钟，每 30 秒续租 120 秒租约，最多三次暂时故障重试。快照只由维护者离线导入，构建进程从持久对象还原快照、原生包、参考材料、radio 与 suspend helper；固定代码入口调用 `build`，不接受 HTTP 命令或脚本上传，不调用 ADB 或设备写入。

## 固定输入和接入配置

导入目录恰按以下语义准备：`input.json`、`snapshot/`（保留仓库相对路径）、`native/`、`reference/`、`radio/`、`suspend/`、`target/`。`target` 是固定发布的完整 NORMAL 包，含完整 manifest 与全部 `files/`；所有文件权限须匹配 manifest。原生源码、模板、硬件参考与工具必须满足已有 NORMAL 构建器的摘要约束；不能以空夹具或不完整清单代替。导入树总量及单个文件受界限限制，快照排除 `.git`、`node_modules` 和 `__pycache__`，所有符号链接拒绝。

`input.json` 字段为 `schema=1,model,channel,version,native_sha256,suspend_helper_sha256,toolchain_sha256,radio_binary`。`radio_binary` 为 `radio/` 内相对路径；工具链摘要作为受审来源标识纳入构建键。输出的输入摘要供 Web 选择，不向页面返回本机路径。候选产物必须逐项等于 target 的发布文件清单；若不同基线导致文件变化，则稳定拒绝，需要维护者准备适配输入。

接入配置字段为 `device_id,credential_sha256,model,channels,ota_abi=1,helper_sha256,bootstrap_version,baseline,unique_credential_verified=true`。凭据摘要是现有 Bearer token 的 SHA-256；共享 token 不可登记到多台设备。baseline 必须先导入并通过现有 `capture_old` 完整索引核验。登记不修改云端原凭据映射；云端请求仍须通过现有 profile，撤销凭据立即阻止新请求。设备 ID 与历史记录不可重新分配。

在 `<data-root>/ota-config.json` 写入 0600 私有配置：

```json
{"schema":1,"enabled":true,"root":"<data-root>/ota","signer_socket":"<运行目录>/signer.sock","signer_uid":0,"key_id":"<引导公钥ID>","local_device_id":"<仅本地部署需要的设备ID>"}
```

`root` 和 `signer_socket` 使用绝对路径；root 必须恰为当前 data-root 下的 ota。云端可省略 `local_device_id`。两类进程使用同一 data-root；配置无效、库不存在或版本未知时 OTA 不启用，内容服务继续。更改配置后重启对应服务，普通启动不自动给任何设备分配任务。上线前仍须核验签名根、完整基线及一台真机的两轮升级和受控恢复；本 issue 不执行生产启用。

## 管理行为

Web 支持选择受控输入创建草稿、校验、审批签名与不可逆撤回；任务固定设备范围及批次，默认一台试点再放行其余设备。所有写请求带 Idempotency-Key 和现有会话/CSRF，已有对象变更带 revision。每批健康上报后至少观察 24 小时才可推进。 无报告期限从对应批次启动、推进放行或管理员显式恢复时计时，尚未放行的批次不提前判未知；恢复未知目标继续保留已有 attempt 与设备占用。未知、回退、恢复或证据冲突均保留证据，不以内容 ACK 或下载完成判成功。

取消任务后已授权目标仍占用设备，直到合法 HEALTHY 或受控恢复核对；首版不提供 Web 清除告警、强制恢复或远程回退入口。维护者实际完成恢复并核对完整基线后，可通过 `ota_publish reconcile` 提交 `device_id,target_id,baseline,recovery_verified=true,reason` 的私有配置，释放已核对目标并保留原事件与审计；此操作不能替代设备恢复。任务和设备详情提供 candidate、bundle、输入快照与构建标识供维护核对。失败发布使用更高 sequence 修复。暂停允许旧有效授权下载；撤回和取消停止后续 chunk，但无法撤销设备已离线持有的有效签名。

## 备份、恢复与审计

停用 OTA 写入后，通过 SQLite backup API 创建独立副本与完整对象清单：

```sh
python3 -m manager.ota_publish --root <data-root>/ota backup <不存在的备份目录>
python3 -m manager.ota_publish --root <不存在的恢复目录> restore <备份目录> --signing-ledger <独立签名审计账本>
python3 -m manager.ota_publish --root <恢复目录> verify
```

恢复入口拒绝覆盖现有目录，核验数据库、外键、对象摘要与高水位，并将序号提高到签名账本以上。维护者在停用状态下核验副本后切换至配置要求的路径，禁止在线合并或删除历史授权。备份对象表即完整被引用对象清单；首版不自动 GC 完整旧包、候选或恢复证据。发现对象损坏先保留现场并停用 OTA；同构建键不同产物会写入全局隔离状态。

`ota_audit` 保存审批、任务操作、导入、接入、构建与授权，签名进程另存原始签名审计；不记录 token、Cookie、nonce 原文或私钥到日志。可从任务/队列查看构建失败、未知状态与恢复告警。构建至少保留 1 GiB 可用空间并预留 256 MiB，超限停止新构建，不影响内容服务。
