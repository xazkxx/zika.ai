/**
 * 资金参数面板（v1.81.0）
 *
 * 默认只露 5 个老板真的会动的数：付款周期、回款周期、日资金成本、预收、上游定金。
 * 七个税率收进「高级参数」折叠 —— 它们一年也不改一次，摊在外面只会让人不敢碰。
 *
 * 费率的存储形态是**小数**（0.00045），输入框显示的是**百分数**（0.045）。
 * 转换只在这一层做：`× 100 / ÷ 100`，来回都过 Number 再定长，避免 0.0004500001。
 */
import { memo } from 'react';
import { DEFAULT_SETTINGS, num, percent } from '../../lib/projectCalc';

const BASIC_FIELDS = [
  { key: 'pay_days', label: '付款周期', suffix: '天', hint: '多久把钱付给上游' },
  { key: 'collect_days', label: '回款周期', suffix: '天', hint: '多久收回下游货款' },
  { key: 'capital_daily_rate', label: '日资金成本', suffix: '%', percent: true, hint: '0.02% ≈ 年化 7.30%' },
  { key: 'prepay', label: '已收预收', suffix: '元', money: true, hint: '抵减垫资' },
  { key: 'prepay_supplier', label: '已付定金', suffix: '元', money: true, hint: '抵减垫资' },
];

const RATE_FIELDS = [
  { key: 'vat_rate', label: '增值税率' },
  { key: 'city_rate', label: '城建税' },
  { key: 'edu_rate', label: '教育费附加' },
  { key: 'ledu_rate', label: '地方教育附加' },
  { key: 'water_rate', label: '水利基金' },
  { key: 'stamp_rate', label: '印花税' },
  { key: 'income_rate', label: '企业所得税' },
];

const toPercentInput = (value) => {
  const scaled = num(value) * 100;
  return String(Number(scaled.toFixed(6)));
};

const fromPercentInput = (text) => String(Number((num(text) / 100).toFixed(8)));

function CapitalSettings({ settings, onChange, onReset }) {
  return (
    <section className="pc-card pc-settings">
      <header className="pc-card__head">
        <h3>资金参数</h3>
        <button type="button" className="pc-link-btn" onClick={onReset} title="恢复 Excel v6 / 现行小微口径">
          恢复默认
        </button>
      </header>

      <div className="pc-settings__grid">
        {BASIC_FIELDS.map((field) => (
          <label key={field.key} className="pc-field">
            <span className="pc-field__label">
              {field.label}
              <em>{field.hint}</em>
            </span>
            <span className="pc-field__input">
              <input
                className="pc-input pc-input--num"
                value={field.percent ? toPercentInput(settings[field.key]) : settings[field.key]}
                inputMode="decimal"
                onChange={(event) =>
                  onChange({
                    [field.key]: field.percent ? fromPercentInput(event.target.value) : event.target.value,
                  })
                }
              />
              <i>{field.suffix}</i>
            </span>
          </label>
        ))}
      </div>

      <p className="pc-settings__line">
        占用天数 = 回款 − 付款（≤0 记 0）　日利率 {percent(settings.capital_daily_rate, 2)}　
        年化 {percent(num(settings.capital_daily_rate) * 365, 2)}
      </p>

      <details className="pc-settings__more">
        <summary>高级参数（税率与减半口径）</summary>
        <div className="pc-settings__grid pc-settings__grid--rates">
          {RATE_FIELDS.map((field) => (
            <label key={field.key} className="pc-field">
              <span className="pc-field__label">{field.label}</span>
              <span className="pc-field__input">
                <input
                  className="pc-input pc-input--num"
                  value={toPercentInput(settings[field.key])}
                  inputMode="decimal"
                  onChange={(event) => onChange({ [field.key]: fromPercentInput(event.target.value) })}
                />
                <i>%</i>
              </span>
            </label>
          ))}
        </div>
        <div className="pc-settings__checks">
          <label>
            <input
              type="checkbox"
              checked={Boolean(settings.surcharge_half)}
              onChange={(event) => onChange({ surcharge_half: event.target.checked })}
            />
            六税两费减半（城建/教育/地方教育/印花 ÷2）
          </label>
          <label>
            <input
              type="checkbox"
              checked={Boolean(settings.include_income_tax_in_advance)}
              onChange={(event) => onChange({ include_income_tax_in_advance: event.target.checked })}
            />
            所得税计入垫资（默认不计：按季预缴，不占货款）
          </label>
        </div>
        <p className="pc-settings__tip">
          默认值：增值税 {percent(DEFAULT_SETTINGS.vat_rate, 0)} · 小微所得税 {percent(DEFAULT_SETTINGS.income_rate, 0)} ·
          水利基金 {percent(DEFAULT_SETTINGS.water_rate, 3)} · 印花税 {percent(DEFAULT_SETTINGS.stamp_rate, 3)}
        </p>
      </details>
    </section>
  );
}

export default memo(CapitalSettings);
