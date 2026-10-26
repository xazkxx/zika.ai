# 任务 C 交付报告：新建合同「智能优先」流程重构

> 2026-10-19 · 承接任务 B（合同 OCR）之后
> 用户原话：「现在的设计是"先填表 → 保存 → 进详情上传文件去识别"……请立刻重构新建合同的流程，改成真正的'智能优先'」

---

## 一、先回答一个问题：后端要不要大改？

**不需要。** 现有 OCR 引擎（`contract_ocr.py` 的 `extract_text` / `parse_fields`）是**纯函数**——输入字节 + 文件名 + 方向，输出候选字段，**完全不依赖合同记录**。阻碍只在入口设计上：

| 现有接口 | 依赖 | 新流程能不能用 |
| --- | --- | --- |
| `POST /contracts/{id}/source` | 合同必须已存在 | ❌ 新建时没有 id |
| `POST /contracts/{id}/ocr` | 按 `contract_id` 读 `source_file_path` | ❌ 同上 |

所以**没有采用"先建草稿合同"**（那会污染合同台账、要处理废弃草稿、单号被吃掉），而是加了一条**平行通道**：

```
POST /contracts/ocr/upload      （multipart，无 ID）→ 落 contracts/tmp/，返回 temp_token
POST /contracts/ocr/recognize   （{temp_token, direction}）→ 直接返回识别结果，不落库
POST /contracts                 （原来就有）→ 多了 source_temp_token：把 tmp 文件搬进正式目录
DELETE /contracts/ocr/upload?token=…  → 换文件/关弹窗时丢弃
```

**总改动量**：后端 +230 行（3 个新路由 + 4 个辅助函数 + 创建接口 40 行），`contract_ocr.py` **零改动**，旧详情页流程**一行未动**（`/contracts/{id}/ocr` 只是内部改为调用共用的 `_recognize_contract`）。

> 折中备选（未采用）：在 `POST /contracts` 时先建 draft、再识别、再 PATCH 回填。缺点：台账里会出现一堆 `draft` 空合同、占合同号、用户中途放弃就是垃圾数据。**临时目录方案把这些副作用都关在 tmp/ 里，24 小时自动清。**

---

## 二、后端改动（2 个文件）

### `app/api/v1/routes/erp_sales.py`（2326 行）

| 位置 | 改动 |
| --- | --- |
| 常量区 | `CONTRACT_DRAFT_SUBDIR = "contracts/tmp"`、`CONTRACT_DRAFT_TTL_HOURS = 24`、`_DRAFT_TOKEN_RE`（白名单：`contracts/tmp/<12hex>-draft.<真实后缀>`） |
| 新增辅助 | `_draft_rel(token)` 校验 token 形状 + 文件存在；`_purge_stale_drafts()` 上传时顺手清 24h 前的垃圾；`_recognize_contract(raw, filename, direction)` **识别+解析的唯一实现**；`_ocr_result_payload(...)` 两个识别接口共用的返回结构 |
| 新增路由 | `POST /contracts/ocr/upload`（校验口径与旧上传完全一致：空文件/20MB/按文件头嗅探格式）、`POST /contracts/ocr/recognize`（不落库）、`DELETE /contracts/ocr/upload`（幂等） |
| `run_contract_ocr` | 内部改为调用 `_recognize_contract` + `_ocr_result_payload`，**行为不变**（旧接口台 21/21 回归通过） |
| `create_contract` | `model_dump(exclude={... "source_temp_token","source_file_path","source_file_name","source_file_size","source_file_mime"})` —— **客户端传的路径一律不信**；有 `source_temp_token` 时由后端搬文件、写 `source_*`、删 tmp；`db.commit()` 失败时回删已搬文件（不留孤儿） |

### `app/schemas.py`

`ContractCreate` 加 `source_temp_token: Optional[str] = None`（原有的 `source_file_*` / `ocr_json` / `ocr_status` 本来就在，创建时能直接落库）。

---

## 三、前端改动（2 个文件）

### `ContractsLedger.jsx`（1655 行）

- 删掉 `pendingFile`（旧"保存后上传"），换成草稿状态机：`draftFile`（已暂存）/ `draftUploading` / `draftOcr` / `draftOcrRunning` / `draftError` / `draftConflict` / `draftApplied`
- 新建弹窗**顶部**新增「合同原件与智能识别」区块（原来在底部、且只是占位说明）
- `pickDraftFile()`：选文件即上传到 tmp/；换文件先丢弃旧的
- `startDraftOcr()`：调 `/ocr/recognize` → 表单空则自动填；**表单有内容则只弹冲突条，一个字不动**
- `filledLabels()`：判定"用户填过什么"，**排除表单默认值**（标题=销售合同/采购合同、日期=今天、税率=13%）
- `applyDraftOcr(pack, strategy)`：`empty-only` 只补空（备注只写回填说明、不抢用户的话）；`overwrite` 整块替换；`auto` 走 empty-only
- `submitForm()`：`source_temp_token` + `ocr_json` 随合同一次提交；`ocr_status` 按实际采用情况给 `reviewed`（用了识别结果）或 `parsed`（识别过但"暂不填充"）
- `closeCreate()`：丢弃 tmp 文件

### `contractsLedger.css`

`.cledger__draft*`（区块 / 上传行 / 明细预览表 / 黄色冲突条 / 绿色已应用提示）。

### `frontend/public/sw.js`

`CACHE_VERSION` → **`erp-pwa-v45`**。

---

## 四、验证结果

### 接口层 `verify_contract_draft_api.py` — **23/23 全绿**

上传（无 ID）→ 临时目录 → 识别（不落库）→ 保存（搬文件+落 ocr_json）→ 原件可下载且字节一致；路径穿越 400、直传 `source_file_path` 被忽略、不存在 token 404、丢弃幂等、24h 过期清理、采购方向认乙方、Word 可存不可识别。

### 界面层 `verify_contract_draft_ui.mjs` — **29/29 全绿**（真 Chrome）

场景 A（空表单）：区块存在→按钮初始灰→选文件暂存→骨架屏→自动填入（标题/客户档案/明细/字段卡片）→保存→详情打开、原件「已上传」、状态「已人工核对」。
场景 B（已手填）：手填标题+客户 B → 识别（认出甲方 A）→ **冲突条出现且点出"合同标题、客户"** → 标题/客户**一字未改** → 点「仅填充空白字段」→ 手填项保留、付款条款与明细被补上 → 提示「已只填入空白项」。

### 反证 4 组（break → 红 → restore → 绿，`grep PROBE` = 0）

| 反证 | break 点 | 结果 |
| --- | --- | --- |
| A token 校验 | `if not _DRAFT_TOKEN_RE.match` → `if False` | **仅 D10 红**（404 而非 400） |
| B 文件搬家 | `if payload.source_temp_token:` → `if False` | **D5b/D6/D6b/D9/D10 五红**（无原件、tmp 不删、下载 404） |
| C 冲突检测 | `if (filled.length === 0)` → `if (true)` | **E6b/E6c/E7e 三红**（不弹冲突条） |
| D 覆盖保护 | `overwrite = strategy === 'overwrite'` → `true` | **E7a/E7b 双红**（手填标题/客户被覆盖） |

> ⭐ 反证 C/D 分开做才看清：**冲突检测与覆盖保护是两层**。C 把检测打掉后，D 那层仍在守（手填内容没被盖）——这正好证明"就算误判了空表单，也不会毁掉用户数据"。

### 回归（旧流程一点没坏）

- `verify_contract_ocr_api.py` **21/21**
- `verify_contract_ocr_ui.mjs` **22/22**

---

## 五、清理与快照

- `cleanup_contract_ocr.py`（扩展了本轮 3 个客户名前缀）：删原件文件 15 / 合同明细 33 / 合同 17 / 客户 22，残留 0
- `data/contracts/tmp/` 残留草稿 3 个（反证时人为制造的）已清空
- 快照 `backup/20261019_taskC_smart_create/`（10 文件，含验证/反证/清理脚本与新使用说明）

---

## 六、部署提醒

`desktop_app.py` **无 --reload**：请重启「启动ERP.bat」，否则三个新路由都是 404。前端已即时生效（v45，需强刷一次）。

---

## 七、边界与已知取舍

1. **临时文件 24h 自动清**：靠"下次上传时顺手清"，不引入定时任务。若长期无人上传，垃圾会一直躺着（体积很小，可接受）。
2. **`ocr_status` 语义**：只有"识别过 + 采用了"才写 `reviewed`；"暂不填充"写 `parsed`（详情页仍要求再点一次确认，不撒谎）。
3. **只支持单文件**：一份合同对应一个 PDF/图片；多张照片需要自己合成 PDF（引擎本身也只吃一个文件流）。
4. **识别不落库**（预识别）：结果只在前端内存里；页面刷新/关弹窗即丢，需要重新识别（避免产生"没有合同的识别记录"）。
