<div align="center">

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

```bash
# Backend + tests, no credentials and no network required
python -m venv .venv && . .venv/bin/activate
pip install -e '.[api,dev]'
pytest                                    # runs fully offline against MockProvider
python scripts/validate_schemas.py        # JSON Schema contract check

# Frontend
cd frontend && npm install && npm run dev
```

Or the whole thing at once:

```bash
docker compose up
# API      → http://localhost:8000/v1/health
# Frontend → http://localhost:5173
```

Analyse a document through the library:

```python
from aleph.pipeline import run_analysis
from aleph.llm import get_provider

bundle = run_analysis("path/to/document.pdf", provider=get_provider("mock"))

print(bundle.readiness.overall_state)      # insufficient | partial | ready
print(len(bundle.propositions))
for axis, a in bundle.impact_map.axes.items():
    print(axis, a.score, [c.label for c in a.components])   # never a bare number
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
  framing/      the eight framing dimensions
  impact/       seven policy axes, beneficiary and cost-bearer maps
  neutrality/   six perturbations, runner, metrics
  llm/          LLMProvider · QwenProvider · MockProvider
  export/       AnalysisBundle assembly, static site export
api/            FastAPI analysis service
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
abstraction with a deterministic mock; export, validation and the API. The test suite runs
offline with no credentials.

**Scaffolded behind interfaces:** live web retrieval and crawling (a `SearchProvider` interface
with a deterministic mock; the source registry ships with `verified: false` on every entry and
`null` URLs wherever a feed address was not confirmed — those need checking before any real
crawl), and LLM-assisted extraction (works against `MockProvider`; `QwenProvider` needs a running
endpoint).

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
