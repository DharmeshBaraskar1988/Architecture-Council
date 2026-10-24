from app.factcheck.quotes import find_quote, normalise
from app.knowledge.ingest import Document, Page

DOC = Document("t", [Page(1, "Intro text."), Page(2, "The engineering team has “six” developers — all in Pune.")])


def test_exact_quote_on_claimed_page():
    r = find_quote(DOC, 'The engineering team has "six" developers', 2)
    assert r.found and r.page == 2 and r.page_matches_claim


def test_wrong_page_is_corrected():
    r = find_quote(DOC, "the engineering team has \"six\" developers", 1)
    assert r.found and r.page == 2 and not r.page_matches_claim


def test_ellipsis_parts_in_order():
    assert find_quote(DOC, "engineering team ... all in Pune", 2).found
    assert not find_quote(DOC, "all in Pune ... engineering team", 2).found


def test_invented_quote_not_found():
    assert not find_quote(DOC, "The team has ten developers", 2).found


def test_normalise_dashes_and_quotes():
    assert normalise("A — “B”") == normalise('a - "b"')
