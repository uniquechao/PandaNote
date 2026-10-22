# 服务端开发与测试

要求 Python 3.11+。以下命令在仓库根目录执行：

```sh
python3 -m venv apps/manager/.venv
apps/manager/.venv/bin/python -m pip install -r apps/manager/requirements.lock -r apps/manager/requirements-caldav.lock
mkdir -p apps/manager/build
apps/manager/.venv/bin/python -m pytest apps/manager/tests --basetemp=apps/manager/build/pytest -q
```

测试使用合成数据；部分测试会绑定临时 loopback 端口。TLS 测试需要 OpenSSL CLI，并在测试临时目录生成短期证书和密钥。

内容与协议变化同时检查设备消费者。日历错误应保留旧内容，不应伪造成功读取时间；设备获取、显示和 ACK 分别记录。修改 Web 源码后按 Web 文档重建静态资源。
