"""คลังข้อมูลโครงการ: เนื้อหาแต่ละบท (บล็อก JSON) ประวัติการแก้ไข และการสร้างไฟล์ Word/PDF ลงโฟลเดอร์"""
from __future__ import annotations

import hashlib
import io
import re
import threading
import zipfile

from . import db, refs
from .config import EDITABLE, FOLDERS, KINDS, docs_for, doc_path, doc_title, project_dir

_build_lock = threading.RLock()
TEXT_WIDTH_IN = 5.7


# ------------------------------------------------------------------ โครงการ / งานวิจัย
def project(pid: int) -> dict | None:
    p = db.q1("""SELECT p.*, o.full_name AS owner_name, o.role AS owner_role, o.org AS owner_org,
                        a.full_name AS advisor_name
                 FROM projects p JOIN users o ON o.id = p.owner_id LEFT JOIN users a ON a.id = p.advisor_id
                 WHERE p.id=?""", (pid,))
    if p:
        for k in ("requirement", "plan", "steps"):
            p[k] = db.loads(p[k], {})
    return p


def papers(pid: int) -> list[dict]:
    rows = db.q("SELECT * FROM papers WHERE project_id=? ORDER BY id", (pid,))
    for r in rows:
        r["meta"] = db.loads(r["meta"], {})
        r["summary"] = db.loads(r["summary"], {})
        r["apa"], r["cite"], r["narr"] = refs.apa(r["meta"]), refs.cite(r["meta"]), refs.narr(r["meta"])
    return rows


def refs_map(pid: int) -> dict[str, dict]:
    return {r["rkey"]: r["meta"] for r in papers(pid)}


def papers_dir(pid: int):
    d = project_dir(pid) / FOLDERS["papers"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_folders(pid: int):
    """สร้างโฟลเดอร์ผลลัพธ์เฉพาะเอกสารของงานประเภทนั้น"""
    kind = db.q1("SELECT kind FROM projects WHERE id=?", (pid,))["kind"]
    for key in docs_for(kind):
        (project_dir(pid) / FOLDERS[key]).mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ บล็อกเนื้อหา
_s = refs.clean_text


def sanitize_blocks(raw) -> list:
    """ตรวจและปรับรูปร่างบล็อกจาก AI/ผู้ใช้ ให้ตัวสร้าง Word ใช้ได้เสมอ"""
    out = []
    for b in raw if isinstance(raw, list) else []:
        if isinstance(b, dict):  # {"type": "p", "text": "..."}
            kind = b.get("type") or b.get("kind")
            b = [kind, b.get("spec") or b.get("table") or b] if kind == "table" else [kind, b.get("text", ""), b.get("level", 1)]
        if isinstance(b, str):
            b = ["p", b]
        if not isinstance(b, list) or not b or not isinstance(b[0], str):
            continue
        kind = b[0]
        if kind in ("h1", "h2", "hd", "p", "pn", "ref"):
            if len(b) > 1 and _s(b[1]).strip():
                out.append([kind, _s(b[1]).strip()])
        elif kind in ("title", "center"):
            if len(b) > 1:
                size = b[2] if len(b) > 2 and isinstance(b[2], (int, float)) and 10 <= b[2] <= 28 else None
                out.append([kind, _s(b[1])] + ([size] if size else []))
        elif kind == "chapter":
            if len(b) > 2:
                out.append(["chapter", _s(b[1]), _s(b[2])])
        elif kind == "item":
            if len(b) > 1 and _s(b[1]).strip():
                lv = b[2] if len(b) > 2 and b[2] in (1, 2, 3) else 1
                out.append(["item", _s(b[1]).strip(), lv])
        elif kind == "fill":
            n = b[1] if len(b) > 1 and isinstance(b[1], int) else 3
            out.append(["fill", max(1, min(15, n))])
        elif kind in ("pb", "blank"):
            out.append([kind])
        elif kind == "table" and len(b) > 1 and isinstance(b[1], dict):
            t = _table(b[1])
            if t:
                out.append(["table", t])
        elif kind == "gantt" and len(b) > 1 and isinstance(b[1], dict):
            g = _gantt(b[1])
            if g:
                out.append(["gantt", g])
        elif kind == "sign" and len(b) > 1 and isinstance(b[1], dict):
            rows = [[{"name": _s(c.get("name")).strip(), "role": _s(c.get("role")).strip()} if isinstance(c, dict)
                     else {"name": "", "role": ""} for c in (list(r) + [None, None])[:2]]
                    for r in b[1].get("rows") or [] if isinstance(r, list)]
            if rows:
                out.append(["sign", {"rows": rows}])
    return out


def _gantt(spec: dict) -> dict | None:
    months = [_s(m).strip() for m in spec.get("months") or [] if _s(m).strip()][:6]
    if not months:
        return None
    ncol = len(months) * 4
    weeks = spec.get("weeks")
    weeks = max(1, min(ncol, weeks)) if isinstance(weeks, int) else ncol
    rows = []
    for r in spec.get("rows") or []:
        if isinstance(r, list) and r and _s(r[0]).strip():
            try:
                start, end = int(r[1]), int(r[2])
            except (IndexError, TypeError, ValueError):
                start = end = 0  # ยังไม่กำหนดช่วง: ไม่แรเงา
            start, end = max(0, min(ncol, start)), max(0, min(ncol, end))
            rows.append([_s(r[0]).strip(), start, max(start, end)])
    return {"months": months, "weeks": weeks, "rows": rows, "label": _s(spec.get("label")).strip() or "กิจกรรม"}


def _table(spec: dict) -> dict | None:
    headers = [_s(h) for h in spec.get("headers") or []]
    if not headers:
        return None
    n = len(headers)
    rows = []
    for r in spec.get("rows") or []:
        if isinstance(r, list):
            r = [_s(c) for c in r][:n]
            rows.append(r + [""] * (n - len(r)))
    t = {"headers": headers, "rows": rows}
    if _s(spec.get("caption")).strip():
        t["caption"] = _s(spec["caption"]).strip()
    if _s(spec.get("note")).strip():
        t["note"] = _s(spec["note"]).strip()
    align = spec.get("align")
    if isinstance(align, list) and len(align) == n and all(a in ("left", "center") for a in align):
        t["align"] = align
    w = spec.get("widths")
    if isinstance(w, list) and len(w) == n and all(isinstance(i, (int, float)) and i > 0 for i in w):
        scale = min(1.0, TEXT_WIDTH_IN / sum(w))
        t["widths"] = [round(i * scale, 2) for i in w]
    else:
        t["widths"] = _auto_widths(headers, rows)
    size = spec.get("size")
    t["size"] = size if isinstance(size, int) and 10 <= size <= 16 else (12 if n >= 6 else 14)
    return t


def _auto_widths(headers, rows) -> list[float]:
    """กระจายความกว้างคอลัมน์ตามความยาวข้อความ"""
    plain = re.compile(r"[⟦⟧*!]|\[\[.*?\]\]")
    lens = []
    for i, h in enumerate(headers):
        cells = [h] + [r[i] for r in rows]
        longest = max(len(plain.sub("", c)) for c in cells)
        lens.append(min(45, max(4, longest)) ** 0.75)
    total = sum(lens)
    return [round(TEXT_WIDTH_IN * v / total, 2) for v in lens]


def renumber_tables(blocks: list, chapter: int) -> list:
    """เรียงเลขตารางใหม่เป็น ตารางที่ <บท>.<ลำดับ> และแก้ข้อความที่อ้างถึงให้ตรงกัน"""
    pat = re.compile(r"ตารางที่\s*([\d]+(?:[.\-–]\d+)*)")
    mapping, n = {}, 0
    for b in blocks:
        if b[0] == "table" and b[1].get("caption"):
            m = pat.match(b[1]["caption"])
            n += 1
            if m:
                mapping.setdefault(m.group(1), f"{chapter}.{n}")
            else:
                b[1]["caption"] = f"ตารางที่ {chapter}.{n} {b[1]['caption']}"
    if not mapping:
        return blocks

    def fix(v):
        if isinstance(v, str):
            return pat.sub(lambda m: f"ตารางที่ {mapping.get(m.group(1), m.group(1))}", v)
        if isinstance(v, list):
            return [fix(i) for i in v]
        if isinstance(v, dict):
            return {k: fix(i) for k, i in v.items()}
        return v

    return [fix(b) for b in blocks]


def renumber_headings(blocks: list, chapter: int) -> list:
    """เรียงเลขหัวข้อ (h1 = บท.ลำดับ, h2 = บท.ลำดับ.ย่อย) ให้ต่อเนื่อง แม้ AI ข้ามหรือนับเลขผิด"""
    h1_pat, h2_pat = re.compile(r"^\d+\.\d+\.?\s+"), re.compile(r"^\d+\.\d+\.\d+\.?\s+")
    n = m = 0
    for b in blocks:
        if b[0] == "h1" and h1_pat.match(b[1]) and not h2_pat.match(b[1]):
            n, m = n + 1, 0
            b[1] = h1_pat.sub(f"{chapter}.{n} ", b[1])
        elif b[0] == "h2" and h2_pat.match(b[1]) and n:
            m += 1
            b[1] = h2_pat.sub(f"{chapter}.{n}.{m} ", b[1])
    return blocks


def load_blocks(pid: int, key: str) -> list:
    r = db.q1("SELECT blocks FROM docs WHERE project_id=? AND key=?", (pid, key))
    return db.loads(r["blocks"], []) if r else []


def save_blocks(pid: int, key: str, blocks: list, note: str = ""):
    if key not in EDITABLE:
        raise ValueError("เอกสารนี้สร้างอัตโนมัติ แก้ไขโดยตรงไม่ได้")
    old = db.q1("SELECT blocks FROM docs WHERE project_id=? AND key=?", (pid, key))
    if old:
        db.x("INSERT INTO doc_history(project_id,key,blocks,note,created_at) VALUES(?,?,?,?,?)",
             (pid, key, old["blocks"], note, db.now()))
    db.x("""INSERT INTO docs(project_id,key,blocks,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(project_id,key) DO UPDATE SET blocks=excluded.blocks, updated_at=excluded.updated_at""",
         (pid, key, db.dumps(blocks), db.now()))
    db.x("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), pid))


def history(pid: int, key: str) -> list[dict]:
    return db.q("SELECT id, note, created_at FROM doc_history WHERE project_id=? AND key=? ORDER BY id DESC LIMIT 30",
                (pid, key))


def undo(pid: int, key: str) -> bool:
    last = db.q1("SELECT id, blocks FROM doc_history WHERE project_id=? AND key=? ORDER BY id DESC LIMIT 1", (pid, key))
    if not last:
        return False
    db.x("UPDATE docs SET blocks=?, updated_at=? WHERE project_id=? AND key=?", (last["blocks"], db.now(), pid, key))
    db.x("DELETE FROM doc_history WHERE id=?", (last["id"],))
    return True


# ------------------------------------------------------------------ เอกสารที่สร้างอัตโนมัติ
def bibliography_blocks(pid: int) -> list:
    rows = sorted(papers(pid), key=lambda r: refs.sort_key(r["meta"]))
    return [["title", "บรรณานุกรม", 20], ["blank"]] + [["ref", r["apa"]] for r in rows]


def papers_summary_blocks(p: dict) -> list:
    rows = papers(p["id"])
    plan = p.get("plan") or {}
    kws = "  ".join(f"“{k}”" for k in (plan.get("keywords_th") or []) + (plan.get("keywords_en") or []))
    b = [["title", "รายการงานวิจัยที่เกี่ยวข้อง (ไฟล์ฉบับเต็มอยู่ในโฟลเดอร์นี้)", 18],
         ["center", p["title_th"], 16], ["blank"],
         ["p", "สืบค้นงานวิจัยจากฐานข้อมูลวารสารไทย ThaiJO (TCI) และวารสารวิชาการแบบเปิด (Open Access) ผ่านดัชนี OpenAlex "
               + (f"ด้วยคำค้น {kws} " if kws else "")
               + f"ได้งานวิจัยที่เกี่ยวข้องและดาวน์โหลดไฟล์ฉบับเต็มจำนวน {len(rows)} เรื่อง ดังนี้"],
         ["table", {"caption": "ตารางที่ 1 รายการไฟล์งานวิจัยและการอ้างอิงแบบ APA",
                    "headers": ["ที่", "ชื่อไฟล์", "รายการอ้างอิง (APA 7th)"],
                    "rows": [[str(i), r["file"], r["apa"]] for i, r in enumerate(rows, 1)],
                    "widths": [0.4, 1.6, 3.7], "align": ["center", "left", "left"], "size": 12}],
         ["h1", "สรุปสาระสำคัญของงานวิจัยแต่ละเรื่อง"]]
    labels = (("วัตถุประสงค์", "objective"), ("กลุ่มตัวอย่าง", "sample"), ("วิธีดำเนินการวิจัย", "method"),
              ("เครื่องมือและสถิติ", "instruments"), ("ผลการวิจัย", "findings"))
    for i, r in enumerate(rows, 1):
        b.append(["pn", f"**{i}. {r['narr']}**  {r['meta'].get('title', '')}  (ไฟล์: {r['file']})"])
        for label, key in labels:
            if r["summary"].get(key):
                b.append(["item", f"**{label}:** {r['summary'][key]}", 1])
    return b


# แผนงานตามแบบฟอร์ม: (กิจกรรม, สัปดาห์เริ่ม, สัปดาห์สิ้นสุด) ภาคเรียนที่ 2 จำนวน 18 สัปดาห์
GANTT_MONTHS = ["ตุลาคม", "พฤศจิกายน", "ธันวาคม", "มกราคม", "กุมภาพันธ์"]
GANTT_ROWS = [["1. การวางแผน (Planning)", 1, 2], ["2. การเก็บรวบรวมข้อมูล", 1, 4], ["3. วิเคราะห์ (Requirement)", 1, 4],
              ["4. การออกแบบ (Design)", 4, 8], ["5. การพัฒนา", 6, 13], ["6. การทดสอบ", 14, 15], ["7. ประเมินผล", 16, 17]]
BLANK = "⟦…⟧"


def _lines(v) -> list[str]:
    """รายการข้อความจากคำตอบของ AI (รับทั้งลิสต์และข้อความหลายบรรทัด)"""
    items = v if isinstance(v, list) else str(v or "").split("\n")
    return [re.sub(r"^\s*(?:\d+(?:\.\d+)+|\d+[.)]|[-•])\s+", "", _s(i)).strip() for i in items if _s(i).strip()]


def form_defaults() -> dict:
    """ค่าของสถานศึกษาที่ผู้ดูแลระบบตั้งไว้สำหรับแบบเสนอโครงงาน"""
    return {k: db.get_setting(f"form_{k}") for k in ("institution", "department", "subject_teacher", "head", "deputy")}


def proposal_blocks(p: dict, data: dict) -> list:
    """ประกอบ "แบบเสนอโครงงาน" ตามแบบฟอร์มของสถานศึกษา จากข้อมูลงานและเนื้อหาที่ AI ร่าง (data)

    ข้อความใน data ยังมีโทเคนอ้างอิง [[R1]] ได้ ผู้เรียกเป็นผู้แปลงและตรวจการอ้างอิง
    """
    req, plan, org = p["requirement"], p.get("plan") or {}, form_defaults()
    dept = (req.get("department") or org["department"]).strip()
    dept = re.sub(r"^แผนกวิชา\s*", "", dept)
    place = (req.get("institution") or org["institution"] or p.get("owner_org") or "").strip() or BLANK
    # แต่ละบรรทัด: "ชื่อ-สกุล, เลขประจำตัว" (เลขประจำตัวไม่บังคับ)
    members = [list(re.match(r"(.*?)(?:[\s,|]+(\d[\d-]{3,}))?$", m.strip()).groups(""))
               for m in (req.get("members") or "").split("\n") if m.strip()]
    if not members:
        members = [[p["owner_name"]], [BLANK]]
    b = [["title", "แบบเสนอโครงงาน", 18], ["title", f"แผนกวิชา{dept or BLANK}", 18], ["blank"],
         ["pn", f"**ชื่อโครงงาน**   {p['title_th']}"], ["pn", "**ผู้รับผิดชอบโครงงาน**"]]
    b += [["item", f"{i}. {m[0]}   เลขประจำตัว {m[1] if len(m) > 1 and m[1] else BLANK}", 2] for i, m in enumerate(members, 1)]
    b += [["pn", f"**ระยะเวลาดำเนินการ**   {(req.get('period') or '').strip() or BLANK + ' ถึง ' + BLANK}"],
          ["pn", f"**พื้นที่ดำเนินการ**   {place}"]]

    b.append(["hd", "1. หลักการและเหตุผล"])
    b += [["p", t] for t in _lines(data.get("rationale"))] or [["p", BLANK], ["fill", 6]]

    b.append(["hd", "2. วัตถุประสงค์"])
    objectives = _lines(data.get("objectives")) or _lines(plan.get("objectives")) or [BLANK]
    b += [["item", f"2.{i} {t}", 1] for i, t in enumerate(objectives, 1)]

    b += [["hd", "3. ขอบเขตของโครงงาน"], ["item", "3.1 ขอบเขตด้านประชากรและกลุ่มตัวอย่าง", 1],
          ["item", f"3.1.1 {_s(data.get('experts')).strip() or 'ผู้เชี่ยวชาญด้านการพัฒนา ' + BLANK + ' จำนวน 3 คน'}", 2],
          ["item", f"3.1.2 ประชากร ได้แก่ {_s(data.get('population')).strip() or BLANK + ' จำนวน ' + BLANK + ' คน'}", 2],
          ["item", f"3.1.3 กลุ่มตัวอย่าง ได้แก่ {_s(data.get('sample')).strip() or BLANK + ' จำนวน ' + BLANK + ' คน'}", 2],
          ["item", "3.2 ขอบเขตด้านเนื้อหา", 1]]
    groups = [g for g in data.get("content_scope") or [] if isinstance(g, dict) and _s(g.get("title")).strip()] \
        or [{"title": BLANK, "items": [BLANK]}]
    for i, g in enumerate(groups, 1):
        b.append(["item", f"3.2.{i} {_s(g['title']).strip()}", 2])
        b += [["item", f"3.2.{i}.{j} {t}", 3] for j, t in enumerate(_lines(g.get("items")), 1)]
    b.append(["item", "3.3 ขอบเขตด้านซอฟต์แวร์", 1])
    b += [["item", f"3.3.{i} {t}", 2] for i, t in enumerate(_lines(data.get("software")) or [BLANK], 1)]

    b.append(["hd", "4. เป้าหมาย"])
    b.append(["item", f"**เชิงคุณภาพ**   {_s(data.get('goal_quality')).strip() or BLANK}", 2])
    quantity = _lines(data.get("goal_quantity")) or [BLANK]
    b.append(["item", f"**เชิงปริมาณ**   {quantity[0]}", 2])
    b += [["item", t, 3] for t in quantity[1:]]

    b += [["hd", "5. ขั้นตอนในการดำเนินโครงงาน"],
          ["gantt", {"months": list(GANTT_MONTHS), "weeks": 18, "rows": [list(r) for r in GANTT_ROWS]}]]

    b.append(["hd", "6. ค่าใช้จ่ายในการดำเนินโครงงาน"])
    b += [["item", f"6.{i} {t}   {BLANK} บาท", 1] for i, t in enumerate(_lines(data.get("budget")) or ["ค่า" + BLANK], 1)]

    b.append(["hd", "7. ประโยชน์ที่คาดว่าจะได้รับ"])
    b += [["item", f"7.{i} {t}", 1] for i, t in enumerate(_lines(data.get("benefits")) or [BLANK], 1)]

    b.append(["hd", "8. เอกสารอ้างอิง"])
    b += [x for x in bibliography_blocks(p["id"]) if x[0] == "ref"]

    people = [[m[0] if m[0] != BLANK else "", "ผู้จัดทำโครงงาน"] for m in members]
    people += [[p.get("advisor_name") or "", "ครูที่ปรึกษาหลัก"], [org["subject_teacher"], "ครูประจำวิชา"],
               [org["head"], f"หัวหน้าแผนกวิชา{dept}"], [org["deputy"], "รองผู้อำนวยการฝ่ายวิชาการ"]]
    if len(people) % 2:
        people.insert(len(members), ["", ""])  # จำนวนผู้จัดทำเป็นเลขคี่: เว้นช่องขวาให้แถวผู้ลงนามตรงกัน
    cells = [{"name": n, "role": r} for n, r in people]
    b += [["pb"], ["hd", "เสนอขออนุมัติโครงงาน"],
          ["sign", {"rows": [cells[i:i + 2] for i in range(0, len(cells), 2)]}]]
    return sanitize_blocks(b)


def cover_blocks(p: dict) -> list:
    """ปกของโครงร่างงานวิจัย 3 บท"""
    org = (p["requirement"].get("institution") or form_defaults()["institution"] or p.get("owner_org") or "").strip()
    b = [["blank"], ["blank"], ["title", "โครงร่างงานวิจัย", 24], ["blank"], ["title", p["title_th"], 20]]
    if p.get("title_en"):
        b.append(["title", p["title_en"], 18])
    b += [["blank"], ["blank"], ["center", f"ผู้วิจัย  {p['owner_name']}"], ["blank"],
          ["center", org or "⟦ชื่อสถานศึกษา⟧"], ["blank"], ["blank"], ["center", "ภาคเรียนที่ ⟦…⟧ ปีการศึกษา ⟦…⟧"], ["pb"]]
    return b


def generated_blocks(p: dict, key: str) -> list:
    pid = p["id"]
    if key == "papers":
        return papers_summary_blocks(p)
    if key == "ref":
        return bibliography_blocks(pid)
    if key == "outline":  # ปก + บทที่ 1-3 + บรรณานุกรม ประกอบจากเนื้อหาปัจจุบันทุกครั้ง
        out = cover_blocks(p)
        for ch in ("ch1", "ch2", "ch3"):
            out += load_blocks(pid, ch) + [["pb"]]
        return out + bibliography_blocks(pid)
    raise KeyError(key)


def blocks_for(p: dict, key: str) -> list:
    return load_blocks(p["id"], key) if key in EDITABLE else generated_blocks(p, key)


def available(p: dict, key: str) -> bool:
    """เอกสารพร้อมสร้างไฟล์หรือยัง"""
    pid = p["id"]
    if key not in docs_for(p["kind"]):
        return False
    if key in EDITABLE:
        return bool(load_blocks(pid, key))
    if key == "outline":
        return all(load_blocks(pid, ch) for ch in ("ch1", "ch2", "ch3"))
    return bool(db.q1("SELECT id FROM papers WHERE project_id=? LIMIT 1", (pid,)))


# ------------------------------------------------------------------ สร้างไฟล์
BUILD_VERSION = 2  # เพิ่มค่านี้เมื่อแก้รูปแบบเอกสารใน docbuilder เพื่อให้สร้างไฟล์ใหม่ทั้งหมด
MANIFEST = ".build.json"


def _digest(blocks: list) -> str:
    return hashlib.sha1(db.dumps([BUILD_VERSION, blocks]).encode("utf-8")).hexdigest()


def build(p: dict, keys, pdf: bool = False) -> list:
    """สร้างไฟล์ Word (และ PDF) ของเอกสารที่ระบุ ลงโฟลเดอร์ของแต่ละเอกสาร

    จำลายนิ้วมือของเนื้อหาที่ใช้สร้างแต่ละไฟล์ไว้ใน .build.json จึงสร้าง/แปลงใหม่เฉพาะเอกสารที่เนื้อหาเปลี่ยน
    (การแปลง PDF ด้วย Word เป็นส่วนที่ช้าที่สุดของการส่งออก)
    """
    from .docbuilder import add_words, build_docx, convert_to_pdf

    with _build_lock:
        mpath = project_dir(p["id"]) / MANIFEST
        man = db.loads(mpath.read_text(encoding="utf-8"), {}) if mpath.exists() else {}
        add_words(w for m in refs_map(p["id"]).values() for w in refs.author_words(m))
        paths, stale = [], []
        for k in keys:
            if not available(p, k):
                continue
            blocks = blocks_for(p, k)
            digest, path = _digest(blocks), doc_path(p["id"], p["kind"], k)
            entry = man.get(k) or {}
            if entry.get("docx") != digest or not path.exists():
                build_docx([tuple(b) for b in blocks], path)
                entry = {"docx": digest, "pdf": entry.get("pdf")}
            if pdf and (entry.get("pdf") != digest or not path.with_suffix(".pdf").exists()):
                stale.append((k, path, digest))
            man[k] = entry
            paths.append(path)

        def save():
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(db.dumps(man), encoding="utf-8")

        save()
        if stale:
            convert_to_pdf([path for _k, path, _d in stale])
            for k, _path, digest in stale:
                man[k]["pdf"] = digest
            save()
        return paths


def ensure_file(p: dict, key: str, ext: str):
    """คืนพาธไฟล์ที่เป็นปัจจุบันสำหรับดาวน์โหลด (สร้าง/แปลงใหม่เมื่อจำเป็น)"""
    if not available(p, key):
        raise FileNotFoundError("เอกสารนี้ยังไม่ได้สร้าง")
    docx = build(p, [key], pdf=(ext == "pdf"))[0]
    return docx if ext == "docx" else docx.with_suffix(".pdf")


def zip_project(p: dict) -> io.BytesIO:
    """รวมทุกโฟลเดอร์ของโครงการเป็นไฟล์ zip"""
    root = project_dir(p["id"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file() and not f.name.startswith(("~$", ".")) and "_text" not in f.parts:
                z.write(f, f.relative_to(root).as_posix())
    buf.seek(0)
    return buf


CITING = ("ch1", "ch2", "ch3", "proposal")  # เอกสารที่มีการอ้างอิงงานวิจัยในเนื้อหา


def refs_signature(pid: int) -> str:
    """ลายนิ้วมือของรายการงานวิจัยและรูปแบบการอ้างอิงปัจจุบัน"""
    return _digest(sorted(f"{r['rkey']}|{r['cite']}" for r in papers(pid)))


def mark_written(pid: int, key: str):
    """จำว่าบทนี้เขียนด้วยรายการงานวิจัยชุดใด เพื่อเตือนเมื่อรายการเปลี่ยนภายหลัง"""
    if key in CITING:
        db.set_setting(f"refs_sig:{pid}:{key}", refs_signature(pid))


def stale_chapters(pid: int) -> set[str]:
    """บทที่เขียนไว้ก่อนรายการงานวิจัยจะถูกเพิ่ม/ลบ/แก้ไข (การอ้างอิงในเนื้อหาอาจไม่ตรงกับรายการปัจจุบัน)"""
    now = refs_signature(pid)
    return {k for k in CITING if db.get_setting(f"refs_sig:{pid}:{k}", now) != now}


def doc_list(p: dict) -> list[dict]:
    stale = stale_chapters(p["id"])
    return [{"key": k, "title": doc_title(p["kind"], k), "folder": FOLDERS[k], "editable": k in EDITABLE,
             "available": available(p, k), "stale": k in stale} for k in docs_for(p["kind"])]


def chapter_heading(p: dict, key: str) -> list:
    return ["chapter", f"บทที่ {key[-1]}", KINDS.get(p["kind"], KINDS["research"])["chapters"][key]]
