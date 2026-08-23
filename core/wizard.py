"""
wizard.py -- `python savebrain.py setup`.

Asks the five questions that actually change behaviour, writes .env and
config.json, creates the vault folders, and prints the two remaining manual
steps (load the extension, start the bridge).

Runs unattended too:
    python savebrain.py setup --domains cooking,fitness --key gsk_... --yes
"""

from __future__ import annotations

import json
import os

from . import config, domains, llm, ui


def _write_env(key: str) -> None:
    lines = []
    if config.ENV_PATH.exists():
        lines = [l for l in config.ENV_PATH.read_text(encoding="utf-8-sig").splitlines()
                 if not l.startswith("GROQ_API_KEY=")]
    lines.insert(0, "GROQ_API_KEY=" + key)
    config.ENV_PATH.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    os.environ["GROQ_API_KEY"] = key


def _choose_domains(interactive: bool, preset) -> list:
    packs = domains.available()
    if preset:
        chosen = [p.strip() for p in preset if p.strip()]
        known = {i for i, _, _ in packs}
        unknown = [c for c in chosen if c not in known]
        if unknown:
            raise SystemExit("unknown domain pack(s): %s\ninstalled: %s"
                             % (", ".join(unknown), ", ".join(sorted(known))))
        return chosen
    if not interactive:
        return ["tech"]

    ui.rule("what is this vault about?")
    for n, (pid, label, ncat) in enumerate(packs, 1):
        ui.say("  %2d. %-16s %s (%d folders)" % (n, pid, label, ncat))
    ui.say("   c. something else -- describe it and one gets generated for you")
    ui.dim("pick one or several, e.g.  2  or  1,4,7")

    while True:
        raw = ui.ask("choice", "1").strip().lower()
        if raw in ("c", "custom"):
            subject = ui.ask("describe the subject (e.g. 'urban beekeeping')").strip()
            if not subject:
                continue
            if not config.api_key():
                ui.err("a provider key is needed to generate a pack -- rerun setup and enter it first")
                continue
            ui.dim("writing a domain pack for: %s ..." % subject)
            try:
                cfg = config.load(strict=False)
                path = domains.write_custom_pack(
                    subject, lambda s, u: llm.json_call(s, u, cfg))
            except Exception as e:
                ui.err("could not generate the pack: %s" % str(e)[:160])
                continue
            pack = json.loads(path.read_text(encoding="utf-8"))
            ui.ok("created domains/%s.json with folders: %s"
                  % (pack["id"], ", ".join(pack["categories"])))
            return [pack["id"]]

        picks = []
        for token in raw.replace(" ", ",").split(","):
            if not token:
                continue
            if token.isdigit() and 1 <= int(token) <= len(packs):
                picks.append(packs[int(token) - 1][0])
            elif token in {p for p, _, _ in packs}:
                picks.append(token)
        if picks:
            return list(dict.fromkeys(picks))
        ui.warn("did not understand that -- try a number from the list")


def _refresh_models(cfg: dict) -> dict:
    """Pin the model ids the provider actually serves today."""
    try:
        live = llm.live_models(cfg)
    except Exception:
        live = []
    if not live:
        return cfg
    for kind in ("text", "vision", "audio"):
        cfg["llm"][kind + "_model"] = llm.resolve_model(kind, cfg)
    return cfg


def run(args) -> int:
    interactive = not getattr(args, "yes", False)
    cfg = config.load(strict=False)
    config.load_env()

    ui.rule("savebrain setup")

    # ---------------- 1. provider key
    key = (getattr(args, "key", "") or "").strip() or config.api_key()
    if not key and interactive:
        ui.say("A free Groq API key powers the extraction, OCR and transcription.")
        ui.say("Get one in about 30 seconds: https://console.groq.com/keys")
        key = ui.ask("paste your key (starts with gsk_)").strip()
    if not key:
        ui.err("no API key -- rerun with --key gsk_... or add GROQ_API_KEY to .env")
        return 1
    _write_env(key)
    ui.ok("saved key to .env (git-ignored)")

    # ---------------- 2. domains
    preset = None
    if getattr(args, "domains", None):
        preset = str(args.domains).split(",")
    picked = _choose_domains(interactive, preset)
    cfg["domains"] = picked
    spec = domains.merge(picked)
    ui.ok("domains: %s" % ", ".join(spec["labels"]))
    ui.dim("folders: %s" % ", ".join(spec["categories"]))

    # ---------------- 3. vault location
    vault = (getattr(args, "vault", "") or "").strip()
    if not vault and interactive:
        vault = ui.ask("where should the notes live", cfg.get("vault_dir", "vault"))
    cfg["vault_dir"] = vault or cfg.get("vault_dir", "vault")

    # ---------------- 4. media handling
    if interactive:
        ui.rule("media")
        ui.say("Video posts can be transcribed and carousel slides can be read.")
        ui.say("Both default to the cloud API: nothing heavy to install.")
        cfg["transcribe"] = "cloud" if ui.ask_yes("transcribe videos?", True) else "off"
        cfg["ocr"] = "cloud" if ui.ask_yes("read text off carousel slides?", True) else "off"
        cfg["port"] = int(ui.ask("local bridge port", str(cfg.get("port", 8799))) or 8799)

    # ---------------- 5. pin live models, write everything out
    cfg = _refresh_models(cfg)
    config.save(cfg)

    vault_path = config.vault_dir(cfg)
    for cat in spec["categories"]:
        (vault_path / cat).mkdir(parents=True, exist_ok=True)
    for special in ("_inbox", "_digests", "_logs", "_index"):
        (vault_path / special).mkdir(parents=True, exist_ok=True)
    (vault_path / ".gitignore").write_text(
        "# your notes are yours -- nothing here is pushed anywhere\n*\n!.gitignore\n",
        encoding="utf-8")

    ui.ok("config.json written, vault ready at %s" % vault_path)

    ui.rule("two steps left")
    ui.say("1. Load the extension (once):")
    ui.say("     open  brave://extensions   (or chrome://extensions / edge://extensions)")
    ui.say("     turn on Developer mode -> Load unpacked -> select:")
    ui.say("     %s" % (config.ROOT / "extension"))
    ui.say("")
    ui.say("2. Every run:")
    ui.say("     python savebrain.py bridge          # leave it running")
    ui.say("     open instagram.com/<you>/saved/all-posts/ while logged in")
    ui.say("     click the extension -> Start")
    ui.say("     python savebrain.py ingest          # turns the catch into notes")
    ui.say("")
    ui.dim("check everything first with:  python savebrain.py doctor")
    return 0
