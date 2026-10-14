# -*- coding: utf-8 -*-
"""浩技云进销存 — 模块数据量盘点
用法: python haoji_probe.py
对菜单里每个模块抓取列表页 -> 解析 datagrid 接口与字段 -> 拉取 total
输出: haoji_probe.json
"""
import sys, io, re, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

BASE = 'http://www.janssa.com:18526/emk/'
USER, PWD = 'zika2023', 'zika@~2023'

# 要盘点的模块: (菜单名, list页面操作)
MODULES = [
    ('客户管理',   'ymkCustomController.do?list'),
    ('商品管理',   'emkProductController.do?list'),
    ('商品期初库存','emkProductController.do?list1'),
    ('供应商管理', 'emkFactoryArchivesController.do?list'),
    ('仓库管理',   'emkStorageSetController.do?list'),
    ('员工管理',   'hmStaffController.do?list'),
    ('采购入库',   'emkMInStorageController.do?list'),
    ('采购订单',   'emkMInStorageController.do?list2'),
    ('采购对账单', 'emkMInStorageController.do?listBill'),
    ('采购合同',   'emkMaterialContractController.do?listCg'),
    ('开单管理',   'emkMOutStorageController.do?list'),
    ('销售对账单', 'emkMOutStorageController.do?listBill'),
    ('产品销售明细','emkMOutStorageController.do?listBill2'),
    ('销售退货',   'emkOutOrderController.do?list'),
    ('订单管理',   'emkProOrderController.do?list'),
    ('报价单',     'emkOfferPriceController.do?list'),
    ('合同管理',   'emkMaterialContractController.do?list'),
    ('合同模板',   'emkClauseController.do?list'),
    ('退货管理',   'emkCancelOrderController.do?list'),
    ('库存管理',   'emkStorageController.do?list'),
    ('调拨管理',   'emkStorageAllotController.do?list'),
    ('盘点管理',   'emkStroageCheckController.do?list'),
    ('变动查询',   'emkStorageLogController.do?list'),
    ('报损管理',   'emkStorageAllotController.do?bsList'),
    ('报溢管理',   'emkStorageAllotController.do?byList'),
    ('客户往来账', 'emkYsPayController.do?list'),
    ('应收账款',   'emkYsPayController.do?listBill'),
    ('供应商往来账','emkFinanceYfCheckController.do?list'),
    ('应付账款',   'emkFinanceYfCheckController.do?listBill'),
    ('现金银行',   'emkBankRecordController.do?accountList'),
    ('日常收入',   'emkFinanceReceivableController.do?list'),
    ('日常支出',   'emkFinanceCheckController.do?list'),
    ('销售开票',   'emkInvoicesController.do?list2'),
    ('进货开票',   'emkInvoicesController.do?list1'),
    ('BOM清单',    'emkBomController.do?list'),
    ('生产单',     'emkProduceController.do?list'),
    ('生产领料',   'emkReceptionController.do?list'),
    ('生产退料',   'emkOutForumController.do?list'),
    ('成品入库',   'emkScStorageController.do?list'),
    ('委外加工单', 'emkWwjgController.do?list'),
]

FIELD_RE = re.compile(r"([A-Za-z]+Controller\.do\?datagrid[^'\"]*)")
FIELD_ATTR_RE = re.compile(r"field=([A-Za-z0-9_,]+)")

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
                         'randCode': code, 'langCode': '', 'orgId': ''},
                   timeout=20)
        try:
            if r.json().get('success'):
                print('登录成功')
                return s
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit('登录失败')

def probe(s, page_url):
    """抓列表页, 返回 (datagrid_url, field, total)"""
    r = s.get(BASE + page_url, timeout=25)
    m = FIELD_RE.search(r.text)
    if not m:
        return None
    dg = m.group(1).replace('&amp;', '&')
    fm = FIELD_ATTR_RE.search(dg)
    field = fm.group(1) if fm else 'id'
    rr = s.get(BASE + dg.split('&field')[0] if '&field' not in dg else BASE + dg,
               params={'field': field, 'page': 1, 'rows': 1}, timeout=25)
    try:
        d = rr.json()
        return dg, field, d.get('total', 0), d.get('rows', [])
    except Exception:
        return dg, field, -1, []

def main():
    s = new_session()
    out = {}
    for name, url in MODULES:
        try:
            res = probe(s, url)
            if res is None:
                out[name] = {'page': url, 'note': '无datagrid'}
                print(f'{name:12s} -          无datagrid')
            else:
                dg, field, total, rows = res
                out[name] = {'page': url, 'datagrid': dg, 'field': field,
                             'total': total, 'sample': rows[:2]}
                print(f'{name:12s} {total:>8}   {dg[:80]}')
        except Exception as e:
            out[name] = {'page': url, 'error': str(e)[:120]}
            print(f'{name:12s} ERR {str(e)[:60]}')
        time.sleep(0.3)
    with open('haoji_probe.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n已保存 haoji_probe.json')

if __name__ == '__main__':
    main()
