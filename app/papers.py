"""ค้นหาและดาวน์โหลดงานวิจัยฉบับเต็ม (Open Access) พร้อมสกัดข้อความและเมทาดาทา

แหล่งค้นหา:
  - ThaiJO (ระบบ OJS ของวารสารไทย) ค้นข้ามวารสารในแต่ละโฮสต์ soXX.tci-thaijo.org
  - OpenAlex (วารสารต่างประเทศแบบเปิด)
เมทาดาทาอ่านจากแท็ก <meta name="citation_*"> ของหน้าบทความจริง จึงไม่ต้องให้ AI เดา
"""
from __future__ import annotations

import html as htmllib
import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, urlparse

import requests

from .config import MAX_PDF_MB
from .refs import is_thai, split_name

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
THAIJO_HOSTS = ["so01", "so02", "so03", "so04", "so05", "so06"]
MAX_BYTES = MAX_PDF_MB * 1024 * 1024


class Resp:
    def __init__(self, url, content, ctype):
        self.url, self.content, self.ctype = url, content, ctype

    @property
    def is_pdf(self):
        return self.content[:5].lstrip()[:4] == b"%PDF"

    @property
    def text(self):
        return self.content.decode("utf-8", errors="ignore")


def _check_public(url: str):
    """อนุญาตเฉพาะ http(s) ไปยังที่อยู่สาธารณะ (กันการเรียกเข้าเครือข่ายภายใน)"""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("URL ไม่ถูกต้อง")
    for info in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80)):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("ไม่อนุญาตให้เข้าถึงที่อยู่ภายในเครือข่าย")


def safe_get(url: str, timeout: int = 45) -> Resp:
    for _ in range(6):
        _check_public(url)
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=False, stream=True)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            r.close()
            continue
        r.raise_for_status()
        chunks, size = [], 0
        for chunk in r.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                r.close()
                raise ValueError(f"ไฟล์ใหญ่เกิน {MAX_PDF_MB} MB")
            chunks.append(chunk)
        return Resp(url, b"".join(chunks), r.headers.get("Content-Type", ""))
    raise ValueError("เปลี่ยนเส้นทางหลายครั้งเกินไป")


# ------------------------------------------------------------------ search
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def search_thaijo(query: str, host: str, limit: int = 12) -> list[dict]:
    url = f"https://{host}.tci-thaijo.org/index.php/index/search/search?query={quote(query)}"
    try:
        page = safe_get(url, timeout=30).text
    except Exception:  # noqa: BLE001
        return []
    out = []
    for part in page.split('<div class="obj_article_summary">')[1:]:
        m = re.search(r'<a id="article-\d+"\s+href="([^"]+)"[^>]*>(.*?)</a>', part, re.S)
        if not m:
            continue
        au = re.search(r'<div class="authors">(.*?)</div>', part, re.S)
        pub = re.search(r'<div class="published">\s*(\d{4})', part)
        out.append({"source": "ThaiJO", "url": htmllib.unescape(m.group(1)), "pdf_url": "",
                    "title": _clean(m.group(2)), "authors": _clean(au.group(1)) if au else "",
                    "year": pub.group(1) if pub else "", "hint": {}})
        if len(out) >= limit:
            break
    return out


def search_openalex(query: str, limit: int = 10) -> list[dict]:
    url = ("https://api.openalex.org/works?search=" + quote(query) +
           f"&filter=open_access.is_oa:true,type:article&per-page={limit}"
           "&select=title,publication_year,language,doi,authorships,biblio,primary_location,best_oa_location,open_access")
    try:
        data = requests.get(url, headers=UA, timeout=30).json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for w in data.get("results", []):
        best = w.get("best_oa_location") or {}
        prim = w.get("primary_location") or {}
        pdf = best.get("pdf_url") or (w.get("open_access") or {}).get("oa_url") or ""
        landing = best.get("landing_page_url") or prim.get("landing_page_url") or w.get("doi") or ""
        if not w.get("title") or not (pdf or landing):
            continue
        lang = "th" if w.get("language") == "th" or is_thai(w["title"]) else "en"
        names = [a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")]
        bib = w.get("biblio") or {}
        pages = bib.get("first_page") or ""
        if pages and bib.get("last_page") and bib["last_page"] != pages:
            pages += f"-{bib['last_page']}"
        out.append({"source": "OpenAlex", "url": landing, "pdf_url": pdf, "title": _clean(w["title"]),
                    "authors": ", ".join(names[:3]), "year": str(w.get("publication_year") or ""),
                    "hint": {"lang": lang, "title": _clean(w["title"]),
                             "authors": [split_name(n, lang) for n in names],
                             "year": str(w.get("publication_year") or ""), "source_type": "journal",
                             "journal": ((prim.get("source") or {}).get("display_name") or ""),
                             "volume": bib.get("volume") or "", "issue": bib.get("issue") or "",
                             "pages": pages, "url": w.get("doi") or landing}})
    return out


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", (t or "").lower())[:80]


def search_all(queries_th: list[str], queries_en: list[str], log=lambda m: None) -> list[dict]:
    """ค้นทุกแหล่งพร้อมกัน คืนรายการไม่ซ้ำ"""
    # OJS ค้นแบบ AND ทุกคำ: วลีไทยหลายคำคั่นด้วยช่องว่างมักไม่พบผล จึงค้นทีละวลี
    phrases = [w for qy in queries_th for w in qy.split() if len(w) >= 4]
    queries_th = list(dict.fromkeys(phrases))[:8]
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for qy in queries_th:
            for host in THAIJO_HOSTS:
                jobs.append(ex.submit(search_thaijo, qy, host))
        for qy in queries_en:
            jobs.append(ex.submit(search_openalex, qy))
            jobs.append(ex.submit(search_thaijo, qy, "so01", 5))
        results = [j.result() for j in jobs]
    seen, out = set(), []
    for cand in (c for r in results for c in r):
        key = _norm_title(cand["title"])
        if key and key not in seen:
            seen.add(key)
            out.append(cand)
    log(f"พบรายการงานวิจัยจากการค้น {len(out)} รายการ (ThaiJO + OpenAlex)")
    return out


# ------------------------------------------------------------------ download
def parse_citation_meta(page: str) -> dict:
    """อ่านแท็ก citation_* (Google Scholar/Highwire) จากหน้าบทความ"""
    tags: dict[str, list[str]] = {}
    for m in re.finditer(r"<meta\s+([^>]*?)/?>", page, re.S | re.I):
        attrs = dict((k.lower(), v) for k, v in re.findall(r'([\w:]+)\s*=\s*"([^"]*)"', m.group(1)))
        name = attrs.get("name", "")
        if name.lower().startswith("citation_") and attrs.get("content"):
            tags.setdefault(name.lower()[9:], []).append(htmllib.unescape(attrs["content"]).strip())
    if not tags.get("title"):
        return {}
    title = tags["title"][0]
    lang = "th" if is_thai(title) else "en"
    hint = {"lang": lang, "title": title,
            "authors": [split_name(a, "th" if is_thai(a) else "en") for a in tags.get("author", [])],
            "source_type": "journal", "journal": (tags.get("journal_title") or [""])[0],
            "volume": (tags.get("volume") or [""])[0], "issue": (tags.get("issue") or [""])[0]}
    first, last = (tags.get("firstpage") or [""])[0], (tags.get("lastpage") or [""])[0]
    hint["pages"] = f"{first}-{last}" if first and last and first != last else first
    date = (tags.get("date") or tags.get("publication_date") or tags.get("online_date") or [""])[0]
    y = re.search(r"\d{4}", date)
    hint["year"] = y.group(0) if y else ""
    doi = (tags.get("doi") or [""])[0]
    hint["url"] = (f"https://doi.org/{doi}" if doi and not doi.startswith("http") else doi) \
        or (tags.get("abstract_html_url") or [""])[0]
    hint["_pdf"] = (tags.get("pdf_url") or [""])[0]
    return hint


def _pdf_links(url: str, page: str) -> list[str]:
    cands = []
    for href in re.findall(r'href="([^"]+)"', page):
        full = urljoin(url, htmllib.unescape(href))
        if re.search(r"/article/(view|download)/\d+/\d+", full) or full.lower().split("?")[0].endswith(".pdf"):
            cands.append(full.replace("/article/view/", "/article/download/"))
    return list(dict.fromkeys(cands))


def fetch_paper(cand: dict) -> dict | None:
    """ดาวน์โหลด PDF ของรายการที่ค้นพบ คืน {pdf, url, hint} หรือ None"""
    hint = dict(cand.get("hint") or {})
    tried = set()

    def get(u):
        if not u or u in tried:
            return None
        tried.add(u)
        try:
            return safe_get(u)
        except Exception:  # noqa: BLE001
            return None

    queue = [u for u in (cand.get("pdf_url"), cand.get("url")) if u]
    depth = {u: 0 for u in queue}
    while queue and len(tried) < 14:
        u = queue.pop(0)
        r = get(u)
        if r is None:
            continue
        if r.is_pdf:
            hint.pop("_pdf", None)
            return {"pdf": r.content, "url": hint.get("url") or cand.get("url") or r.url, "hint": hint}
        if depth[u] >= 2:
            continue
        page = r.text
        found = parse_citation_meta(page)
        if found:
            # เมทาดาทาจากหน้าบทความจริงน่าเชื่อถือกว่าข้อมูลจากดัชนีค้นหา
            hint = {**hint, **{k: v for k, v in found.items() if v}}
            hint.setdefault("url", r.url)
        nxt = []
        if found.get("_pdf"):
            nxt.append(found["_pdf"].replace("/article/view/", "/article/download/"))
        nxt += _pdf_links(r.url, page)[:5]
        for n in nxt:
            if n not in depth:
                depth[n] = depth[u] + 1
                queue.insert(0, n) if n == nxt[0] else queue.append(n)
    return None


def extract_text(pdf: bytes) -> tuple[str, int]:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        return text, doc.page_count


def normalize_year(yr: str, lang: str) -> str:
    """บทความภาษาไทยอ้างอิงเป็น พ.ศ."""
    m = re.search(r"\d{4}", str(yr or ""))
    if not m:
        return ""
    y = int(m.group(0))
    if lang == "th" and y < 2400:
        y += 543
    if lang == "en" and y > 2400:
        y -= 543
    return str(y)


def safe_filename(n: int, meta: dict) -> str:
    au = (meta.get("authors") or [{}])[0]
    who = (au.get("given") if meta.get("lang") == "th" else au.get("family")) or "paper"
    name = re.sub(r'[\\/:*?"<>|\s.]+', "_", f"{n:02d}_{who}_{meta.get('year', '')}").strip("_")
    return name[:60] + ".pdf"
