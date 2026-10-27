# 外部端接入 API 指南（微信小程序 / 移动端 / 第三方系统）

> 适用版本：ERP v1.80.0（2026-10-26 封版）· API 前缀 `/api/v1`
> 本文所有请求/响应样例均为**真实抓包**，不是设计稿。
>
> ⚠️ **v1.80.0 起 `/api/v1` 默认拒绝匿名请求**（除 `health` / `auth/login` / `auth/register`
> / 商品图 `/api/v1/uploads/products/*` 外，一律要 `Authorization: Bearer <token>`）。
> 下表"鉴权"列的"必须"就是字面意思：不带 token 直接 **401**，不是"也能拿到数据"。
> 详见 [P0-1_鉴权收口_方案B_20261026.md](./P0-1_鉴权收口_方案B_20261026.md)。

---

## 0. 一分钟速查表

| 能力 | 方法与路径 | 鉴权 | 说明 |
|---|---|---|---|
| 健康检查 | `GET /api/v1/health` | 无 | 探活，返回 `{"status":"ok"}` |
| 登录 | `POST /api/v1/auth/login` | 无 | 拿 token + 账套清单 |
| 我的账套 | `GET /api/v1/auth/companies` | ✔ | 顶栏切换用 |
| 切换账套 | `POST /api/v1/auth/switch-company` | ✔ | **换发新 token** |
| 当前用户 | `GET /api/v1/auth/me` | ✔ | 校验 token 是否还活着 |
| 商品列表 | `GET /api/v1/products` | **必须** | 全量 262 条，无 keyword 参数 |
| 商品辅助单位 | `GET /api/v1/products/{id}/units` | **必须** | 多单位换算 |
| 客户列表 | `GET /api/v1/customers` | **必须** | 开单选客户 |
| 仓库列表 | `GET /api/v1/warehouses?only_active=true` | **必须** | 开单选仓库 |
| 销售单列表 | `GET /api/v1/sales-orders` | **必须** | `doc_type` 区分订单/出库单 |
| 新建销售单 | `POST /api/v1/sales-orders` | **必须** | 成功 **201** |
| 改单据状态 | `PATCH /api/v1/sales-orders/{id}/status` | **必须** | 只能沿状态机走 |
| 反审核 | `PATCH /api/v1/sales-orders/{id}/unsubmit` | **必须** | 有流水 → 409 |
| 采购单列表 | `GET /api/v1/purchase-orders` | **必须** | 同上 |
| 经营概览（智能体） | `GET /api/v1/agent/summary` | **必须** | 无 token → 401 |
| 库存预警 | `GET /api/v1/agent/stock-alerts` | **必须** | 当前 **501** 占位 |
| 单据查询（智能体） | `GET /api/v1/agent/orders` | **必须** | 当前 **501** 占位 |

---

## 1. 连通性（先把这条路打通）

- **服务地址**：`http://<ERP所在电脑的局域网IP>:8010`
  后端监听 `0.0.0.0:8010`，手机与电脑连同一个 WiFi 即可访问。
  查 IP：电脑上 `ipconfig` → IPv4 地址，例如 `http://192.168.1.20:8010/api/v1/health`。
- **首次连通失败的三个原因**（按概率排序）：
  1. Windows 防火墙拦了 8010 入站（需放行，或临时关防火墙测试）；
  2. 手机连的是 5G 网络不是同一 WiFi；
  3. 后端没启动（双击 `启动ERP.bat`，浏览器能打开 `http://127.0.0.1:8010` 才算活）。
- **微信小程序的硬约束**：
  - 正式版/体验版要求 **HTTPS + 备案域名**，`http://192.168.x.x` 无法上线；
  - 开发阶段用微信开发者工具勾选 **「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」**，即可直连局域网 IP；
  - 上线方案二选一：① 用 frp/ngrok 之类做 HTTPS 内网穿透；② 部署到有域名的服务器 + Nginx 反代。**代码里 BASE_URL 只改一处**（见提示词文档）。
- **CORS**：后端已 `allow_origins=["*"]`，Taro H5 调试不需要额外配置。小程序原生请求不受 CORS 限制。

---

## 2. 通用约定（先记住这 6 条）

1. **所有请求/响应都是 JSON（UTF-8）**，POST/PATCH 必须带
   `Content-Type: application/json`。
2. **金额都是数字（float），单位元，两位小数**；**单价是数字，最多 4 位小数**。
   例：`"total_amount": 1000.0`、`"unit_price": 73.901`。
   ⚠️ 前端只负责显示，**不要拿单价去 toFixed(2)**，否则 `73.901 × 580` 会算错 58 分。
3. **日期是字符串**：`order_date` 是 `"2026-10-20"`（`YYYY-MM-DD`，**不是** ISO 带时区）；
   `created_at`/`signed_at` 是 ISO8601 带时区 `"2026-10-20T00:59:47.432738+08:00"`。
4. **列表分页是 `skip` / `limit` 两个 query 参数**，**不传 `limit` 就返回全量**
   （商品 262 条、客户 33 条，移动端建议自己传 `limit` 控制首屏）。
5. **错误响应统一是 `{"detail": "中文说明"}`**，用 HTTP 状态码判断类型，`detail` **直接展示给用户**（后端写的就是中文人话）。
6. ⚠️ **账套由 token 决定**：后端按 token 里的 `company` 字段切数据库 schema。
   **v1.80.0 起不带 token 连数据都拿不到**（网关直接 401，根本走不到"落到默认账套"那一步）；
   带上 token 后读到的才是你以为的那家公司。外部端必须"先登录、再取数"。

### 错误码约定

| 状态码 | 含义 | 前端该怎么做 |
|---|---|---|
| 200 / 201 | 成功（201 = 新建成功） | — |
| 400 | 参数不合法（如 `doc_type` 传错、单号重复） | 直接弹 `detail` |
| 401 | 未登录 / token 过期 / 密码错 | **清 token，跳登录页** |
| 403 | 账号被停用 / 无该账套权限 | 弹 `detail`，不要反复重试 |
| 404 | 资源不存在 | 弹 `detail`，列表刷新 |
| 409 | 状态冲突（非法流转、有流水不能反审核、未结清不能完结） | 弹 `detail`，**不要重试**，刷新详情 |
| 501 | 接口未开放（占位） | 隐藏对应入口，别当 bug 报 |
| 500 | 服务端异常 | 提示"系统繁忙"，记日志 |

---

## 3. 登录与鉴权（第一步）

### 3.1 登录

```http
POST /api/v1/auth/login
Content-Type: application/json
```

```json
{ "username": "admin", "password": "Admin123", "company": "public" }
```

- `company` **可选**：传账套号（如 `co_02`）或 schema 名；不传 = 该用户默认账套；
  传了一个没权限的账套 = **静默回落到默认账套**（不报错，防越权）。

**成功 200**（真实响应，token 已截断）：

```json
{
  "access_token": "eyJhbGciOiJIUzI1Ni...",
  "token_type": "bearer",
  "role": "admin",
  "company": "public",
  "company_name": "西安寨卡信息技术有限公司",
  "companies": [
    { "id": 1, "code": "public", "name": "西安寨卡信息技术有限公司", "schema_name": "public",
      "tax_no": "91610131MA6TXU2T6R", "is_default": true },
    { "id": 29, "code": "co_02", "name": "西安华诺迈贸易有限公司", "schema_name": "co_02",
      "tax_no": "91610131MACQ0JAT5J", "is_default": false },
    { "id": 30, "code": "co_03", "name": "陕西寨纬智能科技有限公司", "schema_name": "co_03",
      "tax_no": "91611104MA6TJURR23", "is_default": false }
  ]
}
```

**失败**：
- 用户名/密码错 → `401 {"detail":"Incorrect username or password"}`
- 账号被停用 → `403 {"detail":"账号已停用，请联系管理员"}`

> ⚠️ 登录用的是 **JSON body**，不是 OAuth2 的 form-urlencoded。
> 虽然 `/docs` 上显示为 OAuth2，实际按 JSON 发就对了。

### 3.2 带 token 的方式

```http
Authorization: Bearer <access_token>
```

### 3.3 token 有效期与刷新

- **有效期 60 分钟**，`HS256` 签名，**没有 refresh token**。
- 策略建议：`401` 时清 storage + 跳登录页；也可以做"临期静默重登"——把用户名密码
  （或微信登录态换取的凭据）留在安全存储里，剩 5 分钟时后台重登换新 token。
- 校验 token 是否还有效：`GET /api/v1/auth/me`（401 就说明废了）。

### 3.4 多账套切换

```http
POST /api/v1/auth/switch-company
Authorization: Bearer <token>
Content-Type: application/json

{ "company": "co_02" }
```

返回结构与登录**完全一致**（含新 `access_token`）。**必须用它换发的新 token 覆盖本地旧 token**，
因为账套是写死在 token 里的。
传一个你没权限的账套 → `403 {"detail":"你没有这家公司的访问权限"}`（登录时是静默回落，切换时是明确报错）。

---

## 4. 商品

### 4.1 商品列表

```http
GET /api/v1/products?skip=0&limit=50
Authorization: Bearer <token>
```

参数：`skip`（默认 0）、`limit`（**不传 = 全量**）。排序固定 `id DESC`（新商品在前）。

**响应 200**（数组，真实样例一条）：

```json
[
  {
    "sku": "测试", "name": "焊条", "category": "焊条", "unit": "公斤",
    "purchase_price": 500.0, "sale_price": 550.0, "tax_rate": 13.0,
    "mnemonic": null, "standards": null, "brand": null, "bar_code": null,
    "color": null, "size": null, "manufacturer": null, "manufacturer_id": null,
    "serial_no": null, "unit_weight": 0.0,
    "stock_upper": null, "stock_lower": null, "pack_qty": 12,
    "shelf_life": null, "warn_days": null,
    "image_url": "/api/v1/uploads/products/fcdb0cf1d8ad-xxx.jpg",
    "note": null,
    "id": 15317,
    "created_at": "2026-10-17T16:07:01.696958+08:00"
  }
]
```

要点：
- **没有 `keyword` 参数**。移动端做搜索 = 拉一次全量（262 条，约 100KB）后在本地按
  `name` / `sku` / `mnemonic`（拼音助记码）/ `category` 过滤，和小程序端体验一致；**不要每输入一个字就发请求**。
- `image_url` 是**相对路径**，要拼上前缀：`http://<host>:8010` + `image_url`。
- 价格取哪个：销售侧用 `sale_price`，采购侧用 `purchase_price`；`tax_rate` 可能是 `null`（未维护，**别默认 13**）。
- `pack_qty` = 默认辅助单位的换算率（1 个录入单位 = 几个基本单位）。

### 4.2 商品辅助单位（多单位）

```http
GET /api/v1/products/{product_id}/units
```

**响应 200（真实响应）**：

```json
[
  {
    "unit_name": "箱", "factor": 12,
    "price": null, "sale_price": null, "bar_code": null,
    "is_default": true, "is_enabled": true, "note": null,
    "id": 473, "product_id": 15317, "sort_order": 0,
    "created_at": "2026-10-17T16:07:01.696958+08:00"
  }
]
```

字段说明：`unit_name`（单位名，**不叫 name**）、`factor`（1 个该单位 = 几个基本单位，≥2）、
`is_default`（是否默认单位）、`is_enabled`（停用的不显示在开单下拉）、`sort_order`。
顺序后端已排好，**不要重排**。
选完商品后如果 `factor > 1`，说明这个商品有"箱/件"之类的大单位，开单时可让用户选单位，
但**换算率不要自己算**——下单时只传 `unit` 名称，服务端自己解析。

---

## 5. 销售单（订单 / 出库单）

> 同一个接口、同一张表，用 `doc_type` 区分：
> - `order` = 销售订单（只订货，不动库存和钱，要审核）
> - `outbound` = 销售出库单 / 现货开单（**默认值**，建单即扣库存、即产生应收）

### 5.1 列表

```http
GET /api/v1/sales-orders?doc_type=outbound&skip=0&limit=20
Authorization: Bearer <token>
```

参数：`doc_type`（`order` / `outbound` / 不传=全部）、`customer_id`、`skip`、`limit`。
排序 `id DESC`。**列表已内含明细 `items`**，不需要再请求详情接口。

**响应 200**（数组，真实样例一条）：

```json
[
  {
    "customer_id": 7039,
    "order_no": "XS20261020002",
    "items": [
      {
        "product_id": 15317, "quantity": 1, "unit_price": 1000.0,
        "product_name": "焊条", "standards": null, "unit": "公斤", "note": null,
        "id": 4849, "sales_order_id": 4739, "unit_factor": 1, "amount": 1000.0
      }
    ],
    "doc_type": "outbound",
    "warehouse_id": 204, "project_id": null, "businesser": null,
    "order_date": "2026-10-20", "delivery_date": null,
    "payment_method": null, "contact": null, "contact_phone": null, "address": null, "note": null,
    "logistics_company": "顺丰", "logistics_no": "123",
    "signed_by": "速", "signed_at": "2026-10-20T01:00:00+08:00",
    "discount_amount": 0.0, "received_amount": 1000.0, "is_invoiced": false,
    "id": 4739,
    "status": "completed",
    "total_amount": 1000.0,
    "source_order_id": null,
    "receivable_amount": 1000.0,
    "current_debt": 0.0, "prev_debt": 42862.58, "total_debt": 42862.58,
    "invoiced_amount": 2000.0,
    "outstanding_amount": 0.0,
    "uninvoiced_amount": -1000.0,
    "settled": true,
    "created_at": "2026-10-20T00:59:47.432738+08:00"
  }
]
```

**结算四件套（后端现算，前端绝对不要自己算）**：

| 字段 | 含义 |
|---|---|
| `invoiced_amount` | 已开票金额（关联销项发票合计） |
| `outstanding_amount` | 应收余额 =（价税合计 − 优惠）− 实收 |
| `uninvoiced_amount` | 未开票 =（价税合计 − 优惠）− 已开票 |
| `settled` | `outstanding_amount ≤ 0 且 uninvoiced_amount ≤ 0` → **都已收齐开齐** |

`total_debt` / `prev_debt` 是**客户累计欠款**口径（不是本单），列表做"客户欠款"展示时用。

### 5.2 状态机（写库只允许这几个值）

| doc_type | 合法流转 |
|---|---|
| `order`（订单） | `draft → pending → approved → completed` |
| `outbound` / `inbound`（即时单） | `draft → submitted → completed` |

- 任意非终态都可以 → `cancelled`；`completed` / `cancelled` 是终态，**不可再改**。
- 订单上的历史值 `submitted` 等价于 `pending`（后端会归一）。
- 中文标签建议对齐 PC 端：
  - 订单一套：`draft 草稿 / pending 待审核 / approved 已审核 / completed 已转单 / cancelled 已取消`
  - **出库单另一套**：`draft 草稿 / submitted 已提交 / completed 已发货 / cancelled 已取消`
    （⚠️ 出库单的 `completed` 是「已发货」，不是「已转单」——这是 PC 端刚修过的文案 Bug，别复制错）

### 5.3 新建

```http
POST /api/v1/sales-orders
Content-Type: application/json
Authorization: Bearer <token>

{
  "customer_id": 7039,
  "doc_type": "order",
  "order_date": "2026-10-20",
  "warehouse_id": 204,
  "note": "小程序下单",
  "items": [
    { "product_id": 15317, "quantity": 2, "unit_price": 550.0, "unit": "公斤" }
  ]
}
```

- **成功返回 201**，body 与列表单条同结构。
- `doc_type` **不传 = `outbound`**（会立刻扣库存 + 产生应收！做"订货"一定显式传 `order`）。
- `order_no` 不传 → 自动生成（订单 `XSD+日期+序号`，出库单 `XS+日期+序号`）。
- `items[].unit_price` 必填，**保留原始精度**（最多 4 位小数），`quantity` 是整数。
- `unit` 可选：不传 = 基本单位；传了辅助单位名（如"箱"），服务端按 `product_units` 的 `factor` 自动换算。
- `items` 里整行空白会被静默丢弃；**选了商品却没填数量 → 400**。

### 5.4 改状态 / 审核

```http
PATCH /api/v1/sales-orders/{id}/status
Content-Type: application/json

{ "status": "approved" }
```

- 同状态 = 幂等成功（双击不报错）；非法流转 → `409`；未知状态码 → `400`（detail 里列出允许值）。
- ⚠️ **出库单改成 `completed` 有过关闸**：应收没结清或没开完票 → `409`，body 是**对象**不是字符串：

```json
{
  "detail": {
    "code": "not_settled",
    "outstanding_amount": 1000.0,
    "uninvoiced_amount": 1000.0,
    "message": "单据 XS20261020002 还有 应收余额 1000.00、未开票 1000.00，无法标记为已完结。请先「收款」「开票」。"
  }
}
```

前端解析时**先判断 `detail` 是对象还是字符串**，两种都要兜住。

### 5.5 反审核（退回草稿）

```http
PATCH /api/v1/sales-orders/{id}/unsubmit
```

- `pending`（订单历史值 `submitted` 也算）/ `approved` → 退回 `draft`；`completed` / `cancelled` → `409`。
- **已产生库存/资金流水 → `409`**（detail 提示"已产生…流水，请走红冲或删除"）。
  出库单/入库单建单即有流水，所以这个接口实际上**只对订单有意义**。
- 成功返回更新后的单据对象（`status` 变 `draft`）。

### 5.6 采购侧（完全对称）

`GET /api/v1/purchase-orders`（参数 `doc_type` / `supplier_id` / `skip` / `limit`）、
`POST /api/v1/purchase-orders`、`PATCH /purchase-orders/{id}/status`、`PATCH /purchase-orders/{id}/unsubmit`。

⚠️ **采购单 `POST` 不传 `doc_type` 的默认值是 `inbound`（会立刻入库+记账）**，做"采购订货"必须显式传 `"doc_type":"order"`。

### 5.7 开单要用的基础档案

```http
GET /api/v1/customers?skip=0&limit=100     # code, name, phone, contact, contact_phone, tax_no, address, discount, credit_limit, category_id, id
GET /api/v1/suppliers?skip=0&limit=100
GET /api/v1/warehouses?only_active=true    # id, code, name, location, manager, is_active
```

⚠️ **客户档案里没有欠款字段**（`total_debt` 只在单据上）。要展示"客户欠我多少钱"，
读该客户最新一张单据的 `total_debt`（它是客户累计口径，不是单张单据金额）。

客户/商品/供应商列表**都不支持 keyword**，做搜索一律"拉全量 + 本地过滤"。

---

## 6. 智能体接口（给小程序首页 / 微信对话用）

### 6.1 经营概览 `GET /api/v1/agent/summary`

**必须带 token**（无 token → `401 {"detail":"未登录：请在请求头带上 Authorization: Bearer <token>"}`）。

**响应 200（真实响应）**：

```json
{
  "generated_for": "admin",
  "generated_at": "2026-10-20",
  "counts": { "customers": 33, "suppliers": 69, "products": 262 },
  "today": { "sales_amount": 43862.58, "sales_orders": 2 },
  "receivable": { "total": 37362.58, "received": 2676.0, "outstanding": 34686.58 },
  "payable":    { "total": 2028.93,  "paid": 0.0,      "outstanding": 2028.93 },
  "sales_orders_by_status": { "submitted": 1, "approved": 1, "completed": 2 },
  "purchase_orders_by_status": { "submitted": 5 }
}
```

口径说明（很重要，别自己另算一套）：
- `today.sales_amount` 只算 **`doc_type=outbound`** 且 `order_date` = 今天的单据（订单是意向，不进销售额）。
- `receivable.total` = 所有开单应收（`transaction_type='receivable'`）累计；
  `received` = 收款流水（`transaction_type='receipt'`）累计；`outstanding = total − received`。
  ⚠️ 收付款是**独立类型**，不是"方向对冲"，别用 `direction` 去查。
- 这是**全账套粗口径**，精确到单的口径看单据上的 `outstanding_amount`。

### 6.2 占位接口（已占路径，返回 501）

```http
GET /api/v1/agent/stock-alerts?limit=20   → 501 {"detail":"库存预警明细接口建设中，第二阶段开放"}
GET /api/v1/agent/orders?keyword=XS2026   → 501 {"detail":"单据查询接口建设中，第二阶段开放"}
```

**前端处理原则**：收到 `501` 就把对应卡片置灰/隐藏，**不要弹错误**，也不要当成后端故障。

---

## 7. 微信小程序端的 7 个坑（血泪版）

1. **token 存哪**：`Taro.setStorageSync('erp_token', token)` 足够；
   但**不要**把账号密码明文存本地。token 60 分钟过期，`401` 就跳登录。
2. **请求封装统一在一处**：拦截 `401 → 清 token + 跳登录`、`409/400 → 直接 toast detail`。
   散在各页面写 `if (res.statusCode === 401)` 迟早漏。
3. **`detail` 可能是对象**（完结闸 409），封装里要 `typeof detail === 'string' ? detail : detail.message`。
4. **金额显示用后端给的数**：不要在前端做 `合计 = Σ(数量×单价)` 反算，四舍五入会和后端差几分钱，
   用户立刻会截图来问。要合计就读 `total_amount`。
5. **单价不要 toFixed(2)**：`73.901` 抹成 `73.90`，580 件就差 58 分。显示可以 `toFixed(4)` 或按需截断，但**回传必须原值**。
6. **涨红跌绿**：这是中国习惯，PC 端也是这么做的；金额为负（`uninvoiced_amount` 可能为负）用绿色。
7. **`order_date` 是纯日期字符串**：`new Date("2026-10-20")` 在 iOS 上会按 UTC 解析导致差一天，
   要么 `new Date("2026-10-20T00:00:00")`，要么直接按字符串截取显示。

---

## 8. 当前限制与后续计划（如实告知）

| 限制 | 影响 | 计划 |
|---|---|---|
| 业务接口（商品/订单等）**不做鉴权** | 内网单机部署下无风险；公网暴露必须加网关 | 上线前统一加 `get_current_user`，或只经反代暴露 `/agent/*` |
| 列表无 `keyword` 参数 | 移动端需全量拉取后本地过滤（262 条可接受） | 数据量涨到 2000+ 时再加服务端搜索 |
| `agent/stock-alerts`、`agent/orders` 为 501 | 智能体暂时只能拿概览 | 第二阶段实现（复用 `erp_stock_alert` 现成查询） |
| 无 refresh token | 每 60 分钟需重登 | 可在小程序端用 `wx.login` 换 session 后静默重登 |
| 写操作无幂等键 | 弱网重试可能重复建单 | 建议前端用 `order_no` 自定义单号去重（同号会被 400 拦下） |

---

## 9. 自测清单（接完先跑这 7 条）

```bash
BASE=http://192.168.1.20:8010/api/v1

# 1 探活
curl --noproxy '*' $BASE/health

# 2 登录（记下 access_token）
curl --noproxy '*' -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin123"}'

# 3 无 token 访问 agent → 必须 401
curl --noproxy '*' -o /dev/null -w '%{http_code}\n' $BASE/agent/summary

# 4 带 token → 200
curl --noproxy '*' $BASE/agent/summary -H "Authorization: Bearer $TOKEN"

# 5 商品 262 条
curl --noproxy '*' "$BASE/products?limit=5" -H "Authorization: Bearer $TOKEN"

# 6 出库单列表（含结算四件套）
curl --noproxy '*' "$BASE/sales-orders?doc_type=outbound&limit=1" -H "Authorization: Bearer $TOKEN"

# 7 占位接口 → 501（不是 500）
curl --noproxy '*' -o /dev/null -w '%{http_code}\n' $BASE/agent/orders -H "Authorization: Bearer $TOKEN"
```

---

*文档随 API 变更同步维护。新增接口请先补本表，再写代码。*
