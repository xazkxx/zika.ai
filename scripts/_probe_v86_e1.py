"""反证 2：把 onClick 里的 isClickSuppressed 拿掉，E1 应该变红。

用法：python scripts/_probe_v86_e1.py apply | restore
"""
import sys
from pathlib import Path

P = Path(__file__).resolve().parent.parent / 'frontend/src/components/product-category/ProductCategoryTree.jsx'
GOOD = """    onClick: () => {
      if (drag.isClickSuppressed()) return;
      select(key, toggleOff);
    },"""
BAD = """    onClick: () => {
      // PROBE 故意不吞 click
      select(key, toggleOff);
    },"""

mode = sys.argv[1] if len(sys.argv) > 1 else 'apply'
text = P.read_text(encoding='utf-8')

if mode == 'apply':
    assert GOOD in text, '未找到 isClickSuppressed 那段'
    P.write_text(text.replace(GOOD, BAD), encoding='utf-8', newline='\n')
    print('probe applied')
elif mode == 'restore':
    assert BAD in text, '未找到 PROBE 标记'
    P.write_text(text.replace(BAD, GOOD), encoding='utf-8', newline='\n')
    print('restored')
else:
    raise SystemExit('用法: apply | restore')
