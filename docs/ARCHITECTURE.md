# Aleph — Architecture

Aleph takes **a document, its context, and the public discourse around it**, and produces an
inspectable analysis. It is deliberately *not* built around any particular reform: the first
benchmark is a Chilean bill, but nothing in the library, the schemas, or the frontend knows that.
Jurisdiction-specific facts live only in data and registry files.

---

## 1. The shape of the system

```mermaid
flowchart TB
    subgraph input["Input"]
        A1["PDF upload"]
        A2["Public PDF URL"]
        A3["Title / description hint"]
    end

    subgraph warm["WARM STAGE — build understanding before judging anything"]
        direction TB
        W1["1 · Document understanding<br/><i>DocumentModel</i>"]
        W2["2 · Proposition extraction<br/><i>atomic claims + verbatim spans</i>"]
        W3["3 · Topic graph<br/><i>who/what/affects whom</i>"]
        W4["4 · Search vocabulary<br/><i>how to find the debate</i>"]
        W5["5 · Evidence collection<br/><i>primary → technical → press</i>"]
        W6["6 · News clustering<br/><i>independence analysis</i>"]
        W7["7 · Readiness<br/><i>is there enough to say anything?</i>"]
        W1 --> W2 --> W3 --> W4 --> W5 --> W6 --> W7
    end

    subgraph eval["EVALUATION — gated on readiness"]
        E1["Blind factual evaluation<br/><b>speaker identity withheld</b>"]
        E2["Attributed analysis<br/><i>framing only — cannot change the verdict</i>"]
        E3["Framing profile · Impact axes · Beneficiary map"]
        E4["Contradiction clusters"]
        E5["Neutrality test suite"]
        E1 --> E2 --> E3 --> E4 --> E5
    end

    subgraph out["Output"]
        O1["AnalysisBundle (validated JSON)"]
        O2["Static datasets → GitHub Pages"]
        O3["Aleph API (live analysis)"]
    end

    input --> warm
    W7 -->|"ready / partial"| eval
    W7 -->|"insufficient — verdicts withheld"| O1
    eval --> O1 --> O2
    O1 --> O3
```

The single most important edge in that diagram is the one from **Readiness** that bypasses
evaluation. If the evidence is thin, Aleph says so and withholds verdicts. It does not substitute
model confidence for missing evidence.

---

## 2. Why the warm stage exists

The naive design asks a language model "is this bill good?" and renders the answer. That product
fails in a specific, predictable way: the model's prior about the topic does the work, and the
document becomes decoration.

The warm stage forces the opposite order. Before any evaluative question is asked, Aleph must
have parsed the document, reduced it to atomic propositions each anchored to a quotable passage,
mapped what it affects, worked out *how the public actually refers to it* (a bill's title is
rarely what the debate calls it), gathered evidence across tiers, and worked out how much of the
apparent coverage is genuinely independent.

Only then is there something to evaluate a claim *against*.

---

## 3. Independence from authority

Aleph separates two things that are constantly conflated:

| | |
|---|---|
| **Source authority** | who produced an artefact, and their standing |
| **Evidential relevance** | what that artefact can actually establish, for *this specific question* |

The distinction is implemented, not just documented. `aleph/evidence/rank.py` carries an explicit
tier-capability matrix — what each kind of source *can* and *cannot* establish — and the ranking
function has no per-institution or per-outlet prestige weight to tune.

So:

- An official bill text is decisive for *"what does the current draft say?"* and carries no weight
  at all for *"will this raise GDP?"*
- A budget office report is decisive for *"what does the budget office estimate?"* and does not
  establish *"this will happen."*
- A statement from an opposition figure and a statement from a minister are evaluated by the same
  rubric, because the evaluator cannot see which is which.

---

## 4. How speaker-blindness is enforced

This is a type-level guarantee rather than a convention, because conventions erode.

```mermaid
flowchart LR
    C["Claim<br/>(text + speaker + party + outlet)"]
    R{{"redact()"}}
    RC["<b>RedactedClaimContext</b><br/>text · date · semantic context · evidence<br/><i>no field exists for identity</i>"]
    BE["evaluate_blind()"]
    V["BlindEvaluation<br/>verdict + 10 epistemic checks"]
    AA["analyse_attributed()<br/><i>framing, consistency, patterns</i>"]
    OUT["Claim record"]

    C --> R --> RC --> BE --> V
    V -->|"frozen input"| AA
    C -.->|"identity restored here only"| AA
    V --> OUT
    AA --> OUT
```

`RedactedClaimContext` is a frozen model with `extra='forbid'` and **no field for speaker, party,
coalition, outlet, or government/opposition status**. `evaluate_blind()` accepts that type and
nothing else, so there is no code path by which political identity reaches the factual verdict —
adding one would require changing the type and failing the test suite.

Stage two restores provenance to analyse framing and rhetorical consistency, and takes the
`BlindEvaluation` as *frozen input*. A guard raises if the attributed stage tries to alter the
verdict.

The escape hatch — when the speaker's identity genuinely *is* the fact at issue ("did X say Y?") —
must be requested deliberately and is never the default.

---

## 5. Metrics: nothing opaque, nothing collapsed

Two rules shape every number in the product.

**No single left–right score.** The impact map has seven named axes, each scored −100..+100
against two *named poles*. They describe where a document's identified effects fall. They are not
party labels, and the schema descriptions say so explicitly.

**No score without its components.** Every composite carries a `components[]` array — the
individual contributions, each with a signed weight and evidence references — plus a `confidence`
object. Pydantic validators *raise* if a score is produced with an empty component list. An
uninspectable number is a contract violation, not a cosmetic problem.

The eight framing dimensions carry a `polarity` field (`higher_is_better` / `lower_is_better` /
`neutral`) so a consumer can never mis-colour them — a high `source_diversity` and a high
`loaded_language` are not the same kind of high.

Confidence is likewise split. **Evidence confidence** is derived from coverage, agreement,
corroboration, quantitative validation and retrieval completeness. **Model confidence** is
recorded as a diagnostic and is never the headline figure.

---

## 6. Deployment: static by default, live when available

```mermaid
flowchart LR
    subgraph gh["GitHub Pages — static presentation layer"]
        F["React · TypeScript · Vite<br/>base = /Aleph/"]
        D[("frontend/public/data/**<br/>precomputed JSON")]
        F -->|"reads"| D
    end

    subgraph api["Aleph API — optional, self-hosted"]
        S["FastAPI"]
        P["Warm stage → pipeline"]
        L["LLMProvider<br/>Qwen · vLLM · local · mock"]
        S --> P --> L
    end

    U["Browser"] --> F
    F -.->|"VITE_ALEPH_API_URL<br/>(only for live PDF analysis)"| S
    P -->|"export"| D
```

GitHub Pages serves static files and nothing else — no Python, no scrapers, no database, no
persistent container. So the site's default mode reads **precomputed JSON** and works with the
analysis API completely offline. The API is needed only for *Mode B*, analysing a new PDF on
demand, and its URL is injected at build time via `VITE_ALEPH_API_URL`.

No API key ever reaches the frontend bundle. Everything under `VITE_*` is compiled into public
JavaScript, which is exactly why the model credentials live only in the API's environment.

---

## 7. Model layer

The pipeline codes against an `LLMProvider` abstract base class — `complete(prompt, schema=...)`
plus an optional `embed()`. `QwenProvider` speaks the OpenAI-compatible chat-completions API that
vLLM and most Qwen deployments expose. `MockProvider` is fully deterministic and returns
schema-valid responses, so the entire pipeline, the test suite, and CI run offline with no
credentials.

Swapping the provider must leave the factual evaluation pipeline unchanged. That is the design
constraint the abstraction exists to protect.

---

## 8. Repository layout

```
Aleph/
├── aleph/                   # the library — document-agnostic, no jurisdiction logic
│   ├── core/                # ids, enums, pydantic models, config, errors
│   ├── ingestion/           # PDF bytes → text with layout and offsets
│   ├── documents/           # warm 1: DocumentModel, sections, provisions, quantities
│   ├── propositions/        # warm 2-3: atomic propositions, topic graph
│   ├── retrieval/           # warm 4: search vocabulary, search providers
│   ├── news/                # warm 5-6: source registry, clustering, independence
│   ├── evidence/            # evidence store, relevance-based ranking
│   ├── claims/              # extraction, fact/forecast classification, redaction, evaluation
│   ├── framing/             # the eight framing dimensions
│   ├── impact/              # seven policy axes, beneficiary and cost-bearer maps
│   ├── neutrality/          # six perturbations, runner, metrics
│   ├── llm/                 # LLMProvider, QwenProvider, MockProvider
│   ├── export/              # AnalysisBundle assembly, static site export
│   └── pipeline.py          # warm-stage orchestration + readiness gate
├── api/                     # FastAPI analysis service
├── schemas/                 # JSON Schema — the contract between backend and frontend
├── frontend/                # React/TS/Vite static site
│   └── public/data/         # precomputed analyses served by GitHub Pages
├── scripts/                 # validation, refresh, export CLIs
├── tests/                   # offline test suite
├── data/                    # raw / processed / exports working directories
└── .github/workflows/       # ci · pages · refresh
```

---

## 9. Data contract

`schemas/analysis_bundle.json` is the boundary. The backend validates against it before writing;
CI validates every committed dataset against it; the frontend's TypeScript types mirror it field
for field. Changing the shape of the product means changing that schema first.

Ids are stable and human-readable (`doc:`, `prov:`, `clm:`, `ev:`, `art:`, `cluster:`…), and
export is deterministic — sorted keys, stable ordering, unchanged files left untouched — so a
refresh run produces a clean, reviewable diff rather than noise.

---

## 10. What the neutrality suite does and does not prove

Before publishing, Aleph re-runs evaluations under six substitutions that *should not matter*:
speaker swap, source swap, party swap, authority removal, claim paraphrase, and evidence-order
shuffle. It tracks verdict flip rate, confidence delta, framing delta and explanation semantic
delta, and aggregates them into a neutrality health figure.

This measures **invariance under irrelevant substitution**. It does not prove political
neutrality, and the schema requires an `interpretation_caveat` string to be carried alongside the
number so the figure is never displayed as if it did.
