import { webview } from '@kit.ArkWeb';

// ============================================================
// ERP 服务器地址：改成你电脑的局域网 IP（电脑 IP 变了就改这里重新编译）
// 生产环境：http://192.168.3.7:8010（桌面版/后端一个端口全包）
// 端口说明：原为 8000，因本机 8000 被系统残留的端口代理规则占用
//          （见 desktop_app.py 注释），桌面端改监听 8010，鸿蒙壳随之同步。
// ============================================================
const ERP_URL: string = 'http://192.168.3.7:8010';

@Entry
@Component
struct Index {
  controller: webview.WebviewController = new webview.WebviewController();
  @State loading: boolean = true;
  @State loadFailed: boolean = false;

  build() {
    Column() {
      // 顶部加载进度条
      LoadingProgress()
        .visibility(this.loading ? Visibility.Visible : Visibility.Hidden)
        .width(40)
        .height(40)
        .margin({ top: 8, bottom: 4 })

      // 加载失败时给出提示和重试按钮
      if (this.loadFailed) {
        Column({ space: 12 }) {
          Text('无法连接 ERP 服务器')
            .fontSize(16)
            .fontColor('#475569')
          Text('请确认电脑已启动服务，且手机与电脑在同一 Wi-Fi')
            .fontSize(13)
            .fontColor('#94a3b8')
            .textAlign(TextAlign.Center)
          Button('重新加载')
            .onClick(() => {
              this.loadFailed = false;
              this.controller.loadUrl(ERP_URL);
            })
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .padding(24)
      } else {
        // ERP 网页容器
        Web({ src: ERP_URL, controller: this.controller })
          .layoutWeight(1)
          .domStorageAccess(true)      // 允许本地存储（登录态等）
          .javaScriptAccess(true)      // 允许 JavaScript
          .fileAccess(true)            // 允许文件上传（发票 OCR 用）
          .onlineImageAccess(true)     // 允许在线图片
          .mixedMode(webview.MixedMode.All)
          .onPageBegin(() => {
            this.loading = true;
          })
          .onPageEnd(() => {
            this.loading = false;
          })
          .onErrorReceive(() => {
            this.loading = false;
            this.loadFailed = true;
          })
          .onSslErrorEventReceive((event) => {
            // 局域网自签证书（mkcert）：开发阶段按“继续”放行
            // 正式部署 HTTPS 后，可改为 event.handler.handleCancel()
            event.handler.handleConfirm();
          })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#f8fafc')
  }
}
