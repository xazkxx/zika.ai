# 需求 4（菜单下架）+ 单据明细 UI 崩坏 修复报告

日期：2026-10-18　｜　`erp-pwa-v41`　｜　构建戳 `20261018-2338`
验证：`verify_step6_menu_layout.mjs` **21/21**、`verify_bug1_payment_delete_guard.mjs` **37/37**（两套都含反证）
后端回归：`pytest test_menu_admin + test_menu_reorder + test_delete_endpoints + test_order_doc_type + test_order_settlement_and_finance_link + test_system_users` → **84 passed**

---

## 一、菜单为什么"删了还在"

用户第一次只看到前端 `menuGroups` 改过，侧边栏却还有「销售出库（多单位）」。根因是**两层**：

1. **展示用的是后端菜单树**：`visibleGroups` 优先用 `/system/menus` 下发的 `menuTree`，
   只改 `menuGroups` 只影响"全新安装的种子"，老库仍显示旧结构。
2. **启动迁移只补不删**：`_backfill_builtin_menus` 的语义是"缺则补"，这是**对的**
   （否则管理员删过的菜单每次重启都复活）。所以从 `PERMISSION_CATALOG` 删掉一项，
   库里那一行（public.menus id=3092）会一直躺着 —— 于是"代码里删了，界面还在"。

### 修复：四层一起改 + 一份"下架清单"

| 层 | 文件 | 改动 |
|---|---|---|
| 前端接线 | `App.jsx` | 删 `import`、删 `menuGroups` 项、删 `selectedTab === 'sales-units'` 分发块 |
| 权限目录 | `app/core/permissions.py` | 从「销售管理」items 移除（新装库不再播种） |
| 角色默认 | `app/models/role.py` | `sales` / `warehouse` 的 `menus` 去掉 `sales-units`；`manager` 由 `all_menu_keys()` 差集自动收敛 |
| 存量数据 | `app/main.py` | 新增 `MENU_RETIRED_KEYS` + `_retire_builtin_menus()`，启动时删库里的行并清掉角色 `permissions.menus` 里的残留 key |

```python
MENU_RETIRED_KEYS: tuple[str, ...] = ("sales-units",)

def _retire_builtin_menus(db) -> None:
    # 只删 is_builtin=True 的行（管理员自建的同名 key 不碰），子节点先删
    # roles.permissions 是 Text 存的 JSON 字符串 —— 直接 .get() 会让整个服务起不来
    ...
```

**踩到的坑**：`roles.permissions` 是 **Text 存的 JSON 字符串**（不是 JSONB），
第一版写成 `perms = role.permissions or {}` → `AttributeError: 'str' object has no attribute 'get'`，
而这个函数在 `create_app()` 里跑，**直接整个服务起不来**。已改为 `json.loads` + `json.dumps`。

实际数据结果：库里行已删（`public.menus` 查 `sales-units` → 空），
角色 `manager 48→47`、`sales 14→13`、`warehouse 14→13`。

> 组件源码 `frontend/src/components/sales-units/` **保留但不引用**（只作参考实现）。
> 它的 `handleDelete` 只走 `window.confirm` + `setListError`，是 Bug 1 的现场；
> 真要启回来，必须先把删单闸口接进去。

---

## 二、商品明细被压扁：两个原因叠加

真浏览器实测（1600×1000，销售订单页）：

| 场景 | 左栏 | 明细表可视宽 | 表格宽 | 结果 |
|---|---|---|---|---|
| 修复前，全局 `erp:mgrid:left=300` | 300px | **250px** | 600px | 横滚 350px，商品搜索框只剩半截 |
| 修复前，1366 宽 | 660px | 610px | 600px | 勉强放平，但右栏只剩 326px |

1. **拖拽宽度是全站共用一个 key**：`erp:mgrid:left`。用户在客户档案把左栏拖到 300px，
   回到单据页还是 300px —— 而明细表 `minWidth=600`，必然"压成一条 + 横滚"。
   `readStored()` 读出来**没有夹下限**（`clamp()` 只在拖动/窗口 resize 时跑）。
2. **分栏断点太低**：`@media (min-width:1081px)` 就分栏，但分栏要放得下
   `660(左) + 16(手柄) + 400(右栏下限) = 1076`，再减掉侧边栏 ~364px，
   视口 < 1440 根本放不下。

### 修复（4 处）

```jsx
// ResizableLayout.jsx —— 读出来当场夹下限；挂载即夹一次上限；容器装不下时下限优先
const [leftWidth, setLeftWidth] = useState(() => {
  const stored = readStored(storageKey);
  if (stored === null) return null;
  return Math.max(minLeft, stored);   // ← 别处拖的 300 不许带进单据页
});
```

```jsx
// 三张单据页（OrderBoard / PurchaseInboundBoard / SalesOutboundBoard）
<ResizableLayout
  className="doc-page"
  storageKey="erp:mgrid:doc"   // 单据页用自己的 key，跟档案页互不干扰
  minLeft={660}                // 660 = 明细表 600 + 卡片左右内边距 50
>
```

```css
/* docs.css —— 断点 1081 → 1440；窄屏单列堆叠（明细表拿整幅宽度） */
@media (min-width: 1440px) {
  .doc-page.management-grid.mgrid--split { grid-template-columns: var(--mgrid-left, 660px) 16px minmax(0, 1fr); }
}
@media (max-width: 1439px) {
  .doc-page.management-grid.mgrid--split { grid-template-columns: minmax(0, 1fr); gap: var(--space-4, 16px); }
  .doc-page .mgrid-handle { display: none; }   /* 不然手柄会把右栏顶到第二行 */
}
```

修好后实测：

| 场景 | 网格 | 明细表可视/表格宽 | 商品列 | 横滚 |
|---|---|---|---|---|
| 1600 + 全局 stale 300 | `660px 16px 560px` | 610 / 610 | 280px | 无 |
| 1600 + `erp:mgrid:doc=300` | 夹回 660 | 610 / 610 | 280px | 无 |
| 1366 | 单列 `1002px` | 952 / 952 | 622px | 无 |
| 1100 | 单列 `736px` | 686 / 686 | 356px | 无 |

---

## 三、验证矩阵

`verify_step6_menu_layout.mjs`（21 项，真 Chrome + 几何量）

- **菜单**：M1 后端菜单树无 `sales-units` / M2「可选页面」清单无它 / M3 销售管理其余 6 项完整 /
  M4 侧边栏渲染文本搜不到「多单位」
- **布局**：L1 1600 三分栏且左栏 ≥650 / L2 明细表 `scrollWidth ≤ clientWidth+1` /
  L3 商品列 ≥200 / L4 搜索框整体在视口内 / L5 页面无横向滚动条 /
  L6-L7 存了 300 也夹回 ≥650 且不横滚 / L8-L11 1366 单列、手柄隐藏、不横滚 /
  L12 采购入库页同样（共用 doc-page）
- G1 浏览器加载的 bundle = 本次构建 hash（防 SW 喂旧包）、G4 全程无 JS 异常

`verify_bug1_payment_delete_guard.mjs`（37 项）——界面层按新结构改写：
- G2 侧边栏已无「多单位」
- G3-G4 开单管理页**确实有**这张开单、**确实有删除按钮**（用户点的就是它）
- G5-G9 点删除 → 删除确认 → **专用拦截弹窗**（点名来源订单已登记资金流水、无强制删除后门）→ 关掉后单据还在

> 顺带纠正一个认知：`to-outbound` 出来的开单状态是 **`submitted`（已提交）**，不是 `completed`，
> 所以它在开单管理页**有删除按钮**。这正是 Bug 1 的真实入口 —— 闸口拦在这里，界面也给了明确文案。

### 反证（break → red → restore）

| 反证 | 改动 | 结果 |
|---|---|---|
| A 菜单 | 直接往 `public.menus` 插回一行 `sales-units` | **19/21**，只红 M1/M4；M2 仍绿（说明两条断言各管一层，不是重复）。重启后端后该行被 `_retire_builtin_menus` 自动清掉，恢复 21/21 |
| B 布局 | 去掉"读出来夹下限" + "挂载即夹" + 把断点改回 1081/1080 | **16/21**，红 L6/L7（`scroll=600 client=250`，正是用户截图那种状态）、L8/L10（1366 又变三栏）、L12（采购入库一起坏，证明修复是共享的） |

还原后 `grep -rn PROBE frontend/src frontend/public` = **0**，两套验证恢复 21/21 + 37/37。

---

## 四、上线

1. **重启后端**（必须）：下架迁移在 `create_app()` 里，重启才会删库里那一行 + 清角色残留 key。
   不重启的话，侧边栏仍会从旧进程的菜单树里拿到它。
2. **强刷**（Ctrl+F5）：`CACHE_VERSION=erp-pwa-v41`，侧边栏应无「销售出库（多单位）」。
3. 销售订单页：明细表 6 列一次排开、无横向滚动条、商品搜索框完整可见；
   1366 笔记本上改为上下单列（明细表占满宽度）。

> 不要用 `POST /system/menus/reset`：它会把默认树按当前目录整棵重播，
> 管理员自建的菜单会被一起清掉。下架走启动迁移即可，幂等。
