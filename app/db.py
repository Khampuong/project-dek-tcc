"""ฐานข้อมูล SQLite: ผู้ใช้ โครงการ งานวิจัยที่เกี่ยวข้อง เอกสาร ความคิดเห็น การตั้งค่า"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time

from werkzeug.security import generate_password_hash

from .config import DB_PATH, STORAGE

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('student','teacher','admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending','disabled')),
  org TEXT DEFAULT '',
  level TEXT DEFAULT '',
  group_name TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL REFERENCES users(id),
  advisor_id INTEGER REFERENCES users(id),
  kind TEXT NOT NULL,
  title_th TEXT DEFAULT '',
  title_en TEXT DEFAULT '',
  requirement TEXT NOT NULL DEFAULT '{}',
  plan TEXT NOT NULL DEFAULT '{}',
  steps TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS papers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  rkey TEXT NOT NULL,
  file TEXT NOT NULL,
  url TEXT DEFAULT '',
  meta TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '{}',
  source TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS docs (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  blocks TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (project_id, key)
);
CREATE TABLE IF NOT EXISTS doc_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  blocks TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  msg TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  doc_key TEXT DEFAULT '',
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def q(sql: str, args=()) -> list[dict]:
    con = connect()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def q1(sql: str, args=()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def x(sql: str, args=()) -> int:
    con = connect()
    try:
        with con:
            return con.execute(sql, args).lastrowid
    finally:
        con.close()


def get_setting(key: str, default: str = "") -> str:
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value: str):
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except json.JSONDecodeError:
        return default


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def init():
    """สร้างตาราง และบัญชีผู้ดูแลระบบเริ่มต้น (ครั้งแรกเท่านั้น)"""
    STORAGE.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)
        # ฐานข้อมูลที่สร้างก่อนมีข้อมูลระดับ/กลุ่มของนักเรียน: เพิ่มคอลัมน์ให้
        have = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
        for col in ("level", "group_name"):
            if col not in have:
                con.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
        con.commit()
    finally:
        con.close()
    if not get_setting("secret_key"):
        set_setting("secret_key", secrets.token_hex(32))
    if not q1("SELECT id FROM users WHERE role='admin'"):
        pw = secrets.token_urlsafe(9)
        x("INSERT INTO users(username,password_hash,full_name,role,status,created_at) VALUES(?,?,?,?,?,?)",
          ("admin", generate_password_hash(pw), "ผู้ดูแลระบบ", "admin", "active", now()))
        note = STORAGE / "initial_admin.txt"
        note.write_text(f"username: admin\npassword: {pw}\n(เปลี่ยนรหัสผ่านหลังเข้าสู่ระบบครั้งแรก แล้วลบไฟล์นี้)\n",
                        encoding="utf-8")
        print(f"\n*** สร้างบัญชีผู้ดูแลระบบ: admin / {pw}  (บันทึกไว้ที่ {note}) ***\n")
    # งานที่ค้างสถานะ running จากการปิดเซิร์ฟเวอร์กลางคัน
    for p in q("SELECT id, steps FROM projects"):
        steps = loads(p["steps"], {})
        dirty = False
        for s in steps.values():
            if s.get("status") == "running":
                s.update(status="error", msg="เซิร์ฟเวอร์หยุดทำงานระหว่างดำเนินการ กรุณาสั่งทำใหม่")
                dirty = True
        if dirty:
            x("UPDATE projects SET steps=? WHERE id=?", (dumps(steps), p["id"]))
