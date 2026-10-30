"""จัดรูปแบบการอ้างอิง APA 7 จากเมทาดาทาของงานวิจัยที่ดาวน์โหลดมาจริง

meta = {lang: 'th'|'en', authors: [{given, family}], year, title, source_type: journal|thesis|other,
        journal, volume, issue, pages, publisher, url}

ในเนื้อหาที่ AI เขียน ใช้โทเคนอ้างอิง แล้วระบบแทนที่เป็นข้อความจริง:
  [[R1]] / [[R1;R3]]  -> (ผู้แต่ง, ปี) / (ผู้แต่ง, ปี; ผู้แต่ง, ปี)
  [[@R1]]             -> ผู้แต่ง (ปี)
"""
from __future__ import annotations

import re

_THAI = re.compile(r"[฀-๿]")
_LEAD_VOWELS = "เแโใไ"
_NARR_LEAD = ("ของ", "กับ", "ตาม", "จาก", "โดย", "และ", "ว่า", "ที่", "เช่น", "ได้แก่", "ซึ่ง", "ส่วน", "ขณะที่",
              "งานวิจัย", "การศึกษา", "ผลการวิจัย", "นอกจากนี้", "ทั้งนี้", "ต่อมา", ",", ";", ":", "(")
# คำกริยาที่ตามหลังชื่อผู้แต่งเมื่อผู้แต่งเป็นประธานของประโยคใหม่กลางย่อหน้า ("... [[@R1]] กล่าวว่า ...")
_NARR_VERBS = ("กล่าว", "ศึกษา", "ได้", "พบ", "ระบุ", "เสนอ", "อธิบาย", "ให้ความหมาย", "สรุป", "รายงาน", "พัฒนา", "ทำการ",
               "วิจัย", "ชี้", "ที่", "ซึ่ง")
CITE_TOKEN = re.compile(r"\[\[\s*(@?)\s*([^\[\]]+?)\s*\]\]")


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]")


def clean_text(v) -> str:
    """ข้อความจาก AI/หน้าเว็บ: ตัดอักขระควบคุมที่ไฟล์ Word (XML) รับไม่ได้"""
    return _CONTROL.sub("", v if isinstance(v, str) else ("" if v is None else str(v)))


def is_thai(text: str) -> bool:
    return bool(_THAI.search(text or ""))


_THAI_MARKS = re.compile(r"[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]")


def thai_damaged(text: str) -> bool:
    """ข้อความไทยที่สระบน/ล่างและวรรณยุกต์หายเกือบหมด (พบในเมทาดาทาของบางวารสาร เช่น "การเปรยบเทยบผลสมฤทธ")

    ภาษาไทยปกติมีสระบน/ล่างและวรรณยุกต์ราว 15-20% ของอักษรไทยทั้งหมด
    """
    thai = _THAI.findall(text or "")
    return len(thai) >= 20 and len(_THAI_MARKS.findall(text)) / len(thai) < 0.04


def split_name(name: str, lang: str) -> dict:
    """แยกชื่อ-นามสกุลจากข้อความชื่อเต็ม"""
    name = clean_text(name)
    if is_thai(name):  # "ปารณัท ศุภพิมล (Paranat Suphapimol)" -> ตัดชื่ออักษรโรมันที่วารสารใส่ซ้ำไว้
        name = re.sub(r"\([A-Za-z][A-Za-z .,'-]*\)", " ", name)
        lang = "th"
    name = re.sub(r"\s+", " ", name).strip(" ,;")
    if name.islower():  # วารสารบางแห่งบันทึกชื่ออักษรโรมันเป็นตัวพิมพ์เล็กทั้งหมด
        name = name.title()
    if "," in name and lang == "en":
        family, given = [s.strip() for s in name.split(",", 1)]
        return {"given": given, "family": family}
    parts = name.split(" ")
    if len(parts) == 1:
        return {"given": "", "family": parts[0]} if lang == "en" else {"given": parts[0], "family": ""}
    if lang == "th":
        return {"given": parts[0], "family": " ".join(parts[1:])}
    return {"given": " ".join(parts[:-1]), "family": parts[-1]}


def _th_name(a: dict) -> str:
    return f"{a.get('given', '')} {a.get('family', '')}".strip()


def _initials(given: str) -> str:
    out = []
    for part in re.split(r"[\s.]+", given or ""):
        if part:
            out.append("-".join(p[0].upper() + "." for p in part.split("-") if p))
    return " ".join(out)


def _en_name(a: dict) -> str:
    ini = _initials(a.get("given", ""))
    return f"{a.get('family', '')}, {ini}" if ini else a.get("family", "")


def _authors(meta: dict) -> list[dict]:
    return [a for a in meta.get("authors") or [] if (a.get("given") or a.get("family"))]


def _thai_names(meta: dict) -> bool:
    """จัดรูปแบบชื่อแบบไทย (ชื่อ นามสกุล) เมื่อชื่อผู้แต่งเป็นอักษรไทย แม้ตัวบทความจะเป็นภาษาอังกฤษ"""
    au = _authors(meta)
    return is_thai(_th_name(au[0])) if au else meta.get("lang") == "th"


def year(meta: dict) -> str:
    return str(meta.get("year") or "").strip() or ("ม.ป.ป." if meta.get("lang") == "th" else "n.d.")


def _short(meta: dict, narrative: bool) -> str:
    au = _authors(meta)
    if _thai_names(meta):
        if not au:
            return meta.get("title", "")[:40]
        if len(au) == 1:
            return _th_name(au[0])
        if len(au) == 2:
            return f"{_th_name(au[0])} และ{_th_name(au[1])}"
        return f"{_th_name(au[0])} และคณะ"
    if not au:
        return meta.get("title", "")[:40]
    fam = [a.get("family") or a.get("given") for a in au]
    if len(fam) == 1:
        return fam[0]
    if len(fam) == 2:
        return f"{fam[0]} {'and' if narrative else '&'} {fam[1]}"
    return f"{fam[0]} et al."


def cite(meta: dict) -> str:
    """รูปแบบในวงเล็บ (ไม่รวมวงเล็บ): ผู้แต่ง, ปี"""
    return f"{_short(meta, False)}, {year(meta)}"


def narr(meta: dict) -> str:
    """รูปแบบนำหน้าประโยค: ผู้แต่ง (ปี)"""
    return f"{_short(meta, True)} ({year(meta)})"


def apa(meta: dict) -> str:
    """รายการบรรณานุกรม APA 7 (ใช้ *…* แทนตัวเอียง)"""
    au = _authors(meta)
    th = _thai_names(meta)
    if th:
        names = [_th_name(a) for a in au]
        if len(names) <= 1:
            who = "".join(names)
        elif len(names) == 2:
            who = f"{names[0]} และ{names[1]}"
        else:
            who = ", ".join(names[:-1]) + f", และ{names[-1]}"
    else:
        names = [_en_name(a) for a in au]
        if len(names) <= 1:
            who = "".join(names)
        elif len(names) == 2:
            who = f"{names[0]}, & {names[1]}"
        else:
            who = ", ".join(names[:-1]) + f", & {names[-1]}"
    title = (meta.get("title") or "").strip().rstrip(".")
    kind = meta.get("source_type") or "journal"
    url = (meta.get("url") or "").strip()
    head = f"{who.rstrip('.')}. ({year(meta)})." if who else f"{title}. ({year(meta)})."

    if kind == "journal" and meta.get("journal"):
        src = meta["journal"].strip()
        vol, iss, pages = (str(meta.get(k) or "").strip() for k in ("volume", "issue", "pages"))
        if vol:
            src = f"*{src}, {vol}*" + (f"({iss})" if iss else "")
        else:
            src = f"*{src}*" + (f"({iss})" if iss else "")
        if pages:
            src += f", {pages.replace('-', '–')}"
        body = f"{title}. {src}." if who else f"{src}."
    else:
        pub = (meta.get("publisher") or "").strip()
        if kind == "thesis" and pub:
            body = f"*{title}* [{pub}]." if who else f"[{pub}]."
        else:
            body = (f"*{title}*." if who else "") + (f" {pub}." if pub else "")
    out = f"{head} {body.strip()}".strip()
    return f"{out} {url}".strip() if url else out


def sort_key(meta: dict):
    """เรียงบรรณานุกรม: ภาษาไทยก่อน แล้วเรียงตามตัวอักษร (สระหน้าเรียงตามพยัญชนะต้น)"""
    s = apa(meta).lstrip("*")
    if len(s) > 1 and s[0] in _LEAD_VOWELS:
        s = s[1] + s[0] + s[2:]
    return (0 if _thai_names(meta) else 1, s.lower())


def author_words(meta: dict) -> list[str]:
    """คำในชื่อผู้แต่งไทย สำหรับกันไม่ให้ตัดบรรทัดกลางชื่อ"""
    words = []
    if _thai_names(meta):
        for a in _authors(meta):
            for piece in re.split(r"[()\s]+", _th_name(a)):
                if piece:
                    words.append(piece)
    return words


def resolve(text: str, refs: dict[str, dict], unknown: list | None = None) -> str:
    """แทนโทเคน [[R1;R2]] / [[@R1]] ด้วยข้อความอ้างอิงจริง; คีย์ที่ไม่มีอยู่จริงจะถูกตัดออก"""

    def sub(m):
        # [[@R1]] เป็นแบบนำหน้าประโยคได้เฉพาะเมื่ออยู่ต้นข้อความหรือตามหลังคำเชื่อม
        # AI บางรุ่นใส่ @ ท้ายประโยค ซึ่งที่ถูกต้องคือรูปแบบในวงเล็บ
        before = text[:m.start()].rstrip()
        after = text[m.end():].lstrip()
        narrative = bool(m.group(1)) and (not before or before.endswith(_NARR_LEAD) or after.startswith(_NARR_VERBS))
        keys = [k.strip().lstrip("@").upper() for k in re.split(r"[;,]", m.group(2)) if k.strip()]
        if not keys or not all(re.fullmatch(r"R\d+", k) for k in keys):
            return m.group(0)  # ไม่ใช่โทเคนอ้างอิง
        good = [k for k in keys if k in refs]
        if unknown is not None:
            unknown.extend(k for k in keys if k not in refs)
        if not good:
            return ""
        if narrative:
            parts = [narr(refs[k]) for k in good]
            return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " และ " + parts[-1]
        return "(" + "; ".join(cite(refs[k]) for k in good) + ")"

    out = CITE_TOKEN.sub(sub, text)
    if out == text:  # ไม่มีโทเคน: คงการเว้นวรรคเดิมไว้ (เช่น ช่องไฟหลังหัวข้อในแบบฟอร์ม)
        return text
    return re.sub(r"[ \t]{2,}", " ", out).replace(" )", ")").replace("( ", "(")


FLAG = "⟦เพิ่มแหล่งอ้างอิง⟧"
_YEAR = r"(?:19|20|24|25)\d{2}[a-z]?"
_PAREN_CITE = re.compile(r"\(([^()]*?,\s*" + _YEAR + r"(?:\s*;[^()]*?,\s*" + _YEAR + r")*)\)")
_NARR_CITE = re.compile(r"\((" + _YEAR + r")\)")
_NOT_CITE = ("พ.ศ.", "ค.ศ.", "ฉบับ", "ปีการศึกษา", "ปี ")


def flag_unlisted(text: str, refs: dict[str, dict], flagged: list | None = None) -> str:
    """แทนการอ้างอิง (ผู้แต่ง, ปี) / ผู้แต่ง (ปี) ที่ไม่ตรงกับงานวิจัยในรายการ ด้วยช่องให้ผู้จัดทำเติมแหล่งอ้างอิงเอง

    โทเคน [[R1]] รับประกันได้เฉพาะสิ่งที่ AI ใส่เป็นโทเคน; ฟังก์ชันนี้ดักกรณีที่ AI พิมพ์ชื่อและปีขึ้นเอง
    """
    cites = {cite(m) for m in refs.values()}
    narrs = [(_short(m, True), year(m)) for m in refs.values()]

    def note(s):
        if flagged is not None:
            flagged.append(s)
        return FLAG

    def paren(m):
        inner = m.group(1)
        if any(w in inner for w in _NOT_CITE):
            return m.group(0)
        parts = [p.strip() for p in inner.split(";")]
        good = [p for p in parts if p in cites]
        if len(good) == len(parts):
            return m.group(0)
        note(m.group(0))
        return ("(" + "; ".join(good) + ") " if good else "") + FLAG

    def narrative(m):
        before = text2[:m.start()].rstrip()
        if any(before.endswith(name) and y == m.group(1) for name, y in narrs):
            return m.group(0)
        if before.endswith(_NOT_CITE) or re.search(r"(พ\.ศ\.|ค\.ศ\.)\s*$", before):
            return m.group(0)
        return note(before[-30:] + " " + m.group(0))

    text2 = _PAREN_CITE.sub(paren, text)
    return _NARR_CITE.sub(narrative, text2)


def guard_blocks(blocks: list, refs: dict[str, dict], flagged: list | None = None, only: set | None = None) -> list:
    """ใช้ flag_unlisted กับทุกข้อความในบล็อก (only = ตำแหน่งบล็อกที่ต้องตรวจ; None = ทั้งหมด)"""
    def walk(v):
        if isinstance(v, str):
            return flag_unlisted(v, refs, flagged)
        if isinstance(v, list):
            return [walk(i) for i in v]
        if isinstance(v, dict):
            return {k: walk(i) for k, i in v.items()}
        return v

    return [[b[0]] + walk(b[1:]) if (only is None or i in only) and b and b[0] != "ref" else b
            for i, b in enumerate(blocks)]


def resolve_blocks(blocks: list, refs: dict[str, dict], unknown: list | None = None) -> list:
    def walk(v):
        if isinstance(v, str):
            return resolve(v, refs, unknown)
        if isinstance(v, list):
            return [walk(i) for i in v]
        if isinstance(v, dict):
            return {k: walk(i) for k, i in v.items()}
        return v

    return [walk(b) for b in blocks]
