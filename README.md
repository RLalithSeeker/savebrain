# SaveBrain

**You save hundreds of posts. You reread none of them.**

SaveBrain turns your Instagram *Saved* folder into a searchable Markdown vault —
one clean note per post, with the video transcribed, the carousel slides read,
the links extracted and checked, and everything filed into folders that match
whatever you actually save about.

Cooking. Lifting. Money. Travel. Design. Parenting. Or software, if that is your thing.
**The subject is a config choice, not a fork.**

```
your browser (logged in, you)  ->  collector extension scrolls your Saved page
                               ->  local bridge on 127.0.0.1
                               ->  transcribe + read slides + extract
                               ->  vault/<folder>/2026-08-23_topic_author.md
```

Everything lands as plain Markdown with YAML frontmatter and `[[wiki-links]]`.
Open it in Obsidian, Logseq, VS Code, or just a file browser. No app, no lock-in,
no account. Your posts never leave your machine except for the model calls that
read them.

---

## What a note looks like

```markdown
---
date: 2026-08-19
author: somechef
source: https://www.instagram.com/p/XXXXXXXX/
categories: [recipes, technique]
tags: [one-pan-dinners, pantry-staples]
primary_link: seriouseats.com/one-pan-chicken
link_status: ok
media: carousel
---

# Sheet-pan chicken with a 3-ingredient pan sauce

**Go here:** seriouseats.com/one-pan-chicken

**TL;DR:** Roast at 220C on the top rack, then build the sauce in the same tin.

## Steps
1. Dry the chicken, salt it 40 minutes ahead...

## Key points
- The tin has to be hot before the chicken goes in...

**Mentioned:** sheet pan, Dijon, shallots

## Related
- [[2026-08-02_pan-sauce-ratios_anotherchef]]
```

Plus, every run: an updated `INDEX.md`, a compact index for AI tools, and a
paste-ready weekly digest you can hand to any chat model.

---

## Install

Needs **Python 3.9+** and a Chromium browser (Chrome, Brave, Edge) logged into
Instagram. Nothing else. No torch, no CUDA, no Docker.

```bash
git clone https://github.com/RLalithSeeker/savebrain.git
cd savebrain
pip install -r requirements.txt          # 3 small packages, all optional-ish
python savebrain.py setup                # pick your subjects, paste a free API key
python savebrain.py doctor               # confirms every moving part before you rely on it
```

`setup` asks five things and writes `config.json` + `.env`. The API key is a free
Groq key from <https://console.groq.com/keys> — it powers the extraction, the
slide reading and the transcription. Free tier is enough for normal use.

**Then load the collector extension, once:**

1. open `chrome://extensions` (or `brave://extensions`, `edge://extensions`)
2. turn on **Developer mode**
3. **Load unpacked** → select this repo's `extension/` folder

---

## Use it

```bash
python savebrain.py bridge      # leave this running
```

Open `instagram.com/<your-handle>/saved/all-posts/` in that browser, click the
SaveBrain icon, hit **Start**. The page scrolls itself at a human pace and stops
on its own — at the end of the feed, at your limit, or as soon as it reaches
posts you already have.

```bash
python savebrain.py ingest      # turns the catch into notes
```

> Instagram's media links expire after a few hours. Ingest the same day you collect.

Want it hands-off? A weekly scheduled run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1   # Windows
bash scripts/run_once.sh                                               # macOS/Linux (put it in cron)
```

---

## Pick your subject

```bash
python savebrain.py domains
```

Ships with 15 packs:

| | | |
|---|---|---|
| `tech` software, AI, dev tools | `fitness` training, nutrition, recovery | `cooking` recipes, technique, gear |
| `finance` budgeting, investing, tax | `travel` places, itineraries, logistics | `style` outfits, wardrobe, grooming |
| `design` type, colour, UI, branding | `business` marketing, sales, ops | `study` methods, exams, resources |
| `photography` shooting, editing, gear | `music` production, mixing, practice | `home` interiors, DIY, plants |
| `career` CV, interviews, negotiation | `wellness` sleep, mind, habits | `parenting` development, routines, gear |

Combine them freely — `--domains cooking,fitness` gives you one vault with both
sets of folders.

**Nothing fits?** Describe your subject and a pack gets written for you:

```bash
python savebrain.py new-domain "urban beekeeping"
python savebrain.py setup --domains urban-beekeeping --yes
```

A pack is one small JSON file: folder names, what counts as relevant, what to
reject, what a good tag looks like. Edit it by hand any time — see
[DOMAINS.md](DOMAINS.md).

---

## Why it does not get your account flagged

- **No API, no automation login, no password.** The extension reads the JSON
  Instagram's own web app already fetched for the page you are looking at.
- **Your real session.** It runs in your browser, with your cookies and your
  fingerprint, on a page you opened.
- **Read-only.** It never posts, likes, follows, or modifies a request.
- **Human cadence.** Randomized gaps, occasional scroll-backs, periodic breaks.
  Three speed presets; the default is the slow-ish one.

It is you scrolling your own saves, with the results written down.

---

## Cost and privacy

- Runs on Groq's **free tier**. Typical week (~30 posts) sits inside it.
- Posts are sent to the model provider only as: caption text, the audio of a
  video you saved, and the slide images. Nothing else leaves your machine.
- Notes, inbox and state live in `vault/`, which is git-ignored by default.
- Want zero cloud? Set `transcribe`/`ocr` to `local` in `config.json` and install
  `requirements-local.txt`, then point `fallback.base_url` at LM Studio or Ollama.

---

## Commands

| command | what it does |
|---|---|
| `setup` | interactive first run; `--domains a,b --key gsk_... --yes` for unattended |
| `doctor` | checks config, key, live models, packages, port, vault, extension |
| `bridge` | the local receiver; `--auto-ingest` to process automatically when a run ends |
| `ingest` | processes the inbox into notes; `--no-transcribe`, `--max N`, `--clear-inbox` |
| `domains` | lists installed packs, marks the active ones |
| `new-domain "subject"` | writes a new pack for any subject |
| `index` | rebuilds `INDEX.md` and the compact index |
| `auto` | one unattended cycle (used by the scheduling scripts) |

Something not working? [TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers every
failure we have actually hit. Start with `python savebrain.py doctor`.

Handing this to an AI coding agent instead of reading? Point it at
[AGENTS.md](AGENTS.md) — it is written for exactly that.

---

## Layout

```
savebrain.py           the CLI, all of it
core/                  config, domains, llm, media, links, notes, pipeline, bridge, doctor, wizard
domains/               one JSON per subject -- edit, add, or generate more
extension/             the browser collector (load unpacked)
scripts/               scheduled/unattended runs, Windows + Unix
vault/                 your notes (created at setup, never committed)
```

MIT licensed. Built for a friend who kept saving things and never looking at them again.
