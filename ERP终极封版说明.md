# ERP 终极封版说明

> **版本 v1.0.0 · 封版日期 2026-10-19 · 前端 sw `erp-pwa-v50`**
> 这份文档是本项目的**收官档案**：今天修了什么、验证了什么、清掉了什么、备份在哪、怎么打包成 .exe、以后再动要注意什么。

---

## 一、今天最后修的两个 UX 盲区（任务 H）

| 盲区 | 修法 | 位置 |
| --- | --- | --- |
| 已「人工核对」的合同，识别按钮还叫「开始识别」，误点就覆盖核对成果 | 状态是 `reviewed` 时**按钮改名「重新识别」**，点击先弹二次确认「重新识别将覆盖当前已核对数据，是否继续？」；点「取消」一个请求都不发 | `ContractsLedger.jsx:831` `:1805` `:1961` |
| 合同停在「草稿」，详情页找不到「转为生效」 | 底部加 **「确认生效」**，`PATCH /contracts/{id}/status {status:'active'}`；**只对草稿/待审核显示**（后端是直写接口，不收窄就能把"已完成"拉回"生效"） | `ContractsLedger.jsx:847` `:1947` |

配套：`docs/使用说明_合同OCR识别.md` 新增「重新识别」「确认生效」两节 + 4 条防呆 + 流程图；详细实现与反证见 `_contract_module/REPORT-TASKH-DETAIL-UX.md`。

---

## 二、封版四步曲 · 第一步：全量回归（12 台 / 327 项 / 0 红）

| # | 验证台 | 覆盖 | 结果 |
| --- | --- | --- | --- |
| 1 | `verify_taskH_detail_ux.mjs` | 详情页重新识别 + 二次确认 + 确认生效 | **22 / 22** |
| 2 | `verify_taskG_quick_create.mjs` | 黄条「+ 一键新建该客户」两遍流程 | **30 / 30** |
| 3 | `verify_taskF_ocr_fill.mjs` | OCR 回填精度 / 假选中 / 尾差 | **25 / 25** |
| 4 | `verify_taskF_precision.mjs` | 精度层 4 函数（纯函数台） | **24 / 24** |
| 5 | `verify_taskE_word_ui.mjs` | 四类单据 Word 导出（界面） | **18 / 18** |
| 6 | `verify_taskE_word_export.py` | Word 导出（接口 / 版式 / 中文 / 列宽） | **48 / 48** |
| 7 | `verify_taskD_word_guard.mjs` | 明细 0 行守卫 + 导出前置校验 | **21 / 21** |
| 8 | `verify_taskD_ocr_pdf.py` | 扫描件 PDF 解析（真实 6.5MB / 18 页） | **36 / 36** |
| 9 | `verify_contract_draft_ui.mjs` | 新建合同「智能优先」全流程 | **29 / 29** |
| 10 | `verify_contract_draft_api.py` | 草稿流 / tmp token / 冲突保护 | **23 / 23** |
| 11 | `verify_reverse_ui.mjs` | 红冲（界面：按钮/弹窗/红字行/二次拦截） | **24 / 24** |
| 12 | `verify_reverse_api.py` | 红冲（接口：行锁/一次性/applied_amount） | **27 / 27** |

**首轮不绿的三处，原因全部查明，且都不是业务代码问题：**

1. **G 台、F 台 E9** —— 你 14:55 手动建的「湖南华邦建设有限公司」还在客户档案里，导致"未匹配到客户"这个前置条件不成立（系统还很聪明地**按"唯一包含"规则模糊匹配**上了，连改成"…（临时隐藏）"都能匹配到）。临时用哨兵名隐藏后复跑，全绿。
2. **G 台、F 台 E9 第二次红** —— 真正原因是 **Puppeteer 默认 `protocolTimeout = 180 秒`**：扫描件 OCR 单次要 **53 ~ 320 秒**（同一台机器，冷/热差异），一超 180 秒连接就被测试台自己掐断，报「Waiting for selector failed」，看着像"识别没回填"。已在 6 个界面台统一加 `protocolTimeout: 900000`。
3. **C 台界面** —— 任务 G 为了修「点新建把下拉顶开」，把客户字段容器从 `<label>` 换成了 `div.cledger__field`，而 C 台还按 `label` 找元素 → 选择器过期。已改成 `label, .cledger__field` 双标签匹配。

> 这三条都记进 `REPORT-TASKH-DETAIL-UX.md` 与项目记忆了。**教训**：测试台报"识别没回填"时，先看等待上限和协议超时，再看业务。

---

## 三、封版四步曲 · 第二步：清理（归档，不销毁）

| 类别 | 处理 |
| --- | --- |
| 探针 / 诊断 / 验证脚本（`_probe_*` `_diag_*` `verify_*` `cleanup_*` `recon_*` `probe_*`） | 移到 `backup/20261019_final_cleanup/_contract_module/` |
| 临时补丁脚本（`frontend/scripts/_patch_*.py`、`_sweep_number_step.py`） | 移到 `backup/20261019_final_cleanup/frontend_scripts/` |
| 历史步骤目录（`_ui_kit_step1..3`、`_product_*`、`_partner_*`、`_menu_tree_refactor`、`_select_audit` 等 13 个） | 移到 `backup/20261019_final_cleanup/_legacy_steps/` |
| 回归日志 / 截图 / 一次性脚本 | 移到 `backup/20261019_final_cleanup/` |
| `data/contracts/tmp/` 草稿残留 | 已清空（本来就有 24h TTL，会自动清） |
| 数据库测试数据 | 删干净，见下表 |

**数据库核回基线（保留你手动建的那家客户）：**

| 表 | 封版值 | 说明 |
| --- | --- | --- |
| `contracts` / `contract_items` | **0** | 今天测试造的合同全删（含 A–H 各台夹具） |
| `customers` | **33** | 32 条存量 + 你 14:55 建的「湖南华邦（CUS20261019001）」——**没动你的** |
| `suppliers` | **68** | 测试供应商已删 |
| `quotations` | 5 | 存量 |
| `statements` | 1 | 存量 |
| `sales_orders` | 3 | 测试订单 4349–4352 已删（含明细与流水） |
| `purchase_orders` | 5 | A 台付款红冲用的 CGD20261019001 已删 |
| `financial_transactions` | 17 | 红冲/收款测试流水已清（凭证行 → 凭证 → 流水，顺序不能反） |
| `journal_entries` | 10 | |
| `products` | 262 | |

> 归档目录 25MB，想找回任何脚本直接去 `backup/20261019_final_cleanup/` 拿。

---

## 四、封版四步曲 · 第三步：备份

| 备份 | 路径 | 体积 |
| --- | --- | --- |
| 数据库（PG18 自定义格式，可 `pg_restore`） | `backup/erp_20261019_final.dump` | 757 KB |
| 全量源码 | `backup/源码全量_20261019_封版.zip` | 3.11 MB（466 个文件） |
| 任务 H 代码改动快照 | `backup/20261019_taskH_detail_ux/` | 136 KB |
| 测试脚本 / 探针 / 历史步骤归档 | `backup/20261019_final_cleanup/` | 25 MB |

**恢复数据库**（谨慎，会覆盖现有库）：

```bat
E:\AI\Postgres\bin\pg_restore.exe -h 127.0.0.1 -U erp -d erp --clean --if-exists ^
  "E:\AI\ERP软件\backup\erp_20261019_final.dump"
```

密码见本机 `E:\AI\ERP软件\.env` 的 `DATABASE_URL`（**该文件不在仓库内**，绝不写进文档）。

---

## 五、封版四步曲 · 第四步：打包桌面版 .exe 的指令

### 5.1 前置检查（三件，缺一不可）

```bat
cd /d E:\AI\ERP软件
if not exist .env  echo 缺少 .env（里面要有 DATABASE_URL）
if not exist frontend\dist\index.html  echo 前端没构建
findstr /C:"erp-pwa-v50" frontend\dist\sw.js >nul && echo sw 版本 OK
```

### 5.2 打包命令（两条）

```bat
cd /d E:\AI\ERP软件\frontend
npm run build

cd /d E:\AI\ERP软件
.venv\Scripts\python.exe -m PyInstaller erp.spec --noconfirm --clean
```

- `erp.spec` 已经把 **前端 dist**、`.env`、**rapidocr 模型、pymupdf 原生库、passlib 处理器**都打包进去了，不需要额外参数。
- 产物：`dist\ERP管理系统\ERP管理系统.exe`（onedir，旁边带 `_internal\`）
- 首次打包约 3–8 分钟；`--clean` 会清缓存，改动后建议保留。
- 打包前**必须**先 `npm run build`，否则打进去的是旧前端。**每次改前端记得先 bump `frontend/public/sw.js` 的 `CACHE_VERSION`**（现在是 v50）。

### 5.3 打包后验收（5 条，逐条过）

1. 双击 `dist\ERP管理系统\ERP管理系统.exe`，浏览器打开 `http://127.0.0.1:8010`；
2. 登录 `admin / Admin123` 能进；
3. 打开「合同台账」，随便点开一张（或新建一张）——页面不白屏、样式正常；
4. 上传一份 PDF 原件 → 「开始识别」→ 能出识别结果（**证明 rapidocr 模型打进去了**）；
5. 导出一份 Word（合同/报价单）→ 文件能打开、中文不是"等线"、表格不串列。

### 5.4 三个必须知道的注意事项

1. **端口 8010 不能被占**：`netstat -ano | findstr :8010`，有旧进程先 `taskkill /PID <pid> /F`。
2. **附件目录**：程序会把上传的原件写在 `_internal\data\contracts\`。**升级 exe 前请先把 `data` 目录拷出来**，否则换包后旧附件"看不见"（数据库记录还在，文件没了）。
3. **杀毒软件**：PyInstaller 单目录包偶发被误报，加白名单即可；`console=False`，出错时看同目录 `erp_error.log`。

---

## 六、系统全貌（封版时点）

| 维度 | 现状 |
| --- | --- |
| 技术栈 | 前端 Vite 5.4.21 + React 18.3.1（纯 JS，无 TS、无 router）；后端 FastAPI + SQLAlchemy；库 PostgreSQL 18；打包 PyInstaller |
| 端口 | 8010（`desktop_app.py`，纯 Web 后端，`uvicorn.run(host=0.0.0.0)`，局域网/手机 PWA 可访问） |
| 账套 | 多账套（按 token 切 schema，`get_db(request)` 路由注入，**业务路由禁用 `SessionLocal`**） |
| 菜单 | 后端 `menuTree` + 前端 `menuGroups` 双源；权限在 `PERMISSION_CATALOG`，新页 5 件套 |
| 单据 | 销售订单 / 采购订单 / 出入库 / 合同 / 报价单 / 对账单 / 发票 / 收付款流水 / 总账 |
| 单据状态 | 唯一权威 `app/core/doc_status.py`（draft→pending→approved→completed / draft→submitted→completed） |
| 财务 | 红冲（`reversal_of_id` 反查 + 行锁 + 负数流水 + `applied_amount`）；"已冲销"只有一个真相源 |
| OCR | 合同 OCR 双入口（详情页 / 新建「智能优先」），引擎 `contract_ocr.py` 纯函数；明细三形态；金额"宁可漏不可错" |
| 导出 | 合同 / 报价单 / 入库单 / 对账单 → Word（python-docx 逐 run 设 `w:eastAsia`、逐格设 `cell.width`、`w:tblHeader`、PAGE/NUMPAGES 域） |
| 离线 | PWA，`sw.js` 缓存外壳，`CACHE_VERSION` 每次发版必 bump |
| 版本号 | 唯一来源 `package.json`（vite 注入 `__APP_*__`），`app/main.py` 与 `sw.js` 同步 |

---

## 七、这几个月最贵的 10 条经验（已写进项目记忆）

1. **钱 ≠ 费率**：金额/合计/税额是"钱"（2 位）；单价/数量是"费率"（4 位不截断）。`73.901 × 580 = 42862.58`，抹成 `73.90` 就少 0.58 元——这就是那次"合计差 5 毛"的真身。合计必须**逐行金额累加**。
2. **`Math.round(n*100)/100` 会舍错 1.005**（二进制是 1.00499999…）→ 用 ``Math.round(Number(`${n}e2`))/100``。
3. **`step="0.01"` 是隐藏的价格改写器**：单价 3–4 位小数时浏览器报「请输入有效的值」，用户只能把价改成两位，于是顺手少钱。
4. **"假选中"**：`ErpSearchSelect` 只写 `displayValue` 不写 `value` → 框里有字、`party_id` 为空 → 校验拦住，用户看得见却存不了。回填必须"三条管道一起写"：id + name + 本地列表。
5. **`<label>` 里不能放按钮**：点按钮会连带激活 label 关联控件（把下拉顶开）→ 换同 class 的 `<div>`。
6. **`.modal-card` 有 `overflow:auto`**：小弹窗嵌进去会被裁，必须挂在父弹窗**外面**；Esc 要用捕获阶段 + `stopPropagation`。
7. **`table-layout:fixed` 下 `min-width` 完全无效**：只认首行 `<col>`/`<th>` 的 `width`。
8. **反证全绿 ≠ 稳**：可能是断言没写，也可能是**构建根本没换包**（本环境 `NODE_OPTIONS` 的删除拦截让 `rm -rf dist` EPERM）。反证前必须重构建 + 断言产物 mtime/清单变了。
9. **计时型假红**：扫描件 OCR 实测 45–322 秒；等待上限给到实测 2 倍，且**别忘了 Puppeteer 的 `protocolTimeout=180s`**。
10. **`from app.main import xxx` 会执行 `create_app()`**，顺手对三套真实账套跑 DDL —— 验证脚本绝不 import `app.main`。

---

## 八、已知限制与待办（都不影响封版）

| # | 事项 | 说明 |
| --- | --- | --- |
| 1 | 扫描件 OCR 无进度反馈 | 45–320 秒只有骨架屏，建议后端报页码 + 前端轮询 |
| 2 | 发票页「关联客户」下拉 | 12 张存量发票待认领；客户档案税号会重复 → 只认"名称全等"或"税号唯一" |
| 3 | 对账单 generate 四个断点 | 见 REFERENCE §I |
| 4 | 下拉框扫盲剩 35 处 | 批 3 |
| 5 | 菜单「开单管理」→「现货开单」 | 待做 |
| 6 | 合同/对账单「作废」「加行」入口 | 需求待定 |
| 7 | 7 条过期断言（App.jsx 拆分遗留） | 你明确"现在不修" |
| 8 | OCR 404 提示文案 | 建议对齐红冲的"请重启 ERP"引导 |

---

## 九、交付物索引

**报告**（`_contract_module/`）：TASKA 财务红冲 / TASKB 合同 OCR / TASKC 智能建合同 / TASKD OCR-PDF 修复 / TASKE 全单据 Word 导出 / TASKF 精度回填 / TASKG 一键新建客户 / **TASKH 详情页 UX（本次）**

**使用说明**（`docs/`，给不懂代码的人看）：`使用说明_合同OCR识别.md`（已更新到 v50） / `使用说明_全单据Word导出.md` / `使用说明_财务红冲.md` / `样张_Word导出/`

**打包与运维**：`erp.spec` / `desktop_app.py` / `启动ERP.bat` / `启动网页版.bat` / `配置局域网访问.bat` / `backup/backup.ps1`（每日 21:37 自动备份，保留 14 份）

---

## 十、收尾

这几个月，从"数据库连不上"到"327 项断言全绿"，中间踩过的坑几乎都变成了**代码里的护栏**和**说明书里的一句人话**：

- 钱和费率分开存，是因为真的有人少收了 5 毛；
- OCR 认出名字却不替你选客户，是因为"认错"比"认不出"贵得多；
- 重新识别要问一句，是因为那半小时的核对是你花的；
- 单据删不掉只能红冲，是因为账要留痕。

**现在这套系统，可以开始跑真账了。**

---

*封版：2026-10-19 · 版本 v1.0.0 · sw v50 · 数据库 `erp_20261019_final.dump` · 源码 `源码全量_20261019_封版.zip`*
