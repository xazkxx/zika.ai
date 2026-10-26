/**
 * 接口错误文案解析 —— 纯逻辑层
 *
 * 为什么必须有这个文件（v76 血案）：
 * 后端 `raise HTTPException(400, "中文")` 返回的 `detail` 是**字符串**，
 * 但 Pydantic 校验失败（422）返回的 `detail` 是**数组**：
 *   { "detail": [ { "type": "int_parsing", "loc": ["body","ids",0],
 *                   "msg": "Input should be a valid integer…", "input": "abc" } ] }
 * 前端只要写一句 `setNotice(data.detail)`，数组就会流进 React 状态，
 * 渲染时抛 "Objects are not valid as a React child" → **整棵页面树被卸载 → 白屏**。
 *
 * 所以：任何把 `detail` 交给用户看的场合，都必须先过这个函数。
 * 它保证**返回一个非空字符串**，永不返回对象/数组。
 *
 * 不依赖 React、不碰 window，标准 ESM 导出 —— 可以直接
 * `node --test src/lib/apiDetail.test.mjs` 跑回归。
 */

/**
 * @param {unknown} detail 接口 body 里的 detail 字段（可能是 string / array / object / undefined）
 * @param {string} fallback 兜底文案（HTTP 状态不认识、body 不是 JSON 时用）
 * @returns {string} 一定是一行可直接渲染的中文
 */
export function parseApiDetail(detail, fallback = '请求失败，请稍后重试') {
  const safeFallback = typeof fallback === 'string' && fallback.trim() ? fallback.trim() : '请求失败，请稍后重试';

  // 主力分支：我们自己 raise 的中文业务错误
  if (typeof detail === 'string') {
    const text = detail.trim();
    return text || safeFallback;
  }

  // 422：数组。取第一条能用的 msg
  if (Array.isArray(detail)) {
    for (const item of detail) {
      if (typeof item === 'string' && item.trim()) return item.trim();
      if (!item || typeof item !== 'object') continue;
      if (typeof item.msg === 'string' && item.msg.trim()) {
        // Pydantic 的 msg 是英文（"Input should be…"），至少让人知道是哪个字段
        const field = Array.isArray(item.loc) && item.loc.length
          ? String(item.loc[item.loc.length - 1])
          : '';
        // 常见类型换成中文，别把 "Input should be a valid integer" 摊给业务人员
        const reason = translatePydanticMsg(item.msg, field);
        return reason;
      }
      if (typeof item.detail === 'string' && item.detail.trim()) return item.detail.trim();
    }
    return safeFallback;
  }

  // 单个对象（少见，但别炸）
  if (detail && typeof detail === 'object') {
    if (typeof detail.msg === 'string' && detail.msg.trim()) return detail.msg.trim();
    if (typeof detail.detail === 'string' && detail.detail.trim()) return detail.detail.trim();
  }

  return safeFallback;
}

/**
 * Pydantic 英文校验消息 → 中文提示。
 * 只覆盖本项目实际会踩到的几类（漏字段 / 类型错 / 空值），其余原文返回，
 * 至少让开发看得懂，而不是塞一句"操作失败"把线索抹掉。
 */
function translatePydanticMsg(msg, field) {
  const raw = String(msg || '').trim();
  const lower = raw.toLowerCase();
  const where = field ? `「${field}」` : '';

  if (lower.includes('field required')) return `缺少必填参数${where}`;
  if (lower.startsWith('input should be a valid integer') || lower.includes('valid integer')) {
    return `参数${where}必须是整数`;
  }
  if (lower.includes('input should be a valid string')) return `参数${where}必须是文本`;
  if (lower.includes('input should be a valid list') || lower.includes('valid list')) {
    return `参数${where}必须是列表`;
  }
  if (lower.includes('none is not an allowed value') || lower.includes('input should not be none')) {
    return `参数${where}不能为空`;
  }
  if (lower.includes('string should have at most')) {
    const limit = /at most (\d+) character/.exec(lower);
    return limit ? `参数${where}最多 ${limit[1]} 个字符` : `参数${where}内容过长`;
  }
  return raw;
}

export default parseApiDetail;
