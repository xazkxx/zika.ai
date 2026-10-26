/**
 * usePartnerCategories —— 分类树的数据层（加载 / 拖拽 / 索引 / 路径）
 *
 * 为什么数据层不塞进 `PartnerTree.jsx`：
 *   右侧表格的「分类」列与"按分类过滤"都要用同一棵树（要 `pathLabel` / `subtreeIds`）。
 *   如果树只活在树组件内部，页面就得再拉一遍接口 —— 两份数据必然不同步，
 *   而"拖完表格不刷新"正是这一轮要解决的问题。
 *   所以：**数据在页面（这个 hook），交互在组件（`<PartnerTree />`）**。
 *
 * 拖拽采用**乐观更新 + 失败整体回滚**：
 *   松手瞬间本地就把节点挪过去（不等网络），后端 400/500 时把快照灌回去。
 *   这棵树的大小是几十个节点，深拷贝的成本远低于"拖完转圈等接口"的体感损失。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  applyMove,
  indexTree,
  insertNode,
  nextSortOrder,
  pathLabel,
  recomputeTotals,
  removeNode,
  renameNode,
  subtreeIds,
  validateCategoryName,
} from '../../lib/partnerTree.js';
import {
  createCategory,
  deleteCategory,
  fetchCategories,
  moveCategory,
  updateCategory,
} from './partnerTreeApi.js';

export function usePartnerCategories({ kind = 'customer', apiBase, authHeaders } = {}) {
  const [tree, setTree] = useState([]);
  const [loading, setLoading] = useState(true);
  // 是否**成功**拉过一次。区分"分类为空"和"还没加载完"：
  // 表格的「分类」列靠它决定显示「未分类」还是「…」，判错会把整列刷成未分类。
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  /**
   * 错误状态码（0 = 网络层失败）。
   * 为什么要分开存：`404` 意味着**这个后端进程里没有这条路由**（代码没合并 / 没重启），
   * 这时左侧树应该照常显示「全部 / 未分类」并给一条安静提示，而不是弹一个红色报错把人吓住。
   */
  const [errorStatus, setErrorStatus] = useState(0);
  const [moving, setMoving] = useState(false);
  /** 新建 / 改名 / 删除 正在进行（按钮禁用，避免连点造出两个同名节点） */
  const [busy, setBusy] = useState(false);

  // 组件卸载后不再 setState（快速切页时接口可能后到）
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchCategories(kind, { apiBase, authHeaders });
      if (!alive.current) return;
      setTree(recomputeTotals(next));
      setLoaded(true);
      setError('');
      setErrorStatus(0);
    } catch (err) {
      if (!alive.current) return;
      setError(err?.message || '加载分类失败');
      setErrorStatus(Number(err?.status) || 0);
      // 加载失败时**不清空**已有的树：一次短暂断网不该把用户正在拖的树打空。
      // 首次加载就失败的话 tree 本来就是 []，界面照样有「全部 / 未分类」两个出口。
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [kind, apiBase, authHeaders]);

  useEffect(() => {
    reload();
  }, [reload]);

  const index = useMemo(() => indexTree(tree), [tree]);

  /** 节点全路径（表格「分类」列用）；找不到 → 空串，由调用方回落「未分类」 */
  const pathOf = useCallback((id) => pathLabel(index, id), [index]);

  /** 选中分类的整棵子树 id 集（含自己） */
  const idsOf = useCallback((id) => subtreeIds(index, id), [index]);

  /**
   * 拖拽落点提交。
   * @returns {Promise<boolean>} 是否真的移动了（非法落点直接 false，不发请求）
   */
  const move = useCallback(
    async (dragId, { parentId = null, beforeId = null } = {}) => {
      const snapshot = tree;
      const { roots, changed } = applyMove(tree, dragId, parentId, beforeId);
      if (!changed) return false;

      setTree(recomputeTotals(roots));
      setMoving(true);
      setError('');
      try {
        await moveCategory(kind, dragId, { parentId, beforeId }, { apiBase, authHeaders });
        return true;
      } catch (err) {
        if (alive.current) {
          setTree(snapshot); // 整棵回滚：绝不让界面停在一个"库里并不存在"的结构上
          setError(err?.message || '移动分类失败，已还原');
          setErrorStatus(Number(err?.status) || 0);
        }
        return false;
      } finally {
        if (alive.current) setMoving(false);
      }
    },
    [tree, kind, apiBase, authHeaders],
  );

  /**
   * 批量移动（多选拖拽 / 多选操作条）。
   *
   * ⚠️ 必须**串行**：服务端 `_move` 每次都会把目标父级下所有兄弟的 sort_order
   * 重排成 10/20/30 —— 并发 N 个请求，后到的会覆盖先到的，顺序必乱。
   * 也不能复用上面的 `move()`：它的 `tree` 是闭包值，循环到第 2 条时拿到的
   * 还是第 1 条**之前**的树，乐观更新会互相踩。所以这里用本地 `working`
   * 副本逐条推进，每条都基于前一条之后的状态。
   *
   * 失败处理：某条被后端拒绝 → 立即停止；前面几条已经改变了兄弟顺序，
   * "逆向补偿"算不回来，直接重新 GET 整棵树（后端真值最可信）。
   *
   * 批量固定 `before_id = null`（追加到目标末尾）：多个节点来自不同父级，
   * 它们的相对顺序在目标里没有语义。
   *
   * @param {number[]} ids 已归一化的待移动 id（调用方先用 `batchMovePlan`）
   * @param {number|null} parentId 目标父级；null = 移到顶级
   * @returns {Promise<{moved:number,total:number}|null>} null = 一条都没成功
   */
  const batchMove = useCallback(
    async (ids, parentId) => {
      const list = (Array.isArray(ids) ? ids : []).map(Number).filter(Number.isFinite);
      if (!list.length) return null;
      let working = tree;
      let moved = 0;
      setMoving(true);
      setError('');
      try {
        for (const id of list) {
          const { roots, changed } = applyMove(working, id, parentId, null);
          if (!changed) break; // 节点已经不在树里（并发删除）：剩下的也没必要试了
          const snapshot = working;
          working = recomputeTotals(roots);
          setTree(working); // 乐观推进：N 条全部完成后界面已经是对的了
          try {
            await moveCategory(kind, id, { parentId, beforeId: null }, { apiBase, authHeaders });
            moved += 1;
          } catch (err) {
            if (alive.current) {
              setTree(snapshot); // 至少把"这一条"回滚掉
              setError(err?.message || '移动分类失败，已还原');
              setErrorStatus(Number(err?.status) || 0);
            }
            if (moved > 0 && alive.current) await reload();
            return moved ? { moved, total: list.length } : null;
          }
        }
        return { moved, total: list.length };
      } finally {
        if (alive.current) setMoving(false);
      }
    },
    [tree, kind, apiBase, authHeaders, reload],
  );

  /** 统一的错误落点：把后端 400/409 的中文 detail 原样显示（后端文案已经写得很具体了） */
  const fail = useCallback((err, fallback) => {
    setError(err?.message || fallback);
    setErrorStatus(Number(err?.status) || 0);
  }, []);

  /** 同级兄弟（校验重名用） */
  const siblingsOf = useCallback(
    (parentId) => {
      const target = parentId === null || parentId === undefined ? null : Number(parentId);
      return (index.childrenOf.get(target) || []).map((id) => index.byId.get(id)).filter(Boolean);
    },
    [index],
  );

  /**
   * 新建分类。
   * @returns {Promise<Object|null>} 成功返回服务端创建的节点（带真 id），失败 null
   */
  const create = useCallback(
    async (parentId = null, name = '') => {
      const problem = validateCategoryName(name, siblingsOf(parentId));
      if (problem) {
        setError(problem);
        return null;
      }
      setBusy(true);
      setError('');
      try {
        // sort_order 由这里算「同级最大 + 10」并发下去：让"新节点排最后"服务端与前端一致，
        // 否则服务端默认 0 会把新节点排到所有兄弟**前面**。
        const created = await createCategory(
          kind,
          { parentId, name: String(name).trim(), sortOrder: nextSortOrder(index, parentId) },
          { apiBase, authHeaders },
        );
        if (alive.current && created) {
          setTree((prev) => recomputeTotals(insertNode(prev, parentId, created)));
          setLoaded(true);
        }
        return created || null;
      } catch (err) {
        if (alive.current) fail(err, '新建分类失败');
        return null;
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [kind, apiBase, authHeaders, index, siblingsOf, fail],
  );

  /** 重命名。@returns {Promise<boolean>} */
  const rename = useCallback(
    async (id, name) => {
      const row = index.byId.get(Number(id));
      const parentId = index.parentOf.has(Number(id)) ? index.parentOf.get(Number(id)) : null;
      const problem = validateCategoryName(name, siblingsOf(parentId), id);
      if (problem) {
        setError(problem);
        return false;
      }
      if (row && row.name === String(name).trim()) return true; // 没改，省一次请求

      setBusy(true);
      setError('');
      try {
        const updated = await updateCategory(kind, id, { name: String(name).trim() }, { apiBase, authHeaders });
        if (alive.current) {
          setTree((prev) => recomputeTotals(renameNode(prev, id, (updated && updated.name) || String(name).trim())));
        }
        return true;
      } catch (err) {
        if (alive.current) fail(err, '重命名失败');
        return false;
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [kind, apiBase, authHeaders, index, siblingsOf, fail],
  );

  /**
   * 删除。后端在「有子级」或「仍被档案引用」时返回 409 并带中文原因，
   * 这里原样显示 —— 不要自己编一句"删除失败"，用户需要知道到底是哪一类挡住的。
   * @returns {Promise<boolean>}
   */
  const remove = useCallback(
    async (id) => {
      setBusy(true);
      setError('');
      try {
        await deleteCategory(kind, id, { apiBase, authHeaders });
        if (alive.current) setTree((prev) => recomputeTotals(removeNode(prev, id)));
        return true;
      } catch (err) {
        if (alive.current) fail(err, '删除分类失败');
        return false;
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [kind, apiBase, authHeaders, fail],
  );

  return {
    tree,
    loading,
    loaded,
    error,
    errorStatus,
    /** 后端没有这条路由（代码没合并 / 没重启）—— 界面走"安静降级"而不是红色报错 */
    notReady: errorStatus === 404,
    moving,
    busy,
    reload,
    move,
    batchMove,
    create,
    rename,
    remove,
    index,
    pathOf,
    idsOf,
    setError,
  };
}
