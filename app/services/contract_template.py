"""《工矿产品购销合同》正文生成器（2026-10-22）。

## 为什么单独一个模块

合同正文是**法律文件**，条款顺序、措辞、缺省值都不能散落在路由里 ——
散在路由里的后果是"预览一套、导出一套、存库第三套"，客户拿到的纸质件跟系统里看的不一样。
这里只做一件事：把**一份数据**渲染成**一份文档结构**（纯函数，不碰数据库），
预览接口、PDF 导出、以后可能的 Word 导出都吃同一个产物。

## 设计取舍

1. **变量全部从现有合同字段取**（`quality_standard` / `delivery_place` / `penalty_rate` …），
   一个字段都不新增 —— 这些"条款变量"当初就是为模板留的。
2. **缺省值写死在 `DEFAULTS` 里，并且能在界面上改**：财务合同不能出现
   "这里空着，请自行理解"。没填就用行业常规表述，打印出来是完整句子。
3. 金额同时给**小写与大写**：合同上的大小写不一致是最常见的扯皮点。
4. 条款编号用中文「第一条…第八条」，与用户给的标准范本一致。

## 八条正文（用户指定顺序）

    第一条 产品信息      第二条 质量要求      第三条 包装标准      第四条 交货方式
    第五条 验收标准      第六条 结算方式      第七条 违约责任      第八条 争议解决
    + 落款（甲乙双方签字盖章 / 法定代表人 / 开户行 / 账号 / 日期）
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.company_info import load_company
from app.api.v1.routes.erp_common import amount_to_chinese

# 缺省条款值。界面上每一格都能覆盖，这里只保证"空着也有正经话"。
DEFAULTS: dict[str, Any] = {
    "quality_standard": "国家标准；无国家标准的，按行业标准执行；二者均无的，按双方确认的技术协议或封样样品执行",
    "package_standard": "按行业标准包装，包装物不回收；因包装不当造成的货损由供货方承担",
    "delivery_method": "供货方送货至购货方指定地点",
    "freight_bearer": "运费由供货方承担（含卸货）",
    "inspection_days": 7,
    "objection_days": 7,
    "payment_terms": "货到验收合格后 30 日内付清全款",
    "invoice_requirement": "供货方开具与合同金额一致的增值税专用发票",
    "penalty_rate": 0.0005,  # 按日万分之五
    "dispute_resolution": "向合同签订地人民法院提起诉讼",
    "copies": 2,
}

# ===========================================================================
# 模板变体（2026-10-23）
# ---------------------------------------------------------------------------
# simple = 用户提供的《产品买卖合同（简易版）》（条款极简，20% 违约金，款到发货）
# detail = 原《工矿产品购销合同》详细版（九条，日万分之五违约金）
# 默认 simple：用户明确要求"把默认模板换成这个简易版"。
# ===========================================================================
TEMPLATE_SIMPLE = "simple"
TEMPLATE_DETAIL = "detail"

TEMPLATE_NAMES = {
    TEMPLATE_SIMPLE: "产品买卖合同（简易版）",
    TEMPLATE_DETAIL: "工矿产品购销合同",
}

# 简易版的条款标题（对应源文档"一、…八、"）
SIMPLE_CLAUSE_TITLES = [
    ("一、", "合同标的"),
    ("二、", "包装标准"),
    ("三、", "产品质量"),
    ("四、", "交（提）货时间、地点"),
    ("五、", "结算方式"),
    ("六、", "违约责任"),
    ("七、", "争议解决"),
    ("八、", "合同份数与生效"),
]

# 简易版缺省值：与源文档措辞一致（款到发货、20% 违约金、施工所在地法院）
SIMPLE_DEFAULTS = {
    "package_standard": "简单包装",
    "quality_standard": "按照双方确认的产品样式及图纸（见附件）执行",
    "delivery_method": "由供货方送至购货方指定交货地点",
    "freight_bearer": "报价含运输、卸车费用",
    "payment_terms": "款到发货（凭供货方提供的产品销售发票的扫描件一次付清）",
    "invoice_requirement": "普通销售发票",
    "delivery_days": 7,
    "penalty_ratio": 20,  # 违约金按合同金额的百分比
    "dispute_resolution": "向施工所在地人民法院提起诉讼",
    "copies": 4,
}

CLAUSE_TITLES = [
    ("第一条", "产品信息"),
    ("第二条", "质量要求"),
    ("第三条", "包装标准"),
    ("第四条", "交货方式"),
    ("第五条", "验收标准"),
    ("第六条", "结算方式"),
    ("第七条", "违约责任"),
    ("第八条", "争议解决"),
]


def _s(value: Any) -> str:
    return str(value or "").strip()


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001 —— 合同金额宁可按 0 显示，也不能让整份正文生成失败
        return Decimal("0.00")


def _num(value: Any, fallback):
    """取数字型条款变量：空/非法就退回缺省值。"""
    if value in (None, ""):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _parties(payload: dict) -> tuple[dict[str, str], dict[str, str]]:
    """甲乙双方信息。方向 in（采购）时甲乙互换 —— 合同抬头必须与真实买卖关系一致。"""
    direction = _s(payload.get("direction") or "out").lower()
    company = load_company()

    party = {
        "name": _s(payload.get("party_name")),
        "tax_no": _s(payload.get("party_tax_no")),
        "address": _s(payload.get("party_address")),
        "legal": _s(payload.get("party_legal_person")),
        "contact": _s(payload.get("party_contact")),
        "phone": _s(payload.get("party_phone")),
        "bank_name": _s(payload.get("party_bank_name")),
        "bank_account": _s(payload.get("party_bank_account")),
    }
    own = {
        "name": _s(payload.get("own_name")) or _s(company.get("own_name")),
        "tax_no": _s(payload.get("own_tax_no")) or _s(company.get("own_tax_no")),
        "address": _s(payload.get("own_address")) or _s(company.get("own_address")),
        "legal": _s(payload.get("own_legal_person")) or _s(company.get("own_legal_person")),
        "contact": _s(payload.get("own_contact")) or _s(company.get("own_contact")),
        "phone": _s(payload.get("own_phone")) or _s(company.get("own_phone")),
        "bank_name": _s(payload.get("own_bank_name")) or _s(company.get("own_bank_name")),
        "bank_account": _s(payload.get("own_bank_account")) or _s(company.get("own_bank_account")),
    }
    # out（销项）：甲方=客户（购货方）、乙方=我方（供货方）；in（采购）反之
    if direction == "in":
        return own, party
    return party, own


def _simple_clauses(
    payload: dict,
    *,
    items: list[dict],
    total: Decimal,
    chinese: str,
    buyer: dict[str, str],
    seller: dict[str, str],
) -> list[dict[str, Any]]:
    """《产品买卖合同（简易版）》的八条正文 —— 措辞严格对齐用户提供的范本。

    与详细版的差异（不是"少写几条"，而是口径变了）：
      · 违约：**固定 20% 合同金额**，不再按日万分之几累计；
      · 结算：**款到发货**（详细版是"验收后 30 日内"）；
      · 争议：**施工所在地**法院（详细版是签订地）；
      · 份数：一式肆份（详细版 2 份）。
    """
    def pick(field: str) -> str:
        value = _s(payload.get(field))
        return value or str(SIMPLE_DEFAULTS[field])

    delivery_days = _num(payload.get("delivery_days"), SIMPLE_DEFAULTS["delivery_days"])
    penalty_ratio = _num(payload.get("penalty_ratio"), SIMPLE_DEFAULTS["penalty_ratio"])
    copies = int(_num(payload.get("copies"), SIMPLE_DEFAULTS["copies"]))
    tax_note = "含税价" if payload.get("is_tax_included", True) else "不含税价"
    tax_rate = payload.get("tax_rate")
    tax_text = f"，增值税税率 {float(tax_rate):g}%" if tax_rate not in (None, "") else ""
    delivery_date = _s(payload.get("delivery_date")) or f"收到全额货款后 {int(delivery_days)} 天内"
    delivery_place = _s(payload.get("delivery_place")) or "购货方指定交货地点"
    buyer_contact = " ".join(
        part for part in (_s(buyer.get("contact")), _s(buyer.get("phone"))) if part
    ) or "—"
    seller_contact = " ".join(
        part for part in (_s(seller.get("contact")), _s(seller.get("phone"))) if part
    ) or "—"

    bodies: list[list[str]] = [
        # 一、合同标的
        [
            "1. 编号、产品名称、规格、单位、数量、单价、金额等，以下表所列为准：",
            f"2. 合同合计金额（人民币大写）：{chinese}（¥{total:,.2f}），为{tax_note}{tax_text}。",
            "说明：以上报价含运输、卸车及普通销售发票等费用。",
        ],
        # 二、包装标准
        [f"包装标准：{pick('package_standard')}。"],
        # 三、产品质量
        [
            f"产品质量：{pick('quality_standard')}。",
            "供货方应随货提供产品合格证、质量保证书等质量证明文件。",
        ],
        # 四、交（提）货时间、地点
        [
            f"1. 交货期限：{delivery_date}。",
            f"2. 交货地点：{delivery_place}。",
            f"3. 交（提）货双方联系人：甲方 {buyer_contact}；乙方 {seller_contact}。",
            f"4. 运输与费用：{pick('freight_bearer')}。",
        ],
        # 五、结算方式
        [
            f"结算方式：{pick('payment_terms')}。",
            f"发票要求：{pick('invoice_requirement')}。",
            "结算币种为人民币，付款以银行转账方式支付至供货方在本合同落款处载明的账户。",
        ],
        # 六、违约责任
        [
            f"任何一方未按照合同约定付款、交货的，违约方需向守约方支付合同金额 "
            f"{float(penalty_ratio):g}% 的违约金。",
            "违约金不足以弥补守约方实际损失的，违约方还应赔偿差额部分。",
        ],
        # 七、争议解决
        [
            "若双方因合同产生争议，先协商解决；协商不成时，"
            f"{pick('dispute_resolution')}。",
        ],
        # 八、合同份数与生效
        [
            f"本合同一式{copies}份，双方各执{copies // 2}份，双方代表签字、盖章后生效。",
            "本合同未尽事宜，由双方另行签订书面补充协议，与本合同具有同等效力。",
        ],
    ]

    return [
        {"no": no, "heading": heading, "paragraphs": bodies[index]}
        for index, (no, heading) in enumerate(SIMPLE_CLAUSE_TITLES)
    ]


def _clauses(
    payload: dict,
    *,
    items: list[dict],
    total: Decimal,
    chinese: str,
    buyer: dict[str, str],
    seller: dict[str, str],
) -> list[dict[str, Any]]:
    def pick(field: str) -> str:
        return _s(payload.get(field)) or str(DEFAULTS[field])

    inspection_days = int(_num(payload.get("inspection_days"), DEFAULTS["inspection_days"]))
    objection_days = int(_num(payload.get("objection_days"), DEFAULTS["objection_days"]))
    copies = int(_num(payload.get("copies"), DEFAULTS["copies"]))
    rate = _num(payload.get("penalty_rate"), DEFAULTS["penalty_rate"])
    # 违约金按"日万分之几"表述，0.0005 → 万分之五
    penalty_desc = f"万分之{round(float(rate) * 10000)}" if rate else "万分之五"
    tax_note = "含税价" if payload.get("is_tax_included", True) else "不含税价"
    tax_rate = payload.get("tax_rate")
    tax_text = f"，增值税税率 {float(tax_rate):g}%" if tax_rate not in (None, "") else ""

    delivery_date = _s(payload.get("delivery_date")) or "双方另行约定"
    delivery_place = _s(payload.get("delivery_place")) or "购货方指定地点"
    sign_place = _s(payload.get("sign_place")) or "供货方所在地"

    bodies: list[list[str]] = [
        # 第一条 产品信息
        [
            "1.1 产品的名称、规格型号、单位、数量、单价及金额，均以本合同所附明细表为准；"
            "明细表与本合同正文具有同等法律效力。",
            f"1.2 本合同总价为人民币（大写）{chinese}（¥{total:,.2f}），为{tax_note}{tax_text}。"
            "总价已包含货物价款、包装费及约定的运输费用，除双方书面确认的变更外不作调整。",
            f"1.3 本合同共 {len(items)} 项标的物。数量以购货方实际验收合格的到货数量为准结算。",
        ],
        # 第二条 质量要求
        [
            f"2.1 产品质量要求：{pick('quality_standard')}。",
            "2.2 供货方应随货提供产品合格证、质量保证书、装箱单等质量证明文件；"
            "属于实行生产许可或强制性认证的产品，还应提供相应证书复印件。",
            "2.3 质量保证期内出现质量问题的，供货方应在接到通知后 3 日内响应，"
            "并按购货方要求予以更换、修复或退货，相关费用由供货方承担。",
        ],
        # 第三条 包装标准
        [
            f"3.1 包装标准：{pick('package_standard')}。",
            "3.2 每件包装应标明产品名称、规格型号、数量及收货单位；"
            "因标识不清导致错发、错收的，由供货方承担相应责任。",
        ],
        # 第四条 交货方式
        [
            f"4.1 交货时间：{delivery_date}。",
            f"4.2 交货地点：{delivery_place}。",
            f"4.3 交货方式：{pick('delivery_method')}；{pick('freight_bearer')}。",
            "4.4 货物毁损、灭失的风险自购货方签收之时起转移；签收前的一切风险由供货方承担。",
        ],
        # 第五条 验收标准
        [
            f"5.1 购货方应在收到货物后 {inspection_days} 个工作日内完成验收，"
            "验收标准按本合同第二条执行。",
            f"5.2 对数量、外观、包装等表面瑕疵有异议的，应于收货后 3 日内书面提出；"
            f"对内在质量有异议的，应于收货后 {objection_days} 个工作日内书面提出。",
            "5.3 购货方在上述期限内未提出书面异议的，视为验收合格，但不免除供货方对"
            "隐蔽瑕疵应承担的质量责任。",
        ],
        # 第六条 结算方式
        [
            f"6.1 付款条件：{pick('payment_terms')}。",
            f"6.2 发票要求：{pick('invoice_requirement')}。",
            f"6.3 结算币种为人民币。付款以银行转账方式支付至供货方在本合同落款处载明的账户，"
            "账户变更须以加盖公章的书面通知为准。",
        ],
        # 第七条 违约责任
        [
            f"7.1 供货方逾期交货的，每逾期一日按逾期交付货物金额的{penalty_desc}向购货方支付违约金；"
            "逾期超过 15 日的，购货方有权解除合同并要求赔偿损失。",
            f"7.2 购货方逾期付款的，每逾期一日按逾期付款金额的{penalty_desc}向供货方支付违约金。",
            "7.3 供货方交付的产品不符合本合同约定质量标准的，应负责更换或退货，"
            "并承担由此给购货方造成的直接损失。",
        ],
        # 第八条 争议解决
        [
            f"8.1 因本合同引起的或与本合同有关的任何争议，双方应友好协商解决；"
            f"协商不成的，{pick('dispute_resolution')}。",
            "8.2 争议解决期间，不影响本合同其他条款的继续履行。",
        ],
    ]

    return [
        {"no": no, "heading": heading, "paragraphs": bodies[index]}
        for index, (no, heading) in enumerate(CLAUSE_TITLES)
    ] + [
        {
            "no": "第九条",
            "heading": "其他约定",
            "paragraphs": [
                f"9.1 本合同自双方签字并盖章之日起生效，一式 {copies} 份，甲乙双方各执 "
                f"{max(1, copies // 2)} 份，具有同等法律效力。",
                "9.2 本合同未尽事宜，由双方另行签订书面补充协议，补充协议与本合同具有同等效力。",
                "9.3 双方以本合同落款处载明的地址、电话作为有效送达地址；变更须书面通知对方。",
            ],
        }
    ]


def build_gongkuang_document(
    payload: dict,
    items: list[dict] | None = None,
    template: str | None = None,
) -> dict[str, Any]:
    """把一份合同数据渲染成合同文档结构（纯函数，不写库）。

    `payload` 即 `ContractCreate` 的字段集合；`items` 为明细行
    （product_name / standards / unit / quantity / unit_price / amount）。

    `template`：`simple`（默认，《产品买卖合同（简易版）》）或 `detail`（工矿详细版）。
    不传时再看 `payload["template"]` —— 这样 HTTP 接口不用额外长参数，
    前端把 `{"template": "detail"}` 塞进 body 就能切变体。
    两个变体输出**同一套结构**（title / parties / items / clauses / signatures），
    所以预览、PDF、Word 变量替换三条链路都不用改 —— 换的只是条款口径。
    """
    template = template or payload.get("template") or TEMPLATE_SIMPLE
    rows = list(items or [])
    total = sum((_money(row.get("amount") if row.get("amount") is not None
                        else _money(row.get("unit_price")) * _money(row.get("quantity")))
                 for row in rows), Decimal("0.00"))
    total = _money(total)
    chinese = amount_to_chinese(float(total))
    buyer, seller = _parties(payload)
    variant = TEMPLATE_DETAIL if str(template or "").lower() == TEMPLATE_DETAIL else TEMPLATE_SIMPLE
    builder = _simple_clauses if variant == TEMPLATE_SIMPLE else _clauses
    clauses = builder(payload, items=rows, total=total, chinese=chinese, buyer=buyer, seller=seller)

    numbered_items = [
        {
            "no": index,
            "product_name": _s(row.get("product_name")),
            "standards": _s(row.get("standards")),
            "unit": _s(row.get("unit")),
            "quantity": float(row.get("quantity") or 0),
            "unit_price": float(row.get("unit_price") or 0),
            "amount": float(_money(row.get("amount"))),
            "note": _s(row.get("note")),
        }
        for index, row in enumerate(rows, 1)
    ]

    return {
        "template": "SIMPLE" if variant == TEMPLATE_SIMPLE else "GONGKUANG",
        "template_name": TEMPLATE_NAMES[variant],
        "title": _s(payload.get("title")) or TEMPLATE_NAMES[variant],
        "contract_no": _s(payload.get("contract_no")) or "（未编号 · 草稿）",
        "sign_date": _s(payload.get("sign_date")),
        "sign_place": _s(payload.get("sign_place")),
        # 这几个是"合同事实"，除了写进条款正文，Word 模板变量替换时也要取得到
        # （缺了它们，模板里 {{delivery_place}} 会被替换成空字符串 —— 静默少一段信息最要命）
        "delivery_date": _s(payload.get("delivery_date")),
        "delivery_place": _s(payload.get("delivery_place")),
        "delivery_method": _s(payload.get("delivery_method")) or str(DEFAULTS["delivery_method"]),
        "freight_bearer": _s(payload.get("freight_bearer")) or str(DEFAULTS["freight_bearer"]),
        "payment_terms": _s(payload.get("payment_terms")) or str(DEFAULTS["payment_terms"]),
        "invoice_requirement": _s(payload.get("invoice_requirement"))
        or str(DEFAULTS["invoice_requirement"]),
        "quality_standard": _s(payload.get("quality_standard"))
        or str(DEFAULTS["quality_standard"]),
        "package_standard": _s(payload.get("package_standard"))
        or str(DEFAULTS["package_standard"]),
        "parties": {"buyer": buyer, "seller": seller},
        "items": numbered_items,
        "totals": {
            "amount": float(total),
            "amount_text": f"¥{total:,.2f}",
            "chinese": chinese,
            "tax_note": ("含税价" if payload.get("is_tax_included", True) else "不含税价"),
        },
        "clauses": clauses,
        "signatures": [
            {
                "role": "甲方（购货单位·盖章）",
                "name": buyer["name"],
                "legal": buyer["legal"],
                "bank_name": buyer["bank_name"],
                "bank_account": buyer["bank_account"],
                "date": _s(payload.get("sign_date")),
            },
            {
                "role": "乙方（供货单位·盖章）",
                "name": seller["name"],
                "legal": seller["legal"],
                "bank_name": seller["bank_name"],
                "bank_account": seller["bank_account"],
                "date": _s(payload.get("sign_date")),
            },
        ],
        "notes": [
            "本合同正文与明细表、补充协议共同构成完整的合同文件。",
            "签字盖章前请核对：双方名称、税号、开户行账号、数量单价金额、交货与付款条件。",
        ],
    }


def document_to_print_spec(document: dict[str, Any]) -> dict[str, Any]:
    """把文档结构转成打印引擎吃的 spec（走 `/print/*` 的同一条 PDF 出口）。

    复用打印出口的好处：页脚、纸张、字体全部跟其它单据一致，不再单独维护一套排版。
    """
    buyer = document["parties"]["buyer"]
    seller = document["parties"]["seller"]

    def block(label: str, party: dict) -> list[tuple[str, str]]:
        return [
            (label, party.get("name") or ""),
            ("统一社会信用代码", party.get("tax_no") or ""),
            ("地址", party.get("address") or ""),
            ("法定代表人", party.get("legal") or ""),
            ("联系人 / 电话", f"{party.get('contact') or ''} {party.get('phone') or ''}".strip()),
        ]

    paragraphs = [
        f"{clause['no']} {clause['heading']}\n" + "\n".join(clause["paragraphs"])
        for clause in document["clauses"]
    ]

    sig = document.get("signatures") or [{}, {}]
    s0, s1 = (sig + [{}, {}])[:2]

    def sign_cell(label: str, value: str) -> str:
        return f"{label}：{value or '＿＿＿＿＿＿'}"

    sign_grid = [
        [s0.get("role") or "甲方（购货单位·盖章）", s1.get("role") or "乙方（供货单位·盖章）"],
        [sign_cell("单位名称", s0.get("name")), sign_cell("单位名称", s1.get("name"))],
        [sign_cell("法定代表人", s0.get("legal")), sign_cell("法定代表人", s1.get("legal"))],
        [sign_cell("开户银行", s0.get("bank_name")), sign_cell("开户银行", s1.get("bank_name"))],
        [sign_cell("银行账号", s0.get("bank_account")), sign_cell("银行账号", s1.get("bank_account"))],
        ["（盖章处）", "（盖章处）"],
        [sign_cell("签订日期", document.get("sign_date")), sign_cell("签订日期", document.get("sign_date"))],
    ]

    return {
        "company": seller.get("name") or "",
        "title": document["title"],
        # 副标题跟着变体走：默认是《产品买卖合同（简易版）》，别把详细版的名字挂上去
        "subtitle": f"（{document.get('template_name') or document['title']} · 标准范本）",
        "period": f"合同编号：{document['contract_no']}",
        # 公文排版（2026-10-25）：黑体大标题 + 宋体 10.5pt 正文 + 1.5 倍行距 +
        # 条款首行缩进两字符 + 两端对齐；标题/表头字号在 layout 里统一。
        "layout": {
            "font_title": 16,
            "font_header": 10,
            "font_body": 10.5,
            "margin_left": 48,
            "margin_right": 48,
        },
        "paragraph_style": {"size": 10.5, "lineheight": 1.5, "indent": True, "justify": True},
        "header_left": block("甲方（购货单位）", buyer),
        "header_right": block("乙方（供货单位）", seller),
        "columns": [
            {"label": "序号", "width": 32, "align": "c"},
            {"label": "产品名称", "width": 150, "align": "l"},
            {"label": "规格型号", "width": 110, "align": "l"},
            {"label": "单位", "width": 42, "align": "c"},
            {"label": "数量", "width": 52, "align": "r"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 72, "align": "r"},
            {"label": "备注", "width": 48, "align": "l"},
        ],
        "rows": [
            [
                item["no"],
                item["product_name"],
                item["standards"],
                item["unit"],
                f"{item['quantity']:g}",
                f"{item['unit_price']:,.2f}",
                f"{item['amount']:,.2f}",
                item["note"],
            ]
            for item in document["items"]
        ],
        "totals": {
            "label": "合计",
            "chinese": f"大写：{document['totals']['chinese']}",
            "amount": f"{document['totals']['amount']:,.2f}",
        },
        "extra_rows": [
            ("签订日期", document.get("sign_date") or ""),
            ("签订地点", document.get("sign_place") or ""),
        ],
        "paragraphs": paragraphs,
        "notes": document["notes"],
        "sign_grid": sign_grid,
    }
