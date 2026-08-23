# AGENTS.md — instructions for an AI coding agent setting this up

You are installing **SaveBrain** for a person who wants their saved Instagram
posts turned into a Markdown knowledge vault about a subject *they* choose.

Work through this top to bottom. It is written so you can finish without asking
the user anything except the two things only they can supply: **their subject**
and **their API key**.

---

## 0. What this repo is

| piece | what it does | file |
|---|---|---|
| CLI | every command | `savebrain.py` |
| config | paths, models, domains, pacing | `core/config.py`, `config.json` (generated) |
| domain packs | what "relevant" means, which folders exist | `domains/*.json` |
| model calls | chat, vision OCR, whisper — plain stdlib HTTP, no SDK | `core/llm.py` |
| media | download, downscale, transcribe, OCR | `core/media.py` |
| notes | note/bucket/index/digest writers | `core/notes.py` |
| ingest | the run loop | `core/pipeline.py` |
| bridge | local receiver for the extension | `core/bridge.py` |
| checks | preflight diagnostics | `core/doctor.py` |
| collector | MV3 browser extension | `extension/` |

Data flow: **extension → `POST 127.0.0.1:<port>/post` → `vault/_inbox/inbox.jsonl`
→ `ingest` → `vault/<category>/*.md`**.

---

## 1. Preconditions to verify first

```bash
python --version        # need 3.9+
```

- A Chromium browser (Chrome / Brave / Edge) that is **logged into Instagram**.
  Firefox and Safari are not supported: the extension is MV3.
- Ask the user for a free Groq key if they have not got one:
  <https://console.groq.com/keys>. Do not proceed without it — every extraction
  path needs it.

Do **not** install torch, CUDA, easyocr or whisper. The default path is cloud
and deliberately dependency-light. Only touch `requirements-local.txt` if the
user explicitly asks to run offline.

---

## 2. Install

```bash
pip install -r requirements.txt
```

Three packages, all with graceful fallbacks: `rich` (nicer output), `python-dotenv`
(there is a built-in parser if it is missing), `pillow` (image downscaling —
without it, vision calls cost more but still work). If pip fails on any of them,
continue; do not fight it.

---

## 3. Choose the domain — the one real decision

Ask the user: **"what do you save posts about?"**

Then:

```bash
python savebrain.py domains       # lists the 15 shipped packs
```

- One or several packs fit → use them: `--domains cooking,fitness`
- Nothing fits → generate one:
  ```bash
  python savebrain.py new-domain "the subject in their words"
  ```
  This writes `domains/<id>.json`. **Read it back to the user** — the folder
  names are what their vault will look like for years. Edit the JSON directly if
  they want different folders; the schema is in `DOMAINS.md`.

Never leave the default `tech` pack in place unless tech is genuinely their subject.

---

## 4. Configure

Interactive (preferred if a human is at the keyboard):

```bash
python savebrain.py setup
```

Unattended (you already know the answers):

```bash
python savebrain.py setup --domains cooking,fitness --key gsk_xxx --yes
```

This writes `.env` (key only, git-ignored) and `config.json`, creates the vault
folders, and pins the model ids the provider actually serves today.

---

## 5. Verify before declaring success

```bash
python savebrain.py doctor
```

Every line is PASS / WARN / FAIL with the fixing command attached. **Do not tell
the user it is installed while any FAIL is on screen.** WARNs are fine — they
mean something is degraded, not broken (no ffmpeg, no Pillow, a retired model id
that was auto-substituted).

---

## 6. Load the extension (the user must click this, you cannot)

Give them these four lines verbatim, with the real absolute path filled in:

1. open `chrome://extensions` (or `brave://extensions` / `edge://extensions`)
2. turn on **Developer mode** (top right)
3. click **Load unpacked**
4. select `<repo>/extension`

There are no icon files, so the browser shows a default puzzle piece. That is
expected, not a broken install.

---

## 7. First run

```bash
python savebrain.py bridge
```

Leave it running. Tell the user to open
`https://www.instagram.com/<their-handle>/saved/all-posts/`, click the SaveBrain
icon, and press **Start**. A small panel appears bottom-right of the page with a
live count and the bridge status.

When it finishes (it stops itself):

```bash
python savebrain.py ingest
```

Then show them `vault/INDEX.md` and one written note. That is the moment the
thing becomes real to them.

**Timing matters:** Instagram's media URLs are signed and expire in a few hours.
Ingest the same day as the collection, or slides and audio will 403.

---

## 8. Optional extras, only if asked

- **Weekly hands-off run**
  - Windows: `powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1`
  - macOS/Linux: put `bash scripts/run_once.sh` in cron
  - Both need `instagram_username` set in `config.json`.
- **Offline / no cloud**: `pip install -r requirements-local.txt`, set
  `"ocr": "local"` and `"transcribe": "local"` in `config.json`, and point
  `fallback.base_url` at LM Studio (`http://localhost:1234/v1`) or Ollama
  (`http://localhost:11434/v1`) with a `fallback.model`. Warn them this pulls in
  torch and is a much heavier install.
- **A second vault** for a different subject: clone the repo again into another
  folder with its own `config.json`, or set `vault_dir` to a different path and
  keep separate configs. One config = one vault.

---

## 9. Failure modes you will actually hit

| symptom | cause | fix |
|---|---|---|
| bridge dot red in the popup | bridge not running, or popup port ≠ config port | start it; make the numbers match |
| "content script not loaded" | tab predates the extension load | reload the Instagram tab |
| posts stay at 0 while scrolling | not on a Saved feed, or not logged in | open `/saved/all-posts/`, check login |
| `ingest` says no inbox | nothing collected yet | run the bridge and a collection first |
| slide/audio download 403 | media links expired | re-collect, ingest same day |
| `HTTP 429` mid-run | free-tier rate limit | it stops cleanly and keeps the queue; re-run later, or set a fallback endpoint |
| a model id 404s | provider retired it | `doctor` auto-substitutes a live one; re-run `setup` to pin it |
| notes land in `uncategorized` | the pack does not match what they save | edit the categories in `domains/<id>.json`, then `python savebrain.py ingest --reset` |

---

## 10. Rules

- **Never commit `.env`, `config.json`, or `vault/`.** `.gitignore` already
  covers them; do not "helpfully" add them.
- **Never** write the user's API key into any file other than `.env`, and never
  echo it back in full.
- A post that fails is deliberately **not** marked processed, so it retries next
  run. Do not "fix" that by marking everything seen.
- Do not add scraping of anyone else's account, hashtags, or the public feed.
  This tool reads one thing: the signed-in user's own saved posts. Keep it that way.
- If you change extraction fields in `core/domains.py`, update `core/notes.py`
  in the same edit — the renderers read those exact keys.
