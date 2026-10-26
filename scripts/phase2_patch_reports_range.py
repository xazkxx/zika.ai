# -*- coding: utf-8 -*-
"""第二阶段 P2-4（报表日期）：把两个裸 date 输入换成「年/月下拉 + 快捷时段」。

用户原话：「报表中心日期选择器改版为『年份/月份下拉 + 快捷时间（本月/上月/今年）』」。

设计取舍：
  · 只保留**一个真相源** = reportQuery.date_from / date_to。
    年月下拉与快捷按钮都只是"往这两个字段里写值"，不另存 state——
    否则用户手动改日期时年月会显示错的（两份状态必然漂移）。
  · 自定义日期区间不删，收进「自定义区间」折叠里：月末结算、跨年对比仍然要用。
"""
import shutil
from datetime import datetime
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "ReportsPage.jsx"
shutil.copy2(PAGE, PAGE.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))

text = PAGE.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sub_once(source, old, new, label):
    n = source.count(old)
    assert n == 1, f"[{label}] 命中 {n} 次"
    return source.replace(old, new)


# ---------------------------------------------------------- 1. 计算与快捷逻辑
text = sub_once(
    text,
    """  } = ctx;
  return (
""",
    """  } = ctx;

  // —— 报表日期：年月下拉 / 快捷时段的派生与写入（P2-4）——
  // 单一真相源是 reportQuery.date_from / date_to，下面这些都只是"往里写"。
  const TODAY = new Date();
  const pad2 = (n) => String(n).padStart(2, '0');
  const monthEnd = (year, month) => new Date(year, month, 0).getDate(); // month 为 1-12
  const rangeYear = (reportQuery.date_from || '').slice(0, 4) || String(TODAY.getFullYear());
  const rangeMonth = (reportQuery.date_from || '').slice(5, 7) || pad2(TODAY.getMonth() + 1);
  // 「全年」判定：起止正好卡在 1 月 1 日 ~ 12 月 31 日
  const isFullYear =
    reportQuery.date_from === `${rangeYear}-01-01` && reportQuery.date_to === `${rangeYear}-12-31`;
  const yearOptions = Array.from({ length: 9 }, (_, i) => String(TODAY.getFullYear() - 5 + i));

  /** 按「年 + 月」写区间；month='all' 表示整年 */
  const applyRange = (year, month) => {
    if (!year) return;
    if (month === 'all') {
      setReportQuery((prev) => ({ ...prev, date_from: `${year}-01-01`, date_to: `${year}-12-31` }));
      return;
    }
    const end = monthEnd(Number(year), Number(month));
    setReportQuery((prev) => ({
      ...prev,
      date_from: `${year}-${month}-01`,
      date_to: `${year}-${month}-${pad2(end)}`,
    }));
  };

  /** 快捷时段：本月 / 上月 / 今年 */
  const applyQuickRange = (kind) => {
    const year = TODAY.getFullYear();
    const month = TODAY.getMonth() + 1;
    if (kind === 'this-month') {
      applyRange(String(year), pad2(month));
      return;
    }
    if (kind === 'last-month') {
      const prev = month === 1 ? { y: year - 1, m: 12 } : { y: year, m: month - 1 };
      applyRange(String(prev.y), pad2(prev.m));
      return;
    }
    applyRange(String(year), 'all');
  };

  return (
""",
    "range-helpers",
)

# ------------------------------------------------------------- 2. 工具栏改版
OLD = """                      <label className="report-field">
                        起
                        <input type="date" value={reportQuery.date_from} onChange={handleReportQueryChange('date_from')} />
                      </label>
                      <label className="report-field">
                        止
                        <input type="date" value={reportQuery.date_to} onChange={handleReportQueryChange('date_to')} />
                      </label>
"""
NEW = """                      {/* 年份 / 月份下拉：选完立刻把起止日期写进 reportQuery */}
                      <label className="report-field">
                        年份
                        <select
                          className="report-select"
                          value={rangeYear}
                          data-report-year
                          onChange={(event) =>
                            applyRange(event.target.value, isFullYear ? 'all' : rangeMonth)
                          }
                        >
                          {yearOptions.map((year) => (
                            <option key={year} value={year}>
                              {year} 年
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="report-field">
                        月份
                        <select
                          className="report-select"
                          value={isFullYear ? 'all' : rangeMonth}
                          data-report-month
                          onChange={(event) => applyRange(rangeYear, event.target.value)}
                        >
                          <option value="all">全年</option>
                          {Array.from({ length: 12 }, (_, i) => pad2(i + 1)).map((month) => (
                            <option key={month} value={month}>
                              {Number(month)} 月
                            </option>
                          ))}
                        </select>
                      </label>

                      <div className="report-quick" data-report-quick>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          data-range="this-month"
                          onClick={() => applyQuickRange('this-month')}
                        >
                          本月
                        </button>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          data-range="last-month"
                          onClick={() => applyQuickRange('last-month')}
                        >
                          上月
                        </button>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          data-range="this-year"
                          onClick={() => applyQuickRange('this-year')}
                        >
                          今年
                        </button>
                      </div>

                      {/* 自定义区间：月末结算 / 跨年对比还要用，不删，收进折叠 */}
                      <details className="report-custom-range" data-report-custom-range>
                        <summary>自定义</summary>
                        <label className="report-field">
                          起
                          <input
                            type="date"
                            value={reportQuery.date_from}
                            onChange={handleReportQueryChange('date_from')}
                          />
                        </label>
                        <label className="report-field">
                          止
                          <input
                            type="date"
                            value={reportQuery.date_to}
                            onChange={handleReportQueryChange('date_to')}
                          />
                        </label>
                      </details>
"""
text = sub_once(text, OLD, NEW, "toolbar")

PAGE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK ReportsPage.jsx 年/月下拉 + 快捷时段")
