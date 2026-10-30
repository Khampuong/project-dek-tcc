"""ตัวแก้ไขเอกสารด้วย AI — รับคำสั่งภาษาไทยแล้วคืนชุดคำสั่งแก้ไขบล็อก"""
from __future__ import annotations

import json

from . import llm, prompts, store


def _doc_text(blocks):
    return "\n".join(f"[{i}] " + json.dumps(b, ensure_ascii=False) for i, b in enumerate(blocks))


def ask(p: dict, doc_title: str, blocks: list, message: str, chat_history=None) -> dict:
    hist = [{"role": h.get("role"), "text": str(h.get("text", ""))[:2000]} for h in (chat_history or [])[-8:]
            if isinstance(h, dict)]
    data = llm.call_json(f"เอกสารปัจจุบัน: {doc_title}\n{_doc_text(blocks)}\n\nคำสั่งของผู้จัดทำ: {message}",
                         system=prompts.editor_system(p, store.papers(p["id"])), history=hist, temperature=0.4)
    if not isinstance(data, dict):
        data = {}
    return {"reply": str(data.get("reply") or ""), "ops": data.get("ops") if isinstance(data.get("ops"), list) else []}


def apply_ops(blocks, ops):
    """ใช้คำสั่งแก้ไขกับเอกสาร คืน (เอกสารใหม่, รายการตำแหน่งที่เปลี่ยน)"""
    blocks = [list(b) for b in blocks]
    n = len(blocks)
    prio = {"insert": 0, "replace": 1, "delete": 2}

    def pos(o):
        try:
            return int(o.get("index", o.get("after", -1)))
        except (TypeError, ValueError):
            return -2

    def clean(b):
        got = store.sanitize_blocks([b])
        return got[0] if got else None

    valid = [o for o in ops if isinstance(o, dict) and o.get("op") in prio and -1 <= pos(o) < n]
    marks = [False] * n  # True = บล็อกเดิมที่ถูกแก้
    inserted = {}
    for o in sorted(valid, key=lambda o: (-pos(o), prio[o["op"]])):
        i = pos(o)
        if o["op"] == "replace" and i >= 0:
            nb = clean(o.get("block"))
            if nb:
                blocks[i] = nb
                marks[i] = True
        elif o["op"] == "delete" and i >= 0:
            blocks[i] = None
        elif o["op"] == "insert":
            inserted.setdefault(i, []).extend(store.sanitize_blocks(o.get("blocks") or []))
    out, changed = [], []
    for b in inserted.get(-1, []):
        changed.append(len(out))
        out.append(b)
    for i, b in enumerate(blocks):
        if b is not None:
            if marks[i]:
                changed.append(len(out))
            out.append(b)
        for nb in inserted.get(i, []):
            changed.append(len(out))
            out.append(nb)
    return out, changed
