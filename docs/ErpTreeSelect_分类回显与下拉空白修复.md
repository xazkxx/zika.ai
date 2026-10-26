# ErpTreeSelect：回显成了数字 id / 下拉一片空白（2026-10-21）

> 用户报障：「编辑客户」里分类选的是「施工一部」，输入框却显示 **330**；
> 点开下拉只有一个搜索框 + 「未分类」，分类节点一个都没有。
> 结论：**组件没坏，喂给它的数据形状不对**。改 `App.jsx` 一处，已修复并构建 v134。

---

## 根因：树被摊平了

`App.jsx::loadPartnerCategoryOptions` 还在用 **v75 的扁平形状**：

```js
// 旧（错的）
const options = [];
walk(data, '');                                  // 递归拼 "集团客户 / 华东分公司"
options.push({ value: String(node.id), label }); // [{value,label}]
setPartnerCategoryOptions(prev => ({ ...prev, [kind]: [{value:'',label:'未分类'}, ...options] }));
```

而弹窗 v76 已经换成树形组件：

```jsx
<ErpTreeSelect nodes={categoryOptions} value={String(form.category_id ?? '')} … />
```

`ErpTreeSelect` 的默认取值口径是 **`node.id` / `node.name` / `node.children`**
（见组件文件头「数据形状」）。拿到 `[{value,label}]` 之后：

| 症状 | 机制 |
|---|---|
| 输入框显示 `330` | `selectedLabel` 遍历树找不到 `node.id === '330'` → **走兜底显示原值**（这个兜底本来是给"分类被删后留下的孤儿 id"用的），于是把 id 原样印出来 |
| 下拉一片空白 | 渲染每个节点时读 `node.name` → `undefined` → 标签空、`getNodeChildren` 也取不到 `children`，只剩组件自带的「未分类」 |

> 关键点：组件**没有**报错。这正是它最坑的地方 —— 形状错了会静默退化成"数字 + 空列表"。

## 改法

```js
// 新（对的）：后端树原样传下去
const data = await response.json();
setPartnerCategoryOptions(prev => ({ ...prev, [kind]: Array.isArray(data) ? data : [] }));
```

- 不再拼路径前缀：**回显时组件自己拼**（`selectedLabel` 会输出「其他客户（临时） / 储能」）；
- 不再自己塞「未分类」：组件有 `allowClear` + `clearLabel`，面板里那条「未分类（不归属任何分支）」是它渲染的；
- 另外在登录后**预拉一次**两种分类：原先只在"弹窗打开"时拉，首帧会先闪一下原始 id，用户会当成回显失败。

接口 `GET /customer-categories` 返回的就是树（`{id,name,parent_id,children}`），
所以这条链路不需要任何后端改动。

---

## 全局体检结果

| 位置 | 数据源 | 状态 |
|---|---|---|
| 客户档案 → 编辑 → 所属分类 | `loadPartnerCategoryOptions('customer')` | **坏的 → 已修** |
| 供应商档案 → 编辑 → 所属分类 | `loadPartnerCategoryOptions('supplier')` | **坏的 → 已修** |
| 商品档案 → 编辑 → 类别 | `ctx.productCategories`（`/product-categories` 树） | 正常（`getNodeValue=node.name`） |
| 商品 → 批量移动 → 目标分类 | `ctx.productCategories` | 正常 |
| 销售 / 采购订单 | 没有分类树下拉（选商品/客户用的是 `ErpSearchSelect`，不是本组件） | 不受影响 |

实测（`scripts/verify_treeselect.cjs`，真浏览器 8/8）：

```
PASS  客户：分类回显是名称而不是纯数字 id  — "其他客户（临时） / 储能"
PASS  客户：下拉面板列出了分类节点  — 4 个节点（未分类 + 中铁一局集团2 / 国家电网公司1 / 其他客户（临时）1）
PASS  供应商：分类回显是名称而不是纯数字  — "国家电网公司"
PASS  商品：类别下拉有回显  — "其他"
PASS  商品：类别面板列出了节点  — 44 个
PASS  全程零页面错误
```

## 防回归

`tests/test_partner_category_options.py`（5 条，纯源码断言）：

- 分类选项必须 `Array.isArray(data) ? data : []`（原样传树）；
- 不许再出现 `value: String(node.id)` 与 `` `${prefix} / ${node.name}` ``（扁平形状的两处指纹）；
- `PartnerModal` 必须是 `nodes={categoryOptions}`；
- 组件默认按 `id/name/children` 取值（改这里要同步后端字段）。

## 版本

**v134 · 20261021-1920**。这次只改前端，**不用重启后端**，`Ctrl + F5` 即可。
