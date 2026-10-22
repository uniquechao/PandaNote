# Web 端开发与测试

已验证 Node 25.8.2 / npm 11.11.1。在 `apps/manager/frontend/` 执行：

```sh
npm ci --ignore-scripts
npm test
npm run typecheck
npm run build
```

测试使用合成状态和数据，不代表真实日历或设备可用。主界面位于 `src/App.tsx`，设备工作区和来源交互由相应组件管理；界面品牌为 PandaNote 966U2。

裁剪、权限、错误提示和预览一致性变化需运行相关回归。浏览器字体渲染不承诺与 Qt 电子墨水界面像素一致。
