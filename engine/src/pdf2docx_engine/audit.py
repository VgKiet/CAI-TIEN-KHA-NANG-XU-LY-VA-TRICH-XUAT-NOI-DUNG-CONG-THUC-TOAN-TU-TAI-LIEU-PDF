"""Kiểm tra tự động sau khi chạy pipeline -> ghi `audit.json` + in danh sách chỗ cần người xem.

Ba phép kiểm tra (đều offline):
1. dropped_pages      : đọc log MinerU, tìm trang bị `dropped=N` (khối bị bỏ = nội dung thiếu).
2. numbering_gaps     : đề bài/ý nhỏ nhảy số ("Bài 53" mất, "11a) 11c)" thiếu b) ...).
3. docx_math_failures : quét document.xml của DOCX, tìm LaTeX còn sót thành chữ thường
                        (\\frac, \\left, $...) = công thức Pandoc không đổi được sang Equation.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

_DROP = re.compile(r"page_idx=(\d+).*?dropped=(\d+)")
_PART = re.compile(r"part_\d+_p(\d+)-(\d+)")


def dropped_pages(run_dir: Path) -> list[dict]:
    """Trả [{page, dropped}] với page là số trang PDF (đếm từ 1)."""
    out = []
    logs = sorted(run_dir.glob("mineru_parts/out/*/mineru_log.txt"))
    if not logs:
        logs = sorted(run_dir.rglob("mineru_log.txt"))
    for log in logs:
        m = _PART.search(log.parent.name)
        start = int(m.group(1)) if m else 1
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            d = _DROP.search(line)
            if d and int(d.group(2)) > 0:
                out.append({"page": start + int(d.group(1)), "dropped": int(d.group(2))})
    return sorted(out, key=lambda r: r["page"])


def numbering_gaps(md: str) -> list[dict]:
    gaps = []
    lines = md.split("\n")
    # 1) "Bài N." / "Câu N." phải tăng dần
    pat = re.compile(r"^\s*(?:\*\*)?(Bài|Câu)\s+(\d{1,3})\s*[.:)]")
    last = {}
    for i, l in enumerate(lines):
        m = pat.match(l)
        if not m:
            continue
        kind, n = m.group(1), int(m.group(2))
        prev = last.get(kind)
        if prev is not None and n != prev + 1 and not (n == 1):
            gaps.append({"line": i + 1, "type": "nhảy số", "detail": f"{kind} {prev} -> {kind} {n}",
                         "Số lỗi": max(1, n - prev - 1)})
        last[kind] = n
    # 2) ý nhỏ a) b) c) trong cùng một câu: thiếu chữ cái ở giữa
    sub = re.compile(r"^\s*(?:\*\*)?(?:\d{1,3}[.)]\s*)?([a-h])\)")
    seq, start = [], 0
    for i, l in enumerate(lines + ["Bài 0."]):
        if pat.match(l) or re.match(r"^\s*(?:\*\*)?\d{1,3}\.\s", l) or i == len(lines):
            letters = [c for _, c in seq]
            for a, b in zip(letters, letters[1:]):
                if ord(b) - ord(a) > 1:
                    missing = "".join(chr(x) + ")" for x in range(ord(a) + 1, ord(b)))
                    gaps.append({"line": seq[letters.index(b)][0] + 1, "type": "thiếu ý",
                                 "detail": f"có {a}) rồi {b}) nhưng thiếu {missing}",
                                 "Số lỗi": ord(b) - ord(a) - 1})
            seq = []
            continue
        m = sub.match(l)
        if m:
            seq.append((i, m.group(1)))
    seen, uniq = set(), []
    for g in gaps:
        k = (g["line"], g["type"], g["detail"])
        if k not in seen:
            seen.add(k); uniq.append(g)
    for gap in uniq:
        gap.setdefault("Số lỗi", 1)
    return uniq

#  "numbering_gaps": [
#     {
#       "line": 13,
#       "type": "nhảy số",
#       "detail": "Câu 1 -> Câu 3",
#       "Số lỗi": 1
#     },
#     {
#       "line": 23,
#       "type": "nhảy số",
#       "detail": "Câu 3 -> Câu 5",
#       "Số lỗi": 2
#     },

_LEFTOVER = re.compile(r"\\(?:frac|left|right|begin|end|sqrt|sum|int|mathbf|mathrm|cdot|leq|geq|Leftrightarrow)\b|\$[^$]{1,80}\$")


def docx_math_failures(docx_path: Path, limit: int = 50) -> dict:
    """Đếm Equation thật (m:oMath) và liệt kê đoạn còn LaTeX thô."""
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    n_math = len(re.findall(r"<m:oMath[ >]", xml))
    bad = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        # chỉ lấy chữ thường (w:t) nằm NGOÀI m:oMath
        body = re.sub(r"<m:oMath[ >].*?</m:oMath>", "", p, flags=re.S)
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", body))
        if _LEFTOVER.search(text):
            bad.append(text[:140])
    return {"equations": n_math, "raw_latex_paragraphs": len(bad), "samples": bad[:limit]}


def run_audit(run_dir: Path, md_text: str, docx_path: Path | None = None) -> dict:
    rep = {
        "dropped_pages": dropped_pages(run_dir),
        "numbering_gaps": numbering_gaps(md_text),
    }
    if docx_path and Path(docx_path).exists():
        rep["docx"] = docx_math_failures(Path(docx_path))
        # So sánh định lượng giữa PDF gốc và DOCX
        pdf_path = _find_source_pdf(run_dir)
        comparison = compare_pdf_docx(
            pdf_path,
            Path(docx_path),
            md_text=md_text,
            dropped=rep["dropped_pages"],
        )
        rep["comparison"] = comparison["comparison"]
        (run_dir / "compare.json").write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    
    (run_dir / "audit.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep

# So sánh định lượng giữa PDF gốc và DOCX
def _find_source_pdf(run_dir: Path) -> Path | None:
    """Tìm PDF đầu vào trong thư mục chạy, ưu tiên file nằm ngay thư mục gốc."""
    direct = sorted(run_dir.glob("*.pdf"))
    if direct:
        return direct[0]
    candidates = sorted(p for p in run_dir.rglob("*.pdf") if "mineru_parts" not in p.parts)
    return candidates[0] if candidates else None


def _missing_numbers(md_text: str) -> list[int]:
    missing = set()
    for gap in numbering_gaps(md_text):
        match = re.search(r"(?:Bài|Câu)\s+(\d+)\s*->\s*(?:Bài|Câu)\s+(\d+)", gap["detail"])
        if match:
            previous, current = map(int, match.groups())
            missing.update(range(previous + 1, current))
    return sorted(missing)


def compare_pdf_docx(
    pdf_path: Path | None,
    docx_path: Path,
    *,
    md_text: str = "",
    dropped: list[dict] | None = None,
) -> dict:
    """Tạo báo cáo so sánh định lượng giữa PDF gốc và DOCX chuyển đổi."""
    pdf_pages = 0
    if pdf_path and Path(pdf_path).exists():
        try:
            try:
                from pypdf import PdfReader
            except ImportError:  # pragma: no cover - phụ thuộc môi trường
                from PyPDF2 import PdfReader
            pdf_pages = len(PdfReader(str(pdf_path)).pages)
        except Exception:
            pdf_pages = 0

    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paragraphs = len(re.findall(r"<w:p(?:\s|>)", xml))
    equations = len(re.findall(r"<m:oMath(?:\s|>)", xml))
    warnings = [
        {"page": page, "type": "possible_missing_content"}
        for page in sorted({int(item["page"]) for item in (dropped or [])})
    ]
    return {
        "comparison": {
            "pdf_pages": pdf_pages,
            "docx_paragraphs": paragraphs,
            "docx_equations": equations,
            "missing_numbering": _missing_numbers(md_text),
            "warnings": warnings,
        }
    }
# Hết so sánh định lượng giữa PDF gốc và DOCX

def print_audit(rep: dict) -> None:
    dp = rep["dropped_pages"]
    print(f"[audit] trang MinerU bỏ khối: {len(dp)}"
          + (" -> " + ", ".join(f"tr.{r['page']}(-{r['dropped']})" for r in dp[:20]) if dp else ""))
    ng = rep["numbering_gaps"]
    print(f"[audit] chỗ nhảy số/thiếu ý: {len(ng)}")
    for g in ng[:15]:
        print(f"   dòng {g['line']}: {g['type']} - {g['detail']}")
    if "docx" in rep:
        d = rep["docx"]
        print(f"[audit] DOCX: {d['equations']} Equation | đoạn còn LaTeX thô: {d['raw_latex_paragraphs']}")
        for s in d["samples"][:5]:
            print("   ", s)
    print("[audit] chi tiết trong audit.json -> mở đúng các trang/dòng trên để đối chiếu với PDF.")
