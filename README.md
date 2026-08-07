<div align="center">

<img src="frontend/public/logo-256.png" alt="Aleph logo" width="160">

# א · ALEPH

**Entiende la evidencia detrás del debate público.**

Aleph takes a public document, works out what it actually says, finds the debate happening around
it, and shows you the evidence — claim by claim, with every number traceable back to a passage you
can read yourself.

[Architecture](docs/ARCHITECTURE.md) · [Methodology](docs/METHODOLOGY.md) · [Schemas](schemas/)

</div>

---

## What this is

Most tools that touch political documents do one of two things: they summarise (and you have to
trust the summary), or they score (and you have to trust the scorer). Aleph is built on the
premise that both are the wrong product.

The input is **document + context + public discourse**. The output is an *inspectable analysis*:
what is being claimed, what evidence exists, what the document actually says, which assumptions a
claim depends on, what contradicts it, what context was left out, who benefits, who pays, how
different outlets are framing the same development, and what remains genuinely uncertain.

Aleph does not tell you who to believe.

### Three design commitments

**The warm stage.** Aleph never opens with "is this bill good?" It first parses the document into
a structured model, reduces it to atomic propositions each anchored to a verbatim passage, maps
what it affects, derives how the public actually refers to it, gathers evidence, and measures how
much of the coverage is genuinely independent. Only then — and only if a readiness score says
there is enough to work with — does it evaluate anything. When the evidence is thin, Aleph says
so instead of covering the gap with model confidence.

**Speaker-blind factual evaluation.** The factual verdict is produced by a function that
*structurally cannot see* who spoke. `RedactedClaimContext` is a frozen type with no field for
speaker, party, coalition, outlet, or government/opposition status. Provenance is restored only
afterwards, to analyse framing — and the attributed stage takes the verdict as frozen input and
raises if it tries to change it. A minister and an opposition spokesperson get the same rubric,
because the evaluator cannot tell them apart.

**No opaque numbers, no single political axis.** There is no left–right score anywhere in this
product; policy effects are described on seven named axes with two named poles each. And no score
exists without its `components[]` — the individual contributions, signed, with evidence
references. A pydantic validator *raises* if you try to publish a score with an empty component
list. Click any number and you get the derivation, the counter-evidence, and the uncertainty.

---

## Two modes

| | |
|---|---|
| **A · Precomputed analyses** | Curated documents, deeply processed ahead of time and exported to static JSON. Works with no backend at all — this is what GitHub Pages serves. |
| **B · Analyse any PDF** | Upload a file or paste a URL and watch the seven warm-stage phases run. Requires the Aleph API. |

---

## Quick start

The build contract is Python 3.12 and Node 22 (pinned in `.python-version`,
`.nvmrc`, Docker, and CI). Python 3.11–3.13 remain supported by the package;
3.12 is the reproducible build and deployment target. Frontend dependencies are
locked by `package-lock.json`.

```bash
# Backend + tests, no credentials and no network required
python -m venv .venv && . .venv/bin/activate
pip install -e '.[api,dev]'
pytest                                    # runs fully offline against MockProvider
python scripts/validate_schemas.py        # JSON Schema contract check
python scripts/validate_data.py           # committed bundle + referential checks
python scripts/validate_design_tokens.py  # light/dark semantic colour contract

# Frontend
cd frontend && npm install && npm run dev
```

Or the whole thing at once:

```bash
docker compose up
# API      → http://localhost:8000/v1/health
# Frontend → http://localhost:5173
```

PostgreSQL is part of that stack. Uploaded bytes, source snapshots, analysis
runs and phase artifacts survive API restarts; rerunning a document creates a
new version linked by `supersedes_run_id` and never updates the earlier result.

### Local Blackwell inference

The GPU profile is pinned to
`nvidia/Qwen3.5-122B-A10B-NVFP4@98915d837c4e7c87ac8296d02e89de19b3207e6d`.
It serves an OpenAI-compatible endpoint inside the Compose network and uses no
hosted inference API.

```bash
# First launch: downloads the pinned checkpoint into the model_cache volume.
ALEPH_LLM_PROVIDER=qwen docker compose --profile local-llm up --build

# Later launches: prohibit Hugging Face access after the checkpoint is cached.
HF_HUB_OFFLINE=1 ALEPH_LLM_PROVIDER=qwen \
  docker compose --profile local-llm up
```

The vLLM process uses one GPU, NVFP4 weights, an FP8 KV cache and a conservative
32K working context so the 96 GB card retains decoding headroom. Aleph sends a
JSON Schema with every structured request and validates the returned payload
again before accepting it.

On a host without Docker, the equivalent native path is isolated from Aleph's
application environment:

```bash
scripts/bootstrap_local_llm.sh
scripts/serve_local_llm.sh

# In a second terminal:
ALEPH_LLM_PROVIDER=qwen \
ALEPH_QWEN_BASE_URL=http://127.0.0.1:8001/v1 \
ALEPH_DATABASE_URL=sqlite:///./data/aleph.db \
  .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000

# Submit a PDF; the response contains a durable analysis id.
curl -F "file=@/absolute/path/to/document.pdf" http://127.0.0.1:8000/v1/analyses
```

The server launch is offline-only after bootstrap: it resolves the pinned local
snapshot, disables runtime Hub access, and exposes its health endpoint at
`http://127.0.0.1:8001/health`. Watch checkpoint, GPU, durable-analysis and
retrieval counters in another terminal:

```bash
~/aleph-progress -w
```

### Live news acquisition

Network retrieval is never implicit. Poll only registry entries whose feeds and
robots policy have been verified, and preserve exact feed/article bytes in the
append-only database, with:

```bash
.venv/bin/python scripts/refresh.py --fetch \
  --query "18216-05 megarreforma reconstrucción desarrollo económico social" \
  --max-articles 20
```

Repeated runs update first/last observation times and deduplicate articles by
canonical URL and content hash; they do not overwrite prior scrape runs or
retrieval snapshots. Omit `--fetch` to regenerate deterministic static demo
data without network access.

Analyse a document through the library:

```python
from aleph.pipeline import run_analysis
from aleph.llm import get_provider

bundle = run_analysis("path/to/document.pdf", provider=get_provider("mock"))

print(bundle.readiness.overall_state)      # insufficient until retrieval runs
print(len(bundle.propositions.propositions))
print([phase.state for phase in bundle.phases])
```

---

## Repository layout

```
aleph/          the library — document-agnostic; no jurisdiction logic anywhere
  core/         ids, enums, pydantic models, config, errors
  ingestion/    PDF bytes → text with layout, offsets and quality flags
  documents/    warm 1 · DocumentModel, sections, provisions, quantities
  propositions/ warm 2-3 · atomic propositions, topic graph
  retrieval/    warm 4 · search vocabulary, search providers
  news/         warm 5-6 · source registry, clustering, independence analysis
  evidence/     evidence store, relevance-based ranking (no prestige weighting)
  claims/       extraction, fact/forecast classification, redaction, evaluation
  actors/       attributed-only profiles, blind-path tripwire, track records
  framing/      the eight framing dimensions
  impact/       seven policy axes, beneficiary and cost-bearer maps
  neutrality/   six perturbations, runner, metrics
  llm/          LLMProvider · QwenProvider · MockProvider
  export/       deterministic JSON export and contract validation
api/            FastAPI service + durable SQLAlchemy repository
migrations/     Alembic database migrations
schemas/        JSON Schema — the contract between backend and frontend
frontend/       React · TypeScript · Vite · Tailwind
  public/data/  precomputed analyses served by GitHub Pages
scripts/        validation, refresh and export CLIs
tests/          offline test suite
```

---

## Deployment

The public site is a **static presentation layer**. GitHub Pages runs no Python, no scrapers, no
database — it serves precomputed JSON from `frontend/public/data/`, and the site is fully
functional with the analysis API switched off.

A push to `main` runs lint → Python tests → schema validation → frontend typecheck and build →
container build, and **a failing test blocks the deploy**. The site publishes to
`https://mezosky.github.io/Aleph/`, which is why Vite's `base` is `/Aleph/`.

The API URL is injected at build time through `VITE_ALEPH_API_URL` and is not coupled to any
hosting provider. Everything under `VITE_*` is compiled into public JavaScript, so no model
credential is ever referenced there — those live only in the API's own environment.

---

## Status — read this before trusting any output

This is a **production-quality skeleton**, and the parts that are real and the parts that are
scaffolding are worth being precise about.

**Real and working:** the JSON Schema contract; the pydantic model layer and its validators; PDF
parsing, section/provision segmentation and locale-aware quantity extraction; rule-based
proposition and claim extraction; the redaction layer and its leak assertions; the epistemic
check → verdict derivation; near-duplicate and syndication detection; the framing, impact and
beneficiary computations; the six neutrality perturbations and their metrics; the provider
abstraction with a deterministic mock; local vLLM/Qwen structured inference; immutable source
snapshots; append-only PostgreSQL analysis history; export, validation and the API. The test suite
runs offline with no credentials.

**Scaffolded behind interfaces:** general web search (a `SearchProvider` interface with a
deterministic mock). Verified Chilean news feeds have a separate explicit acquisition path that
checks the registry and robots policy, applies per-host delays, and stores immutable response
bytes. Sources without a confirmed machine-readable endpoint remain excluded. Live uploads
therefore persist a real document analysis, but readiness still withholds
claim verdicts until a frozen evidence set has been collected. `QwenProvider` requires the local
GPU profile (or another explicitly configured OpenAI-compatible endpoint).

**The bundled analysis is synthetic.** Every dataset in `frontend/public/data/` carries
`"data_status": "synthetic"` and the UI shows a banner saying so. The outlets are invented, the
speakers are generic roles, and no quotation is attributed to any real person or publication.
It exists to exercise the rendering path and the schema contract — it is not an analysis of any
real reform, and it should not be read as one.

The first benchmark document is Chilean (Boletín 18.216-05), but that fact lives only in data
files. No section, layout, actor, or query is hard-coded anywhere in `aleph/` — an arbitrary PDF
goes through exactly the same pipeline.

---

## License

See [LICENSE](LICENSE).
