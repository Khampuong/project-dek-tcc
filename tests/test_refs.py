"""การจัดรูปแบบ APA การแปลงโทเคนอ้างอิง และตัวดักการอ้างอิงที่ AI พิมพ์เอง"""
import unittest

from app import papers, refs

TH3 = {"lang": "th", "year": "2564", "title": "การจัดการเรียนการสอนแบบโครงงานเป็นฐาน", "source_type": "journal",
       "authors": [{"given": "ภูมิพัฒน์", "family": "วนพิพัฒน์พงศ์"}, {"given": "สุภาณี", "family": "เส็งศรี"},
                   {"given": "กอบสุข", "family": "คงมนัส"}],
       "journal": "วารสารวิชาการ T-VET Journal", "volume": "5", "issue": "9", "pages": "127-139", "url": "https://x.org/1"}
EN2 = {"lang": "en", "year": "2020", "title": "PBL in schools.", "source_type": "journal", "journal": "J. Educ.",
       "volume": "3", "authors": [{"given": "Jean-Paul A.", "family": "Smith"}, {"given": "Li", "family": "Wang"}]}
TH1 = {"lang": "th", "year": "2567", "title": "ชุดฝึกทักษะ", "authors": [{"given": "เกษตร", "family": "เมืองทอง"}]}
REFS = {"R1": TH3, "R2": EN2, "R3": TH1}


class ApaTest(unittest.TestCase):
    def test_thai_journal_entry(self):
        self.assertEqual(refs.apa(TH3), "ภูมิพัฒน์ วนพิพัฒน์พงศ์, สุภาณี เส็งศรี, และกอบสุข คงมนัส. (2564). "
                                        "การจัดการเรียนการสอนแบบโครงงานเป็นฐาน. *วารสารวิชาการ T-VET Journal, 5*(9), 127–139. https://x.org/1")

    def test_english_entry_uses_initials(self):
        self.assertEqual(refs.apa(EN2), "Smith, J.-P. A., & Wang, L. (2020). PBL in schools. *J. Educ., 3*.")

    def test_thesis_entry(self):
        m = {**EN2, "source_type": "thesis", "journal": "", "publisher": "Doctoral dissertation, MIT"}
        self.assertEqual(refs.apa(m), "Smith, J.-P. A., & Wang, L. (2020). *PBL in schools* [Doctoral dissertation, MIT].")

    def test_in_text_forms(self):
        self.assertEqual(refs.cite(TH3), "ภูมิพัฒน์ วนพิพัฒน์พงศ์ และคณะ, 2564")
        self.assertEqual(refs.narr(TH1), "เกษตร เมืองทอง (2567)")
        self.assertEqual(refs.cite(EN2), "Smith & Wang, 2020")
        self.assertEqual(refs.narr(EN2), "Smith and Wang (2020)")

    def test_missing_year(self):
        self.assertEqual(refs.year({"lang": "th"}), "ม.ป.ป.")
        self.assertEqual(refs.year({"lang": "en"}), "n.d.")

    def test_thai_author_of_english_article_keeps_full_name(self):
        m = {"lang": "en", "year": "2016", "title": "t", "authors": [refs.split_name("รสสุคนธ์ เสวตเวชากุล", "en")]}
        self.assertEqual(refs.cite(m), "รสสุคนธ์ เสวตเวชากุล, 2016")

    def test_bibliography_order_thai_first_and_leading_vowels(self):
        metas = [EN2, TH1, TH3, {"lang": "th", "year": "2560", "title": "t", "authors": [{"given": "กมล", "family": "ก"}]}]
        order = [refs.apa(m)[:3] for m in sorted(metas, key=refs.sort_key)]
        self.assertEqual(order, ["กมล", "เกษ", "ภูม", "Smi"])  # เ-ก-ษ เรียงที่ ก ไม่ใช่ท้ายพยัญชนะ


class NameTest(unittest.TestCase):
    def test_split_names(self):
        self.assertEqual(refs.split_name("พระสมนึก ฐิตาจาโร (พันธุ์เพชร)", "th"), {"given": "พระสมนึก", "family": "ฐิตาจาโร (พันธุ์เพชร)"})
        self.assertEqual(refs.split_name("John Ronald Smith", "en"), {"given": "John Ronald", "family": "Smith"})
        self.assertEqual(refs.split_name("Smith, John", "en"), {"given": "John", "family": "Smith"})

    def test_cleans_journal_quirks(self):
        self.assertEqual(refs.split_name("ปารณัท ศุภพิมล (Paranat Suphapimol)", "th"), {"given": "ปารณัท", "family": "ศุภพิมล"})
        self.assertEqual(refs.split_name("suphitcha  chanrueang", "en"), {"given": "Suphitcha", "family": "Chanrueang"})

    def test_detects_thai_text_with_missing_vowels(self):
        self.assertTrue(refs.thai_damaged("การเปรยบเทยบผลสมฤทธทางการเรยน ความสามารถในการแกปญหาทางคณตศาสตร"))
        self.assertFalse(refs.thai_damaged("การเปรียบเทียบผลสัมฤทธิ์ทางการเรียน ความสามารถในการแก้ปัญหาทางคณิตศาสตร์"))
        self.assertFalse(refs.thai_damaged("วารสารการศึกษา"))  # สั้นเกินกว่าจะตัดสิน
        self.assertFalse(refs.thai_damaged("Project-based learning"))

    def test_control_characters_removed(self):
        self.assertEqual(refs.clean_text("a\x0bb\x00c\tก\n"), "abc\tก\n")

    def test_year_conversion(self):
        self.assertEqual(papers.normalize_year("2021/06/30", "th"), "2564")
        self.assertEqual(papers.normalize_year("2564", "th"), "2564")
        self.assertEqual(papers.normalize_year("2564", "en"), "2021")
        self.assertEqual(papers.normalize_year("", "th"), "")


class ResolveTest(unittest.TestCase):
    def test_tokens_become_citations(self):
        self.assertEqual(refs.resolve("ช่วยพัฒนาทักษะ [[R1;R2]] จริง", REFS),
                         "ช่วยพัฒนาทักษะ (ภูมิพัฒน์ วนพิพัฒน์พงศ์ และคณะ, 2564; Smith & Wang, 2020) จริง")
        self.assertEqual(refs.resolve("[[@R3]] ศึกษาพบว่า", REFS), "เกษตร เมืองทอง (2567) ศึกษาพบว่า")
        self.assertEqual(refs.resolve("สอดคล้องกับงานวิจัยของ [[@R3]] ที่พบ", REFS), "สอดคล้องกับงานวิจัยของ เกษตร เมืองทอง (2567) ที่พบ")

    def test_unknown_keys_are_dropped_and_reported(self):
        unknown = []
        self.assertEqual(refs.resolve("ผล [[R9]] และ [[R1;R8]] จบ", REFS, unknown), "ผล และ (ภูมิพัฒน์ วนพิพัฒน์พงศ์ และคณะ, 2564) จบ")
        self.assertEqual(unknown, ["R9", "R8"])

    def test_narrative_token_at_sentence_end_becomes_parenthetical(self):
        self.assertEqual(refs.resolve("ช่วยลดภาระงาน [[@R3]] ต่อมา", REFS), "ช่วยลดภาระงาน (เกษตร เมืองทอง, 2567) ต่อมา")

    def test_narrative_token_starting_a_new_sentence_mid_paragraph(self):
        self.assertEqual(refs.resolve("มาใช้ส่งเสริมการจัดกิจกรรมการเรียนรู้ [[@R3]] กล่าวว่าสื่อช่วยผู้เรียน", REFS),
                         "มาใช้ส่งเสริมการจัดกิจกรรมการเรียนรู้ เกษตร เมืองทอง (2567) กล่าวว่าสื่อช่วยผู้เรียน")

    def test_other_double_brackets_untouched(self):
        self.assertEqual(refs.resolve("ดู [[หมายเหตุ]]", REFS), "ดู [[หมายเหตุ]]")

    def test_resolve_blocks_walks_tables(self):
        out = refs.resolve_blocks([["table", {"headers": ["ผู้วิจัย"], "rows": [["[[@R3]]"]]}]], REFS)
        self.assertEqual(out[0][1]["rows"], [["เกษตร เมืองทอง (2567)"]])


class GuardTest(unittest.TestCase):
    """การอ้างอิงที่ AI พิมพ์เองโดยไม่ผ่านโทเคน ต้องถูกแทนด้วยช่องให้เติม"""

    def flag(self, text):
        found = []
        return refs.flag_unlisted(text, REFS, found), found

    def test_typed_narrative_citation_flagged(self):
        out, found = self.flag("สอดคล้องกับแนวคิดของ Piaget (2007) ที่ระบุว่า")
        self.assertEqual(out, f"สอดคล้องกับแนวคิดของ Piaget {refs.FLAG} ที่ระบุว่า")
        self.assertEqual(len(found), 1)

    def test_typed_parenthetical_citation_flagged(self):
        out, _ = self.flag("ช่วยพัฒนาผู้เรียน (Prensky, 2007) และ (กระทรวงศึกษาธิการ, 2551)")
        self.assertEqual(out, f"ช่วยพัฒนาผู้เรียน {refs.FLAG} และ {refs.FLAG}")

    def test_mixed_group_keeps_listed_part(self):
        out, _ = self.flag("ผล (เกษตร เมืองทอง, 2567; Vygotsky, 1978) จบ")
        self.assertEqual(out, f"ผล (เกษตร เมืองทอง, 2567) {refs.FLAG} จบ")

    def test_listed_citations_untouched(self):
        text = "เกษตร เมืองทอง (2567) พบว่า Smith and Wang (2020) ศึกษา (ภูมิพัฒน์ วนพิพัฒน์พงศ์ และคณะ, 2564; Smith & Wang, 2020)"
        self.assertEqual(self.flag(text), (text, []))

    def test_right_author_wrong_year_flagged(self):
        self.assertIn(refs.FLAG, self.flag("เกษตร เมืองทอง (2560) พบว่า")[0])

    def test_non_citation_parentheses_untouched(self):
        text = "หลักสูตร พุทธศักราช 2551 (ฉบับปรับปรุง พ.ศ. 2560) กลุ่มตัวอย่าง (n = 30) ผ่านเกณฑ์ (ร้อยละ 80) ระดับ (4.51)"
        self.assertEqual(self.flag(text), (text, []))

    def test_guard_blocks_only_checks_selected_blocks_and_skips_bibliography(self):
        blocks = [["p", "Piaget (2007)"], ["p", "Piaget (2007)"], ["ref", "Piaget, J. (2007). Book."]]
        out = refs.guard_blocks(blocks, REFS, only={1})
        self.assertEqual([b[1] for b in out], ["Piaget (2007)", f"Piaget {refs.FLAG}", "Piaget, J. (2007). Book."])
        self.assertEqual(refs.guard_blocks(blocks, REFS)[2], blocks[2])


class OjsMetaTest(unittest.TestCase):
    PAGE = """<meta name="citation_journal_title" content="วารสารทดสอบ"/>
<meta name="citation_author" content="สมชาย ใจดี"/><meta name="citation_author" content="สมหญิง  รักเรียน"/>
<meta name="citation_title" content="ผลของการสอน &amp; การเรียน"/><meta name="citation_date" content="2021/06/30"/>
<meta name="citation_volume" content="5"/><meta name="citation_issue" content="2"/>
<meta name="citation_firstpage" content="10"/><meta name="citation_lastpage" content="25"/>
<meta name="citation_pdf_url" content="https://j.org/index.php/x/article/download/1/2"/>
<a href="https://j.org/index.php/x/article/view/1/2">PDF</a>"""

    def test_reads_citation_tags(self):
        h = papers.parse_citation_meta(self.PAGE)
        self.assertEqual((h["lang"], h["title"], h["journal"], h["volume"], h["issue"], h["pages"], h["year"]),
                         ("th", "ผลของการสอน & การเรียน", "วารสารทดสอบ", "5", "2", "10-25", "2021"))
        self.assertEqual(h["authors"], [{"given": "สมชาย", "family": "ใจดี"}, {"given": "สมหญิง", "family": "รักเรียน"}])
        self.assertEqual(h["_pdf"], "https://j.org/index.php/x/article/download/1/2")

    def test_page_without_tags(self):
        self.assertEqual(papers.parse_citation_meta("<html><title>x</title></html>"), {})

    def test_finds_ojs_pdf_links(self):
        self.assertEqual(papers._pdf_links("https://j.org/index.php/x/article/view/1", self.PAGE),
                         ["https://j.org/index.php/x/article/download/1/2"])

    def test_private_addresses_refused(self):
        for url in ("http://127.0.0.1/x", "http://localhost/", "file:///c:/x", "http://169.254.169.254/", "ftp://a.org/x.pdf"):
            with self.assertRaises(ValueError, msg=url):
                papers._check_public(url)


if __name__ == "__main__":
    unittest.main()
