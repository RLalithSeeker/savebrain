"""
config.py — every path, key and tunable in one place.

Config lives in TWO files, both created by `python savebrain.py setup`:

  .env          secrets only (API keys). Never committed.
  config.json   everything else (domains, models, vault location, pacing).

Nothing else in the codebase is allowed to hardcode a path or a model name.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

# Model candidates, tried in order when the configured one is unavailable.
# Providers retire models; this list is what keeps a stale config from
# hard-failing months after you set it up.
MODEL_CANDIDATES = {
    "text": [
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b",
    ],
    "vision": [
        "qwen/qwen3.6-27b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-3.2-90b-vision-preview",
    ],
    "audio": [
        "whisper-large-v3-turbo",
        "whisper-large-v3",
    ],
}

DEFAULTS = {
    "version": 1,
    "vault_dir": "vault",
    "domains": ["tech"],
    "extra_categories": [],
    "llm": {
        "provider": "groq",
        "text_model": MODEL_CANDIDATES["text"][0],
        "vision_model": MODEL_CANDIDATES["vision"][0],
        "audio_model": MODEL_CANDIDATES["audio"][0],
    },
    # Optional second brain: ANY OpenAI-compatible endpoint (LM Studio, Ollama,
    # Cerebras, OpenRouter, a colleague's vLLM). Used only when the primary fails.
    "fallback": {
        "base_url": "",
        "model": "",
        "api_key_env": "FALLBACK_API_KEY",
    },
    "transcribe": "cloud",   # cloud (Groq Whisper API) | local (faster-whisper) | off
    "ocr": "cloud",          # cloud (Groq vision)      | local (easyocr)        | off
    "verify_links": True,
    "bucket_short_posts": True,
    "port": 8799,
    "max_posts": 1000,
    "language": "en",
    # Only used by the unattended scheduling scripts in scripts/.
    "instagram_username": "",
    "browser_command": "",
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_env() -> None:
    """Load .env into os.environ. Works with or without python-dotenv."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
        return
    except ImportError:
        pass
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def exists() -> bool:
    return CONFIG_PATH.exists()


def load(strict: bool = True) -> dict:
    """Return the merged config. strict=True exits with a setup hint if unconfigured."""
    load_env()
    if not CONFIG_PATH.exists():
        if strict:
            print("No config.json yet.  Run:  python savebrain.py setup")
            sys.exit(1)
        return dict(DEFAULTS)
    try:
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"config.json is not valid JSON: {e}")
        sys.exit(1)
    return _deep_merge(DEFAULTS, user)


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- derived paths ----------

def vault_dir(cfg: dict) -> Path:
    p = Path(cfg.get("vault_dir") or "vault")
    if not p.is_absolute():
        p = ROOT / p
    return p


def state_file(cfg: dict) -> Path:
    return vault_dir(cfg) / ".processed.json"


def inbox_file(cfg: dict) -> Path:
    return vault_dir(cfg) / "_inbox" / "inbox.jsonl"


def logs_dir(cfg: dict) -> Path:
    return vault_dir(cfg) / "_logs"


def digests_dir(cfg: dict) -> Path:
    return vault_dir(cfg) / "_digests"


def api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()
