"""เว็บเซิร์ฟเวอร์ของระบบจัดทำงานวิจัย (Flask): ผู้ใช้ 3 บทบาท โครงการ ขั้นตอนอัตโนมัติ การแก้ไข และการดาวน์โหลด"""
from __future__ import annotations

import re
import shutil
import time
from functools import wraps

from flask import Flask, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, editor, llm, papers as paperlib, pipeline, refs, store
from .config import (ALL_DOCS, DEFAULT_INSTITUTION, EDITABLE, KINDS, LEVELS, MIN_PAPERS, ROLE_KINDS, ROLES, STEP_KEYS,
                     STEPS, WEB_DIR, docs_for, doc_title, project_dir, step_label)

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
app.config.update(MAX_CONTENT_LENGTH=30 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7)
_fails: dict[str, list[float]] = {}


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify({"ok": False, "error": str(e)}), e.code


@app.errorhandler(pipeline.StepError)
@app.errorhandler(llm.LLMError)
def _step_error(e):
    return jsonify({"ok": False, "error": str(e)}), 400


@app.errorhandler(500)
def _server_error(_e):
    return jsonify({"ok": False, "error": "เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่"}), 500


@app.errorhandler(404)
def _not_found(_e):
    return jsonify({"ok": False, "error": "ไม่พบข้อมูล"}), 404


@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"ok": False, "error": "ไฟล์ใหญ่เกิน 30 MB"}), 413


@app.before_request
def _guard():
    g.user = None
    uid = session.get("uid")
    if uid:
        u = db.q1("SELECT id, username, full_name, role, status, org, level, group_name FROM users WHERE id=?", (uid,))
        if u and u["status"] == "active":
            g.user = u
        else:
            session.clear()
    # คำขอที่เปลี่ยนข้อมูลต้องมาจากหน้าเว็บของระบบเอง (กัน CSRF)
    if request.method not in ("GET", "HEAD") and request.path.startswith("/api/") \
            and request.headers.get("X-Requested-With") != "research-app":
        raise ApiError("คำขอไม่ถูกต้อง", 403)


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                raise ApiError("กรุณาเข้าสู่ระบบ", 401)
            if roles and g.user["role"] not in roles:
                raise ApiError("ไม่มีสิทธิ์ใช้งานส่วนนี้", 403)
            return fn(*a, **kw)
        return wrapper
    return deco


def body() -> dict:
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def get_project(pid: int, write: bool = False, manage: bool = False) -> dict:
    """โหลดโครงการพร้อมตรวจสิทธิ์

    ดู/ให้ความเห็น: เจ้าของ ครูที่ปรึกษา ผู้ดูแลระบบ
    แก้ไข (write): เจ้าของงานเท่านั้น — ผู้ดูแลระบบก็แก้งานของผู้อื่นไม่ได้
    ลบ (manage): เจ้าของงาน หรือผู้ดูแลระบบ
    """
    p = store.project(pid)
    if not p:
        raise ApiError("ไม่พบโครงการ", 404)
    u = g.user
    owner, admin, advisor = p["owner_id"] == u["id"], u["role"] == "admin", p["advisor_id"] == u["id"]
    if not (owner or admin or advisor):
        raise ApiError("ไม่มีสิทธิ์เข้าถึงโครงการนี้", 403)
    if (manage and not (owner or admin)) or (write and not manage and not owner):
        raise ApiError("แก้ไขได้เฉพาะเจ้าของงานเท่านั้น", 403)
    return p


def _idle(pid: int):
    if pipeline.is_running(pid):
        raise ApiError("ระบบกำลังทำงานกับโครงการนี้อยู่ กรุณารอให้เสร็จหรือกดยกเลิกก่อน", 409)


# ------------------------------------------------------------------ หน้าเว็บ
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/meta")
def meta():
    return jsonify({"kinds": {k: v["label"] for k, v in KINDS.items()}, "roles": ROLES, "role_kinds": ROLE_KINDS,
                    "steps": [{"key": k, "label": v} for k, v in STEPS], "min_papers": MIN_PAPERS,
                    "allow_register": db.get_setting("allow_register", "1") == "1", "levels": LEVELS,
                    "default_org": db.get_setting("form_institution") or DEFAULT_INSTITUTION})


# ------------------------------------------------------------------ บัญชีผู้ใช้
def _check_password(pw: str):
    if len(pw or "") < 8:
        raise ApiError("รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร")


def _check_username(name: str) -> str:
    """ชื่อผู้ใช้คืออีเมล (เก็บเป็นตัวพิมพ์เล็ก)"""
    name = (name or "").strip().lower()
    if len(name) > 100 or not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+", name):
        raise ApiError("กรุณากรอกอีเมลให้ถูกต้องเพื่อใช้เป็นชื่อผู้ใช้ เช่น name@example.com")
    return name


def _create_user(d: dict, role: str, status: str, need_class: bool = False) -> int:
    """need_class: นักเรียน/นักศึกษาที่สมัครเองต้องระบุระดับ (ปวช./ปวส.) และกลุ่ม"""
    username = _check_username(d.get("username"))
    _check_password(d.get("password"))
    full_name = (d.get("full_name") or "").strip()
    if not full_name:
        raise ApiError("กรุณากรอกชื่อ-สกุล")
    level, group = "", ""
    if role == "student":
        level, group = (d.get("level") or "").strip(), (d.get("group_name") or "").strip()[:60]
        if level and level not in LEVELS:
            raise ApiError("กรุณาเลือกระดับ ปวช. หรือ ปวส.")
        if need_class and not (level and group):
            raise ApiError("นักเรียน/นักศึกษากรุณาเลือกระดับ (ปวช./ปวส.) และกรอกกลุ่ม")
    if db.q1("SELECT id FROM users WHERE username=?", (username,)):
        raise ApiError("อีเมลนี้ถูกใช้สมัครแล้ว")
    org = (d.get("org") or "").strip()[:200] or db.get_setting("form_institution") or DEFAULT_INSTITUTION
    return db.x("""INSERT INTO users(username,password_hash,full_name,role,status,org,level,group_name,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (username, generate_password_hash(d["password"]), full_name, role, status, org, level, group, db.now()))


@app.post("/api/auth/register")
def register():
    if db.get_setting("allow_register", "1") != "1":
        raise ApiError("ระบบปิดการสมัครสมาชิก กรุณาติดต่อผู้ดูแลระบบ", 403)
    d = body()
    role = d.get("role")
    if role not in ("student", "teacher"):
        raise ApiError("กรุณาเลือกประเภทผู้ใช้")
    # ครูต้องให้ผู้ดูแลระบบอนุมัติก่อน เพราะเห็นงานของนักเรียนที่เลือกเป็นที่ปรึกษาได้
    status = "pending" if role == "teacher" else "active"
    uid = _create_user(d, role, status, need_class=True)
    if status == "active":
        session.clear()
        session["uid"] = uid
        session.permanent = True
    return jsonify({"ok": True, "pending": status == "pending"})


@app.post("/api/auth/login")
def login():
    d = body()
    username = (d.get("username") or "").strip()
    key = f"{request.remote_addr}|{username.lower()}"
    recent = [t for t in _fails.get(key, []) if time.time() - t < 300]
    if len(recent) >= 5:
        raise ApiError("พยายามเข้าสู่ระบบผิดหลายครั้ง กรุณารอ 5 นาที", 429)
    u = db.q1("SELECT * FROM users WHERE username=?", (username,))
    if not u or not check_password_hash(u["password_hash"], d.get("password") or ""):
        _fails[key] = recent + [time.time()]
        raise ApiError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", 401)
    if u["status"] == "pending":
        raise ApiError("บัญชีนี้รอผู้ดูแลระบบอนุมัติ", 403)
    if u["status"] != "active":
        raise ApiError("บัญชีนี้ถูกระงับการใช้งาน", 403)
    _fails.pop(key, None)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    return jsonify({"ok": True})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    return jsonify({"user": g.user})


@app.post("/api/me/password")
@login_required()
def change_password():
    d = body()
    u = db.q1("SELECT password_hash FROM users WHERE id=?", (g.user["id"],))
    if not check_password_hash(u["password_hash"], d.get("old") or ""):
        raise ApiError("รหัสผ่านเดิมไม่ถูกต้อง")
    _check_password(d.get("new"))
    db.x("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(d["new"]), g.user["id"]))
    return jsonify({"ok": True})


@app.post("/api/me/profile")
@login_required()
def update_profile():
    """แก้ข้อมูลของตนเอง (อีเมล/บทบาทเปลี่ยนเองไม่ได้)"""
    d, u = body(), g.user
    full_name = (d.get("full_name") or "").strip()[:120]
    if not full_name:
        raise ApiError("กรุณากรอกชื่อ-สกุล")
    level, group = "", ""
    if u["role"] == "student":
        level, group = (d.get("level") or "").strip(), (d.get("group_name") or "").strip()[:60]
        if level not in LEVELS or not group:
            raise ApiError("นักเรียน/นักศึกษากรุณาเลือกระดับ (ปวช./ปวส.) และกรอกกลุ่ม")
    db.x("UPDATE users SET full_name=?, org=?, level=?, group_name=? WHERE id=?",
         (full_name, (d.get("org") or "").strip()[:200], level, group, u["id"]))
    return jsonify({"ok": True})


@app.get("/api/teachers")
@login_required()
def teachers():
    return jsonify({"teachers": db.q("SELECT id, full_name, org FROM users WHERE role='teacher' AND status='active' "
                                     "ORDER BY full_name")})


# ------------------------------------------------------------------ โครงการ
def _advisor_id(value):
    if not value:
        return None
    t = db.q1("SELECT id FROM users WHERE id=? AND role='teacher' AND status='active'", (value,))
    if not t:
        raise ApiError("ไม่พบครูที่ปรึกษาที่เลือก")
    return t["id"]


def _requirement(d: dict) -> dict:
    req = {k: str(d.get(k) or "").strip()[:6000] for k in
           ("requirement", "title", "level", "subject", "institution", "problem", "innovation", "extra",
            "department", "members", "period")}
    if len(req["requirement"]) < 20:
        raise ApiError("กรุณาพิมพ์ requirement อธิบายงานที่ต้องการอย่างน้อย 20 ตัวอักษร")
    return req


@app.get("/api/projects")
@login_required()
def list_projects():
    u = g.user
    sql = """SELECT p.id, p.kind, p.title_th, p.requirement, p.steps, p.updated_at, p.owner_id, p.advisor_id,
                    o.full_name AS owner_name, o.role AS owner_role, a.full_name AS advisor_name
             FROM projects p JOIN users o ON o.id=p.owner_id LEFT JOIN users a ON a.id=p.advisor_id"""
    if u["role"] == "admin":
        rows = db.q(sql + " ORDER BY p.updated_at DESC")
    else:
        rows = db.q(sql + " WHERE p.owner_id=? OR p.advisor_id=? ORDER BY p.updated_at DESC", (u["id"], u["id"]))
    out = []
    for r in rows:
        steps = db.loads(r.pop("steps"), {})
        req = db.loads(r.pop("requirement"), {})
        r["title"] = r.pop("title_th") or req.get("title") or req.get("requirement", "")[:80]
        r["kind_label"] = KINDS.get(r["kind"], KINDS["research"])["label"]
        r["done"] = sum(1 for k in STEP_KEYS if steps.get(k, {}).get("status") == "done")
        r["total"] = len(STEP_KEYS)
        r["error"] = any(s.get("status") == "error" for s in steps.values())
        r["running"] = pipeline.is_running(r["id"])
        r["mine"] = r["owner_id"] == u["id"]
        r["can_delete"] = r["mine"] or u["role"] == "admin"
        out.append(r)
    return jsonify({"projects": out})


@app.post("/api/projects")
@login_required()
def create_project():
    d = body()
    if d.get("kind") not in KINDS:
        raise ApiError("กรุณาเลือกประเภทงาน")
    if d["kind"] not in ROLE_KINDS[g.user["role"]]:
        allowed = " หรือ ".join(KINDS[k]["label"] for k in ROLE_KINDS[g.user["role"]])
        raise ApiError(f"บัญชี{ROLES[g.user['role']]}สร้างได้เฉพาะ{allowed}", 403)
    req = _requirement(d)
    pid = db.x("INSERT INTO projects(owner_id,advisor_id,kind,requirement,created_at,updated_at) VALUES(?,?,?,?,?,?)",
               (g.user["id"], _advisor_id(d.get("advisor_id")), d["kind"], db.dumps(req), db.now(), db.now()))
    store.ensure_folders(pid)
    if d.get("autostart", True):
        pipeline.start(pid, STEP_KEYS)
    return jsonify({"ok": True, "id": pid})


def _status(p: dict, after: int = 0) -> dict:
    pid = p["id"]
    return {"running": pipeline.is_running(pid),
            "steps": [{"key": k, "label": step_label(p["kind"], k, label), **p["steps"].get(k, {"status": "pending", "msg": ""})}
                      for k, label in STEPS],
            "logs": db.q("SELECT id, ts, level, msg FROM logs WHERE project_id=? AND id>? ORDER BY id", (pid, after)),
            "title_th": p["title_th"], "title_en": p["title_en"], "updated_at": p["updated_at"],
            "docs": store.doc_list(p), "n_papers": len(db.q("SELECT id FROM papers WHERE project_id=?", (pid,)))}


@app.get("/api/projects/<int:pid>")
@login_required()
def project_detail(pid):
    p = get_project(pid)
    u = g.user
    return jsonify({"project": {k: p[k] for k in ("id", "kind", "title_th", "title_en", "requirement", "plan",
                                                    "owner_name", "advisor_name", "advisor_id", "created_at")},
                    "kind_label": KINDS.get(p["kind"], KINDS["research"])["label"],
                    "can_edit": p["owner_id"] == u["id"],
                    "can_delete": p["owner_id"] == u["id"] or u["role"] == "admin",
                    "folder": str(project_dir(pid)) if u["role"] == "admin" else "",
                    "status": _status(p)})


@app.get("/api/projects/<int:pid>/status")
@login_required()
def project_status(pid):
    return jsonify(_status(get_project(pid), request.args.get("after", 0, type=int)))


@app.patch("/api/projects/<int:pid>")
@login_required()
def update_project(pid):
    p = get_project(pid, write=True)
    _idle(pid)
    d = body()
    if "requirement" in d:
        db.x("UPDATE projects SET requirement=? WHERE id=?", (db.dumps(_requirement(d["requirement"])), pid))
    for k in ("title_th", "title_en"):
        if k in d:
            db.x(f"UPDATE projects SET {k}=? WHERE id=?", (str(d[k]).strip()[:500], pid))
    if "plan" in d and isinstance(d["plan"], dict):
        plan = {**p["plan"], **d["plan"]}
        db.x("UPDATE projects SET plan=? WHERE id=?", (db.dumps(plan), pid))
    if "advisor_id" in d:
        db.x("UPDATE projects SET advisor_id=? WHERE id=?", (_advisor_id(d["advisor_id"]), pid))
    db.x("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))
    return jsonify({"ok": True})


@app.delete("/api/projects/<int:pid>")
@login_required()
def delete_project(pid):
    get_project(pid, manage=True)
    _idle(pid)
    db.x("DELETE FROM projects WHERE id=?", (pid,))
    db.x("DELETE FROM settings WHERE key LIKE ?", (f"refs_sig:{pid}:%",))
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    return jsonify({"ok": True})


@app.post("/api/projects/<int:pid>/run")
@login_required()
def run_steps(pid):
    get_project(pid, write=True)
    d = body()
    steps = d.get("steps")
    if d.get("from") in STEP_KEYS:
        steps = STEP_KEYS[STEP_KEYS.index(d["from"]):]
    if not isinstance(steps, list) or not [s for s in steps if s in STEP_KEYS]:
        raise ApiError("ไม่ได้ระบุขั้นตอน")
    if not pipeline.start(pid, steps):
        raise ApiError("ระบบกำลังทำงานกับโครงการนี้อยู่", 409)
    return jsonify({"ok": True})


@app.post("/api/projects/<int:pid>/cancel")
@login_required()
def cancel_run(pid):
    get_project(pid, write=True)
    pipeline.cancel(pid)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ งานวิจัยที่เกี่ยวข้อง
def _paper_view(r: dict) -> dict:
    return {"id": r["id"], "rkey": r["rkey"], "file": r["file"], "url": r["url"], "source": r["source"],
            "apa": r["apa"], "cite": r["cite"], "title": r["meta"].get("title", ""), "lang": r["meta"].get("lang"),
            "summary": r["summary"]}


@app.get("/api/projects/<int:pid>/papers")
@login_required()
def list_papers(pid):
    get_project(pid)
    return jsonify({"papers": [_paper_view(r) for r in store.papers(pid)]})


def _add_paper(pid: int, pdf: bytes, url: str, hint: dict, source: str):
    p = store.project(pid)
    if not p["title_th"]:
        raise ApiError("กรุณารอให้ระบบวิเคราะห์ requirement (ขั้นตอนแรก) เสร็จก่อนเพิ่มงานวิจัย")
    r = pipeline.analyze_and_add(pid, p, pdf, url, hint, source, min_relevance=1)
    store.build(store.project(pid), ["papers", "ref"])
    return jsonify({"ok": True, "file": r["file"]})


@app.post("/api/projects/<int:pid>/papers/upload")
@login_required()
def upload_paper(pid):
    get_project(pid, write=True)
    _idle(pid)
    f = request.files.get("file")
    data = f.read() if f else b""
    if data[:4] != b"%PDF":
        raise ApiError("กรุณาเลือกไฟล์ PDF")
    return _add_paper(pid, data, "", {}, "อัปโหลด")


@app.post("/api/projects/<int:pid>/papers/url")
@login_required()
def add_paper_url(pid):
    get_project(pid, write=True)
    _idle(pid)
    url = (body().get("url") or "").strip()
    try:
        got = paperlib.fetch_paper({"url": url, "pdf_url": "", "hint": {}})
    except ValueError as e:
        raise ApiError(str(e)) from e
    if not got:
        raise ApiError("ไม่พบไฟล์ PDF จากลิงก์นี้ (ลองดาวน์โหลดเองแล้วใช้ปุ่มอัปโหลด)")
    return _add_paper(pid, got["pdf"], got["url"], got["hint"], "ลิงก์")


def _paper_row(pid: int, paper_id: int) -> dict:
    r = db.q1("SELECT * FROM papers WHERE id=? AND project_id=?", (paper_id, pid))
    if not r:
        raise ApiError("ไม่พบงานวิจัย", 404)
    return r


@app.delete("/api/projects/<int:pid>/papers/<int:paper_id>")
@login_required()
def delete_paper(pid, paper_id):
    p = get_project(pid, write=True)
    _idle(pid)
    r = _paper_row(pid, paper_id)
    folder = store.papers_dir(pid)
    (folder / r["file"]).unlink(missing_ok=True)
    (folder / "_text" / (r["file"][:-4] + ".txt")).unlink(missing_ok=True)
    db.x("DELETE FROM papers WHERE id=?", (paper_id,))
    store.build(p, ["papers", "ref"])
    return jsonify({"ok": True})


@app.get("/api/projects/<int:pid>/papers/<int:paper_id>/file")
@login_required()
def paper_file(pid, paper_id):
    get_project(pid)
    r = _paper_row(pid, paper_id)
    path = store.papers_dir(pid) / r["file"]
    if not path.is_file():
        raise ApiError("ไม่พบไฟล์", 404)
    return send_file(path, mimetype="application/pdf", download_name=r["file"])


# ------------------------------------------------------------------ เอกสาร
def _doc_key(key: str, p: dict, editable: bool = False) -> str:
    """ตรวจว่าเป็นเอกสารของงานประเภทนี้ (เช่น งานวิจัยของครูไม่มีแบบเสนอโครงงาน)"""
    if key not in docs_for(p["kind"]) or (editable and key not in EDITABLE):
        raise ApiError("เอกสารนี้สร้างอัตโนมัติจากบทอื่น กรุณาเลือกบทที่ 1–4 เพื่อแก้ไข" if editable else "ไม่พบเอกสาร", 404)
    return key


@app.get("/api/projects/<int:pid>/doc/<key>")
@login_required()
def get_doc(pid, key):
    p = get_project(pid)
    _doc_key(key, p)
    return jsonify({"title": doc_title(p["kind"], key), "blocks": store.blocks_for(p, key),
                    "editable": key in EDITABLE,
                    "history": store.history(pid, key) if key in EDITABLE else []})


@app.post("/api/projects/<int:pid>/doc/<key>/block/<int:idx>")
@login_required()
def edit_block(pid, key, idx):
    """แก้ไขหรือลบบล็อกโดยตรงจากหน้าตัวอย่าง"""
    p = get_project(pid, write=True)
    _doc_key(key, p, editable=True)
    _idle(pid)
    blocks = store.load_blocks(pid, key)
    if not 0 <= idx < len(blocks):
        raise ApiError("ไม่พบย่อหน้าที่ต้องการแก้ไข", 404)
    d = body()
    if d.get("delete"):
        blocks.pop(idx)
        note = "ลบย่อหน้าด้วยตนเอง"
    else:
        new = store.sanitize_blocks([d.get("block")])
        if not new:
            raise ApiError("เนื้อหาไม่ถูกต้อง")
        blocks[idx] = new[0]
        note = "แก้ไขด้วยตนเอง"
    store.save_blocks(pid, key, blocks, note=note)
    store.build(p, [key])
    return jsonify({"ok": True})


@app.post("/api/projects/<int:pid>/doc/<key>/chat")
@login_required()
def chat(pid, key):
    p = get_project(pid, write=True)
    _doc_key(key, p, editable=True)
    _idle(pid)
    d = body()
    msg = (d.get("message") or "").strip()
    if not msg:
        raise ApiError("กรุณาพิมพ์หรือพูดคำสั่ง")
    blocks = store.load_blocks(pid, key)
    if not blocks:
        raise ApiError("เอกสารนี้ยังไม่ได้สร้าง")
    result = editor.ask(p, doc_title(p["kind"], key), blocks, msg[:4000], d.get("history"))
    changed = []
    if result["ops"]:
        new_blocks, changed = editor.apply_ops(blocks, result["ops"])
        # ตรวจเฉพาะส่วนที่ AI เพิ่งเขียน: การอ้างอิงที่ไม่อยู่ในรายการงานวิจัยถูกแทนด้วยช่องให้เติมเอง
        new_blocks = refs.guard_blocks(new_blocks, store.refs_map(pid), only=set(changed))
        if changed or len(new_blocks) != len(blocks):
            store.save_blocks(pid, key, new_blocks, note=msg[:200])
            store.build(p, [key])
    return jsonify({"ok": True, "reply": result["reply"], "changed": changed})


@app.post("/api/projects/<int:pid>/doc/<key>/undo")
@login_required()
def undo(pid, key):
    p = get_project(pid, write=True)
    _doc_key(key, p, editable=True)
    _idle(pid)
    if not store.undo(pid, key):
        raise ApiError("ไม่มีประวัติให้ย้อนกลับ")
    store.build(p, [key])
    return jsonify({"ok": True})


@app.get("/api/projects/<int:pid>/download/<key>.<ext>")
@login_required()
def download(pid, key, ext):
    p = get_project(pid)
    _doc_key(key, p)
    if ext not in ("docx", "pdf"):
        raise ApiError("รูปแบบไฟล์ไม่ถูกต้อง", 404)
    try:
        path = store.ensure_file(p, key, ext)
    except FileNotFoundError as e:
        raise ApiError(str(e), 404) from e
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"สร้างไฟล์ไม่สำเร็จ: {e}", 500) from e
    return send_file(path, as_attachment=True, download_name=path.name)


@app.get("/api/projects/<int:pid>/download-all")
@login_required()
def download_all(pid):
    p = get_project(pid)
    name = re.sub(r'[\\/:*?"<>|]+', " ", p["title_th"] or f"project-{pid}")[:80].strip()
    return send_file(store.zip_project(p), as_attachment=True, download_name=f"{name}.zip", mimetype="application/zip")


# ------------------------------------------------------------------ ความคิดเห็น
@app.get("/api/projects/<int:pid>/comments")
@login_required()
def list_comments(pid):
    get_project(pid)
    return jsonify({"comments": db.q(
        """SELECT c.id, c.doc_key, c.text, c.created_at, u.full_name, u.role, c.user_id
           FROM comments c JOIN users u ON u.id=c.user_id WHERE c.project_id=? ORDER BY c.id""", (pid,))})


@app.post("/api/projects/<int:pid>/comments")
@login_required()
def add_comment(pid):
    get_project(pid)
    d = body()
    text = (d.get("text") or "").strip()[:4000]
    if not text:
        raise ApiError("กรุณาพิมพ์ความคิดเห็น")
    key = d.get("doc_key") if d.get("doc_key") in ALL_DOCS else ""
    db.x("INSERT INTO comments(project_id,user_id,doc_key,text,created_at) VALUES(?,?,?,?,?)",
         (pid, g.user["id"], key, text, db.now()))
    return jsonify({"ok": True})


@app.delete("/api/projects/<int:pid>/comments/<int:cid>")
@login_required()
def delete_comment(pid, cid):
    get_project(pid)
    c = db.q1("SELECT user_id FROM comments WHERE id=? AND project_id=?", (cid, pid))
    if not c or (c["user_id"] != g.user["id"] and g.user["role"] != "admin"):
        raise ApiError("ลบความคิดเห็นนี้ไม่ได้", 403)
    db.x("DELETE FROM comments WHERE id=?", (cid,))
    return jsonify({"ok": True})


# ------------------------------------------------------------------ ผู้ดูแลระบบ
@app.get("/api/admin/users")
@login_required("admin")
def admin_users():
    return jsonify({"users": db.q(
        """SELECT u.id, u.username, u.full_name, u.role, u.status, u.org, u.level, u.group_name, u.created_at,
                  (SELECT COUNT(*) FROM projects p WHERE p.owner_id=u.id) AS n_projects
           FROM users u ORDER BY (u.status='pending') DESC, u.role, u.full_name""")})


@app.post("/api/admin/users")
@login_required("admin")
def admin_create_user():
    d = body()
    if d.get("role") not in ROLES:
        raise ApiError("กรุณาเลือกบทบาท")
    return jsonify({"ok": True, "id": _create_user(d, d["role"], "active")})


@app.patch("/api/admin/users/<int:uid>")
@login_required("admin")
def admin_update_user(uid):
    u = db.q1("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError("ไม่พบผู้ใช้", 404)
    d = body()
    role, status = d.get("role", u["role"]), d.get("status", u["status"])
    if role not in ROLES or status not in ("active", "pending", "disabled"):
        raise ApiError("ข้อมูลไม่ถูกต้อง")
    losing_admin = u["role"] == "admin" and u["status"] == "active" and (role != "admin" or status != "active")
    if losing_admin and uid == g.user["id"]:
        raise ApiError("ไม่สามารถลดสิทธิ์หรือระงับบัญชีของตนเองได้")
    db.x("UPDATE users SET role=?, status=?, full_name=?, org=? WHERE id=?",
         (role, status, (d.get("full_name") or u["full_name"]).strip(), d.get("org", u["org"]), uid))
    if d.get("password"):
        _check_password(d["password"])
        db.x("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(d["password"]), uid))
    return jsonify({"ok": True})


@app.delete("/api/admin/users/<int:uid>")
@login_required("admin")
def admin_delete_user(uid):
    if uid == g.user["id"]:
        raise ApiError("ไม่สามารถลบบัญชีของตนเองได้")
    if db.q1("SELECT id FROM projects WHERE owner_id=? LIMIT 1", (uid,)):
        raise ApiError("ผู้ใช้นี้มีโครงการอยู่ ให้ใช้การระงับบัญชีแทนการลบ")
    db.x("UPDATE projects SET advisor_id=NULL WHERE advisor_id=?", (uid,))
    db.x("DELETE FROM comments WHERE user_id=?", (uid,))
    db.x("DELETE FROM users WHERE id=?", (uid,))
    return jsonify({"ok": True})


@app.route("/api/admin/settings", methods=["GET", "POST"])
@login_required("admin")
def admin_settings():
    if request.method == "POST":
        d = body()
        if d.get("api_key") is not None and d["api_key"].strip():
            db.set_setting("gemini_api_key", d["api_key"].strip())
        if d.get("clear_key"):
            db.set_setting("gemini_api_key", "")
        if d.get("model"):
            db.set_setting("gemini_model", d["model"].strip())
        if d.get("fast_model"):
            db.set_setting("gemini_fast_model", d["fast_model"].strip())
        if "allow_register" in d:
            db.set_setting("allow_register", "1" if d["allow_register"] else "0")
        if isinstance(d.get("form"), dict):  # ค่าของสถานศึกษาสำหรับแบบเสนอโครงงาน
            for k in store.form_defaults():
                if k in d["form"]:
                    db.set_setting(f"form_{k}", str(d["form"][k] or "").strip()[:200])
        if d.get("ch2_parallel") is not None:
            try:
                db.set_setting("ch2_parallel", str(max(1, min(6, int(d["ch2_parallel"])))))
            except (TypeError, ValueError):
                pass
        if d.get("min_interval") is not None:
            try:
                db.set_setting("llm_min_interval", str(max(0.0, min(60.0, float(d["min_interval"])))))
            except (TypeError, ValueError):
                pass
    s = llm.get_settings()
    key = s["api_key"]
    return jsonify({"model": s["model"], "fast_model": s["fast_model"], "has_key": bool(key), "key_hint": (key[:4] + "…" + key[-4:]) if key else "",
                    "min_interval": s["min_interval"], "ch2_parallel": int(float(db.get_setting("ch2_parallel") or 1)),
                    "allow_register": db.get_setting("allow_register", "1") == "1", "form": store.form_defaults(),
                    "stats": {"users": db.q1("SELECT COUNT(*) n FROM users")["n"],
                              "projects": db.q1("SELECT COUNT(*) n FROM projects")["n"],
                              "papers": db.q1("SELECT COUNT(*) n FROM papers")["n"]}})


@app.post("/api/admin/settings/test")
@login_required("admin")
def admin_test_key():
    text, _ = llm.call("ตอบคำว่า พร้อมใช้งาน เท่านั้น", json_mode=False, retries=1, timeout=60)
    return jsonify({"ok": True, "reply": text.strip()[:100]})


def create_app():
    db.init()
    app.secret_key = db.get_setting("secret_key")
    return app
