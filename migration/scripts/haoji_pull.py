# -*- coding: utf-8 -*-
"""浩技云全量拉取：按 haoji_probe.json 的 datagrid 接口分页拉取全部数据，
并从 list 页面解析动态字段(a01aXXaNN)的中文标题映射。
输出: haoji_data/raw_*.json  （含 rows / columns 映射）
"""
import sys, io, re, json, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

BASE = 'http://www.janssa.com:18526/emk/'
USER, PWD = 'zika2023', 'zika@~2023'
OUT = 'haoji_data'
os.makedirs(OUT, exist_ok=True)

# (存档名, probe.json 中文键, list页面)
TARGETS = [
    ('customers',   '客户管理',   'ymkCustomController.do?list'),
    ('products',    '商品管理',   'emkProductController.do?list'),
    ('suppliers',   '供应商管理', 'emkFactoryArchivesController.do?list'),
    ('warehouses',  '仓库管理',   'emkStorageSetController.do?list'),
    ('stock',       '库存管理',   'emkStorageController.do?list'),
    ('bank',        '现金银行',   'emkBankRecordController.do?accountList'),
    ('staff',       '员工管理',   'hmStaffController.do?list'),
    ('contract_cg', '采购合同',   'emkMaterialContractController.do?listCg'),
    ('contract_xs', '合同管理',   'emkMaterialContractController.do?list'),
    ('offers',      '报价单',     'emkOfferPriceController.do?list'),
    ('allot',       '调拨管理',   'emkStorageAllotController.do?list'),
    ('bom',         'BOM清单',    'emkBomController.do?list'),
    ('scstorage',   '成品入库',   'emkScStorageController.do?list'),
]

COL_RE = re.compile(r"\{[^{}]*?\}")

def parse_columns(html):
    """从 easyui 列定义解析 field->title 映射（处理 field/title 先后顺序）"""
    mapping = {}
    for block in COL_RE.findall(html):
        fm = re.search(r"field\s*:\s*['\"]([^'\"]+)['\"]", block)
        tm = re.search(r"title\s*:\s*['\"]([^'\"]+)['\"]", block)
        if fm and tm and fm.group(1) != tm.group(1):
            mapping[fm.group(1)] = tm.group(1)
    return mapping

def new_session():
    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'
    s.headers['Referer'] = BASE
    s.get(BASE + 'loginController.do?login', timeout=20)
    for i in range(8):
        img = s.get(BASE + 'randCodeImage', timeout=20).content
        code = ocr.classification(img)
        r = s.post(BASE + 'loginController.do?checkuser',
                   data={'userName': USER, 'password': PWD,
                         'randCode': code, 'langCode': '', 'orgId': ''}, timeout=20)
        try:
            if r.json().get('success'):
                print('登录成功')
                return s
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit('登录失败')

def pull_all(s, dg_url, field):
    """按 datagrid 分页拉全量"""
    rows, page, total = [], 1, None
    while True:
        # field 已含在 dg_url 里（probe 完整串），只追加分页参数，避免 field 重复
        r = s.get(f'{BASE}{dg_url}&page={page}&rows=500', timeout=40)
        d = r.json()
        total = d.get('total', 0)
        batch = d.get('rows', [])
        rows.extend(batch)
        print(f'    page {page}: +{len(batch)} (total {total})')
        if len(rows) >= total or not batch:
            break
        page += 1
        time.sleep(0.2)
    return rows, total

def main():
    probe = json.load(open('haoji_probe.json', encoding='utf-8'))
    s = new_session()
    for name, probe_key, list_op in TARGETS:
        m = probe.get(probe_key) or {}
        dg = m.get('datagrid', '')
        field = m.get('field', 'id')
        if not dg:
            print(f'== {name}: probe 中无 datagrid，跳过')
            continue
        print(f'== {name}: {dg[:70]}')
        try:
            # 1. 抓 list 页解析列标题
            colmap = {}
            try:
                lp = s.get(BASE + list_op, timeout=30)
                colmap = parse_columns(lp.text)
            except Exception as e:
                print('    colmap err', e)
            # 2. 全量拉数据
            rows, total = pull_all(s, dg, field)
            json.dump({'datagrid': dg, 'field': field, 'total': total,
                       'columns': colmap, 'rows': rows},
                      open(f'{OUT}/raw_{name}.json', 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            print(f'    saved raw_{name}.json rows={len(rows)} colmap={len(colmap)}')
        except Exception as e:
            print(f'    FAIL {name}: {str(e)[:150]}')
        time.sleep(0.4)

if __name__ == '__main__':
    main()
