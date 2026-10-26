# -*- coding: utf-8 -*-
"""第二阶段 P2-4（返回按钮）：全局「← 返回」，不是逐页塞按钮。

用户原话：「全局排查二级页面加返回按钮」。
逐页加的问题：二级页面有几十个，漏一个就有一条"死胡同"；而且同一个页面
既可能是入口页、也可能是二级页，写死按钮会出现"没上一页可回"的空按钮。

做法：在 App 里维护一个**页内导航栈**（最多 20 层），顶栏在栈非空时才渲染
「← 返回」。任何页面跳转都会自动入栈，业务组件一行都不用改。
"""
import shutil
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.jsx"
shutil.copy2(APP, APP.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))

text = APP.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sub_once(source, old, new, label):
    n = source.count(old)
    assert n == 1, f"[{label}] 命中 {n} 次"
    return source.replace(old, new)


# ---------------------------------------------------------------- 1. state
text = sub_once(
    text,
    """  const [selectedTab, setSelectedTab] = useState('overview');
""",
    """  const [selectedTab, setSelectedTab] = useState('overview');
  // 页内导航栈：[{ tab, label }]。只用于顶栏「← 返回」，不参与业务判定。
  const [navHistory, setNavHistory] = useState([]);
""",
    "nav-state",
)

# ------------------------------------------------- 2. 入栈逻辑（放在 currentActions 之后）
text = sub_once(
    text,
    """  // 当前页面该显示在顶栏右上角的快捷入口（见文件顶部的 pageActions）
  const currentActions = pageActions[selectedTab] || [];
""",
    """  // 当前页面该显示在顶栏右上角的快捷入口（见文件顶部的 pageActions）
  const currentActions = pageActions[selectedTab] || [];

  // —— 页内导航栈（P2-4）：每换一页就把"上一页"压进去 ——
  // 用 ref 记住"这一帧是哪一页、叫什么"，effect 里比对 selectedTab 变化后入栈。
  // 不用 selectedTab 当依赖去算上一个值：那样拿到的是旧 state，不是旧页面名。
  const navCurrentRef = useRef({ tab: selectedTab, label: currentPageLabel });
  navCurrentRef.current = { tab: selectedTab, label: currentPageLabel };
  useEffect(() => {
    setNavHistory((stack) => {
      const last = stack[stack.length - 1];
      // 同一页反复进（比如退款单 → 客户 → 退款单）不该堆成三层
      if (!last || last.tab === selectedTab) return stack;
      return stack;
    });
  }, [selectedTab]);

  // 真正入栈：监听 selectedTab 变化，把变化**之前**那一页压进去
  const navPrevRef = useRef(selectedTab);
  const navPrevLabelRef = useRef(currentPageLabel);
  useEffect(() => {
    if (navPrevRef.current === selectedTab) {
      navPrevLabelRef.current = currentPageLabel;
      return;
    }
    const prevTab = navPrevRef.current;
    const prevLabel = navPrevLabelRef.current;
    navPrevRef.current = selectedTab;
    navPrevLabelRef.current = currentPageLabel;
    setNavHistory((stack) => {
      if (stack[stack.length - 1]?.tab === prevTab) return stack;
      const next = [...stack, { tab: prevTab, label: prevLabel }];
      return next.length > 20 ? next.slice(next.length - 20) : next;
    });
  }, [selectedTab, currentPageLabel]);

  /** 回到上一页；栈空了就什么都不做（按钮本身也不会渲染）。 */
  const goBack = useCallback(() => {
    setNavHistory((stack) => {
      if (!stack.length) return stack;
      const target = stack[stack.length - 1];
      setSelectedTab(target.tab);
      setActiveMenuEntry(null);
      return stack.slice(0, -1);
    });
  }, []);
""",
    "nav-push",
)

# --------------------------------------------------------------- 3. 顶栏渲染
text = sub_once(
    text,
    """        <header className="topbar">
          <div>
            <p className="eyebrow">{currentGroupLabel}</p>
            <h1>{currentPageLabel}</h1>
          </div>
""",
    """        <header className="topbar">
          <div className="topbar-heading">
            {navHistory.length > 0 && (
              <button
                type="button"
                className="back-btn"
                data-nav-back
                onClick={goBack}
                title={`返回：${navHistory[navHistory.length - 1]?.label || '上一页'}`}
              >
                ← 返回
              </button>
            )}
            <div>
              <p className="eyebrow">{currentGroupLabel}</p>
              <h1>{currentPageLabel}</h1>
            </div>
          </div>
""",
    "topbar",
)

# ---------------------------------------------------------------- 4. ctx 导出
text = sub_once(
    text,
    """  currentGroupLabel,
""",
    """  currentGroupLabel,
  goBack,
  navHistory,
""",
    "ctx-export",
)

APP.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK App.jsx 全局返回按钮已接")
