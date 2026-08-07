"""Stable, human-readable identifiers for every object Aleph publishes.

Identity is an epistemic problem here, not a bookkeeping one. Aleph's output is
meant to be re-derived: the same document analysed again next month should
produce a bundle that can be *diffed* against the last one, so that a reader can
see what changed in the world rather than what changed in the pipeline's random
number generator. If ids were UUIDs minted at run time, every re-run would look
like a complete rewrite, real changes would be invisible inside the noise, and
no external citation of a provision or a claim could survive a refresh.

So every id here is a pure function of its inputs. ``make_id("prov", slug, 3)``
returns the same string on every machine, in every process, forever. Nothing in
this module reads a clock, a counter, a hostname or an environment variable.

Ids are also readable on purpose. ``prov:water-levy-2026:14`` tells a reader
which document and which provision without a lookup, which matters when the id
appears in an evidence reference inside a verdict a person is trying to check.
The prefix vocabulary is closed and pinned by ``schemas/common.json``:

    doc, prov, prop, clm, ev, art, cluster, contra, actor, node, edge, src,
    axis, job

``framing:`` is handled separately by :func:`framing_profile_id` because
``framing_profile.json`` gives it its own pattern rather than reusing the shared
one.

Slugification is deliberately lossy but deterministic: accents are folded, case
is dropped, and anything outside ``[a-z0-9._-]`` becomes a hyphen. A part that
slugifies to nothing raises rather than silently disappearing, because an id
that quietly loses a component would collide with a different object.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "ID_PATTERN",
    "ID_PREFIXES",
    "ID_MIN_LENGTH",
    "ID_MAX_LENGTH",
    "FRAMING_ID_PATTERN",
    "SLUG_PATTERN",
    "InvalidIdError",
    "slugify",
    "is_valid_slug",
    "is_valid_id",
    "validate_id",
    "id_prefix",
    "id_parts",
    "make_id",
    "stable_hash",
    "document_id",
    "provision_id",
    "proposition_id",
    "claim_id",
    "evidence_id",
    "article_id",
    "cluster_id",
    "contradiction_id",
    "node_id",
    "edge_id",
    "actor_id",
    "source_id",
    "axis_id",
    "job_id",
    "framing_profile_id",
]


# The shared identifier grammar, copied character for character from
# schemas/common.json#/$defs/id. Changing it is a breaking data-contract change.
ID_PATTERN = (
    r"^(doc|prov|prop|clm|ev|art|cluster|contra|actor|node|edge|src|axis|job):[A-Za-z0-9._:-]+$"
)
ID_MIN_LENGTH = 3
ID_MAX_LENGTH = 200

#: The closed set of id prefixes. Anything else is a bug, not an extension point.
ID_PREFIXES: frozenset[str] = frozenset(
    {
        "doc",
        "prov",
        "prop",
        "clm",
        "ev",
        "art",
        "cluster",
        "contra",
        "actor",
        "node",
        "edge",
        "src",
        "axis",
        "job",
    }
)

#: Framing profiles carry their own prefix, pinned by framing_profile.json.
FRAMING_ID_PATTERN = r"^framing:[A-Za-z0-9._:-]+$"

#: Document slugs, pinned by document.json#/$defs/identity/slug.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"

_ID_RE = re.compile(ID_PATTERN)
_FRAMING_ID_RE = re.compile(FRAMING_ID_PATTERN)
_SLUG_RE = re.compile(SLUG_PATTERN)

# Characters kept verbatim by slugify. ':' is excluded on purpose: it is the id
# separator, so allowing it inside a part would let one part masquerade as two.
_SLUG_KEEP_RE = re.compile(r"[^a-z0-9._-]+")
_SLUG_COLLAPSE_RE = re.compile(r"-{2,}")


class InvalidIdError(ValueError):
    """Raised when an identifier does not satisfy the published id grammar.

    A ``ValueError`` rather than an ``AlephError`` because a malformed id is a
    programming error in the caller, not a condition of the data being analysed.
    """


def slugify(value: object, *, max_length: int = 80) -> str:
    """Fold an arbitrary label into a deterministic, id-safe token.

    Unicode is normalised to NFKD and combining marks are dropped, so that
    ``"Presupuesto Público"`` and ``"Presupuesto Publico"`` produce the same
    token: two spellings of one name must not become two objects.

    Args:
        value: Anything with a ``str()``. Integers pass through as their digits.
        max_length: Hard cap, applied after normalisation, so one very long
            heading cannot push an id past the schema's 200-character limit.

    Returns:
        A lowercase token drawn from ``[a-z0-9._-]``.

    Raises:
        InvalidIdError: If the input contains nothing that survives folding. An
            empty part is refused rather than dropped, because dropping it would
            silently merge two distinct objects into one id.
    """
    text = str(value)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = stripped.lower()
    hyphenated = _SLUG_KEEP_RE.sub("-", lowered)
    collapsed = _SLUG_COLLAPSE_RE.sub("-", hyphenated)
    trimmed = collapsed.strip("-._")[:max_length].strip("-._")
    if not trimmed:
        raise InvalidIdError(
            f"cannot slugify {text!r}: nothing survives normalisation, and an "
            "empty id part would silently collide with a different object"
        )
    return trimmed


def is_valid_id(value: str) -> bool:
    """Return whether ``value`` satisfies the shared id grammar and length bounds."""
    return (
        isinstance(value, str)
        and ID_MIN_LENGTH <= len(value) <= ID_MAX_LENGTH
        and _ID_RE.match(value) is not None
    )


def validate_id(value: str, *, expected_prefix: str | None = None) -> str:
    """Return ``value`` unchanged if it is a well-formed id, else raise.

    Args:
        value: The identifier to check.
        expected_prefix: When given, also require the id to carry this prefix.
            Used at package boundaries where a wrong-typed id (an ``art:`` where
            an ``ev:`` was meant) would otherwise produce a dangling reference
            that no schema check would catch.

    Raises:
        InvalidIdError: If the id is malformed or carries the wrong prefix.
    """
    if not is_valid_id(value):
        raise InvalidIdError(
            f"{value!r} is not a valid Aleph id; expected "
            f"'<prefix>:<part>[:<part>...]' with prefix in {sorted(ID_PREFIXES)} "
            f"and length {ID_MIN_LENGTH}-{ID_MAX_LENGTH}"
        )
    if expected_prefix is not None and id_prefix(value) != expected_prefix:
        raise InvalidIdError(
            f"{value!r} has prefix {id_prefix(value)!r} but {expected_prefix!r} was required"
        )
    return value


def id_prefix(value: str) -> str:
    """Return the prefix of an id (the text before the first colon).

    Raises:
        InvalidIdError: If ``value`` is not a well-formed id.
    """
    if not is_valid_id(value):
        raise InvalidIdError(f"{value!r} is not a valid Aleph id")
    return value.split(":", 1)[0]


def id_parts(value: str) -> tuple[str, ...]:
    """Return the parts of an id after its prefix, in order.

    ``id_parts("prov:water-levy:14") == ("water-levy", "14")``.

    Raises:
        InvalidIdError: If ``value`` is not a well-formed id.
    """
    if not is_valid_id(value):
        raise InvalidIdError(f"{value!r} is not a valid Aleph id")
    return tuple(value.split(":")[1:])


def make_id(prefix: str, *parts: object) -> str:
    """Build a stable identifier from a prefix and one or more parts.

    The same arguments always produce the same string; there is no counter, no
    clock and no randomness anywhere in the path. That is the whole point: two
    runs over the same document must produce a diffable bundle, and an id cited
    in a published verdict must still resolve after a refresh.

    Args:
        prefix: One of :data:`ID_PREFIXES`.
        *parts: Components to slugify and join with ``:``. Integers are common
            (sequence numbers) and pass through as digits.

    Returns:
        An id matching :data:`ID_PATTERN`.

    Raises:
        InvalidIdError: If the prefix is unknown, no parts were given, a part
            slugifies to nothing, or the assembled id breaks the grammar or the
            length bound.
    """
    if prefix not in ID_PREFIXES:
        raise InvalidIdError(
            f"unknown id prefix {prefix!r}; the vocabulary is closed and pinned by "
            f"schemas/common.json: {sorted(ID_PREFIXES)}"
        )
    if not parts:
        raise InvalidIdError(f"make_id({prefix!r}) needs at least one part")

    slugged = [slugify(part) for part in parts]
    candidate = f"{prefix}:" + ":".join(slugged)

    if len(candidate) > ID_MAX_LENGTH:
        # Truncating would risk a collision, so fold the overflowing tail into a
        # content hash instead: still deterministic, still unique, still short.
        head = ":".join(slugged[:-1])
        digest = stable_hash(prefix, *slugged, length=12)
        keep = ID_MAX_LENGTH - len(prefix) - len(head) - len(digest) - 3
        tail = slugged[-1][: max(keep, 1)].strip("-._") or "x"
        candidate = f"{prefix}:{head}:{tail}-{digest}" if head else f"{prefix}:{tail}-{digest}"

    return validate_id(candidate, expected_prefix=prefix)


def stable_hash(*parts: object, length: int = 16) -> str:
    """Return a deterministic hex digest of the given parts.

    SHA-256 over the parts joined by an ASCII unit separator, so that
    ``("ab", "c")`` and ``("a", "bc")`` cannot collide. Deliberately not
    :func:`hash`, which is salted per process and would make ids differ between
    runs of the same code on the same input.

    Used for content-addressing where a readable id is impossible: deduplicating
    near-identical evidence spans, keying a cache entry on a document's bytes,
    or absorbing the tail of an over-long identifier.

    Args:
        *parts: Values to fingerprint. Each is rendered with ``str()``.
        length: Number of hex characters to return, 1-64.

    Raises:
        ValueError: If ``length`` is outside 1-64.
    """
    if not 1 <= length <= 64:
        raise ValueError(f"length must be between 1 and 64 hex characters, got {length}")
    joined = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Typed constructors
#
# One per prefix, so that call sites read as intent ("this is a provision of
# that document") rather than as string assembly, and so the shape of each id
# family is defined in exactly one place.
# ---------------------------------------------------------------------------


def document_id(slug: object) -> str:
    """``doc:<slug>`` — the document everything else in a bundle traces back to."""
    return make_id("doc", slug)


def provision_id(document_slug: object, number: object) -> str:
    """``prov:<document-slug>:<number>`` — one operative unit of a document.

    The document slug is embedded rather than referenced so a provision id is
    self-describing in an evidence reference a reader is checking by hand.
    """
    return make_id("prov", document_slug, number)


def proposition_id(document_slug: object, number: object) -> str:
    """``prop:<document-slug>:<number>`` — one atomic statement a document makes."""
    return make_id("prop", document_slug, number)


def claim_id(number: object, *, scope: object | None = None) -> str:
    """``clm:<number>`` or ``clm:<scope>:<number>`` — one assertion under evaluation.

    ``scope`` is optional and exists for pipelines that evaluate several
    documents into one store; omit it for the single-document case the contract
    describes.
    """
    return make_id("clm", scope, number) if scope is not None else make_id("clm", number)


def evidence_id(number: object, *, scope: object | None = None) -> str:
    """``ev:<number>`` or ``ev:<scope>:<number>`` — one retrieved artefact or passage."""
    return make_id("ev", scope, number) if scope is not None else make_id("ev", number)


def article_id(outlet_slug: object, number: object) -> str:
    """``art:<outlet-slug>:<number>`` — one published item.

    The outlet slug is part of the id for traceability only. It carries no
    weight: outlet standing never influences a factual verdict anywhere in
    Aleph, and nothing downstream may branch on this component.
    """
    return make_id("art", outlet_slug, number)


def cluster_id(number: object, *, kind: object | None = None) -> str:
    """``cluster:<number>`` or ``cluster:<kind>:<number>`` — a group of coverage or claims."""
    return make_id("cluster", kind, number) if kind is not None else make_id("cluster", number)


def contradiction_id(number: object) -> str:
    """``contra:<number>`` — one dispute framed around a single question at issue."""
    return make_id("contra", number)


def node_id(slug: object, *, kind: object | None = None) -> str:
    """``node:<slug>`` or ``node:<kind>:<slug>`` — one entity in the topic graph.

    Where the node is a ``person_role``, the slug must name the ROLE and never a
    named individual; an id carrying a person's name would leak identity into
    every reference to that node.
    """
    return make_id("node", kind, slug) if kind is not None else make_id("node", slug)


def edge_id(source_node_id: str, kind: object, target_node_id: str) -> str:
    """``edge:<source-slug>:<kind>:<target-slug>`` — one asserted relation.

    Built from its endpoints so the same relation always gets the same id: an
    edge is a claim in miniature, and re-deriving the graph must not renumber
    every relation in it.

    Raises:
        InvalidIdError: If either endpoint is not a valid ``node:`` id.
    """
    source_tail = ".".join(id_parts(validate_id(source_node_id, expected_prefix="node")))
    target_tail = ".".join(id_parts(validate_id(target_node_id, expected_prefix="node")))
    return make_id("edge", source_tail, kind, target_tail)


def actor_id(slug: object) -> str:
    """``actor:<slug>`` — an actor referenced by attributed (stage-two) analysis only.

    Never reaches the blind evaluator: :class:`~aleph.core.models.RedactedClaimContext`
    has no field this could be written into.
    """
    return make_id("actor", slug)


def source_id(slug: object) -> str:
    """``src:<slug>`` — one entry in the source registry.

    Registering a source records that it exists and how to reach it. It is not a
    judgement about it: the registry carries no credibility, bias or prestige
    field anywhere.
    """
    return make_id("src", slug)


def axis_id(axis_key: object) -> str:
    """``axis:<key>`` — one of the seven fixed policy-effect axes.

    Axes describe where effects fall, not who supports them.
    """
    return make_id("axis", axis_key)


def job_id(*parts: object) -> str:
    """``job:<...>`` — an analysis run.

    Callers that need uniqueness across runs of the same input should pass a
    caller-supplied discriminator (a request id, a timestamp string). This
    function itself reads no clock, so a job id is reproducible when the caller
    wants it to be.
    """
    return make_id("job", *parts)


def framing_profile_id(article_identifier: str) -> str:
    """``framing:<article-tail>`` — the eight-dimension profile of one article.

    Framing profiles use their own prefix, pinned by ``framing_profile.json``
    rather than by the shared id grammar, so this is built and validated
    separately from :func:`make_id`. A profile is always about one published
    item: there is no outlet-level profile, because scoring an outlet rather
    than a text would be exactly the reputation shortcut Aleph refuses.

    Raises:
        InvalidIdError: If ``article_identifier`` is not a valid ``art:`` id, or
            if the assembled framing id breaks its own pattern.
    """
    tail = ".".join(id_parts(validate_id(article_identifier, expected_prefix="art")))
    candidate = f"framing:{slugify(tail)}"
    if not _FRAMING_ID_RE.match(candidate) or len(candidate) > ID_MAX_LENGTH:
        raise InvalidIdError(f"{candidate!r} is not a valid framing profile id")
    return candidate


def is_valid_slug(value: str) -> bool:
    """Return whether ``value`` is a well-formed document slug.

    Document slugs are stricter than id parts: they must start with an
    alphanumeric, because they also become path segments under
    ``frontend/public/data/`` and a leading dot or dash there is a footgun.
    """
    return isinstance(value, str) and _SLUG_RE.match(value) is not None
