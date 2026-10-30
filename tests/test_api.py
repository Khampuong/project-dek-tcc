"""API: บัญชีผู้ใช้ สิทธิ์ 3 บทบาท การป้องกันพื้นฐาน และข้อความเมื่อยังไม่ได้ตั้งค่า AI"""
import unittest

from app.config import project_dir

from .helpers import Client, admin, app, new_project, new_user, reset_login_throttle, settings_rows, wait_idle


class AccountTest(unittest.TestCase):
    def setUp(self):
        reset_login_throttle()

    def test_first_run_creates_admin(self):
        a = admin()
        self.assertEqual(a.get("/me").get_json()["user"]["role"], "admin")
        s = a.get("/admin/settings").get_json()
        self.assertFalse(s["has_key"])
        self.assertEqual(s["key_hint"], "")

    def test_state_changing_requests_need_app_header(self):
        r = app().test_client().post("/api/auth/login", json={"username": "admin", "password": "x"})
        self.assertEqual(r.status_code, 403)

    def test_anonymous_is_rejected(self):
        anon = Client()
        self.assertEqual(anon.get("/projects").status_code, 401)
        self.assertEqual(anon.get("/admin/users").status_code, 401)
        self.assertIsNone(anon.get("/me").get_json()["user"])

    def test_registration_rules(self):
        reg = lambda **d: Client().post("/auth/register", d)  # noqa: E731
        base = {"password": "password1", "full_name": "ทดสอบ", "role": "student", "level": "ปวส.", "group_name": "2/1"}
        for bad in ("ก ข", "somchai", "somchai@", "@school.ac.th", "a b@school.ac.th", "somchai@school", ""):
            r = reg(**base, username=bad)
            self.assertEqual(r.status_code, 400, bad)  # ชื่อผู้ใช้ต้องเป็นอีเมล
            self.assertIn("อีเมล", r.get_json()["error"])
        self.assertEqual(reg(**{**base, "password": "123"}, username="shortpw@school.ac.th").status_code, 400)
        self.assertEqual(reg(**{**base, "role": "admin"}, username="evil@school.ac.th").status_code, 400)
        self.assertEqual(reg(**{**base, "full_name": " "}, username="noname@school.ac.th").status_code, 400)
        self.assertEqual(reg(**base, username="Reg.Student@School.ac.th").get_json(), {"ok": True, "pending": False})
        self.assertEqual(reg(**base, username="REG.STUDENT@school.ac.th").status_code, 400)  # ซ้ำ (ไม่สนตัวพิมพ์)
        Client("reg.student@school.ac.th", "password1")
        Client("REG.Student@SCHOOL.ac.th", "password1")  # เข้าสู่ระบบโดยไม่สนตัวพิมพ์

    def test_student_registers_with_level_group_and_default_school(self):
        reg = lambda c, **d: c.post("/auth/register", {"password": "password1", "full_name": "นักเรียน ใหม่", "role": "student", **d})  # noqa: E731
        meta = Client().get("/meta").get_json()
        self.assertEqual((meta["levels"], meta["default_org"]), (["ปวช.", "ปวส."], "วิทยาลัยพณิชยการธนบุรี"))
        for missing in ({}, {"level": "ปวช."}, {"group_name": "1/2"}, {"level": "ป.ตรี", "group_name": "1"}, {"level": " ", "group_name": " "}):
            r = reg(Client(), username="class@school.ac.th", **missing)
            self.assertEqual(r.status_code, 400, missing)
            self.assertIn("ปวช.", r.get_json()["error"])
        c = Client()
        self.assertEqual(reg(c, username="class@school.ac.th", level="ปวช.", group_name="3/2 การบัญชี").status_code, 200)
        me = c.get("/me").get_json()["user"]
        self.assertEqual((me["username"], me["level"], me["group_name"], me["org"]),
                         ("class@school.ac.th", "ปวช.", "3/2 การบัญชี", "วิทยาลัยพณิชยการธนบุรี"))
        c2 = Client()
        reg(c2, username="other@school.ac.th", level="ปวส.", group_name="1/1", org="วิทยาลัยอื่น")
        self.assertEqual(c2.get("/me").get_json()["user"]["org"], "วิทยาลัยอื่น")
        row = next(u for u in admin().get("/admin/users").get_json()["users"] if u["username"] == "class@school.ac.th")
        self.assertEqual((row["level"], row["group_name"]), ("ปวช.", "3/2 การบัญชี"))

    def test_user_updates_own_profile(self):
        u, uid, name = new_user()  # ผู้ดูแลสร้างให้ ยังไม่มีระดับ/กลุ่ม
        self.assertEqual(u.post("/me/profile", {"full_name": "ชื่อใหม่", "level": "ปวส.", "group_name": ""}).status_code, 400)
        self.assertEqual(u.post("/me/profile", {"full_name": " ", "level": "ปวส.", "group_name": "1"}).status_code, 400)
        r = u.post("/me/profile", {"full_name": "ชื่อใหม่ นามสกุลใหม่", "level": "ปวส.", "group_name": "2/4", "org": "วิทยาลัยพณิชยการธนบุรี",
                                   "role": "admin", "username": "hacker@x.io", "status": "active"})
        self.assertEqual(r.status_code, 200)
        me = u.get("/me").get_json()["user"]
        self.assertEqual((me["full_name"], me["level"], me["group_name"], me["role"], me["username"]),
                         ("ชื่อใหม่ นามสกุลใหม่", "ปวส.", "2/4", "student", name))  # บทบาทและอีเมลเปลี่ยนเองไม่ได้
        t, _, _ = new_user("teacher")
        self.assertEqual(t.post("/me/profile", {"full_name": "ครู แก้ชื่อ", "level": "ปวช.", "group_name": "1"}).status_code, 200)
        self.assertEqual(t.get("/me").get_json()["user"]["level"], "")
        self.assertEqual(Client().post("/me/profile", {"full_name": "x"}).status_code, 401)

    def test_teacher_registers_without_level_or_group(self):
        c = Client()
        r = c.post("/auth/register", {"username": "kru@school.ac.th", "password": "password1", "full_name": "ครู ไม่มีกลุ่ม",
                                      "role": "teacher", "level": "ปวส.", "group_name": "9/9"})
        self.assertEqual(r.get_json(), {"ok": True, "pending": True})
        row = next(u for u in admin().get("/admin/users").get_json()["users"] if u["username"] == "kru@school.ac.th")
        self.assertEqual((row["level"], row["group_name"], row["org"]), ("", "", "วิทยาลัยพณิชยการธนบุรี"))  # ครูไม่มีระดับ/กลุ่ม

    def test_admin_account_and_admin_created_users(self):
        a = admin()  # บัญชี admin เดิม (ไม่ใช่อีเมล) ยังเข้าสู่ระบบได้
        self.assertEqual(a.get("/me").get_json()["user"]["username"], "admin")
        make = lambda **d: a.post("/admin/users", {"password": "password1", "full_name": "สร้างโดยผู้ดูแล", "role": "student", **d})  # noqa: E731
        self.assertEqual(make(username="notanemail").status_code, 400)
        self.assertEqual(make(username="made@school.ac.th").status_code, 200)  # ผู้ดูแลสร้างให้: ระดับ/กลุ่มเว้นไว้ได้
        self.assertEqual(make(username="made2@school.ac.th", level="มหาวิทยาลัย").status_code, 400)

    def test_teacher_needs_admin_approval(self):
        t = Client()
        r = t.post("/auth/register", {"username": "reg.teacher@school.ac.th", "password": "password1", "full_name": "ครูใหม่", "role": "teacher"})
        self.assertTrue(r.get_json()["pending"])
        login = lambda: Client().post("/auth/login", {"username": "reg.teacher@school.ac.th", "password": "password1"})  # noqa: E731
        self.assertEqual(login().status_code, 403)
        a = admin()
        users = a.get("/admin/users").get_json()["users"]
        self.assertIn("reg.teacher@school.ac.th", [u["username"] for u in users if u["status"] == "pending"])
        self.assertEqual(users[0]["status"], "pending")  # รออนุมัติแสดงก่อน
        users = [u for u in users if u["username"] == "reg.teacher@school.ac.th"]
        student, _, _ = new_user()
        self.assertNotIn("ครูใหม่", [t["full_name"] for t in student.get("/teachers").get_json()["teachers"]])
        self.assertEqual(student.patch(f"/admin/users/{users[0]['id']}", {"status": "active"}).status_code, 403)
        self.assertEqual(a.patch(f"/admin/users/{users[0]['id']}", {"status": "active"}).status_code, 200)
        self.assertEqual(login().status_code, 200)
        self.assertIn("ครูใหม่", [t["full_name"] for t in student.get("/teachers").get_json()["teachers"]])

    def test_registration_can_be_closed(self):
        a = admin()
        a.post("/admin/settings", {"allow_register": False})
        try:
            r = Client().post("/auth/register", {"username": "late@school.ac.th", "password": "password1", "full_name": "x", "role": "student", "level": "ปวช.", "group_name": "1"})
            self.assertEqual(r.status_code, 403)
        finally:
            a.post("/admin/settings", {"allow_register": True})

    def test_login_throttled_after_five_failures(self):
        c = Client()
        codes = [c.post("/auth/login", {"username": "ghost", "password": "wrong"}).status_code for _ in range(6)]
        self.assertEqual(codes, [401] * 5 + [429])

    def test_change_password(self):
        u, _, name = new_user()
        self.assertEqual(u.post("/me/password", {"old": "wrong", "new": "newpassword1"}).status_code, 400)
        self.assertEqual(u.post("/me/password", {"old": "password1", "new": "short"}).status_code, 400)
        self.assertEqual(u.post("/me/password", {"old": "password1", "new": "newpassword1"}).status_code, 200)
        self.assertEqual(Client().post("/auth/login", {"username": name, "password": "password1"}).status_code, 401)
        Client(name, "newpassword1")

    def test_admin_user_management(self):
        a = admin()
        me = a.get("/me").get_json()["user"]["id"]
        self.assertEqual(a.patch(f"/admin/users/{me}", {"role": "student"}).status_code, 400)
        self.assertEqual(a.delete(f"/admin/users/{me}").status_code, 400)
        u, uid, name = new_user()
        self.assertEqual(a.patch(f"/admin/users/{uid}", {"password": "resetpass9"}).status_code, 200)
        Client(name, "resetpass9")
        # ระงับบัญชี: เซสชันที่เปิดอยู่ใช้ต่อไม่ได้ทันที
        self.assertEqual(a.patch(f"/admin/users/{uid}", {"status": "disabled"}).status_code, 200)
        self.assertEqual(u.get("/projects").status_code, 401)
        self.assertEqual(Client().post("/auth/login", {"username": name, "password": "resetpass9"}).status_code, 403)
        self.assertEqual(a.delete(f"/admin/users/{uid}").status_code, 200)

    def test_user_with_projects_cannot_be_deleted(self):
        u, uid, _ = new_user()
        new_project(u)
        self.assertEqual(admin().delete(f"/admin/users/{uid}").status_code, 400)

    def test_settings_are_clamped_and_key_is_masked(self):
        a = admin()
        s = a.post("/admin/settings", {"ch2_parallel": 99, "min_interval": -5, "api_key": "AIzaSy-test-key-123456"}).get_json()
        try:
            self.assertEqual((s["ch2_parallel"], s["min_interval"]), (6, 0))
            self.assertTrue(s["has_key"])
            self.assertEqual(s["key_hint"], "AIza…3456")
            self.assertNotIn("test-key", a.get("/admin/settings").get_data(as_text=True))
        finally:
            a.post("/admin/settings", {"ch2_parallel": 1, "min_interval": 4, "clear_key": True})
        self.assertFalse(a.get("/admin/settings").get_json()["has_key"])

    def test_ai_test_button_without_key_explains(self):
        r = admin().post("/admin/settings/test")
        self.assertEqual(r.status_code, 400)
        self.assertIn("API key", r.get_json()["error"])


class ProjectPermissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner, cls.owner_id, _ = new_user(name="สมชาย เจ้าของงาน")
        cls.other, cls.other_id, _ = new_user()
        cls.advisor, cls.advisor_id, _ = new_user("teacher", "ครูสมศรี ที่ปรึกษา")
        cls.pid = new_project(cls.owner, advisor_id=cls.advisor_id)
        cls.P = f"/projects/{cls.pid}"

    def test_create_validation(self):
        bad = lambda **d: self.owner.post("/projects", {"kind": "student_project", "requirement": "x" * 30, "autostart": False, **d}).status_code  # noqa: E731
        self.assertEqual(bad(kind="zzz"), 400)
        self.assertEqual(bad(requirement="สั้นไป"), 400)
        self.assertEqual(bad(advisor_id=self.other_id), 400)  # นักเรียนเป็นที่ปรึกษาไม่ได้

    def test_each_role_creates_only_its_own_kind_of_work(self):
        make = lambda c, kind: c.post("/projects", {"kind": kind, "requirement": "x" * 30, "autostart": False})  # noqa: E731
        self.assertEqual(app().test_client().get("/api/meta").get_json()["role_kinds"],
                         {"student": ["student_project"], "teacher": ["classroom_research"],
                          "admin": ["student_project", "classroom_research", "research"]})
        # นักเรียน/นักศึกษา: โครงงานเท่านั้น
        self.assertEqual(make(self.owner, "student_project").status_code, 200)
        for kind in ("classroom_research", "research"):
            r = make(self.owner, kind)
            self.assertEqual(r.status_code, 403, kind)
            self.assertIn("โครงงาน", r.get_json()["error"])
        # ครู: วิจัยในชั้นเรียนเท่านั้น
        self.assertEqual(make(self.advisor, "classroom_research").status_code, 200)
        for kind in ("student_project", "research"):
            self.assertEqual(make(self.advisor, kind).status_code, 403, kind)
        for kind in ("student_project", "classroom_research", "research"):
            self.assertEqual(make(admin(), kind).status_code, 200, kind)

    def test_documents_differ_by_kind(self):
        """โครงงานมีแบบเสนอโครงงาน งานวิจัยของครูมีโครงร่าง 3 บทแทน และเข้าถึงเอกสารของอีกประเภทไม่ได้"""
        tid = new_project(self.advisor, kind="classroom_research")
        docs = lambda c, pid: [d["key"] for d in c.get(f"/projects/{pid}/status").get_json()["docs"]]  # noqa: E731
        step7 = lambda c, pid: c.get(f"/projects/{pid}/status").get_json()["steps"][-1]["label"]  # noqa: E731
        self.assertEqual(docs(self.owner, self.pid)[-1], "proposal")
        self.assertEqual(docs(self.advisor, tid), ["papers", "ch1", "ch2", "ch3", "ch4", "ref", "outline"])
        self.assertEqual(step7(self.owner, self.pid), "7) แบบเสนอโครงงาน และส่งออก Word + PDF")
        self.assertEqual(step7(self.advisor, tid), "7) โครงร่างงานวิจัย 3 บท และส่งออก Word + PDF")
        self.assertEqual(self.advisor.get(f"/projects/{tid}/doc/proposal").status_code, 404)
        self.assertEqual(self.advisor.get(f"/projects/{tid}/download/proposal.docx").status_code, 404)
        self.assertEqual(self.advisor.get(f"/projects/{tid}/doc/outline").status_code, 200)
        self.assertEqual(self.owner.get(f"{self.P}/doc/outline").status_code, 404)
        self.assertEqual(self.advisor.post(f"/projects/{tid}/doc/outline/block/0", {"block": ["p", "x"]}).status_code, 404)

    def test_stranger_sees_nothing(self):
        for path in ("", "/status", "/doc/ch1", "/papers", "/download-all", "/comments", "/download/ch1.docx"):
            self.assertEqual(self.other.get(self.P + path).status_code, 403, path)
        self.assertEqual(self.other.post(self.P + "/comments", {"text": "hi"}).status_code, 403)
        self.assertNotIn(self.pid, [p["id"] for p in self.other.get("/projects").get_json()["projects"]])

    def test_advisor_reads_and_comments_but_cannot_change(self):
        d = self.advisor.get(self.P).get_json()
        self.assertFalse(d["can_edit"])
        self.assertEqual(d["folder"], "")
        t = self.advisor
        codes = [t.post(self.P + "/run", {"from": "plan"}).status_code, t.patch(self.P, {"title_th": "x"}).status_code,
                 t.delete(self.P).status_code, t.post(self.P + "/papers/url", {"url": "https://example.org"}).status_code,
                 t.post(self.P + "/doc/ch1/undo").status_code, t.post(self.P + "/cancel").status_code,
                 t.post(self.P + "/doc/ch1/chat", {"message": "แก้"}).status_code,
                 t.post(self.P + "/doc/ch1/block/0", {"delete": True}).status_code]
        self.assertEqual(codes, [403] * 8)
        mine = [p for p in t.get("/projects").get_json()["projects"] if p["id"] == self.pid]
        self.assertEqual([(p["mine"], p["can_delete"]) for p in mine], [(False, False)])

    def test_comments_flow(self):
        self.assertEqual(self.advisor.post(self.P + "/comments", {"text": "  "}).status_code, 400)
        self.assertEqual(self.advisor.post(self.P + "/comments", {"text": "เพิ่มขอบเขตให้ชัด", "doc_key": "ch1"}).status_code, 200)
        c = self.owner.get(self.P + "/comments").get_json()["comments"][-1]
        self.assertEqual((c["full_name"], c["role"], c["doc_key"]), ("ครูสมศรี ที่ปรึกษา", "teacher", "ch1"))
        self.assertEqual(self.owner.delete(f"{self.P}/comments/{c['id']}").status_code, 403)
        self.assertEqual(self.advisor.delete(f"{self.P}/comments/{c['id']}").status_code, 200)

    def test_admin_sees_everything_but_edits_only_own_work(self):
        a = admin()
        self.assertIn(self.pid, [p["id"] for p in a.get("/projects").get_json()["projects"]])
        d = a.get(self.P).get_json()
        self.assertEqual((d["can_edit"], d["can_delete"]), (False, True))
        self.assertTrue(d["folder"])
        codes = [a.patch(self.P, {"title_th": "แก้โดยผู้ดูแล"}).status_code, a.post(self.P + "/run", {"from": "plan"}).status_code,
                 a.post(self.P + "/doc/ch1/undo").status_code, a.post(self.P + "/papers/url", {"url": "https://example.org"}).status_code]
        self.assertEqual(codes, [403] * 4)
        self.assertIn("เจ้าของงาน", a.patch(self.P, {"title_th": "x"}).get_json()["error"])
        self.assertEqual(a.post(self.P + "/comments", {"text": "ผู้ดูแลให้ความเห็นได้"}).status_code, 200)
        own = new_project(a)
        self.assertEqual(a.get(f"/projects/{own}").get_json()["can_edit"], True)
        self.assertEqual(a.patch(f"/projects/{own}", {"title_th": "งานของผู้ดูแลเอง"}).status_code, 200)

    def test_owner_returns_to_edit_own_work(self):
        """เจ้าของกลับมาแก้ข้อมูลงานเดิมได้ทุกอย่าง ส่วนผู้อื่นแก้ไม่ได้"""
        u, _, _ = new_user()
        pid = new_project(u, department="บัญชี")
        P = f"/projects/{pid}"
        d = u.get(P).get_json()
        self.assertEqual((d["can_edit"], d["can_delete"]), (True, True))
        req = {**d["project"]["requirement"], "requirement": "แก้ไขรายละเอียดโครงงานใหม่ให้ชัดเจนกว่าเดิม", "department": "การตลาด",
               "members": "นาย ก, 111111", "period": "พ.ย. ถึง ก.พ."}
        self.assertEqual(u.patch(P, {"requirement": req, "advisor_id": self.advisor_id}).status_code, 200)
        again = u.get(P).get_json()["project"]
        self.assertEqual((again["requirement"]["department"], again["requirement"]["members"], again["advisor_id"]),
                         ("การตลาด", "นาย ก, 111111", self.advisor_id))
        self.assertTrue(next(p for p in u.get("/projects").get_json()["projects"] if p["id"] == pid)["mine"])
        for other in (self.other, self.advisor, admin()):
            self.assertEqual(other.patch(P, {"requirement": {**req, "requirement": "ผู้อื่นพยายามแก้ไขข้อมูลของงานนี้"}}).status_code, 403)
        self.assertEqual(u.get(P).get_json()["project"]["requirement"]["requirement"], "แก้ไขรายละเอียดโครงงานใหม่ให้ชัดเจนกว่าเดิม")
        self.assertEqual(self.advisor.delete(P).status_code, 403)
        can = lambda c: next(p for p in c.get("/projects").get_json()["projects"] if p["id"] == pid)["can_delete"]  # noqa: E731
        self.assertEqual((can(u), can(admin())), (True, True))
        folder = project_dir(pid)
        self.assertTrue(folder.is_dir())
        self.assertEqual(admin().delete(P).status_code, 200)  # ผู้ดูแลระบบลบงานของผู้ใช้ได้ แต่แก้เนื้อหาไม่ได้
        self.assertFalse(folder.exists())  # ไฟล์ของงานถูกลบไปด้วย
        self.assertEqual(u.get(P).status_code, 404)
        self.assertNotIn(pid, [p["id"] for p in u.get("/projects").get_json()["projects"]])

    def test_documents_before_generation(self):
        o = self.owner
        self.assertEqual(o.get(self.P + "/doc/secret").status_code, 404)
        self.assertEqual(o.get(self.P + "/download/ch1.docx").status_code, 404)
        self.assertEqual(o.get(self.P + "/download/ch1.exe").status_code, 404)
        self.assertEqual(o.post(self.P + "/doc/proposal/block/0", {"block": ["p", "x"]}).status_code, 404)
        self.assertEqual(o.post(self.P + "/doc/ch1/block/0", {"block": ["p", "x"]}).status_code, 404)
        self.assertEqual(o.post(self.P + "/doc/ch1/undo").status_code, 400)
        self.assertEqual(o.post(self.P + "/doc/ch1/chat", {"message": "แก้"}).status_code, 400)
        docs = o.get(self.P + "/status").get_json()["docs"]
        self.assertEqual([d["available"] for d in docs], [False] * 7)
        self.assertEqual(docs[-1]["title"], "แบบเสนอโครงงาน")
        z = o.get(self.P + "/download-all")
        self.assertEqual(z.data[:2], b"PK")

    def test_paper_inputs_are_checked(self):
        import io

        o = self.owner
        r = o.post(self.P + "/papers/upload", data={"file": (io.BytesIO(b"not a pdf"), "a.pdf")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        for url in ("http://127.0.0.1:5000/api/meta", "http://localhost/", "file:///C:/Windows/win.ini",
                    "http://169.254.169.254/latest/meta-data/", "ftp://example.org/a.pdf", ""):
            self.assertEqual(o.post(self.P + "/papers/url", {"url": url}).status_code, 400, url)

    def test_owner_edits_requirement_and_advisor(self):
        u, _, _ = new_user()
        pid = new_project(u, advisor_id=self.advisor_id)
        self.assertEqual(u.patch(f"/projects/{pid}", {"requirement": {"requirement": "ก" * 30, "institution": "วิทยาลัยทดสอบ"}}).status_code, 200)
        self.assertEqual(u.get(f"/projects/{pid}").get_json()["project"]["requirement"]["institution"], "วิทยาลัยทดสอบ")
        self.assertEqual(u.patch(f"/projects/{pid}", {"requirement": {"requirement": "สั้น"}}).status_code, 400)
        self.assertEqual(self.advisor.get(f"/projects/{pid}").status_code, 200)
        self.assertEqual(u.patch(f"/projects/{pid}", {"advisor_id": None}).status_code, 200)
        self.assertEqual(self.advisor.get(f"/projects/{pid}").status_code, 403)


class NoKeyAndDeleteTest(unittest.TestCase):
    def test_pipeline_without_key_fails_with_guidance_then_delete_cleans_up(self):
        u, _, _ = new_user()
        r = u.post("/projects", {"kind": "student_project", "requirement": "โครงงานสิ่งประดิษฐ์ ถังขยะคัดแยกอัตโนมัติด้วยเซนเซอร์ในโรงเรียน"})
        pid = r.get_json()["id"]  # autostart
        st = wait_idle(u, pid)
        steps = {s["key"]: s for s in st["steps"]}
        self.assertEqual(steps["plan"]["status"], "error")
        self.assertIn("API key", steps["plan"]["msg"])
        self.assertEqual({s["status"] for k, s in steps.items() if k != "plan"}, {"pending"})
        self.assertIn("error", [l["level"] for l in st["logs"]])

        # ขั้นเขียนบทต้องบอกว่าต้องทำขั้นแรกก่อน
        self.assertEqual(u.post(f"/projects/{pid}/run", {"steps": ["ch1"]}).status_code, 200)
        ch1 = {s["key"]: s for s in wait_idle(u, pid)["steps"]}["ch1"]
        self.assertEqual(ch1["status"], "error")
        self.assertIn("requirement", ch1["msg"])
        self.assertEqual(u.post(f"/projects/{pid}/run", {"steps": ["hack"]}).status_code, 400)

        folder = project_dir(pid)
        self.assertEqual(len([d for d in folder.iterdir() if d.is_dir()]), 7)
        self.assertEqual(u.delete(f"/projects/{pid}").status_code, 200)
        self.assertFalse(folder.exists())
        self.assertEqual(u.get(f"/projects/{pid}").status_code, 404)
        self.assertEqual(settings_rows(f"refs_sig:{pid}:"), [])


if __name__ == "__main__":
    unittest.main()
