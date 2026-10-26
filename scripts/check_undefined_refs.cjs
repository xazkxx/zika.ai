/**
 * 静态体检：找出"被调用/被引用但本文件没定义"的标识符。
 *
 * 为什么需要这个脚本（真实事故 ×2）：
 *   ① 2026-10-20 清理「导入导出」死代码时，`const authHeaders = ...` 因为紧挨在
 *      被删代码块的第一行，被一起删掉了。后果是**整个主界面白屏**
 *      （ReferenceError: authHeaders is not defined）。
 *   ② 2026-10-27 B4b 把 xlsx / pdfjs-dist / tesseract.js 改成按需 import，静态 import
 *      删了，但 `appCtx` 里的 `Tesseract,` / `XLSX,` 两个**简写属性**忘了删 ——
 *      对象字面量在 render 期间求值 → ReferenceError → 又一次整屏白。
 *      当时这个脚本**没报**：旧版按"文件里出现过同名定义就算有定义"判断，而
 *      `readImageInvoiceText` 里正好有局部 `const Tesseract = await loadTesseract()`，
 *      把顶层漏掉的键洗白了。
 *   而 `vite build` 照样成功 —— esbuild 只做语法/打包，**不做未定义变量检查**；
 *   日常也没人开控制台。于是"构建通过 + 页面全白"这种最坏组合反复发生。
 *
 * 判定策略（宁可漏报，绝不误报 —— 误报会让这个脚本被无视）：
 *   只盯四种高置信度形态：
 *     ① `foo(...)` —— 标识符作为 CallExpression / OptionalCallExpression 的 callee；
 *     ② `<Foo />` —— 大驼峰 JSX 组件；
 *     ③ `{ foo }` —— 对象字面量的**简写属性**（事故 ② 的形态）；
 *     ④ `[foo, bar]` —— 数组里的裸标识符。
 *   判定"有没有定义"用 **@babel/traverse 的真实作用域链**（`scope.hasBinding`），
 *   而不是"这个文件里某处出现过"：
 *     - 函数内局部 `const Tesseract = ...` **不能**给顶层的 `{ Tesseract }` 背书；
 *     - `import`、函数/类声明、`const/let/var`、函数参数、catch 参数、解构都算绑定；
 *     - 解构模式里的 `{ foo }` 是**声明**，不是引用，直接跳过。
 *   ⚠️ 字符串、属性访问 `obj.foo`、JSX `<Foo.Bar />` 都不算。
 *
 * 跑法：
 *   node scripts/check_undefined_refs.cjs
 * 退出码：0 = 干净，1 = 有可疑引用（逐条打印 文件:行 名字 类型）
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'frontend', 'src');
const NM = path.join(ROOT, 'frontend', 'node_modules');
const parser = require(path.join(NM, '@babel', 'parser'));
const traverseMod = require(path.join(NM, '@babel', 'traverse'));
const traverse = traverseMod.default || traverseMod;

// 全局白名单：浏览器 / ES 内置里会被"当函数调用"的那些
const GLOBALS = new Set([
  'fetch', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
  'requestAnimationFrame', 'cancelAnimationFrame', 'queueMicrotask', 'structuredClone',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent', 'decodeURIComponent',
  'encodeURI', 'decodeURI', 'alert', 'confirm', 'prompt', 'getComputedStyle', 'matchMedia',
  'Object', 'Array', 'String', 'Number', 'Boolean', 'Math', 'JSON', 'Date', 'RegExp',
  'Error', 'TypeError', 'RangeError', 'Map', 'Set', 'WeakMap', 'WeakSet', 'Symbol',
  'BigInt', 'Promise', 'Intl', 'URL', 'URLSearchParams', 'FormData', 'Blob', 'File',
  'FileReader', 'Headers', 'Request', 'Response', 'AbortController', 'Image', 'Audio',
  'ResizeObserver', 'IntersectionObserver', 'MutationObserver', 'DOMParser', 'XMLSerializer',
  'TextEncoder', 'TextDecoder', 'print', 'require', 'define',
  // base64 / 转义的老全局（本项目下载通道与 token 解析真在用）
  'atob', 'btoa', 'escape', 'unescape',
  // JSX 里会当组件用、但其实是全局的
  'Fragment', 'StrictMode',
]);

function analyseFile(file) {
  const code = fs.readFileSync(file, 'utf8');
  const ast = parser.parse(code, {
    sourceType: 'module',
    // 各级调用都在用：jsx / 可选链 / 空值合并 / 对象展开 / 顶层 await / 动态 import
    plugins: [
      'jsx', 'classProperties', 'classPrivateProperties', 'classPrivateMethods',
      'optionalChaining', 'nullishCoalescingOperator', 'objectRestSpread',
      'dynamicImport', 'topLevelAwait', 'importMeta',
    ],
    errorRecovery: false,
  });

  const missing = [];
  const seen = new Set();

  /** 高置信度引用点：只做"这个作用域链里有没有同名绑定"这一件事。 */
  const check = (p, name, kind) => {
    if (!name || GLOBALS.has(name)) return;
    if (p.scope.hasBinding(name, true)) return; // true = 不把真正的全局当绑定
    const key = name + '@' + p.node.loc.start.line;
    if (seen.has(key)) return;
    seen.add(key);
    missing.push({ name, line: p.node.loc.start.line, kind });
  };

  traverse(ast, {
    // ① foo(...)
    CallExpression(p) {
      const callee = p.node.callee;
      if (callee && callee.type === 'Identifier') check(p, callee.name, '调用');
    },
    // ①' foo?.(...)
    OptionalCallExpression(p) {
      const callee = p.node.callee;
      if (callee && callee.type === 'Identifier') check(p, callee.name, '调用');
    },
    // ② <Foo />
    JSXOpeningElement(p) {
      const name = p.node.name;
      if (name && name.type === 'JSXIdentifier' && /^[A-Z]/.test(name.name)) {
        check(p, name.name, '组件');
      }
    },
    // ③ { foo } 简写属性 —— 2026-10-27 白屏事故的形态：
    //    静态 import 删了，`appCtx` 里的 `Tesseract,` / `XLSX,` 还在，
    //    render 时求值 → ReferenceError。旧版因为文件里有同名局部变量而漏报。
    ObjectProperty(p) {
      if (!p.node.shorthand) return;
      if (!p.node.key || p.node.key.type !== 'Identifier') return;
      // 解构里的简写是「声明」不是「引用」：`const { foo } = ctx`
      if (p.findParent((pp) => pp.isObjectPattern())) return;
      check(p, p.node.key.name, '简写属性');
    },
    // ④ 数组里的裸标识符：[foo, bar] —— ctx 导出列表常见形态
    ArrayExpression(p) {
      p.node.elements.forEach((el) => {
        if (el && el.type === 'Identifier') check(p, el.name, '数组元素');
      });
    },
  });

  return missing;
}

function collectFiles(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      collectFiles(full, out);
    } else if (/\.(jsx?|mjs)$/.test(entry.name) && !entry.name.includes('.bak')) {
      // 测试/工具文件不进打包产物，`undefined` 之类的字面量是刻意写的边界样本，
      // 在这里报警只会把真问题淹掉（2026-10-21：*.test.mjs 里 4 条假红）
      if (/\.(test|spec)\.(mjs|jsx?|ts)$/.test(entry.name)) continue;
      out.push(full);
    }
  }
  return out;
}

const files = collectFiles(SRC);
let bad = 0;
const report = [];

for (const file of files) {
  let missing;
  try {
    missing = analyseFile(file);
  } catch (err) {
    console.log(`[解析失败] ${path.relative(ROOT, file)}: ${String(err.message).slice(0, 140)}`);
    bad += 1;
    continue;
  }
  if (missing.length) {
    bad += missing.length;
    const rel = path.relative(ROOT, file);
    for (const item of missing) {
      report.push(`  ${rel}:${item.line}  ${item.name}  (${item.kind})`);
    }
  }
}

if (report.length) {
  console.log('⚠️ 发现"被调用/被当成组件/被简写引用，但作用域里没有定义"的标识符：');
  console.log(report.join('\n'));
  console.log(`\n合计 ${bad} 处。这类问题 vite build **不会**报错，但运行时会白屏。`);
  process.exit(1);
}

console.log(`OK  ${files.length} 个源文件，高置信度引用全部都有定义（作用域级检查）。`);
process.exit(0);
