"""生成一张税控码二维码图片，供打包版解析验证（测完可删）。"""
import qrcode

qr = qrcode.QRCode(box_size=8, border=4)
qr.add_data("01,31,,26612000000979180051,4875.00,20260525,,4C58")
qr.make(fit=True)
qr.make_image().save(r"E:\AI\ERP软件\test_invoices\sample_qr.png")
print("sample_qr.png 已生成")
