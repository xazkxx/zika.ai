/**
 * 静态体检：找出"被调用/被引用但本文件没定义"的标识符。
 *
 * 为什么需要这个脚本（真实事故）：
 *   2026-10-20 清理「导入导出」死代码时，`const authHeaders = ...` 因为紧挨在
 *   被删代码块的第一行，被一起删掉了。后果是**整个主界面白屏**
 *   （ReferenceError: authHeaders is not defined）。
 *   而 `vite build` 照样成功 —— esbuild 只做语法/打包，**不做未定义变量检查**；
 *   日常也没人开控制台。于是"构建通过 + 页面全白"这种最坏组合发生了。
 *
 * 判定策略（宁可漏报，绝不误报 —— 误报会让这个脚本被无视）：
 *   只盯两种高置信度形态：
 *     ① `foo(...)` —— 标识符作为 CallExpression 的 callee；
 *     ② `<Foo />` —— 大驼峰 JSX 组件。
 *   并且要满足"本文件里没有同名绑定"。绑定来源包括：
 *     import、函数/类声明、const/let/var（含解构）、函数参数、catch 参数。
 *   ⚠️ 对象键、字符串、属性访问 `obj.foo` 的 foo 都不算 —— 这是上一版误报的根源。
 *
 * 作用域：**按文件算，不按块算**。"本文件任何地方定义过 foo"就算有定义，
 *   所以函数 A 里调用、函数 B 里定义的情况会漏报。这是有意的取舍：
 *   漏报的后果是"下次真出事还得靠浏览器"，误报的后果是"这个脚本被关掉"。
 *
 * 跑法：
 *   node scripts/check_undefined_refs.cjs
 * 退出码：0 = 干净，1 = 有可疑引用（逐条打印 文件:行 名字）
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'frontend', 'src');
const parser = require(path.join(ROOT, 'frontend', 'node_modules', '@babel', 'parser'));

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

function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    node.forEach((child) => walk(child, visit));
    return;
  }
  if (typeof node.type !== 'string') return;
  visit(node);
  for (const key of Object.keys(node)) {
    if (key === 'loc' || key === 'start' || key === 'end') continue;
    const value = node[key];
    if (value && typeof value === 'object') walk(value, visit);
  }
}

/** 从解构/参数模式里抽绑定名。 */
function namesFromPattern(pattern, out) {
  if (!pattern) return;
  switch (pattern.type) {
    case 'Identifier':
      out.add(pattern.name);
      break;
    case 'ObjectPattern':
      pattern.properties.forEach((prop) => {
        if (prop.type === 'RestElement') namesFromPattern(prop.argument, out);
        else namesFromPattern(prop.value, out);
      });
      break;
    case 'ArrayPattern':
      pattern.elements.forEach((el) => namesFromPattern(el, out));
      break;
    case 'AssignmentPattern':
      namesFromPattern(pattern.left, out);
      break;
    case 'RestElement':
      namesFromPattern(pattern.argument, out);
      break;
    default:
      break;
  }
}

function analyseFile(file) {
  const code = fs.readFileSync(file, 'utf8');
  const ast = parser.parse(code, {
    sourceType: 'module',
    plugins: ['jsx', 'classProperties', 'optionalChaining', 'nullishCoalescingOperator'],
  });

  const bound = new Set();
  const suspects = [];

  // ── 第一遍：绑定 ──
  walk(ast.program, (node) => {
    switch (node.type) {
      case 'ImportDeclaration':
        node.specifiers.forEach((spec) => bound.add(spec.local.name));
        break;
      case 'FunctionDeclaration':
      case 'FunctionExpression':
      case 'ArrowFunctionExpression':
        if (node.id) bound.add(node.id.name);
        node.params.forEach((p) => namesFromPattern(p, bound));
        break;
      case 'VariableDeclarator':
        namesFromPattern(node.id, bound);
        break;
      case 'ClassDeclaration':
      case 'ClassExpression':
        if (node.id) bound.add(node.id.name);
        break;
      case 'CatchClause':
        if (node.param) namesFromPattern(node.param, bound);
        break;
      case 'ImportDefaultSpecifier':
      case 'ImportNamespaceSpecifier':
      case 'ImportSpecifier':
        if (node.local) bound.add(node.local.name);
        break;
      default:
        break;
    }
  });

  // ── 第二遍：高置信度引用 ──
  walk(ast.program, (node) => {
    // ① foo(...)
    if (node.type === 'CallExpression' && node.callee && node.callee.type === 'Identifier') {
      suspects.push({ name: node.callee.name, line: node.loc.start.line, kind: '调用' });
    }
    // ② <Foo />
    if (node.type === 'JSXOpeningElement' && node.name && node.name.type === 'JSXIdentifier') {
      const name = node.name.name;
      if (/^[A-Z]/.test(name)) {
        suspects.push({ name, line: node.loc.start.line, kind: '组件' });
      }
    }
    // ③ { foo } 简写属性 —— 这是最容易漏的一类：
    //    删掉 `const [excelBusy, setExcelBusy] = useState(false)` 之后，
    //    ctx 里的 `setExcelBusy,` 只是**裸标识符**，既不是调用也不是组件，
    //    构建不报错、检查器也看不见，直到页面渲染到那个对象才炸。
    //    真实事故里就是这样连炸两块（authHeaders 之后是 setExcelBusy）。
    if (node.type === 'ObjectProperty' && node.shorthand && node.key && node.key.type === 'Identifier') {
      suspects.push({ name: node.key.name, line: node.loc.start.line, kind: '简写属性' });
    }
    // ④ 数组里的裸标识符：[foo, bar] —— ctx 导出列表常见形态
    if (node.type === 'ArrayExpression') {
      node.elements.forEach((el) => {
        if (el && el.type === 'Identifier') {
          suspects.push({ name: el.name, line: el.loc.start.line, kind: '数组元素' });
        }
      });
    }
  });

  const missing = [];
  const seen = new Set();
  for (const item of suspects) {
    const { name, line, kind } = item;
    if (bound.has(name) || GLOBALS.has(name)) continue;
    if (seen.has(name)) continue; // 同一个名字只报一次，附带首次出现行
    seen.add(name);
    missing.push({ name, line, kind });
  }
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
  console.log('⚠️ 发现"被调用/被当成组件，但本文件没有定义"的标识符：');
  console.log(report.join('\n'));
  console.log(`\n合计 ${bad} 处。这类问题 vite build **不会**报错，但运行时会白屏。`);
  process.exit(1);
}

console.log(`OK  ${files.length} 个源文件，被调用的标识符全部都有定义。`);
process.exit(0);
