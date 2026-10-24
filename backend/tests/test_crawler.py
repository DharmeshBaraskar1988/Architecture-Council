from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.knowledge import crawler
from app.knowledge.crawler import Crawler, Page, best_passage, crawl, html_to_text, load_page, page_id

HTML = """<html><head><title>Config | Twelve-Factor</title><script>var x = 1;</script></head>
<body><nav>Home About</nav><h1>III. Config</h1><p>Store config in the environment.</p>
<table><tr><td>a</td><td>b</td></tr></table>""" + "<p>" + "More words about config. " * 20 + "</p><footer>Copyright</footer></body></html>"


def _crawler(routes: dict[str, httpx.Response]) -> Crawler:
    def handler(req: httpx.Request) -> httpx.Response:
        return routes.get(str(req.url), httpx.Response(404))
    c = Crawler(httpx.Client(transport=httpx.MockTransport(handler)))
    c.gap = 0
    return c


def test_html_to_text_drops_scripts_navigation_and_footers():
    title, text = html_to_text(HTML)
    assert title == "Config | Twelve-Factor"
    assert "## III. Config" in text and "Store config in the environment." in text and "a | b" in text
    assert "var x" not in text and "Home About" not in text and "Copyright" not in text


def test_allowlist():
    assert crawler.allowed("https://12factor.net/config")
    assert crawler.allowed("https://docs.aws.amazon.com/x")             # subdomain of an allowlisted domain
    assert not crawler.allowed("https://example.com/")
    assert not crawler.allowed("http://12factor.net/")                  # https only
    assert not crawler.allowed("https://12factor.net.evil.com/")


def test_fetch_stores_page_with_url_and_date():
    c = _crawler({"https://12factor.net/robots.txt": httpx.Response(404),
                  "https://12factor.net/config": httpx.Response(200, html=HTML)})
    [p] = crawl(["https://12factor.net/config"], crawler=c)
    assert p.ok and p.status == 200 and p.title.startswith("Config") and p.content_hash
    stored = load_page("https://12factor.net/config")
    assert stored.text == p.text and stored.fetched_at and stored.capture == "crawler"


def test_redirect_off_the_allowlist_is_refused():
    c = _crawler({"https://12factor.net/robots.txt": httpx.Response(404),
                  "https://12factor.net/go": httpx.Response(302, headers={"location": "https://example.com/x"})})
    p = c.fetch("https://12factor.net/go")
    assert not p.ok and "allowlist" in p.error


def test_robots_txt_is_respected():
    c = _crawler({"https://12factor.net/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /private"),
                  "https://12factor.net/private/x": httpx.Response(200, html=HTML)})
    p = c.fetch("https://12factor.net/private/x")
    assert not p.ok and "robots.txt" in p.error


def test_short_or_javascript_only_page_is_not_evidence():
    c = _crawler({"https://12factor.net/robots.txt": httpx.Response(404),
                  "https://12factor.net/js": httpx.Response(200, html="<html><body><div id=app></div></body></html>")})
    p = c.fetch("https://12factor.net/js")
    assert not p.ok and "JavaScript" in p.error


def test_fresh_copy_is_reused_and_failed_refetch_keeps_it():
    url = "https://12factor.net/config"
    c = _crawler({"https://12factor.net/robots.txt": httpx.Response(404), url: httpx.Response(200, html=HTML)})
    first = crawl([url], crawler=c)[0]
    assert crawl([url], crawler=_crawler({}))[0].fetched_at == first.fetched_at     # fresh: not fetched again
    kept = crawl([url], refresh=True, crawler=_crawler({}))[0]                      # refresh fails: keep the copy
    assert kept.ok and "re-fetch failed" in kept.error


def test_stale_pages():
    old = Page(id=page_id("u"), url="u", domain="d", ok=True, fetched_at=(datetime.now(timezone.utc) - timedelta(days=200)).isoformat())
    assert crawler.is_stale(old) and not crawler.is_stale(old, max_age_days=365)


def test_manual_capture(tmp_path):
    f = tmp_path / "page.html"
    f.write_text(HTML, encoding="utf-8")
    p = crawler.capture_file("https://openai.com/api/pricing/", f)
    assert p.ok and p.capture == "manual" and load_page("https://openai.com/api/pricing/").capture == "manual"
    with pytest.raises(PermissionError):
        crawler.capture_file("https://example.com/", f)


def test_best_passage_finds_the_matching_paragraph():
    text = "\n".join(["Unrelated words here."] * 60 + ["Store config in environment variables."] + ["Filler."] * 60)
    assert "environment variables" in best_passage(text, "config belongs in environment variables", size=200)
