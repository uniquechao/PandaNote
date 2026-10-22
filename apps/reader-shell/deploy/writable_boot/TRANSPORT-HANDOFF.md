# Independent writable RAM transport checkpoint

Base `025b49e`，只新增 `transport.py` 及针对它的 fake USB 测试/证据。没有修改旧 `ram_boot.py`、旧只读 load/readiness/证明或 writable candidate。首次准备 manifest 为 `b9b2cf13ecf3a027ff2d25cf2b33aff8b1db2ae7109e22f925bcfa65b91961d6`（该次实际加载后未出现 ADB；已由下述 stat 修正版取代），`hardware_execution_permitted=false` 不被修改；实际执行由新入口明确 promotion。

## 最小接续命令（根代理审查后执行）

中央项目根目录：

```sh
python3 apps/reader-shell/deploy/writable_boot/transport.py
python3 apps/reader-shell/deploy/writable_boot/transport.py --list-candidates
python3 apps/reader-shell/deploy/writable_boot/transport.py --execute-once --readiness <本次根审查的0600文件.json>
```

第一条完全离线，输出实际 source/plan SHA；第二条为显式 USB 枚举，在共享互斥锁内读 descriptors，不打开任何 target handle；根代理取得唯一 candidate 的 vendor/product/bus/address/ports 后写本次 readiness。worker 只执行了第一条与 fake USB 测试，未运行枚举/执行分支。

readiness 须为 0600 regular file，内容字段：

```text
schema: 1
profile: writable-development-v1
scope: one bounded writable-development RAM boot
execution_promotion: reviewed independent transport entrypoint for one RAM attempt
review_verdict: no actionable defects remain
reviewed_epoch: 本次实际审查Unix秒，最多30分钟且不能在未来
physical_cycle_confirmed: true（根代理实际确认本次物理BootROM状态）
observed_cpu_info: X2000
attempt_id: 本次唯一字母数字/横线ID，1至64字符
expected_usb: 第二条命令实际取得的唯一vendor/product/bus/address/ports对象
manifest_sha256: 11a16c58eca78d52c6d3a4c76196ae6c8ecf6271c42e337c8b746a937867ac53
plan_sha256: 第一条命令实际输出
source_sha256: 第一条命令实际输出的完整对象
```

这不是预生成的批准文件。根代理需在独立审查完成后填入实际数据。每份 readiness 固定 `evidence/writable-boot-<attempt_id>.jsonl`；0600、O_EXCL 创建，已存在即拒绝。锁忙或任何失败都消耗该次 journal，绝不自动重试、删除或换 journal 复用同次物理尝试。

## 实施与验证

- 只 AST 提取 hash-pinned 原实现的 inert Segment/digest；不导入或改写旧 load_plan/readiness/LibUSB first-match。
- 新 libusb adapter 先枚举全部 descriptors，必须唯一匹配 a108:eaef，并与 readiness 中的完整物理路径相等，再对该具体 device 调 `libusb_open`。不用 `open_device_with_vid_pid`。设备消失/描述符失败/多个匹配直接停止。
- 共享锁源码 SHA 与实际 canonical origin 都固定，不能换一份拷贝绕过面板锁。执行前重新核对 readiness/source/plan；锁获取后再次核对且 readiness 内容必须与捕获值相同。
- 固定六段：DDR参数、DDR-only SPL、c7af内核、wrapper、argv、bootstrap。开始与 SPL 后都要求 CPU_INFO 恰为裸 `X2000`。RAM OUT 只允许 control 1..5、每块≤65536 B、精确计数；无存储/erase/reset API。
- 120秒整体 deadline，libusb 控制/块传输 timeout 使用剩余预算，外部传入 deadline 也不能扩大120秒；每次 I/O 前后检查。USB枚举/open/claim和文件fsync属于OS同步操作，无法在内核卡死时承诺严格墙钟中断；没有背景重试。
- fake USB + fake libusb **15/15** 通过；原始 RED10项缺实现失败保留。覆盖六段/controls、初始和SPL后CPU错、shortwrite、deadline、caller bytearray变化、唯一开设备/物理路径错/只枚举不开设备、底层count、timeout预算、readiness变旧/源或plan变化、O_EXCL/0600、锁忙不开USB，以及实际pinned flock源码在独立 fixture lock 上的互斥。所有 fixture 都没有访问实际共享锁/USB。
- 默认 dryrun 与 Python byte compilation 通过。此工具请求 RAM handoff 后仍不证明 Linux 启动、p3/p9已挂载或应用已就绪；下一步由根代理核对新 USB serial、实际 cmdline/内核/PID1和本次operator交接，不发布旧 RO 证明。

已有 BusyBox `380811...` 的历史受限执行证据证明 setsid applet 存在，由根代理另行确认；本 worker 没有重复执行厂商 ELF。

## 首次物理启动的兼容性修正

Cycle1 六段 RAM 装载成功，但未出现 ADB，未发布 payload/receipt，也未执行持久挂载。新 PID1 在 gadget 创建前调用不存在的 BusyBox `stat`，会确定性进入 halt；原厂独立 stat 同样不存在。已改用已执行核验存在的 `LC_ALL=C ls -ldn`，固定检查数字前列，拒绝符号链接、扩展/特殊权限、错误属主与硬链接；policy 与 radio guard 同步修正。

当前 manifest `11a16c58eca78d52c6d3a4c76196ae6c8ecf6271c42e337c8b746a937867ac53`，PID1 `16ee0bac0ce0f10e9338847b87a6c4ac64d35c1c062c19f4cbcf28e46a61de6d`，argv 3902 B，commandline 3879 B，bootstrap 1440 B。内核及 DDR 输入保持不变。此为待再次物理启动的修正版，不宣称已启动。

隐藏 stat 的 native Linux fixtures 原先 7 项失败，修正后 16 项通过；实际历史受限 BusyBox list 提取 274 applets，确认 ls/setsid 存在、stat 缺失。没有为本修正重新执行厂商二进制或访问设备。
