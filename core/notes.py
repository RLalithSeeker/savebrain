"""
notes.py -- writing the vault.

Two shapes of output, because two kinds of post exist:

  deep post   video, multi-slide carousel, or 5+ key points
              -> its own file, full structure, cross-linked
  short find   a product, a link, a one-line idea
              -> appended to that category's weekly file, so the vault does not
                 fill up with 40-word notes

Everything is plain Markdown with YAML frontmatter and [[wiki-links]]: it opens
in Obsidian, Logseq, VS Code, or nothing at all.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import config


def slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "").lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:maxlen] or "untitled"


def iso_week(date_str: str) -> str:
    try:
        d = dt.datetime.fromisoformat((date_str or "")[:19].replace("Z", ""))
    except Exception:
        d = dt.datetime.now()
    y, w, _ = d.isocalendar()
    return "%d-W%02d" % (y, w)


def is_deep(rec: dict) -> bool:
    s = rec["summary"]
    if rec.get("is_video"):
        return True
    if rec.get("is_carousel") and len(s.get("steps") or []) >= 2:
        return True
    return len(s.get("key_points") or []) >= 5 or bool(s.get("full_text_extraction"))


def _tagline(s: dict, collection: str) -> str:
    cats = s.get("categories") or ["uncategorized"]
    tags = [("#" + c) for c in cats] + [("#" + t) for t in (s.get("subtopic_tags") or [])]
    col = re.sub(r"[^\w-]", "-", (collection or "main").lower()).strip("-")
    tags.append("#from-" + col)
    return " ".join(tags)


def render_note(rec: dict) -> str:
    s = rec["summary"]
    cats = s.get("categories") or ["uncategorized"]
    lines = [
        "---",
        "date: " + (rec.get("date") or "")[:10],
        "author: " + (rec.get("author") or ""),
        "source: " + (rec.get("url") or ""),
        "categories: [%s]" % ", ".join(cats),
        "tags: [%s]" % ", ".join(s.get("subtopic_tags") or []),
        "collection: " + (rec.get("collection") or "main"),
        "primary_link: " + (s.get("primary_link") or ""),
        "link_status: " + (s.get("link_status") or "-"),
        "media: " + ("video" if rec.get("is_video") else "carousel" if rec.get("is_carousel") else "image"),
        "---",
        "",
        "# " + (s.get("topic") or "(untitled)"),
        "",
        _tagline(s, rec.get("collection")),
        "",
    ]
    if s.get("primary_link"):
        lines += ["**Go here:** " + s["primary_link"], ""]
    others = [l for l in (s.get("all_links") or []) if l != s.get("primary_link")]
    if others:
        lines += ["**Also mentioned:** " + ", ".join(others), ""]
    lines += ["**TL;DR:** " + (s.get("one_liner") or ""), ""]

    if s.get("steps"):
        lines += ["## Steps", ""]
        lines += ["%d. %s" % (i, step) for i, step in enumerate(s["steps"], 1)]
        lines.append("")
    if s.get("key_points"):
        lines += ["## Key points", ""] + ["- " + p for p in s["key_points"]] + [""]
    if s.get("entities"):
        lines += ["**Mentioned:** " + ", ".join(s["entities"]), ""]
    if s.get("snippets"):
        lines += ["## Worth copying", "", "```"] + list(s["snippets"]) + ["```", ""]
    if s.get("full_text_extraction"):
        lines += ["## Full text (verbatim)", "", s["full_text_extraction"], ""]
    if s.get("evidence"):
        lines += ["**Why it holds up:** " + s["evidence"], ""]

    lines += ["---", "_Source: [@%s](%s) - %s_" % (
        rec.get("author") or "unknown", rec.get("url") or "", (rec.get("date") or "")[:10])]
    return "\n".join(lines)


def render_bucket_entry(rec: dict) -> str:
    s = rec["summary"]
    parts = ["### %s - @%s" % (s.get("topic") or "(untitled)", rec.get("author") or "")]
    if s.get("primary_link"):
        parts.append("**" + s["primary_link"] + "**")
    parts.append("_%s - [post](%s)_" % ((rec.get("date") or "")[:10], rec.get("url") or ""))
    parts.append(_tagline(s, rec.get("collection")))
    parts.append("")
    if s.get("one_liner"):
        parts.append(s["one_liner"])
    if s.get("key_points"):
        parts += [""] + ["- " + p for p in s["key_points"]]
    if s.get("full_text_extraction"):
        parts += ["", "**Verbatim:**", "", s["full_text_extraction"]]
    parts += ["", "---", ""]
    return "\n".join(parts)


def write_notes(kept: list, cfg: dict, spec: dict):
    """-> (n_full, n_bucket, [paths of full notes])"""
    vault = config.vault_dir(cfg)
    categories = list(spec["categories"].keys())
    buckets_on = cfg.get("bucket_short_posts", True)
    bucket_cats = set(spec["bucket_categories"]) if buckets_on else set()

    for c in categories:
        (vault / c).mkdir(parents=True, exist_ok=True)
    config.digests_dir(cfg).mkdir(parents=True, exist_ok=True)

    buckets, full_paths, n_bucket = {}, [], 0
    for rec in kept:
        s = rec["summary"]
        cats = [c for c in (s.get("categories") or []) if c in spec["categories"]] or ["uncategorized"]
        s["categories"] = cats
        primary = cats[0]

        if (not is_deep(rec)) and primary in bucket_cats:
            buckets.setdefault((primary, iso_week(rec.get("date"))), []).append(render_bucket_entry(rec))
            n_bucket += 1
            continue

        name = "%s_%s_%s.md" % ((rec.get("date") or "")[:10],
                                slugify(s.get("topic")),
                                slugify(rec.get("author") or "unknown", 24))
        path = vault / primary / name
        path.write_text(render_note(rec), encoding="utf-8")
        full_paths.append(path)

    for (cat, week), entries in buckets.items():
        f = vault / cat / ("weekly_%s_%s.md" % (cat, week))
        header = ""
        if not f.exists():
            header = "# Weekly %s - %s\n\n_Short finds, collected automatically._\n\n---\n\n" % (
                cat.replace("_", " ").title(), week)
        with open(f, "a", encoding="utf-8") as fh:
            if header:
                fh.write(header)
            fh.write("\n".join(entries) + "\n")

    return len(full_paths), n_bucket, full_paths


def add_related_links(new_paths: list, cfg: dict, spec: dict) -> int:
    """Append a ## Related block linking notes that name the same entities."""
    vault = config.vault_dir(cfg)
    entity_map = {}
    for cat in spec["categories"]:
        d = vault / cat
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            if f.name.startswith("weekly_"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            m = re.search(r"\*\*Mentioned:\*\*\s*(.+)", text)
            entity_map[f] = {e.strip().lower() for e in m.group(1).split(",")} if m else set()

    linked = 0
    for p in new_paths:
        p = Path(p)
        mine = entity_map.get(p, set())
        if not mine or not p.exists():
            continue
        scored = []
        for other, theirs in entity_map.items():
            if other == p:
                continue
            overlap = len(mine & theirs)
            if overlap:
                scored.append((overlap, other.stat().st_mtime, other))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], -x[1]))
        block = "\n## Related\n" + "\n".join("- [[%s]]" % o.stem for _, _, o in scored[:5]) + "\n\n"
        text = p.read_text(encoding="utf-8")
        new = re.sub(r"\n---\n_Source: \[", block + "---\n_Source: [", text, count=1)
        if new != text:
            p.write_text(new, encoding="utf-8")
            linked += 1
    return linked


def rebuild_index(cfg: dict, spec: dict) -> Path:
    """INDEX.md (for humans) + _index/compact.md (one line per note, for an AI agent)."""
    vault = config.vault_dir(cfg)
    today = dt.date.today().isoformat()
    lines = ["# Vault index", "_Updated: %s - domains: %s_" % (today, ", ".join(spec["labels"])), ""]
    compact = ["# Compact index", "_One line per note: path | topic | link | tags_", ""]

    for cat, desc in spec["categories"].items():
        d = vault / cat
        if not d.is_dir():
            continue
        files = sorted((f for f in d.glob("*.md")), reverse=True)
        if not files:
            continue
        lines += ["## %s (%d)" % (cat, len(files)), "_%s_" % desc, ""]
        for f in files:
            lines.append("- [[%s/%s]]" % (cat, f.stem))
            try:
                head = f.read_text(encoding="utf-8")[:1400]
            except Exception:
                continue
            topic = (re.search(r"^# (.+)$", head, re.M) or [None, f.stem])[1]
            link = (re.search(r"^primary_link: (.*)$", head, re.M) or [None, ""])[1]
            tags = (re.search(r"^tags: \[(.*)\]$", head, re.M) or [None, ""])[1]
            compact.append("%s/%s | %s | %s | %s" % (cat, f.stem, topic, link.strip(), tags))
        lines.append("")

    (vault / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    idx_dir = vault / "_index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / "compact.md").write_text("\n".join(compact), encoding="utf-8")
    return vault / "INDEX.md"


def write_digest(kept: list, cfg: dict, spec: dict) -> Path:
    """A single paste-ready file: hand it to any chat model as this week's reading."""
    today = dt.date.today().isoformat()
    out = [
        "# Saved this week - %s" % today,
        "",
        "%d posts I saved, extracted and organized automatically. Domains: %s." % (
            len(kept), ", ".join(spec["labels"])),
        "",
        "Read it all, then tell me: (a) the 3 things worth acting on this week,",
        "(b) anything here that contradicts something else here, (c) what I should",
        "save more of next week.",
        "", "---", "",
    ]
    by_cat = {}
    for r in kept:
        for c in (r["summary"].get("categories") or ["uncategorized"]):
            by_cat.setdefault(c, []).append(r)

    for cat in spec["categories"]:
        if cat not in by_cat:
            continue
        out += ["", "# " + cat.upper(), ""]
        for r in by_cat[cat]:
            s = r["summary"]
            out += ["## " + (s.get("topic") or "(untitled)"),
                    "@%s - %s - %s" % (r.get("author"), (r.get("date") or "")[:10], r.get("url")), ""]
            if s.get("primary_link"):
                out += ["**" + s["primary_link"] + "**", ""]
            out += ["**TL;DR:** " + (s.get("one_liner") or ""), ""]
            if s.get("steps"):
                out += ["**Steps:**"] + ["%d. %s" % (i, x) for i, x in enumerate(s["steps"], 1)] + [""]
            if s.get("key_points"):
                out += ["**Key points:**"] + ["- " + p for p in s["key_points"]] + [""]
            if s.get("entities"):
                out += ["**Mentioned:** " + ", ".join(s["entities"]), ""]
            if s.get("snippets"):
                out += ["**Verbatim:**", "```"] + list(s["snippets"]) + ["```", ""]
            out += ["---", ""]

    d = config.digests_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("digest_%s.md" % today)
    path.write_text("\n".join(out), encoding="utf-8")
    return path
