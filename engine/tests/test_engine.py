from pdf2docx_engine.docx.build_docx import fix_legacy_tex_bf
from pdf2docx_engine.math.math_repair import merge_fragmented_math, repair_markdown


def test_merge_fragmented_math():
    md, n = merge_fragmented_math("Khai triển x$^{7}$ và (1+x)$^{11}$")
    assert "$x^{7}$" in md and "$(1+x)^{11}$" in md and n >= 2


def test_fix_legacy_bf():
    assert "\\mathbf{X}" in fix_legacy_tex_bf("${\\bf X}$")


def test_repair_markdown_reports():
    _, rep = repair_markdown("Bài 1. x$^{2}$\n\nBài 2. y\n")
    assert rep["merged_math_fragments"] >= 1


def test_vi_correct_merge_keeps_punctuation_and_prefix():
    from pdf2docx_engine.recognition.vi_correct import _merge, _word_ok
    from pdf2docx_engine.recognition.vietnam import _PREFIX, strip_diacritics

    assert _merge("Đối tượng phần ánh", "Đối tượng phản ánh")[0] == "Đối tượng phản ánh"
    assert _merge("tàn newborn, bạc", "tàn nhẫn, bạc")[0] == "tàn newborn, bạc"   # đổi hẳn chữ -> giữ gốc
    assert _merge("(THEO CHƯỜNG", "(TheO CHƯƠNG")[0] == "(THEO CHƯƠNG"           # chỉ đổi hoa/thường -> bỏ
    assert _word_ok("x1", "x2") is False                                          # không đổi số
    assert _word_ok("Bài", "BÀI") is False                                        # chỉ đổi hoa/thường
    assert _PREFIX.match("## CHUYÊN ĐÊ 3").groups() == ("## ", "CHUYÊN ĐÊ 3")
    assert strip_diacritics("Đối tượng phản ánh") == "Doi tuong phan anh"


def test_vi_correct_short_text_skips_model():
    from pdf2docx_engine.recognition.vi_correct import correct_markdown as fix_spelling
    from pdf2docx_engine.recognition.vietnam import correct_markdown as add_diacritics

    out, rep = add_diacritics("ngắn", report_path="")
    assert out == "ngắn" and rep["pieces"] == 0
    out, rep = fix_spelling("ngắn", report_path="", spelling=True, add_diacritics=False)
    assert out == "ngắn" and rep["units"] == 0


def test_ocr_fusion_votes():
    from pdf2docx_engine.recognition.diacritic_fusion import fuse_markdown
    md = "## CHUYÊN ĐÊ 3. ĐẶC TRUNG VĂN HỌC\nĐối tượng phần ánh của văn học, tàn newborn, bạc bẽo $x^2$ ở đây"
    good = "CHUYÊN ĐỀ 3. ĐẶC TRƯNG VĂN HỌC Đối tượng phản ánh của văn học, tàn nhẫn, bạc bẽo ở đây"
    ref = [(w, 97.0) for w in good.replace(",", "").replace(".", "").split()]
    out, rep = fuse_markdown(md, {"tesseract": ref, "vision": ref})
    assert out == ("## CHUYÊN ĐỀ 3. ĐẶC TRƯNG VĂN HỌC\n"
                   "Đối tượng phản ánh của văn học, tàn nhẫn, bạc bẽo $x^2$ ở đây")
    one, _ = fuse_markdown(md, {"tesseract": ref})            # 1 bộ OCR: chỉ sửa dấu, không thay hẳn chữ
    assert "phản ánh" in one and "newborn" in one


def test_place_tone():
    from pdf2docx_engine.recognition.diacritic_fusion import place_tone
    for bad, good in [("diụ", "dịu"), ("hóa", "hoá"), ("thủy", "thuỷ"), ("meọ", "mẹo"), ("người", "người"),
                      ("của", "của"), ("giữa", "giữa"), ("quả", "quả"), ("thuyền", "thuyền"), ("ngoài", "ngoài")]:
        assert place_tone(bad) == good, (bad, place_tone(bad))


def test_drop_facing_page_slivers_keeps_poems():
    from pdf2docx_engine.recognition.diacritic_fusion import drop_facing_page_slivers
    body = "Gatsby nhanh chóng rơi vào sự lãng quên với Gatsby của Gatsby tưởng như có rất nhiều bạn bè và không có ai"
    sliver = "n với Gatsby,\ni của Gatsby,\nt tưởng như\nà và không"
    poem = "Trúc nhớ mai, mai về trúc nhớ\nTrúc trở về, mai nhớ trúc không?\nGió đưa cây cải về trời"
    md = f"{body}\n\n{sliver}\n\n{poem}\n\n{poem}"
    out, removed = drop_facing_page_slivers(md, set())
    assert len(removed) == 1 and "n với Gatsby,\n" not in out and out.count("Trúc nhớ mai") == 2
