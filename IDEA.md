# Core Idea

## The problem

Knowledge about what I've built lives scattered across dozens of GitHub repos and a personal
website — READMEs, source comments, project pages, half-remembered implementation details.
Answering a simple question like *"which of my projects used JWT auth?"* or *"what stack did
I use for the hospital management system?"* means manually grepping through old repos or
scrolling a portfolio site.

## The idea

Turn that scattered knowledge into something queryable: a retrieval-augmented generation
(RAG) assistant that has actually read every repo I own and every page of my site, and can
answer questions about my own work with real citations back to the source.

## Design principles

- **Fully local and free.** No API keys, no per-query cost, no data leaving the machine.
  Embeddings run via `sentence-transformers`, generation runs via a local Ollama model,
  storage is a Chroma folder on disk. This is a tool for one person, so it should cost
  nothing to run indefinitely.
- **Own the data pipeline.** GitHub access goes through the already-authenticated `gh` CLI
  rather than a bespoke token — one less credential to manage or leak. Website crawling
  respects `robots.txt` and stays scoped to the owned domain.
- **Answers must be honest.** Every answer cites the repo/file or URL it came from. If the
  knowledge base doesn't contain something, the assistant says so instead of guessing —
  verified directly in [TESTING.md](TESTING.md) with adversarial "you don't actually know
  this" probes.
- **Untrusted content stays untrusted.** Source code and web pages are ingested from many
  places over time; the LLM is explicitly told to treat retrieved content as data to cite,
  never as instructions to follow. This mattered in practice — see the prompt-injection
  findings in [TESTING.md](TESTING.md).

## Who it's for

Just me, for now: a fast way to ask "have I built something like this before?" or "how did
I structure X last time?" without archaeology. The architecture doesn't assume multi-user
access, and deliberately doesn't build auth/rate-limiting/multi-tenancy it doesn't need —
see [ARCHITECTURE.md](ARCHITECTURE.md) for what that trade-off means in practice.
