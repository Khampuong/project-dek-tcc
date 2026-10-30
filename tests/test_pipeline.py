"""ขั้นตอนอัตโนมัติทั้ง 8 ขั้นแบบออฟไลน์: แทน AI การค้น/ดาวน์โหลด และ Word ด้วยตัวจำลอง

ตรวจสิ่งที่โค้ดของระบบรับผิดชอบเอง: การอ้างอิงมาจากไฟล์จริงเท่านั้น เลขหัวข้อ/ตาราง ไฟล์ครบทุกโฟลเดอร์
การส่งออกเฉพาะไฟล์ที่เปลี่ยน และคำเตือนเมื่อรายการงานวิจัยเปลี่ยนหลังเขียนบท
"""
import json
import re
import unittest
from unittest import mock

from app import db, docbuilder, llm, papers as paperlib, pipeline, refs, store
from app.config import FOLDERS, STEP_KEYS, docs_for, project_dir

from .helpers import admin, new_project, new_user

THAI_TEXT = "งานวิจัยนี้มีวัตถุประสงค์เพื่อพัฒนาผลสัมฤทธิ์ทางการเรียนของนักเรียนด้วยการเรียนรู้แบบโครงงานเป็นฐาน " * 30
ENG_TEXT = "This study examined the effect of project-based learning on the achievement of vocational students. " * 30


def candidate(i: int, source: str) -> dict:
    thai = source == "ThaiJO"
    name = [("สมชาย", "ใจดี"), ("สมหญิง", "รักเรียน"), ("เกษตร", "เมืองทอง"), ("อารี", "มีสุข")][i] if thai \
        else [("John", "Smith"), ("Li", "Wang")][i]
    title = f"การพัฒนาผลสัมฤทธิ์ด้วยโครงงานเป็นฐาน เรื่องที่ {i + 1}" if thai else f"Project-based learning study {i + 1}"
    hint = {"lang": "th" if thai else "en", "title": title, "authors": [{"given": name[0], "family": name[1]}],
            "year": str(2020 + i), "source_type": "journal", "journal": "วารสารทดสอบ" if thai else "Journal of Tests",
            "volume": str(i + 1), "issue": "2", "pages": "10-20", "url": f"https://example.org/{source}/{i}"}
    return {"source": source, "url": hint["url"], "pdf_url": "", "title": title, "authors": "", "year": hint["year"], "hint": hint}


CANDS = [candidate(i, "ThaiJO") for i in range(4)] + [candidate(i, "OpenAlex") for i in range(2)]
GOOD_TITLE = "การเปรียบเทียบผลสัมฤทธิ์ทางการเรียนด้วยโครงงานเป็นฐาน"
CANDS[3]["hint"]["title"] = CANDS[3]["title"] = "การเปรยบเทยบผลสมฤทธทางการเรยนดวยโครงงานเปนฐาน"  # เมทาดาทาวารสารสระหาย
CANDS.append({**candidate(0, "ThaiJO"), "url": "https://example.org/broken", "title": "ลิงก์เสีย"})
CANDS.append({**candidate(1, "ThaiJO"), "url": "https://example.org/offtopic", "title": "เรื่องไม่เกี่ยวข้อง"})


def fake_fetch(cand):
    if cand["url"].endswith("broken"):
        return None
    text = ENG_TEXT if cand["hint"]["lang"] == "en" else THAI_TEXT
    marker = "OFFTOPIC " if cand["url"].endswith("offtopic") else ""
    return {"pdf": b"%PDF-1.4 " + (marker + text).encode("utf-8"), "url": cand["url"], "hint": dict(cand["hint"])}


def fake_extract(pdf: bytes):
    return pdf[9:].decode("utf-8"), 12


def fake_llm(prompt: str, **kw):
    """ตอบตามชนิดของคำสั่ง; เนื้อหาบทจงใจมีข้อผิดพลาดแบบที่ AI จริงเคยทำ เพื่อให้โค้ดของระบบต้องแก้"""
    if '"ch2_outline"' in prompt:
        return {"title_th": "การพัฒนาผลสัมฤทธิ์ทางการเรียนโดยใช้โครงงานเป็นฐาน", "title_en": "Improving Achievement with PBL",
                "research_type": "การวิจัยเชิงทดลองเบื้องต้น", "objectives": ["เพื่อเปรียบเทียบผลสัมฤทธิ์"], "hypotheses": [],
                "keywords_th": ["โครงงานเป็นฐาน"], "keywords_en": ["project based learning"],
                "ch2_outline": [{"no": "2.1", "title": "การเรียนรู้แบบโครงงานเป็นฐาน", "points": ["ความหมาย"]},
                                {"no": "2.2", "title": "งานวิจัยที่เกี่ยวข้อง"}, {"no": "2.3", "title": "กรอบแนวคิดในการวิจัย"}]}
    if "รายการงานวิจัยที่ค้นพบ" in prompt:
        n = len(re.findall(r"^\d+\. \[", prompt, re.M))
        return {"order": list(range(n)) + [999, "x", 0]}  # มีเลขเกินช่วง/ซ้ำ/ไม่ใช่ตัวเลขปนมา
    if "ข้อความที่สกัดจากไฟล์ PDF" in prompt:
        return {"relevance": 2 if "OFFTOPIC" in prompt else 8, "lang": "th", "authors": [],
                "title": GOOD_TITLE if "การเปรยบเทยบ" in prompt else "",
                "summary": {"objective": "เพื่อศึกษา", "findings": "หลังเรียนสูงกว่าก่อนเรียน\x0c"}}
    if '"rationale"' in prompt:  # เนื้อหาสำหรับแบบเสนอโครงงาน
        return {"rationale": ["เทคโนโลยีมีบทบาทต่อการจัดการเรียนรู้ [[@R1]] กล่าวว่าช่วยให้ผู้เรียนพัฒนาขึ้น",
                              "สื่อประเภทนี้ได้ผลดี [[R2;R77]] และ Mayer (2009) เสนอหลักการออกแบบ",
                              "จากที่กล่าวข้างต้น คณะผู้จัดทำจึงพัฒนาชิ้นงานนี้"],
                "objectives": ["2.1 เพื่อพัฒนาชิ้นงาน", "2.2 เพื่อหาประสิทธิภาพ", "เพื่อหาความพึงพอใจ"],
                "experts": "ผู้เชี่ยวชาญด้านการพัฒนาสื่อ จำนวน 3 คน", "population": "นักศึกษา ปวส.1 จำนวน ⟦…⟧ คน",
                "sample": "นักศึกษา ปวส.1/1 จำนวน 30 คน ได้มาโดยการเลือกแบบเจาะจง",
                "content_scope": [{"title": "ส่วนของผู้ใช้", "items": ["เข้าสู่ระบบ", "ดูรายงาน"]}, {"title": "ส่วนของผู้ดูแล", "items": "จัดการข้อมูล"}],
                "software": ["โปรแกรมจัดการเอกสาร Microsoft Word", "- โปรแกรมออกแบบภาพนิ่ง Canva"],
                "goal_quality": "นักศึกษาได้พัฒนาชิ้นงานที่มีคุณภาพ",
                "goal_quantity": ["นักศึกษาพัฒนาชิ้นงาน จำนวน 1 ชิ้นงาน", "30 คน มีความพึงพอใจต่อชิ้นงาน"],
                "budget": ["ค่าวัสดุ", "ค่าจัดทำรูปเล่ม"], "benefits": ["นักศึกษาได้ฝึกทักษะ", "ผู้สอนนำไปใช้ได้"]}
    m = re.search(r'เริ่มด้วยบล็อก \["h1","(2\.\d+) ([^"]+)"\]', prompt)
    if m:  # หัวข้อของบทที่ 2
        return {"blocks": [["h1", f"{m.group(1)} {m.group(2)}"], ["p", f"เนื้อหา {m.group(1)} [[R1;R5]]"],
                           ["table", {"caption": f"ตารางที่ {m.group(1)}-1 สรุป", "headers": ["ผู้วิจัย", "ผล"],
                                      "rows": [["[[@R2]]", "ดีขึ้น"]]}], ["p", f"ดังตารางที่ {m.group(1)}-1"]]}
    return {"blocks": [
        ["chapter", "บทที่ 9", "AI ใส่หัวบทเอง"], ["h1", "บทที่ 1 บทนำ"],
        ["h1", "1.1 ความเป็นมา"], ["p", "[[@R1]] ศึกษาพบว่าดีขึ้น และช่วยลดภาระ [[@R2]] ทั้งนี้ [[R3;R99]]"],
        ["p", "สอดคล้องกับแนวคิดของ Piaget (1970) และ (กระทรวงศึกษาธิการ, 2551) ⟦ชื่อสถานศึกษา⟧"],
        ["h1", "1.3 ขอบเขต"], ["h2", "1.4.1 ประชากร"], ["fill", 4],
        ["table", {"caption": "ตารางที่ 3.1 ผล", "headers": ["รายการ", "x̄"], "rows": [["ก่อนเรียน", ""]]}]]}


def fake_convert(paths):
    for p in paths:
        p.with_suffix(".pdf").write_bytes(b"%PDF-1.4 converted")


def start_fakes():
    """แทน AI การค้น/ดาวน์โหลด และ Word ด้วยตัวจำลอง คืน (รายการ patch, ตัวนับการแปลง PDF)"""
    convert = mock.Mock(side_effect=fake_convert)
    patches = [mock.patch.object(llm, "call_json", side_effect=fake_llm),
               mock.patch.object(paperlib, "search_all", side_effect=lambda th, en, log=None: list(CANDS)),
               mock.patch.object(paperlib, "fetch_paper", side_effect=fake_fetch),
               mock.patch.object(paperlib, "extract_text", side_effect=fake_extract),
               mock.patch.object(docbuilder, "convert_to_pdf", convert)]
    for p in patches:
        p.start()
    return patches, convert


class TeacherClassroomResearchTest(unittest.TestCase):
    """งานวิจัยในชั้นเรียนของครู: ไม่มีแบบเสนอโครงงาน ปิดท้ายด้วยโครงร่างงานวิจัย 3 บท"""

    @classmethod
    def setUpClass(cls):
        cls.teacher, _, _ = new_user("teacher", "ครูวิจัย ในชั้นเรียน")
        cls.pid = new_project(cls.teacher, kind="classroom_research", institution="โรงเรียนทดสอบ")
        cls.patches, cls.convert = start_fakes()
        cls.prompts = []
        with mock.patch.object(llm, "call_json", side_effect=lambda prompt, **kw: cls.prompts.append((prompt, kw.get("system", ""))) or fake_llm(prompt)):
            pipeline._run(cls.pid, STEP_KEYS)
        cls.project = store.project(cls.pid)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    def test_all_steps_done_without_proposal_form(self):
        self.assertEqual({v["status"] for v in self.project["steps"].values()}, {"done"})
        self.assertEqual(store.load_blocks(self.pid, "proposal"), [])
        self.assertFalse(any('"rationale"' in prompt for prompt, _ in self.prompts))  # ไม่เรียก AI เขียนแบบเสนอโครงงาน
        self.assertEqual([d["key"] for d in store.doc_list(self.project)], list(docs_for("classroom_research")))

    def test_outline_is_cover_three_chapters_and_bibliography(self):
        outline = store.blocks_for(self.project, "outline")
        self.assertEqual([b[1] for b in outline if b[0] == "chapter"], ["บทที่ 1", "บทที่ 2", "บทที่ 3"])
        self.assertIn(["title", "โครงร่างงานวิจัย", 24], outline)
        self.assertIn(["center", "ผู้วิจัย  ครูวิจัย ในชั้นเรียน"], outline)
        self.assertIn(["center", "โรงเรียนทดสอบ"], outline)
        self.assertEqual(sum(b[0] == "ref" for b in outline), 6)
        self.assertEqual(store.load_blocks(self.pid, "ch3")[0], ["chapter", "บทที่ 3", "วิธีดำเนินการวิจัย"])

    def test_files_and_folders(self):
        root = project_dir(self.pid)
        self.assertTrue((root / "โครงร่างงานวิจัย 3 บท" / "โครงร่างงานวิจัย 3 บท.docx").exists())
        self.assertTrue((root / "โครงร่างงานวิจัย 3 บท" / "โครงร่างงานวิจัย 3 บท.pdf").exists())
        self.assertEqual(list((root / "แบบเสนอโครงงาน").glob("*")), [])
        names = __import__("zipfile").ZipFile(store.zip_project(self.project)).namelist()
        self.assertFalse(any("แบบเสนอโครงงาน" in n for n in names))

    def test_writing_style_follows_kind(self):
        system = next(s for prompt, s in self.prompts if "เริ่มด้วยบล็อก" in prompt)
        self.assertIn("วิจัยในชั้นเรียนของครู", system)
        self.assertIn("One-Group Pretest-Posttest", system)
        self.assertNotIn("คณะผู้จัดทำ", system)
        plan = next(prompt for prompt, _ in self.prompts if '"ch2_outline"' in prompt)
        self.assertIn("กลุ่มเป้าหมาย", plan)
        ch4 = next(prompt for prompt, _ in self.prompts if 'จงเขียน "บทที่ 4"' in prompt)
        self.assertIn("คะแนนก่อนเรียน-หลังเรียน", ch4)


class OfflinePipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user, _, _ = new_user(name="สมชาย ผู้วิจัย")
        _, cls.advisor_id, _ = new_user("teacher", "ครูสมศรี ที่ปรึกษา")
        admin().post("/admin/settings", {"form": {"institution": "วิทยาลัยทดสอบ", "subject_teacher": "นางสาวครู ประจำวิชา",
                                                  "head": "นางสาวหัวหน้า แผนก", "deputy": ""}})
        cls.pid = new_project(cls.user, advisor_id=cls.advisor_id, department="แผนกวิชาเทคโนโลยีธุรกิจดิจิทัล",
                              period="ตุลาคม 2569 ถึง กุมภาพันธ์ 2570",
                              members="นายสมชาย ผู้วิจัย, 66201010001\nนางสาวสมหญิง ร่วมทำ 66201010002")
        cls.patches, cls.convert = start_fakes()
        cls.prompts = []
        with mock.patch.object(llm, "call_json", side_effect=lambda prompt, **kw: cls.prompts.append((prompt, kw.get("system", ""))) or fake_llm(prompt)):
            pipeline._run(cls.pid, STEP_KEYS)  # ทำงานในเธรดนี้ ไม่ผ่านคิวเบื้องหลัง
        cls.project = store.project(cls.pid)
        cls.logs = [(r["level"], r["msg"]) for r in db.q("SELECT level, msg FROM logs WHERE project_id=?", (cls.pid,))]

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    def text(self, key):
        return json.dumps(store.load_blocks(self.pid, key), ensure_ascii=False)

    def test_all_steps_done(self):
        self.assertEqual({k: v["status"] for k, v in self.project["steps"].items()}, {k: "done" for k in STEP_KEYS},
                         [m for lv, m in self.logs if lv == "error"])
        self.assertEqual(self.project["title_th"], "การพัฒนาผลสัมฤทธิ์ทางการเรียนโดยใช้โครงงานเป็นฐาน")

    def test_papers_downloaded_with_real_metadata(self):
        rows = store.papers(self.pid)
        self.assertEqual([r["rkey"] for r in rows], ["R1", "R2", "R3", "R4", "R5", "R6"])
        self.assertEqual([r["source"] for r in rows], ["ThaiJO"] * 4 + ["OpenAlex"] * 2)
        self.assertEqual(rows[0]["cite"], "สมชาย ใจดี, 2563")  # ค.ศ. 2020 จากหน้าวารสาร -> พ.ศ. สำหรับบทความไทย
        self.assertEqual(rows[4]["cite"], "Smith, 2020")
        self.assertEqual(rows[3]["meta"]["title"], GOOD_TITLE)  # ชื่อจากหน้าวารสารสระหาย -> ใช้ชื่อที่อ่านจากไฟล์
        self.assertEqual(rows[2]["meta"]["title"], CANDS[2]["title"])  # ปกติใช้ชื่อจากหน้าวารสาร
        self.assertEqual(rows[0]["summary"]["findings"], "หลังเรียนสูงกว่าก่อนเรียน")  # อักขระควบคุมถูกตัด
        folder = project_dir(self.pid) / FOLDERS["papers"]
        self.assertEqual(sorted(f.name for f in folder.glob("0*.pdf")), sorted(r["file"] for r in rows))
        skipped = [m for lv, m in self.logs if lv == "warn"]
        self.assertTrue(any("ดาวน์โหลดไม่ได้" in m for m in skipped))
        self.assertTrue(any("ไม่เกี่ยวข้อง" in m for m in skipped))

    def test_citations_come_only_from_downloaded_papers(self):
        ch1 = self.text("ch1")
        self.assertIn("สมชาย ใจดี (2563) ศึกษาพบว่าดีขึ้น", ch1)            # [[@R1]] ต้นประโยค
        self.assertIn("ช่วยลดภาระ (สมหญิง รักเรียน, 2564)", ch1)           # [[@R2]] ท้ายประโยค -> ในวงเล็บ
        self.assertIn("ทั้งนี้ (เกษตร เมืองทอง, 2565)", ch1)                 # R99 ไม่มีไฟล์ -> ตัดทิ้ง
        self.assertNotIn("[[", ch1.replace('[["', ""))
        self.assertNotIn("1970", ch1)
        self.assertNotIn("2551", ch1)
        self.assertEqual(ch1.count(refs.FLAG), 2)                            # อ้างอิงที่ AI พิมพ์เอง 2 แห่ง
        self.assertTrue(any("R99" in m for _, m in self.logs))
        self.assertTrue(any("AI พิมพ์เอง" in m for _, m in self.logs))
        for key in ("ch1", "ch2", "ch3"):
            flagged = []
            refs.guard_blocks(store.load_blocks(self.pid, key), store.refs_map(self.pid), flagged)
            self.assertEqual(flagged, [], key)

    def test_chapter_structure_is_repaired(self):
        ch1 = store.load_blocks(self.pid, "ch1")
        self.assertEqual(ch1[0], ["chapter", "บทที่ 1", "บทนำ"])
        self.assertEqual([b[1] for b in ch1 if b[0] in ("h1", "h2")], ["1.1 ความเป็นมา", "1.2 ขอบเขต", "1.2.1 ประชากร"])
        self.assertEqual([b[1]["caption"] for b in ch1 if b[0] == "table"], ["ตารางที่ 1.1 ผล"])
        self.assertIn("⟦ชื่อสถานศึกษา⟧", self.text("ch1"))
        self.assertEqual(store.load_blocks(self.pid, "ch4")[0], ["chapter", "บทที่ 4", "ผลการดำเนินโครงงาน"])
        self.assertEqual(store.load_blocks(self.pid, "ch3")[0], ["chapter", "บทที่ 3", "วิธีดำเนินโครงงาน"])

    def test_writing_style_follows_kind(self):
        system = next(s for prompt, s in self.prompts if "เริ่มด้วยบล็อก" in prompt)
        self.assertIn("โครงงานของนักเรียน/นักศึกษา", system)
        self.assertIn("คณะผู้จัดทำ", system)
        self.assertNotIn("One-Group Pretest-Posttest", system)
        plan = next(prompt for prompt, _ in self.prompts if '"ch2_outline"' in prompt)
        self.assertIn("ผู้เชี่ยวชาญ 3 คน", plan)
        ch4 = next(prompt for prompt, _ in self.prompts if 'จงเขียน "บทที่ 4"' in prompt)
        self.assertIn("ผลการประเมินคุณภาพโดยผู้เชี่ยวชาญ", ch4)
        self.assertNotIn("การทดสอบที", ch4)

    def test_chapter2_sections_in_order_with_renumbered_tables(self):
        ch2 = store.load_blocks(self.pid, "ch2")
        self.assertEqual([b[1][:3] for b in ch2 if b[0] == "h1"], ["2.1", "2.2", "2.3"])
        self.assertEqual([b[1]["caption"] for b in ch2 if b[0] == "table"], ["ตารางที่ 2.1 สรุป", "ตารางที่ 2.2 สรุป", "ตารางที่ 2.3 สรุป"])
        self.assertEqual([b[1] for b in ch2 if b[0] == "p" and b[1].startswith("ดังตาราง")], ["ดังตารางที่ 2.1", "ดังตารางที่ 2.2", "ดังตารางที่ 2.3"])
        self.assertEqual([b[1]["rows"][0][0] for b in ch2 if b[0] == "table"][0], "สมหญิง รักเรียน (2564)")
        self.assertIn("(สมชาย ใจดี, 2563; Smith, 2020)", self.text("ch2"))

    def test_bibliography_and_proposal(self):
        bib = [b[1] for b in store.bibliography_blocks(self.pid) if b[0] == "ref"]
        self.assertEqual([e.split(".")[0] for e in bib], ["เกษตร เมืองทอง", "สมชาย ใจดี", "สมหญิง รักเรียน", "อารี มีสุข", "Smith, J", "Wang, L"])
        self.assertIn("*วารสารทดสอบ, 1*(2), 10–20. https://example.org/ThaiJO/0", bib[1])

    def test_proposal_form_follows_school_template(self):
        form = store.load_blocks(self.pid, "proposal")
        text = [b[1] for b in form if b[0] in ("title", "pn", "p", "item")]
        heads = [b[1] for b in form if b[0] == "hd"]
        self.assertEqual(text[:2], ["แบบเสนอโครงงาน", "แผนกวิชาเทคโนโลยีธุรกิจดิจิทัล"])
        self.assertEqual(heads, [
            "1. หลักการและเหตุผล", "2. วัตถุประสงค์", "3. ขอบเขตของโครงงาน", "4. เป้าหมาย", "5. ขั้นตอนในการดำเนินโครงงาน",
            "6. ค่าใช้จ่ายในการดำเนินโครงงาน", "7. ประโยชน์ที่คาดว่าจะได้รับ", "8. เอกสารอ้างอิง", "เสนอขออนุมัติโครงงาน"])
        for line in ("**ชื่อโครงงาน**   การพัฒนาผลสัมฤทธิ์ทางการเรียนโดยใช้โครงงานเป็นฐาน", "**ผู้รับผิดชอบโครงงาน**",
                     "1. นายสมชาย ผู้วิจัย   เลขประจำตัว 66201010001", "2. นางสาวสมหญิง ร่วมทำ   เลขประจำตัว 66201010002",
                     "**ระยะเวลาดำเนินการ**   ตุลาคม 2569 ถึง กุมภาพันธ์ 2570", "**พื้นที่ดำเนินการ**   วิทยาลัยทดสอบ",
                     "2.1 เพื่อพัฒนาชิ้นงาน", "2.3 เพื่อหาความพึงพอใจ", "3.1 ขอบเขตด้านประชากรและกลุ่มตัวอย่าง",
                     "3.1.1 ผู้เชี่ยวชาญด้านการพัฒนาสื่อ จำนวน 3 คน", "3.1.3 กลุ่มตัวอย่าง ได้แก่ นักศึกษา ปวส.1/1 จำนวน 30 คน ได้มาโดยการเลือกแบบเจาะจง",
                     "3.2 ขอบเขตด้านเนื้อหา", "3.2.1 ส่วนของผู้ใช้", "3.2.1.2 ดูรายงาน", "3.2.2.1 จัดการข้อมูล", "3.3 ขอบเขตด้านซอฟต์แวร์",
                     "3.3.2 โปรแกรมออกแบบภาพนิ่ง Canva", "**เชิงคุณภาพ**   นักศึกษาได้พัฒนาชิ้นงานที่มีคุณภาพ",
                     "**เชิงปริมาณ**   นักศึกษาพัฒนาชิ้นงาน จำนวน 1 ชิ้นงาน", "30 คน มีความพึงพอใจต่อชิ้นงาน",
                     "6.1 ค่าวัสดุ   ⟦…⟧ บาท", "7.2 ผู้สอนนำไปใช้ได้"):
            self.assertIn(line, text)

    def test_proposal_citations_gantt_and_signatures(self):
        form = store.load_blocks(self.pid, "proposal")
        text = self.text("proposal")
        self.assertIn("สมชาย ใจดี (2563) กล่าวว่า", text)                       # [[@R1]] กลางประโยคตามแบบฟอร์ม
        self.assertIn(f"(สมหญิง รักเรียน, 2564) และ Mayer {refs.FLAG}", text)    # R77 ไม่มีไฟล์, Mayer (2009) AI พิมพ์เอง
        self.assertEqual(sum(b[0] == "ref" for b in form), 6)
        gantt = next(b[1] for b in form if b[0] == "gantt")
        self.assertEqual((gantt["months"][0], gantt["months"][-1], gantt["weeks"], len(gantt["rows"])), ("ตุลาคม", "กุมภาพันธ์", 18, 7))
        self.assertEqual(gantt["rows"][4], ["5. การพัฒนา", 6, 13])
        sign = next(b[1] for b in form if b[0] == "sign")["rows"]
        self.assertEqual([[c["role"] for c in r] for r in sign], [
            ["ผู้จัดทำโครงงาน", "ผู้จัดทำโครงงาน"], ["ครูที่ปรึกษาหลัก", "ครูประจำวิชา"],
            ["หัวหน้าแผนกวิชาเทคโนโลยีธุรกิจดิจิทัล", "รองผู้อำนวยการฝ่ายวิชาการ"]])
        self.assertEqual([[c["name"] for c in r] for r in sign], [
            ["นายสมชาย ผู้วิจัย", "นางสาวสมหญิง ร่วมทำ"], ["ครูสมศรี ที่ปรึกษา", "นางสาวครู ประจำวิชา"], ["นางสาวหัวหน้า แผนก", ""]])
        self.assertEqual(form.index(next(b for b in form if b[0] == "sign")) - 2, form.index(["pb"]))  # หน้าลงนามขึ้นหน้าใหม่

    def test_proposal_is_editable_document(self):
        P = f"/projects/{self.pid}/doc/proposal"
        d = self.user.get(P).get_json()
        self.assertTrue(d["editable"])
        self.assertEqual(d["title"], "แบบเสนอโครงงาน")
        i = next(i for i, b in enumerate(d["blocks"]) if b[0] == "gantt")
        edited = {**d["blocks"][i][1], "rows": [["1. วางแผน", 1, 3], ["2. ไม่กำหนดช่วง", "x", None], ["", 1, 2], ["3. เกินช่วง", 19, 99]]}
        self.assertEqual(self.user.post(f"{P}/block/{i}", {"block": ["gantt", edited]}).status_code, 200)
        self.assertEqual(self.user.get(P).get_json()["blocks"][i][1]["rows"], [["1. วางแผน", 1, 3], ["2. ไม่กำหนดช่วง", 0, 0], ["3. เกินช่วง", 19, 20]])
        self.assertEqual(self.user.post(P + "/undo").status_code, 200)
        self.assertEqual(self.user.get(P).get_json()["blocks"], d["blocks"])

    def test_word_and_pdf_in_every_folder(self):
        root = project_dir(self.pid)
        for key in docs_for("student_project"):
            folder = FOLDERS[key]
            docs = list((root / folder).glob("*.docx"))
            self.assertEqual(len(docs), 1, folder)
            self.assertTrue(docs[0].with_suffix(".pdf").exists(), folder)
        names = set(__import__("zipfile").ZipFile(store.zip_project(self.project)).namelist())
        self.assertEqual(len([n for n in names if n.endswith(".docx")]), 7)
        self.assertFalse(any("_text" in n or n.startswith(".") for n in names))

    def test_z_export_only_reconverts_changed_documents(self):
        self.convert.reset_mock()
        store.build(self.project, list(FOLDERS), pdf=True)
        self.convert.assert_not_called()

        blocks = store.load_blocks(self.pid, "ch4")
        store.save_blocks(self.pid, "ch4", blocks + [["p", "เพิ่มผลการทดลอง"]], note="ทดสอบ")
        store.build(self.project, list(FOLDERS), pdf=True)
        self.assertEqual([[p.parent.name for p in c.args[0]] for c in self.convert.call_args_list], [["บทที่ 4"]])

        self.convert.reset_mock()
        self.assertTrue(store.undo(self.pid, "ch4"))
        self.assertEqual(store.ensure_file(self.project, "ch4", "pdf").suffix, ".pdf")
        self.assertEqual(self.convert.call_count, 1)
        store.ensure_file(self.project, "ch4", "pdf")
        self.assertEqual(self.convert.call_count, 1)  # ดาวน์โหลดซ้ำไม่แปลงใหม่

    def test_z_manual_edit_and_undo_through_api(self):
        P = f"/projects/{self.pid}/doc/ch1"
        before = self.user.get(P).get_json()["blocks"]
        idx = next(i for i, b in enumerate(before) if b[0] == "p")
        self.assertEqual(self.user.post(f"{P}/block/{idx}", {"block": ["p", "แก้เอง\x00"]}).status_code, 200)
        self.assertEqual(self.user.get(P).get_json()["blocks"][idx], ["p", "แก้เอง"])
        self.assertEqual(self.user.post(f"{P}/block/{idx}", {"block": ["bogus"]}).status_code, 400)
        self.assertEqual(self.user.post(f"{P}/block/{idx}", {"delete": True}).status_code, 200)
        self.assertEqual(len(self.user.get(P).get_json()["blocks"]), len(before) - 1)
        self.assertEqual(self.user.post(P + "/undo").status_code, 200)
        self.assertEqual(self.user.post(P + "/undo").status_code, 200)
        self.assertEqual(self.user.get(P).get_json()["blocks"], before)
        r = self.user.get(f"/projects/{self.pid}/download/ch1.docx")
        self.assertEqual((r.status_code, r.data[:2]), (200, b"PK"))
        r.close()

    def test_zz_chapters_flagged_stale_when_paper_list_changes(self):
        stale = lambda: {d["key"] for d in self.user.get(f"/projects/{self.pid}/status").get_json()["docs"] if d["stale"]}  # noqa: E731
        self.assertEqual(stale(), set())
        last = store.papers(self.pid)[-1]
        self.assertEqual(self.user.delete(f"/projects/{self.pid}/papers/{last['id']}").status_code, 200)
        self.assertEqual(stale(), {"ch1", "ch2", "ch3", "proposal"})
        self.assertFalse((project_dir(self.pid) / FOLDERS["papers"] / last["file"]).exists())
        self.assertEqual(sum(b[0] == "ref" for b in self.user.get(f"/projects/{self.pid}/doc/ref").get_json()["blocks"]), 5)
        pipeline._run(self.pid, ["ch1"])  # เขียนใหม่ -> บทนั้นไม่ถูกเตือนอีก
        self.assertEqual(stale(), {"ch2", "ch3", "proposal"})

    def test_zzz_fewer_than_five_papers_blocks_writing(self):
        for r in store.papers(self.pid)[1:]:
            self.user.delete(f"/projects/{self.pid}/papers/{r['id']}")
        pipeline._run(self.pid, ["ch1"])
        step = store.project(self.pid)["steps"]["ch1"]
        self.assertEqual(step["status"], "error")
        self.assertIn("อย่างน้อย 5", step["msg"])


if __name__ == "__main__":
    unittest.main()
