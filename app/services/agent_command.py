"""自然语言指令 → 结构化意图 + 数据（2026-10-23）。

## 一条命令要拆成三件事

1. **意图**：要合同还是对账单？（"给我周广平的对账单" / "生成上海汉川机械厂的最新销售合同"）
2. **主体**：说的是哪家单位？可能是全称、简称、联系人或业务员的名字。
3. **数据**：按意图取数 —— 对账单看"未结清单据 + 已生成对账单"，合同看"该单位的合同列表"。

## 为什么先规则、后大模型

* 规则版**零依赖、毫秒级、结果可解释**：`intent.parser = "rules"` + `confidence`，
  用户能看懂"系统是怎么理解这句话的"；
* 大模型要显卡、要联网、还会把"对账单"理解成"对账"再编出一张不存在的单子；
* 但规则版**注定只能覆盖常见句式**，所以留了 `parse_command_via_llm()` 的位置
  （见文件末尾的预留块）：装了显卡后把 `dispatch()` 里的 `parse_command()` 换掉即可，
  后面的数据装配一行都不用改 —— 这也是本模块把"解析"和"取数"分开写的原因。

## 取数口径：绝不算第二套数

* 对账单的金额/欠款**复用 `erp_statement._build_fusion_rows`**（对账单页面的同一个引擎），
  不是在这里再写一遍 `订单金额 - 已收`。两套算法迟早会差一分钱，而对账场景差一分钱就是事故。
* 合同只用 `Contract` 表自己的字段，不做跨表推断。
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.contract import CONTRACT_STATUS, Contract
from app.models.customer import Customer
from app.models.statement import STATEMENT_STATUS, Statement
from app.models.supplier import Supplier
from app.services.pinyin_initials import is_latin_query, pinyin_initials

# 对账单取数的时间窗：从很早开始，保证"历史欠款"不会被漏掉。
# 上界是今天 —— 未来的单据不该出现在"未结清"里。
UNSETTLED_FROM = "2015-01-01"

# ---- 词表 --------------------------------------------------------------
TYPE_WORDS = {
    "statement": (
        "对账单", "对帐单", "对账", "对帐", "结算单", "欠款", "未结清", "应收", "应付",
        # 2026-10-24 放宽：口语里的这些词也认成"查账"意图（"周广平的往来"）
        "账单", "往来", "单据", "结算",
    ),
    "contract": ("合同", "协议", "购销合同", "价目", "报价单"),
}
# 出现在命令里、但不属于"单位名"的词，抽名字时要连同它们一起剥掉
NOISE_WORDS = (
    # ⚠️ 顺序 = 剥离顺序：长词必须在前（"给我" 先于 "给"），否则"给我周广平"会剩个"我"。
    "给我", "帮我", "给我看看", "帮我看", "请帮", "麻烦", "我要", "我想", "想看", "看一下", "看看",
    "查一下", "查查",
    # 单个动词/介词：口语里"给湖南华邦的对账单""和明珠的对账""跟万方的合同"非常常见，
    # 不剥掉就会拼成"给湖南华邦"这种查不到的名字。
    "给", "和", "跟", "关于", "对一下",
    "查询", "查", "找一下", "找找", "找", "搜一下", "搜索", "搜", "打开", "显示", "列出", "列",
    "生成", "做一份", "做", "来一份", "要一份", "导出", "下载", "打印", "预览",
    "最新的", "最新", "最近的", "最近", "全部的", "全部", "所有的", "所有", "当前的",
    "这份", "那份", "相关", "对方的", "往来",
)
# 类型词与修饰词在剥名字时也要去掉（"最新销售合同" → 只剩单位名）
TYPE_SUFFIX_WORDS = (
    "的销售合同", "销售合同", "采购合同", "购销合同", "的合同", "合同",
    "的对账单", "对账单", "对帐单", "的对账", "对账", "对帐",
    "的结算单", "结算单", "的欠款", "欠款", "未结清单据", "未结清",
    "的账单", "账单", "的往来", "往来", "的单据", "单据", "的结算", "结算",
    "的明细", "明细", "的详情", "详情", "的数据", "数据",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def extract_party_query(text: str) -> str:
    """从命令里剥出一个"像单位名"的片段。

    顺序很重要：先剥**后缀型**词（"销售合同"），再剥前缀动词（"给我"），
    否则"给我周广平的对账单"里的"给我"剥掉之后会剩"周广平的对账单"，
    而"的对账单"这一层如果先剥，又会把"对账单"当名字的一部分留着。
    最后再把首尾的"的/了/吧/呢"这类语气词收掉。
    """
    value = _clean(text)
    for word in TYPE_SUFFIX_WORDS:
        value = value.replace(word, " ")
    for word in NOISE_WORDS:
        value = value.replace(word, " ")
    # 标点与语气词
    value = re.sub(r"[，。！？、,.!?~～]+", " ", value)
    value = re.sub(r"(的|了|吧|呢|啊|呀|一下)$", "", value.strip())
    value = re.sub(r"\s+", " ", value).strip()
    # 去掉单独成词的"的"
    value = re.sub(r"(^|\s)的(\s|$)", " ", value)
    return value.strip()


def parse_command(text: str) -> dict[str, object]:
    """规则版意图解析。返回 `{type, action, party_query, confidence, parser, matched_words}`。"""
    raw = _clean(text)
    lowered = raw.lower()

    matched_words: list[str] = []
    # 类型：谁先出现算谁（"给周广平的合同对账单"这种病句，取先说的那个）
    type_hits = []
    for key, words in TYPE_WORDS.items():
        for word in words:
            index = raw.find(word)
            if index >= 0:
                type_hits.append((index, key, word))
    type_hits.sort()
    if type_hits:
        intent_type = type_hits[0][1]
        matched_words = [word for _, _, word in type_hits]
    else:
        intent_type = "unknown"

    # 动作：出现"生成/新建/开/做"算写入意图，其余都是查看
    action = "create" if re.search(r"(生成|新建|开一张|开个|做一?份|创建)", raw) else "list"

    party_query = extract_party_query(raw)

    # 置信度：有类型 + 有名字 = 高；只有名字或只有类型 = 中低
    confidence = 0.4
    if intent_type != "unknown":
        confidence += 0.35
    if party_query:
        confidence += 0.2
    if intent_type != "unknown" and party_query:
        confidence = 0.9
    if intent_type == "unknown":
        confidence = 0.2 if party_query else 0.05

    return {
        "type": intent_type,
        "action": action,
        "party_query": party_query,
        "confidence": round(confidence, 2),
        "parser": "rules",
        "matched_words": matched_words,
        "normalized": lowered,
    }


# ---- 主体识别 ---------------------------------------------------------
def _score(name: str | None, query: str) -> tuple[int, str]:
    """名字与查询的匹配分。返回 (分数, 匹配方式)；0 分表示不匹配。"""
    if not name or not query:
        return 0, ""
    name_l = name.lower()
    query_l = query.lower()
    if name_l == query_l:
        return 100, "exact"
    if query_l in name_l:
        # 查询是名字的一部分：「汉川机械厂」→「上海汉川机械厂有限公司」
        # 越接近整名分越高，避免"西安"这种短片段把一堆客户都匹配上
        return 60 + int(30 * len(query_l) / max(len(name_l), 1)), "contains"
    if name_l in query_l:
        # 名字是查询的一部分：用户多打了"有限公司"或后缀
        return 55, "partial"
    # 拼音首字母（2026-10-23）：zgp → 周广平。
    # 只在关键词纯拉丁时才走拼音通道；整串首字母相等分高于"包含"，
    # 但都低于字面匹配 —— 同名冲突时字面赢，符合直觉。
    if is_latin_query(query_l):
        initials = pinyin_initials(name)
        if initials:
            if initials == query_l:
                return 92, "pinyin-exact"
            if query_l in initials:
                return 65, "pinyin-contains"
    return 0, ""


def resolve_parties(db: Session, query: str, limit: int = 5) -> list[dict[str, object]]:
    """按名字找往来单位（客户 + 供应商）。

    除了 `name`，还看 `short_name`（供应商简称）与 `contact` / `businesser`
    —— 用户常说"给我周广平的对账单"，周广平是联系人不是公司名。
    """
    query = _clean(query)
    if not query:
        return []

    # 拼音首字母通道（2026-10-23）：zgp → 周广平。纯拉丁关键词才启用
    latin = is_latin_query(query)
    query_l = query.lower()

    rows: list[dict[str, object]] = []
    for model, party_type in ((Customer, "customer"), (Supplier, "supplier")):
        candidates = (
            db.query(model)
            .filter(
                or_(
                    model.name.ilike(f"%{query}%"),
                    # 反向：用户打了全称，库里是简称
                    model.code.ilike(f"%{query}%"),
                )
            )
            .limit(40)
            .all()
        )
        # 名字反向包含（库里名字是查询的子串）没法用 SQL 表达，内存里补一遍；
        # 拼音首字母同理（zgp 撞不上任何 SQL LIKE），也在这里补
        if len(candidates) < 5:
            more = db.query(model).limit(400).all()
            known = {row.id for row in candidates}
            for row in more:
                if row.id in known:
                    continue
                row_name = row.name or ""
                if query_l in row_name.lower() or (
                    latin and query_l in pinyin_initials(row_name)
                ):
                    candidates.append(row)

        # 联系人 / 业务员 / 简称 / 电话：只在前面没找到时兜底，且分数低。
        # 「给我周广平的对账单」里周广平是联系人不是公司名 —— 走的就是这一支。
        contact_hits: list[tuple[object, str]] = []
        if len(candidates) < 3:
            for row in db.query(model).limit(400).all():
                fields = [
                    getattr(row, "contact", None),
                    getattr(row, "businesser", None),
                    getattr(row, "short_name", None),
                    getattr(row, "mobile", None),
                    getattr(row, "phone", None),
                ]
                hit_by = ""
                for field in fields:
                    if not field:
                        continue
                    text = str(field)
                    if query_l in text.lower():
                        hit_by = "contact"
                        break
                    if latin and query_l in pinyin_initials(text):
                        hit_by = "contact-pinyin"
                        break
                if hit_by:
                    contact_hits.append((row, hit_by))
                if len(contact_hits) >= 8:
                    break

        for row in candidates:
            score, how = _score(getattr(row, "name", ""), query)
            short_score, short_how = _score(getattr(row, "short_name", None), query)
            if short_score > score:
                score, how = short_score - 10, f"short_name:{short_how}"
            if score <= 0:
                continue
            rows.append(
                {
                    "id": row.id,
                    "type": party_type,
                    "name": row.name,
                    "code": getattr(row, "code", ""),
                    "tax_no": getattr(row, "tax_no", None),
                    "contact": getattr(row, "contact", None),
                    "phone": getattr(row, "phone", None),
                    "_score": score,
                    "matched_by": how,
                }
            )

        for row, hit_by in contact_hits:
            rows.append(
                {
                    "id": row.id,
                    "type": party_type,
                    "name": row.name,
                    "code": getattr(row, "code", ""),
                    "tax_no": getattr(row, "tax_no", None),
                    "contact": getattr(row, "contact", None),
                    "phone": getattr(row, "phone", None),
                    "_score": 40,
                    "matched_by": hit_by,
                }
            )

    # 去重（同一单位可能既按名字命中又按联系人命中），保留高分
    best: dict[tuple[str, int], dict[str, object]] = {}
    for row in rows:
        key = (str(row["type"]), int(row["id"]))
        if key not in best or int(row["_score"]) > int(best[key]["_score"]):
            best[key] = row

    ordered = sorted(best.values(), key=lambda item: (-int(item["_score"]), str(item["name"])))
    return ordered[:limit]


def suggest_parties(db: Session, text: str, limit: int = 6) -> list[dict[str, object]]:
    """输入即提示（2026-10-24）：从半截话里认人，供搜索框实时下拉。

    与 `dispatch` 的区别：**不求结果、只求快**——
      · 不解析意图（用户还没说完，猜意图没意义）；
      · 复用同一套 `extract_party_query`（剥掉"给我/的"这些残渣）+
        `resolve_parties`（字面 / 拼音首字母 zgp→周广平 / 联系人兜底）；
      · 每次按键都会来，必须轻：只认人、不取数，最多 `limit` 条。

    2026-10-24 补盲区：**分类节点也在搜索范围**。
    实测"周广平"这类名字常以「客户分类/供应商分类」节点存在（如 public 库的
    customer_categories「周广平总」、supplier_categories「周广平项目」），
    档案表里反而没有 —— 只搜 customers/suppliers 会漏。分类表很小，
    直接全量拉出来做「字面 + 拼音首字母」双通道过滤，追加在档案命中之后。
    """
    query = extract_party_query(_clean(text))
    if not query:
        return []

    out: list[dict[str, object]] = [
        {
            "type": row["type"],
            "id": row["id"],
            "name": row["name"],
            "code": row.get("code", ""),
            "contact": row.get("contact"),
            "matched_by": row.get("matched_by", ""),
        }
        for row in resolve_parties(db, query, limit=limit)
    ]

    # 分类节点（档案没搜满才补 —— 档案是"能直接查账的"，优先级更高）
    if len(out) < limit:
        from app.models.partner_category import CustomerCategory, SupplierCategory

        query_l = query.lower()
        for model, type_key in (
            (CustomerCategory, "customer-category"),
            (SupplierCategory, "supplier-category"),
        ):
            if len(out) >= limit:
                break
            try:
                rows = db.query(model).all()
            except Exception:  # noqa: BLE001 —— 老库缺表时绝不能让搜索框报错
                continue
            for row in rows:
                if len(out) >= limit:
                    break
                name = str(row.name or "").strip()
                if not name:
                    continue
                hit = query_l in name.lower() or (
                    is_latin_query(query_l) and query_l in pinyin_initials(name)
                )
                if not hit:
                    continue
                out.append(
                    {
                        "type": type_key,
                        "id": row.id,
                        "name": name,
                        "code": "",
                        "contact": None,
                        "matched_by": "category",
                    }
                )
    return out


# ---- 取数 -------------------------------------------------------------
def _pending_documents(db: Session, party: dict[str, object]) -> tuple[list[dict], dict]:
    """未结清单据（欠款 > 0）。**复用对账单页面的聚合引擎**，不自己算钱。"""
    from app.api.v1.routes.erp_statement import _build_fusion_rows

    data = _build_fusion_rows(
        db,
        party_type=str(party["type"]),
        party_id=int(party["id"]),
        party_name=str(party["name"]),
        period_start=UNSETTLED_FROM,
        period_end=date.today().isoformat(),
    )
    documents: list[dict] = []
    total_remaining = 0.0
    total_amount = 0.0
    for row in data.get("rows") or []:
        if row.get("row_kind") != "summary" or not row.get("source_id"):
            continue
        remaining = float(row.get("remaining_debt") or 0)
        amount = float(row.get("amount") or 0)
        invoiced = float(row.get("invoiced_amount") or 0)
        paid = float(row.get("paid_amount") or 0)
        total_amount += amount
        if remaining <= 0.005:
            continue
        total_remaining += remaining
        documents.append(
            {
                "kind": "document",
                "id": row.get("source_id"),
                "no": row.get("source_no") or "",
                "date": row.get("business_date") or "",
                "amount": round(amount, 2),
                "invoiced_amount": round(invoiced, 2),
                "paid_amount": round(paid, 2),
                "remaining": round(remaining, 2),
                "uninvoiced": round(max(0.0, amount - invoiced), 2),
                "status": "unsettled",
                "status_label": "未结清",
                "party_type": party["type"],
                "party_id": party["id"],
                "party_name": party["name"],
            }
        )
    documents.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("no") or "")), reverse=True)
    summary = {
        "document_count": len(documents),
        "outstanding_total": round(total_remaining, 2),
        "business_total": round(total_amount, 2),
    }
    return documents, summary


def _statement_cards(db: Session, party: dict[str, object], limit: int = 8) -> list[dict]:
    rows = (
        db.query(Statement)
        .filter(Statement.party_type == party["type"], Statement.party_id == party["id"])
        .order_by(Statement.id.desc())
        .limit(limit)
        .all()
    )
    cards: list[dict] = []
    for row in rows:
        period_start = getattr(row, "period_start", None) or ""
        period_end = getattr(row, "period_end", None) or ""
        cards.append(
            {
                "kind": "statement",
                "id": row.id,
                "no": row.statement_no,
                "period": f"{period_start} ~ {period_end}".strip(" ~"),
                # 对账单的金额字段叫 contract_amount（合同额合计），不是 total_amount
                "amount": float(getattr(row, "contract_amount", 0) or 0),
                "received": float(getattr(row, "received_amount", 0) or 0),
                "outstanding": float(getattr(row, "outstanding_amount", 0) or 0),
                "status": row.status,
                "status_label": STATEMENT_STATUS.get(row.status, row.status),
                "created_at": row.created_at.strftime("%Y-%m-%d") if getattr(row, "created_at", None) else "",
                "party_type": party["type"],
                "party_id": party["id"],
                "party_name": row.party_name or party["name"],
            }
        )
    return cards


def _auto_generate_statement(
    db: Session, party: dict[str, object], documents: list[dict]
) -> dict[str, object] | None:
    """一张对账单都没有、但有未结清单据时，**静默生成一张真草稿**。

    复用 `/statements/generate-selected` 的既有落库路径（**每张单据一行**，
    与对账单编辑页"勾选生成"完全同口径：net = 应收 − 折扣、票额/实收实时查），
    不在搜索框里再造第二套生成逻辑 —— 生成的草稿和对账单页面手工生成的
    是同一种东西，预览 / PDF / 确认全部走现成管道。

    keys 就是这批未结清单据的 source_id（融合引擎的 summary 行只可能是
    结算单据：销售侧 outbound / 采购侧 inbound）；区间取这批单据的
    最早 ~ 最晚业务日期（兜底今天），保证生成的就是这批欠款对应的账期。

    生成失败（单据被并发删除等）返回 None，dispatch 退回原有卡片，
    绝不让自动生成这件事把查询本身搞挂。
    """
    from fastapi import HTTPException

    from app.api.v1.routes.erp_statement import generate_selected

    today = date.today().isoformat()
    dates = sorted(str(item.get("date") or "") for item in documents if item.get("date"))
    if not dates:
        return None
    period_start = min(dates[0], today)
    period_end = max(dates[-1], today)
    keys = [f"order:{int(item['id'])}" for item in documents if item.get("id")]
    if not keys:
        return None
    payload = {
        "party_type": str(party["type"]),
        "direction": "in" if party["type"] == "supplier" else "out",
        "party_id": int(party["id"]),
        "period_start": period_start,
        "period_end": period_end,
        "keys": keys,
        "note": "智能指令自动生成草稿",
    }
    try:
        data = generate_selected(payload, db)
    except HTTPException:
        db.rollback()
        return None
    except Exception:
        db.rollback()
        return None
    if not data or not data.get("id"):
        return None
    return {
        "id": data.get("id"),
        "statement_no": data.get("statement_no") or "",
        "line_count": int(data.get("generated_lines") or 0),
        "amount": float(data.get("contract_amount") or 0),
        "outstanding": float(data.get("outstanding_amount") or 0),
        "period": f"{period_start} ~ {period_end}".strip(" ~"),
    }


def _contract_cards(db: Session, party: dict[str, object], limit: int = 8) -> list[dict]:
    rows = (
        db.query(Contract)
        .filter(Contract.party_type == party["type"], Contract.party_id == party["id"])
        .order_by(Contract.id.desc())
        .limit(limit)
        .all()
    )
    cards: list[dict] = []
    for row in rows:
        cards.append(
            {
                "kind": "contract",
                "id": row.id,
                "no": row.contract_no,
                "title": row.title or "购销合同",
                "sign_date": row.sign_date or "",
                "amount": float(row.total_amount or 0),
                "status": row.status,
                "status_label": CONTRACT_STATUS.get(row.status, row.status),
                "direction": row.direction,
                "party_type": row.party_type or party["type"],
                "party_id": row.party_id,
                "party_name": row.party_name or party["name"],
                "order_no": row.order_no,
            }
        )
    return cards


def _goto_link(intent_type: str, party: dict[str, object] | None) -> dict[str, object]:
    """前端"去修改/去确认"要跳哪儿、带什么参数。参数形状与页面自身状态对齐。"""
    if not party:
        return {}
    if intent_type == "statement":
        scope = "in" if party["type"] == "supplier" else "out"
        return {
            "page": "statements-editor",
            "scope": scope,
            "party": f"{'s' if party['type'] == 'supplier' else 'c'}:{party['id']}",
            "party_id": party["id"],
            "party_type": party["type"],
            "party_name": party["name"],
        }
    if intent_type == "contract":
        return {
            "page": "contracts",
            "keyword": party["name"],
            "party_id": party["id"],
            "party_type": party["type"],
            "party_name": party["name"],
        }
    return {}


def dispatch(db: Session, text: str) -> dict[str, object]:
    """一条命令的完整处理：解析 → 认人 → 取数 → 组织成前端能直接渲染的结构。"""
    intent = parse_command(text)
    party_query = str(intent["party_query"] or "")
    candidates = resolve_parties(db, party_query) if party_query else []
    party = candidates[0] if candidates else None

    # 一句里塞了两个名字（"湖南华邦 周广平"）时整串匹配不上，拆词再试一次：
    # 用户很可能是"公司 + 联系人"一起打的，按长度从长到短试，命中谁算谁。
    if party is None and " " in party_query:
        for token in sorted(party_query.split(), key=len, reverse=True):
            if len(token) < 2:
                continue
            retry = resolve_parties(db, token)
            if retry:
                candidates, party = retry, retry[0]
                break

    # 名字没认出来时，给几个"可能是你要找的"候选（取查询的前两个字去模糊搜）
    suggestions: list[dict[str, object]] = []
    if not party and party_query:
        stem = party_query[:2] if len(party_query) >= 2 else party_query
        suggestions = resolve_parties(db, stem)

    # 宽松兜底（2026-10-24）：只要人认到了，就别拿"没听懂"打发用户。
    # 用户只打名字/拼音（"周广平"、"zgp"）没带"对账单/合同"时，默认按对账单查
    # —— 对账单是这口搜索框最高频的意图，查错了换一个词比看一句报错快得多。
    if intent["type"] == "unknown" and party is not None:
        intent = {**intent, "type": "statement", "fallback": True}

    base = {
        "query": _clean(text),
        "intent": intent,
        "party": party,
        "candidates": [item for item in (candidates[1:] or suggestions)][:5],
        "goto": _goto_link(str(intent["type"]), party),
        "matched_data": [],
        "summary": {},
    }

    if intent["type"] == "unknown":
        base["message"] = "没听懂要查什么 —— 试试「给我XX的对账单」或「XX的合同」。"
        base["type"] = "unknown"
        return base

    if party is None:
        base["type"] = intent["type"]
        base["message"] = (
            f"没找到「{party_query}」这个往来单位，换个写法试试（全称/简称/联系人都行）。"
            if party_query
            else "没说清是哪家单位 —— 把单位名称一起打上，例如「给西安明珠的对账单」。"
        )
        return base

    if intent["type"] == "statement":
        documents, doc_summary = _pending_documents(db, party)
        statements = _statement_cards(db, party)
        # 自动生成闭环（2026-10-25）：一张对账单都没有、但名下有未结清单据时，
        # 静默生成一张真草稿 —— 让「给我XX的对账单」直接出一张可预览、
        # 可确认的卡片，而不是一句"暂无对账单"把人踢回左侧列表。
        # 第二次再查时草稿已经在库里，`statements` 非空，不会重复占号。
        # 门槛：只认**显式**对账单意图。只打名字的宽松兜底（fallback）绝不触发生成
        # —— 用户只是想看看，不能悄悄给人家落一张单。
        generated = None
        if not statements and documents and not intent.get("fallback"):
            generated = _auto_generate_statement(db, party, documents)
            if generated:
                statements = _statement_cards(db, party)
        base["type"] = "statement"
        base["matched_data"] = statements + documents
        base["summary"] = {
            **doc_summary,
            "statement_count": len(statements),
        }
        # 空结果要说人话（2026-10-24）：不再让"没锁定具体单位"背锅 ——
        # 人认到了就是没单据，前端拿 `empty` 渲染黄字提示。
        base["empty"] = not statements and not documents
        if generated:
            base["generated"] = generated
            base["message"] = (
                f"已为您生成对账单草稿 {generated['statement_no']}，"
                f"包含 {generated['line_count']} 行明细，"
                f"总金额 ¥{generated['amount']:,.2f}"
            )
        elif base["empty"]:
            base["message"] = f"「{party['name']}」名下暂无对账单，也没有未结清单据。"
        else:
            parts = []
            if statements:
                parts.append(f"{len(statements)} 张已生成的对账单")
            if documents:
                parts.append(f"{doc_summary['document_count']} 张未结清单据（欠款 ¥{doc_summary['outstanding_total']:,.2f}）")
            base["message"] = (
                f"「{party['name']}」" + ("，".join(parts) if parts else "暂时没有未结清单据，也没生成过对账单")
            )
        return base

    contracts = _contract_cards(db, party)
    base["type"] = "contract"
    base["matched_data"] = contracts
    base["summary"] = {
        "contract_count": len(contracts),
        "amount_total": round(sum(float(item["amount"]) for item in contracts), 2),
    }
    base["empty"] = not contracts
    base["message"] = (
        f"「{party['name']}」有 {len(contracts)} 份合同"
        if contracts
        else f"「{party['name']}」名下暂无合同"
    )
    return base


# ---------------------------------------------------------------------------
# 预留：接本地大模型（Ollama）时只替换 `parse_command`
# ---------------------------------------------------------------------------
# 装了显卡 / 起了 Ollama 之后，把 `dispatch()` 里的
#     intent = parse_command(text)
# 换成
#     intent = parse_command_via_llm(text)
# 即可 —— 后面的认人、取数、goto 全都不用改，因为约定好的返回结构没变
# （type / action / party_query / confidence / parser）。
#
# 建议的提示词（让模型**只输出 JSON**，别让它自由发挥）：
#   你是 ERP 的指令解析器。把用户的话解析成 JSON：
#   {"type": "contract|statement|unknown", "action": "list|create", "party_query": "单位名原文"}
#   用户输入：<text>
#
# def parse_command_via_llm(text: str) -> dict[str, object]:
#     """把意图解析交给本地大模型（Ollama）。失败**必须**回落到规则版。"""
#     import json
#
#     import httpx
#
#     try:
#         response = httpx.post(
#             "http://127.0.0.1:11434/api/generate",
#             json={
#                 "model": "qwen2.5:7b-instruct",
#                 "prompt": _LLM_PROMPT.format(text=text),
#                 "stream": False,
#                 "format": "json",          # Ollama 的结构化输出开关
#                 "options": {"temperature": 0},
#             },
#             timeout=20,
#         )
#         data = json.loads(response.json().get("response") or "{}")
#         if data.get("type") in ("contract", "statement"):
#             rules = parse_command(text)
#             return {
#                 "type": data["type"],
#                 "action": data.get("action") or "list",
#                 # 单位名优先用规则版剥出来的（模型常把"的合同"也带上）
#                 "party_query": data.get("party_query") or rules["party_query"],
#                 "confidence": float(data.get("confidence") or 0.85),
#                 "parser": "ollama",
#                 "matched_words": rules["matched_words"],
#                 "normalized": rules["normalized"],
#             }
#     except Exception:  # noqa: BLE001 —— 模型没起/超时，绝不能因此让搜索框报错
#         pass
#     return parse_command(text)
