# CLAUDE.md

Read [AGENTS.md](AGENTS.md). It is the full operating guide for setting up and
working on this repo, written for an AI agent.

Quick orientation:

- `savebrain.py` is the only entry point. Everything else lives in `core/`.
- The subject of the vault is a JSON file in `domains/`, never hardcoded logic.
- `python savebrain.py doctor` answers "why is it not working" before you guess.
- Never commit `.env`, `config.json`, or `vault/`.
