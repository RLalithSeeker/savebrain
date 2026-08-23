"""
domains.py -- the part that makes this vault work for ANY subject.

A "domain pack" is one JSON file in domains/. It tells the extraction model
what counts as relevant, which folders exist, what the domain's nouns are,
and what a good tag looks like. Swap the pack, and the exact same pipeline
turns saved posts into a cooking vault, a fitness vault, a film vault.

Packs are additive: pick 1 or 5. Categories are the union, relevance rules
are the union.

Make your own without writing JSON:
    python savebrain.py new-domain "vintage watch collecting"
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

PACK_DIR = config.ROOT / "domains"

REQUIRED_KEYS = ["id", "label", "categories", "relevant", "not_relevant"]


def available() -> list:
    """All installed packs, sorted, as (id, label, n_categories)."""
    out = []
    for f in sorted(PACK_DIR.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8-sig"))
            out.append((p["id"], p.get("label", p["id"]), len(p.get("categories", {}))))
        except Exception:
            continue
    return out


def load_pack(pack_id: str) -> dict:
    f = PACK_DIR / (pack_id + ".json")
    if not f.exists():
        raise FileNotFoundError(
            "no domain pack '%s'. Installed: %s"
            % (pack_id, ", ".join(i for i, _, _ in available()))
        )
    pack = json.loads(f.read_text(encoding="utf-8-sig"))
    missing = [k for k in REQUIRED_KEYS if k not in pack]
    if missing:
        raise ValueError("domain pack %s is missing: %s" % (pack_id, ", ".join(missing)))
    return pack


def validate_pack(pack: dict) -> list:
    """Return a list of problems (empty list = valid)."""
    problems = ["missing key: " + k for k in REQUIRED_KEYS if k not in pack]
    if not isinstance(pack.get("categories"), dict) or not pack.get("categories"):
        problems.append("categories must be a non-empty object of folder -> description")
    for cat in (pack.get("categories") or {}):
        if not re.fullmatch(r"[a-z0-9_]+", cat):
            problems.append("category '%s' must be lowercase_with_underscores" % cat)
    for cat in (pack.get("bucket_categories") or []):
        if cat not in (pack.get("categories") or {}):
            problems.append("bucket_categories has '%s' which is not a category" % cat)
    return problems


def merge(pack_ids: list, extra_categories=None) -> dict:
    """Combine one or more packs into the single spec the pipeline uses."""
    packs = [load_pack(p) for p in pack_ids]
    categories, buckets, relevant, not_relevant = {}, [], [], []
    entity_labels, artifacts, snippets, tags, cleanup, labels = [], [], [], [], [], []

    for p in packs:
        categories.update(p.get("categories", {}))
        buckets += p.get("bucket_categories", [])
        relevant += p.get("relevant", [])
        not_relevant += p.get("not_relevant", [])
        tags += p.get("tag_examples", [])
        cleanup += p.get("cleanup_hints", [])
        labels.append(p.get("label", p["id"]))
        if p.get("entity_label"):
            entity_labels.append(p["entity_label"])
        if p.get("artifact_examples"):
            artifacts.append(p["artifact_examples"])
        if p.get("snippet_label"):
            snippets.append(p["snippet_label"])

    for c in (extra_categories or []):
        categories.setdefault(c, "user-added category")
    categories.setdefault("uncategorized", "did not fit anywhere else")

    return {
        "ids": [p["id"] for p in packs],
        "labels": labels,
        "categories": categories,
        "bucket_categories": sorted(set(buckets)),
        "relevant": relevant,
        "not_relevant": not_relevant,
        "entity_label": "; ".join(entity_labels) or "tools, brands, people, products named",
        "artifact_examples": "; ".join(artifacts) or "a full recipe, template, script or checklist",
        "snippet_label": "; ".join(snippets) or "short verbatim lines worth copying exactly",
        "tag_examples": tags[:14],
        "cleanup_hints": cleanup[:14],
    }


def spec_from_config(cfg: dict) -> dict:
    return merge(cfg.get("domains") or ["tech"], cfg.get("extra_categories"))


# =====================================================================
# The extraction prompt. One prompt, domain-injected.
# =====================================================================
def build_system_prompt(spec: dict) -> str:
    cat_lines = "\n".join("    %s -- %s" % (k, v) for k, v in spec["categories"].items())
    rel = "\n".join("  - " + r for r in spec["relevant"])
    notrel = "\n".join("  - " + r for r in spec["not_relevant"])
    tags = ", ".join('"%s"' % t for t in spec["tag_examples"]) or '"beginner-mistakes", "budget-picks"'
    cleanup = "\n".join("  - " + c for c in spec["cleanup_hints"]) \
        or "  - fix obvious OCR mangling of well-known names in this field"

    return PROMPT_TEMPLATE.format(
        labels=", ".join(spec["labels"]),
        entity_label=spec["entity_label"],
        artifact_examples=spec["artifact_examples"],
        snippet_label=spec["snippet_label"],
        cat_lines=cat_lines,
        rel=rel,
        notrel=notrel,
        cleanup=cleanup,
        tags=tags,
    )


PROMPT_TEMPLATE = """You are an extraction assistant for a personal knowledge vault built from
social-media posts the owner saved. The vault covers: {labels}.

Input: a caption + (optional) video transcript + (optional) numbered carousel
slide texts produced by OCR.

Output STRICT JSON. No markdown fences, no prose before or after:
{{
  "is_relevant": bool,
  "categories": [str],          // 1-3 of the folder names listed below
  "topic": str,                 // short specific title, like a good bookmark name
  "one_liner": str,             // one sentence: what this post gives you
  "primary_link": str,          // THE one link/handle/place worth going to. "" if none.
  "all_links": [str],           // every URL, @handle, product name, place mentioned
  "key_points": [str],          // 3-8 concrete, actionable bullets. No filler lines.
  "steps": [str],               // ordered steps if the post teaches a sequence, else []
  "entities": [str],            // {entity_label}
  "full_text_extraction": str,  // If the post's REAL value is a copyable artifact
                                //   ({artifact_examples}),
                                //   reproduce it here VERBATIM and complete. Else "".
  "snippets": [str],            // {snippet_label}
  "evidence": str,              // why this is credible or proven (result, number, demo). "" if none.
  "subtopic_tags": [str]        // 2-5 specific kebab-case tags
}}

FOLDERS (use these exact names in "categories"):
{cat_lines}

RELEVANCE (be generous -- when in doubt, true):
{rel}
Mark is_relevant=false only for:
{notrel}

LINK RULES:
  - Hunt for links in caption, slides and transcript.
  - Prefer the actionable destination (a product page, a repo, a booking page)
    over a personal handle.
  - Keep them short: "example.com/thing", not the full tracking URL.
  - Slide text comes from OCR and may be unreadable. If you are not confident of
    the exact URL, leave primary_link "" and put the readable fragment in
    all_links. A blank link beats an invented one. NEVER output placeholders
    like "example.com/user/repo".

VERBATIM RULES:
  - full_text_extraction and snippets must be copied word for word. Never
    paraphrase, summarize or truncate them.
  - If an artifact spans several slides, reassemble it in order, keeping line breaks.
  - snippets = short lines. full_text_extraction = the long complete artifact.
    A post can have both, one, or neither.

OCR CLEANUP:
  - Slide text may arrive with mashed words and misread characters. Silently fix
    obvious manglings of real names in this domain:
{cleanup}
  - Never invent a name that is not actually in the post.

CAROUSEL RULES:
  - Slides arrive labelled [Slide 1], [Slide 2] and so on.
  - "steps" keeps the teaching order but drops filler slides: intro hype,
    "follow me", "save this post", "share with a friend", end-card branding.

TAGGING:
  - kebab-case, lowercase, hyphens only.
  - Be specific. Generic tags are forbidden: no "tips", "tricks", "tutorial",
    "instagram", "saved", or the bare domain name.
  - Tags must be REUSABLE -- aim for one that 5-20 future posts could share.
  - Good examples: {tags}
  - Do not repeat a category name as a tag.
"""


# =====================================================================
# Custom pack generation (the model writes the pack for a subject you name)
# =====================================================================
PACK_WRITER_PROMPT = r"""You design "domain packs" for a personal knowledge vault that turns saved
social-media posts into organized Markdown notes.

Write ONE pack for the subject the user names. Output STRICT JSON only:
{
  "id": "kebab-case-id",
  "label": "Human Readable Name",
  "emoji": "single emoji",
  "categories": { "lowercase_underscore_folder": "what belongs in it" },
  "bucket_categories": ["folders whose short posts merge into one weekly file"],
  "relevant": ["what kinds of posts belong in this vault"],
  "not_relevant": ["what to reject"],
  "entity_label": "the domain's proper nouns worth extracting (e.g. 'brands, cultivars, nurseries')",
  "artifact_examples": "what a copyable artifact looks like here (e.g. 'a full recipe with quantities')",
  "snippet_label": "what short verbatim lines matter here (e.g. 'oven temps, ratios, exact cues')",
  "tag_examples": ["6-10 realistic kebab-case subtopic tags"],
  "cleanup_hints": ["3-6 OCR fixes specific to this domain, format: \"wrong\" -> \"Right\""]
}

RULES:
- 6 to 12 categories. Folder names lowercase_with_underscores, no spaces.
- Categories must match how a real enthusiast browses the subject, not an
  academic taxonomy. Think: which folder would they open at 11pm?
- bucket_categories = folders that collect one-line finds (products, links,
  quick ideas) rather than deep explanations. Usually 1-4, may be [].
- Do NOT include "uncategorized" -- it is added automatically.
- relevant / not_relevant: short phrases, 4-8 of each.
- No markdown, no commentary. JSON only.
"""


def write_custom_pack(subject: str, llm_json_call) -> Path:
    """llm_json_call(system, user) -> dict. Injected so this module imports no LLM code."""
    pack = llm_json_call(PACK_WRITER_PROMPT, "Subject: " + subject)
    cats = {}
    for k, v in (pack.get("categories") or {}).items():
        key = re.sub(r"[^a-z0-9_]", "_", str(k).lower().replace(" ", "_")).strip("_")
        if key and key != "uncategorized":
            cats[key] = v
    pack["categories"] = cats
    pack["id"] = re.sub(r"[^a-z0-9-]", "-", str(pack.get("id") or subject).lower()).strip("-")
    pack["bucket_categories"] = [
        c for c in (pack.get("bucket_categories") or []) if c in cats
    ]
    problems = validate_pack(pack)
    if problems:
        raise ValueError("generated pack is invalid:\n  " + "\n  ".join(problems))
    out = PACK_DIR / (pack["id"] + ".json")
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
