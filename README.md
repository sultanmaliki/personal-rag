# Personal RAG

A fully local, self-hosted RAG (retrieval-augmented generation) assistant over:

- **All of your GitHub repos** (including private ones), listed and cloned via the `gh` CLI.
- **Your website and its live subdomains** (`syedmohammedsultan.online` by default), crawled directly.

Everything runs on your machine: embeddings via [sentence-transformers](https://www.sbert.net/),
vector storage via [Chroma](https://www.trychroma.com/) (a local folder, no server/account needed),
and answers via a local [Ollama](https://ollama.com/) model. No API keys, no cloud bills.

**Docs:** [the idea behind this](IDEA.md) · [system architecture](ARCHITECTURE.md) ·
[planning & decisions log](PLANNING.md) · [full testing report](TESTING.md)

## 1. Prerequisites

- Python 3.10+ (tested on 3.14)
- [Ollama](https://ollama.com/) installed and running, with a model pulled, e.g.:
  ```bash
  ollama pull qwen3:14b
  ```
- [GitHub CLI](https://cli.github.com/) installed and authenticated:
  ```bash
  gh auth status   # should show a logged-in account
  ```

## 2. Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then edit values if needed
```

The defaults in `.env.example` already match this project's owner (GitHub user
`sultanmaliki`, site `syedmohammedsultan.online`) — adjust if that's wrong, or
if you want to point this at a different GitHub account or domain.

## 3. Ingest your knowledge

```bash
python scripts/ingest_github.py
python scripts/ingest_website.py
```

- `ingest_github.py` lists every repo you own via `gh repo list`, shallow-clones
  each into `data/repos/`, and indexes source/docs files (skipping build output,
  dependencies, binaries, and lockfiles).
- `ingest_website.py` optionally discovers live subdomains via crt.sh
  (certificate-transparency logs — a passive lookup, not a scan), then crawls
  same-domain pages while respecting `robots.txt`, extracting readable text.

Both scripts are safe to re-run — repos are re-cloned fresh, chunks are
upserted by a stable ID so nothing duplicates, and stale entries (deleted
files, renamed/removed repos, pages no longer reachable) are purged
automatically on each run.

**Note on subdomain discovery:** `ingest_website.py` finds subdomains via
crt.sh, a free community certificate-transparency mirror — it's best-effort
and occasionally returns errors or is temporarily down; the script logs this
and continues rather than failing. If your apex domain itself has no
A/AAAA record (common if everything is served from named subdomains, e.g.
behind Cloudflare Workers/Pages), add your actual subdomains directly to
`WEBSITE_SEED_URLS` in `.env` rather than relying solely on discovery — the
script logs exactly why any seed URL was rejected (bad scheme, wrong domain,
no DNS record, etc.) so a zero-page crawl is never a silent mystery.

## 4. Run the assistant

Every time after initial setup, you just need this (Ollama runs as a
background app on Windows and stays up on its own):

```powershell
.\start.ps1
```

Or manually:

```bash
.venv\Scripts\activate
uvicorn app.main:app --reload
```

Open http://localhost:8000 and start asking questions. Every answer cites the
repo/file or URL it drew from.

**Chat history** persists across restarts (SQLite, `data/conversations.db`) —
past conversations live in the sidebar, click one to continue it, and the app
remembers your last-open conversation across page reloads. **Answers stream
in live**, and the model's reasoning trace streams into a collapsible
"Thinking" panel above the answer (expanded while it's actively reasoning,
collapsed once the answer starts) — the same pattern Claude's own UI uses.
Follow-up questions in the same conversation get the prior turns as context,
so "what about its backend?" correctly resolves to whatever project you were
just discussing. Code in answers renders as real syntax-highlighted blocks
with a copy button, not plain text with literal backticks. The UI passes a
WCAG AA contrast check, is fully keyboard-navigable (including the
conversation sidebar), and adapts to a phone-width screen — see
[TESTING.md](TESTING.md) for the full accessibility/mobile audit.

Note: showing the reasoning trace means Ollama runs with `think: true`,
which is noticeably slower than the non-thinking default — qwen3:14b can take
60–100+ seconds on an ambiguous question as it reasons through multiple
angles before answering. This is a deliberate trade-off (transparency over
speed), not a bug; see [TESTING.md](TESTING.md) for measured examples.

This binds to `127.0.0.1` (localhost-only) by default and has **no
authentication** — that's intentional for a single-user local tool. If you
ever run this with `--host 0.0.0.0` or expose it through a tunnel, add an
auth layer first; as shipped it assumes only you can reach the port.

## Configuration

All settings live in `.env` (see `.env.example` for the full list and defaults):
GitHub username/fork inclusion, website domain/seed URLs/crawl limits, chunk
size/overlap, retrieval top-k, and which embedding/Ollama model to use.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```

Covers chunking edge cases, the SSRF defenses in the website crawler
(redirect validation, private-IP blocking, response-size caps), the
stale-data purge logic, conversation persistence (SQLite CRUD, isolated from
your real chat history), API input validation, a live end-to-end streaming
test (asks a real question, confirms both turns persisted, asks a follow-up
and confirms it reused the same conversation), and a live prompt-injection
check against your running Ollama model (skipped automatically if Ollama
isn't reachable).

To spot-check answer *quality* rather than just correctness of the plumbing,
run `python scripts/eval_run.py` — it asks one question per ingested repo
plus 10 broad cross-repo questions against your live knowledge base and
writes every answer, citation, and latency to `eval_results.md`. See
[TESTING.md](TESTING.md) for a worked example, including two real bugs it
caught and fixed.

## Project layout

```
app/            FastAPI backend + static chat UI + RAG pipeline
app/store/      SQLite conversation history (CRUD)
ingest/         GitHub and website ingestion logic
scripts/        CLI entry points for ingestion
tests/          Regression test suite (pytest)
data/           Cloned repos + Chroma index + conversations.db (gitignored, local only)
```
