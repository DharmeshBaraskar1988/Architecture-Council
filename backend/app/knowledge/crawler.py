"""Crawler (task 1.7): fetches allowlisted official pages and stores their text with URL and fetch date.

Only domains in config/sources.yaml are fetched, robots.txt is respected, and each domain is rate
limited. A redirect that leaves the allowlist is refused. Every page is stored as one JSON file in
data/sources/pages/, so a citation can always be traced to the exact text that was read and when.

Plain httpx and an HTML-to-text pass from the standard library, instead of Crawl4AI: Crawl4AI needs
a headless browser (Playwright) that official docs pages do not need. Pages that only render with
JavaScript come back too short and are reported as failed, never stored as evidence.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel

from app.config import config, data_dir, load_dir

MIN_TEXT = 200          # shorter than this is a shell page (JavaScript-only, cookie wall): not evidence


class Page(BaseModel):
    id: str
    url: str                      # as listed in the catalog
    final_url: Optional[str] = None
    domain: str
    ok: bool
    status: Optional[int] = None
    title: str = ""
    text: str = ""
    content_type: str = ""
    content_hash: str = ""
    fetched_at: str
    error: Optional[str] = None
    capture: Literal["crawler", "manual"] = "crawler"   # manual: a person saved the page from a browser


def page_id(url: str) -> str:
    return "pg-" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:12]


def store_dir() -> Path:
    return data_dir() / "sources" / "pages"


def allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme == "https" and any(host == d or host.endswith("." + d) for d in config("sources")["domains"])


def load_page(url: str) -> Optional[Page]:
    p = store_dir() / f"{page_id(url)}.json"
    return Page.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def save_page(page: Page) -> None:
    store_dir().mkdir(parents=True, exist_ok=True)
    (store_dir() / f"{page.id}.json").write_text(page.model_dump_json(indent=1), encoding="utf-8")


def is_stale(page: Page, max_age_days: Optional[int] = None) -> bool:
    days = max_age_days if max_age_days is not None else config("sources").get("max_age_days", 90)
    return datetime.now(timezone.utc) - datetime.fromisoformat(page.fetched_at) > timedelta(days=days)


# ---------- HTML to text ----------

_SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "button", "iframe", "template", "select"}
_BLOCK = {"p", "div", "section", "article", "main", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
          "table", "ul", "ol", "dd", "dt", "pre", "blockquote", "header"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n")
            if tag in ("h1", "h2", "h3"):
                self.parts.append("## ")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text) with scripts, navigation and footers removed and whitespace collapsed."""
    p = _Text()
    p.feed(html)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in lines if ln not in ("", "|", "## ")))
    return " ".join(p.title.split()), text.strip()


def pdf_to_text(data: bytes) -> tuple[str, str]:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    title = (r.metadata.title if r.metadata and r.metadata.title else "") or ""
    return title, "\n\n".join((pg.extract_text() or "").strip() for pg in r.pages)


# ---------- fetching ----------

class Crawler:
    """One crawler per run: shares the HTTP client, robots.txt answers and per-domain rate limits."""

    def __init__(self, client: Optional[httpx.Client] = None):
        cfg = config("sources")
        self.agent = cfg.get("user_agent", "council-crawler/0.1")
        self.client = client or httpx.Client(timeout=cfg.get("timeout_seconds", 30), follow_redirects=False,
                                             headers={"User-Agent": self.agent, "Accept-Language": "en"})
        self.gap = 60.0 / max(1, cfg.get("rate_limit_per_domain_per_minute", 20))
        self.respect_robots = cfg.get("respect_robots_txt", True)
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            due = self._last.get(host, 0.0) + self.gap
            self._last[host] = max(now, due)
        if due > now:
            time.sleep(due - now)

    def robots_allow(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        u = urlparse(url)
        if u.netloc not in self._robots:
            rp: Optional[RobotFileParser] = RobotFileParser()
            try:
                r = self.client.get(f"{u.scheme}://{u.netloc}/robots.txt", follow_redirects=True)
                if r.status_code >= 400:
                    rp = None                                    # no robots.txt: everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[u.netloc] = rp
        rp = self._robots[u.netloc]
        return rp is None or rp.can_fetch(self.agent, url)

    def get(self, url: str, max_redirects: int = 5) -> httpx.Response:
        """GET that follows redirects only while they stay on the allowlist."""
        for _ in range(max_redirects + 1):
            if not allowed(url):
                raise PermissionError(f"not on the allowlist: {url}")
            if not self.robots_allow(url):
                raise PermissionError(f"robots.txt disallows: {url}")
            self._wait(urlparse(url).netloc)
            r = self.client.get(url)
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            return r
        raise httpx.TooManyRedirects(f"too many redirects: {url}")

    def fetch(self, url: str) -> Page:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        page = Page(id=page_id(url), url=url, domain=(urlparse(url).hostname or ""), ok=False, fetched_at=now)
        try:
            r = self.get(url)
        except (PermissionError, httpx.HTTPError) as e:
            return page.model_copy(update={"error": str(e)[:300]})
        ctype = r.headers.get("content-type", "").split(";")[0].strip()
        page = page.model_copy(update={"status": r.status_code, "final_url": str(r.url), "content_type": ctype})
        if r.status_code >= 400:
            return page.model_copy(update={"error": f"HTTP {r.status_code}"})
        if "pdf" in ctype:
            title, text = pdf_to_text(r.content)
        elif "json" in ctype:
            title, text = "", r.text
        else:
            title, text = html_to_text(r.text)
        if len(text) < MIN_TEXT:
            return page.model_copy(update={"title": title, "text": text,
                                           "error": f"Only {len(text)} characters of text (page needs JavaScript or is blocked)"})
        return page.model_copy(update={"ok": True, "title": title, "text": text,
                                       "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()})

    def close(self) -> None:
        self.client.close()


def capture_file(url: str, path: Path) -> Page:
    """Store a page a person saved from their browser (HTML, PDF or text), for official sites that
    block automated clients. The URL must still be on the allowlist; the page is marked `manual`."""
    if not allowed(url):
        raise PermissionError(f"not on the allowlist: {url}")
    data = Path(path).read_bytes()
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        title, text = pdf_to_text(data)
    elif suffix in (".html", ".htm", ".mhtml"):
        title, text = html_to_text(data.decode("utf-8", errors="replace"))
    else:
        title, text = "", data.decode("utf-8", errors="replace")
    if len(text) < MIN_TEXT:
        raise ValueError(f"only {len(text)} characters of text in {path}: save the full page")
    page = Page(id=page_id(url), url=url, final_url=url, domain=(urlparse(url).hostname or ""), ok=True,
                title=title or Path(path).stem, text=text, content_type=f"saved{suffix}",
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(), capture="manual",
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    save_page(page)
    return page


def crawl(urls: Iterable[str], refresh: bool = False, crawler: Optional[Crawler] = None,
          workers: int = 6) -> list[Page]:
    """Fetch every URL not already stored (or stale, or all with refresh). Failed fetches are stored
    too, so the report shows them; a failed page is never evidence."""
    from concurrent.futures import ThreadPoolExecutor
    urls = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))
    own = crawler is None
    crawler = crawler or Crawler()

    def one(url: str) -> Page:
        old = load_page(url)
        if old and old.ok and not is_stale(old) and (not refresh or old.capture == "manual"):
            return old                                    # a fresh manual capture is never overwritten
        page = crawler.fetch(url)
        if not page.ok and old and old.ok:
            return old.model_copy(update={"error": f"re-fetch failed, kept copy from {old.fetched_at}: {page.error}"})
        save_page(page)
        return page

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, urls))
    finally:
        if own:
            crawler.close()


def catalog_urls() -> dict[str, list[str]]:
    """Every URL the catalogs cite, with what cites it."""
    out: dict[str, list[str]] = {}
    for fw in load_dir("frameworks"):
        for s in fw.get("sources", []):
            out.setdefault(s["url"], []).append(f"framework {fw['id']}")
    for cap in load_dir("solutions"):
        for c in cap.get("candidates", []):
            for kind, url in (c.get("pages") or {}).items():
                out.setdefault(url, []).append(f"{cap['capability']}/{c['id']} {kind}")
    return out


# ---------- reading stored pages ----------

def passages(text: str, size: int = 900) -> list[str]:
    """Split a page into passages of about `size` characters on paragraph boundaries."""
    out, cur = [], ""
    for para in text.split("\n"):
        if cur and len(cur) + len(para) > size:
            out.append(cur.strip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out


_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = set("the and for with that this from are was were has have not but you your our their its can will "
            "should must into than then them they all any use used using per via also may each more most".split())


def best_passage(text: str, query: str, size: int = 900) -> str:
    """The passage that shares the most words with the query (plain word overlap, no model)."""
    q = {w for w in _WORD.findall(query.lower()) if w not in _STOP}
    ps = passages(text, size)
    if not ps:
        return ""
    return max(ps, key=lambda p: (len(q & set(_WORD.findall(p.lower()))), -ps.index(p)))


def report(pages: list[Page], used_by: dict[str, list[str]]) -> dict:
    return {"fetched": sum(p.ok for p in pages), "failed": sum(not p.ok for p in pages),
            "pages": [{"url": p.url, "ok": p.ok, "status": p.status, "title": p.title[:120], "chars": len(p.text),
                       "fetched_at": p.fetched_at, "capture": p.capture, "error": p.error,
                       "used_by": used_by.get(p.url, [])} for p in pages]}


def write_report(rep: dict) -> Path:
    path = data_dir() / "sources" / "crawl_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
