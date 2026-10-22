# 设备端开发与测试

设备端入口见 [README](../README.md)。根目录 `.cpp`/`.h` 为原生实现，`tests/` 为主机与受控离线验证，`radio/` 为独立无线组件。

部分策略测试只要求 Python 3、C++ 编译器和 `nm`，可在仓库根目录运行：

```sh
mkdir -p apps/reader-shell/build
cd apps/reader-shell/tests
python3 -m unittest test_standbypolicy test_startup_retry test_timeanchor test_standby_runtime test_suspendrequest test_battery test_einkrefresh test_powerkeys_boundary test_local_apps_tool -v
```

这组测试执行源码中的策略或带替代系统调用的边界，不访问真实设备。完整 Qt/目标 ABI、TLS、协议和离线镜像测试需要额外环境，见各测试入口。

交叉构建入口为 `build.py`、`build_tls.py`。工具链、目标 Qt 头文件、受控运行库与启动基线需另行准备，不能把主机测试通过写成完整设备构建成功。修改休眠、时钟、输入、网络或显示行为后，实际硬件验收应单独记录。
