# 任务 I · 封神前两处 Bug（已核对死链 + Word 打不开）

日期：2026-10-19　｜　版本：`erp-pwa-v51`　｜　验证：**26 / 26 全绿**，反证 3 组（红→绿）

---

## 1. 两个 Bug 的真身

### Bug 1：「已核对」看着能点、点了没反应

**不是死链，是"染色没跟上状态"。** 代码里其实已经 `disabled` 了：

```jsx
disabled={reviewing || detail.ocr_status === 'reviewed'}
```

但 `styles.css` 的 `.primary-btn` **从来没有写过 `:disabled` 样式** —— 浏览器只管"不响应点击"，不管"看起来像不像能点"。于是按钮依旧是纯蓝 `#2563eb` + `cursor:pointer`，用户当然当成死链。

> 顺带暴露的第二个问题：就算它是灰的，`.cledger__notice` 在**列表工具栏**里，详情弹窗打开时被遮罩盖着 —— 用户也看不到"已完成"的反馈。

### Bug 2：导出的 Word 打不开

后端链路本身是好的（实测 `200 / 38KB / 50 4B 03 04 / xxx.docx`）。真正的问题是**失败路径没有闸**：

```
fetch → response.ok ?
   false → 报错（√ 这条以前就有）
   true  → 直接 response.blob() → saveBlob 存盘
```

只要服务端/代理在**200 的情况下**返回一段 JSON（`{"detail": …}`）或 HTML 登录页，前端就会把它当 docx 存下来。用户双击 → Word 报"文件已损坏"。这正是当年 PDF 0 字节那类"看着成功了其实是垃圾"的同款陷阱。

---

## 2. 修复代码

### 2.1 前端 · 按钮（`ContractsLedger.jsx`）

```jsx
{/* ⚠️ 已核对后必须"看着也不能点"：光有 disabled 属性、没样式，
    按钮还是一片纯蓝，用户会当成死链。 */}
<button
  type="button"
  className={`primary-btn small-btn${detail.ocr_status === 'reviewed' ? ' is-done' : ''}`}
  onClick={reviewOcr}
  disabled={reviewing || detail.ocr_status === 'reviewed'}
  aria-disabled={detail.ocr_status === 'reviewed' ? 'true' : 'false'}
  data-ocr-review
  data-ocr-reviewed={detail.ocr_status === 'reviewed' ? '1' : '0'}
  title={
    detail.ocr_status === 'reviewed'
      ? '已是「已人工核对」，无需再点；如需重做请先点「重新识别」'
      : '核对完成后，识别状态变为「已人工核对」'
  }
>
  {reviewing ? '提交中…' : detail.ocr_status === 'reviewed' ? '已完成核对' : '确认无误'}
</button>
```

**第二道守卫**（键盘回车 / 旧缓存里的旧按钮 / 脚本都可能绕过 disabled）：

```js
const reviewOcr = async () => {
  if (!detail || reviewing) return;
  if (detail.ocr_status === 'reviewed') {
    setNotice('识别结果已人工核对完成，无需重复确认；如需重做请点「重新识别」');
    return;
  }
  ...
};
```

**同一视野里的常驻说明**（补上被遮罩盖住的那个 toast）：

```jsx
{detail.ocr_status === 'reviewed' ? (
  <p className="cledger__muted" data-ocr-done-hint>
    识别结果已人工核对完成，无需再确认；如需重做请点上方「重新识别」。
  </p>
) : null}
```

### 2.2 前端 · 样式

`contractsLedger.css`（组件级，双类提高特异性）：

```css
.cledger__ocr-actions .primary-btn:disabled,
.cledger__ocr-actions .primary-btn.is-done {
  background: #e2e8f0;
  border-color: #cbd5e1;
  color: #64748b;
  box-shadow: none;
  cursor: not-allowed;
}
.cledger__ocr-actions .primary-btn.is-done::before {
  content: '✓';
  margin-right: 6px;
  font-weight: 700;
  color: #16a34a;
}
```

`styles.css`（全局兜底，全站所有"提交中…/已完成"的主按钮一起修）：

```css
.primary-btn:disabled,
.primary-btn[aria-disabled='true'] {
  background: #e2e8f0;
  border-color: #e2e8f0;
  color: #94a3b8;
  box-shadow: none;
  transform: none;
  cursor: not-allowed;
}
```

### 2.3 前端 · Word 下载（`lib/wordExport.js`）

```js
const response = await fetch(`${API_BASE}/exports/word/${kind}/${id}`, {
  headers: {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    Accept:
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/octet-stream',
  },
});
if (!response.ok) { /* 原样保留：读 JSON detail 抛错 */ }

const blob = await response.blob();

// ⭐ 只要不是 docx 二进制，就绝不落盘
if (!blob || blob.size === 0) {
  throw new Error('导出失败：服务端返回了空文件，请重试或联系管理员');
}
if (!(await looksLikeDocx(blob))) {
  const preview = (await blob.slice(0, 300).text()).replace(/\s+/g, ' ').trim();
  let detail = '';
  try { detail = JSON.parse(preview).detail || ''; } catch { /* 不是 JSON 就算了 */ }
  throw new Error(
    `导出失败：服务端返回的不是 Word 文件${detail ? `（${detail}）` : `（内容开头：${preview.slice(0, 60)}）`}`,
  );
}

const name = ensureDocxName(
  fileNameFromDisposition(response.headers.get('Content-Disposition'), fallbackName),
);
saveBlob(blob, name);

/** docx = zip 包：前 4 字节必须是 PK\x03\x04 */
async function looksLikeDocx(blob) {
  const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  return head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04;
}

/** 文件名兜底补后缀：`报价单-BJ001` → `报价单-BJ001.docx` */
function ensureDocxName(name) {
  const clean = String(name || '').trim() || '单据.docx';
  return /\.docx$/i.test(clean) ? clean : `${clean}.docx`;
}
```

### 2.4 后端 · 发出前自检（`app/api/v1/routes/erp_word.py`）

```python
company = load_company(db)
content, filename = _render(kind, doc_id, db, company)

# docx 是 zip 包，前 4 字节必然是 PK\x03\x04。
# 生成为空/写坏时**宁可报 500 让人看见**，也不要把坏字节流当文件发出去。
if not content or len(content) < 4 or not content.startswith(b"PK"):
    raise HTTPException(
        status_code=500,
        detail="Word 生成异常（内容为空或不是 docx 二进制），请联系管理员",
    )
```

`media_type` 一直是 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`（`erp_word.py` 的 `DOCX_MEDIA_TYPE`），本次实测确认未变。

---

## 3. 验证（`verify_two_bugs.mjs`，26 / 26）

真浏览器 + CDP `Browser.setDownloadBehavior`，把文件**真存到磁盘**再读字节：

| 组 | 断言 |
| --- | --- |
| X0–X0c | admin 登录；建两张合同；一张推到「已人工核对 + 生效」 |
| B1a–B1c | 详情里按钮在、文案是「已完成核对」 |
| B1d–B1e | `disabled=true`、`data-ocr-reviewed=1`、`aria-disabled=true` |
| B1f | 计算样式：`background != rgb(37,99,235)` 且 `cursor=not-allowed` |
| B1g | `title` 说清了"为什么不能点、想重做点哪里" |
| B1h | 点它**不发** `/ocr/review` 请求 |
| B1i | 详情里有常驻说明（不是被遮罩盖住的 toast） |
| B1j | 强制点亮 `disabled` 再点，**仍然不发请求**（第二道守卫） |
| B2a–B2b2 | 点 Word → 真触发 `<a download>`，名字以 `.docx` 结尾 |
| B2b3 | 浏览器真落盘 |
| B2c–B2e | 大小 39,468 B；魔数 `504b0304` |
| B2f–B2g | 不是 JSON 文本；包内含 `word/document.xml` |
| B2h–B2j | **负向**：服务端 200 + `{"detail":"模拟后端报错：模板缺失"}` → 不触发任何保存，界面提示「导出失败…模板缺失」 |
| X9 | 全程无 JS 报错 |

### 反证（3 组，全红 → 全绿，PROBE 残留 0）

| 组 | 改坏什么 | 预期红 | 实测 |
| --- | --- | --- | --- |
| A | 拿掉灰态样式（**组件 CSS + 全局 styles.css 一起**） | B1f | `rgb(37,99,235) / pointer` → 红 ✔ |
| B | `disabled={reviewing}`（已核对也能点） | B1d | `disabled=false` → 红 ✔ |
| C | 去掉 `looksLikeDocx` 魔数闸 | B2i、B2j | 存了第 2 个文件 + 提示"已导出" → 红 ✔ |

> 反证第一轮抓出了我自己三个漏洞：A 组只改组件 CSS（全局兜底仍生效 → 假绿）、B 组预期写错（第二道守卫本来就该拦）、C 组用"数文件"当判据（headless 的 blob 下载不一定落盘 → 假绿）。现在 C 组改成直接监听 `<a download>` 的 click。
>
> 回归：任务 H 详情台 22/22、任务 E Word 界面台 18/18。

---

## 4. F12 怎么确认下载流是二进制

1. `F12` → **Network**，先清空；
2. 点「导出 Word」；
3. 找到 `exports/word/...` 这条请求，看：
   - **Status** `200`；
   - **Response Headers → content-type** = `application/vnd.openxmlformats-officedocument.wordprocessingml.document`（若是 `application/json`，就是"存下来打不开"的原因）；
   - **content-disposition** 含 `filename*=UTF-8''…docx`；
   - **Size** 30KB 上下（几十字节 = 报错文本）；
   - **Response** 面板显示 Binary/乱码（不是 `{"detail": …}`）。
4. 落盘验证：文件属性 30KB 上下；记事本打开第一行是 `PK` 开头的乱码。

（这套步骤也写进 `docs/使用说明_合同OCR识别.md` 第八节，业务人员能照着做。）
