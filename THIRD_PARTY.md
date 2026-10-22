# 第三方依赖与素材

依赖版本来源：`apps/manager/requirements.lock`、`requirements-caldav.lock`、`frontend/package.json` 与 `package-lock.json`。正式发行需生成依赖清单并核实许可证及必要的版权声明，锁版本本身不等于许可证审查完成。

前端包括 React、Vite、TypeScript、Tailwind、shadcn/Base UI、Lucide、Motion、Zustand 等依赖；组件来源记录见 `apps/manager/frontend/nova-provenance.json`。该记录不能代替各依赖的许可证文本。

`frontend/src/public-assets/` 与静态资源中的图片、logo、字体和生成素材需核实来源与使用范围。没有授权证据的素材暂缓公开。

原厂固件、分区镜像、提取的 Qt 运行库、内核模块、SDK、USB 工具和第三方源码不在默认发行范围。即使文件不含凭证，也可能存在版权、保密或再分发约束。

当前未完成逐依赖和逐素材的许可证清单，因此尚不能宣称发行包已经通过开源合规审查。

## 本次发行记录

项目所有者已确认 logo 与宣传图片可公开。npm 锁文件清单见 docs/THIRD_PARTY_NPM.json，已安装前端依赖的许可与 NOTICE 文本汇总于 THIRD_PARTY_NOTICES.txt。少数开发依赖未附带独立许可文本，依赖清单仍保留其声明；它们不被复制为运行时源码。Python 软件包由各自发行包提供许可。

## 设备端第三方文件

设备端字体保留 WenQuanYi 的 Apache-2.0/GPL 字体许可与来源记录（本项目选择 Apache-2.0）；启动适配保留 LGPL 与链接例外；SHA-256 实现保留上游公有领域声明和本地修改记录；MbedTLS 配置与来源记录保留其 Apache/GPL 双许可声明。MIT 不替代这些文件的许可。未分发原厂提取库或设备固件。
