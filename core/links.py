"""
links.py -- OCR reads URLs off stylized slides, so the extracted link is often
truncated, a placeholder, or simply wrong. A vault full of dead links is worse
than a vault with none, so every link gets one cheap liveness check and, if it
fails, one model-assisted repair attempt.

Returns a status that lands in the note's frontmatter:
  ok         reachable as extracted
  repaired   the model supplied a reachable replacement
  dead       nothing reachable found (link kept, flagged)
  skipped    verification disabled
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from . import llm

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PLACEHOLDERS = {
    "example.com", "example.com/", "yourdomain.com", "site.com",
    "github.com", "github.com/", "github.com/owner/repo", "github.com/user/repo",
    "github.com/username/repo", "owner/repo", "link in bio", "linkinbio",
}

REPAIR_PROMPT = """A URL was read out of an image by OCR and does not resolve. Using the context,
give the single correct, currently-live URL for the thing being described.

Rules:
- Output STRICT JSON: {"url": "domain.com/path"} -- no scheme, no tracking params.
- If you are not confident the URL is real, output {"url": ""}.
- Never invent a plausible-looking path. An empty answer is correct and useful.
"""


def preclean(link: str) -> str:
    link = (link or "").strip().strip("<>()[],.\"' ")
    link = re.sub(r"^https?://", "", link, flags=re.I)
    link = re.sub(r"^www\.", "", link, flags=re.I)
    link = link.rstrip("/")
    return link


def is_placeholder(link: str) -> bool:
    l = preclean(link).lower()
    return (not l) or l in PLACEHOLDERS or "/" not in l and "." not in l


def alive(link: str, timeout: float = 8.0) -> bool:
    url = "https://" + preclean(link)
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return 200 <= r.status < 400
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 429):      # bot-blocked, not dead
                return True
            if e.code == 404:
                return False
        except Exception:
            continue
    return False


def _repair(link: str, topic: str, entities: list, context: str, cfg: dict) -> str:
    user = "Broken/uncertain link: %s\nTopic: %s\nNamed in the post: %s\n\nContext:\n%s" % (
        link, topic, ", ".join(entities or [])[:300], (context or "")[:2500],
    )
    try:
        out = llm.json_call(REPAIR_PROMPT, user, cfg, retries=0)
        return preclean(out.get("url") or "")
    except Exception:
        return ""


def verify(link: str, cfg: dict, topic: str = "", entities=None, context: str = ""):
    """-> (link, status). Never raises."""
    if not cfg.get("verify_links", True):
        return preclean(link), "skipped"
    link = preclean(link)
    if not link:
        return "", "skipped"

    if not is_placeholder(link) and alive(link):
        return link, "ok"

    guess = _repair(link, topic, entities, context, cfg)
    if guess and guess != link and alive(guess):
        return guess, "repaired"
    return ("", "dead") if is_placeholder(link) else (link, "dead")
