# 任务 A · 财务红冲（Reverse）交付报告

> 时间：2026-10-19
> 目标：后端 `POST /finance/receipt/{id}/reverse`（+ 付款对应接口）、前端流水列表「红冲」按钮与确认弹窗、
> 生成反向流水并自动冲减原单 `received_amount`、红冲后带红字「已冲销」标签且不可再次红冲。
>
> 验证：接口层 **27 / 27**、界面层（真 Chrome）**24 / 24**、回归 step7 **31 / 31**
> 反证：3 组改坏 → 精确变红 → 还原 → 全绿，`grep PROBE` = 0

---

## 一、建表字段（2 列 + 1 个唯一索引）

`financial_transactions` 新增：

| 列 | 类型 | 作用 |
|---|---|---|
| `reversal_of_id` | INTEGER | **只有红字行有值**，指向被它冲掉的那条原始流水 |
| `applied_amount` | DOUBLE PRECISION | 这笔收付款**实际冲抵到单据**的金额（预收/预付那部分不进单据） |

- 文件：`app/models/finance.py`（模型）+ `app/main.py:191 FINANCE_ADDITIONS`（存量库补列）
- 唯一索引 `uq_financial_transactions_reversal_of`（一笔原流水只能有一条红字行）由
  `_contract_module/migrate_20261019_finance_reversal.py` 建（幂等，`--apply` 才写库）。
  已执行：3 个 schema 各补 2 列 + 1 索引，并把 4 条存量收款的 `applied_amount` 回填到位。

**为什么不用 `is_reversed` 布尔列**：状态只留一个来源。
"有没有被冲过"用 `reversal_of_id == 本行 id` 反查即可；再存一个布尔，
迟早出现"显示已冲销、却还能再冲一次"这种自相矛盾的账。

**为什么必须有 `applied_amount`**：单欠 1000、客户给了 1500，其中 500 是预收。
红冲若按总额回退，`received_amount` 会变成 -500。
这一列不是"锦上添花"——验证台 R10c 专门证明了：去掉它，单据会被冲成 700（见第四节反证）。

---

## 二、后端接口

### 2.1 路由（`app/api/v1/routes/erp_finance.py`）

```python
POST /api/v1/finance/receipt/{flow_id}/reverse   # 红冲一笔收款
POST /api/v1/finance/payment/{flow_id}/reverse   # 红冲一笔付款
```

入参（都可省）：`{"reason": "金额登记错误", "occurred_at": "2026-10-19"}`

返回：

```json
{
  "original": { "id": 12540, "amount": 1000, "is_reversed": true, "reversed_flow_id": 12541 },
  "reversal": { "id": 12541, "amount": -1000, "transaction_type": "receipt",
                "occurred_at": "2026-10-19", "period": "2026-10", "note": "红冲 #12540（收款 ¥1000.00）：金额登记错误",
                "reversal_of_id": 12540 },
  "applied_amount": 1000,
  "order": { "id": 4312, "amount_field": "received_amount", "amount": 0, "current_debt": 1000 }
}
```

### 2.2 四条硬规矩（都写在 `_reverse_flow` 的注释里）

1. **只红冲 `receipt` / `payment`**。应收 / 应付是单据审核时自动生成的，
   要冲就红冲单据本身；在这里单独冲会造出"单据还在、应收没了"的错账。
2. **一笔只能冲一次**：`reversal_of_id` 反查 + `SELECT … FOR UPDATE` 行锁双保险。
   连点两下不会冲两次（第二次读到"已被冲销"直接 409）。
3. **红冲生成负数流水，不删原行、不改金额** —— 所以 `sum(amount)` 天然归零，
   报表口径一行都不用改，两条记录都留痕。
4. **挂单据的收款同步回退 `received_amount` / `paid_amount`**，并 `_recalc_debt_chain`
   重算 `prev_debt / current_debt / total_debt`，否则单据还显示"已结清"。

错误码（前端按 `code` 分流，不靠字符串匹配）：

| HTTP | code | 场景 |
|---|---|---|
| 404 | — | 流水不存在 |
| 409 | `already_reversed` | 这笔已经被冲过（detail 里带 `reversal_id`） |
| 409 | `reversal_of_reversal` | 想冲"红冲本身" |
| 409 | —（字符串） | 类型不匹配（用收款接口冲付款） |

### 2.3 凭证：必须单独处理（`app/services/ledger.py`）

新增 `post_reversal_entry(db, flow, original)`：把原凭证的**借贷方向对调**。

> 为什么不直接复用 `post_journal_entry`：那里有一条 `if amount <= 0: return None`，
> 而红字行金额本来就是负数 —— 照它走会**一条凭证都不生成**，
> 流水表里多了一行负数、总账里却什么都没有，账和凭证对不上。
> 金额一律取绝对值（`_create_entry` 只接受 debit/credit > 0，负数分录会被整张撤回）。

### 2.4 列表接口带出红冲状态

`GET /finance` 里一次聚合查询拿到 `{被冲的流水 id: 红字行 id}`，再挂到 ORM 实例上
（逐行 `exists` 会变成 N+1：500 条流水 = 500 次查询）。
`FinancialTransactionRead` 增加 `reversal_of_id` / `applied_amount` / `is_reversed` / `reversed_flow_id`。

### 2.5 顺带修正的一个隐患

`_register_payment` 以前**不保存** `applied`（只在返回体里给一次），
现在落库到 `record.applied_amount` —— 红冲要靠它，否则只能靠猜。

---

## 三、前端

| 文件 | 改动 |
|---|---|
| `components/finance/ReverseFlowDialog.jsx`（新建，153 行） | 红冲确认弹窗：金额 / 关联单据 / 业务日期 + 原因输入 + 风险提示 |
| `components/finance/reverse-dialog.css`（新建，210 行） | 只写 `.reverse-flow*` / `.flow-tag*` 独占类名，不碰公共类 |
| `pages/FinancePage.jsx` | 新增「状态」列、行尾「红冲」按钮、`submitReverse()`、挂载弹窗 |
| `components/finance/FinanceFlowDrawer.jsx` | 抽屉里加「冲销状态」一行；底部提示改成"点行尾的红冲按钮" |

### 3.1 界面行为

- **状态列**：正常 = `—`；被冲的 = 红色实底「已冲销」；红字行 = 红色虚线「红冲」。
  两种标签样式**故意不同**：一个是"被冲的"，一个是"冲别人的"，混成一样就看不明白谁冲了谁。
- **金额**：负数一律红字（`.flow-amount--red`），符合中式账本习惯。
- **红冲按钮**只在 `收款/付款 && 未被冲 && 不是红字行 && 金额>0` 时出现。
- 点「红冲」→ 弹窗 → 填原因（选填，带 placeholder 提示）→ 确认 → 成功提示条
  「已红冲流水 #x，生成红字流水 #y；单据 #z 的已收/已付回退至 ¥0.00」→ 列表自动刷新。
- 弹窗 `busy` 时禁用两个按钮并**拦住 ESC**：红冲是写操作，点完手快关掉会让人不知道到底冲没冲。
- 409 的 `detail` 是**对象**，前端按 `message` 取值（直接当字符串渲染会出现 `[object Object]`）。

### 3.2 挂载位置（老坑）

弹窗和抽屉一样挂在 `</ResizableLayout>` **之外**：`ResizableLayout` 只在"恰好 2 个子元素"
时可拖拽，多挂一个就静默降级成普通网格（拖不动、也不报错）。

---

## 四、验证台账

### 4.1 接口层 `_contract_module/verify_reverse_api.py` —— 27 / 27

```
R0   admin 登录
R1a 收款登记成功                      R1b applied_amount=1000        R1c 单据 received_amount=1000
R2a 红冲返回 201                      R2b 红字金额 = -1000           R2c 备注含「红冲 #原id」
R2d 红字行记录 reversal_of_id         R3  原流水 is_reversed + 指向红字行
R4  单据 received_amount 回到 0       R4b 列表接口里也是 0            R5  欠款链 current_debt 回到净额
R3b /finance 带出 is_reversed         R3c 红字行 reversal_of_id
R6a 原收款有凭证                      R6b 红冲也生成了凭证            R6c 借贷方向与原凭证完全相反
R7  再冲一次 → 409 already_reversed   R8  冲红冲本身 → 409 reversal_of_reversal
R10a 收 1500 只冲抵 1000              R10b 冲 1500 后单据是 0（不是 -500）
R10c1 已结清后再收 300 全算预收（applied=0）
R10c2 冲预收不动单据：received_amount 仍是 1000
R9  付款红冲把采购单 paid_amount 从 600 回退到 0
R11 用收款接口冲付款 → 409            R12 不存在的流水 → 404
R13 收款合计净额 == 未冲销收款之和
```

### 4.2 界面层 `_contract_module/verify_reverse_ui.mjs` —— 24 / 24（真 Chrome）

```
U0c 浏览器加载的 bundle = dist 本次构建          ← 防 SW 缓存伪装全绿
U1b 收款行有「红冲」「详情」两个按钮             U1c 红冲前状态是「—」
U1d 日常收入行**没有**红冲按钮
U2a 弹出「确认红冲」弹窗   U2b 金额 ¥880.00   U2c 写明冲哪张单   U2d 有原因框 + 两个按钮
U3a 点取消弹窗消失   U3b **接口里 is_reversed 仍为 false**（真的没冲）
U4a 确认后弹窗关闭 + 成功提示
U5a 原行变「已冲销」红标签   U5b 红冲按钮消失   U5c 详情按钮还在（没连带弄坏）
U6a 出现「红冲」红字行   U6b 金额负数且红字样式   U6c 红字行自己没有红冲按钮
U7  详情抽屉写明「已冲销」
U8  绕过界面直接调接口再冲 → 409（前端藏按钮是体验，后端拦是底线）
U9  订单 received_amount 回到 0
U10 全程无 JS 异常
```

### 4.3 回归

- `verify_step7_flow_drawer_print.mjs`：**31 / 31**（流水表加了「状态」列后，抽屉与打印确认都没坏）
- `pytest tests/test_bank_and_entries.py tests/test_finance_analysis.py`：**11 passed / 1 failed**
  - 失败的是 `test_entry_category_dictionaries_seeded`：它去 `App.jsx` 里 grep datalist，
    而那段代码早已随页面拆分搬到 `pages/IncomeExpensePage.jsx` ——
    属于已知的「7 条过期断言」，用户明确"现在不修"，**与本次改动无关**。

### 4.4 反证（3 组，证明断言不是摆设）

| 改坏哪里 | 预期 | 实测 |
|---|---|---|
| ① `if order is not None and applied > 0:` → `if False and …`（不回退单据） | R4b/R5/R9/R10b 红 | ✅ 4 条全红（received 停在 1000、paid 停在 600） |
| ② `applied = min(original.applied_amount, amount)` → `applied = amount`（忽略预收） | R10c2 红 | ✅ 红（`received_amount=700`，正是"按总额回退"的错账） |
| ③ 前端 `canReverse` 去掉 `!isReversed`（已冲销仍显示按钮） | U5b 红 | ✅ 红（`hasReverse:true`，行文本里「红冲」还在） |

还原后复跑：接口 **27/27**、界面 **24/24**，`grep PROBE` = 0。

> 反证 ② 一开始跑了却没红 —— 因为代码里还有一道 `min(applied, 当前已收)` 夹取把它兜住了。
> 这说明原断言（R10b）其实是在验夹取、不是在验 `applied_amount`。
> 于是补了 **R10c**（已结清后再收 300 → 冲掉它，单据必须还是 1000），才真正把这一列钉住。

---

## 五、一个有意保留的边界

**红冲之后，单据依然不能删。** `_assert_no_payment_flows` 判的是"这笔资金记录存在"，
红冲并不删除它（这是对的：钱确实发生过，只是被冲回了）。
如果让红冲"解锁"删单，删完单据那两条净额为 0 的流水就成了指向不存在单据的孤儿。

所以口径是：**红冲修账，不开删单的口子**。真要删单，请先把收付款处理干净再走正规流程。

---

## 六、改动清单（回滚用）

快照：`backup/20261019_taskA_reverse/`（10 个文件）

```
app/models/finance.py                     + reversal_of_id / applied_amount 两列
app/main.py                               FINANCE_ADDITIONS 补两列（存量库启动自动补）
app/schemas.py                            FinancialTransactionRead + 4 个字段
app/services/ledger.py                    + post_reversal_entry()（借贷对调的凭证）
app/api/v1/routes/erp_finance.py          _register_payment 落 applied_amount
                                          + REVERSIBLE_TYPES / _reverse_flow / 两条路由
                                          GET /finance 批量带出 is_reversed
frontend/src/pages/FinancePage.jsx        import + state + submitReverse + 状态列 + 红冲按钮 + 挂载弹窗
frontend/src/components/finance/ReverseFlowDialog.jsx   新建
frontend/src/components/finance/reverse-dialog.css      新建
frontend/src/components/finance/FinanceFlowDrawer.jsx   加「冲销状态」行、改底部提示
frontend/public/sw.js                     CACHE_VERSION = erp-pwa-v43
_contract_module/migrate_20261019_finance_reversal.py   新建（已执行）
_contract_module/verify_reverse_api.py                  新建（27 项）
_contract_module/verify_reverse_ui.mjs                  新建（24 项）
_contract_module/cleanup_reverse.py                     新建（测试数据清理）
_contract_module/_probe_reverse.py                      新建（反证开关）
```

构建：`✓ built in 6.69s`；产物哈希与浏览器实载一致（U0c）。
测试数据：57 条流水 + 57 张凭证 + 20 张销售单 + 6 张采购单 + 17 个往来单位，已清零，孤儿 0。

---

## 六点五、部署提醒（很重要）

`启动ERP.bat` 起的 `desktop_app.py` **没有 `--reload`**，所以：

- **前端 dist 立刻生效**（静态文件按请求读盘）→ 你会马上看到「红冲」按钮；
- **后端还是旧进程**（实测 8010 的 `openapi.json` 里**没有** reverse 路由）→ 点红冲会 404。

所以验收前请**关掉窗口、双击 `启动ERP.bat` 重启一次**。
为了不让这件事变成"莫名其妙的红冲失败"，前端对 404 做了专门提示：
「红冲接口未生效：后端进程还是旧版本，请重启「启动ERP.bat」后再试」。

## 七、下一步（任务 B · 合同原件 OCR）勘察结论
现有基础比预期好，可以直接接着做：

- `contracts.ocr_status`（pending / parsed / failed / reviewed）与 `CONTRACT_OCR_STATUS` 字典**已存在**；
- 已有写回接口 `POST /contracts/{id}/ocr`（`erp_sales.py:1143`）与人工复核 `…/ocr/review`（`:1196`）；
- OCR 引擎现成：`rapidocr_onnxruntime` → `paddleocr` 两级回退（`erp_invoice.py:520 _ocr_image_bytes`，
  发票导入已经在用，含 PDF 文本层与二维码通道）。

缺的是"合同这条路"本身：**没有"开始识别"的触发入口，也没有把 PDF 拆页 → 图片 → OCR → 字段映射接起来**。
建议 B 的实现顺序：① 复用 `_ocr_image_bytes` 抽成公共函数 → ② 合同 PDF 分页识别 →
③ 按合同字段做正则/关键词映射（甲乙方、金额、签订日期、编号）→ ④ 前端「开始识别」按钮 + 进度 + 回填表单 + 人工复核。
