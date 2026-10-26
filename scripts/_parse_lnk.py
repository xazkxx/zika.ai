import re

path = r"C:\Users\admi\Desktop\ERP管理系统.lnk"
data = open(path, "rb").read()

print("=== ASCII 可打印序列（含关键字）===")
kws = ["ERP", ".bat", ".exe", "pythonw", "desktop", "8010", "8011", "desktop_app", "启动", "uvicorn"]
for m in re.finditer(rb"[ -~]{3,}", data):
    s = m.group(0).decode("ascii", "ignore")
    if any(k in s for k in kws):
        print(repr(s))

print("\n=== 所有 ASCII 序列（前 60 条，供排查）===")
cnt = 0
for m in re.finditer(rb"[ -~]{3,}", data):
    s = m.group(0).decode("ascii", "ignore")
    print(repr(s))
    cnt += 1
    if cnt >= 60:
        break
