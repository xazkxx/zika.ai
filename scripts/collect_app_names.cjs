#!/usr/bin/env node
// 用 @babel/parser 精确收集 App 函数「顶层作用域」的所有标识符名。
// 这些名字会被打包进 appCtx，供抽出的页面组件通过 ctx 解构使用。
// 只收集函数体直接子语句里的声明（VariableDeclaration / FunctionDeclaration）
// 以及函数参数与 import 的本地名；嵌套块（if/for/while/try/内部函数）里的声明不计
// —— 因为它们不在 App 的渲染作用域里。
const fs = require('fs');
const parser = require('@babel/parser');

const filePath = process.argv[2];
const code = fs.readFileSync(filePath, 'utf8');
const ast = parser.parse(code, { sourceType: 'module', plugins: ['jsx'] });

const names = new Set();

function collectPattern(pat) {
  if (!pat) return;
  switch (pat.type) {
    case 'Identifier':
      names.add(pat.name);
      break;
    case 'ObjectPattern':
      pat.properties.forEach((p) => {
        if (p.type === 'RestElement') collectPattern(p.argument);
        else collectPattern(p.value);
      });
      break;
    case 'ArrayPattern':
      pat.elements.forEach((e) => collectPattern(e));
      break;
    case 'AssignmentPattern':
      collectPattern(pat.left);
      break;
    case 'RestElement':
      collectPattern(pat.argument);
      break;
    default:
      break;
  }
}

let appFn = null;
function findApp(node) {
  if (!node || typeof node.type !== 'string') return;
  if (node.type === 'FunctionDeclaration' && node.id && node.id.name === 'App') {
    appFn = node; return;
  }
  if (node.type === 'VariableDeclarator' && node.id && node.id.name === 'App' &&
      node.init && (node.init.type === 'ArrowFunctionExpression' || node.init.type === 'FunctionExpression')) {
    appFn = node.init; return;
  }
  for (const k in node) {
    if (['loc', 'start', 'end', 'range', 'leadingComments', 'trailingComments',
         'innerComments', 'comments', 'type'].includes(k)) continue;
    const v = node[k];
    if (Array.isArray(v)) v.forEach(findApp);
    else if (v && typeof v.type === 'string') { /* primitive */ }
    else if (v && v.type) findApp(v);
  }
}
findApp(ast.program);

if (!appFn) { console.error('找不到 App 函数'); process.exit(1); }

// 函数参数
(appFn.params || []).forEach(collectPattern);

// 函数体直接子语句
const body = appFn.body;
if (body && body.type === 'BlockStatement') {
  for (const stmt of body.body) {
    if (stmt.type === 'VariableDeclaration') {
      stmt.declarations.forEach((d) => collectPattern(d.id));
    } else if (stmt.type === 'FunctionDeclaration' && stmt.id) {
      names.add(stmt.id.name);
    }
    // 其它语句（ExpressionStatement / IfStatement / ReturnStatement 等）不收集其内部声明
  }
}

// import 本地名
for (const stmt of ast.program.body) {
  if (stmt.type === 'ImportDeclaration') {
    for (const s of stmt.specifiers) {
      if (s.local) names.add(s.local.name);
    }
  }
}

// 模块顶层（函数外）的声明：menuGroups / pageActions 等。
// 原 inline 页面块能访问模块作用域变量，抽出后也必须能访问，故一并纳入。
for (const stmt of ast.program.body) {
  if (stmt === appFn) continue;
  if (stmt.type === 'VariableDeclaration') {
    // 跳过定义 App 本身的语句
    const definesApp = stmt.declarations.some((d) => d.id && d.id.name === 'App');
    if (definesApp) continue;
    stmt.declarations.forEach((d) => collectPattern(d.id));
  } else if (stmt.type === 'FunctionDeclaration' && stmt.id) {
    if (stmt.id.name === 'App') continue;
    names.add(stmt.id.name);
  }
}

// JS 保留字 / 关键字防护：import 别名（`import * as ns`、`import { x as y }`）
// 的本地名绝不应是 `as`/`from`/`import` 之类关键字；一旦误收，注入 appCtx 后
// 登录后渲染主界面会抛 ReferenceError。这里兜底过滤，避免重跑 extract_pages.py 复现该 bug。
const RESERVED = new Set([
  'as', 'from', 'import', 'export', 'default', 'await', 'yield', 'typeof',
  'instanceof', 'in', 'of', 'new', 'delete', 'void', 'this', 'super', 'class',
  'extends', 'const', 'let', 'var', 'function', 'return', 'if', 'else', 'for',
  'while', 'do', 'switch', 'case', 'break', 'continue', 'try', 'catch', 'finally',
  'throw', 'typeof', 'null', 'true', 'false', 'enum', 'get', 'set', 'static',
]);

const out = Array.from(names).filter((n) => n !== 'appCtx' && !RESERVED.has(n));
process.stdout.write(JSON.stringify(out));
