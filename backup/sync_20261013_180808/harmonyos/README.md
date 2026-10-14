# ERP 鸿蒙端（HarmonyOS NEXT）

鸿蒙原生工程（DevEco Studio / ArkTS），采用 **WebView 壳 + 原生框架** 的方式承载现有 ERP 网页界面：
最快落地、与网页端功能完全同步，后续可逐步把常用页面改写成原生 ArkUI。

## 适用设备

- 鸿蒙 NEXT（HarmonyOS 5.0+）手机 / 平板 / 2in1
- 老鸿蒙（4.x 及以前，兼容安卓 APK）请直接用浏览器或 PWA 方式访问

## 运行前准备（一次性）

1. 电脑端服务已启动（后端 8000 + 前端 5173，见主 README）
2. 安装 **DevEco Studio 5.0+**（免费）：
   https://developer.huawei.com/consumer/cn/deveco-studio/
3. 注册华为开发者账号（免费），用于自动签名
4. 鸿蒙手机：设置 → 系统 → 开发者选项 → 打开"USB 调试"
   （开发者选项：设置 → 关于手机 → 连续点击版本号 7 次）

## 运行步骤

1. 打开 DevEco Studio → **Open Project** → 选择本目录 `harmonyos`
2. 等待右下角 Sync 完成（首次会下载 HarmonyOS SDK）
3. 手机 USB 连接电脑，弹窗允许调试
4. 点击顶部 **Run ▶** 按钮，选择你的手机设备
5. 首次运行会引导配置自动签名（登录华为账号，一路确认）

## 修改 ERP 服务器地址

电脑 IP 变化时，编辑：

`entry/src/main/ets/pages/Index.ets`

顶部常量：

```ts
const ERP_URL: string = 'https://192.168.3.7:5173';
```

## 证书说明

局域网自签证书（mkcert）已由应用内 SSL 处理自动放行，无需在手机上安装 CA 证书。
正式部署公网 HTTPS 后，建议改为拒绝放行：

```ts
event.handler.handleCancel();
```

## 后续优化方向

- 常用页面原生化（ArkUI）：首页看板、审批、库存查询
- 接收系统级推送通知（审批提醒）
- 离线缓存（复用 PWA 缓存策略）
- 对接鸿蒙 AI 能力（意图框架、小艺）
