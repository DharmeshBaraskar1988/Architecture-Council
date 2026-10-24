"""Live gate verifier (task 1.10): fetches the evidence behind every catalog candidate.

For every candidate, every page listed in the catalog (official, pricing, terms, SLA) must be stored
by the crawler from an allowlisted domain; only then is the candidate `verified`. For open source,
code also reads, instead of trusting what was typed in:
  - the licence, archive state and last push from the GitHub API (maintained = not archived and
    pushed in the last 12 months), plus the OpenSSF Scorecard score as a security signal
  - the licence of model weights from the Hugging Face model card
For services, an official page whose title says preview or beta turns the lifecycle to preview.

Results go to data/catalog/verification.json; the gate merges them over the recorded fields.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from app.config import config, data_dir, load_dir
from app.knowledge import crawler

MAINTAINED_DAYS = 365
_PREVIEW = re.compile(r"\b(preview|beta)\b", re.I)


def path() -> Path:
    return data_dir() / "catalog" / "verification.json"


def load() -> dict[str, dict]:
    """Verification results by candidate id ({} when `council verify` has not run)."""
    p = path()
    return json.loads(p.read_text(encoding="utf-8"))["candidates"] if p.exists() else {}


def spdx(licence: Optional[str]) -> Optional[str]:
    """Normalise a licence id to the spelling used in config/license_policy.yaml (apache-2.0 → Apache-2.0)."""
    if not licence:
        return None
    pol = config("license_policy")
    known = {x.lower(): x for key in ("allowed", "review_needed", "blocked", "model_licences_allowed") for x in pol.get(key, [])}
    return known.get(licence.lower(), licence)


def same_licence(a: Optional[str], b: Optional[str]) -> bool:
    """GPL-family ids with and without the -only suffix name the same licence (GitHub returns the old form)."""
    norm = lambda x: (spdx(x) or "").lower().removesuffix("-only")       # noqa: E731
    return norm(a) == norm(b)


class Signals:
    """Calls to official APIs (GitHub, Hugging Face, OpenSSF). These are APIs, not crawled pages, so
    robots.txt does not apply, but the allowlist still does."""

    def __init__(self, client: Optional[httpx.Client] = None):
        headers = {"User-Agent": config("sources").get("user_agent", "council"), "Accept": "application/json"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
        self.client = client or httpx.Client(timeout=30, headers=headers, follow_redirects=True)

    def _json(self, url: str) -> tuple[Optional[dict], Optional[str]]:
        if not crawler.allowed(url):
            return None, f"not on the allowlist: {url}"
        try:
            r = self.client.get(url)
        except httpx.HTTPError as e:
            return None, str(e)[:200]
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} from {url}"
        return r.json(), None

    def github(self, repo: str) -> dict:
        j, err = self._json(f"https://api.github.com/repos/{repo}")
        if err:
            return {"error": err}
        pushed = j.get("pushed_at")
        recent = bool(pushed) and datetime.now(timezone.utc) - datetime.fromisoformat(pushed.replace("Z", "+00:00")) \
            < timedelta(days=MAINTAINED_DAYS)
        lic = (j.get("license") or {}).get("spdx_id")
        out = {"licence": None if lic in (None, "NOASSERTION", "OTHER") else lic, "archived": bool(j.get("archived")),
               "pushed_at": pushed, "maintained": recent and not j.get("archived"), "stars": j.get("stargazers_count"),
               "url": f"https://github.com/{repo}"}
        sc, err = self._json(f"https://api.securityscorecards.dev/projects/github.com/{repo}")
        out["scorecard"] = sc.get("score") if sc else None
        return out

    def huggingface(self, model: str) -> dict:
        j, err = self._json(f"https://huggingface.co/api/models/{model}")
        if err:
            return {"error": err}
        lic = (j.get("cardData") or {}).get("license") or next(
            (t.split(":", 1)[1] for t in j.get("tags", []) if t.startswith("license:")), None)
        return {"licence": spdx(lic), "url": f"https://huggingface.co/{model}"}

    def close(self) -> None:
        self.client.close()


def verify_candidate(c: dict, pages: dict[str, crawler.Page], sig: Signals) -> dict:
    out: dict = {"pages": {}, "overrides": {}, "notes": [], "signals": {}}
    for kind, url in (c.get("pages") or {}).items():
        p = pages.get(url)
        out["pages"][kind] = {"url": url, "ok": bool(p and p.ok and not crawler.is_stale(p)),
                              "title": p.title[:150] if p else "", "fetched_at": p.fetched_at if p else None,
                              "capture": p.capture if p else None, "error": (p.error if p else "not fetched")}
    missing = [k for k, v in out["pages"].items() if not v["ok"]]
    if missing:
        out["notes"].append("Pages not stored: " + ", ".join(f"{k} ({out['pages'][k]['error']})" for k in missing))
    official = out["pages"].get("official")
    if c.get("type") in ("cloud_managed", "saas") and official and official["ok"] and _PREVIEW.search(official["title"]):
        out["overrides"]["lifecycle"] = "preview"
        out["notes"].append(f"Official page title says preview or beta: “{official['title']}”")

    if c.get("repo"):
        gh = sig.github(c["repo"])
        out["signals"]["github"] = gh
        if gh.get("error"):
            out["notes"].append(f"GitHub: {gh['error']}")
            missing.append("github")
        else:
            out["overrides"]["maintained"] = gh["maintained"]
            if not gh["maintained"]:
                out["notes"].append("Archived" if gh["archived"] else f"No push since {gh['pushed_at'][:10]}")
            if not c.get("model"):                  # for a model, the weights' licence is what counts
                if gh["licence"]:
                    out["overrides"]["licence"] = gh["licence"]
                    if c.get("licence") and not same_licence(c["licence"], gh["licence"]):
                        out["notes"].append(f"Recorded licence {c['licence']} differs from GitHub's {gh['licence']}: GitHub's is used")
                elif c.get("licence"):
                    out["notes"].append(f"GitHub could not name the licence; recorded {c['licence']} kept (see the terms page)")
    if c.get("model"):
        hf = sig.huggingface(c["model"])
        out["signals"]["huggingface"] = hf
        if hf.get("error"):
            out["notes"].append(f"Hugging Face: {hf['error']}")
            missing.append("huggingface")
        elif hf.get("licence"):
            out["overrides"]["licence"] = hf["licence"]
            if c.get("licence") and not same_licence(c["licence"], hf["licence"]):
                out["notes"].append(f"Recorded licence {c['licence']} differs from the model card's {hf['licence']}: the model card's is used")
    out["verified"] = not missing and bool(out["pages"])
    return out


def verify_catalog(refresh: bool = False, crawl: Optional[crawler.Crawler] = None,
                   sig: Optional[Signals] = None) -> dict:
    """Crawl every candidate page (stored fresh copies are reused) and verify every candidate."""
    caps = load_dir("solutions")
    urls = [u for cap in caps for c in cap.get("candidates", []) for u in (c.get("pages") or {}).values()]
    pages = {p.url: p for p in crawler.crawl(urls, refresh=refresh, crawler=crawl)}
    own = sig is None
    sig = sig or Signals()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        results = {c["id"]: {"capability": cap["capability"], "checked_at": now, **verify_candidate(c, pages, sig)}
                   for cap in caps for c in cap.get("candidates", []) if c.get("type") not in ("none", "owned")}
    finally:
        if own:
            sig.close()
    doc = {"checked_at": now, "candidates": results}
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc
