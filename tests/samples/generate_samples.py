import io
import zipfile

samples_dir = "."

with open(f"{samples_dir}/fake.csv", "wb") as f:
    f.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("xl/workbook.xml", "<workbook/>")
    zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
with open(f"{samples_dir}/fake.zip", "wb") as f:
    f.write(buf.getvalue())

with open(f"{samples_dir}/xxe.xml", "wb") as f:
    f.write(
        b"<?xml version=\"1.0\"?>"
        b"<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>"
        b"<root>&xxe;</root>"
    )

with open(f"{samples_dir}/corrupt.json", "wb") as f:
    f.write(b'{"valid": 1}\nTHIS IS GARBAGE\n{"also_valid": 2}')

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("bomb.bin", b"\x00" * (3 * 1024 * 1024))
with open(f"{samples_dir}/zipbomb.zip", "wb") as f:
    f.write(buf.getvalue())

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    info = zipfile.ZipInfo("../../etc/passwd")
    zf.writestr(info, "root:x:0:0")
with open(f"{samples_dir}/path_traversal.zip", "wb") as f:
    f.write(buf.getvalue())

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("word/document.xml", "<document/>")
    zf.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0fake vba")
    zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
with open(f"{samples_dir}/macro.docx", "wb") as f:
    f.write(buf.getvalue())

with open(f"{samples_dir}/pdf_js.pdf", "wb") as f:
    f.write(b"%PDF-1.4\n/JS (app.alert(1))\n%%EOF")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("word/document.xml", "<document/>")
    zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
with open(f"{samples_dir}/bom.docx", "wb") as f:
    f.write(b"\xef\xbb\xbf" + buf.getvalue())

print("All sample files created.")
