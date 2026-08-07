"""Where a document's effects fall, and which groups they reach.

⚠ **THE SEVEN AXES ARE NOT PARTY LABELS.** They describe the direction of
effects Aleph found *in a text*. They are not an ideological placement of the
document, its authors, its sponsors or anyone who supports it. A negative
``households_vs_firms`` value means the identified advantages accrue mainly to
households; it does **not** mean "left-wing", and a positive value does **not**
mean "right-wing". The same score is compatible with any political sponsorship,
and Aleph emits no left-right number anywhere — not here, not by summing these
seven, not by any other route.

Two modules:

* :mod:`aleph.impact.axes` places the document on the seven fixed axes. Every
  score is the sum of individually-listed, weighted components, each naming the
  provision that produced it and the rule that fired. No axis is ever a single
  model guess, and an axis asked to publish a non-zero score with nothing behind
  it raises instead.
* :mod:`aleph.impact.beneficiaries` builds the beneficiary and cost-bearer maps.
  The group vocabulary is OPEN: a starter list plus groups discovered from the
  topic graph and from the document's own declared affected populations, so an
  arbitrary document is never forced into fixed buckets. Direct effects (stated
  in a provision) are separated from indirect ones (requiring a causal chain),
  and every indirect effect carries its chain step by step so a reader can
  challenge a specific link rather than the conclusion as a whole.

Both modules refuse rather than guess. An effect Aleph cannot sign comes out as
``uncertain`` with ``insufficient`` evidence quality, which is a real result and
must be displayed as one.
"""

from __future__ import annotations

from aleph.impact.axes import (
    AXES_VERSION,
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisDerivation,
    AxisRule,
    ComponentDerivation,
    ImpactAxesResult,
    build_axes,
)
from aleph.impact.beneficiaries import (
    STARTER_GROUP_SIGNALS,
    BeneficiaryAnalysis,
    CausalChain,
    CausalStep,
    GroupFinding,
    GroupSignal,
    build_beneficiary_maps,
    discover_groups,
)

__all__ = [
    "AXES_VERSION",
    "AXIS_DEFINITIONS",
    "STARTER_GROUP_SIGNALS",
    "AxisDefinition",
    "AxisDerivation",
    "AxisRule",
    "BeneficiaryAnalysis",
    "CausalChain",
    "CausalStep",
    "ComponentDerivation",
    "GroupFinding",
    "GroupSignal",
    "ImpactAxesResult",
    "build_axes",
    "build_beneficiary_maps",
    "discover_groups",
]
