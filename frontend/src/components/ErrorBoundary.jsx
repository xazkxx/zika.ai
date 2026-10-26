/**
 * ErrorBoundary —— 全局渲染兜底（2026-10-20）
 *
 * 起因：供应商档案里点某一条记录，整页**直接白屏，连报错都没有**。
 * 那是 React 18 的默认行为 —— 渲染期抛出的异常会把整棵树卸载掉，
 * 页面上什么都不剩，用户既看不到哪个字段坏了，也没法把信息发给我们。
 * 白屏是"最难排查的一类 bug"：它把证据一起销毁了。
 *
 * 这个组件的职责就一件事：**把崩溃变成一条可复制的错误信息**，
 * 而不是假装没崩。它不负责"修数据"，只负责"别再让用户对着白屏发呆"。
 *
 * 三个刻意的设计：
 *  ① `resetKey` 变了就清空错误 —— 用户在左侧点了另一条记录 / 换了页面，
 *     说明他想干别的了，不该继续顶着上一页的错误卡片。父组件传
 *     `selectedTab` + 当前行的 id 之类即可（见 App.jsx 的用法）。
 *  ② 错误详情默认折叠，只显示"哪一块坏了 + 一句话原因"。
 *     满屏 stack trace 对业务人员毫无意义，反而让人以为系统彻底废了。
 *  ③ 提供「复制错误信息」按钮 —— 客服/开发最需要的是这段文本，
 *     让用户自己截图念一遍是最容易丢信息的环节。
 */
import { Component } from 'react';

import './error-boundary.css';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null, copied: false };
    this.handleReset = this.handleReset.bind(this);
    this.handleCopy = this.handleCopy.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // 控制台留一份完整的：开发时按 F12 就能看到组件栈
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] 渲染崩溃：', error, info);
    this.setState({ info });
  }

  componentDidUpdate(prevProps) {
    // resetKey 变化 = 用户已经离开出问题的那一块，把错误清掉重新渲染
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null, info: null, copied: false });
    }
  }

  handleReset() {
    this.setState({ error: null, info: null, copied: false });
  }

  handleCopy() {
    const { error, info } = this.state;
    const text = [
      `时间：${new Date().toLocaleString()}`,
      `位置：${this.props.label || '应用'}`,
      `错误：${error && error.message ? error.message : String(error)}`,
      '',
      error && error.stack ? String(error.stack) : '',
      '',
      info && info.componentStack ? String(info.componentStack) : '',
    ].join('\n');
    // navigator.clipboard 在 http:// 非 localhost 下不存在（ERP 是 http://127.0.0.1 没事，
    // 但装到别的机器上用 IP 访问就会走 http，所以必须有 textarea 兜底）
    const fallback = () => {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand('copy');
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error(err);
      }
      document.body.removeChild(area);
      this.setState({ copied: true });
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        () => this.setState({ copied: true }),
        fallback,
      );
    } else {
      fallback();
    }
  }

  render() {
    const { error, info, copied } = this.state;
    if (!error) return this.props.children;

    const message = error && error.message ? String(error.message) : String(error);
    const stack = [error && error.stack, info && info.componentStack].filter(Boolean).join('\n\n');

    return (
      <div className="error-boundary" role="alert" data-error-boundary>
        <div className="error-boundary__card">
          <div className="error-boundary__badge" aria-hidden="true">
            !
          </div>
          <h2 className="error-boundary__title">这块页面出错了，没有正常显示</h2>
          <p className="error-boundary__lead">
            你的数据没有被改动，只是这一块内容没能画出来。
            可以点下面的「重新加载这一块」试试；如果反复出错，请把错误信息复制给管理员。
          </p>

          <p className="error-boundary__message" data-error-boundary-message>
            {message}
          </p>

          <details className="error-boundary__details">
            <summary>查看技术细节（给开发 / 客服看）</summary>
            <pre data-error-boundary-stack>{stack || '(无堆栈信息)'}</pre>
          </details>

          <div className="error-boundary__actions">
            <button type="button" className="primary-btn" onClick={this.handleReset} data-error-boundary-retry>
              重新加载这一块
            </button>
            <button type="button" className="secondary-btn" onClick={this.handleCopy} data-error-boundary-copy>
              {copied ? '已复制' : '复制错误信息'}
            </button>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => window.location.reload()}
              data-error-boundary-reload
            >
              刷新整个页面
            </button>
          </div>
        </div>
      </div>
    );
  }
}
