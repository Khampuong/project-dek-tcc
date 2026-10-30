"""ตัวเชื่อมต่อ Google Gemini API (ใช้ร่วมกันทุกโมดูล)"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import requests

from . import db
from .config import DEFAULT_FAST_MODEL, DEFAULT_MODEL

_lock = threading.Lock()
_last_call = 0.0
_local = threading.local()
_unhealthy: dict[str, float] = {}  # โมเดลที่เพิ่งล้มเหลว -> เวลาที่จะกลับมาลองใหม่
RETRYABLE = (429, 500, 502, 503, 504)


def set_notifier(fn):
    """กำหนดฟังก์ชันรับข้อความแจ้งสถานะ (เช่น กำลังลองใหม่/สลับโมเดล) ของเธรดปัจจุบัน"""
    _local.notify = fn


def _notify(msg: str):
    fn = getattr(_local, "notify", None)
    if fn:
        fn(msg)


class LLMError(RuntimeError):
    pass


def get_settings() -> dict:
    return {
        "api_key": db.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY", ""),
        "model": db.get_setting("gemini_model") or DEFAULT_MODEL,
        "fast_model": db.get_setting("gemini_fast_model") or DEFAULT_FAST_MODEL,
        "min_interval": float(db.get_setting("llm_min_interval") or 4),
    }


def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        end = max(text.rfind("}"), text.rfind("]"))
        return json.loads(text[: end + 1])


def _throttle(min_interval: float):
    """เว้นระยะระหว่างคำขอ เพื่อไม่ให้เกินโควตาต่อนาทีของ API"""
    global _last_call
    with _lock:
        wait = _last_call + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def call(prompt: str, system: str = "", history=None, json_mode: bool = True, search: bool = False,
         temperature: float = 0.5, timeout: int = 180, retries: int = 4, fast: bool = False):
    """เรียก Gemini คืน (ข้อความ, grounding_urls)

    fast=True ใช้โมเดลเร็วสำหรับงานคัดกรอง/สกัดข้อมูล; งานเขียนใช้โมเดลหลัก
    และสลับไปโมเดลเร็วอัตโนมัติเมื่อโมเดลหลักไม่ว่าง (503/429) หรือช้าเกินกำหนด
    """
    s = get_settings()
    if not s["api_key"]:
        raise LLMError("ยังไม่ได้ตั้งค่า Gemini API key (ผู้ดูแลระบบตั้งค่าได้ที่เมนู ผู้ดูแลระบบ)")
    contents = []
    for h in history or []:
        contents.append({"role": "user" if h["role"] == "user" else "model", "parts": [{"text": h["text"]}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    body = {"contents": contents, "generationConfig": {"temperature": temperature}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    elif json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    models = [s["fast_model"]] if fast else [s["model"], s["fast_model"]]
    models = list(dict.fromkeys(m for m in models if m))
    healthy = [m for m in models if _unhealthy.get(m, 0) < time.time()]
    if healthy and len(healthy) < len(models):
        models = healthy  # โมเดลหลักเพิ่งล้มเหลว: ข้ามไปใช้โมเดลสำรองสักพัก ไม่ต้องรอซ้ำทุกคำขอ
    last = ""
    for mi, model in enumerate(models):
        if mi:
            _unhealthy[models[mi - 1]] = time.time() + 600
            _notify(f"โมเดลหลักไม่พร้อมใช้งาน ({last[:120]}) — ใช้โมเดลสำรอง {model} แทนในช่วง 10 นาทีนี้")
        # โมเดลหลักลองน้อยครั้งเมื่อยังมีโมเดลสำรอง เพื่อไม่ให้ผู้ใช้รอนาน
        tries = 2 if mi < len(models) - 1 else retries
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(tries):
            _throttle(s["min_interval"])
            try:
                r = requests.post(url, json=body, headers={"x-goog-api-key": s["api_key"]}, timeout=timeout)
            except requests.RequestException as e:
                last = f"เชื่อมต่อ Gemini ไม่ได้หรือใช้เวลานานเกินไป: {type(e).__name__}"
                if mi < len(models) - 1:
                    break  # มีโมเดลสำรอง: ไม่รอหมดเวลาซ้ำอีกรอบ
                continue
            if r.status_code == 200:
                cands = r.json().get("candidates") or []
                parts = (cands[0].get("content", {}).get("parts", []) if cands else [])
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                if not text.strip():
                    reason = cands[0].get("finishReason") if cands else "ไม่มีคำตอบ"
                    last = f"Gemini ส่งคำตอบว่าง ({reason})"
                    continue
                urls = []
                for ch in cands[0].get("groundingMetadata", {}).get("groundingChunks", []) or []:
                    web = ch.get("web") or {}
                    if web.get("uri"):
                        urls.append({"uri": web["uri"], "title": web.get("title", "")})
                return text, urls
            try:
                msg = r.json()["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = r.text[:300]
            last = f"Gemini API error {r.status_code}: {msg}"
            if r.status_code not in RETRYABLE:
                if r.status_code in (400, 401, 403) and "API key" in msg:
                    raise LLMError(last)
                break  # เช่น 404 โมเดลถูกยกเลิก: ลองโมเดลถัดไป
            if attempt < tries - 1:
                m = re.search(r"retry in ([\d.]+)s", msg)
                wait = min(60, float(m.group(1)) + 2 if m else 8 * (attempt + 1))
                _notify(f"AI ไม่ว่าง ({r.status_code}) รอ {wait:.0f} วินาทีแล้วลองใหม่ ...")
                time.sleep(wait)
    raise LLMError(last)


def call_json(prompt: str, system: str = "", retries_parse: int = 2, **kw):
    """เรียก Gemini แบบ JSON; ถ้าแปลง JSON ไม่ได้ให้ลองใหม่"""
    err = None
    for _ in range(retries_parse):
        text, _urls = call(prompt, system=system, json_mode=True, **kw)
        try:
            data = extract_json(text)
            # โมเดลบางรุ่นห่อคำตอบ {…} ไว้ในลิสต์อีกชั้น
            if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                data = data[0]
            return data
        except (json.JSONDecodeError, ValueError) as e:
            err = e
    raise LLMError(f"AI ตอบกลับในรูปแบบที่อ่านไม่ได้: {err}")
