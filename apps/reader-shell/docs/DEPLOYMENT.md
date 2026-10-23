# 设备端构建与部署

## 发布输入

需要经过验证的目标交叉编译环境、Qt 头文件和运行库、启动适配基线、设备型号与恢复条件。原厂镜像、运行库提取件、生产 token 和私有同步 profile 不随公开源码提供。

受控环境中的构建入口：

```sh
python3 apps/reader-shell/build_tls.py --fetch
python3 apps/reader-shell/build.py
```

这些底层命令依赖工具链和设备 SDK。新机器可先用下文的 `toolchain.py image` 建立编译器环境；设备原厂运行库和匹配的 Qt SDK 仍须独立核验。目标程序不能在 Mac 或编译容器中直接执行。构建输出应包含 ELF、源码/产物校验信息、相邻 assets 和第三方许可。

## 生命周期源码

`deploy/normal_boot/` 包含正常启动相关辅助组件；`deploy/` 其余目录包括安装、回退、隔离运行和保护逻辑，`stage_ram.py` 为受控 RAM 验证入口。部分流程还依赖本地未公开的固件输入和验证记录，应先逐项满足脚本的前提条件。

正式操作前确认精确设备与外部输入，备份现有有效版本，检查恢复路径；再按受控流程暂存、校验、激活并分别验证显示、物理键、网络、唤醒刷新和休眠。不要跳过原有只读、存储保护或触摸固件保护来绕过失败检查。

本次公开整理只导入源码、脱敏路径和执行部分主机测试，没有连接、加载、刷写、复位或重启设备，也没有重新验收完整固件。

## 本次命名迁移

当前公开版本采用统一的新命名空间：`/user/pandanote/`、`/run/pandanote-normal/`、`/tmp/pandanote-*`，本地应用状态头为 `PANDANOTE-WORDS-1`、`PANDANOTE-NOTES-1`、`PANDANOTE-DRAFT-1`；构建容器及工作路径使用 `pandanote-*`。服务端本机 Cookie 名为 `pandanote_session`。

这属于兼容性变化。更新既有安装时应：

1. 停止目标应用与对应辅助组件，私有备份原配置、状态和可回退版本。
2. 在新命名空间准备配置和权限，重新配置设备身份与凭证；不要假定早期安装的路径或 USB 标识已经改变。
3. 对词卡、笔记和草稿先在副本上按当前解析器验证格式。本仓库没有提供自动转换工具，不支持直接覆盖旧状态文件；不要删除原文件。
4. 让应用、无线辅助进程、休眠辅助进程与启动脚本使用同一版本，再在受控环境中验证。
5. 验证失败时回退整套组件及其原始状态。源码统一更名未对现有实体设备执行迁移。

需要在外部参考目录中准备的新路径包括 `pandanote-analysis/app-development-research/qt-stock-sysroot/` 与 `pandanote-analysis/app-development-research/minimal-qt/`。其文件来源、ABI 与校验值仍需独立验证；仅修改目录名不构成输入验证。

## OTA 检测与升级

[设备端 OTA 自动升级详细设计](OTA-DESIGN.md) 定义基于精确 NORMAL 普通文件事务的发布签名、设备编排、安装重启和恢复流程。设备端已接入手动/每日检测、逐次升级确认、独立 worker 与授权 helper、重启及健康确认。首次启用仍须受控引导部署可信公钥、稳定身份、私有配置和完整基线；`deploy/normal_boot/prepare_ota.py` 只生成接入材料。充电状态未知时推迟安装；主机测试不代表真机闪存、重启或救援验收。

## 本轮 OTA 修复的验收边界

先生成 `tests/run_ota_host.py` 的 worker/UI 主机夹具，再执行管理端 `tests/test_ota_lifecycle.py`，可验证真实签名、同 attempt 续期、迟到报告及两轮完整基线的合成闭环。这里模拟健康事件身份，没有执行目标安装或真实重启。

2026-10-23 首次在当前环境尝试目标构建时缺失 `pandanote-analysis/app-development-research/minimal-qt/build-support/start.S`、目标 `build/tls-provenance.json` 及运行中的 `pandanote-mips-dev` 可信容器；后续已建立独立交叉编译镜像并完成真实 MIPS TLS 库编译；仍缺设备匹配的原厂 SDK，UI、worker 与 helper 的完整目标构建未通过。不得为绕过构建前提改用主机产物接入设备。

真实设备仍须在受控测试环境完成：可信首次接入；手动和每日检测；等待超过授权期后再次确认；下载中续期与网络恢复；ready 后安全电源变化、worker 退出或失活；安装重启及第二轮完整基线；已获明确授权的测试设备断电及 USB 救援、草稿保留。当前未操作设备，也未启用生产 OTA；真实断电测试须先核实设备、备份和救援条件并取得明确授权。

## Mac 首次验证与后续只编译交付

用户确认的流程为：首次下载源码到连接设备的 Mac，完成实际设备验证；之后在本地代理环境开发并只编译、静态核验产物，再经管理端受控导入、审批签名和设备 OTA 交付。编译器不需要 USB，也不会执行生成的 MIPS 程序。设备仍按现有策略检测和逐次确认升级。

本轮代码交接由用户在 Mac 使用已保留的材料安排目标编译和设备验证；管理网站地址及传输方式待用户补充，再接实际上传流程。当前没有上传或上线操作，目标构建与真机结果须以该环境生成的记录为准。

在仓库根目录执行，Mac 需先具备 Docker Desktop、Python 3.10 以上和 Git：

```sh
python3 apps/reader-shell/toolchain.py image
python3 apps/reader-shell/toolchain.py probe
python3 apps/reader-shell/toolchain.py tls --fetch
```

`image` 从固定官方 Ubuntu 基础镜像建立 `pandanote-mips-toolchain:1`；软件包版本和镜像 ID 写入构建记录，标签不是永久身份。`probe` 实际编译 C++ 物件并检查 ELF32、小端、MIPS32r2、o32、NaN2008 与 64 位浮点寄存器，仅验证编译器；它不表示 Qt ABI、完整固件或真机验收通过。`tls` 在无网络、无设备的临时容器内编译固定 MbedTLS；显式 `--fetch` 只在主机获取并校验公开源码。容器平台固定为 `linux/amd64`，Apple Silicon 使用 Docker Desktop 的平台模拟；参考 [Docker 多平台说明](https://docs.docker.com/build/building/multi-platform/)。当前实际验证平台为 Linux amd64，Mac 路径仍由首次本机验证确认。

设备 SDK 是与原厂运行环境匹配的 Qt 头文件、运行库和启动适配参考，不是 Mac 系统 SDK。若旧工程保留了 `pandanote-analysis/`，将其作为参考根目录使用，不必重建或修改原厂库；也可以放在本工程忽略的 `external-inputs/` 下。目录至少包括：

```text
external-inputs/pandanote-analysis/
  app-development-research/
    minimal-qt/include/QtCore/、QtGui/
    minimal-qt/build-support/{start.S,entry.h,csu.cpp,libio-init.c}
    qt-stock-sysroot/original-library-provenance.json
    qt-stock-sysroot/ 中来源清单绑定的原厂运行库
  qt-sdk-source/qt-4.7.4/  固定提交的 Git 工作树
```

没有这些材料时，先在 Mac 的原工程或原厂备份中定位，不得用通用 Ubuntu 库、复制当前源码冒充独立启动参考，或修改摘要来放行。SDK 不需要设备 token、账号、私钥或用户数据。

```sh
python3 apps/reader-shell/toolchain.py doctor --reference external-inputs
python3 apps/reader-shell/toolchain.py compile --reference external-inputs --fetch
```

`doctor` 汇总所有缺失或不匹配项到 `apps/reader-shell/build/toolchain/sdk-check.json`，不会连接设备。`compile` 只在 SDK 前置检查通过后启动专用 `pandanote-mips-dev`：无网络、无设备、根文件系统只读，以当前用户身份运行；只读挂载 Qt 头文件和原厂库，工作目录单独可写。已有同名容器必须身份、镜像、挂载和隔离条件一致，工具不会接管或删除其他容器。文件复制保留当前用户属主，避免无特权编译器无法读取或写入物件。共享工作目录的编译和打包操作互斥。

随后按既有入口生成目标 TLS、UI、worker、固定 helper 及来源清单，并编译 suspend helper；全程不运行这些产物。成功后按 native manifest 的文件白名单和摘要生成 `apps/reader-shell/build/toolchain/native-<native-sha256>.tar`，不带配置、凭据或整个工作目录。构建记录均位于 `apps/reader-shell/build/toolchain/`。

这个 tar 是原生构建交接包，不是可直接刷写的完整固件，也没有自动上传或自动启用生产的行为。管理端现有入口接受完整 NORMAL 目标及受控输入目录，仍需匹配的完整基线、radio/suspend 与硬件参考，经候选闭包核验、审批和签名后才派发。当前 Web 页面没有通用固件上传接口；将此原生包接入网页上传和发布流程需要单独明确制品与受控输入的绑定规则，不能把普通文件上传成功当作 OTA 发布成功。
