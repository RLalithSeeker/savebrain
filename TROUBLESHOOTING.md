# Troubleshooting

Run this first. It checks every moving part and prints the fix next to whatever
is broken:

```bash
python savebrain.py doctor
```

---

## Setup

**`python` is not recognized / wrong version**
Install Python 3.9+ from python.org and tick *Add python.exe to PATH*. On macOS
and Linux use `python3` everywhere in these docs.

**`pip install -r requirements.txt` fails**
Keep going. All three packages are optional: `rich` only makes output prettier,
`.env` has a built-in parser if `python-dotenv` is missing, and without `pillow`
the images are simply sent at full size. Run `doctor` to confirm.

**`No config.json yet`**
`python savebrain.py setup`.

**`GROQ_API_KEY not set`**
Get a free key at <https://console.groq.com/keys>, then either re-run `setup` or
put `GROQ_API_KEY=gsk_...` in `.env` at the repo root. No quotes, no spaces.

**`unknown domain pack(s)`**
`python savebrain.py domains` lists the valid ids. For anything else:
`python savebrain.py new-domain "your subject"`.

---

## The extension

**The icon does nothing / no panel appears on the page**
Reload the Instagram tab. A content script only injects into tabs opened *after*
the extension was loaded.

**Popup says "content script not loaded"**
Same fix: reload the tab. If it persists, check the extension is enabled at
`chrome://extensions` and that the page is `https://www.instagram.com/...`.

**Bridge shows offline (red) in the popup or the page panel**
- Is `python savebrain.py bridge` actually running?
- Does the port in the popup match `config.json`? Default 8799 in both.
- Something else on 8799? Change both: `python savebrain.py bridge --port 8801`
  and the popup field.

**The count stays at 0 while the page scrolls**
- You are not on a Saved feed. It must be `instagram.com/<you>/saved/all-posts/`
  or one of your collections.
- You are logged out — the panel says so explicitly.
- Instagram changed its response shape. The collector walks the JSON generically,
  but if this happens, open an issue with what the bridge terminal printed.

**It stops after a few seconds saying "caught up"**
Working as designed: it reached posts already in your vault. New saves sit at the
top, so there is nothing below worth scrolling to. To force a full pass, set
`caughtUpStop: 0` in `extension/content.js` `DEFAULTS` and reload the extension.

**It stops too early otherwise**
Raise *Max posts* in the popup. It also stops after 6 scrolls with nothing new,
which is a genuine end-of-feed signal.

---

## Ingest

**`no inbox at ...`**
Nothing has been collected yet. Bridge → collect → then ingest.

**Slide or video download fails, 403s everywhere**
Instagram's media URLs are signed and expire after a few hours. Collect and
ingest the same day. Re-collect the posts and run again.

**`HTTP 429` / rate limit**
Free-tier quota. The run stops cleanly, and any post that did not finish stays in
the inbox and is retried next time — nothing is lost. Options:
- wait and re-run `python savebrain.py ingest`
- run with `--no-transcribe` (transcription is the expensive part)
- set `"ocr": "off"` for a pass that only reads captions
- add a fallback endpoint in `config.json` (LM Studio, Ollama, OpenRouter):
  ```json
  "fallback": { "base_url": "http://localhost:1234/v1", "model": "your-local-model", "api_key_env": "FALLBACK_API_KEY" }
  ```

**`model_not_found` / a model id 404s**
The provider retired it. `core/llm.py` substitutes a live model automatically and
prints what it used; re-run `python savebrain.py setup --yes` to pin the new id.

**Videos over 24MB are skipped**
That is the upload cap. Install `ffmpeg` and they get compressed to audio-only
first. Otherwise the note is still written, just without a transcript.

**Everything lands in `uncategorized`**
Your pack does not describe what you actually save. Edit
`domains/<id>.json` — add the folders you want, sharpen the `relevant` lines.
Then delete `vault/.processed.json` and re-ingest to re-file the same inbox.

**Posts are marked irrelevant that you wanted kept**
Loosen `relevant` in your pack, and check `not_relevant` is not too broad. The
prompt is instructed to be generous, so a rejection usually traces to a specific
`not_relevant` line.

**`link_status: dead` on notes**
The URL was read off a stylized image and could not be verified. The link is kept
and flagged, never silently invented. Set `"verify_links": false` to skip the
check entirely.

---

## Windows specifics

**Unicode errors in the console**
`set PYTHONIOENCODING=utf-8` before running, or use Windows Terminal.

**`running scripts is disabled on this system`**
Use `powershell -ExecutionPolicy Bypass -File scripts\...` as shown in the docs.

**The scheduled task runs but nothing happens**
Its log lands in `vault/_logs/`. The usual cause is a logged-out browser session:
the extension detects it and the log says `logged_out`. Log back in once; the next
run resumes.

---

## Still stuck

Open an issue with:
- the output of `python savebrain.py doctor`
- what the bridge terminal printed
- what the on-page panel said

Leave out your API key and your notes.
