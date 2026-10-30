"""การตั้งค่าหลักของระบบจัดทำงานวิจัย"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STORAGE = Path(os.environ.get("RESEARCH_STORAGE", BASE / "storage"))
PROJECTS_DIR = STORAGE / "projects"
DB_PATH = STORAGE / "app.db"
WEB_DIR = BASE / "web"

DEFAULT_MODEL = "gemini-flash-latest"  # ชื่อแทนรุ่นล่าสุด: ไม่ต้องแก้เมื่อ Google เลิกให้บริการรุ่นเก่า
DEFAULT_FAST_MODEL = "gemini-flash-lite-latest"  # งานคัดกรอง/สกัดข้อมูล และโมเดลสำรองเมื่อโมเดลหลักไม่ว่าง

MIN_PAPERS = 5       # จำนวนงานวิจัยขั้นต่ำที่ต้องดาวน์โหลดได้จริง
TARGET_PAPERS = 8    # จำนวนที่พยายามหา
MAX_PDF_MB = 25

ROLES = {"student": "นักเรียน/นักศึกษา", "teacher": "ครู", "admin": "ผู้ดูแลระบบ"}
LEVELS = ("ปวช.", "ปวส.")  # ระดับของนักเรียน/นักศึกษา
DEFAULT_INSTITUTION = "วิทยาลัยพณิชยการธนบุรี"  # ค่าเริ่มต้นในฟอร์มสมัคร (ผู้ดูแลระบบเปลี่ยนได้ที่ข้อมูลสถานศึกษา)

# ประเภทงาน -> ชื่อบท
KINDS = {
    "student_project": {
        "label": "โครงงานนักเรียน/นักศึกษา",
        "word": "โครงงาน",
        "chapters": {"ch1": "บทนำ", "ch2": "เอกสารและงานวิจัยที่เกี่ยวข้อง",
                     "ch3": "วิธีดำเนินโครงงาน", "ch4": "ผลการดำเนินโครงงาน"},
    },
    "classroom_research": {
        "label": "งานวิจัยในชั้นเรียน",
        "word": "การวิจัย",
        "chapters": {"ch1": "บทนำ", "ch2": "เอกสารและงานวิจัยที่เกี่ยวข้อง",
                     "ch3": "วิธีดำเนินการวิจัย", "ch4": "ผลการวิเคราะห์ข้อมูล"},
    },
    "research": {
        "label": "งานวิจัย/วิจัยและพัฒนา",
        "word": "การวิจัย",
        "chapters": {"ch1": "บทนำ", "ch2": "เอกสารและงานวิจัยที่เกี่ยวข้อง",
                     "ch3": "วิธีดำเนินการวิจัย", "ch4": "ผลการวิเคราะห์ข้อมูล"},
    },
}

# ประเภทงานที่แต่ละบทบาทสร้างได้: นักเรียน/นักศึกษาทำโครงงาน ครูทำวิจัยในชั้นเรียน
ROLE_KINDS = {"student": ("student_project",), "teacher": ("classroom_research",), "admin": tuple(KINDS)}

# โฟลเดอร์ผลลัพธ์ของแต่ละเอกสาร (ภายในโฟลเดอร์โครงการ)
FOLDERS = {
    "papers": "งานวิจัยที่เกี่ยวข้อง",
    "ch1": "บทที่ 1",
    "ch2": "บทที่ 2",
    "ch3": "บทที่ 3",
    "ch4": "บทที่ 4",
    "ref": "บรรณานุกรม",
    "proposal": "แบบเสนอโครงงาน",
    "outline": "โครงร่างงานวิจัย 3 บท",
}
EDITABLE = ("ch1", "ch2", "ch3", "ch4", "proposal")
ALL_DOCS = ("papers", "ch1", "ch2", "ch3", "ch4", "ref", "proposal", "outline")


def docs_for(kind: str) -> tuple:
    """เอกสารของงานแต่ละประเภท: โครงงานปิดท้ายด้วยแบบเสนอโครงงาน งานวิจัยปิดท้ายด้วยโครงร่าง 3 บท"""
    return ALL_DOCS[:6] + (("proposal",) if kind == "student_project" else ("outline",))


def step_label(kind: str, key: str, label: str) -> str:
    if key == "export":
        return "7) " + doc_title(kind, docs_for(kind)[-1]) + " และส่งออก Word + PDF"
    return label

# ขั้นตอนของระบบ (ตามลำดับ)
STEPS = [
    ("plan", "วิเคราะห์ requirement และกำหนดหัวข้อ"),
    ("papers", "1) ค้นหาและดาวน์โหลดงานวิจัยที่เกี่ยวข้อง"),
    ("ch1", "2) เขียนบทที่ 1"),
    ("ch2", "3) เขียนบทที่ 2"),
    ("ch3", "4) เขียนบทที่ 3"),
    ("ch4", "5) เขียนบทที่ 4"),
    ("ref", "6) บรรณานุกรมแบบ APA"),
    ("export", "7) เอกสารสรุป และส่งออก Word + PDF"),
]
STEP_KEYS = [k for k, _ in STEPS]


def project_dir(pid: int) -> Path:
    return PROJECTS_DIR / str(pid)


def doc_title(kind: str, key: str) -> str:
    ch = KINDS.get(kind, KINDS["research"])["chapters"]
    if key in ch:
        return f"บทที่ {key[-1]} {ch[key]}"
    return {"papers": "สรุปงานวิจัยที่เกี่ยวข้อง", "ref": "บรรณานุกรม (APA)",
            "proposal": "แบบเสนอโครงงาน", "outline": "โครงร่างงานวิจัย 3 บท"}[key]


def doc_path(pid: int, kind: str, key: str, ext: str = "docx") -> Path:
    return project_dir(pid) / FOLDERS[key] / f"{doc_title(kind, key)}.{ext}"
