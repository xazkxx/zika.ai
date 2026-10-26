-- =============================================================================
-- ERP 第一阶段：底层规范与字典体系
-- 文件：scripts/sql/phase1_dictionary_and_print_template.sql
-- 日期：2026-10-20
-- 适用：PostgreSQL 12+（当前生产 18）
--
-- 执行方式（二选一）：
--   A. 双击启动ERP.bat 重启一次 —— app/main.py 的 ensure_schema_in() 会自动补
--      customers / suppliers / financial_transactions 的列（幂等，本节 3 的效果相同）；
--   B. 手工执行本脚本：psql -U erp -d erp -f scripts/sql/phase1_dictionary_and_print_template.sql
--
-- 三条设计前提（务必先读）：
--   1. **data_dictionaries / data_dictionary_items / print_templates 是"全局表"**，
--      只存在于 public 一套，所有账套共用（见 app/core/company.py 的 GLOBAL_TABLES）。
--      所以这三张表**不需要**按账套复制，第 2、4 节只操作 public。
--   2. customers / suppliers / financial_transactions 是**账套表**，每个账套 schema
--      各有一份 —— 第 3、5 节用 DO 块遍历所有账套，不能只改 public。
--   3. 所有语句**幂等**：重复执行不报错、不覆盖已有数据（只补缺）。
-- =============================================================================


-- =============================================================================
-- 第 1 节 · 数字字典（现状：已存在，无需重建）
-- -----------------------------------------------------------------------------
-- 老系统截图里的「资金账户 / 付款方式 / 结算方式」在现有系统里对应
-- data_dictionaries（字典分类）+ data_dictionary_items（字典项）两张表。
-- 现有结构已经覆盖需求：分类 Code = dict_type、项 Name = item_label、
-- 项 Value = item_value、启用状态 = is_enabled。
-- 下面这段是**基线参考 DDL**（新库由 SQLAlchemy create_all 自动建，这里只是
-- 让审阅时一眼看到字段；IF NOT EXISTS 保证不会动到现有表）。
-- =============================================================================
CREATE TABLE IF NOT EXISTS data_dictionaries (
    id          SERIAL PRIMARY KEY,
    dict_type   VARCHAR(60)  NOT NULL UNIQUE,   -- 字典分类编码（Code），如 payment_method
    dict_name   VARCHAR(80)  NOT NULL,          -- 分类名称，如「付款方式」
    description VARCHAR(255),
    is_system   BOOLEAN      NOT NULL DEFAULT FALSE,  -- 内置字典，程序有读取点，不许删
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,   -- 启用状态
    created_at  TIMESTAMPTZ  DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_dictionary_items (
    id          SERIAL PRIMARY KEY,
    dict_type   VARCHAR(60) NOT NULL,           -- 所属分类（字符串关联，不用外键）
    item_value  VARCHAR(80) NOT NULL,           -- 值（存进单据的那个）
    item_label  VARCHAR(80) NOT NULL,           -- 显示名（给人看的）
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    is_enabled  BOOLEAN     NOT NULL DEFAULT TRUE,
    remark      VARCHAR(255),
    created_at  TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_dict_type_value UNIQUE (dict_type, item_value)
);

CREATE INDEX IF NOT EXISTS ix_data_dictionary_items_dict_type
    ON data_dictionary_items (dict_type);


-- =============================================================================
-- 第 2 节 · 补齐缺失的字典分类（资金账户 / 结算方式）
-- -----------------------------------------------------------------------------
-- 付款方式 payment_method 已存在；补另外两个。字典项用 ON CONFLICT 幂等插入，
-- 管理员以后在「系统设置 → 数字字典」里改过的名字不会被这脚本覆盖。
-- =============================================================================
INSERT INTO data_dictionaries (dict_type, dict_name, description, is_system, is_active)
VALUES
    ('fund_account',      '资金账户', '日常收支登记时的资金账户候选（真实余额以现金银行页的资金账户为准）', TRUE, TRUE),
    ('settlement_method', '结算方式', '单据上的结算方式候选（现结 / 月结 / 账期 …），与「付款方式」互补', TRUE, TRUE)
ON CONFLICT (dict_type) DO NOTHING;

INSERT INTO data_dictionary_items (dict_type, item_value, item_label, sort_order, is_enabled)
VALUES
    ('fund_account', '现金',     '现金',     10, TRUE),
    ('fund_account', '基本户',   '基本户',   20, TRUE),
    ('fund_account', '一般户',   '一般户',   30, TRUE),
    ('fund_account', '微信',     '微信',     40, TRUE),
    ('fund_account', '支付宝',   '支付宝',   50, TRUE),
    ('fund_account', '备用金',   '备用金',   60, TRUE),
    ('settlement_method', '现结',           '现结',           10, TRUE),
    ('settlement_method', '月结',           '月结',           20, TRUE),
    ('settlement_method', '货到付款',       '货到付款',       30, TRUE),
    ('settlement_method', '预付款',         '预付款',         40, TRUE),
    ('settlement_method', '货到验收后付',   '货到验收后付',   50, TRUE),
    ('settlement_method', '分期付款',       '分期付款',       60, TRUE),
    ('settlement_method', '代收代付',       '代收代付',       70, TRUE)
ON CONFLICT (dict_type, item_value) DO NOTHING;


-- =============================================================================
-- 第 3 节 · 客户 / 供应商档案补公司信息字段（账套表，遍历所有 schema）
-- -----------------------------------------------------------------------------
-- 增量说明：
--   customers : 已有 tax_no / bank_name / bank_account → 只补 account_name（开户名称）
--   suppliers : 有 bank_name / bank_account → 补 tax_no（税号）+ account_name（开户名称）
-- 全部可空，历史数据一行都不用回填。
-- =============================================================================
DO $$
DECLARE
    s text;
BEGIN
    FOR s IN
        SELECT schema_name FROM information_schema.schemata
        WHERE schema_name = 'public' OR schema_name LIKE 'co\_%'
        ORDER BY schema_name
    LOOP
        -- 客户：开户名称
        IF EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = s AND table_name = 'customers')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = s AND table_name = 'customers'
                             AND column_name = 'account_name') THEN
            EXECUTE format('ALTER TABLE %I.customers ADD COLUMN account_name VARCHAR(150)', s);
        END IF;

        -- 供应商：税号 + 开户名称
        IF EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = s AND table_name = 'suppliers')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = s AND table_name = 'suppliers'
                             AND column_name = 'tax_no') THEN
            EXECUTE format('ALTER TABLE %I.suppliers ADD COLUMN tax_no VARCHAR(50)', s);
        END IF;

        IF EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = s AND table_name = 'suppliers')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = s AND table_name = 'suppliers'
                             AND column_name = 'account_name') THEN
            EXECUTE format('ALTER TABLE %I.suppliers ADD COLUMN account_name VARCHAR(150)', s);
        END IF;

        -- 财务流水：流水号 FL…
        IF EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = s AND table_name = 'financial_transactions')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = s AND table_name = 'financial_transactions'
                             AND column_name = 'flow_no') THEN
            EXECUTE format('ALTER TABLE %I.financial_transactions ADD COLUMN flow_no VARCHAR(40)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_%s_ft_flow_no ON %I.financial_transactions (flow_no)', s, s);
        END IF;
    END LOOP;
END $$;

COMMENT ON COLUMN public.customers.account_name IS '开户名称（对公打款户名，可能不同于客户名称）';
COMMENT ON COLUMN public.suppliers.tax_no       IS '税号（进项发票认证用）';
COMMENT ON COLUMN public.suppliers.account_name IS '开户名称';
COMMENT ON COLUMN public.financial_transactions.flow_no IS '流水号 FL+日期+流水，历史数据为空';


-- =============================================================================
-- 第 4 节 · 打印模板库扩展（全局表，只改 public）
-- -----------------------------------------------------------------------------
-- 现状 print_templates 已有：name / doc_type / doc_label / title / header_text /
-- footer_text / show_company / show_signatures / note / sort_order。
-- 缺"纸张与排版"这一层。本节点补齐：
--   纸张：paper_size + 自定义宽高（mm）
--   边距：上右下左（mm）
--   字号：标题 / 表头 / 表体（pt）
-- 全部带默认值且 NOT NULL，历史模板行不需要回填。
--
-- ⚠️ 为什么用 INTEGER 存 mm/pt 而不是小数：打印渲染最终落到整数像素/缇，
--    1mm 的精度已经远超肉眼分辨；用小数只会让"12.0000001mm"这种值进数据库。
-- =============================================================================
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS paper_size      VARCHAR(20) NOT NULL DEFAULT 'A4';
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS paper_width_mm  INTEGER;          -- 自定义纸张宽（paper_size='CUSTOM' 时生效）
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS paper_height_mm INTEGER;          -- 自定义纸张高
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS margin_top      INTEGER NOT NULL DEFAULT 12;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS margin_right    INTEGER NOT NULL DEFAULT 10;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS margin_bottom   INTEGER NOT NULL DEFAULT 12;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS margin_left     INTEGER NOT NULL DEFAULT 10;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS font_size_title  INTEGER NOT NULL DEFAULT 16;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS font_size_header INTEGER NOT NULL DEFAULT 10;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS font_size_body   INTEGER NOT NULL DEFAULT 9;
ALTER TABLE print_templates ADD COLUMN IF NOT EXISTS font_size_footer INTEGER NOT NULL DEFAULT 8;

COMMENT ON COLUMN print_templates.paper_size      IS '纸张：A4 / A5 / LETTER / CUSTOM';
COMMENT ON COLUMN print_templates.paper_width_mm  IS '自定义纸张宽（mm），仅 CUSTOM 使用';
COMMENT ON COLUMN print_templates.paper_height_mm IS '自定义纸张高（mm），仅 CUSTOM 使用';
COMMENT ON COLUMN print_templates.margin_top      IS '上边距（mm）';
COMMENT ON COLUMN print_templates.margin_right    IS '右边距（mm）';
COMMENT ON COLUMN print_templates.margin_bottom   IS '下边距（mm）';
COMMENT ON COLUMN print_templates.margin_left     IS '左边距（mm）';
COMMENT ON COLUMN print_templates.font_size_title  IS '标题字号（pt）';
COMMENT ON COLUMN print_templates.font_size_header IS '表头字号（pt）';
COMMENT ON COLUMN print_templates.font_size_body   IS '表体字号（pt）';
COMMENT ON COLUMN print_templates.font_size_footer IS '页脚字号（pt）';

-- 取值护栏：纸张只认这几种；边距 0~50mm；字号 6~28pt。
-- 用 CHECK 而不是只靠前端校验 —— 直接写 SQL 或走接口都要被挡住。
ALTER TABLE print_templates DROP CONSTRAINT IF EXISTS ck_print_templates_paper_size;
ALTER TABLE print_templates ADD  CONSTRAINT ck_print_templates_paper_size
    CHECK (paper_size IN ('A4', 'A5', 'LETTER', 'CUSTOM'));

ALTER TABLE print_templates DROP CONSTRAINT IF EXISTS ck_print_templates_margins;
ALTER TABLE print_templates ADD  CONSTRAINT ck_print_templates_margins
    CHECK (margin_top    BETWEEN 0 AND 50 AND
           margin_right  BETWEEN 0 AND 50 AND
           margin_bottom BETWEEN 0 AND 50 AND
           margin_left   BETWEEN 0 AND 50);

ALTER TABLE print_templates DROP CONSTRAINT IF EXISTS ck_print_templates_fonts;
ALTER TABLE print_templates ADD  CONSTRAINT ck_print_templates_fonts
    CHECK (font_size_title  BETWEEN 8 AND 28 AND
           font_size_header BETWEEN 6 AND 20 AND
           font_size_body   BETWEEN 6 AND 20 AND
           font_size_footer BETWEEN 6 AND 20);

-- CUSTOM 必须给宽高，否则渲染器不知道该用多大的纸
ALTER TABLE print_templates DROP CONSTRAINT IF EXISTS ck_print_templates_custom_size;
ALTER TABLE print_templates ADD  CONSTRAINT ck_print_templates_custom_size
    CHECK (paper_size <> 'CUSTOM' OR (paper_width_mm BETWEEN 50 AND 500 AND paper_height_mm BETWEEN 50 AND 500));


-- =============================================================================
-- 第 5 节 · 完整建表参考（供审阅，不要执行 —— 表已存在）
-- -----------------------------------------------------------------------------
-- 把第 4 节的增量合并进来后，print_templates 的**目标结构**长这样：
--
-- CREATE TABLE print_templates (
--     id                SERIAL PRIMARY KEY,
--     doc_type          VARCHAR(40)  NOT NULL UNIQUE,  -- 单据类型（打印注册表 key）
--     doc_label         VARCHAR(60)  NOT NULL DEFAULT '',
--     name              VARCHAR(80)  NOT NULL DEFAULT '',  -- 模板名称
--     title             VARCHAR(80)  NOT NULL DEFAULT '',  -- 标题覆盖
--     header_text       TEXT         NOT NULL DEFAULT '',  -- 抬头文本（支持 \n 多行）
--     footer_text       TEXT         NOT NULL DEFAULT '',  -- 页脚文本
--     show_company      BOOLEAN      NOT NULL DEFAULT TRUE,
--     show_signatures   BOOLEAN      NOT NULL DEFAULT TRUE,
--     paper_size        VARCHAR(20)  NOT NULL DEFAULT 'A4',
--     paper_width_mm    INTEGER,
--     paper_height_mm   INTEGER,
--     margin_top        INTEGER      NOT NULL DEFAULT 12,
--     margin_right      INTEGER      NOT NULL DEFAULT 10,
--     margin_bottom     INTEGER      NOT NULL DEFAULT 12,
--     margin_left       INTEGER      NOT NULL DEFAULT 10,
--     font_size_title   INTEGER      NOT NULL DEFAULT 16,
--     font_size_header  INTEGER      NOT NULL DEFAULT 10,
--     font_size_body    INTEGER      NOT NULL DEFAULT 9,
--     font_size_footer  INTEGER      NOT NULL DEFAULT 8,
--     note              VARCHAR(255),
--     sort_order        INTEGER      NOT NULL DEFAULT 0,
--     updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
-- );
-- =============================================================================


-- =============================================================================
-- 第 6 节 · 自检（执行完跑一遍，四列都应返回 t）
-- =============================================================================
SELECT
    EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='customers'
              AND column_name='account_name')                      AS customers_account_name,
    EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='suppliers'
              AND column_name='account_name')                      AS suppliers_account_name,
    EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='financial_transactions'
              AND column_name='flow_no')                           AS finance_flow_no,
    EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='print_templates'
              AND column_name='margin_top')                        AS template_margins;
