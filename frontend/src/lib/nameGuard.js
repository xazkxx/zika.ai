/**
 * 档案名称防呆：**重名硬拦截** + **相似名软提醒**（2026-10-22）
 *
 * 为什么放在前端还要做一遍（后端已经有 409）：
 *   后端 409 是"回合制"——用户点了保存、等一个来回、才被告知重名，输入框里的
 *   其它内容还在，但体验是"白填了一遍"。这里在提交前先用内存里的列表挡一道，
 *   0 延迟；后端那道继续留着，防并发、防别的入口绕过。
 *
 * 相似度不引入拼音库（离线部署装不了依赖，且 8 万汉字表会让首屏变大）：
 *   用四个便宜但命中率高的信号 ——
 *     ① 规范化后完全相同            → 不是"相似"，是"重名"，直接拦
 *     ② 前 2~3 个字相同             → 「陕西送变电…」vs「陕西送变电工程…」
 *     ③ 一方包含另一方              → 「劳保鞋」vs「劳保鞋(新)」
 *     ④ 编辑距离 ≤ 1（短名才做）    → 「甲001」vs「甲0001」
 *   商品额外比 **助记码**（`mnemonic` 本来就是拼音首字母），命中率高且零成本。
 */

/** 规范化：去首尾空白、全角括号转半角、去掉常见分隔符、转小写 */
export function normalizeName(value) {
  return String(value || '')
    .replace(/[（]/g, '(')
    .replace(/[）]/g, ')')
    .replace(/[\s\-_/\\·、,，.。:：]/g, '')
    .toLowerCase();
}

/** 编辑距离（只算到 1：超过 1 直接返回 2，省得跑完整 DP） */
function withinOneEdit(a, b) {
  if (a === b) return true;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  let i = 0;
  let j = 0;
  let diff = 0;
  while (i < la && j < lb) {
    if (a[i] === b[j]) {
      i += 1;
      j += 1;
      continue;
    }
    diff += 1;
    if (diff > 1) return false;
    if (la > lb) i += 1;
    else if (lb > la) j += 1;
    else {
      i += 1;
      j += 1;
    }
  }
  return diff + (la - i) + (lb - j) <= 1;
}

/**
 * 找同名项（严格相同）。
 * @returns {object|null} 命中的那一行（带 code 方便提示"编码 xxx"）
 */
export function findDuplicateName(list, name, { excludeId = null, key = 'name' } = {}) {
  const target = normalizeName(name);
  if (!target) return null;
  return (
    (list || []).find((row) => {
      if (excludeId != null && String(row.id) === String(excludeId)) return false;
      return normalizeName(row[key]) === target;
    }) || null
  );
}

/**
 * 找相似项（不含完全相同）。
 * @returns {{row: object, reason: string}[]} 最多 3 条，按"相似程度"排序
 */
export function findSimilarNames(list, name, { excludeId = null, key = 'name', mnemonicKey = null } = {}) {
  const raw = String(name || '').trim();
  const target = normalizeName(raw);
  if (target.length < 2) return [];

  const scored = [];
  (list || []).forEach((row) => {
    if (excludeId != null && String(row.id) === String(excludeId)) return;
    const candidateRaw = String(row[key] || '');
    const candidate = normalizeName(candidateRaw);
    if (!candidate || candidate === target) return;

    let score = 0;
    let reason = '';

    // 助记码命中（商品专用）：拼音首字母相同 = 读音高度相近
    if (mnemonicKey) {
      const m = normalizeName(row[mnemonicKey]);
      if (m && m.length >= 2 && (m === target || target.startsWith(m) || m.startsWith(target))) {
        score = 4;
        reason = '助记码相近';
      }
    }

    if (!score && target.slice(0, 3) === candidate.slice(0, 3)) {
      score = 3;
      reason = '前三个字相同';
    } else if (!score && target.slice(0, 2) === candidate.slice(0, 2)) {
      score = 2.5;
      reason = '前两个字相同';
    } else if (!score && (candidate.includes(target) || target.includes(candidate))) {
      score = 2;
      reason = '名称互相包含';
    } else if (!score && candidate.length <= 8 && withinOneEdit(target, candidate)) {
      score = 1;
      reason = '只差一个字';
    }

    if (score > 0) scored.push({ row, reason, score });
  });

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(({ row, reason }) => ({ row, reason }));
}
