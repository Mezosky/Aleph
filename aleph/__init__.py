"""Aleph — evidence analysis for public-policy documents.

Aleph reads a policy document, extracts what it actually says, goes looking for
what the world has said about it, and then evaluates the resulting factual claims
against evidence — with the speaker's identity structurally withheld from the
evaluation.

The product exists because the failure mode of automated fact-checking is not
being wrong; it is being confidently wrong in a direction. Three commitments are
built into the data contract rather than left to good intentions:

1. **Speaker-blind factual evaluation.** The verdict path receives a
   :class:`~aleph.core.models.RedactedClaimContext`, which has no field for a
   speaker, party, coalition or outlet, and cannot be given one.
2. **No single left-right axis.** Framing is eight named dimensions, policy
   effect is seven named axes, and neither may be collapsed into a scalar.
3. **Every score is inspectable, and refusal is allowed.** No metric exists
   without the components that produced it, and an evidence base too thin to
   support verdicts is published as such rather than papered over with model
   confidence.

Aleph is document-agnostic. No jurisdiction, institution or named document
appears anywhere in this package; those live in registry and data files.

Import surface: :mod:`aleph.core` holds the shared contract — enums, ids, models,
errors and configuration — that every other subpackage depends on. This module
itself imports nothing at package-import time, so ``import aleph`` is cheap and
free of side effects, and in particular performs no network access.
"""

from __future__ import annotations

__all__ = ["__version__", "SCHEMA_VERSION"]

#: Version of the Aleph implementation.
__version__ = "0.1.0"

#: Version of the published Aleph data contract (the JSON Schemas in /schemas).
#: Bumped independently of :data:`__version__`: an implementation change that
#: leaves the contract intact must not invalidate consumers' parsers.
SCHEMA_VERSION = "1.0.0"
