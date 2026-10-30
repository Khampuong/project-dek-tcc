"""ชุดทดสอบของระบบ — รันจากโฟลเดอร์โปรเจกต์:  python -m unittest discover -s tests -t . -v

ทุกการทดสอบใช้ฐานข้อมูลและโฟลเดอร์ชั่วคราว ไม่แตะ storage/ จริง และไม่เรียก AI หรืออินเทอร์เน็ต
"""
import atexit
import os
import shutil
import tempfile

# ต้องตั้งค่าก่อน import app.* เพราะ app.config อ่านตำแหน่ง storage ตอน import
_tmp = tempfile.mkdtemp(prefix="research-tests-")
os.environ["RESEARCH_STORAGE"] = _tmp
os.environ.pop("GEMINI_API_KEY", None)
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)
