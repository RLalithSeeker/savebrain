"""
doctor.py -- "why is it not working?", answered before you ask.

Every check prints PASS / WARN / FAIL plus the exact command that fixes it.
FAIL means the pipeline cannot run. WARN means it runs with something reduced.
"""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import sys

from . import config, domains, llm, ui

FAIL, WARN, PASS = "FAIL", "WARN", "PASS"


def _line(status, label, detail=""):
    mark = {PASS: "  ok  ", WARN: " warn ", FAIL: " FAIL "}[status]
    style = {PASS: "ok", WARN: "warn", FAIL: "err"}[status]
    ui.say("[%s] %-34s %s" % (mark, label, detail), style)


def _has(mod):
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def _port_free(port, host="127.0.0.1"):
    s = socket.socket()
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run(cfg=None) -> int:
    ui.rule("savebrain doctor")
    fails = warns = 0

    # ---- python
    v = sys.version_info
    if v >= (3, 9):
        _line(PASS, "python", "%d.%d.%d" % (v.major, v.minor, v.micro))
    else:
        _line(FAIL, "python", "need 3.9+, found %d.%d" % (v.major, v.minor))
        fails += 1

    # ---- config
    if not config.exists():
        _line(FAIL, "config.json", "missing -> run: python savebrain.py setup")
        return 1
    cfg = cfg or config.load()
    _line(PASS, "config.json", "vault=%s" % config.vault_dir(cfg))

    # ---- domain packs
    try:
        spec = domains.spec_from_config(cfg)
        _line(PASS, "domain packs", "%s (%d folders)"
              % (", ".join(spec["labels"]), len(spec["categories"])))
    except Exception as e:
        _line(FAIL, "domain packs", str(e)[:90])
        fails += 1
        spec = None

    # ---- api key
    key = config.api_key()
    if key.startswith("gsk_") and len(key) > 20:
        _line(PASS, "GROQ_API_KEY", key[:8] + "..." + key[-4:])
    elif key:
        _line(WARN, "GROQ_API_KEY", "set, but does not look like a Groq key")
        warns += 1
    else:
        _line(FAIL, "GROQ_API_KEY", "not set -> put it in .env (console.groq.com/keys)")
        fails += 1

    # ---- live provider check
    if key:
        try:
            model = llm.ping(cfg)
            _line(PASS, "provider reachable", "answered with %s" % model)
            live = llm.live_models(cfg)
            for kind in ("text", "vision", "audio"):
                want = (cfg.get("llm") or {}).get(kind + "_model")
                got = llm.resolve_model(kind, cfg)
                if not live:
                    _line(WARN, "%s model" % kind, "could not list models; using %s" % got)
                    warns += 1
                elif got == want:
                    _line(PASS, "%s model" % kind, got)
                else:
                    _line(WARN, "%s model" % kind,
                          "%s retired -> will use %s (run `setup --refresh-models` to pin it)"
                          % (want, got))
                    warns += 1
        except llm.LLMError as e:
            if e.is_quota:
                _line(WARN, "provider reachable", "quota/rate limit right now: %s" % str(e)[:70])
                warns += 1
            else:
                _line(FAIL, "provider reachable", str(e)[:100])
                fails += 1

    # ---- optional python packages
    for mod, why in (("rich", "prettier output"),
                     ("dotenv", ".env parsing (a built-in fallback is used otherwise)"),
                     ("PIL", "image downscaling before OCR (cheaper vision calls)")):
        if _has(mod):
            _line(PASS, "package %s" % mod, why)
        else:
            _line(WARN, "package %s" % mod, "missing -> pip install -r requirements.txt (%s)" % why)
            warns += 1

    # ---- local-mode packages, only if selected
    if (cfg.get("ocr") or "").lower() == "local" and not _has("easyocr"):
        _line(FAIL, "easyocr", 'ocr="local" but easyocr is missing -> '
                               "pip install -r requirements-local.txt (or set ocr to cloud)")
        fails += 1
    if (cfg.get("transcribe") or "").lower() == "local" and not _has("faster_whisper"):
        _line(FAIL, "faster-whisper", 'transcribe="local" but faster-whisper is missing -> '
                                      "pip install -r requirements-local.txt (or set transcribe to cloud)")
        fails += 1

    # ---- ffmpeg (only needed for long videos on the cloud path)
    if shutil.which("ffmpeg"):
        _line(PASS, "ffmpeg", "found (long videos can be compressed for upload)")
    else:
        _line(WARN, "ffmpeg", "not found -- videos over 24MB will be skipped, everything else fine")
        warns += 1

    # ---- port
    port = cfg.get("port", 8799)
    if _port_free(port):
        _line(PASS, "bridge port %d" % port, "free")
    else:
        _line(WARN, "bridge port %d" % port, "in use (a bridge may already be running)")
        warns += 1

    # ---- vault writable
    vault = config.vault_dir(cfg)
    try:
        vault.mkdir(parents=True, exist_ok=True)
        probe = vault / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _line(PASS, "vault writable", str(vault))
    except Exception as e:
        _line(FAIL, "vault writable", str(e)[:90])
        fails += 1

    # ---- extension present
    ext = config.ROOT / "extension" / "manifest.json"
    _line(PASS if ext.exists() else FAIL, "extension files",
          str(ext.parent) if ext.exists() else "missing extension/manifest.json")
    fails += 0 if ext.exists() else 1

    # ---- data on hand
    inbox = config.inbox_file(cfg)
    n_inbox = 0
    if inbox.exists():
        n_inbox = sum(1 for line in inbox.read_text(encoding="utf-8").splitlines() if line.strip())
    from . import pipeline
    _line(PASS, "queued / processed", "%d waiting in inbox, %d already in notes"
          % (n_inbox, len(pipeline.load_state(cfg))))

    ui.rule("")
    if fails:
        ui.err("%d blocking problem(s), %d warning(s). Fix the FAIL lines above." % (fails, warns))
        return 1
    if warns:
        ui.warn("all good, with %d warning(s). Safe to run." % warns)
    else:
        ui.ok("everything checks out.")
    ui.say("next: python savebrain.py bridge   (then scrape from the extension)")
    return 0
