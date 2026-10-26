# 第四步交付：首页版本号 + 删单拦截（防孤儿收款）

> 日期：2026-10-18 · 缓存 `erp-pwa-v39`
> 本步范围：用户指定的第 1、2 步（版本号配置与展示 / 删单拦截）。
> **第 3 步（菜单「现货开单」、下架「销售出库（多单位）」、发票「关联客户」）未动**，等这两项验收后再做。

---

## 0. 结论

| 需求 | 落地 |
|---|---|
| 版本号展示 | 侧边栏品牌块第二行：`v1.0.0 · 20261018-2110`，hover 显示完整构建时间与提交哈希 |
| 每次 build 自动更新 | `vite.config.js` 的 `define` 注入 `__APP_VERSION__ / __APP_BUILD__ / __APP_BUILD_AT__ / __APP_HASH__` |
| 删单拦截 | 有 `receipt`/`payment` 流水的单据 → **409 + `detail.code=has_payment_flow`**；前端弹「无法删除」，**没有强制删除入口** |

---

## 1. 版本号

### 1.1 数据源（唯一）

`frontend/package.json` 的 `version` 是**唯一**版本来源，构建期读它注入，运行期不再有第二份手写常量。

```
vite.config.js
  __APP_VERSION__  ← package.json.version
  __APP_BUILD__    ← 构建时间 YYYYMMDD-HHmm（本地时区）
  __APP_BUILD_AT__ ← 构建时间 YYYY-MM-DD HH:mm（hover 用）
  __APP_HASH__     ← git rev-parse --short HEAD（不在仓库里给 nogit）
```

**为什么用 define 而不是运行时 fetch**：`dist` 里没有 `package.json`，运行时读它要多一次请求 + 处理 404；define 是编译期替换，产物里直接就是字符串。

### 1.2 代码位置

| 位置 | 内容 |
|---|---|
| `frontend/vite.config.js:1-46` | 读 pkg / 算时间戳 / 取 git 哈希 / `define` 注入 |
| `frontend/src/lib/appLib.js:13-29` | `APP_VERSION` / `APP_BUILD` / `APP_BUILD_AT` / `APP_HASH` / `APP_VERSION_LABEL`（`:26`） |
| `frontend/src/App.jsx:10534-10545` | 侧边栏品牌块渲染，带 `data-app-version` |
| `frontend/src/styles.css:315-322,348-361` | `.sidebar-brand{flex-wrap:wrap}` + `.brand-version` |

```jsx
<span className="brand-text">核心系统</span>
<span
  className="brand-version"
  data-app-version={APP_VERSION_LABEL}
  title={`构建时间 ${APP_BUILD_AT} ｜ 提交 ${APP_HASH}`}
>
  {APP_VERSION_LABEL}
</span>
```

渲染结果：`v1.0.0 · 20261018-2110`，等宽 11px 灰字，单独占第二行（260px 侧栏里跟「核心系统」挤一行会断字）。

### 1.3 ⚠️ 每次发版仍要 bump `sw.js`

版本号是**新构建**才变的，而用户浏览器里可能还跑着 Service Worker 缓存的旧壳 —— 那壳里的版本号自然也是旧的。
所以每次 `npm run build` 发版，**必须同时 bump `public/sw.js` 的 `CACHE_VERSION`**（本次 v38 → **v39**），否则"刷新就能看到最新版本"不成立。

---

## 2. 删单拦截（防孤儿收款）

### 2.1 为什么必须有

`_revert_finance` 只冲销"单据自己产生的"流水（`related_type = sales_out / purchase_in`）。
而 `receipt` / `payment` 是**人工登记的真实资金记录**，删单时不会被一起删，
`related_order_id` 就指向了一张不存在的单据 —— 钱在账上、单据没了，对账无从追溯。

> 反证时我实测到了这个现象：把闸口短路后跑一遍，两张单被 API 删掉，
> 库里立刻多出 2 条指向空气的收款流水，靠 `cleanup_step4.py` 才清掉。

### 2.2 后端

`app/api/v1/routes/erp_common.py:345` 新增共用闸口：

```python
def _assert_no_payment_flows(db: Session, order_id: int, order_no: str) -> None:
    rows = db.query(FinancialTransaction).filter(
        FinancialTransaction.related_order_id == order_id,
        FinancialTransaction.related_type.in_(("receipt", "payment")),
    ).all()
    if not rows:
        return
    ...
    raise HTTPException(status_code=409, detail={
        "code": "has_payment_flow",
        "message": f"单据 {order_no} 已登记 {len(rows)} 笔资金流水（收款 ¥100.00），不能删除。",
        "hint": "收付款是真实资金记录，删单会让这笔钱变成无主账（孤儿流水），财务上不允许。"
                "请保留该单据；金额登错就再登记一笔冲销/退款，而不是删单。",
        "flow_count": len(rows),
        "receipt_amount": ..., "payment_amount": ...,
    })
```

接入两处（都在 `_revert_stock` / `_revert_finance` **之前**，避免先动库存再报错）：

| 文件 | 行 |
|---|---|
| `app/api/v1/routes/erp_sales.py` | `:89` 引入 · `:430` 调用 |
| `app/api/v1/routes/erp_purchase.py` | `:38` 引入 · `:400` 调用 |

**刻意不做的事**：不提供 `force=true` 绕过，也不"顺手把流水一起删"。
前者等于给抹账开后门，后者比留孤儿更糟（真实资金记录消失）。

### 2.3 前端提示

| 位置 | 内容 |
|---|---|
| `App.jsx:779-781` | `deleteBlocked` 状态（单据被拦时存文案） |
| `App.jsx:1820-1833` | 409 且 `detail.code === 'has_payment_flow'` → 弹专用拦截框，**不落到"409 → 强制删除"那条分支** |
| `App.jsx:11213-11240` | 拦截弹窗：标题「无法删除」+ 红底消息 + 解释 + 唯一按钮「知道了」 |
| `App.jsx:11255 / 11258` | 删除确认里补一句「已登记收付款的订单不允许删除」（提前告知，减少无效点击） |
| `styles.css:1806-1829` | `.delete-blocked*`（红底消息 + 说明文字） |

弹窗文案示例：

```
无法删除
单据 XSD20261018001 已登记 1 笔资金流水（收款 ¥100.00），不能删除。
收付款是真实资金记录，删单会让这笔钱变成无主账（孤儿流水），财务上不允许。
请保留该单据；金额登错就再登记一笔冲销/退款，而不是删单。
                                                    [ 知道了 ]
```

---

## 3. 验证

### 3.1 E2E（真 Chrome，`verify_frontend_step4_version_guard.mjs`）→ **31 / 31 全绿**

```
V1-V5  版本号：元素存在 / 格式 v1.0.0 · YYYYMMDD-HHmm / **显示的时间 = 本次产物里注入的时间** /
       hover 含构建时间与提交 / 高度 > 0
D1-D5  接口层：有收款订单 DELETE → 409 + code=has_payment_flow + 笔数与金额；采购同；
       被拦后订单确实还在库里
D6-D15 界面层：点删除 → 删除确认 → 打后端 → 弹「无法删除」→ 文案含单号/金额/孤儿解释 →
       **没有任何「继续/强制删除」按钮** → 知道了关闭 → 订单仍在列表
D16-D19 反向：无收付款订单照样能删（不留拦截弹窗、列表消失、服务端也查不到）
D20    控制台零异常
Z/Z2   有收款的留库等 SQL 收尾 / 无收款的已删
```

> **V3 是这组里最关键的一条**：只断言"页面上有版本号"是假绿 —— SW 缓存里的旧包也带版本号。
> 所以先从 `dist/assets/index-*.js` 里现读注入的时间，再和界面文字比对。

### 3.2 反证（同时注入两组）

| 反证 | 改动 | 实测 |
|---|---|---|
| A | `APP_VERSION_LABEL` 写死 `'v1.0.0'`（丢掉构建时间） | **V2 / V3 红**（V3 报"界面 v1.0.0 vs 产物 ''"） |
| B | `_assert_no_payment_flows` 开头直接 `return` | **D1-D9 红**（DELETE 返回 204、订单被真删、界面无拦截框） |

结果 `8 通过 / 12 失败（脚本中断）`；还原 `grep PROBE` = 0、重建、重启后端后 **31/31** 复绿。

### 3.3 后端回归

`pytest tests/test_order_doc_type.py tests/test_order_settlement_and_finance_link.py tests/test_delete_endpoints.py` → **37 passed**（`test_delete_endpoints` 里原有的删单用例没有被新闸口误伤）。

---

## 4. 一个仍然存在的缺口（建议排期）

**收款登错了没有"撤销"入口。** 现在单据删不掉，而 `DELETE /finance/entries/{id}` 又只允许删人工的
`income`/`expense`（`erp_finance.py:959`），所以一笔登记错的收款只能靠管理员改库。

正确的做法是加一个**红冲**：`POST /finance/receipt/{id}/reverse` —— 生成一笔等额反向流水
（`transaction_type=receipt` 负数 或 单独的 `receipt_reverse`），订单的 `received_amount` 跟着减回去，
**原流水保留**（审计要求）。这样"删不掉"才不会变成死路。

---

## 5. 生效方式

```
npm run build → ✓ index-BvHkY3SO.js（含 20261018-21xx 时间戳）
sw.js CACHE_VERSION = erp-pwa-v39
后端改了 erp_common / erp_sales / erp_purchase → **必须重启 8010**
```

**重启 `启动ERP.bat` + Ctrl+F5**。

验收动线：
1. 左上角「核心系统」下面应出现 `v1.0.0 · 20261018-21xx`，鼠标悬停能看到完整的构建时间与提交号；
2. 找一张已经收过款的订单 → 删除 → 应弹「无法删除」并写明金额，且**没有任何强制删除按钮**；
3. 再找一张没收过款的订单 → 删除 → 正常删掉。

---

## 6. 回滚

```
_contract_module/backup/20261018_step4_version_guard/
  vite.config.js  appLib.js  App.jsx  styles.css  sw.js
  erp_common.py  erp_sales.py  erp_purchase.py
  verify_frontend_step4_version_guard.mjs  cleanup_step4.py
```

---

## 7. 下一步（原计划第 3 步，等验收）

1. 菜单「开单管理」→「现货开单」，下架「销售出库（多单位）」并入多单位模式
   （`SalesOrderUnitsBoard.jsx` 的 `handleStatus(order,'completed')` 与 `STATUS_LABELS` 要跟着改；
   菜单项**只能追加在组末**，`sort_order = 下标×10`）。
2. 发票页「关联客户」`ErpSearchSelect` → 写 `customer_id` / `contract_id`（12 张存量发票因税号歧义挂不上）。
3. 之后才是修对账单 `generate` 的四个断点 + 收款红冲接口。
