"""
pipeline.py -- the ingest run.

Reads the raw posts the browser extension streamed into the inbox, and for each
one that has not been processed before:

    transcribe video  ->  OCR slides  ->  extract structured JSON  ->  verify link
                                                                   ->  write notes

State is a flat list of post ids in the vault (.processed.json). A post that
fails is deliberately NOT marked processed, so the next run retries it instead
of losing it -- that is what makes a quota-limited free tier survivable.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import config, domains, links, llm, media, notes, ui


def load_state(cfg) -> set:
    f = config.state_file(cfg)
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            ui.warn("state file unreadable -- treating everything as new")
    return set()


def save_state(cfg, seen: set) -> None:
    f = config.state_file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def load_inbox(path: Path) -> list:
    if not path.exists():
        ui.err("no inbox at %s" % path)
        ui.warn("run `python savebrain.py bridge`, scrape from the extension, then retry")
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def process(records, cfg, spec, do_transcribe=True, limit=None):
    """-> (kept, processed_count, deferred_count)"""
    system_prompt = domains.build_system_prompt(spec)
    seen = load_state(cfg)
    limit = limit or cfg.get("max_posts", 1000)
    ui.dim("already processed: %d - in inbox: %d" % (len(seen), len(records)))

    kept, done, deferred = [], 0, 0
    for rec in records:
        pid = rec.get("shortcode")
        if not pid or pid in seen:
            continue
        if done >= limit:
            ui.warn("hit max_posts=%d -- the rest stay queued for the next run" % limit)
            break

        kind = "carousel" if rec.get("is_carousel") else ("video" if rec.get("is_video") else "image")
        ui.info("%d. @%s (%s) %s" % (done + 1, rec.get("author", "?"), kind, rec.get("url", "")))

        transcript = ""
        if rec.get("is_video") and do_transcribe and rec.get("video_url"):
            ui.dim("   transcribing...")
            transcript = media.transcribe(rec["video_url"], cfg)

        slide_text = ""
        if rec.get("image_urls"):
            ui.dim("   reading %d slide(s)..." % len(rec["image_urls"]))
            slide_text = media.read_slides(rec["image_urls"], cfg)

        parts = ["CAPTION:\n" + (rec.get("caption") or "(empty)")]
        if transcript:
            parts.append("VIDEO TRANSCRIPT:\n" + transcript)
        if slide_text:
            parts.append("CAROUSEL SLIDES (OCR):\n" + slide_text)

        try:
            summary = llm.json_call(system_prompt, "\n\n".join(parts), cfg)
        except llm.LLMError as e:
            deferred += 1
            ui.err("   deferred (%s) -- stays queued, retried next run" % str(e)[:110])
            if e.is_quota:
                ui.warn("   provider quota reached. Stopping here so nothing is lost; "
                        "re-run later or set a fallback endpoint in config.json.")
                break
            continue

        if not summary.get("is_relevant"):
            seen.add(pid)
            save_state(cfg, seen)
            done += 1
            ui.dim("   skipped (not relevant to your domains)")
            continue

        link = links.preclean(summary.get("primary_link") or "")
        if link:
            context = "\n".join(x for x in [rec.get("caption"), slide_text, transcript] if x)
            fixed, status = links.verify(link, cfg, summary.get("topic", ""),
                                         summary.get("entities"), context)
            summary["primary_link"], summary["link_status"] = fixed, status
            if fixed != link:
                ui.warn("   link %s: %s -> %s" % (status, link, fixed or "(dropped)"))

        ui.dim("   -> %s | %s" % (", ".join(summary.get("categories") or []),
                                  (summary.get("topic") or "")[:60]))

        kept.append({
            "shortcode": pid,
            "url": rec.get("url", ""),
            "author": rec.get("author", ""),
            "date": rec.get("date") or dt.date.today().isoformat(),
            "is_video": bool(rec.get("is_video")),
            "is_carousel": bool(rec.get("is_carousel")),
            "collection": rec.get("collection", "main"),
            "summary": summary,
        })
        seen.add(pid)
        save_state(cfg, seen)
        done += 1

    return kept, done, deferred


def run_ingest(cfg, inbox_path=None, do_transcribe=True, limit=None, clear_inbox=False):
    spec = domains.spec_from_config(cfg)
    inbox = Path(inbox_path) if inbox_path else config.inbox_file(cfg)

    ui.rule("savebrain ingest")
    ui.dim("vault: %s" % config.vault_dir(cfg))
    ui.dim("domains: %s" % ", ".join(spec["labels"]))

    records = load_inbox(inbox)
    if not records:
        return 1

    kept, done, deferred = process(records, cfg, spec, do_transcribe, limit)
    ui.ok("\n%d kept of %d new posts" % (len(kept), done))
    if deferred:
        ui.warn("%d post(s) deferred -- they stay in the inbox and retry next run" % deferred)

    if not kept:
        ui.warn("nothing new to write")
        return 0

    n_full, n_bucket, paths = notes.write_notes(kept, cfg, spec)
    linked = notes.add_related_links(paths, cfg, spec)
    notes.rebuild_index(cfg, spec)
    digest = notes.write_digest(kept, cfg, spec)

    ui.ok("\nDone.")
    ui.say("  %d full notes + %d weekly-file entries" % (n_full, n_bucket))
    ui.say("  %d notes cross-linked" % linked)
    ui.say("  index  -> %s" % (config.vault_dir(cfg) / "INDEX.md"))
    ui.say("  digest -> %s" % digest)

    if clear_inbox and not deferred:
        try:
            inbox.unlink()
            ui.dim("  inbox cleared")
        except Exception:
            pass
    elif clear_inbox:
        ui.warn("  inbox kept -- %d deferred post(s) still need a retry" % deferred)
    return 0
