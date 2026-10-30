"""ขั้นตอนการจัดทำงานวิจัยอัตโนมัติ (ทำงานเบื้องหลังทีละโครงการ)

plan -> papers -> ch1 -> ch2 -> ch3 -> ch4 -> ref -> export
"""
from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import db, llm, papers as paperlib, prompts, refs, store
from .config import MIN_PAPERS, STEP_KEYS, TARGET_PAPERS, doc_title, docs_for

_jobs: dict[int, dict] = {}
_jobs_lock = threading.Lock()


class Cancelled(Exception):
    pass


class StepError(Exception):
    """ข้อผิดพลาดที่อธิบายให้ผู้ใช้แก้ไขเองได้"""


# ------------------------------------------------------------------ สถานะ/บันทึก
def log(pid: int, msg: str, level: str = "info"):
    db.x("INSERT INTO logs(project_id,ts,level,msg) VALUES(?,?,?,?)", (pid, db.now(), level, msg))


def set_step(pid: int, step: str, status: str, msg: str = ""):
    p = db.q1("SELECT steps FROM projects WHERE id=?", (pid,))
    steps = db.loads(p["steps"], {})
    steps[step] = {"status": status, "msg": msg, "at": db.now()}
    db.x("UPDATE projects SET steps=?, updated_at=? WHERE id=?", (db.dumps(steps), db.now(), pid))


def is_running(pid: int) -> bool:
    j = _jobs.get(pid)
    return bool(j and j["thread"].is_alive())


def cancel(pid: int):
    j = _jobs.get(pid)
    if j:
        j["cancel"] = True


def _check(pid: int):
    if _jobs.get(pid, {}).get("cancel"):
        raise Cancelled()


def start(pid: int, steps: list[str]) -> bool:
    steps = [s for s in STEP_KEYS if s in steps]
    with _jobs_lock:
        if is_running(pid) or not steps:
            return False
        t = threading.Thread(target=_run, args=(pid, steps), daemon=True)
        _jobs[pid] = {"thread": t, "cancel": False}
        for s in steps:
            set_step(pid, s, "queued")
        t.start()
    return True


def _run(pid: int, steps: list[str]):
    store.ensure_folders(pid)
    llm.set_notifier(lambda m: log(pid, m, "warn"))
    for i, step in enumerate(steps):
        try:
            _check(pid)
            set_step(pid, step, "running")
            msg = STEP_FUNCS[step](pid) or ""
            set_step(pid, step, "done", msg)
        except Cancelled:
            log(pid, "ยกเลิกการทำงานแล้ว", "warn")
            for s in steps[i:]:
                set_step(pid, s, "error" if s == step else "pending", "ยกเลิกโดยผู้ใช้" if s == step else "")
            return
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, (StepError, llm.LLMError)):
                traceback.print_exc()
            log(pid, f"ผิดพลาด: {e}", "error")
            set_step(pid, step, "error", str(e))
            for s in steps[i + 1:]:
                set_step(pid, s, "pending")
            return
    log(pid, "เสร็จสิ้นทุกขั้นตอนที่สั่ง", "ok")


def _need_papers(pid: int) -> list[dict]:
    rows = store.papers(pid)
    if len(rows) < MIN_PAPERS:
        raise StepError(f"ต้องมีงานวิจัยที่เกี่ยวข้องอย่างน้อย {MIN_PAPERS} เรื่อง (ขณะนี้มี {len(rows)} เรื่อง) "
                        "กรุณาสั่งค้นหาใหม่ หรืออัปโหลดไฟล์ PDF/เพิ่มจากลิงก์ในแท็บงานวิจัยที่เกี่ยวข้อง")
    return rows


def _need_plan(pid: int) -> dict:
    p = store.project(pid)
    if not p["title_th"] or not p["plan"]:
        raise StepError("ยังไม่ได้วิเคราะห์ requirement กรุณาสั่งขั้นตอนแรกก่อน")
    return p


# ------------------------------------------------------------------ ขั้นตอน
def step_plan(pid: int):
    p = store.project(pid)
    log(pid, "กำลังวิเคราะห์ requirement และออกแบบงาน ...")
    plan = llm.call_json(prompts.plan(p), system=prompts.system(p["kind"]), temperature=0.4)
    if not isinstance(plan, dict) or not plan.get("title_th"):
        raise StepError("AI วิเคราะห์ requirement ไม่สำเร็จ กรุณาลองใหม่")
    title_th = (p["requirement"].get("title") or "").strip() or str(plan.pop("title_th")).strip()
    title_en = str(plan.pop("title_en", "")).strip()
    plan.pop("title_th", None)
    db.x("UPDATE projects SET title_th=?, title_en=?, plan=?, updated_at=? WHERE id=?",
         (title_th, title_en, db.dumps(plan), db.now(), pid))
    log(pid, f"ชื่อเรื่อง: {title_th}", "ok")
    return title_th


def analyze_and_add(pid: int, p: dict, pdf: bytes, url: str, hint: dict, source: str, min_relevance: int = 4) -> dict:
    """อ่านไฟล์ PDF ด้วย AI ตรวจความเกี่ยวข้อง สกัดเมทาดาทา/สรุป แล้วบันทึกลงโฟลเดอร์งานวิจัยที่เกี่ยวข้อง"""
    try:
        text, pages = paperlib.extract_text(pdf)
    except Exception as e:  # noqa: BLE001
        raise StepError(f"เปิดไฟล์ PDF ไม่ได้: {e}") from e
    if len(text.strip()) < 1500:
        raise StepError("ไฟล์ PDF ไม่มีข้อความให้อ่าน (อาจเป็นไฟล์สแกนภาพ)")
    a = llm.call_json(prompts.analyze_paper(p, hint, text), temperature=0.2, fast=True)
    if not isinstance(a, dict):
        raise StepError("AI อ่านไฟล์ไม่สำเร็จ")
    try:
        rel = float(a.get("relevance") or 0)
    except (TypeError, ValueError):
        rel = 0
    if rel < min_relevance:
        raise StepError(f"ไม่เกี่ยวข้องกับงานนี้เพียงพอ (คะแนน {rel:g}/10)")

    # บทความไทยมักมีบทคัดย่ออังกฤษอยู่ต้นไฟล์ จึงดูสัดส่วนอักษรไทยทั้งไฟล์
    sample = text[:80000]
    ratio = sum("\u0e00" <= c <= "\u0e7f" for c in sample) / len(sample)
    # สัดส่วนก้ำกึ่ง (บทความไทยที่มีอังกฤษปนมาก): ใช้ภาษาที่ AI อ่านได้จากไฟล์ช่วยตัดสิน
    lang = "th" if ratio > 0.3 or (ratio > 0.08 and a.get("lang") == "th") else "en"
    meta = {"lang": lang}

    def pick(key, empty):
        """เมทาดาทาจากหน้าวารสารจริงมาก่อน; ใช้ค่าที่ AI อ่านจากไฟล์เมื่อหน้าวารสารไม่มี
        หรือให้มาเป็นคนละภาษากับบทความ (เช่น ชื่อผู้แต่งไทยที่หน้าเว็บแสดงเป็นอักษรโรมัน)"""
        def matches(v):
            s = db.dumps(v)
            return bool(v) and refs.is_thai(s) == (lang == "th") and not refs.thai_damaged(s)
        h, ai = hint.get(key), a.get(key)
        return h if matches(h) else ai if matches(ai) else h or ai or empty

    meta["title"], meta["authors"], meta["journal"] = pick("title", ""), pick("authors", []), pick("journal", "")
    if not isinstance(meta["authors"], list):
        meta["authors"] = []
    for k in ("volume", "issue", "pages", "publisher", "source_type"):
        meta[k] = hint.get(k) or a.get(k) or ""
    meta = {k: refs.clean_text(v).strip() if not isinstance(v, list) else v for k, v in meta.items()}
    meta["authors"] = [refs.split_name(f"{x.get('given') or ''} {x.get('family') or ''}", lang) if lang == "th"
                       else {"given": refs.clean_text(x.get("given")).strip(), "family": refs.clean_text(x.get("family")).strip()}
                       for x in meta["authors"] if isinstance(x, dict)]
    meta["year"] = paperlib.normalize_year(hint.get("year") or a.get("year"), lang)
    meta["url"] = hint.get("url") or url or ""
    if not meta["title"] or not meta["authors"]:
        raise StepError("ระบุชื่อเรื่องหรือผู้แต่งจากไฟล์ไม่ได้")

    norm = paperlib._norm_title(meta["title"])
    for r in store.papers(pid):
        if paperlib._norm_title(r["meta"].get("title", "")) == norm:
            raise StepError("มีงานวิจัยเรื่องนี้ในโครงการแล้ว")

    last = db.q1("SELECT rkey FROM papers WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    n = int(last["rkey"][1:]) + 1 if last else 1
    fname = paperlib.safe_filename(n, meta)
    folder = store.papers_dir(pid)
    (folder / fname).write_bytes(pdf)
    (folder / "_text").mkdir(exist_ok=True)
    (folder / "_text" / (fname[:-4] + ".txt")).write_text(text, encoding="utf-8")
    summary = a.get("summary") if isinstance(a.get("summary"), dict) else {}
    summary = {k: refs.clean_text(v).strip() for k, v in summary.items() if v}
    summary["pages"] = pages
    db.x("INSERT INTO papers(project_id,rkey,file,url,meta,summary,source) VALUES(?,?,?,?,?,?,?)",
         (pid, f"R{n}", fname, meta["url"], db.dumps(meta), db.dumps(summary), source))
    return {"rkey": f"R{n}", "file": fname, "meta": meta}


def _download(pid: int, p: dict, cands: list[dict], limit: int, have: int, tried: set) -> int:
    """ดาวน์โหลดและวิเคราะห์รายการตามลำดับ จนมีงานวิจัยครบ limit เรื่อง คืนจำนวนที่มี"""
    for c in cands:
        _check(pid)
        if have >= limit:
            break
        if c["url"] in tried:
            continue
        tried.add(c["url"])
        got = paperlib.fetch_paper(c)
        if not got:
            log(pid, f"ดาวน์โหลดไม่ได้ (ข้าม): {c['title'][:90]}", "warn")
            continue
        try:
            r = analyze_and_add(pid, p, got["pdf"], got["url"], got["hint"], c["source"])
            have += 1
            log(pid, f"[{have}] บันทึก {r['file']} — {refs.narr(r['meta'])}", "ok")
        except StepError as e:
            log(pid, f"ข้าม: {c['title'][:70]} — {e}", "warn")
    return have


def step_papers(pid: int):
    p = _need_plan(pid)
    plan = p["plan"]
    have = len(store.papers(pid))
    if have >= TARGET_PAPERS:
        return f"มีงานวิจัยแล้ว {have} เรื่อง"
    kw_th, kw_en = list(plan.get("keywords_th") or []), list(plan.get("keywords_en") or [])
    tried_urls: set[str] = set()

    for round_no in (1, 2):
        _check(pid)
        log(pid, f"ค้นหางานวิจัยด้วยคำค้น: {', '.join(kw_th + kw_en)}")
        cands = [c for c in paperlib.search_all(kw_th, kw_en, lambda m: log(pid, m)) if c["url"] not in tried_urls]
        if cands:
            order = llm.call_json(prompts.rank(p, cands[:150]), temperature=0.2, fast=True)
            idx = order.get("order") if isinstance(order, dict) else order
            picked = [cands[i] for i in dict.fromkeys(i for i in idx or [] if isinstance(i, int) and 0 <= i < len(cands))]
            abroad = [c for c in cands if c["source"] == "OpenAlex" and c not in picked]
            if abroad and sum(c["source"] == "OpenAlex" for c in picked) < 3:
                more = llm.call_json(prompts.rank(p, abroad[:60], 6), temperature=0.2, fast=True)
                idx = more.get("order") if isinstance(more, dict) else more
                picked += [abroad[i] for i in dict.fromkeys(i for i in idx or [] if isinstance(i, int) and 0 <= i < len(abroad))]
            log(pid, f"AI คัดเลือกรายการที่เกี่ยวข้อง {len(picked)} รายการ กำลังดาวน์โหลดไฟล์ฉบับเต็ม ...")
            # กันที่ไว้ให้งานวิจัยต่างประเทศ 2 เรื่อง (ถ้าค้นพบ) แล้วค่อยเติมด้วยรายการที่เหลือ
            intl = [c for c in picked if c["source"] == "OpenAlex"]
            local = [c for c in picked if c["source"] != "OpenAlex"]
            for group, limit in ((local, TARGET_PAPERS - min(2, len(intl))), (intl, TARGET_PAPERS), (local, TARGET_PAPERS)):
                have = _download(pid, p, group, limit, have, tried_urls)
        if have >= MIN_PAPERS or round_no == 2:
            break
        log(pid, f"ได้งานวิจัย {have} เรื่อง ยังไม่ถึง {MIN_PAPERS} เรื่อง ขยายคำค้นแล้วค้นใหม่ ...", "warn")
        more = llm.call_json(prompts.more_keywords(p, kw_th + kw_en), temperature=0.6, fast=True)
        kw_th, kw_en = list(more.get("keywords_th") or []), list(more.get("keywords_en") or [])

    store.build(store.project(pid), ["papers"])
    if have < MIN_PAPERS:
        raise StepError(f"ดาวน์โหลดงานวิจัยได้ {have} เรื่อง (ต้องการอย่างน้อย {MIN_PAPERS}) "
                        "กรุณาอัปโหลดไฟล์ PDF หรือเพิ่มจากลิงก์ในแท็บงานวิจัยที่เกี่ยวข้อง แล้วสั่งขั้นตอนถัดไป")
    return f"ดาวน์โหลดงานวิจัยฉบับเต็ม {have} เรื่อง"


def _write(pid: int, p: dict, prompt: str, what: str) -> list:
    """เรียก AI เขียนเนื้อหา คืนบล็อกที่แปลงโทเคนอ้างอิงเป็น APA แล้ว"""
    _check(pid)
    data = llm.call_json(prompt, system=prompts.system(p["kind"]), temperature=0.6)
    raw = data.get("blocks") if isinstance(data, dict) else data
    blocks = [b for b in store.sanitize_blocks(raw)
              if b[0] != "chapter" and not (b[0] in ("h1", "title") and b[1].startswith("บทที่"))]
    if not blocks:
        raise StepError(f"AI ไม่ได้ส่งเนื้อหา{what}กลับมา กรุณาลองใหม่")
    unknown: list[str] = []
    known = store.refs_map(pid)
    blocks = refs.resolve_blocks(blocks, known, unknown)
    if unknown:
        log(pid, f"ตัดการอ้างอิงที่ไม่มีไฟล์จริงออกจาก{what}: {', '.join(sorted(set(unknown)))}", "warn")
    typed: list[str] = []
    blocks = refs.guard_blocks(blocks, known, typed)
    if typed:
        log(pid, f"พบการอ้างอิงที่ AI พิมพ์เองและไม่อยู่ในรายการงานวิจัยใน{what} {len(typed)} แห่ง "
                 f"แทนด้วยช่อง [เพิ่มแหล่งอ้างอิง] ให้ตรวจสอบ: {'; '.join(t.strip() for t in typed[:4])}", "warn")
    return blocks


def _finish_chapter(pid: int, p: dict, key: str, blocks: list):
    blocks = store.renumber_headings(blocks, int(key[-1]))
    blocks = store.renumber_tables([store.chapter_heading(p, key)] + blocks, int(key[-1]))
    store.save_blocks(pid, key, blocks, note="สร้างโดยระบบ")
    store.mark_written(pid, key)
    store.build(store.project(pid), [key])
    return f"{sum(1 for b in blocks if b[0] in ('p', 'pn', 'item'))} ย่อหน้า"


def step_ch1(pid: int):
    p, rows = _need_plan(pid), _need_papers(pid)
    log(pid, "กำลังเขียนบทที่ 1 โดยอ้างอิงจากงานวิจัยที่ดาวน์โหลดไว้ ...")
    return _finish_chapter(pid, p, "ch1", _write(pid, p, prompts.ch1(p, rows), "บทที่ 1"))


def step_ch2(pid: int):
    p, rows = _need_plan(pid), _need_papers(pid)
    outline = [s for s in p["plan"].get("ch2_outline") or [] if isinstance(s, dict) and s.get("title")]
    if len(outline) < 3:
        outline = [{"title": "แนวคิดและทฤษฎีที่เกี่ยวข้อง", "points": []}, {"title": "งานวิจัยที่เกี่ยวข้อง"},
                   {"title": "กรอบแนวคิดในการวิจัย"}]
    for i, s in enumerate(outline, 1):
        s["no"] = f"2.{i}"
    word = "โครงงาน" if p["kind"] == "student_project" else "การวิจัย"
    blocks = [["p", f"ใน{word}เรื่อง {p['title_th']} ผู้จัดทำได้ศึกษาเอกสารและงานวิจัยที่เกี่ยวข้อง "
                    "เพื่อเป็นพื้นฐานและแนวทางในการดำเนินงาน โดยนำเสนอตามลำดับหัวข้อต่อไปนี้"]]
    blocks += [["item", f"{s['no']} {s['title']}", 1] for s in outline]

    def write_section(i: int) -> list:
        s = outline[i]
        llm.set_notifier(lambda m: log(pid, m, "warn"))  # เธรดย่อยมีตัวแจ้งสถานะของตัวเอง
        log(pid, f"กำลังเขียนบทที่ 2 หัวข้อ {s['no']} {s['title']} ({i + 1}/{len(outline)}) ...")
        is_fw = i == len(outline) - 1 and "กรอบแนวคิด" in s["title"]
        is_rel = "งานวิจัยที่เกี่ยวข้อง" in s["title"]
        sec = _write(pid, p, prompts.ch2_section(p, rows, outline, s, is_rel, is_fw), f"หัวข้อ {s['no']}")
        if sec[0][0] != "h1":
            sec.insert(0, ["h1", f"{s['no']} {s['title']}"])
        return sec

    # แต่ละหัวข้อเขียนแยกกันได้ จึงส่งคำขอ AI พร้อมกันหลายหัวข้อเมื่อโควตาของ key รองรับ
    workers = max(1, min(6, int(float(db.get_setting("ch2_parallel") or 1))))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sec in ex.map(write_section, range(len(outline))):
            blocks += sec
    return _finish_chapter(pid, p, "ch2", blocks)


def step_ch3(pid: int):
    p, rows = _need_plan(pid), _need_papers(pid)
    log(pid, "กำลังเขียนบทที่ 3 (เว้นช่องบริบทให้เติม) ...")
    return _finish_chapter(pid, p, "ch3", _write(pid, p, prompts.ch3(p, rows), "บทที่ 3"))


def step_ch4(pid: int):
    p = _need_plan(pid)
    outline = "\n".join(b[1] if b[0] in ("h1", "h2") else "  " + b[1].get("caption", "")
                        for b in store.load_blocks(pid, "ch3") if b[0] in ("h1", "h2", "table"))
    log(pid, "กำลังเขียนบทที่ 4 (ตารางและช่องว่างสำหรับเติมผล) ...")
    return _finish_chapter(pid, p, "ch4", _write(pid, p, prompts.ch4(p, outline or "(ยังไม่มีบทที่ 3)"), "บทที่ 4"))


def step_ref(pid: int):
    rows = _need_papers(pid)
    store.build(store.project(pid), ["ref", "papers"])
    log(pid, f"จัดทำบรรณานุกรมแบบ APA {len(rows)} รายการ", "ok")
    return f"{len(rows)} รายการ"


def write_proposal(pid: int):
    """เขียน "แบบเสนอโครงงาน" ตามแบบฟอร์มของสถานศึกษา (แทนที่ฉบับเดิม ย้อนกลับได้จากหน้าเอกสาร)"""
    p, rows = _need_plan(pid), _need_papers(pid)
    background = "\n".join(b[1] for b in store.load_blocks(pid, "ch1") if b[0] == "p")[:3500]
    _check(pid)
    data = llm.call_json(prompts.proposal(p, rows, background), system=prompts.system(p["kind"]), temperature=0.5)
    if not isinstance(data, dict) or not data.get("rationale"):
        raise StepError("AI ไม่ได้ส่งเนื้อหาแบบเสนอโครงงานกลับมา กรุณาลองใหม่")
    known, unknown, typed = store.refs_map(pid), [], []
    blocks = refs.guard_blocks(refs.resolve_blocks(store.proposal_blocks(p, data), known, unknown), known, typed)
    if unknown or typed:
        log(pid, f"แบบเสนอโครงงาน: ตัดการอ้างอิงที่ไม่มีไฟล์จริง {len(set(unknown))} รายการ "
                 f"และแทนการอ้างอิงที่ AI พิมพ์เอง {len(typed)} แห่งด้วยช่อง [เพิ่มแหล่งอ้างอิง]", "warn")
    store.save_blocks(pid, "proposal", blocks, note="สร้างโดยระบบ")
    store.mark_written(pid, "proposal")


def step_export(pid: int):
    p = store.project(pid)
    docs = docs_for(p["kind"])
    if "proposal" in docs:
        log(pid, "กำลังเขียนแบบเสนอโครงงานตามแบบฟอร์ม ...")
        write_proposal(pid)
        p = store.project(pid)
    else:
        log(pid, f"กำลังประกอบ{doc_title(p['kind'], docs[-1])}จากบทที่ 1–3 และบรรณานุกรม ...")
    log(pid, "กำลังส่งออกไฟล์ Word ทุกโฟลเดอร์ ...")
    paths = store.build(p, docs)
    if not paths:
        raise StepError("ยังไม่มีเอกสารให้ส่งออก")
    try:
        log(pid, "กำลังแปลงเป็น PDF ด้วย Microsoft Word ...")
        store.build(p, docs, pdf=True)
    except Exception as e:  # noqa: BLE001
        log(pid, f"แปลง PDF ไม่สำเร็จ (ต้องมี Microsoft Word บนเครื่องเซิร์ฟเวอร์): {e}", "warn")
        return f"ส่งออก Word {len(paths)} ไฟล์ (PDF ไม่สำเร็จ)"
    return f"ส่งออก Word + PDF {len(paths)} ชุด"


STEP_FUNCS = {"plan": step_plan, "papers": step_papers, "ch1": step_ch1, "ch2": step_ch2,
              "ch3": step_ch3, "ch4": step_ch4, "ref": step_ref, "export": step_export}
