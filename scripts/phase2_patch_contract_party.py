# -*- coding: utf-8 -*-
"""合同编辑小补：PATCH 换了对方单位必须同时更新 party_name 快照。
后端 PATCH 的 text_fields 里虽然有 party_name，但新建时没人传（后端按 party_id 反查），
编辑时如果也不传，改了客户名字还是旧的 —— 打印出来对不上。"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.jsx"
text = APP.read_bytes().decode("utf-8").replace("\r\n", "\n")

OLD = """          party_id: num(contractForm.party_id),
          warehouse_id: num(contractForm.warehouse_id),
"""
NEW = """          party_id: num(contractForm.party_id),
          // 对方单位名称快照：编辑态换了客户/供应商时必须跟着换，
          // 否则 PATCH 只改 party_id、名字还是旧的，打印出来就串了。
          party_name:
            (contractForm.contract_type === 'sales' ? customers : suppliers).find(
              (party) => String(party.id) === String(contractForm.party_id),
            )?.name || null,
          warehouse_id: num(contractForm.warehouse_id),
"""
assert text.count(OLD) == 1, text.count(OLD)
text = text.replace(OLD, NEW)
APP.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK party_name 快照已补")
