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

**No opaque numbers.** A meter is allowed only when both poles name a concrete question and its
components and source IDs ship beside it. The benchmark includes a left/right economic-policy
axis because readers asked that question, but it classifies mechanisms (state provision versus
market/investment incentives); it never ranks people, truth or moral worth. Click any meter to
see its derivation, counter-evidence and uncertainty.

---

## The deployed dossier

GitHub Pages is intentionally a **single-document, precomputed edition**. It analyses the exact
DIPRES PDF [Informe Financiero N°84/22.04.2026](https://www.dipres.gob.cl/604/articles-409825_doc_pdf.pdf)
for Boletín 18.216-05. There is no “analyse a new document” control on the public site. The PDF,
news sweep, screenshots, actor profiles and model outputs are prepared offline and exported as
frozen JSON and image assets. The browser makes **zero LLM calls** and needs no API or database.

The general pipeline and upload API remain in this repository for local research and tests; they
are not part of this benchmark deployment.

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

### Local Blackwell inference and model choice

For the available 96 GB NVIDIA Blackwell GPU, the dossier is pinned to
`nvidia/Qwen3.5-122B-A10B-NVFP4@98915d837c4e7c87ac8296d02e89de19b3207e6d`.
The 122B mixture-of-experts checkpoint is the strongest model in the evaluated local set that
fits with decoding headroom in NVFP4. It serves an OpenAI-compatible endpoint inside the Compose
network and uses no hosted inference API. Pinning the exact revision makes later dossier exports
comparable; changing “latest” cannot silently change the analysis.

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

### Dossier news acquisition

Network retrieval is never implicit. The benchmark uses a deliberately broad,
viewpoint-neutral seed registry and preserves exact response bytes, one top-fold
screenshot, hashes and retrieval gaps in the append-only database:

```bash
.venv/bin/python scripts/capture_megareforma_sources.py --allow-network
```

The committed sweep covers 50 curated targets: 36 captured sources, including 25 press pieces,
six videos, one audio item and four comparative-research records. Fourteen inaccessible targets
remain published as gaps rather than disappearing from the denominator. Cards link to the original
publication and display the locally archived screenshot; audiovisual players are not embedded, so
the deployed page sends no request to a publisher until the reader opens the original.

Comparative questions run as a second, accumulated local-GPU analysis. The model may only cite the
source ids in each topic packet, and code rejects an invented reference before export:

```bash
.venv/bin/python scripts/analyze_comparative_evidence.py
```

The frozen result covers corporate tax and investment, fiscal self-financing, environmental
permitting, housing taxation, higher-education access and text/data-mining exceptions. Foreign
evidence is presented as a benchmark, never as an automatic forecast for Chile.

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

The public site is a **static presentation layer**. GitHub Pages runs no Python, scraper,
database or LLM — it serves precomputed JSON and images from `frontend/public/data/`.

A push to `main` runs lint → Python tests → schema validation → frontend typecheck and build →
container build, and **a failing test blocks the deploy**. The site publishes to
`https://mezosky.github.io/Aleph/`, which is why Vite's `base` is `/Aleph/`.

No model URL or credential is compiled into the benchmark frontend. Every analytical artifact is
already frozen before `npm run build`.

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

**The public benchmark is real and date-bounded.** The site loads
`frontend/public/data/megareforma/dossier.json` and its captured-source registry. It clearly
distinguishes the initial 22 April financial report from the bill later amended by Congress. Old
synthetic fixtures remain in the repository only to exercise the generic schema and regression
tests; the Vite publication step removes them from `dist`. Actor portraits carry Wikimedia licensing and factual profiles
remain structurally outside the blind verdict path. The municipal index covers every mayor with a
substantive intervention in the curated corpus at the stated cutoff (17 actors across 22 municipal
sources); it does not claim to be an exhaustive list of everything published on the internet.
Capture gaps remain visible and a later offline sweep may expand that universe.

The first benchmark document is Chilean (Boletín 18.216-05), but that fact lives only in data
files. No section, layout, actor, or query is hard-coded anywhere in `aleph/` — an arbitrary PDF
goes through exactly the same pipeline.

---

## License

See [LICENSE](LICENSE).
