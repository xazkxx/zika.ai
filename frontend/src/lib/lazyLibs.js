/**
 * 重型第三方库的**按需加载**入口（B4b，2026-10-27）
 * ============================================================================
 * 为什么要有这个文件
 * ------------------
 * B4 把 47 个页面拆成路由级 chunk 之后，入口文件里还剩三块"钉子户"：
 *   · xlsx        ~860 KB（导出 Excel 才用）
 *   · pdfjs-dist  ~640 KB（读 PDF 发票文本层才用）
 *   · tesseract.js ~65 KB（图片 OCR 才用）
 * 这三个包都在 `App.jsx` 顶部静态 import，于是**每个用户首屏都要为它们付流量**，
 * 哪怕他这辈子只点过"运营概览"。改成 `await import()` 之后：首屏不认识它们，
 * 点"导出 / 识别发票"的那一刻才去下载对应的 chunk。
 *
 * 用法（调用点必须是 async）：
 *
 *     const XLSX = await loadXLSX();
 *     const pdfjsLib = await loadPdfjs();
 *     const Tesseract = await loadTesseract();
 *
 * 规矩
 * ----
 *  1. **只在这里写 `import('xlsx')` 这类动态导入**。散落到各处的话，vite 会重复
 *     判断、缓存也各管各的，同一个包装两遍的风险还会回来。
 *  2. 加载结果缓存：同一个库第二次调用直接用已 resolve 的 promise，不会重复下载。
 *  3. 失败时**把缓存清掉**再抛 —— 断网/发版后 chunk 404 这类失败是一次性的，
 *     不能让用户"刷新一次仍然永远失败"。
 *  4. 不要用 `import('xlsx')` 的返回值直接当 `XLSX` 用：几个包都是 CJS 产物，
 *     vite 装在 `default` 上还是摊到命名空间上取决于 cjs-module-lexer 能不能识别，
 *     所以下面统一做了一次兼容拆包。
 */

/** 包一层：resolve 前置空缓存，失败可重试 */
function memoize(loader) {
  let promise = null;
  return () => {
    if (!promise) {
      promise = Promise.resolve()
        .then(loader)
        .catch((error) => {
          promise = null;
          throw error;
        });
    }
    return promise;
  };
}

/**
 * xlsx（SheetJS）—— 导出 Excel 用。
 * `utils` 挂在 default 上（CJS），所以优先取 default。
 */
export const loadXLSX = memoize(async () => {
  const mod = await import('xlsx');
  return mod && mod.default && mod.default.utils ? mod.default : mod;
});

/**
 * pdfjs-dist —— 读 PDF 发票文本层用。
 *
 * worker 路径**必须**在拿到库之后再设：`GlobalWorkerOptions` 是库自己的对象，
 * 以前这行写在 App.jsx 模块顶层，等于"为了设一个静态属性把整个 pdfjs 拉进首屏"。
 * 移到这里之后，只有真的要解析 PDF 时才付这个代价。
 */
export const loadPdfjs = memoize(async () => {
  const mod = await import('pdfjs-dist');
  const pdfjsLib = mod && mod.getDocument ? mod : mod.default;
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url,
  ).toString();
  return pdfjsLib;
});

/**
 * tesseract.js —— 图片发票 OCR 用（识别中文+英文）。
 * v5 的入口是 default 导出，带 `recognize`。
 */
export const loadTesseract = memoize(async () => {
  const mod = await import('tesseract.js');
  return mod && mod.default && mod.default.recognize ? mod.default : mod;
});
