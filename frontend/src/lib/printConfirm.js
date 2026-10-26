/**
 * 打印二次确认 —— 模块级单例（2026-10-18，需求 3）
 *
 * 为什么不做成 React Context：
 *   打印入口散在 20+ 个页面/组件里，绝大多数都走 `ctx.printPdf`（App.jsx:1595 那一个函数），
 *   但也有例外 —— `StatementEditor` 自带一份 printPdf（它直接 saveBlob，不走 ctx）。
 *   如果做成 Context，就得保证 Provider 包住每一个调用点，而 App 的 return 是一棵
 *   上万行的树，加包裹层既容易漏、又可能影响布局。单例 + 一个宿主组件：
 *     · 任何模块 `import { confirmPrint }` 就能用，不需要知道自己在树的哪一层；
 *     · 宿主只挂一次，UI 与业务解耦。
 *
 * 关键边界：**宿主没挂载时直接放行**（`return Promise.resolve(true)`）。
 *   打印是"用户明确点了按钮"的动作，绝不能因为"确认框弹不出来"而静默什么都不做 ——
 *   那会变成最难排查的一类 bug（点了没反应，控制台也不报错）。
 *   确认框是**防误触**，不是权限闸口。
 */

let impl = null;

/** 由宿主组件注册；返回注销函数（组件卸载时调用，避免 HMR 后残留旧闭包） */
export function registerPrintConfirm(fn) {
  impl = fn;
  return () => {
    if (impl === fn) impl = null;
  };
}

/**
 * 弹确认框。
 * @param {{ name?: string, title?: string, hint?: string }} options
 *        name  —— 要打印的单据名（文件名），显示在确认框里让用户知道打的是哪张
 * @returns {Promise<boolean>} true = 用户确认，可以继续原打印逻辑
 */
export function confirmPrint(options = {}) {
  if (!impl) return Promise.resolve(true);
  return impl(options);
}

/**
 * 危险动作二次确认（2026-10-20，反审核/红冲拆分）。
 *
 * 和 `confirmPrint` 共用同一个宿主弹窗，只是换一套文案与按钮：
 *   · `danger: true`  → 确认按钮走 danger-btn 红样式，文案是「确认红冲」而不是「确认打印」
 *   · `requireReason` → 弹窗里多一个「原因」输入框，必须填了才能确认
 *
 * 为什么复用宿主而不是再做一个组件：弹窗类东西一多，遮罩层级就会打架
 * （谁在上面、点遮罩关哪个）。一个宿主、一种结算方式，永远只有一个框。
 *
 * ⚠️ 与 confirmPrint 相反：**宿主没挂载时这里返回 false（拒绝）**。
 *   打印弹不出确认框只是少一次确认；红冲弹不出确认框却直接冲掉库存和应收，
 *   那是不可逆的账务事故 —— 宁可"点了没反应"，也不能"静默把钱冲了"。
 *
 * @returns {Promise<{ ok: boolean, reason: string }>}
 */
export function confirmDanger(options = {}) {
  if (!impl) return Promise.resolve({ ok: false, reason: '' });
  return Promise.resolve(impl({ ...options, danger: true })).then((result) => {
    // 宿主对普通确认回 boolean（true/false），对危险确认回 {ok, reason}
    if (result && typeof result === 'object') {
      return { ok: Boolean(result.ok), reason: String(result.reason || '') };
    }
    return { ok: Boolean(result), reason: '' };
  });
}
