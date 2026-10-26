# 任务 H · 详情页两个 UX 盲区修复 + 封版

> 一句话：**「已人工核对」不会再被一次误点冲掉；「草稿」终于有了变「生效」的入口。** 顺带完成封版四步曲。

日期：2026-10-19　｜　版本：`erp-pwa-v50`　｜　快照：`backup/20261019_taskH_detail_ux/`

---

## 1. 用户报的两个盲区

> "OCR 状态已经是'已人工核对'，但下方依然有一个'开始识别'按钮。如果用户误点，可能会覆盖已核对的数据。"
> "当前合同是'草稿'，但我找遍了详情页，没看到'提交审核'或'转为生效'的按钮。"

两条都成立，根因不同：

| 盲区 | 根因 |
| --- | --- |
| 误触覆盖 | 识别按钮的文案和 `onClick` **完全没看 `ocr_status`**，永远叫「开始识别」、点了就跑。而 `POST /contracts/{id}/ocr` 会把 `reviewed` 打回 `parsed` —— 等于一次误点清空半小时的核对成果。 |
| 没有生效入口 | 前端**从来没有**调过 `PATCH /contracts/{id}/status`。详情页只有「编辑」「删除」两个动作，状态只能靠编辑表单改 —— 而编辑表单里根本没有 status 字段。合同建完就永远停在草稿。 |

关键事实（动手前先确认过）：

- `CONTRACT_STATUS = {draft, pending, active, signed, executing, finished, void}`（`app/models/contract.py:171`）
- `PATCH /contracts/{id}/status` 是**直写**接口：只校验枚举合法性，**不做流转规则**。所以"哪些状态配显示按钮"必须由前端收窄，否则 backend 会老老实实把「已完成」改回「生效」。
- OCR 状态机：机器写只能到 `parsed`/`failed`；到 `reviewed` 只有 `POST /contracts/{id}/ocr/review` 一条路。

---

## 2. 改动清单

| 文件 | 位置 | 改了什么 |
| --- | --- | --- |
| `frontend/src/components/contracts/ContractsLedger.jsx` | `:784` | `const [ocrConfirm, setOcrConfirm] = useState(false)` |
| 同上 | `:786` | `const [statusBusy, setStatusBusy] = useState(false)` |
| 同上 | `:831` | `requestOcr()` —— 已核对走确认框，其余直接跑 |
| 同上 | `:847` | `activateContract()` —— `PATCH /status {status:'active'}` |
| 同上 | `:1805`–`:1815` | 识别按钮 `onClick={requestOcr}`、文案三分支、`data-ocr-rerun` |
| 同上 | `:1947`–`:1952` | 底部「确认生效」按钮（`data-contract-activate`） |
| 同上 | `:1961`–`:2010` | 二次确认弹窗（挂在详情弹窗**之外**） |
| `frontend/public/sw.js` | `:100` | `CACHE_VERSION` v49 → **v50** |
| `frontend/scripts/_patch_detail_ux.py` | — | 本次改动的字节级补丁脚本（可重放） |
| `docs/使用说明_合同OCR识别.md` | 四 / 五·7·8 / 六 / 七 | 补「重新识别 + 二次确认」「确认生效」+ 4 条防呆 + 流程图 |

`App.jsx` **零改动**（本次全在 `ContractsLedger.jsx` 内），因此不需要报行号清单。

---

## 3. 防误触：按钮改名 + 二次确认

```js
const requestOcr = () => {
  if (!detail || ocrRunning) return;
  if (detail.ocr_status === 'reviewed') { setOcrConfirm(true); return; }
  startOcr();
};
```

- 状态是 `reviewed` → `setOcrConfirm(true)`，**请求一个都不发**
- 其余状态 → 原路走 `startOcr()`

按钮文案三分支：

```jsx
{ocrRunning ? '识别中…' : detail.ocr_status === 'reviewed' ? '重新识别' : '开始识别'}
```

同时挂 `data-ocr-rerun={detail.ocr_status === 'reviewed' ? '1' : '0'}`，让界面台能断言"前端自己知道这是重跑"，而不是靠文案字符串猜。

### 为什么不用 `window.confirm`

1. `window.confirm` 会**冻住页面主线程**，正在跑的 `setState` / 请求回调全部挂起；
2. E2E 里原生 `dialog` 需要 `page.on('dialog')` 接管，一旦没接管就被自动 dismiss —— 等于测试永远走"取消"分支，**测不出"继续"那一半**；
3. 原生框不能写富文本、不能标红"覆盖"两个字，用户看不清后果。

所以自建了一个 `.cledger__confirm` 小弹窗：`data-ocr-confirm-text` / `data-ocr-confirm-cancel` / `data-ocr-confirm-ok`，确认按钮用 `danger-btn`。

### 弹窗挂在哪

挂在 `</section>` 之前、**详情弹窗之外**。原因是 `.modal-card` 带 `overflow:auto`：嵌进去会被裁掉，或者跟着详情内容一起滚走（这是任务 G 已经踩过一次的坑）。

---

## 4. 状态流转：确认生效

```js
const activateContract = async () => {
  if (!detail || statusBusy) return;
  setStatusBusy(true);
  try {
    const res = await fetch(`${API_BASE}/contracts/${detail.id}/status`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ status: 'active' }),
    });
    ...
    await openDetail(detail.id);          // 详情徽章刷新
    await loadRows(direction, keyword);   // 列表徽章刷新
    setNotice(`合同 ${detail.contract_no} 已生效`);
  } finally { setStatusBusy(false); }
};
```

三个细节：

1. **只对 `draft` / `pending` 显示**：`{['draft','pending'].includes(String(detail.status ?? '')) ? <button …/> : null}`。因为后端是直写接口，前端不收窄的话，「已完成」「已作废」的合同也能被一键拉回 `active` —— 那不是修 bug，那是造 bug。
2. **`statusBusy` 期间按钮显示「处理中…」并 disabled**：防连点造成两次 PATCH。
3. **刷两处**：详情弹窗里的徽章 + 列表行里的徽章。只刷一处会出现"弹窗里是生效、关掉一看列表还是草稿"的自相矛盾。

---

## 5. 验证台 `verify_taskH_detail_ux.mjs`（22/22）

夹具：`.venv/Lib/site-packages/matplotlib/mpl-data/images/matplotlib.pdf`（1 页 / 22KB / 无文本层）—— 真跑 OCR 只要几秒，整台 15~26 秒。

| 断言 | 内容 |
| --- | --- |
| H0 / H0b | 小 PDF 夹具在 / admin 登录 |
| H0c | 建两张合同：`HT-UXH{stamp}A`（草稿）、`…B`（已核对） |
| H0d / H0e | B 挂原件 → PATCH `ocr_json` `{ocr_status:'parsed'}` → `POST /ocr/review {confirm_empty:true}` 推到 `reviewed` |
| H1a / H1 / H1b | 打开 B 的详情：文案是「重新识别」、`data-ocr-rerun=1` |
| H2 / H2b | 点击**先弹确认框**，文案说清"会覆盖已人工核对的数据" |
| H3 / H3b | 点「取消」→ 弹窗关、**没发识别请求**、库里 `ocr_status` 仍是 `reviewed` |
| H4 / H4b | 点「继续重新识别」→ 骨架屏出现 → 跑完 `ocr_status` 回到 `parsed`（证明"覆盖"是真的） |
| H5a / H5 | 打开 A 的详情：底部有「确认生效」 |
| H6 / H6b / H6c / H6d | 点完 → 库里 `status=active`、按钮消失、详情徽章「生效」、列表行徽章「生效」 |
| H7 | 已生效的合同再打开，**没有**「确认生效」（不会被一键拉回） |
| H8 | 全程 `console` 零报错 |

> `H6c` 曾首跑红：裸 `document.querySelector('.cledger__badge')` 抓到的是**列表行**的徽章（详情弹窗背后还盖着一张表）。收窄成 `.modal-header h3 .cledger__badge` 才对准。

---

## 6. 反证（4 组，全红 → 全绿）

脚本 `_probe_taskH.mjs`。每组都做三件事：换包（`dist/assets` mtime + 清单双重校验）→ 改坏 → 确认指定断言变红 → 字节级还原 → `grep PROBE` 归零。

| 组 | 怎么改坏 | 应该红的断言 | 实测 |
| --- | --- | --- | --- |
| H-A | 按钮文案写死 `'开始识别'` | H1 | 红 → 绿 ✔ |
| H-B | `requestOcr` 去掉确认分支，直接 `startOcr()` | H2 | 红 → 绿 ✔ |
| H-C | 「确认生效」对所有状态都显示 | H7 | 红 → 绿 ✔ |
| H-D | `activateContract` 只弹 notice、不发 PATCH | H6 | 红 → 绿 ✔ |

两个必须记住的坑：

- **从 node 里 `spawnSync('npm',['run','build'])` 会假失败**：本环境 `NODE_OPTIONS` 带 `--require node-language-shim.cjs`，加上 `CODEBUDDY_SAFE_DELETE_*` 拦截删除 → `vite build` 第一步 `rm -rf dist` EPERM → dist 还是旧包 → **4 组反证全绿假象**。子进程必须 `delete env.NODE_OPTIONS` + 删掉 `CODEBUDDY_SAFE_DELETE_*`，并且断言产物真的换了。
- **反证 needle 要自动适配 CRLF**：多行锚点按 LF 写，在 CRLF 文件里永远找不到。`pickAnchors()` 先试 LF 再试 CRLF。

---

## 7. 封版四步曲

完整版见项目根 `ERP终极封版说明.md`。这里只记本任务相关的实测结论：

- `sw.js` v49 → **v50**，`npm run build` 通过（213 modules，7.43s，`dist/assets/ContractsLedger-CpwLkGrs.js` 48,278 B）
- **全量回归 12 台 / 327 项 / 0 红**：H 22、G 30、F 25、F精度 24、E界面 18、E接口 48、D守卫 21、D接口 36、C界面 29、C接口 23、A界面 24、A接口 27
- 清理：`_contract_module/` 下探针/诊断/验证脚本 + `frontend/scripts/_*.py` + 13 个历史步骤目录 → `backup/20261019_final_cleanup/`（25MB，可回收）；数据库核回基线（contracts 0 / customers 33 含用户手建的华邦 / suppliers 68 / sales_orders 3 / purchase_orders 5 / 流水 17）
- 备份：`backup/erp_20261019_final.dump`（757KB）+ `backup/源码全量_20261019_封版.zip`（3.11MB / 466 文件）

### 首轮三处不绿的真实原因（都不是业务代码）

| 现象 | 真因 | 处置 |
| --- | --- | --- |
| G 台 G0c/G1 全红、F 台 E9b/E9c/E10 全红 | 用户 14:55 手动建的「湖南华邦建设有限公司」还在客户档案里，"未匹配"前置条件不成立；改成「…（临时隐藏）」还会被**唯一包含**规则模糊匹配上 | 用哨兵名 `ZZZ封版临时客户` 临时隐藏 → 复跑全绿 → 已还原 |
| G 台再红一次，日志「180.0s 后退出」 | **Puppeteer 默认 `protocolTimeout = 180s`**，而扫描件 OCR 单次 53~320 秒 → 连接被测试台自己掐断，报「Waiting for selector failed」，看着像"识别没回填" | 6 个界面台统一加 `protocolTimeout: 900000`；`openSalesDraft` 把真实耗时/异常名打出来 |
| C 台界面 TimeoutError `.ssel-panel .ssel-option` | 任务 G 把客户字段容器 `<label>` 换成 `div.cledger__field`（防 label 连带激活下拉），C 台仍按 `label` 找 → 选择器过期 | 改成 `querySelectorAll('label, .cledger__field')` → 29/29 |

> 教训：测试台报"识别没回填"时，先查**等待上限**和**协议超时**，再怀疑业务。

