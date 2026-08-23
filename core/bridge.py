"""
bridge.py -- the tiny local server the browser extension streams posts into.

The extension runs inside your own logged-in browser and cannot write files, so
it POSTs each post it sees to http://127.0.0.1:<port>/post. Everything lands in
the vault's inbox, deduped by post id.

Routes:
  POST /post      one post, or {"posts": [...]}
  POST /started   beacon: the extension woke up (tells "never ran" from "ran, found nothing")
  POST /done      scrape finished; in --auto-ingest mode this triggers the ingest
  GET  /known     ids already stored or processed -> lets the extension stop early
  GET  /status    counters, used by the popup for its green/red dot

stdlib only, loopback only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, ui

_lock = threading.Lock()
_state = {
    "inbox_ids": set(),      # ids sitting in inbox.jsonl
    "processed_ids": set(),  # ids already turned into notes
    "received": 0,
    "auto_ingest": False,
    "done_seen": False,
    "started_seen": False,
    "ingesting": False,
    "cfg": None,
}
_shutdown = threading.Event()
IDLE_TIMEOUT = 1800


def _inbox_ids(cfg):
    p = config.inbox_file(cfg)
    out = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                sc = json.loads(line).get("shortcode")
                if sc:
                    out.add(sc)
            except Exception:
                continue
    return out


def _append(rec: dict) -> str:
    sc = rec.get("shortcode")
    if not sc:
        return "skip"
    cfg = _state["cfg"]
    with _lock:
        if sc in _state["inbox_ids"] or sc in _state["processed_ids"]:
            return "known"
        _state["inbox_ids"].add(sc)
        rec.setdefault("ingested_at", datetime.now(timezone.utc).isoformat())
        p = config.inbox_file(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _state["received"] += 1
    return "new"


def _trigger_ingest(reason: str) -> bool:
    with _lock:
        if _state["ingesting"]:
            return False
        _state["ingesting"] = True
    cfg = _state["cfg"]
    logs = config.logs_dir(cfg)
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / ("ingest_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    ui.info("  [auto-ingest] %s -> %s" % (reason, log_path.name))

    def _run():
        import os
        try:
            with open(log_path, "w", encoding="utf-8") as logf:
                proc = subprocess.run(
                    [sys.executable, str(config.ROOT / "savebrain.py"), "ingest"],
                    cwd=str(config.ROOT), stdout=logf, stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
            ui.info("  [auto-ingest] finished (exit %s)" % proc.returncode)
        except Exception as e:
            ui.err("  [auto-ingest] failed: %s" % e)
        finally:
            _state["ingesting"] = False
            if _state["auto_ingest"]:
                _shutdown.set()

    threading.Thread(target=_run, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome/Brave block an https page from reaching loopback without this.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith(("/status", "/health")):
            self._json(200, {"ok": True,
                             "received_this_session": _state["received"],
                             "total_in_inbox": len(_state["inbox_ids"]),
                             "already_processed": len(_state["processed_ids"])})
        elif self.path.startswith("/known"):
            with _lock:
                known = sorted(_state["inbox_ids"] | _state["processed_ids"])
            self._json(200, {"ok": True, "shortcodes": known, "count": len(known)})
        else:
            self._json(404, {"ok": False})

    def do_POST(self):
        if self.path.startswith("/started"):
            _state["started_seen"] = True
            payload = self._body()
            ui.dim("  [scrape started] extension alive (auto=%s)" % bool(payload.get("auto")))
            self._json(200, {"ok": True})
            return

        if self.path.startswith("/done"):
            info = self._body()
            total = int(info.get("total", 0) or 0)
            ui.info("  [scrape done] new=%d caught_up=%s logged_out=%s"
                    % (total, info.get("caught_up"), info.get("logged_out")))
            if info.get("logged_out"):
                ui.warn("  the extension reports you are NOT logged in -- log in and re-run")
            _state["done_seen"] = True
            launched = False
            if _state["auto_ingest"] and total > 0:
                launched = _trigger_ingest("%d new posts" % total)
            self._json(200, {"ok": True, "auto_ingest": _state["auto_ingest"], "launched": launched})
            if _state["auto_ingest"] and not launched:
                _shutdown.set()
            return

        if not self.path.startswith("/post"):
            self._json(404, {"ok": False})
            return

        payload = self._body()
        posts = payload.get("posts") if isinstance(payload, dict) and "posts" in payload else [payload]
        written, all_known = 0, True
        for p in posts:
            if not isinstance(p, dict):
                continue
            if _append(p) == "new":
                written += 1
                all_known = False
                kind = "carousel" if p.get("is_carousel") else ("video" if p.get("is_video") else "image")
                cap = (p.get("caption") or "").replace("\n", " ")[:46]
                print("  +[%3d] @%-16s %-8s %s  %s" % (len(_state["inbox_ids"]),
                                                       (p.get("author") or "?")[:16],
                                                       kind, p.get("shortcode", ""), cap), flush=True)
        self._json(200, {"ok": True, "written": written, "known": all_known,
                         "total_in_inbox": len(_state["inbox_ids"])})

    def log_message(self, *_):
        pass  # we print our own, one line per accepted post


def serve(cfg, port=None, host="127.0.0.1", auto_ingest=False):
    from . import pipeline

    port = port or cfg.get("port", 8799)
    _state["cfg"] = cfg
    _state["inbox_ids"] = _inbox_ids(cfg)
    _state["processed_ids"] = pipeline.load_state(cfg)
    _state["auto_ingest"] = auto_ingest
    config.inbox_file(cfg).parent.mkdir(parents=True, exist_ok=True)

    srv = ThreadingHTTPServer((host, port), Handler)
    ui.ok("bridge listening on http://%s:%d%s"
          % (host, port, "  [auto-ingest: on, exits when done]" if auto_ingest else ""))
    ui.dim("inbox: %s  (%d stored, %d already in notes)"
           % (config.inbox_file(cfg), len(_state["inbox_ids"]), len(_state["processed_ids"])))

    if not auto_ingest:
        ui.dim("next: open your Saved page, click the extension, hit Start. Ctrl+C to stop.")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            ui.say("\nbridge stopped. %d new posts this session (%d in inbox)."
                   % (_state["received"], len(_state["inbox_ids"])))
            ui.say("next: python savebrain.py ingest")
        return 0

    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def _watchdog():
        waited = 0
        while waited < IDLE_TIMEOUT and not _shutdown.is_set():
            time.sleep(5)
            waited += 5
        if _shutdown.is_set() or _state["ingesting"] or _state["done_seen"]:
            return
        if _state["started_seen"]:
            ui.warn("extension started but never finished within %ds -- nothing new landed"
                    % IDLE_TIMEOUT)
        else:
            ui.err("no beacon from the extension within %ds. It is probably not loaded: "
                   "open your browser extensions page, enable Developer mode, "
                   "Load unpacked -> the extension/ folder." % IDLE_TIMEOUT)
        _shutdown.set()

    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        _shutdown.wait()
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    ui.say("bridge exited. %d new posts this session." % _state["received"])
    return 0
