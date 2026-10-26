# ERP Core 中文版

这是一个适合本地部署、可扩展的 ERP 系统，目标：本地通用 ERP + 手机端（iOS/安卓 PWA）+ AI 智能体。

## 当前版本

- 后端：Python + FastAPI + SQLAlchemy
- 数据库：SQLite（本地开发，可切换 PostgreSQL）
- 权限：JWT 登录认证
- 前端：React + Vite，已支持 PWA（可安装到桌面/手机主屏幕）
- HTTPS：mkcert 本地证书（局域网手机可直接安装使用）

## 已包含模块

- 用户与权限（登录认证）
- 客户管理、供应商管理、产品管理
- 采购订单、销售订单、库存管理
- 财务管理（收付款、分析、决策支持）
- **现金银行**：资金账户（现金/银行）、账户转账、账户流水账（期初 / 流入 / 流出 / 期末）；
  余额只认**真实资金移动**（日常收支、收付款、转账），应收应付 / 成本 / 报损报溢不进余额
- **日常收支**：经营收支登记（类别走数字字典）、按类型/账户/日期/关键字筛选与合计；
  只有**人工登记**的收支能在此删除，单据自动生成的流水须回原单处理
- 生产模块、BOM 结构、项目管理
- 库存管理：现存量、调拨、盘点、报损报溢、**组合拆卸**（配方读 BOM）
- 分析模块（采购建议、供应商绩效、库存预警）
- 报表中心（16 张报表）、发票 OCR 识别
- AI 智能体（移动助手，支持 DeepSeek 大模型）
- 系统管理：组织机构 / 角色 / 用户（菜单级权限）、参数设置、数字字典、打印模板、操作日志、**菜单管理**
- **发票管理**（财务管理组）：上传发票原件**自动留档**，区**进项/销项**（按本公司税号自动判定，
  可一键重判或逐张手改）、蓝字/红字、手工开票/对接开票；可**下载原件**、按进销项
  **导出原始发票 PDF 压缩包**（导出的是原件，不是重新排版的表格）
- **动态菜单**：左侧导航的层级与名称存在数据库里，可在「系统设置 → 菜单管理」自行增删
  （分组 → 子分组 → 菜单项，最多 3 层）、改名、调顺序、隐藏、删除，并可一键恢复默认。
  菜单项只能挂到**已有页面**上（后台校验），所以调整的是"页面的位置与叫法"，不是造新页面
- 基础资料：客户 / 供应商 / 商品 / 仓库 / **员工档案**；**期初建账**（库存 + 应收 + 应付）
- 移动端界面 + PWA 安装

## 目录结构

```text
app/                # 后端（FastAPI）
  api/v1/routes/    # auth.py 认证 / erp.py 业务接口
  core/             # 配置与安全
  db/               # 数据库会话
  models/           # 数据模型（含 print_template / operation_log / system_config 等）
frontend/           # 前端（React + Vite）
  public/           # PWA 清单、服务工作者、图标、CA 证书
  src/              # App.jsx 主界面
harmonyos/          # 鸿蒙端（DevEco Studio / ArkTS，WebView 壳）
certs/              # mkcert 生成的 HTTPS 证书（私钥不入库，见「证书说明」）
tests/              # 后端回归测试（342 例，含 prod_snapshot.py 正式库快照保护）
scripts/ops/        # 运维脚本（库+附件备份 / 数据库密码轮换）
```

## 快速开始

后端：

```powershell
Set-Location 'E:\AI\ERP软件'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

前端（自动启用 HTTPS，证书来自 certs/）：

```powershell
Set-Location 'E:\AI\ERP软件\frontend'
npm run dev
```

访问地址：

- 前端：https://localhost:5173
- 接口文档：http://127.0.0.1:8010/docs

## 手机端使用（PWA）

1. 手机与电脑连接同一 Wi-Fi，打开：`https://<电脑局域网IP>:5173`
2. 首次需信任证书：手机浏览器打开 `https://<电脑IP>:5173/ca/rootCA.pem` 下载并安装
   - 安卓：设置 → 安全 → 加密与凭据 → 安装证书 → CA 证书
   - iPhone：下载描述文件 → 设置 → 已下载描述文件 → 安装 → 通用 → 关于本机 → 证书信任设置 → 开启信任
3. 浏览器菜单 → 添加到主屏幕，即可像 App 一样使用（支持离线打开）

## 证书说明

- 证书由 mkcert 生成，位于 certs/ 目录，有效期至 2028-12-24
- 电脑 IP 若变化（路由器 DHCP），需重新生成证书：
  `certs\mkcert.exe -cert-file certs\cert.pem -key-file certs\key.pem <新IP> localhost 127.0.0.1`
- **私钥不在 Git 里**：`certs/` 已加入 .gitignore（2026-10-26 移出版本控制）。
  换电脑或重装系统前，请手工把 `certs\key.pem`、`certs\rootCA-key.pem` 复制到安全位置，
  否则手机端要重新安装 CA。公开 CA 证书 `frontend/public/ca/rootCA.pem` 仍在库内（给手机安装用）。

## 运维脚本（scripts/ops）

| 脚本 | 作用 |
|---|---|
| `scripts\ops\backup_db.ps1` | pg_dump 全库 + 打包 `data/` 附件（合同/发票原件），各保留最近 14 份，追加写 `backup\backup_history.log` |
| `scripts\ops\rotate_db_password.ps1` | 改 PostgreSQL 密码 → 同步 `.env` → 用新密码回连验证，一条命令完成 |

数据库密码只存在 `.env`（不入库），所有脚本都从那里读，**改密码不需要改任何脚本**：

```powershell
# 1) 干跑：只打印将要做的事，不动数据库
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\rotate_db_password.ps1 -DryRun
# 2) 真改：自动生成 24 位强密码（也可 -NewPassword '自定义'）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\rotate_db_password.ps1
# 3) 改完重启后端（uvicorn 只在启动时读 .env）
```

- 计划任务「ERP数据库备份」（每日 21:37）入口仍是 `backup\backup.ps1`，
  它现在只是 3 行转发器，真正的脚本是版本化的 `scripts\ops\backup_db.ps1`，任务本身无需改动。
- `backup/` 整个目录被 .gitignore 忽略，所以脚本的权威副本放在 `scripts/ops/`。

## 下一步计划

1. AI 智能体接入大模型（DeepSeek）
2. 数据切换 PostgreSQL + 自动备份
3. 桌面端打包（Electron/Tauri）
4. 财务收尾剩余两项：**工资管理**（需先补计件/工时单据链，非补表单可了）、
   **开票管理**（开票视图实际已在「经营分析」页里，先确认是否只需把菜单接过去）
