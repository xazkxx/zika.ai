# 项目初始化提示词（给 Claude Code / Cursor 用）

> 用法：在 Taro 项目根目录新建会话，把下面 **『提示词正文』** 整段复制粘贴进去即可。
> 建议同时把 `docs/外部端接入_API指南.md` 放到新项目里（或在提示词里改成本机路径引用）。

---

## 提示词正文（从下一行开始复制）

```text
你是我的前端搭档。我们要开发一个「微信小程序端的 ERP 客户端」，后端已经存在并稳定运行，你只需要对接，不要设计/修改后端。

# 一、后端是什么

一套已经在用的本地 ERP（FastAPI + PostgreSQL），PC 端已封版。现在要做手机端，让老板和业务员在手机上：
看经营概览、查商品、查单据、给客户下单。

- API 前缀：/api/v1
- 开发环境地址：http://<局域网IP>:8010  （后端监听 0.0.0.0:8010，手机同一 WiFi 可直连）
  请把 BASE_URL 做成唯一常量，放在 src/config.ts，并在 README 写明怎么改。
- 完整接口文档在本仓库 docs/外部端接入_API指南.md，**动代码前先读它**。以下是必须记住的硬事实：

## 鉴权
- 登录：POST /api/v1/auth/login，**JSON body**（不是 form-urlencoded）：
  { "username": "...", "password": "...", "company": "public" }  // company 可省略
  返回 { access_token, token_type:"bearer", role, company, company_name, companies:[...] }
- 之后所有请求带：Authorization: Bearer <access_token>
- token 有效期 **60 分钟**，没有 refresh token。
  401 一律 = 清 token、跳登录页。
- 账套（多公司）**写死在 token 里**：切换账套要 POST /auth/switch-company { company }
  拿回**新 token** 并覆盖本地，否则读到的是旧公司数据。
- **哪怕业务接口后端不强制鉴权，也必须带 token**，否则会落到默认账套，读到别家数据。

## 错误格式
- 统一 { "detail": "中文人话" }，HTTP 状态码表意：400 参数错 / 401 未登录 / 403 停用 / 404 不存在 / 409 状态冲突 / 501 未开放 / 500 异常。
- ⚠️ 409 的 detail **可能是对象**（单据完结闸）：
  { "detail": { "code":"not_settled", "outstanding_amount":1000, "uninvoiced_amount":1000, "message":"..." } }
  封装里必须两种都兜住：typeof detail === 'string' ? detail : (detail.message || '操作失败')

## 数据约定（踩过坑，务必遵守）
- 金额：数字（元），两位小数。**合计永远用后端返回的 total_amount，不要前端反算**。
- 单价：数字，**最多 4 位小数**。⚠️ 显示可以截断，**回传必须是原值**，绝不能 toFixed(2)（73.901×580 会差 58 分）。
- 日期：order_date 是 "2026-10-20" 纯日期字符串；created_at/signed_at 是 ISO8601 带时区。
  ⚠️ iOS 上 new Date("2026-10-20") 会差时区，用 new Date(s + "T00:00:00") 或直接字符串截取。
- 列表分页：?skip=0&limit=20；**不传 limit 后端返回全量**。
- 商品/客户/供应商列表**没有 keyword 参数** → 搜索做"一次性拉全量 + 本地过滤"，输入框不要每敲一下就发请求。
- 商品图片 image_url 是相对路径，要拼 BASE_HOST 前缀（http://ip:8010 + image_url）。
- 金额颜色遵循中国习惯：**涨/正数用红，跌/负数用绿**。

# 二、核心接口（够你写完全部页面）

1. 登录：POST /auth/login
2. 校验 token：GET /auth/me
3. 经营概览（必须带 token）：GET /agent/summary
   返回：generated_for, generated_at,
        counts{customers,suppliers,products},
        today{sales_amount,sales_orders},
        receivable{total,received,outstanding},
        payable{total,paid,outstanding},
        sales_orders_by_status{status:count}, purchase_orders_by_status{...}
4. 商品：GET /products?skip=&limit=
   字段：id, sku, name, category, unit, purchase_price, sale_price, tax_rate(可能 null), mnemonic, standards, image_url, pack_qty
5. 商品辅助单位：GET /products/{id}/units
   → [{id, product_id, unit_name, factor, price, sale_price, bar_code, is_default, is_enabled, sort_order}]
   注意字段叫 **unit_name** 不是 name；factor = 1 个该单位等于几个基本单位；开单下拉只取 is_enabled=true
6. 客户：GET /customers?skip=&limit=
   → id, code, name, phone, email, address, contact, contact_phone, tax_no, businesser, discount, credit_limit, category_id
   ⚠️ 客户档案里**没有欠款字段**；要知道客户欠多少，读该客户最新单据上的 total_debt（客户累计口径）
7. 仓库：GET /warehouses?only_active=true → id, code, name
8. 销售单列表：GET /sales-orders?doc_type=outbound|order&customer_id=&skip=&limit=
   单条结构（列表已含 items，不需要详情接口）：
   id, order_no, customer_id, doc_type, status, order_date, warehouse_id,
   total_amount, items[{product_id, product_name, quantity, unit, unit_price, amount, unit_factor}],
   logistics_company, logistics_no, signed_by, signed_at,
   invoice 四件套：invoiced_amount, outstanding_amount, uninvoiced_amount, settled(boolean),
   客户欠款口径：current_debt, prev_debt, total_debt
9. 新建销售单：POST /sales-orders（成功 **201**）
   { customer_id, doc_type:"order"|"outbound", order_date:"2026-10-20",
     warehouse_id, note, items:[{ product_id, quantity(整数), unit_price, unit:"公斤"|"箱"(可选) }] }
   ⚠️ 不传 doc_type = outbound = **立刻扣库存并产生应收**。做"订货"必须显式 doc_type:"order"。
   ⚠️ 采购侧对称：POST /purchase-orders 不传 doc_type 默认 inbound（立刻入库记账）。
10. 改状态：PATCH /sales-orders/{id}/status  { "status": "approved" }
    合法值：订单 draft→pending→approved→completed；即时单 draft→submitted→completed；
    任意非终态→cancelled；completed/cancelled 是终态。
    ⚠️ 出库单改 completed 有闸：未结清/未开票 → 409（detail 是对象）。
11. 反审核：PATCH /sales-orders/{id}/unsubmit（有流水 → 409，仅订单有意义）
12. 占位接口：GET /agent/stock-alerts、GET /agent/orders → **501**，收到就当"功能未开放"，置灰入口，不要弹错误。

# 三、状态标签中文（照抄，别自创）

零售端展示用两套，**按 doc_type 分开**：
- 订单 doc_type=order：draft 草稿 / pending 待审核 / approved 已审核 / completed 已转单 / cancelled 已取消
- 出库单 doc_type=outbound：draft 草稿 / submitted 已提交 / completed **已发货** / cancelled 已取消
（出库单的 completed 是"已发货"，不是"已转单"——这是踩过的文案 Bug）

# 四、技术栈与工程约定

- Taro 4 + React 18 + TypeScript，目标平台：微信小程序（H5 也要能跑，方便调试）
- 状态管理用最轻的：React Context + hooks 就够，不要引入 Redux/MobX
- 样式：SCSS 模块化，尺寸统一用 px（Taro 会转 rpx），不要写死 750rpx 布局
- 目录：
  src/
    config.ts            // BASE_URL / BASE_HOST
    services/request.ts  // 唯一请求封装（注入 token、401 跳登录、错误 toast）
    services/api.ts      // 按域导出的函数：login/getSummary/getProducts/getOrders/createOrder...
    types/api.ts         // 所有响应 TS 接口定义，字段名与后端**完全一致**（蛇形，不要驼峰转换）
    store/auth.ts        // token + 用户信息 + 账套，持久化到 Taro storage
    utils/money.ts       // 金额格式化（千分位 + 两位小数，只为显示）
    pages/login/         // 登录（账号密码）
    pages/home/          // 经营概览卡片（读 /agent/summary）
    pages/products/      // 商品列表 + 本地搜索
    pages/orders/        // 单据列表（tab: 订单 / 出库单）+ 状态徽标
    pages/order-detail/  // 单据详情（含结算四件套展示）
    pages/order-create/  // 开单（选客户 → 加商品 → 提交）

- 所有接口调用必须走 services/request.ts，页面里不准直接 Taro.request。
- 类型定义里的字段名用后端的蛇形（customer_id、total_amount），**不要**做 camelCase 映射层——
  多一层转换就多一处对不上的地方。

# 五、界面要求

1. 登录页：账号、密码、账套（下拉，登录成功后才有多账套可切换的话可以只显示当前公司）。
2. 首页：四张卡——今日销售（金额+单数）、应收余额、应付余额、档案数（客户/供应商/商品）。
   数据来自 /agent/summary，下拉刷新重取。**金额用红色显示（中国习惯）**。
3. 商品页：搜索框（本地过滤 name/sku/mnemonic）+ 列表（图片、名称、规格、销售价）+ 上拉加载更多（skip/limit 分页）。
4. 单据页：顶部两个 tab（销售订单 / 销售出库），列表项显示单号、客户、日期、金额 + **三种状态徽标**：
   状态 / 收款（settled 绿、否则显示"欠 ¥x"红）/ 发货（signed_at 有值=已签收）。
5. 详情页：单据头 + 明细表 + 金额汇总 + 物流信息 + 结算四件套（已开票/应收余额/未开票/是否结清）。
6. 开单页：选客户（搜索）→ 选仓库 → 加商品（搜索+加减数量，单价默认 sale_price 可改）→ 提交。
   提交成功 toast 单号并返回列表；409/400 必须原样展示后端 detail。

# 六、交付与验收（做完自己先跑一遍）

交付前必须满足：
1. `npm run build:weapp` 通过，无 TS 报错（tsc --noEmit 也过）。
2. 手动跑通这 5 条：登录 → 首页看到真实数字 → 商品列表能搜到 → 单据列表状态徽标正确 → 开一张 doc_type=order 的订单并在 PC 端能看到。
3. 401 场景验证：手动清掉 storage 里的 token，任意页面请求应自动跳登录页，不能白屏、不能无限弹 toast。
4. 409 场景验证：对一张未结清的出库单点"完结"，必须原样显示后端中文提示（不是 [object Object]）。
5. 不给后端加任何接口、不改后端代码；发现接口不够用，写进 README 的「待后端支持」清单，不要自己造 mock 长期留着。

# 七、绝对不要做的事

- ❌ 不要改后端代码 / 不要连数据库 / 不要动 PC 端前端仓库。
- ❌ 不要在前端自己算合计、应收余额、是否结清——一律用后端字段。
- ❌ 不要对单价做 toFixed(2) 后回传。
- ❌ 不要把金额、状态文案硬编码在多个页面里——统一放 constants。
- ❌ 不要引入 UI 组件库（不用 Vant/Taro UI），样式手写，保持轻量。
- ❌ 不要用 /agent/* 的 501 接口做"暂时 mock 一下然后忘了删"。

现在请先做三件事，做完等我确认再继续：
1) 输出一份执行计划（文件清单 + 每个文件的职责 + 依赖顺序）；
2) 把 types/api.ts 和 services/request.ts 两个文件的完整代码写出来；
3) 列出你需要我提供的两个信息：局域网 IP 是多少、用哪个账号做联调。
```

---

## 使用小贴士

1. **先给 IP 再让它写代码**，否则它会自己编 `localhost`，小程序真机永远连不上。
2. 让 AI **先读 `docs/外部端接入_API指南.md`** 再动手；那份文档里有真实响应样例，能省掉它瞎猜字段。
3. 第一次联调建议在**微信开发者工具**里跑，并勾选「不校验合法域名」；真机预览要保证手机和电脑同一 WiFi。
4. AI 如果开始"顺手优化后端"或"帮你加个搜索接口"，立刻打断——PC 端已封版，后端改动一律走你确认。
