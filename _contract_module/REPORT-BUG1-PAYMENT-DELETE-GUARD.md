# Bug 1 修复报告：带资金流水的单据删不掉

日期：2026-10-18　｜　范围：后端 3 个文件 + 前端 2 个文件 + sw v40
验证：`_contract_module/verify_bug1_payment_delete_guard.mjs` **35/35**（含两轮反证）
后端回归：`pytest tests/test_delete_endpoints.py tests/test_order_doc_type.py tests/test_order_settlement_and_finance_link.py` → **37 passed**

---

## 一、真相：不是"闸口没查 related_order_id"，而是删错了对象

用 `operation_logs` 把 XSD20261018001 的完整操作链还原出来（public 账套）：

| 时间 | 动作 | 结果 |
|---|---|---|
| 21:18:27 | POST /sales-orders | 建**订单** #4230 `XSD20261018001` |
| 21:18:52 | POST /finance/receipt 1000 | 收款挂在 **#4230**（`related_order_id=4230`） |
| 21:18:55 | POST /sales-orders/4230/to-outbound | 生成**开单** #4231（`source_order_id=4230`），订单置 completed |
| 21:19:24 | **DELETE /sales-orders/4231** | **204 成功** |

用户点的是列表里那张**开单**（#4231），钱挂在**订单**（#4230）上。
旧闸口只回答"**这张单自己**有没有收付款"，对 #4231 回答"没有" → 放行。

后果比"删了张单"严重得多：订单 #4230 停在 `completed`，
`to-outbound` 挡 completed（不能重新转单）、`has_payment_flow` 挡删除（收过款不能删）
= **一张谁都动不了的死锁单**，而且它的 1000 元收款仍然挂在账上，出货那张单却没了。

诊断脚本：`_contract_module/diag_delete_bypass.py` / `diag_delete_logs.py` / `diag_4230.py`

---

## 二、后端修了两个洞

### 1. 匹配条件从单字段改成双字段（`erp_common.py`）

原来只查 `related_type in ('receipt','payment')`。但 `POST /finance` 手工登记
只写 `transaction_type`、`related_type` 留空 —— 这类流水会被漏掉。

```python
# _order_payment_flows()
return (
    db.query(FinancialTransaction)
    .filter(
        FinancialTransaction.related_order_id == order_id,
        or_(  # ← 双字段
            FinancialTransaction.transaction_type.in_(("receipt", "payment")),
            FinancialTransaction.related_type.in_(("receipt", "payment")),
        ),
    )
    .all()
)
```

### 2. 新增"来源订单"闸口（`_assert_source_order_no_payment`）

删开单（销售开单 / 采购入库单）之前，先看它 **`source_order_id` 指向的订单**有没有资金流水。

```python
# erp_sales.py:431-435（采购侧 erp_purchase.py:401-404 同构）
_assert_no_payment_flows(db, order_id, item.order_no or f"#{order_id}")
if item.source_order_id:
    _assert_source_order_no_payment(db, db.get(SalesOrder, item.source_order_id), "销售开单")
```

两个闸口都排在 `_revert_stock` / `_revert_finance` **之前** —— 先动库存再报错，
session 里已经排队的删除会在别处被 flush 出去。

### 3. 409 的 detail 是**结构化对象**，前端据此分流

```json
{ "code": "has_payment_flow",
  "message": "单据 XSD20261018001 存在资金流水 1 笔（收款 ¥1000.00），无法删除。",
  "hint": "收付款是真实资金记录，删单会让这笔钱变成无主账（孤儿流水）…请保留该单据；金额登错就再登记一笔冲销/退款。",
  "flow_count": 1, "receipt_amount": 1000.0, "payment_amount": 0.0 }

{ "code": "has_source_payment_flow",
  "message": "该销售开单由订单 XSD20261018001 转入，而该订单已登记资金流水 1 笔（收款 ¥1000.00），无法删除。",
  "hint": "删掉这张开单后，订单会停在「已完成」——既不能重新转单、又因为收了款不能删…",
  "source_order_id": 4230, "source_order_no": "XSD20261018001", ... }
```

⚠️ 这两个 code **绝不能**落进原有「409 → 强制删除」那条档案类分支 —— 那等于给"抹真实资金记录"开后门。
`App.jsx:1824-1841` 先按 code 集合识别（订单类 kind 限定），命中就直接弹拦截 modal 并 `return`。

---

## 三、前端补了两个"没报错"的缺口

| 缺口 | 现象 | 修复 |
|---|---|---|
| `App.jsx:1852` `throw new Error(errorData.detail)` | detail 是对象时提示变成 `[object Object]` | 先取 `message + hint` 拼中文，兜底 `删除失败` |
| `SalesOrderUnitsBoard.jsx` 的 `readError()` 只认字符串 detail | 409 退化成「请求失败（HTTP 409）」，正是用户截图里那个页面，看着像"没什么报错" | 增加结构化 detail 分支，输出 `message；hint` |

拦截 modal 本身（`data-delete-blocked`）只有一个「我知道了」按钮，
**没有** 强制/继续删除 —— 这个场景不存在"确认一下就能删"。

---

## 四、验证矩阵（35 项，两层）

### 接口层
- A4-A7：删"自己收了款"的订单 → 409 `has_payment_flow`，**单据仍在库**
- B2-B6：删"钱在来源订单上"的开单 → 409 `has_source_payment_flow`，**开单在、订单仍 completed（没被推进死锁）**
- C1-C3：`POST /finance` 手工登记（`related_type` 为空）→ 同样 409
- E1-E3：采购侧入库单 → 409 `has_source_payment_flow`
- F1-F2：**没有任何资金流水的订单照样 204 删掉**（闸口不是一刀切）

### 界面层（真 Chrome）
- G1：浏览器加载的 bundle = `dist/index.html` 里本次构建的 hash（防 SW 喂旧包）
- G3-G7：销售出库（多单位）页点删除 → 页面出现「…无法删除」并点名来源订单，**行还在**
- H2-H6：订单页点删除 → 专用拦截弹窗，正文含「无法删除」、hint 提到冲销/退款、**无强制删除按钮**
- H7：全程无 JS 异常（预期内的 409 网络日志精确放过，其余不放行）

### 反证（break → red → restore）

| 反证 | 改动 | 结果 |
|---|---|---|
| A | `_order_payment_flows` 退回只查 `related_type`；`_assert_source_order_no_payment` 开头 `return` | **22/35**，红的是 B2/B3/B4/B5、C2/C3、E2/E3、G3-G7 —— 与改坏点一一对应 |
| B | 前端 `readError` 去掉对象分支（重建 dist） | **33/35**，只红 G5/G6（且 G7 仍绿：单据确实没被删，只是文案退化） |

反证 A 里 B2 变 **HTTP 204** —— 当场复现了用户遇到的"删成功"，证明这条断言有牙。
恢复后 `grep -c PROBE` = 0（前后端均 0）。

---

## 五、数据体检：全库无孤儿账

`cleanup_bug1.py` 先体检后清理，三个账套（public / co_02 / co_03）：

```
【public】  ✅ 无孤儿流水（所有收付款都能追到单据）
【co_02】   ✅ 无孤儿流水
【co_03】   ✅ 无孤儿流水
```

体检 SQL 按 `related_type` 找**对应的表**（receipt/payment → 销售/采购单，
sales_return → sales_returns）。第一版只比对 sales_orders 把
`#12093 receivable/sales_return → 605` 误报成孤儿，实际 605 在 `sales_returns` 里 —— 已修正。

清理脚本自己也踩了一个坑并写进注释：SQL 硬删单据时，系统生成的
应收/应付（`related_type=sales_out/purchase_in`，note 不含测试前缀）不会被按 note 过滤掉，
必须先按 `related_order_id` 删流水再删单据，否则"清理脚本自己造孤儿"（实测多出 6 条）。

---

## 六、改动清单

| 文件 | 换行 | 改动 |
|---|---|---|
| `app/api/v1/routes/erp_common.py` | CRLF | `:33` 引入 `or_`；`:346-475` `_order_payment_flows` / `_payment_flow_amounts` / `_assert_no_payment_flows`（重写文案）/ `_assert_source_order_no_payment` |
| `app/api/v1/routes/erp_sales.py` | CRLF | `:89-90` 引入；`:427-435` 两个闸口 |
| `app/api/v1/routes/erp_purchase.py` | CRLF | `:38-39` 引入；`:399-404` 两个闸口 |
| `frontend/src/App.jsx` | CRLF 11454 | `:1824-1841` 409 code 分流；`:1852-1859` 失败文案取 message/hint |
| `frontend/src/components/sales-units/SalesOrderUnitsBoard.jsx` | LF | `readError()` 支持结构化 detail |
| `frontend/public/sw.js` | LF | `CACHE_VERSION` → `erp-pwa-v40` |

快照：`backup/20261018_step5_bug1_guard/`（7 文件）

---

## 七、上线口径

1. **重启后端**（8010 上的进程还是旧代码）：关掉旧进程 → 双击 `启动ERP.bat`
2. 浏览器**强刷**（Ctrl+F5）：侧边栏版本号应是 `v1.0.0 · 20261018-2138`，`CACHE_VERSION=erp-pwa-v40`
3. 复现场景：给订单收款 → 试图删这张订单，或删它转出来的开单 → 都应被拦，且提示写明金额与来源订单号

> 存量风险：`#4230` 那张订单已经被打成了死锁单（`completed` + 有收款）。
> 它现在删不掉（正确），但也不能重新转单。要处理只能走"冲销/退款"，
> 而这需要一个前端入口 —— 目前只有后端能力，没有界面。见下一步。
