# Planning & Decisions

How this project got built, in order, and why each major fork was decided the way it was.

## 1. Scope decisions (made up front)

Before writing any code, four architecture questions were settled first because they drive
everything downstream — cost, setup complexity, and what accounts/credentials are needed:

| Decision | Choice | Why |
|---|---|---|
| Interface | Local web chat app | Easiest to extend later (e.g. deploy somewhere) versus a CLI, and nicer than raw API calls for daily use |
| LLM + embeddings | Fully local (Ollama + sentence-transformers) | Zero ongoing cost, no API keys to manage, data never leaves the machine |
| Vector store | Chroma, local file-based | No server or account needed for a single-user tool — a folder on disk is enough |
| GitHub scope | All repos, including private | Needs the private ones to actually be useful as a personal knowledge base |

## 2. Build order

1. **Scaffold the pipeline**: config, embeddings, vector store, chunking, LLM client,
   retrieval pipeline, FastAPI app, static chat UI — in that dependency order, each piece
   smoke-tested before moving to the next (verified with a manually inserted test chunk
   before trusting real ingestion).
2. **GitHub ingestion**: discovered `gh` CLI was already authenticated as the account owner,
   so built ingestion around `gh repo list` / `gh repo clone` rather than asking for a
   personal access token — fewer credentials to manage, same result.
3. **Website ingestion**: crawler with `robots.txt` compliance and crt.sh-based subdomain
   discovery, built conservatively from the start (same-domain restriction, page limits)
   since it fetches arbitrary internet content.
4. **Full-scale test run**: ran ingestion against all 10 real repos. This is what surfaced
   the first real bug (see below) — plans survive first contact with real data, not
   synthetic tests.
5. **Security/reliability audit**: a dedicated pass treating the system as if it were going
   to production — see [TESTING.md](TESTING.md) for the complete findings and fixes. Several
   real bugs (not hypothetical) were found this way and are documented there rather than
   swept into this file's "and then it worked" narrative.

## 3. Real problems hit during the build (and what changed as a result)

- **300 `.webp` images silently decoded as garbage text**, producing ~9,500 junk chunks from
  one repo before I noticed the chunk count looked wrong. Extension blocklists are
  inherently incomplete — switched to sniffing file content (NUL-byte heuristic) instead of
  trusting file extensions.
- **A background ingestion run looked hung for minutes** with near-zero CPU usage. Root
  cause turned out to be two separate things: (1) Python fully buffers stdout when not
  attached to a terminal, making genuine progress invisible for a while, and (2) a real hang
  — the embedding model's "check Hugging Face Hub for a newer version" network call could
  stall for minutes even with the model already cached locally. Fixed the second one
  properly (skip the check once cached) rather than just re-running and hoping.
- **`shutil.rmtree` failed on Windows** when re-cloning a repo, because git marks pack files
  read-only. Needed a proper `onexc` handler, not a workaround.
- **Stale data**: re-ingesting never purged chunks for files/repos/pages that had since been
  deleted or renamed, because chunk IDs are content-addressed and nothing diffed old IDs
  against new ones. Fixed with a purge-before-reinsert pass, once this was pointed out during
  the audit rather than assumed to be fine.

## 4. What the audit changed

A full pass explicitly treated this as a system that needed active testing, not just code
review — see [TESTING.md](TESTING.md) for the complete record. The two most important
outcomes:

- **SSRF in the crawler was real, not theoretical**: the original crawler followed redirects
  without re-validating the target, so a same-domain page redirecting to a private IP would
  have been silently fetched. Fixed with a manual redirect loop that re-checks every hop.
- **Indirect prompt injection actually worked** against the original system prompt — a
  poisoned "document" got the local model to state a planted false claim as fact. A
  strengthened, delimited prompt fixed the *tested* payloads (verified 5/5 consistent runs)
  but this is documented as a mitigation, not a guarantee — prompt-based defense has a known
  ceiling, especially for a 14B local model.

## 5. Known gaps, left as documented trade-offs rather than fixed

- **Website ingestion currently indexes 0 pages** — the target domain's apex has no A/AAAA
  record (confirmed via independent DNS lookup, not assumed), and crt.sh subdomain discovery
  was returning 502s at test time. Both are external/operational facts, not code bugs — the
  crawler now logs exactly why a seed was rejected instead of failing silently. Next step is
  supplying real subdomain seeds directly once known.
- **No reranking/hybrid search** — plain top-k vector retrieval clusters on one repo for
  broad, non-specific questions (observed directly, documented in
  [TESTING.md](TESTING.md)). A real limitation, not fixed in this pass because it needs a
  genuinely new retrieval strategy, not a quick patch.
- **No auth layer** — deliberate, not an oversight, for a tool that only ever binds to
  `127.0.0.1`. Documented explicitly in the README as the boundary condition under which
  this assumption holds.
