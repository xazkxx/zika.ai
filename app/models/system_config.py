"""系统参数 与 数字字典 —— 系统管理第 5 批第 2 轮。

**参数设置**（`system_params`）：键值对配置中心。

一条自我约束：**这里只放真正会被程序读取的参数**。
"改了没反应"的假参数比没有参数页更糟 —— 用户会以为改了生效了。
所以每个内置参数都必须能在代码里找到它的读取点，测试里也逐个验证生效
（见 `tests/test_system_config.py::test_every_builtin_param_is_read`）。

**数字字典**（`data_dictionaries` + `data_dictionary_items`）：
可维护的枚举清单，给"付款方式""计量单位"这类**有多候选但允许自由填写**的
字段提供下拉候选（前端用 `<datalist>` 挂上，既给候选又不锁死输入）。

字典项用 `dict_type` 字符串关联而不是外键 id：
- 前端只需要一个 type 字符串就能取到一列候选，不必先查类型表拿 id；
- 字典是"配置"，不需要被业务单据外键引用，也就没有级联删除的负担。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.db.base import Base


class SystemParam(Base):
    __tablename__ = "system_params"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    param_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    param_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 分组 key：print / system / stock ...（见 PARAM_GROUPS）
    param_group: Mapped[str] = mapped_column(String(40), default="system", nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    # string / bool / int / decimal —— 决定前端渲染成输入框、开关还是数字框，也用于写入校验
    value_type: Mapped[str] = mapped_column(String(16), default="string", nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # False = 系统关键项，只读（防止把系统改坏）；内置参数默认可改
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataDictionary(Base):
    __tablename__ = "data_dictionaries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    dict_type: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    dict_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 内置字典（程序里有读取点）不允许删除，避免把页面上的下拉抽空
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataDictionaryItem(Base):
    __tablename__ = "data_dictionary_items"
    __table_args__ = (UniqueConstraint("dict_type", "item_value", name="uq_dict_type_value"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    dict_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    item_value: Mapped[str] = mapped_column(String(80), nullable=False)
    item_label: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 参数分组（前端按此分 Tab/分块渲染）
# ============================================================
PARAM_GROUPS: list[dict[str, str]] = [
    {"group": "print", "label": "打印与单据"},
    {"group": "system", "label": "系统与界面"},
    {"group": "stock", "label": "库存"},
]

PARAM_VALUE_TYPES = {"string": "文本", "bool": "开关", "int": "整数", "decimal": "小数"}


# 内置参数。每一条都**必须**有代码里的读取点，见模块 docstring：
#   print.footer_text   → app/services/pdf_render.py（PDF 页脚文字）
#   system.default_page → 前端 App.jsx（登录后落地页）
#   stock.warn_enabled  → 前端 App.jsx（库存预警徽标开关）
DEFAULT_PARAMS: list[dict[str, object]] = [
    {
        "param_key": "print.footer_text",
        "param_value": "",
        "param_group": "print",
        "label": "打印页脚文字",
        "value_type": "string",
        "description": "打印单据 PDF 的页脚（左侧）；留空则只显示页码",
        "sort_order": 10,
    },
    {
        "param_key": "system.default_page",
        "param_value": "overview",
        "param_group": "system",
        "label": "登录后默认页面",
        "value_type": "string",
        "description": "登录成功后自动打开的菜单 key，如 overview / reports / sales",
        "sort_order": 20,
    },
    {
        "param_key": "stock.warn_enabled",
        "param_value": "true",
        "param_group": "stock",
        "label": "启用库存预警",
        "value_type": "bool",
        "description": "关闭后现存量列表不再显示缺货 / 低库存 / 积压徽标",
        "sort_order": 30,
    },
]


# 内置字典。同样要求有前端读取点：
#   payment_method → 采购/销售/报价/退货单的「付款方式」候选
#   position       → 用户岗位候选
#   product_unit   → 商品档案「单位」候选
#   bank_name      → 客户/供应商「开户银行」候选
#   tax_rate       → 商品档案默认税率、发票/合同/报价单的税率候选
#
# 字典项两种写法都支持：
#   "现金"                                     → value = label = "现金"
#   {"value": "13", "label": "13% — 销售货物"} → 值是 13，下拉里显示说明文字
# 税率这种"值要精确、说明要给人看"的字段必须用后一种，
# 否则下拉里只有光秃秃的 "13"，用户不知道它管哪些业务。
DEFAULT_DICTIONARIES: list[dict[str, object]] = [
    # 日常收支的类别（现金银行页的收支登记用）。放字典而不是硬编码枚举，
    # 是为了让企业按自己的科目改 —— 每家的费用科目都不一样。
    {
        "dict_type": "income_category",
        "dict_name": "收入类别",
        "description": "日常收入登记的类别候选",
        "items": ["销售收入", "其他业务收入", "利息收入", "补贴收入", "往来款收回", "其他收入"],
    },
    {
        "dict_type": "expense_category",
        "dict_name": "支出类别",
        "description": "日常支出登记的类别候选",
        "items": [
            "办公费", "差旅费", "水电费", "运费", "通讯费", "招待费",
            "房租", "工资", "社保公积金", "维修费", "手续费", "利息支出", "其他支出",
        ],
    },
    {
        "dict_type": "payment_method",
        "dict_name": "付款方式",
        "description": "单据上的结算方式候选",
        "items": ["现金", "银行转账", "微信", "支付宝", "承兑汇票", "月结", "货到付款"],
    },
    {
        "dict_type": "position",
        "dict_name": "岗位",
        "description": "员工 / 用户的岗位候选",
        "items": ["总经理", "部门经理", "销售员", "采购员", "仓管员", "会计", "出纳", "技术员", "文员"],
    },
    {
        "dict_type": "product_unit",
        "dict_name": "计量单位",
        "description": "商品档案的单位候选",
        "items": ["个", "件", "台", "套", "只", "把", "箱", "包", "盒", "千克", "克", "吨", "米", "平方米", "立方米", "升", "千瓦", "卷"],
    },
    {
        "dict_type": "bank_name",
        "dict_name": "开户银行",
        "description": "客户 / 供应商的开户行候选",
        "items": [
            "中国工商银行", "中国农业银行", "中国银行", "中国建设银行", "交通银行",
            "中国邮政储蓄银行", "招商银行", "浦发银行", "中信银行", "兴业银行",
            "民生银行", "光大银行", "平安银行", "华夏银行", "广发银行",
        ],
    },
    # —— 开票税点（增值税）——
    # 依据《中华人民共和国增值税法》（2025-12-25 通过，**2026-01-01 施行**）
    # 第十条「税率」与第十一条「征收率」，辅以国家税务总局各地答疑口径：
    #
    #   13% 销售货物、加工修理修配、有形动产租赁、进口货物
    #    9% 交通运输/邮政/基础电信/建筑/不动产租赁、销售不动产、转让土地使用权；
    #       农产品、食用植物油、食用盐、自来水、暖气、燃气、图书报刊、饲料化肥农药农机农膜
    #    6% 销售服务、无形资产（上述两档之外的）
    #    0% 出口货物；跨境销售国务院规定范围内的服务、无形资产
    #    3% 简易计税征收率（**法定**，小规模纳税人及一般纳税人简易计税）
    #    1% 小规模纳税人 3% 征收率减按 1% 征收的**阶段性优惠**
    #
    # ⚠️ 两条要写进代码里别丢的注意点：
    #   1. **没有 5%**。增值税法把简易计税征收率统一为 3%，取消了营改增时期
    #      不动产租赁/销售等适用的 5% 特殊征收率。旧资料里常见的 5% 已不再适用，
    #      保留它会让用户开错票。
    #   2. 字典只是**候选**，不是税收判据。具体业务适用哪一档由纳税人的
    #      实际交易性质决定，最终以主管税务机关口径为准。所以这里用可维护的字典，
    #      不硬编码成枚举；界面上也允许自由填写。
    {
        "dict_type": "tax_rate",
        "dict_name": "开票税率 / 征收率（增值税）",
        "description": "依据《增值税法》（2026-01-01 施行）第十条、第十一条；以主管税务机关口径为准，可按需增减",
        "items": [
            {"value": "13", "label": "13% — 销售货物 / 加工修理修配 / 有形动产租赁 / 进口货物"},
            {"value": "9", "label": "9% — 交通运输·邮政·建筑·不动产租赁 / 农产品·图书·饲料化肥农机等"},
            {"value": "6", "label": "6% — 销售服务 / 无形资产"},
            {"value": "3", "label": "3% — 简易计税征收率（法定）"},
            {"value": "1", "label": "1% — 小规模纳税人 3% 减按 1%（阶段性优惠）"},
            {"value": "0", "label": "0% — 出口货物 / 跨境应税行为"},
        ],
    },
]


# ============================================================
# 读取辅助 —— 供其它模块调用
# ============================================================
def get_param(db: Session, key: str, default: str = "") -> str:
    """读一个系统参数。库里没有该键时返回 default（不建行、不抛错）。"""
    row = db.query(SystemParam).filter(SystemParam.param_key == key).first()
    if row is None or row.param_value is None:
        return default
    return row.param_value


def get_bool_param(db: Session, key: str, default: bool = False) -> bool:
    """读一个开关型参数。只认 'true'/'1'/'yes'/'on'（不区分大小写）为真。"""
    raw = get_param(db, key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "on"}


def param_default(key: str, default: str = "") -> str:
    """从内置参数表里取默认值（不查库）。用于兜底与"恢复默认"。"""
    for spec in DEFAULT_PARAMS:
        if spec["param_key"] == key:
            return str(spec["param_value"])
    return default
