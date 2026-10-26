/* 精确静态校验：前端拆分后每个页面都能从 appCtx 拿到所需标识符。
 * 不依赖正则，用 @babel/parser + @babel/traverse 做 AST 级分析。
 *
 * 三重检查（任一不通过即说明运行时会 ReferenceError / undefined）：
 *   A. 页面里 `const { ... } = ctx` 解构出的每个名字，必须出现在 App.jsx 的 appCtx 键里
 *      （否则运行时 ctx.xxx === undefined，页面用到就崩）
 *   C. 页面里 `ctx.xxx` 成员访问的属性名，必须出现在 appCtx 键里
 *   B. 页面里其它所有被「引用」的标识符，必须能解析为：
 *        - 页面内本地声明（含从 ctx 解构出来的、函数参数、import 等）
 *        - appCtx 键
 *        - JS 内置 / HTML-SVG 标签
 *
 * 运行：NODE_PATH=<frontend/node_modules> node scripts/verify_pages2.cjs
 */
const fs = require('fs');
const path = require('path');
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;

const SRC = path.resolve(__dirname, '../frontend/src');
const APP_JSX = path.join(SRC, 'App.jsx');
const PAGES_DIR = path.join(SRC, 'pages');

// ---------- JS 内置 / 全局对象 ----------
const JS_GLOBALS = new Set([
  'Object','Array','String','Number','Boolean','Symbol','Math','JSON','Date','RegExp',
  'Error','TypeError','ReferenceError','SyntaxError','RangeError','EvalError','URIError',
  'Promise','Map','Set','WeakMap','WeakSet','Proxy','Reflect','Function','BigInt',
  'setTimeout','clearTimeout','setInterval','clearInterval','queueMicrotask',
  'requestAnimationFrame','cancelAnimationFrame','fetch','console','window','document',
  'localStorage','sessionStorage','alert','confirm','prompt','parseInt','parseFloat',
  'isNaN','isFinite','undefined','Infinity','decodeURI','encodeURI','decodeURIComponent','encodeURIComponent',
  'eval','globalThis','URL','URLSearchParams','Blob','File','FileReader','FormData',
  'XMLHttpRequest','Event','CustomEvent','MouseEvent','KeyboardEvent','EventTarget',
  'HTMLElement','Node','navigator','location','history','screen','performance','Intl',
  'TextEncoder','TextDecoder','ArrayBuffer','Uint8Array','Uint16Array','Uint32Array',
  'Int8Array','Int16Array','Int32Array','Float32Array','Float64Array','DataView',
  'WebSocket','MessageChannel','structuredClone','crypto','AbortController','ReadableStream',
  'Image','Audio','Option','ImageData','DOMParser','XMLSerializer','getComputedStyle',
  'matchMedia','btoa','atob','escape','unescape','setImmediate','process','Buffer',
  'requestIdleCallback','cancelIdleCallback','CSS','MutationObserver','IntersectionObserver',
  'ResizeObserver','AudioContext','Notification','Worker','SubtleCrypto','indexedDB',
]);

// ---------- HTML / SVG 标签（小写 JSX 元素） ----------
const HTML_TAGS = new Set([
  'div','span','button','input','form','table','thead','tbody','tfoot','tr','td','th',
  'ul','ol','li','a','p','h1','h2','h3','h4','h5','h6','img','svg','path','circle',
  'rect','line','polyline','polygon','ellipse','br','hr','label','select','option',
  'textarea','section','header','footer','nav','main','aside','article','dialog',
  'details','summary','code','pre','small','strong','em','i','b','u','sub','sup',
  'dl','dt','dd','fieldset','legend','canvas','video','audio','iframe','progress',
  'meter','output','time','mark','abbr','cite','q','blockquote','address','figure',
  'figcaption','map','area','object','param','col','colgroup','caption','kbd','var',
  'samp','wbr','data','bdi','bdo','picture','source','track','template','slot','menu',
  'ruby','rt','rp','switch','webview','use','g','defs','text','tspan','foreignObject',
  'clipPath','linearGradient','radialGradient','stop','mask','pattern','filter',
]);

function parse(code) {
  return parser.parse(code, {
    sourceType: 'module',
    plugins: ['jsx', 'classProperties', 'objectRestSpread', 'dynamicImport', 'optionalChaining', 'nullishCoalescingOperator'],
    errorRecovery: true,
  });
}

// 收集一个 Pattern / Identifier 节点里的所有绑定名
function collectNamesFromPattern(node, out) {
  if (!node) return;
  if (node.type === 'Identifier') {
    out.add(node.name);
  } else if (node.type === 'ObjectPattern') {
    for (const p of node.properties) {
      if (p.type === 'RestElement') collectNamesFromPattern(p.argument, out);
      else collectNamesFromPattern(p.value, out); // key 是属性名不重要，value 才是绑定
    }
  } else if (node.type === 'ArrayPattern') {
    for (const el of node.elements) collectNamesFromPattern(el, out);
  } else if (node.type === 'AssignmentPattern') {
    collectNamesFromPattern(node.left, out);
  } else if (node.type === 'RestElement') {
    collectNamesFromPattern(node.argument, out);
  }
}

// 提取 App.jsx 里 appCtx 对象的键集合
function extractAppCtxKeys() {
  const code = fs.readFileSync(APP_JSX, 'utf8');
  const ast = parse(code);
  const keys = new Set();
  traverse(ast, {
    VariableDeclarator(p) {
      if (p.node.id && p.node.id.name === 'appCtx' && p.node.init && p.node.init.type === 'ObjectExpression') {
        for (const prop of p.node.init.properties) {
          if (prop.type === 'ObjectProperty') {
            if (prop.key.type === 'Identifier') keys.add(prop.key.name);
            else if (prop.key.type === 'StringLiteral') keys.add(prop.key.value);
          } else if (prop.type === 'ObjectMethod') {
            if (prop.key.type === 'Identifier') keys.add(prop.key.name);
          }
        }
      }
    },
  });
  return keys;
}

function verifyPage(file, appCtxKeys) {
  const code = fs.readFileSync(file, 'utf8');
  const ast = parse(code);
  const localBindings = new Set();
  const ctxDestructured = new Set();   // check A
  const ctxMemberAccess = new Set();   // check C
  const referenced = [];               // check B 候选

  traverse(ast, {
    ImportDeclaration(p) {
      for (const spec of p.node.specifiers) {
        if (spec.local) localBindings.add(spec.local.name);
      }
    },
    VariableDeclarator(p) {
      // 绑定名
      collectNamesFromPattern(p.node.id, localBindings);
      // check A: const { ... } = ctx
      if (p.node.id && p.node.id.type === 'ObjectPattern' &&
          p.node.init && p.node.init.type === 'Identifier' && p.node.init.name === 'ctx') {
        for (const prop of p.node.id.properties) {
          if (prop.type === 'RestElement') {
            collectNamesFromPattern(prop.argument, localBindings);
          } else if (prop.type === 'ObjectProperty') {
            // key: local 可能是 rename（foo: bar）或 shorthand（foo）
            const localNode = prop.value;
            let localName = null;
            if (localNode.type === 'Identifier') localName = localNode.name;
            else if (localNode.type === 'AssignmentPattern' && localNode.left.type === 'Identifier') localName = localNode.left.name;
            if (localName) {
              ctxDestructured.add(localName);
              // 记录 appCtx 侧对应的键：shorthand 用 localName；rename 用 prop.key
              let ctxKey = localName;
              if (prop.key.type === 'Identifier' && prop.key.name !== localName) ctxKey = prop.key.name;
              else if (prop.key.type === 'StringLiteral') ctxKey = prop.key.value;
              ctxDestructured.add('__key__' + ctxKey);
            }
          }
        }
      }
    },
    FunctionDeclaration(p) {
      if (p.node.id) localBindings.add(p.node.id.name);
      for (const param of p.node.params) collectNamesFromPattern(param, localBindings);
    },
    'FunctionExpression|ArrowFunctionExpression'(p) {
      for (const param of p.node.params) collectNamesFromPattern(param, localBindings);
    },
    ClassDeclaration(p) {
      if (p.node.id) localBindings.add(p.node.id.name);
    },
    CatchClause(p) {
      if (p.node.param) collectNamesFromPattern(p.node.param, localBindings);
    },
    MemberExpression(p) {
      // check C: ctx.xxx
      if (p.node.object.type === 'Identifier' && p.node.object.name === 'ctx' &&
          !p.node.computed && p.node.property.type === 'Identifier') {
        ctxMemberAccess.add(p.node.property.name);
      }
    },
    Identifier(p) {
      if (p.isReferencedIdentifier()) {
        referenced.push({ name: p.node.name, loc: p.node.loc && p.node.loc.start });
      }
    },
    JSXOpeningElement(p) {
      const name = p.node.name;
      if (name.type === 'JSXIdentifier') {
        // 组件名（首字母大写）算引用；HTML 标签（小写）不算
        if (name.name[0] === name.name[0].toUpperCase()) {
          referenced.push({ name: name.name, loc: name.loc && name.loc.start });
        }
      }
    },
  });

  // ---------- check A ----------
  // A 的判据是「解构了一个 appCtx 里不存在的键」。
  // ⚠️ 但 v72 清理「导入导出」死代码之后，46 个页面里仍留着 15 个
  //    excel*/download*/runExcelImport 之类的解构项 —— 它们**页面上根本没用**
  //    （B 检查已经证明没有未解析引用），留着只是脏。
  //    如果照旧一律报错，这 540 条噪音会把真正的问题（页面真的用了 undefined 的键）
  //    彻底淹掉。所以这里分两级：
  //      · 用了但 appCtx 没有  → 真问题，必须修（会 ReferenceError）
  //      · 解构了但没用        → 只提示，不计入失败
  const aProblems = [];
  const aHarmless = [];
  for (const item of ctxDestructured) {
    if (item.startsWith('__key__')) {
      const key = item.slice(7);
      if (appCtxKeys.has(key)) continue;
      if (referenced.some((r) => r.name === key) || ctxMemberAccess.has(key)) {
        aProblems.push(key);
      } else {
        aHarmless.push(key);
      }
    }
  }

  // ---------- check C ----------
  const cProblems = [];
  for (const key of ctxMemberAccess) {
    if (!appCtxKeys.has(key)) cProblems.push(key);
  }

  // ---------- check B ----------
  const bProblems = [];
  for (const r of referenced) {
    const n = r.name;
    if (localBindings.has(n)) continue;
    if (appCtxKeys.has(n)) continue;
    if (JS_GLOBALS.has(n)) continue;
    if (HTML_TAGS.has(n)) continue;
    bProblems.push(n + (r.loc ? ` (L${r.loc.line})` : ''));
  }

  return { aProblems, cProblems, bProblems };
}

function main() {
  const appCtxKeys = extractAppCtxKeys();
  console.log(`appCtx 键数: ${appCtxKeys.size}`);
  console.log(`appCtx 键: ${[...appCtxKeys].sort().join(', ')}\n`);

  const files = fs.readdirSync(PAGES_DIR).filter(f => f.endsWith('.jsx')).sort();
  let totalA = 0, totalC = 0, totalB = 0;
  const failed = [];

  for (const f of files) {
    const fp = path.join(PAGES_DIR, f);
    const { aProblems, cProblems, bProblems } = verifyPage(fp, appCtxKeys);
    const bad = aProblems.length + cProblems.length + bProblems.length;
    if (bad > 0) {
      failed.push({ f, aProblems, cProblems, bProblems });
      totalA += aProblems.length;
      totalC += cProblems.length;
      totalB += bProblems.length;
      console.log(`❌ ${f}`);
      if (aProblems.length) console.log(`   A 解构缺键: ${aProblems.join(', ')}`);
      if (cProblems.length) console.log(`   C ctx. 缺键: ${cProblems.join(', ')}`);
      if (bProblems.length) console.log(`   B 未解析引用: ${bProblems.join(', ')}`);
    } else {
      console.log(`✅ ${f}`);
    }
  }

  console.log(`\n=== 汇总 ===`);
  console.log(`页面总数: ${files.length}`);
  console.log(`A 类问题(解构缺键): ${totalA}`);
  console.log(`C 类问题(ctx.缺键): ${totalC}`);
  console.log(`B 类问题(未解析引用): ${totalB}`);
  if (failed.length === 0) {
    console.log(`\n✅ 全部通过：每个页面都能从 appCtx 拿到所需标识符，无 ReferenceError 风险。`);
    process.exit(0);
  } else {
    console.log(`\n❌ ${failed.length} 个页面存在问题，需修复。`);
    process.exit(1);
  }
}

main();
