#!/usr/bin/env python3
"""
savebrain -- turn the posts you save on Instagram into a Markdown knowledge
vault about whatever you actually care about.

    python savebrain.py setup       pick your subject(s), paste a free API key
    python savebrain.py doctor      check everything before you rely on it
    python savebrain.py bridge      start the local receiver, then scrape
    python savebrain.py ingest      turn the catch into notes

Full docs: README.md   |   For an AI agent doing the install: AGENTS.md
"""

from __future__ import annotations

import argparse
import sys

from core import __version__, config, ui


def cmd_setup(args):
    from core import wizard
    return wizard.run(args)


def cmd_doctor(args):
    from core import doctor
    return doctor.run(config.load(strict=False) if config.exists() else None)


def cmd_bridge(args):
    from core import bridge
    cfg = config.load()
    return bridge.serve(cfg, port=args.port, host=args.host, auto_ingest=args.auto_ingest)


def cmd_ingest(args):
    from core import pipeline
    cfg = config.load()
    if args.reset:
        state = config.state_file(cfg)
        if state.exists():
            state.unlink()
            ui.warn("state cleared -- every post in the inbox will be processed again")
    return pipeline.run_ingest(
        cfg,
        inbox_path=args.file,
        do_transcribe=not args.no_transcribe,
        limit=args.max,
        clear_inbox=args.clear_inbox,
    )


def cmd_domains(args):
    from core import domains
    cfg = config.load(strict=False)
    active = set(cfg.get("domains") or [])
    ui.rule("installed domain packs")
    for pid, label, ncat in domains.available():
        mark = "*" if pid in active else " "
        ui.say(" %s %-18s %-32s %d folders" % (mark, pid, label, ncat))
    ui.dim('\n* = active. Change with:  python savebrain.py setup --domains a,b --yes')
    ui.dim('New subject:              python savebrain.py new-domain "your subject"')
    return 0


def cmd_new_domain(args):
    from core import domains, llm
    cfg = config.load(strict=False)
    config.load_env()
    if not config.api_key():
        ui.err("GROQ_API_KEY not set -- run `python savebrain.py setup` first")
        return 1
    ui.info("designing a domain pack for: %s" % args.subject)
    try:
        path = domains.write_custom_pack(args.subject, lambda s, u: llm.json_call(s, u, cfg))
    except Exception as e:
        ui.err("failed: %s" % e)
        return 1
    import json
    pack = json.loads(path.read_text(encoding="utf-8"))
    ui.ok("wrote %s" % path)
    ui.say("folders: %s" % ", ".join(pack["categories"]))
    ui.dim("activate it:  python savebrain.py setup --domains %s --yes" % pack["id"])
    return 0


def cmd_index(args):
    from core import domains, notes
    cfg = config.load()
    spec = domains.spec_from_config(cfg)
    path = notes.rebuild_index(cfg, spec)
    ui.ok("rebuilt %s" % path)
    return 0


def cmd_auto(args):
    """One unattended cycle: bridge with auto-ingest, exits when the scrape finishes."""
    from core import bridge
    cfg = config.load()
    return bridge.serve(cfg, port=args.port, host="127.0.0.1", auto_ingest=True)


def main():
    p = argparse.ArgumentParser(
        prog="savebrain",
        description="Saved posts in, organized Markdown vault out.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--version", action="version", version="savebrain " + __version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="interactive first-time setup")
    s.add_argument("--domains", help="comma-separated pack ids, skips the question")
    s.add_argument("--key", help="provider API key, skips the question")
    s.add_argument("--vault", help="where notes are written (default: ./vault)")
    s.add_argument("--yes", action="store_true", help="non-interactive, take defaults")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("doctor", help="check config, key, models, deps, port, vault")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("bridge", help="run the local receiver for the browser extension")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--auto-ingest", action="store_true",
                   help="ingest automatically when the scrape finishes, then exit")
    s.set_defaults(func=cmd_bridge)

    s = sub.add_parser("ingest", help="process scraped posts into notes")
    s.add_argument("file", nargs="?", help="a specific .jsonl (default: the vault inbox)")
    s.add_argument("--max", type=int, default=None, help="cap posts processed this run")
    s.add_argument("--no-transcribe", action="store_true", help="skip video transcription")
    s.add_argument("--clear-inbox", action="store_true", help="delete the inbox after a clean run")
    s.add_argument("--reset", action="store_true",
                   help="forget what has been processed and re-file the whole inbox")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("domains", help="list installed domain packs")
    s.set_defaults(func=cmd_domains)

    s = sub.add_parser("new-domain", help="generate a domain pack for any subject")
    s.add_argument("subject", help='e.g. "urban beekeeping"')
    s.set_defaults(func=cmd_new_domain)

    s = sub.add_parser("index", help="rebuild INDEX.md and the compact index")
    s.set_defaults(func=cmd_index)

    s = sub.add_parser("auto", help="one unattended cycle (used by the scheduled task)")
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(func=cmd_auto)

    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        ui.say("")
        ui.dim("first time here?  python savebrain.py setup")
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
