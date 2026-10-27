#!/usr/bin/env node
/**
 * check_single_primary.cjs —— 「单主按钮」门禁（v1.78.0 UI 标准铺开）
 *
 * 为什么需要它：
 *   金蝶/用友的界面上，一屏只会有一个蓝色主按钮 —— 它代表"这一屏你该做的
 *   那件事"。改造成"多主按钮"很容易悄悄回潮：谁新加一个功能，顺手复制
 *   上一颗按钮的 className="primary-btn" 就完事了，评审时也没人看得出来。
 *   所以把它变成机器判据：**同一操作区里不允许出现两颗及以上主按钮**。
 *
 * 判定方式（故意保守，只抓真问题）：
 *   相邻两个 `primary-btn` 的行号差 ≤ WINDOW 行 → 视为"并排主按钮"。
 *   跨区块（比如「保存合同」在表单里、「确认」在弹窗里）不会误报。
 *
 * 用法：
 *   node scripts/check_single_primary.cjs        # 违规则 exit 1
 *   node scripts/check_single_primary.cjs -v     # 打印每个文件的计数
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const VERBOSE = process.argv.includes('-v');
const WINDOW = 6; // 行号差阈值

const TARGETS = [
  'frontend/src/pages',
  'frontend/src/components/docs',
  'frontend/src/components/statements',
];

function listFiles(dir) {
  const abs = path.join(ROOT, dir);
  if (!fs.existsSync(abs)) return [];
  const out = [];
  const walk = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.jsx')) out.push(full);
    }
  };
  walk(abs);
  return out;
}

const violations = [];
const counts = [];

for (const file of TARGETS.flatMap(listFiles)) {
  const rel = path.relative(ROOT, file).replace(/\\/g, '/');
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
  const hits = [];
  lines.forEach((line, index) => {
    // 注释里提到 primary-btn 不算（文档/说明经常举例）
    const trimmed = line.trim();
    if (trimmed.startsWith('*') || trimmed.startsWith('//') || trimmed.startsWith('/*')) return;
    if (line.includes('primary-btn')) hits.push(index + 1);
  });
  counts.push({ rel, count: hits.length });
  for (let i = 1; i < hits.length; i += 1) {
    if (hits[i] - hits[i - 1] <= WINDOW) {
      violations.push({ rel, a: hits[i - 1], b: hits[i] });
    }
  }
}

if (VERBOSE) {
  counts
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
    .forEach((item) => console.log(`  ${String(item.count).padStart(2)}  ${item.rel}`));
}

if (violations.length) {
  console.error('\n[SINGLE_PRIMARY] 发现并排主按钮（同一操作区两颗以上 primary-btn）：');
  for (const item of violations) {
    console.error(`  ✗ ${item.rel}: L${item.a} 与 L${item.b} 相距 ${item.b - item.a} 行`);
    console.error('      → 只保留一个主入口，其余改 secondary-btn 或收进 ErpMoreMenu(⋯)');
  }
  console.error(`\n共 ${violations.length} 处。标准见 docs/增强对账单_金蝶级UI标准_20261026.md（第二节）。\n`);
  process.exit(1);
}

console.log(`[SINGLE_PRIMARY] OK：${counts.reduce((n, c) => n + c.count, 0)} 个主按钮，无并排冲突。`);
