# Aleph — Methodology

This document states what Aleph does, on what basis, and where it stops. It is meant to be read
adversarially: if a conclusion in the product cannot be traced through the steps below to a
passage you can read yourself, that is a defect.

---

## 1. What gets evaluated, and what doesn't

Aleph sorts every statement it encounters into one of five kinds, because they are not checkable
in the same way and must never be displayed as though they were.

| Kind | Example | How Aleph treats it |
|---|---|---|
| **Fact** | "The bill reduces the rate from 27% to 23%." | Checked against the primary document and the evidence set. Gets a verdict. |
| **Interpretation** | "The reform prioritises investment incentives over transfers." | Assessed for defensibility against the provisions. Not true/false. |
| **Forecast** | "The reduction will increase investment." | Never "supported". Returns `forecast_conditional` with the assumptions it depends on listed. |
| **Opinion** | "This is unfair." | `not_a_factual_claim`. Recorded, never scored. |
| **Normative** | "Municipalities ought to be compensated." | `not_a_factual_claim`. |

Classification is itself inspectable: the classifier returns the linguistic cues that triggered
it — modality, tense, evaluative predicates, conditionals, deontic verbs — so a disputed
classification can be argued with rather than merely disbelieved.

---

## 2. The ten epistemic criteria

Every factual claim is assessed against the same speaker-independent rubric. Each check is
recorded individually as pass / fail / not-applicable with a note, and the verdict is derived
from the recorded checks by an explicit decision function — **not** by asking a model for a bare
label.

1. **Direct textual evidence** — does the primary document say this?
2. **Data consistency** — is it consistent with the underlying figures?
3. **Quantitative correctness** — do the numbers actually compute? Arithmetic is re-checked.
4. **Logical validity** — does the conclusion follow from the premises?
5. **Causal support** — is a causal claim backed by more than co-occurrence?
6. **Uncertainty** — is stated confidence proportionate to the evidence?
7. **Completeness of context** — does an omission change the meaning?
8. **Temporal correctness** — does it describe the current version of the document?
9. **Independent corroboration** — do genuinely independent sources agree?
10. **Contradiction with stronger evidence** — does better evidence point the other way?

What is **never** an input: political party, coalition, government or opposition status,
institutional prestige, or social standing. These are not weighted lightly — they are absent from
the type that reaches the evaluator.

---

## 3. Blind first-pass evaluation

The evaluator receives the claim, its date, the semantic context needed to interpret it, and the
evidence. It does not receive the speaker, the party, the government/opposition status, or the
publication.

This is enforced by the type system rather than by discipline. `RedactedClaimContext` is a frozen
model with `extra='forbid'` and no identity field; `evaluate_blind()` accepts that type and
nothing else. Redaction replaces names and organisations with neutral placeholders that preserve
grammatical sense, and `assert_no_identity_leak()` raises if a known identity survives into the
redacted text or the evidence excerpts.

Over-redaction is treated as a bug, not as safety: a claim stripped until it is uninterpretable
cannot be evaluated either. The boundary is tested explicitly.

**Stage two** restores provenance to analyse framing, historical consistency and rhetorical
pattern. It takes the blind result as frozen input and cannot alter the verdict — a guard raises
if it tries. This is what keeps prestige and political identity out of the factual layer while
still allowing discourse analysis on top of it.

Actor profiles also live only in this second stage. Roles and affiliations are recorded as sourced
facts; declared interests require an official declaration; legal entries require a primary
official record, explicit procedural status, and a presumption-of-innocence note while unresolved.
The interface places this material behind a strong attributed-stage divider so it cannot be read
as an explanation for a verdict.

The profile's claim track record is not a reputation score. It is a count of Aleph's own blind
verdicts, includes every underlying claim id and sample size, and always carries the warning that
the sample is small, non-random, and non-predictive.

There is one deliberate escape hatch: when the speaker's identity genuinely *is* the fact at issue
("did X say Y?"), identity must be requested explicitly. It is never restored by default.

---

## 4. Source authority is not evidential relevance

The most common failure in automated fact-checking is treating institutional standing as truth.
Aleph separates the two, and implements the separation as a capability matrix rather than a
disclaimer.

| Source | Decisive for | Does **not** establish |
|---|---|---|
| Primary document | what the current text says | whether its projections will hold |
| Budget/technical report | what that body estimates | that the estimate will occur |
| Statistical dataset | what was measured | why it happened |
| Peer-reviewed study | what the study found | that it generalises to this case |
| Journalism | that something was reported | that it is true |
| Political statement | what an actor claimed | whether the claim is correct |

An opposition figure can be factually right. A minister can be factually wrong. A CEO can be
correct about social policy and a union representative correct about firms. The ranking function
in `aleph/evidence/rank.py` has no per-institution or per-outlet weight to tune — relevance is
scored against the specific question being asked.

---

## 5. Independence, not volume

Ten outlets running the same wire story is one piece of evidence, not ten. Aleph detects this
before counting corroboration, using near-duplicate detection over normalised text, shared-quotation
overlap, wire attribution parsing, and publication-time cascade analysis (who published first, who
followed within minutes).

Every cluster therefore reports how many genuinely *distinct original sources* sit behind N
articles, with the syndication chains attached as evidence. Corroboration counts only independent
sources.

---

## 6. Confidence follows evidence

High model confidence means nothing on its own, so Aleph reports two numbers and makes the
evidence one prominent.

**Evidence confidence** is derived from: primary-source coverage, agreement among sources,
temporal consistency, quantitative validation, source independence, retrieval completeness, and
claim ambiguity. Each contributing factor is recorded with whether it raised or lowered the
result, plus a plain-language `limiting_factor` naming the single biggest reason confidence is not
higher.

**Model confidence** is recorded as a diagnostic. It is never the headline figure.

---

## 7. Describing effects without a political axis

Aleph does not reduce a document to left-versus-right. That collapse smuggles in the very
assumptions the product exists to expose.

Instead, effects are placed on **seven named axes**, each scored −100..+100 between two *named
poles*:

- households / social rights ↔ firms / capital / investment
- redistribution ↔ growth and incentive orientation
- public provision ↔ private provision
- worker protection ↔ labour flexibility
- environmental protection ↔ project acceleration
- central government ↔ local and municipal autonomy
- current consumption and relief ↔ long-term investment

A score of +32 on the first axis does **not** mean "right wing". It means the identified,
enumerated benefits and costs fall on that side by that margin — and every one of those
contributions is listed. Axis scores are meaningless without their components, so the model layer
raises rather than emit one that has none.

The **beneficiary** and **cost-bearer** maps are separate, and for each affected group record
direction, magnitude, evidence quality, time horizon, whether the effect is direct or requires a
causal chain (and if so, what that chain is), plus the supporting evidence and the remaining
uncertainties. Where evidence is thin the answer is `uncertain` with low evidence quality — not a
guess.

---

## 8. Framing, measured in eight dimensions

Each article gets a framing profile across eight dimensions, never collapsed into one "bias = 73".

| Dimension | Polarity |
|---|---|
| Selection asymmetry | lower is better |
| Loaded / emotional language | lower is better |
| Context omission | lower is better |
| Certainty inflation | lower is better |
| Unsupported causal language | lower is better |
| Opinion presented as fact | lower is better |
| Source diversity | higher is better |
| Primary-source grounding | higher is better |

Two of these deserve a note. **Certainty inflation** is computed by comparing the article's
modality against the modality of the underlying evidence — the source says "estimates", the
article says "will". **Context omission** is computed against the article's cluster and the
primary document, not in isolation: an omission only means something relative to what was
available to report.

Each dimension returns the sentences, terms and counts that produced it. The interface colours
these by *magnitude only* and states the polarity in words, so the visual layer never implies a
judgement the analysis did not make.

The goal is not to sort outlets into acceptable and unacceptable. It is to show how different
sources select and frame the same reality.

---

## 9. The neutrality suite — and what it does not prove

Before publication, evaluations are re-run under six substitutions that *should not matter*:

`speaker_swap` · `source_swap` · `party_swap` · `authority_removal` · `claim_paraphrase` ·
`evidence_order_shuffle`

Paraphrases are guarded to preserve truth conditions — numbers and negation cannot change.
Authority removal is the most important of the six: the same proposition and the same evidence,
with and without an institutional identity attached, should not move the factual judgement. If it
does, prestige is leaking into the verdict.

Tracked: `verdict_flip_rate`, `confidence_delta`, `framing_delta`, `explanation_semantic_delta`,
aggregated into a neutrality health figure. If the flip rate exceeds a configured threshold the
analysis is flagged **not publishable**.

**This measures invariance under irrelevant substitution. It is not proof of political
neutrality**, and the schema requires an `interpretation_caveat` to travel with the number so it
is never displayed as if it were. A system can be perfectly invariant and still be wrong in a
consistent direction — for instance through what it retrieves, or through what the underlying
model absorbed in training. The suite cannot see either.

---

## 10. Known limitations

- **Retrieval bounds everything.** Aleph can only weigh evidence it found. Retrieval breadth is
  the dominant source of error and is not something the neutrality suite can detect.
- **Model priors are invisible to us.** Blindness removes speaker identity from the input; it does
  not remove whatever the underlying model already associates with the *topic*.
- **Extraction is imperfect.** Complex tables, scanned pages and unusual layouts degrade parsing.
  Aleph flags scanned documents rather than silently returning empty text, and records
  `extraction_warnings` — a missing field is reported, not guessed.
- **Forecasts are not resolved, only conditioned.** Aleph lists the assumptions a prediction
  requires. It does not adjudicate whether they will hold.
- **Coarse magnitudes are deliberate.** Effect sizes are small/medium/large rather than precise
  figures, because false precision would overstate what the evidence supports.
- **The bundled sample data is synthetic** and describes no real statement by any real person or
  outlet.

---

## 11. How to check Aleph's work

Every claim view exposes the evidence used, the passages involved, the checks applied and their
outcomes, the assumptions required, the counter-evidence, and the uncertainty. Every score opens
into its components. Every proposition links to the verbatim passage it came from.

If something cannot be traced that way, treat it as a bug and open an issue.
