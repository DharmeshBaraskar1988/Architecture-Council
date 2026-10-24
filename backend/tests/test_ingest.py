from pathlib import Path

from app.knowledge.ingest import chunk, load_document

FIXTURES = Path(__file__).parent / "fixtures"


def test_markdown_page_markers():
    doc = load_document(FIXTURES / "s1_financial_briefing.md")
    assert [p.number for p in doc.pages] == [1, 2, 3, 4]
    assert doc.page_text(1).startswith("# BriefCast")
    assert "five developers" in doc.page_text(2)


def test_chunks_never_cross_pages():
    doc = load_document(FIXTURES / "s2_shopsphere.md")
    for c in chunk(doc, max_chars=80, overlap=10):
        assert c.text in doc.page_text(c.page)


def test_docx_roundtrip(tmp_path: Path):
    import docx
    d = docx.Document()
    d.add_paragraph("The engineering team has six developers.")
    p = tmp_path / "x.docx"
    d.save(p)
    doc = load_document(p)
    assert "six developers" in doc.full_text


def test_unsupported_type(tmp_path: Path):
    p = tmp_path / "x.xlsx"; p.write_text("x")
    try:
        load_document(p)
        assert False
    except ValueError as e:
        assert "unsupported" in str(e)


def test_html_sections_by_heading(tmp_path: Path):
    p = tmp_path / "prd.html"
    p.write_text("<html><head><title>x</title><style>p{color:red}</style></head><body>"
                 "<h1>ShopSphere</h1><p>An online marketplace.</p>"
                 "<h2>Team</h2><p>The engineering team has <b>six</b> developers.</p><script>var x=1</script>"
                 "<h2>Data</h2><table><tr><td>Region</td><td>India</td></tr></table></body></html>", encoding="utf-8")
    doc = load_document(p)
    assert [pg.title for pg in doc.pages] == ["ShopSphere", "Team", "Data"]
    assert "six developers" in doc.page_text(2)
    assert "var x" not in doc.full_text and "color:red" not in doc.full_text
    assert "India" in doc.page_text(3)


def test_markdown_without_markers_splits_at_headings(tmp_path: Path):
    p = tmp_path / "prd.md"
    p.write_text("# Product\nIntro.\n\n## Users\nAll users are in India.\n\n### Detail\nmore\n\n## Budget\nSmall.", encoding="utf-8")
    doc = load_document(p)
    assert [pg.title for pg in doc.pages] == ["Product", "Users", "Budget"]
    assert "Detail" in doc.page_text(2)


def test_page_titles_from_markers():
    doc = load_document(FIXTURES / "s1_financial_briefing.md")
    assert doc.pages[0].title.startswith("BriefCast") and doc.pages[1].title
