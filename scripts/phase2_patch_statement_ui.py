# -*- coding: utf-8 -*-
"""第二阶段 P2-2：对账单编辑器改成用户要的「三步走」。

① 选往来单位 + 账期 → ② 点「搜索预览」看到明细、勾选 → ③ 点「生成对账单」→ 出现下载/打印。
改造前只有一个「生成草稿」：点下去就直接落库，用户没机会在落库前挑行。
"""
import shutil
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "statements" / "StatementEditor.jsx"
shutil.copy2(FILE, FILE.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))

text = FILE.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sub_once(source, old, new, label):
    n = source.count(old)
    assert n == 1, f"[{label}] 命中 {n} 次"
    return source.replace(old, new)


# ---------------------------------------------------------------- 1. 新增 state
text = sub_once(
    text,
    """  const [statement, setStatement] = useState(null);
  const [rows, setRows] = useState([]);
""",
    """  const [statement, setStatement] = useState(null);
  const [rows, setRows] = useState([]);
  // 预览态：明细是「搜索预览」取来的、还没落库。此时 statement 为空，
  // 顶部按钮从「保存」换成「生成对账单」—— 这是三步走的分界线。
  const [previewMode, setPreviewMode] = useState(false);
""",
    "state",
)

# --------------------------------------------- 2. 预览 / 生成 / 直接生成 三个动作
OLD_GENERATE_HEAD = """  // ---- 生成草稿 ----
  const generate = async () => {"""
NEW_GENERATE_HEAD = """  // ---- 第二步：搜索预览（只取数，不落库）----
  // 为什么不复用 /generate：那个接口取完数当场建单。用户要的是"先看再挑"，
  // 所以后端单独加了 /statements/preview，两边共用同一个取数函数，口径一致。
  const searchPreview = async () => {
    const invalid = validateGenerate({ partyId, period });
    if (invalid) {
      setError(invalid);
      setNotice('');
      return;
    }
    setBusy('preview');
    setError('');
    setNotice('');
    try {
      const data = await api('/statements/preview', {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          direction,
          party_type: dirConfig.partyType,
          party_id: Number(partyId),
          period_start: period.start,
          period_end: period.end,
        }),
      });
      const nextRows = (data.items || []).map((item, index) => normalizeItem(item, index));
      if (!nextRows.length) {
        setStatement(null);
        setRows([]);
        setSelectedKeys([]);
        setPreviewMode(false);
        setError('该账期内没有找到这家单位的合同 / 发票 / 收付款记录，换个账期或换个往来单位试试。');
        return;
      }
      setStatement(null);
      setPreviewMode(true);
      setRows(nextRows);
      setSelectedKeys(allRowKeys(nextRows));
      setOpening(String(toNumber(data.opening_balance)));
      setNote('');
      setNotice(
        `已预览 ${nextRows.length} 行（共 ${money(
          nextRows.reduce((sum, row) => sum + toNumber(row.contract_amount), 0),
        )}）。勾掉不参与本单的行，再点「生成对账单」。`,
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 第三步：按勾选生成对账单（此刻才落库）----
  const generateFromPreview = async () => {
    if (!checkedRows.length) {
      setError('请至少勾选一行再生成对账单。');
      setNotice('');
      return;
    }
    setBusy('create');
    setError('');
    setNotice('');
    try {
      const payload = buildSavePayload({ period, opening, note }, checkedRows);
      const data = await api('/statements', {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          direction,
          party_type: dirConfig.partyType,
          party_id: Number(partyId),
          party_name: partyName || null,
          note: note || null,
          ...payload,
        }),
      });
      applyStatement(data, {
        noticeText: `对账单 ${data.statement_no} 已生成（${checkedRows.length} 行）。下面可以直接下载或打印。`,
      });
      setPreviewMode(false);
      const fresh = await api('/statements?limit=50');
      setRecent(Array.isArray(fresh) ? fresh : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 保底入口：跳过预览直接生成草稿（老行为，熟手用）----
  const generate = async () => {"""
text = sub_once(text, OLD_GENERATE_HEAD, NEW_GENERATE_HEAD, "generate-head")

# 老 generate 结束后要清掉预览态，否则「生成」完还挂着预览标志
text = sub_once(
    text,
    """      applyStatement(data, {
        noticeText: data.message || `已生成对账单草稿 ${data.statement_no}`,
      });
      const fresh = await api('/statements?limit=50');""",
    """      setPreviewMode(false);
      applyStatement(data, {
        noticeText: data.message || `已生成对账单草稿 ${data.statement_no}`,
      });
      const fresh = await api('/statements?limit=50');""",
    "generate-preview-reset",
)

# applyStatement 是"载入真单据"，一律退出预览态
text = sub_once(
    text,
    """    setStatement(data);
    setScope(data.direction === 'in' ? 'in' : 'out');""",
    """    setStatement(data);
    setPreviewMode(false);
    setScope(data.direction === 'in' ? 'in' : 'out');""",
    "apply-statement",
)

# ------------------------------------------------------------ 3. 顶部按钮换三步
OLD_BTN = """            <button
              type="button"
              className="primary-btn small-btn stmt__generate"
              onClick={generate}
              disabled={busy === 'generate'}
            >
              {busy === 'generate' ? '生成中…' : '生成草稿'}
            </button>
"""
NEW_BTN = """            <button
              type="button"
              className="primary-btn small-btn stmt__generate"
              data-stmt-preview
              onClick={searchPreview}
              disabled={busy === 'preview'}
            >
              {busy === 'preview' ? '搜索中…' : '搜索预览'}
            </button>
            <button
              type="button"
              className="primary-btn small-btn stmt__generate"
              data-stmt-create
              onClick={generateFromPreview}
              disabled={busy === 'create' || !checkedRows.length}
              title={
                checkedRows.length
                  ? `把勾选的 ${checkedRows.length} 行写成一张对账单`
                  : '先点「搜索预览」并勾选要写进对账单的行'
              }
            >
              {busy === 'create'
                ? '生成中…'
                : checkedRows.length
                  ? `生成对账单（${checkedRows.length} 行）`
                  : '生成对账单'}
            </button>
            <button
              type="button"
              className="link-btn stmt__skip"
              onClick={generate}
              disabled={busy === 'generate'}
              title="跳过预览：按这一期的全部记录直接建草稿（老做法）"
            >
              {busy === 'generate' ? '生成中…' : '直接生成草稿'}
            </button>
"""
text = sub_once(text, OLD_BTN, NEW_BTN, "toolbar-buttons")

# ------------------------------------------------- 4. 步骤条 + 生成后的下载区
OLD_META = """          {/* ================= 单头信息 ================= */}
          <div className="stmt__meta">"""
NEW_META = """          {/* ================= 三步走指示条 ================= */}
          <div className="stmt__steps" data-stmt-steps>
            <span className={`stmt__step${partyId && period.start && period.end ? ' is-done' : ' is-active'}`}>
              ① 选往来单位与账期
            </span>
            <span className="stmt__step-arrow">→</span>
            <span
              className={`stmt__step${previewMode ? ' is-active' : statement ? ' is-done' : ''}`}
              data-stmt-step-preview
            >
              ② 搜索预览 · 勾选明细
            </span>
            <span className="stmt__step-arrow">→</span>
            <span className={`stmt__step${statement ? ' is-active' : ''}`} data-stmt-step-done>
              ③ 生成对账单 · 下载 / 打印
            </span>
          </div>

          {/* 生成之后才出现的下载区：用户要的就是"点完生成，按钮冒出来" */}
          {statement ? (
            <div className="stmt__downloads" data-stmt-downloads>
              <span className="stmt__downloads-label">这张单已生成：</span>
              <button type="button" className="primary-btn small-btn" onClick={printPdf} disabled={busy === 'print'}>
                {busy === 'print' ? '生成中…' : '下载 / 打印 PDF'}
              </button>
              <button type="button" className="secondary-btn small-btn" onClick={exportExcel} disabled={busy === 'export'}>
                {busy === 'export' ? '导出中…' : '下载 Excel'}
              </button>
              <button
                type="button"
                className="secondary-btn small-btn"
                data-word-export="statement"
                onClick={exportWordFile}
                disabled={busy === 'word'}
              >
                {busy === 'word' ? '导出中…' : '下载 Word'}
              </button>
            </div>
          ) : null}

          {/* ================= 单头信息 ================= */}
          <div className="stmt__meta">"""
text = sub_once(text, OLD_META, NEW_META, "steps-and-downloads")

# ------------------------------------------------------------ 5. 空态文案对齐
text = sub_once(
    text,
    """                description:
                  '先选好往来单位与对账期间，点「生成草稿」把这一期的合同 / 发票 / 收付款汇总成一张对账单；也可以从右侧「载入已存对账单」继续核对。',""",
    """                description:
                  '先选好往来单位与对账期间，点「搜索预览」把这一期的合同 / 发票 / 收付款拉出来看；勾选要写进对账单的行，再点「生成对账单」。也可以从右侧「载入已存对账单」继续核对。',""",
    "empty-state",
)

text = sub_once(
    text,
    """                '对账单要按「往来单位 + 账期」生成：把上面的范围切到「应收」或「应付」，选好客户/供应商再点「生成草稿」。',""",
    """                '对账单要按「往来单位 + 账期」生成：把上面的范围切到「应收」或「应付」，选好客户/供应商，点「搜索预览」→ 勾选 → 「生成对账单」。',""",
    "empty-state-ledger",
)

FILE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK StatementEditor.jsx 三步走已接")
