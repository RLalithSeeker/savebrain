"""
llm.py -- every model call in the project, over plain stdlib HTTP.

Deliberately NO SDK. The provider endpoints here are OpenAI-compatible, so
urllib is enough, and that removes the single most common install failure
(an SDK pulling an httpx/pydantic version that fights something else already
on the machine).

Primary provider: Groq (free tier is generous and fast).
Optional fallback: any OpenAI-compatible base_url -- LM Studio, Ollama,
OpenRouter, Cerebras, vLLM -- set in config.json under "fallback".
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import time
import urllib.error
import urllib.request
import uuid

GROQ_BASE = "https://api.groq.com/openai/v1"

_model_cache = {}      # kind -> resolved model id
_live_models = None    # list of ids, fetched once per process


class LLMError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

    @property
    def is_quota(self) -> bool:
        return self.status in (429, 402) or "rate limit" in str(self).lower()


# ---------------------------------------------------------------- transport
USER_AGENT = "savebrain/1.0 (+https://github.com/RLalithSeeker/savebrain)"


def _request(url, key, payload=None, method=None, timeout=60, raw_body=None, content_type=None):
    data = None
    # A default urllib User-Agent gets refused at the edge (Cloudflare 1010),
    # long before the API ever sees the request. Always identify ourselves.
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    if raw_body is not None:
        data = raw_body
        headers["Content-Type"] = content_type
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise LLMError("HTTP %s from %s: %s" % (e.code, url, body), status=e.code)
    except Exception as e:
        raise LLMError("%s: %s" % (type(e).__name__, e))


def _retry_after(message: str) -> float:
    """Free tiers say exactly how long to wait -- use it instead of guessing."""
    m = re.search(r"try again in ([\d.]+)\s*s", message)
    return min(float(m.group(1)) + 1.0, 65.0) if m else 0.0


def _send_chat(url, key, payload, timeout, waits_left=2):
    """One chat request, with the two recoveries worth having: a per-minute rate
    limit (wait exactly as long as the server said) and an endpoint that rejects
    an optional knob (drop it and resend)."""
    try:
        return _request(url, key, payload=payload, timeout=timeout)
    except LLMError as e:
        msg = str(e)
        if e.status == 429 and waits_left > 0:
            wait = _retry_after(msg) or 20.0
            print("   rate limited, waiting %.0fs..." % wait)
            time.sleep(wait)
            return _send_chat(url, key, payload, timeout, waits_left - 1)
        if e.status == 400 and ("reasoning_effort" in msg or "response_format" in msg):
            payload.pop("reasoning_effort", None)
            if "response_format" in msg:
                payload.pop("response_format", None)
            return _request(url, key, payload=payload, timeout=timeout)
        raise


def _base_and_key(cfg, fallback=False):
    if fallback:
        fb = cfg.get("fallback") or {}
        base = (fb.get("base_url") or "").rstrip("/")
        key = os.environ.get(fb.get("api_key_env") or "FALLBACK_API_KEY", "") or "not-needed"
        return base, key, (fb.get("model") or "")
    return GROQ_BASE, os.environ.get("GROQ_API_KEY", "").strip(), None


# ---------------------------------------------------------------- models
def live_models(cfg) -> list:
    """Model ids the provider actually serves right now (empty list on failure)."""
    global _live_models
    if _live_models is not None:
        return _live_models
    base, key, _ = _base_and_key(cfg)
    try:
        data = _request(base + "/models", key, method="GET", timeout=15)
        _live_models = [m.get("id") for m in data.get("data", []) if m.get("id")]
    except Exception:
        _live_models = []
    return _live_models


def resolve_model(kind: str, cfg: dict) -> str:
    """Configured model if the provider still serves it, else the first live candidate.

    Providers retire model ids. Without this, a config written today is a
    hard crash in six months.
    """
    from . import config as _cfg

    if kind in _model_cache:
        return _model_cache[kind]
    configured = (cfg.get("llm") or {}).get(kind + "_model") or ""
    live = live_models(cfg)
    chosen = configured
    if live and configured not in live:
        for cand in _cfg.MODEL_CANDIDATES.get(kind, []):
            if cand in live:
                chosen = cand
                break
        else:
            # nothing from our list is live: take any model whose name hints the role
            hint = {"vision": ("vision", "vl", "scout", "maverick"),
                    "audio": ("whisper",),
                    "text": ("llama", "gpt", "qwen", "gemma")}[kind]
            guess = [m for m in live if any(h in m.lower() for h in hint)]
            chosen = guess[0] if guess else configured
        if chosen != configured:
            print("   [model] '%s' unavailable -> using '%s'" % (configured, chosen))
    _model_cache[kind] = chosen
    return chosen


# ---------------------------------------------------------------- chat
def chat(messages, cfg, kind="text", json_mode=True, max_tokens=4000, timeout=90, fallback=False):
    base, key, fb_model = _base_and_key(cfg, fallback)
    if fallback and not base:
        raise LLMError("no fallback endpoint configured")
    if not fallback and not key:
        raise LLMError("GROQ_API_KEY is not set (see .env)")
    model = fb_model if fallback else resolve_model(kind, cfg)
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    # Reasoning models otherwise spend the whole budget thinking about a slide of
    # text. Values differ per family, so this is keyed on the model name.
    low = model.lower()
    if "qwen" in low:
        payload["reasoning_effort"] = "none"
    elif "gpt-oss" in low:
        payload["reasoning_effort"] = "low"

    data = _send_chat(base + "/chat/completions", key, payload, timeout)
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise LLMError("unexpected response shape: " + json.dumps(data)[:300])


def _extract_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    raise LLMError("model did not return JSON: " + t[:200])


def json_call(system: str, user: str, cfg: dict, retries: int = 2) -> dict:
    """Chat call that must come back as JSON. Retries, then tries the fallback endpoint."""
    last = None
    for attempt in range(retries + 1):
        try:
            raw = chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                cfg, kind="text", json_mode=True,
            )
            return _extract_json(raw)
        except LLMError as e:
            last = e
            if e.is_quota:
                break
            time.sleep(1.5 * (attempt + 1) + random.random())

    if (cfg.get("fallback") or {}).get("base_url"):
        try:
            raw = chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                cfg, kind="text",
                # local servers often reject response_format=json_object
                json_mode=False, timeout=240, fallback=True,
            )
            return _extract_json(raw)
        except LLMError as e:
            last = LLMError("primary failed (%s); fallback failed (%s)" % (last, e),
                            status=getattr(last, "status", None))
    raise last


# ---------------------------------------------------------------- vision OCR
def vision_read(data_urls: list, cfg: dict, start_idx: int = 1) -> str:
    """Transcribe text from up to ~5 images in ONE call (batching keeps you inside the free tier)."""
    n = len(data_urls)
    instruction = (
        "This message contains exactly %d image(s): sequential slides from one social-media "
        "post. Transcribe every visible word exactly as shown -- headings, body text, code, "
        "fine print -- preserving line breaks and reading order (top-to-bottom, "
        "left-to-right). Do not paraphrase, summarize or skip. Output exactly %d block(s), "
        "one per image, each headed [Slide N] with N running from %d to %d. Never invent a "
        "block for an image that is not here. If a slide has no readable text, output its "
        "heading and nothing under it. Output the transcription only, with no commentary."
        % (n, n, start_idx, start_idx + n - 1)
    )
    content = [{"type": "text", "text": instruction}]
    for u in data_urls:
        content.append({"type": "image_url", "image_url": {"url": u}})
    raw = chat([{"role": "user", "content": content}], cfg, kind="vision",
               json_mode=False, max_tokens=4000, timeout=120)
    return (raw or "").strip()


# ---------------------------------------------------------------- audio
def transcribe_file(path: str, cfg: dict) -> str:
    """Whisper transcription through the provider API -- no torch, no local model."""
    base, key, _ = _base_and_key(cfg)
    model = resolve_model("audio", cfg)
    boundary = "----savebrain" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        blob = f.read()

    def part(name, value):
        return ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (boundary, name, value)).encode("utf-8")

    body = bytearray()
    body += part("model", model)
    body += part("response_format", "json")
    lang = cfg.get("language") or ""
    if lang:
        body += part("language", lang)
    body += ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
             "Content-Type: %s\r\n\r\n" % (boundary, os.path.basename(path), ctype)).encode("utf-8")
    body += blob
    body += ("\r\n--%s--\r\n" % boundary).encode("utf-8")

    data = _request(base + "/audio/transcriptions", key, raw_body=bytes(body),
                    content_type="multipart/form-data; boundary=" + boundary, timeout=180)
    return (data.get("text") or "").strip()


def ping(cfg: dict) -> str:
    """One cheap call, used by `doctor`. Returns the model id that answered."""
    # The word "json" has to appear in the messages for json_object mode to be accepted.
    raw = chat([{"role": "user", "content": 'Reply with this exact JSON and nothing else: {"ok": true}'}],
               cfg, kind="text", json_mode=True, max_tokens=32, timeout=30)
    _extract_json(raw)
    return resolve_model("text", cfg)
