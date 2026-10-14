# -*- coding: utf-8 -*-
"""浩技云登录工具 — 复用验证码 OCR，返回带会话的 requests.Session
可被其他脚本 import:  from haoji_login import new_session
"""
import sys, time
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import requests

BASE = 'http://www.janssa.com:18526/emk/'
USER, PWD = 'zika2023', 'zika@~2023'


def new_session(verbose=True):
    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)
    s = requests.Session()
    s.headers['User-Agent'] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 (KHTML, like Gecko) '
                               'Chrome/120.0.0.0 Safari/537.36')
    s.headers['Referer'] = BASE
    s.get(BASE + 'loginController.do?login', timeout=20)
    for i in range(10):
        img = s.get(BASE + 'randCodeImage', timeout=20).content
        code = ocr.classification(img)
        r = s.post(BASE + 'loginController.do?checkuser',
                   data={'userName': USER, 'password': PWD,
                         'randCode': code, 'langCode': '', 'orgId': ''},
                   timeout=20)
        try:
            j = r.json()
        except Exception:
            j = {}
        if j.get('success'):
            if verbose:
                print(f'登录成功 (第{i+1}次尝试, 验证码={code})')
            return s
        if verbose:
            print(f'  第{i+1}次失败: code={code} resp={str(j)[:80]}')
        time.sleep(0.4)
    raise SystemExit('登录失败: 连续10次验证码未通过')


if __name__ == '__main__':
    s = new_session()
    print('cookies:', s.cookies.get_dict())
