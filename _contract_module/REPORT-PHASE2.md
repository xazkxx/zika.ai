# 第 13 批 · 第二阶段交付报告（FastAPI 路由 + 文件上传）

> 前置：`DESIGN-PHASE1.md`（表结构与外键决策）
> 本阶段**只做后端接口**，前端一行没动。日期：2026-10-18

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 新增 / 扩展接口 | **22 个**（合同 5 + 客户文件 8 + 对账单 9） |
| 自检 | **140/140**（`_contract_module/verify_api_phase2.py`） |
| 既有接口回归 | 10 个高频列表接口全 200 + openapi 8 条新路径已注册 |
| 反证 | 3 组，全部按预期变红 |
| 测试数据 | 全部清理（客户/合同/对账单/磁盘文件/空目录） |

---

## 1. 接口清单

### 1.1 合同（扩展 `erp_sales.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/contracts/meta` | 新增 `directions`（in/out）、`ocr_statuses`（5 态）、`file`（白名单/上限） |
| GET | `/contracts?direction=in` | 按方向过滤；**同时兼容只写了 `contract_type` 的老数据** |
| POST | `/contracts` | `direction` 与 `party_type` 必须自洽（out→客户、in→供应商），否则 400 |
| POST | `/contracts/{id}/source` | **新**：上传原件（PDF / Word / 图片），替换旧的 |
| GET | `/contracts/{id}/source` | **新**：下载原件（二进制附件 / `Accept: json` 时 base64） |
| DELETE | `/contracts/{id}/source` | **新**：只删原件，合同还在 |
| PATCH | `/contracts/{id}/ocr` | **新**：回写 OCR 原始 JSON + 状态（pending/parsed/failed） |
| POST | `/contracts/{id}/ocr/review` | **新**：人工核对写回字段 + 置 `reviewed` |
| DELETE | `/contracts/{id}` | 扩展：删合同时**顺手删原件文件**，不留垃圾 |

### 1.2 客户文件归档（新模块 `erp_customer_file.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/customer-files/meta` | 5 个分类 + 允许格式 + 20MB 上限 |
| GET | `/customers/{id}/files` | 列表（分类 / 关键字 / 分页） |
| GET | `/customers/{id}/files/stats` | 按分类计数（抽屉 tab 徽标） |
| GET | `/customers/{id}/files/count` | 只要一个数字（列表行角标） |
| POST | `/customers/{id}/files` | multipart 上传；**按 sha256 去重** |
| GET | `/customer-files/{id}/download` | 下载（二进制 / base64） |
| PATCH | `/customer-files/{id}` | 改名 / 改分类 / 改备注（不换内容） |
| DELETE | `/customer-files/{id}?purge=true` | `purge=false` 只删记录、文件留盘 |

### 1.3 增强对账单（新模块 `erp_statement.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/statements/meta` | 方向 / 往来类型 / 发票状态 / 单据状态 / 来源类型 |
| GET | `/statements` | 方向 + 单位 + 状态 + 期间 + 关键字 |
| POST | `/statements` | 手工新建（合计**不收客户端值**，全由明细算） |
| GET | `/statements/{id}` | 头 + 明细 |
| PATCH | `/statements/{id}` | 改表头；传 `items` 则整单替换并重算 |
| POST | `/statements/generate` | **按单位 + 区间自动汇总合同/发票/收付款** → 草稿 |
| POST | `/statements/{id}/recalc` | 显式重算（唯一能让已发凭证变数的入口） |
| PATCH | `/statements/{id}/status` | draft → confirmed → sent；任意 → void |
| DELETE | `/statements/{id}` | 已确认/已发送不许删（只能作废） |
| POST/PATCH/DELETE | `/statements/{id}/items[/{item_id}]` | 明细行增改删（仅草稿态） |

### 1.4 客户删除守卫（`erp_archive.py`）

`DELETE /customers/{id}` 与 `DELETE /customers/batch` 都加了一道**不受 `force` 影响**的检查：

```json
{
  "status": 409,
  "detail": "客户「XX公司」不能删除：该客户名下还有 3 个归档文件（合同 / 资质 / 发票原件）。…请先到「客户 → 文件」里把需要的文件转存或删除，再删客户。"
}
```

批量删除里对应 `blocked` 一组（`category: "files"`），其他客户照常删掉。

---

## 2. 六个关键决策（都不是随手写的）

### 2.1 归档文件拦截**不接受 `force`**

普通引用（"开过单的客户不能删"）是业务上的不方便，用户确认后可以 `force=true` 越过。
归档文件是**客户自己的资料**，外键是 `ON DELETE RESTRICT` —— `force` 越不过去，
硬越只会得到 `IntegrityError` 500。所以直接在应用层拦成 409，并说清"要怎么才能删"。

**并且**在 `db.commit()` 外面包了一层 `IntegrityError → 409` 兜底：
将来若再有新表挂 RESTRICT，也不会把 500 抛到界面上。

### 2.2 OCR 只存不解析

`ocr_json` 存引擎原始输出（Text），不改任何业务字段；核对结论单独一个 `ocr_status`。
`/ocr/review` 是**唯一**能把状态推到 `reviewed` 的入口，且：
- 白名单字段（不含 `total_amount` / `contract_no` / `status` —— 不让核对接口开后门绕过业务规则）；
- 一个字段都没传 → 400（避免"字段名写错"被当成"核对完成"），要确认无改动必须显式 `confirm_empty=true`。

### 2.3 上传按**文件头**认格式，不认扩展名

`%PDF` → pdf；`PK\x03\x04` → docx；`D0CF11E0` → doc（老 Word）；
PNG/JPEG/WEBP/BMP/TIFF 各自魔数。认不出直接 400。

> 顺手修了一个**存量坑**：`file_storage._ALLOWED_SUFFIXES` 里没有 `.doc/.docx`，
> Word 合同会被静默改名成 `.bin`（下载下来双击打不开）。已把两种 Word 后缀加进白名单
> （`.exe/.bat/.cmd/.ps1/.js` 仍然没有，执行面没有变化）。

### 2.4 上传先去重再落盘

同一个客户下同一份内容（sha256 相同）不再产生第二条记录，返回 **200 + `duplicate: true`**
（而不是 201）。前端据此提示"这份文件已经在库里了"。

### 2.5 对账单：**只有草稿能改**

`status != draft` 时明细、重算一律 409；已确认/已发送不许删，只能作废。
理由：对账单是用来"证明双方账目一致"的东西，两份打印稿数字不同就等于没有对账单。

### 2.6 `opening_balance` 不回写

`compute_totals()` 的返回值里带 `opening_balance`（方便调用方），
第一版 `_apply_totals` 照着全量 `setattr` —— **反证 C 直接踩到**：重算时传 0，
库里的期初就被抹成 0，应收余额凭空少了一个期初。
现在显式跳过这一列，并在代码里写清了原因。

---

## 3. 反证（断言必须能变红）

| 组 | 改坏什么 | 结果 |
|---|---|---|
| A | `_assert_editable` 的 `status != draft` 改成永假 | **119/120**，红：`C29 已确认后重算 → 409` |
| B | `_customer_file_block` 直接 `return None` | **116/118**，红：`B29 409 文案不含「归档文件」`、`B32 批量删除接口` |
| C | `_apply_totals` 用 `opening_balance=0` | **117/120**，红：`C11`、`C17`、`C21b`（三处都是应收余额少一个期初） |
| — | 全部还原 | **140/140** 重新全绿 |

**反证 B 顺带验证了一件重要的事**：即使应用层拦截被删掉，数据库的 `RESTRICT` 也会把删除挡住，
最终仍然是 409（走 `IntegrityError` 兜底）而不是 500 —— 只是文案退化成通用说法。
这就是"两道防线"该有的样子。

---

## 4. 自检跑出来的 4 个真问题（已修）

1. **`StatementItemCreate(merged)`** —— pydantic v2 不接受位置参数，接口直接 500。改成 `**merged`。
2. **`SAWarning: DELETE ... expected to delete 2 rows, 0 matched`** ——
   `db.query(...).delete()` 绕过 session，而 `Statement.items` 是 `lazy="selectin"`，
   commit 时 delete-orphan 又删一遍。已在批量删除后 `db.expire(row, ["items"])`。
3. **`_apply_totals` 回写 `opening_balance`** —— 见 2.6，反证才发现。
4. **空目录堆积** —— 逐个删文件后 `data/customer-files/<id>/` 会留下空目录（跑一轮测试留 11 个）。
   已在删除文件后 `rmdir`（只在目录为空时成功，失败即忽略）。

另外两条是**验证台自己的错**，值得记下来：
- `C21 应收余额跟着合同额变` —— 公式里根本没有合同金额（= 期初 + 已开票 − 已收 − 预收核销），
  是我把断言写错了；改成同时改 `invoiced_amount` 后才有意义。
- 批量删除路径是 `DELETE /customers/batch`（不是 `/batch-delete`）。

---

## 5. 怎么验（你重启之后）

```powershell
# 1) 重启服务（无 --reload，改后端必须重启）
#    双击 启动ERP.bat

# 2) 一键自检（用的是 ASGI 内存调用，不占端口、不受 HTTP_PROXY 影响）
.venv\Scripts\python.exe _contract_module\verify_api_phase2.py
# 应打印：通过 140/140
```

手工看两个最直观的：

```bash
# 合同原件上传（把路径换成一份真实 PDF）
curl --noproxy '*' -X POST "http://127.0.0.1:8010/api/v1/contracts/1/source" -F "file=@D:/某合同.pdf"

# 对账单自动生成（direction=out + 客户 3 + 2026 全年）
curl --noproxy '*' -X POST "http://127.0.0.1:8010/api/v1/statements/generate" \
  -H "Content-Type: application/json" \
  -d "{\"direction\":\"out\",\"party_id\":3,\"period_start\":\"2026-01-01\",\"period_end\":\"2026-12-31\"}"
```

---

## 6. 已知限制（第三阶段处理）

1. **`/statements/generate` 的发票匹配靠名称**：`invoices` 表只有 `counterparty_name`，
   没有 `customer_id`。名称改过、或有重名时匹配不到 → 生成的是草稿，必须人工核。
2. **导出（Excel / PDF）还没做** —— 这是你原始需求里的"全单据导出"，留给第三阶段，
   和前端一起做才有意义（打印模板已经有一套 `erp_print.py` 可以复用）。
3. **前端零改动**：合同台账的进/出切换、客户文件抽屉、对账单编辑器都还没有界面。
4. **客户文件没有"转存到别的客户"接口** —— 目前只能下载后重传（够用，但不是最好）。

---

## 7. 改动清单

| 文件 | 动作 |
|---|---|
| `app/api/v1/routes/erp_sales.py` | 合同 direction/过滤/校验、原件 5 个接口、报价单 `contract_id`、删合同删原件 |
| `app/api/v1/routes/erp_customer_file.py` | **新建**（8 个接口） |
| `app/api/v1/routes/erp_statement.py` | **新建**（9 个接口） |
| `app/api/v1/routes/erp_archive.py` | 删客户 / 批量删客户：归档文件硬拦截 + `IntegrityError → 409` |
| `app/api/v1/routes/erp.py` | 注册两个新 router |
| `app/core/file_storage.py` | 白名单补 `.doc` / `.docx` |
| `_contract_module/verify_api_phase2.py` | **新建**（140 项自检） |

备份：`_contract_module/backup/20261018_phase2/`（改前的 4 个文件）。
