"""ตัวช่วยของชุดทดสอบ: แอป Flask บน storage ชั่วคราว และไคลเอนต์ที่แนบส่วนหัวของหน้าเว็บ"""
import re
import time

from app import db
from app.config import STORAGE
from app.server import _fails, create_app

HEADERS = {"X-Requested-With": "research-app"}
_app = None
ADMIN_PASSWORD = None


def app():
    global _app, ADMIN_PASSWORD
    if _app is None:
        _app = create_app()
        _app.testing = True
        ADMIN_PASSWORD = re.search(r"password: (\S+)", (STORAGE / "initial_admin.txt").read_text(encoding="utf-8")).group(1)
    return _app


class Client:
    """ผู้ใช้หนึ่งคน (คุกกี้แยกกัน)"""

    def __init__(self, username=None, password=None):
        self.c = app().test_client()
        if username:
            r = self.post("/auth/login", {"username": username, "password": password})
            assert r.status_code == 200, r.get_json()

    def get(self, path):
        return self.c.get("/api" + path)

    def post(self, path, json=None, **kw):
        return self.c.post("/api" + path, json=json if json is not None or kw else {}, headers=HEADERS, **kw)

    def patch(self, path, json):
        return self.c.patch("/api" + path, json=json, headers=HEADERS)

    def delete(self, path):
        return self.c.delete("/api" + path, headers=HEADERS)


def admin() -> Client:
    app()
    return Client("admin", ADMIN_PASSWORD)


_seq = 0


def new_user(role="student", name=None) -> tuple[Client, int, str]:
    """สร้างผู้ใช้ที่ใช้งานได้ทันที คืน (ไคลเอนต์ที่เข้าสู่ระบบแล้ว, id, ชื่อผู้ใช้)"""
    global _seq
    _seq += 1
    username = f"{role}{_seq}@test.example"
    r = admin().post("/admin/users", {"username": username, "password": "password1",
                                       "full_name": name or f"ผู้ใช้ ทดสอบ{_seq}", "role": role})
    assert r.status_code == 200, r.get_json()
    return Client(username, "password1"), r.get_json()["id"], username


def wait_idle(client: Client, pid: int, timeout: float = 10) -> dict:
    end = time.time() + timeout
    while True:
        st = client.get(f"/projects/{pid}/status").get_json()
        if not st["running"] or time.time() > end:
            return st
        time.sleep(0.05)


def reset_login_throttle():
    _fails.clear()


REQUIREMENT = ("วิจัยในชั้นเรียนเพื่อพัฒนาผลสัมฤทธิ์ทางการเรียนของนักเรียนโดยใช้การเรียนรู้แบบโครงงานเป็นฐาน "
               "เปรียบเทียบคะแนนก่อนเรียนและหลังเรียน และศึกษาความพึงพอใจ")


def new_project(client: Client, kind: str = "student_project", **extra) -> int:
    r = client.post("/projects", {"kind": kind, "requirement": REQUIREMENT, "autostart": False, **extra})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["id"]


def settings_rows(prefix: str) -> list:
    return db.q("SELECT key FROM settings WHERE key LIKE ?", (prefix + "%",))
