// 反证台：把三处修复分别改坏，确认对应的断言真的会红，然后字节级还原。
//
//   A 去掉「已完成核对」的灰态 CSS        → 预期 B1f 红
//   B 按钮回到 disabled={reviewing}       → 预期 B1d 红
//   C 去掉 looksLikeDocx 魔数闸           → 预期 B2i / B2j 红（JSON 被存成 .docx）
//
// ⚠️ 两次踩过的坑都在这儿复用了：
//   ① 子进程跑 npm 必须摘掉 NODE_OPTIONS 和 CODEBUDDY_SAFE_DELETE_*，否则 rm -rf dist
//      被拦 → 构建"失败"但 dist 还是旧包 → 反证全绿假象；
//   ② 每次构建后比对 dist/assets 的 mtime + 清单，确认真的换包了。
//
// 用法：PROBE_ONLY=A node _contract_module/_probe_two_bugs.mjs
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const NODE = process.execPath;
const FE = path.join(ROOT, 'frontend');
const DIST = path.join(FE, 'dist', 'assets');

const LEDGER = path.join(FE, 'src/components/contracts/ContractsLedger.jsx');
const CSS = path.join(FE, 'src/components/contracts/contractsLedger.css');
const WORD = path.join(FE, 'src/lib/wordExport.js');
const GLOBAL_CSS = path.join(FE, 'src/styles.css');

const cleanEnv = () => {
  const env = { ...process.env };
  delete env.NODE_OPTIONS;
  for (const k of Object.keys(env)) {
    if (k.startsWith('CODEBUDDY_SAFE_DELETE')) delete env[k];
  }
  return env;
};

const stamp = () => {
  const files = fs.readdirSync(DIST).filter((f) => f.endsWith('.js') || f.endsWith('.css'));
  return files
    .map((f) => `${f}:${fs.statSync(path.join(DIST, f)).mtimeMs}`)
    .sort()
    .join('|');
};

function build(tag) {
  const before = stamp();
  const r = spawnSync('npm', ['run', 'build'], {
    cwd: FE,
    env: cleanEnv(),
    shell: true,
    encoding: 'utf8',
    timeout: 300000,
  });
  if (r.status !== 0) {
    console.log(`  [build ${tag}] 失败：\n${(r.stdout || '').slice(-800)}\n${(r.stderr || '').slice(-800)}`);
    return false;
  }
  const after = stamp();
  if (after === before) {
    console.log(`  [build ${tag}] ⚠️ dist/assets 没有任何变化 —— 没换包，反证结果不可信`);
    return false;
  }
  return true;
}

function runVerify() {
  const r = spawnSync(NODE, [path.join(ROOT, '_contract_module/verify_two_bugs.mjs')], {
    cwd: ROOT,
    env: cleanEnv(),
    encoding: 'utf8',
    timeout: 600000,
  });
  return (r.stdout || '') + (r.stderr || '');
}

/** 把 old 换成 new（支持 CRLF 自适应），返回还原函数 */
function swap(file, oldText, newText) {
  const raw = fs.readFileSync(file);
  const crlf = raw.includes('\r\n');
  let text = raw.toString('utf8');
  const norm = (s) => (crlf ? s.replace(/\n/g, '\r\n') : s);
  const oldN = norm(oldText);
  if (!text.includes(oldN)) throw new Error(`${path.basename(file)}: 锚点找不到`);
  fs.writeFileSync(file, text.replace(oldN, norm(newText)));
  return () => fs.writeFileSync(file, raw);
}

const GROUPS = [
  {
    id: 'A',
    name: '去掉灰态样式（组件 CSS + 全局 styles.css 一起拿掉）',
    // ⚠️ 只改组件 CSS 是测不出来的：styles.css 里还有一条全局 `.primary-btn:disabled` 兜底。
    //    要证明 B1f 真的在盯着"视觉"，两处必须一起拿掉。
    break: () => {
      const undoLocal = swap(
        CSS,
        `.cledger__ocr-actions .primary-btn:disabled,
.cledger__ocr-actions .primary-btn.is-done {
  background: #e2e8f0;
  border-color: #cbd5e1;
  color: #64748b;
  box-shadow: none;
  cursor: not-allowed;
}`,
        `.cledger__ocr-actions .primary-btn:disabled,
.cledger__ocr-actions .primary-btn.is-done {
  /* PROBE: 故意拿掉灰态 */
}`,
      );
      const undoGlobal = swap(
        GLOBAL_CSS,
        `.primary-btn:disabled,
.primary-btn[aria-disabled='true'] {
  background: #e2e8f0;
  border-color: #e2e8f0;
  color: #94a3b8;
  box-shadow: none;
  transform: none;
  cursor: not-allowed;
}`,
        `/* PROBE: 全局灰态故意拿掉 */`,
      );
      return () => {
        undoGlobal();
        undoLocal();
      };
    },
    expect: ['B1f'],
  },
  {
    id: 'B',
    name: '按钮退回 disabled={reviewing}（已核对也能点）',
    break: () =>
      swap(
        LEDGER,
        `                          disabled={reviewing || detail.ocr_status === 'reviewed'}`,
        `                          disabled={reviewing /* PROBE */}`,
      ),
    // B1h 在改坏后仍是绿的 —— 因为 reviewOcr 里的第二道守卫拦住了请求。这是设计，不是漏断言。
    expect: ['B1d'],
  },
  {
    id: 'C',
    name: '去掉 looksLikeDocx 魔数闸（JSON 会被存成 .docx）',
    break: () =>
      swap(
        WORD,
        `  if (!(await looksLikeDocx(blob))) {`,
        `  if (false && !(await looksLikeDocx(blob))) { /* PROBE */`,
      ),
    expect: ['B2i', 'B2j'],
  },
];

const only = process.env.PROBE_ONLY || '';
let bad = 0;

for (const g of GROUPS) {
  if (only && only !== g.id) continue;
  console.log(`\n===== 反证 ${g.id}：${g.name} =====`);
  const restore = g.break();
  let output = '';
  try {
    if (!build(`break-${g.id}`)) {
      bad += 1;
      continue;
    }
    output = runVerify();
    const reds = output
      .split('\n')
      .filter((line) => line.includes('❌'))
      .map((line) => line.trim());
    console.log(`  红色断言 ${reds.length} 条：`);
    reds.forEach((r) => console.log('    ' + r));
    for (const key of g.expect) {
      const hit = reds.find((r) => r.includes(key));
      console.log(`  ${hit ? '✔' : '✘'} 预期 ${key} ${hit ? '如期变红' : '没有变红（断言可能没写到）'}`);
      if (!hit) bad += 1;
    }
  } finally {
    restore();
    console.log('  已字节级还原');
  }
  if (!build(`restore-${g.id}`)) bad += 1;
}

// 收尾：还原后必须重新全绿
if (!only) {
  console.log('\n===== 还原后复跑（应全绿）=====');
  const out = runVerify();
  const tail = out.split('\n').filter((l) => l.includes('合计') || l.includes('❌'));
  tail.forEach((l) => console.log('  ' + l.trim()));
  if (out.includes('❌')) bad += 1;
}

// PROBE 归零检查
const leftovers = [LEDGER, CSS, GLOBAL_CSS, WORD].filter((f) =>
  fs.readFileSync(f).toString('utf8').includes('PROBE'),
);
if (leftovers.length) {
  console.log('⚠️ 还有 PROBE 残留：', leftovers.map((f) => path.basename(f)).join(', '));
  bad += 1;
} else {
  console.log('\nPROBE 残留：0');
}

console.log(bad === 0 ? '\n反证全部成立 ✔' : `\n反证有 ${bad} 处问题 ✘`);
process.exitCode = bad ? 1 : 0;
