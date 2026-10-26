# 第一步（后端）：状态白名单 + 发票关联字段迁移

> 2026-10-18 晚。**只改后端**，前端一行未动（按你的要求，等你跑完迁移再动 `OrderBoard.jsx`）。
> 快照：`_contract_module/backup/20261018_step1_backend/`（7 个文件 + 2 个测试）。

---

## 一、改了什么（精确行号）

| 文件 | 行号 | 改动 |
| --- | --- | --- |
| `app/core/doc_status.py` | **新建 161 行** | 状态唯一权威：白名单 + 两类流程 + 流转表 + 中文错误 |
| `app/api/v1/routes/erp_sales.py` | `:13` | 引入状态机 |
| 同上 | `:388-408` | `PATCH status` 改走 `assert_transition()` |
| 同上 | `:450-460` | `to-outbound` 加「必须审核通过」闸口 |
| `app/api/v1/routes/erp_purchase.py` | `:9` | 引入状态机 |
| 同上 | `:299-313` | `PATCH status` 改走 `assert_transition()` |
| 同上 | `:328-338` | `to-inbound` 加同一道闸口 |
| `app/models/invoice.py` | `:52-59` | 新增 `customer_id` / `contract_id`（可空 + 索引） |
| `app/main.py` | `:223-231` | `INVOICE_ADDITIONS` 补两列（启动自动补列，幂等） |
| `app/schemas.py` | `:651-652` / `:666-667` | `InvoiceCreate` / `InvoiceUpdate` 接受这两个字段 |
| `app/api/v1/routes/erp_invoice.py` | `:850-876` | 新增 `_normalize_party_name()` / `_resolve_customer_id()` |
| 同上 | `:963-976` | 手工建发票时，销项自动挂客户 |
| 同上 | `:1058-1075` | OCR 识别入库时同样自动挂 |
| 同上 | `:915-918` | 出参带上 `customer_id` / `contract_id` |
| `tests/test_order_doc_type.py` | 转单两处 + 新增 2 个用例 | 适配"先审核再转单"，并锁住两类流程的分界 |

**新文件**：`_contract_module/migrate_20261018_invoice_links.py`（迁移）、`verify_backend_step1.py`（12 条验证）、`probe_backend_step1.py`（2 组反证）、`baseline_check_20261018.py`（改前对照）。

---

## 二、状态机（`app/core/doc_status.py`）

`PATCH /sales-orders/{id}/status` 与 `/purchase-orders/{id}/status` 现在：

- **未知状态码 → 400**，detail 里直接列出允许值（中文界面能原样显示）
- **缺 status → 400**（改造前默认塞 `submitted`，等于静默放行）
- **非法流转 → 409**，detail 写清"当前是「已审核」，不能直接改成「草稿」。允许的下一步：已完成 / 已取消 / 待审核"
- **同状态幂等**（双击不报错）

### 两类流程（关键设计）

| doc_type | 流程 | 理由 |
| --- | --- | --- |
| `order`（销售订单 / 采购订单） | `draft → pending → approved → completed`（`cancelled` 从非终态可达） | 制单 → 审核 → 转单 |
| `outbound` / `inbound`（现货开单 / 入库单） | `draft → submitted → completed` | 柜台现货，没有审核环节 |

**为什么不搞一套统一流程**：现货开单是"客户上门拿货"，加审核等于给收银台加一道签字流程；
反过来，订单不审核就能转出库，等于库存和应收都能凭空产生（这就是改造前的状态）。
所以按 `doc_type` 分两条，各自的合法集不交叉：现货单塞 `approved` 会 400，订单塞 `submitted` 会归一成 `pending`。

**历史值兼容**：改造前所有订单建出来都是 `submitted`。`normalize_status()` 在**订单**上把
`submitted` 归一成 `pending`（待审核）—— 所以老订单点「转单」会被拦一次，**必须先点「审核」**。
这是刻意的：那批订单确实没人审过。

---

## 三、发票加字段 + 迁移结果

### 3.1 迁移做了什么（脚本已执行，幂等）

```
合计：新增列 6 · 新增索引 6 · 回填发票 0 张 · 销项对不上 0 张 · 税号歧义 12 张
```

- 三个 schema（`public` / `co_02` / `co_03`）各加 `customer_id`、`contract_id`（可空 INTEGER）
- 各建两个索引 `ix_invoices_customer_id` / `ix_invoices_contract_id`
  （`_add_missing_columns` 只补列不建索引，索引必须在脚本里建）
- 第二次执行：`新增列 0 · 新增索引 0`（幂等已实测）

### 3.2 ⚠️ 回填结果：12 张发票全部留空，原因值得你看一眼

发票购买方是《陕西送变电工程有限公司》，税号 `916101332206045948`。
客户档案里**有 3 条记录共用这一个税号**：

| id | 客户名 |
| --- | --- |
| 705 | 西安东750千伏变电站330千伏送出工程（包2） |
| 709 | 西安渼陂110千伏输变电工程（线路工程) |
| 714 | 陕西送变电第一分公司 |

税号无法定位到唯一客户，名称又完全对不上（发票是"总公司"，档案是"分公司/项目部"）。
**脚本选择了留空**，并把每一张列出来 —— 挑一个挂上去会让 8 张发票算进别人的对账单，
比暂时挂不上更糟。

**怎么办（三选一，需要你定）**：
1. 在客户档案里补一条真正的《陕西送变电工程有限公司》（税号同），把发票挂它 —— 最干净；
2. 手工在发票上指定客户（`PATCH /invoices/{id}` 已支持 `customer_id`，**第二步我会在发票页加这个下拉**）；
3. 先清理档案里重复税号的三条记录，再重跑迁移脚本（它会把唯一命中自动挂上）。

> 迁移脚本默认**预演**，加 `--apply` 才写库。你已经可以直接重跑确认它是 0 变更：
> ```
> .venv\Scripts\python.exe _contract_module\migrate_20261018_invoice_links.py --apply
> ```

---

## 四、验证

| 项 | 结果 |
| --- | --- |
| `pytest tests/test_order_doc_type.py` | **9 passed**（原 7 + 新增 2） |
| `pytest tests/test_crud.py` | 4 passed |
| `_contract_module/verify_backend_step1.py` | **12 / 12** |
| `probe_backend_step1.py`（反证 2 组） | 全部命中预期红，还原后 12/12 复绿 |
| 全量 `pytest tests/` | 444 passed / 13 failed（**13 条全部是改前就存在的**，见 §4.2） |

### 4.1 验证台覆盖的 12 条

V1 未知状态码 400 · V2 缺 status 400 · V3 待审核跳级已完成 409 · V4 待审核→已审核 200 ·
V5 同状态幂等 · V6 已审核→草稿 409 · V7 未审核转单 409（提示含"审核"）· V8 审核后转单 200 ·
V9 现货单 submitted→completed 仍可用 · V10 现货单塞 approved 400 ·
V11 销项发票按名称自动挂客户 · V12 税号命中多客户时留空不猜

### 4.2 反证（改坏 → 变红 → 逐字节还原）

| 组 | 改坏什么 | 变红的断言 |
| --- | --- | --- |
| A | `to-outbound` 守卫改成 `if False and …` | **只有 V7** |
| B | `assert_transition` 直接返回目标值 | V1、V2、V3、V6（另带 V8、V10 一起红） |

### 4.3 那 13 条既有失败（不是本批引入，有对照实验）

用 `baseline_check_20261018.py` 把本批 6 个后端文件换回备份版本，跑其中 4 条，**同样红**：

```
对照结论：以上失败在改前版本上同样存在
现场已恢复：逐字节一致
```

13 条分两类：
- **前端字符串过期**（9 条）：`App.jsx` 拆分后，`发票管理`/`往来对账`/`nav theme`/`项目状态`/`报表` 的
  字符串已搬到 `pages/*.jsx`，测试还在 `App.jsx` 里找 → 就是 MEMORY 里记的"7 条过期断言"那一类；
- **测试自身不严谨**（1 条）：`test_sales_return` 断言"全库没有 sales_return 流水"，
  而库里有一条 2026-10-17 的真实退货流水 `#12093`（`XSTH20261017001`）→ 与本次改动无关；
- 其余 3 条同属上述两类（dictionary seed / project cost / print registry）。

按你之前定的"过期断言现在不修"，本批一条都没碰。

---

## 五、你现在要做的一步

**重启 8010**（`启动ERP.bat`）。后端改动必须重启才生效；不重启的话前端点「审核」会 404/409 混乱。

重启后可以手工验一遍（或直接等第二步做完一起验）：

1. 销售管理 → 销售订单 → 新建一张 → 状态是「已提交」（改造前就这样）；
2. 点「转开单」→ 会被拦，提示"当前是「待审核」，必须先审核通过"；
3. 调 `PATCH /api/v1/sales-orders/{id}/status {"status":"approved"}` → 200；
4. 再点「转开单」→ 成功。

> 第二步会把 `approved` / `pending` 的中文标签和「审核」按钮补上，那时就不用调接口了。

---

## 六、回滚

```powershell
cd E:\AI\ERP软件
copy _contract_module\backup\20261018_step1_backend\*.py app\ 2>$null   # 按文件名逐个覆盖回去
# 精确对应：
#   erp_sales.py / erp_purchase.py / erp_invoice.py → app\api\v1\routes\
#   invoice.py → app\models\
#   schemas.py / main.py → app\
del app\core\doc_status.py
# 数据库两列可以留着（可空，不影响旧代码）
# 测试若也要回滚：copy _contract_module\backup\20261018_step1_backend\tests\*.py tests\
```

---

## 七、第二步预告（等你确认这条消息后再动前端）

1. `lib/appLib.js` 新增 `ORDER_STATUS_LABELS`（draft 草稿 / pending 待审核 / approved 已审核 / completed 已完成 / cancelled 已取消 / submitted 已提交）；
   **不动**全局 `DOC_STATUS_LABELS`（被十几个单据模块共用）；
2. `components/docs/OrderBoard.jsx` 操作列加「审核」（`draft|pending` 可见）+「收款/付款」（`approved|completed` 可见）；
3. 新建 `OrderPaymentDialog.jsx`，调 `POST /finance/receipt|payment`（带 `order_id`，后端会自动冲抵并重算欠款链）；
4. 菜单：`开单管理` → **现货开单**；`销售出库（多单位）` 下架并入；
5. 发票页加「关联客户」下拉（`customer_id`），解决那 12 张挂不上的发票；
6. `sw.js` bump 到 `erp-pwa-v37`。
