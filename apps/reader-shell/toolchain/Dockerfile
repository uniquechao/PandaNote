# 固定官方基础镜像；Intel 与 Apple Silicon Mac 统一使用 linux/amd64 编译器。
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc-mipsel-linux-gnu g++-mipsel-linux-gnu binutils-mipsel-linux-gnu \
    libc6-dev-mipsr6el-cross python3 ca-certificates \
    && mkdir -p /opt/pandanote /work/pandanote/app-development-research/qt-stock-sysroot \
      /work/pandanote/app-development-research/minimal-qt/include \
      /work/pandanote-native-completion /work/pandanote-normal-apply \
      /work/pandanote-normal-upgrade /work/pandanote-normal-suspend \
      /work/pandanote-ota-upgrade /work/pandanote-rtc-probe \
    && dpkg-query -W -f='${Package}\t${Version}\n' > /opt/pandanote/packages.txt \
    && rm -rf /var/lib/apt/lists/*
COPY probe.py /opt/pandanote/probe.py
# 只运行主机编译工具；不安装 QEMU，不执行生成的 MIPS 物件。
CMD ["sleep", "infinity"]
