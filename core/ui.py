"""ui.py -- printing that works with or without `rich`, and on a plain Windows console."""

from __future__ import annotations

import sys

try:
    from rich.console import Console
    _c = Console()
except Exception:  # rich missing, or a terminal it cannot drive
    _c = None

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_STYLES = {"ok": "green", "warn": "yellow", "err": "red", "info": "cyan", "dim": "dim"}
_PLAIN = {"ok": "OK  ", "warn": "!   ", "err": "ERR ", "info": "", "dim": "    "}


def say(msg: str, style: str = "") -> None:
    if _c and style in _STYLES:
        _c.print("[%s]%s[/%s]" % (_STYLES[style], msg, _STYLES[style]))
    elif _c:
        _c.print(msg)
    else:
        print(_PLAIN.get(style, "") + str(msg))


def ok(m):
    say(m, "ok")


def warn(m):
    say(m, "warn")


def err(m):
    say(m, "err")


def info(m):
    say(m, "info")


def dim(m):
    say(m, "dim")


def rule(title: str = "") -> None:
    if _c:
        _c.rule(title)
    else:
        print("\n=== %s ===" % title if title else "-" * 60)


def ask(prompt: str, default: str = "") -> str:
    suffix = " [%s]" % default if default else ""
    try:
        val = input("%s%s: " % (prompt, suffix)).strip()
    except EOFError:
        return default
    return val or default


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    val = ask("%s (%s)" % (prompt, d)).lower()
    if not val:
        return default
    return val.startswith("y")
