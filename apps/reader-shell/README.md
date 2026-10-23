# PandaNote 966U2 设备端

原生 C++ / Qt 电子墨水界面与设备运行组件。公开源码包括：日程与内容校验、界面导航、显示刷新、同步与 TLS、系统时钟、电池、物理按键、休眠请求、Wi-Fi 和蓝牙辅助组件，以及安装与回退流程的自有源码。

## 目录

- 根目录 C++：应用、设备接口与内容消费实现。
- `radio/`：无线与蓝牙辅助进程及离线测试。
- `deploy/`：设备生命周期、安装、回退与休眠辅助程序源码。
- `tests/`：主机回归、协议测试与受控离线执行入口。
- `build-support/`：启动适配和版权声明。
- `third_party/`：SHA-256 实现、TLS 配置与许可、来源记录。
- `assets/`：字体、自产背景及对应许可和来源记录。

## 构建条件与边界

完整设备构建依赖 MIPS 交叉编译器、目标 Qt 头文件、经过验证的运行库与启动基线。原厂提取运行库、固件、设备镜像和历史隔离执行镜像不随源码发布；因此当前公开仓库尚不能单独从零生成完整固件。

`toolchain.py image` 可从零建立隔离交叉编译器，`probe` 只编译并核验目标物件，`tls --fetch` 可独立生成目标 TLS 库；`doctor` 和 `compile` 接入已校验的设备 SDK。Mac 首次验证与之后只编译交付的步骤见 [部署与构建说明](docs/DEPLOYMENT.md)。

`build.py` 和 `build_tls.py` 保留底层交叉编译与校验入口。目标 ABI 是 MIPS32r2、小端、o32、NaN2008；不要用主机编译结果替代目标二进制。编译脚本依赖已有受控编译容器，TLS 显式获取入口为 `python3 apps/reader-shell/build_tls.py --fetch`。尚未在本次公开目录重跑完整交叉编译。

需要外部输入的脚本通过 `PANDANOTE_REFERENCE_ROOT`  指定本地参考目录；少量专用审计入口使用 `PANDANOTE_SDIO_MODULE`、`PANDANOTE_UPGRADE_BASELINE`、`PANDANOTE_TRIAGE_TOOL`。这些输入不应提交到公开仓库。

此公开版本统一了运行目录、IPC 标识和构建命名。已有设备状态不可直接覆盖，部署前按迁移说明准备新配置和状态。对外产品名称为 PandaNote 966U2。源码公开不代表自动迁移设备上的目录或配置，详见 [部署与迁移](docs/DEPLOYMENT.md)。

## 主机验证

有 Python 3 与 C++ 编译器时，可在仓库根目录运行部分独立的策略测试：

```sh
python3 -m unittest discover -s apps/reader-shell/tests -p 'test_standbypolicy.py'
python3 -m unittest discover -s apps/reader-shell/tests -p 'test_startup_retry.py'
```

其他测试可能依赖 Qt、交叉工具链、外部输入或专用隔离执行环境，不承诺普通主机直接全量通过。不要直接执行未知目标 ELF。

## 安装与设备操作

`deploy/` 和 `stage_ram.py` 提供流程实现与保护逻辑，不是无条件执行的快速安装指令。任何真机加载、刷写、复位、重启、网络配置或恢复操作，均需先核对设备、外部输入与回退条件。本次公开整理未执行这些操作。

## 许可证

自有代码采用根目录 MIT；第三方启动适配、字体与库遵循各自版权及许可，见对应子目录。MIT 不覆盖第三方文件的原有许可。
