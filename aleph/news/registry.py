"""The set of sources Aleph may look at, and nothing about how much to trust them.

Warm phase 5 (``evidence_collection``) begins by deciding where to look. That
decision is where most automated analysis quietly goes wrong: a system that
carries a per-outlet trust weight will, from then on, report *who published a
thing* as if it were *whether the thing is so*. Once that substitution is in the
pipeline it is invisible — the verdicts still look like verdicts.

So this registry is deliberately impoverished. It records what a source **is**:
what sort of body publishes it, in which jurisdiction and language, at which
address, under which crawl rules. It records nothing about merit. There is no
credibility score, no bias rating, no political-leaning field, no prestige
weight, and :data:`FORBIDDEN_FIELDS` makes that structural rather than
aspirational — a YAML file carrying any such key is *rejected*, loudly, at load
time, instead of having the key ignored. Ignoring it would let someone add one,
see no error, and reasonably conclude Aleph honours it.

Two fields do describe evidential structure, and neither is a ranking:

``evidence_tier``
    What KIND of artefact this source produces, and therefore what it can
    establish. A legislature settles what was formally recorded, not whether a
    projection holds. The capability consequences live in
    :mod:`aleph.evidence.rank`, keyed on the tier and on the question — never on
    the institution.

``typical_independence``
    Whether a source usually originates material or republishes it. It exists so
    ten outlets carrying one wire story count as one observation. It is a prior
    about the source, and :mod:`aleph.news.independence` overrides it per story
    with what the texts actually show.

Two further design points worth stating.

**Jurisdiction is a parameter, never a branch.** No function here — and no
function anywhere in ``aleph/`` — behaves differently because a jurisdiction code
has a particular value. Adding a country means adding a block to
``sources.yaml``. The ``XX`` template block in that file exists to keep that
claim testable.

**Not knowing an address is a publishable state.** An entry whose ``base_url`` is
``null`` becomes an :class:`UnresolvedSource`: retained, reported, never
retrieved from. Inventing a plausible URL would manufacture a source that
silently returns nothing while appearing to have been consulted, which is worse
than a declared gap. The same honesty governs ``verified``: it is an authoring
key that maps to ``last_verified_at``, and this module will not invent a
verification timestamp for a source nobody checked.

Nothing here touches the network. Loading a registry reads one local file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from aleph.core.enums import EvidenceTier, Independence, JurisdictionLevel, SourceKind
from aleph.core.errors import SchemaMismatchError
from aleph.core.ids import validate_id
from aleph.core.models import (
    Jurisdiction,
    RateLimit,
    SourceRegistry,
    SourceRegistryEntry,
)

__all__ = [
    "FORBIDDEN_FIELDS",
    "PACKAGED_REGISTRY_PATH",
    "SCHEMA_NAME",
    "RegistryProblem",
    "RegistryValidationReport",
    "SourceFilter",
    "SourceRegistryStore",
    "UnresolvedSource",
    "add_source",
    "default_registry",
    "filter_sources",
    "get_source",
    "load_registry",
    "load_registry_from_mapping",
    "validate_registry",
]


#: The registry shipped with the package. ``aleph`` declares ``**/*.yaml`` as
#: package data, so this resolves in an installed wheel as well as in a checkout.
PACKAGED_REGISTRY_PATH: Final[Path] = Path(__file__).with_name("sources.yaml")

#: Name of the JSON Schema this file is validated against.
SCHEMA_NAME: Final[str] = "source_registry"

#: Keys that must never appear on a registry entry, in any spelling.
#:
#: ``source_registry.json`` already forbids unknown properties twice over — once
#: through ``additionalProperties: false`` and once through an explicit ``not``
#: clause — but a YAML file is edited by people, often without a validator to
#: hand. Refusing these here means the failure arrives at the moment someone
#: tries to add a trust weight, with an explanation, rather than at some later
#: point where the key is silently absent from the parsed model and the author
#: assumes it is being honoured.
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "credibility",
        "credibility_score",
        "credibility_rating",
        "bias",
        "bias_score",
        "bias_rating",
        "leaning",
        "political_leaning",
        "political_alignment",
        "political_position",
        "left_right",
        "left_right_score",
        "reliability",
        "reliability_score",
        "trust",
        "trust_score",
        "trustworthiness",
        "prestige",
        "prestige_score",
        "authority",
        "authority_score",
        "quality_score",
        "rank",
        "ranking",
        "weight",
        "score",
    }
)

#: Authoring-only keys understood by this loader and translated before the entry
#: reaches the pydantic model. They are not part of the published contract.
_AUTHORING_KEYS: Final[frozenset[str]] = frozenset({"verified"})

_JURISDICTION_KEYS: Final[frozenset[str]] = frozenset({"code", "name", "level"})


# ---------------------------------------------------------------------------
# Problem reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegistryProblem:
    """One thing wrong with, or worth knowing about, a registry file.

    Problems are data rather than exceptions because CI wants the whole list at
    once. A loader that raised on the first bad entry would make fixing a
    twenty-entry file a twenty-round trip.
    """

    severity: str
    """``'error'`` blocks use of the registry; ``'warning'`` does not."""
    entry_id: str | None
    message: str
    pointer: str | None = None
    """JSON-Pointer-ish path into the source file, for editor tooling."""

    def __str__(self) -> str:
        where = self.entry_id or self.pointer or "<registry>"
        return f"[{self.severity}] {where}: {self.message}"


@dataclass(frozen=True, slots=True)
class UnresolvedSource:
    """A source that is known to exist but whose address is not known.

    Kept rather than dropped. A dropped entry is indistinguishable from a source
    nobody thought of, whereas an unresolved one is an actionable gap: the body
    is relevant, and somebody must go and find its address. It is never
    retrievable — :meth:`SourceRegistryStore.retrievable` excludes it — so no
    fetch can be attempted against a URL that was never established.
    """

    id: str
    name: str
    kind: SourceKind | None
    jurisdiction_code: str | None
    reason: str
    """Why the entry could not be resolved, in terms someone can act on."""


@dataclass(frozen=True, slots=True)
class RegistryValidationReport:
    """The outcome of checking a registry file. Safe to render in CI output.

    ``ok`` is false when any problem has severity ``error``. Warnings are
    deliberately not fatal: an unresolved address or an unverified entry is the
    *expected* state of a freshly authored registry, and failing a build for it
    would push authors towards inventing URLs to make the build pass.
    """

    path: Path | None
    ok: bool
    problems: tuple[RegistryProblem, ...] = ()
    entry_count: int = 0
    unresolved: tuple[UnresolvedSource, ...] = ()
    unverified_ids: tuple[str, ...] = ()
    json_schema_checked: bool = False
    """False when ``jsonschema`` or the schema directory was unavailable. The
    pydantic models mirror the contract, so a pydantic-only check is meaningful —
    but it is not the same check, and pretending otherwise would overstate it."""

    @property
    def errors(self) -> tuple[RegistryProblem, ...]:
        return tuple(p for p in self.problems if p.severity == "error")

    @property
    def warnings(self) -> tuple[RegistryProblem, ...]:
        return tuple(p for p in self.problems if p.severity == "warning")

    def render(self) -> str:
        """Format as a human-readable block for a CI log."""
        head = (
            f"source registry {'OK' if self.ok else 'INVALID'}: "
            f"{self.entry_count} entries, {len(self.errors)} errors, "
            f"{len(self.warnings)} warnings"
            f"{'' if self.json_schema_checked else ' (JSON Schema check skipped)'}"
        )
        lines = [head, f"  file: {self.path}" if self.path else "  file: <in-memory>"]
        lines.extend(f"  {p}" for p in self.problems)
        if self.unresolved:
            lines.append("  unresolved addresses (never retrieved from):")
            lines.extend(f"    {u.id} — {u.reason}" for u in self.unresolved)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFilter:
    """A declarative selection over the registry.

    Every criterion asks a structural question — where does this source operate,
    what sort of body is it, in what language does it publish, what class of
    artefact does it produce. There is deliberately no criterion that could be
    used to select sources by standing, and none that could be used to exclude a
    viewpoint: ``enabled`` is an operational flag (broken feed, out of scope,
    template) and its use to drop a position rather than a malfunction would be a
    misuse this type cannot prevent but this docstring can name.

    ``None`` means "do not constrain on this axis". A collection means "any of".
    """

    jurisdiction: str | Iterable[str] | None = None
    """Matched case-insensitively against ``jurisdiction.code``."""
    jurisdiction_level: JurisdictionLevel | Iterable[JurisdictionLevel] | None = None
    kind: SourceKind | Iterable[SourceKind] | None = None
    language: str | Iterable[str] | None = None
    """BCP-47. A bare primary subtag matches its regional variants, so ``'es'``
    selects ``es-CL`` and ``es-ES``; ``'es-CL'`` selects only that variant."""
    evidence_tier: EvidenceTier | Iterable[EvidenceTier] | None = None
    typical_independence: Independence | Iterable[Independence] | None = None
    topic: str | Iterable[str] | None = None
    enabled: bool | None = None
    verified: bool | None = None
    retrievable: bool | None = None
    """True selects entries that are enabled, have an address, and are permitted
    to be crawled as far as the recorded robots policy says. An unchecked robots
    policy counts as *not* permitted."""

    def matches(self, entry: SourceRegistryEntry, *, verified: bool = False) -> bool:
        """Return whether ``entry`` satisfies every stated criterion."""
        if self.jurisdiction is not None:
            wanted = {v.casefold() for v in _as_set(self.jurisdiction)}
            code = (entry.jurisdiction.code or "").casefold()
            if code not in wanted:
                return False
        if self.jurisdiction_level is not None and entry.jurisdiction.level not in _as_set(
            self.jurisdiction_level
        ):
            return False
        if self.kind is not None and entry.kind not in _as_set(self.kind):
            return False
        if self.language is not None and not _language_matches(
            entry.language, entry.additional_languages, _as_set(self.language)
        ):
            return False
        if self.evidence_tier is not None and entry.evidence_tier not in _as_set(
            self.evidence_tier
        ):
            return False
        if self.typical_independence is not None and entry.typical_independence not in _as_set(
            self.typical_independence
        ):
            return False
        if self.topic is not None:
            wanted_topics = {t.casefold() for t in _as_set(self.topic)}
            if not wanted_topics & {t.casefold() for t in entry.topics}:
                return False
        if self.enabled is not None and entry.enabled is not self.enabled:
            return False
        if self.verified is not None and verified is not self.verified:
            return False
        if self.retrievable is not None and _is_retrievable(entry) is not self.retrievable:
            return False
        return True


def _as_set(value: Any) -> set[Any]:
    """Normalise a scalar-or-iterable criterion into a set."""
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        return {value}
    return set(value)


def _language_matches(primary: str, additional: Sequence[str], wanted: set[Any]) -> bool:
    """Match BCP-47 tags, letting a primary subtag stand for its variants.

    Retrieval routinely needs "anything in Spanish" without enumerating every
    regional tag; it equally needs to distinguish ``es-CL`` from ``es-ES`` when
    detecting a translated syndication. Both must be expressible, so the rule is:
    a bare subtag matches its variants, a full tag matches only itself.
    """
    have = {tag.casefold() for tag in (primary, *additional) if tag}
    for want in wanted:
        needle = str(want).casefold()
        if needle in have:
            return True
        if "-" not in needle and any(tag.split("-", 1)[0] == needle for tag in have):
            return True
    return False


def _is_retrievable(entry: SourceRegistryEntry) -> bool:
    """Whether a fetcher may currently attempt this source.

    Deliberately conservative on robots: ``crawl_allowed=None`` means nobody has
    checked, and unchecked is not permitted. Treating unknown as allowed would
    make the default behaviour "crawl until told to stop", which is not how a
    public-interest tool should approach someone else's server.
    """
    if not entry.enabled or not entry.base_url:
        return False
    policy = entry.robots_policy
    if policy is None:
        return False
    if policy.respect_robots and policy.crawl_allowed is not True:
        return False
    return True


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SourceRegistryStore:
    """An in-memory registry with add / get / filter and deterministic order.

    Iteration is sorted by id rather than by insertion, so two runs that assemble
    the same sources in different orders produce the same retrieval plan and the
    same diffable bundle. Nothing here reads a clock or the network.
    """

    _entries: dict[str, SourceRegistryEntry] = field(default_factory=dict)
    _verified: dict[str, bool] = field(default_factory=dict)
    unresolved: tuple[UnresolvedSource, ...] = ()
    schema_version: str | None = None
    registry_version: str | None = None
    default_rate_limit: RateLimit | None = None
    notes: str | None = None
    source_path: Path | None = None

    # -- construction -------------------------------------------------------

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[SourceRegistryEntry],
        *,
        verified: Mapping[str, bool] | None = None,
        **kwargs: Any,
    ) -> SourceRegistryStore:
        """Build a store from already-validated entries."""
        store = cls(**kwargs)
        for entry in entries:
            store.add(entry, verified=bool((verified or {}).get(entry.id, False)))
        return store

    # -- mutation -----------------------------------------------------------

    def add(
        self,
        entry: SourceRegistryEntry,
        *,
        verified: bool = False,
        replace: bool = False,
    ) -> SourceRegistryEntry:
        """Register a source.

        Args:
            entry: The validated entry. Its id must carry the ``src:`` prefix.
            verified: Whether the entry's addresses have been confirmed against
                the live web. Defaults to False, which is the only honest default
                for something this process has not checked.
            replace: Permit overwriting an existing id.

        Raises:
            KeyError: If the id is already present and ``replace`` is False.
                Silent overwrite is refused because two entries sharing an id are
                a data error someone must see, not a merge to perform quietly.
        """
        validate_id(entry.id, expected_prefix="src")
        if entry.id in self._entries and not replace:
            raise KeyError(
                f"source {entry.id!r} is already registered; pass replace=True to "
                "overwrite it deliberately"
            )
        self._entries[entry.id] = entry
        self._verified[entry.id] = verified
        return entry

    def remove(self, source_id: str) -> bool:
        """Drop a source. Returns whether it was present."""
        self._verified.pop(source_id, None)
        return self._entries.pop(source_id, None) is not None

    # -- access -------------------------------------------------------------

    def get(self, source_id: str) -> SourceRegistryEntry | None:
        """Return the entry, or ``None`` when it is not registered."""
        return self._entries.get(source_id)

    def require(self, source_id: str) -> SourceRegistryEntry:
        """Return the entry or raise :class:`KeyError` with the known ids listed."""
        entry = self._entries.get(source_id)
        if entry is None:
            raise KeyError(
                f"no source {source_id!r} in the registry; known ids: {sorted(self._entries)}"
            )
        return entry

    def is_verified(self, source_id: str) -> bool:
        """Whether this entry's addresses have been confirmed against the live web.

        Unknown ids answer False: the absence of a record of verification is not
        evidence of verification.
        """
        return self._verified.get(source_id, False)

    def __contains__(self, source_id: object) -> bool:
        return source_id in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[SourceRegistryEntry]:
        """Iterate entries in id order — stable across runs and machines."""
        for source_id in sorted(self._entries):
            yield self._entries[source_id]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    # -- selection ----------------------------------------------------------

    def filter(
        self,
        spec: SourceFilter | None = None,
        **criteria: Any,
    ) -> tuple[SourceRegistryEntry, ...]:
        """Select entries, in id order.

        Accepts either a prepared :class:`SourceFilter` or the same criteria as
        keyword arguments, so a caller can write
        ``registry.filter(jurisdiction="CL", kind=SourceKind.NEWS_OUTLET)``
        without constructing anything.

        Raises:
            TypeError: On an unknown criterion. A typo'd filter that silently
                matched everything would over-collect and then be reported as
                broad coverage.
        """
        if spec is not None and criteria:
            raise TypeError("pass either a SourceFilter or keyword criteria, not both")
        if spec is None:
            unknown = set(criteria) - {f.name for f in SourceFilter.__dataclass_fields__.values()}
            if unknown:
                raise TypeError(
                    f"unknown filter criteria {sorted(unknown)}; "
                    f"available: {sorted(SourceFilter.__dataclass_fields__)}"
                )
            spec = SourceFilter(**criteria)
        return tuple(
            entry for entry in self if spec.matches(entry, verified=self.is_verified(entry.id))
        )

    def retrievable(
        self, spec: SourceFilter | None = None, **criteria: Any
    ) -> tuple[SourceRegistryEntry, ...]:
        """Entries a fetcher may currently attempt, in id order.

        A convenience over :meth:`filter` that pins ``retrievable=True``. Note
        that this being empty is the *normal* state of a fresh registry: no
        robots policy has been checked, so nothing is permitted yet. That is the
        intended default, and the retrieval policy is opt-in by design.
        """
        entries = self.filter(spec, **criteria) if (spec or criteria) else tuple(self)
        return tuple(e for e in entries if _is_retrievable(e))

    # -- inventory ----------------------------------------------------------

    def jurisdictions(self) -> tuple[str, ...]:
        """Distinct jurisdiction codes present, sorted."""
        return tuple(sorted({e.jurisdiction.code for e in self if e.jurisdiction.code}))

    def kinds(self) -> tuple[SourceKind, ...]:
        return tuple(sorted({e.kind for e in self}, key=lambda k: k.value))

    def tiers(self) -> tuple[EvidenceTier, ...]:
        return tuple(sorted({e.evidence_tier for e in self}, key=lambda t: t.value))

    def languages(self) -> tuple[str, ...]:
        langs: set[str] = set()
        for entry in self:
            langs.add(entry.language)
            langs.update(entry.additional_languages)
        return tuple(sorted(langs))

    def coverage_summary(self) -> dict[str, Any]:
        """A JSON-safe inventory of what the registry can and cannot reach.

        Written for the readiness phase and the methodology page. The interesting
        numbers are the negative ones: how many entries have no address, how many
        have never been verified, how many are currently retrievable. A registry
        that looks broad but is entirely unverified should read as thin, and this
        is what lets it.
        """
        by_tier: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        by_jurisdiction: dict[str, int] = {}
        for entry in self:
            by_tier[entry.evidence_tier.value] = by_tier.get(entry.evidence_tier.value, 0) + 1
            by_kind[entry.kind.value] = by_kind.get(entry.kind.value, 0) + 1
            code = entry.jurisdiction.code or "unknown"
            by_jurisdiction[code] = by_jurisdiction.get(code, 0) + 1
        return {
            "total": len(self),
            "enabled": sum(1 for e in self if e.enabled),
            "verified": sum(1 for e in self if self.is_verified(e.id)),
            "retrievable_now": len(self.retrievable()),
            "with_feeds": sum(1 for e in self if e.feeds),
            "unresolved_addresses": len(self.unresolved),
            "by_tier": dict(sorted(by_tier.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "by_jurisdiction": dict(sorted(by_jurisdiction.items())),
        }

    # -- export -------------------------------------------------------------

    def to_model(self) -> SourceRegistry:
        """Render as the contract object, entries in id order."""
        return SourceRegistry(
            schema_version=self.schema_version,
            registry_version=self.registry_version,
            default_rate_limit=self.default_rate_limit,
            sources=list(self),
            notes=self.notes,
        )

    def to_jsonable(self) -> dict[str, Any]:
        """Render as a mapping that validates against ``source_registry.json``."""
        return self.to_model().to_jsonable()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_registry(path: str | Path | None = None) -> SourceRegistryStore:
    """Read, validate and return a registry.

    Args:
        path: The YAML file. Defaults to :data:`PACKAGED_REGISTRY_PATH`, the
            registry shipped with the package.

    Raises:
        FileNotFoundError: If the file does not exist.
        SchemaMismatchError: If the file is malformed, carries a forbidden trust
            field, or produces entries that do not satisfy the contract. Every
            problem found is listed in the message rather than only the first.
    """
    resolved = Path(path) if path is not None else PACKAGED_REGISTRY_PATH
    if not resolved.is_file():
        raise FileNotFoundError(f"source registry not found at {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SchemaMismatchError(
            "source registry must be a YAML mapping at the top level",
            schema_name=SCHEMA_NAME,
            pointer="/",
            actual=type(raw).__name__,
        )
    store, problems = _build_store(raw, source_path=resolved)
    errors = [p for p in problems if p.severity == "error"]
    if errors:
        detail = "; ".join(str(p) for p in errors)
        raise SchemaMismatchError(
            f"source registry at {resolved} is invalid: {detail}",
            schema_name=SCHEMA_NAME,
            pointer="/sources",
        )
    return store


def load_registry_from_mapping(
    data: Mapping[str, Any], *, source_path: Path | None = None
) -> SourceRegistryStore:
    """Build a registry from an already-parsed mapping.

    Used by tests and by callers that hold registry data from somewhere other
    than a file. Applies exactly the same checks as :func:`load_registry`.
    """
    store, problems = _build_store(dict(data), source_path=source_path)
    errors = [p for p in problems if p.severity == "error"]
    if errors:
        raise SchemaMismatchError(
            "source registry mapping is invalid: " + "; ".join(str(p) for p in errors),
            schema_name=SCHEMA_NAME,
        )
    return store


@lru_cache(maxsize=4)
def _cached_registry(path_str: str) -> SourceRegistryStore:
    return load_registry(Path(path_str))


def default_registry(path: str | Path | None = None) -> SourceRegistryStore:
    """Return the packaged registry, parsed once and cached.

    The cache is keyed on the path, and the returned store is mutable, so a
    caller that intends to modify a registry should use :func:`load_registry`
    instead and keep its own copy.
    """
    resolved = Path(path) if path is not None else PACKAGED_REGISTRY_PATH
    return _cached_registry(str(resolved))


def get_source(
    source_id: str, *, registry: SourceRegistryStore | None = None
) -> SourceRegistryEntry | None:
    """Look one source up in the packaged registry (or a supplied one)."""
    return (registry or default_registry()).get(source_id)


def filter_sources(
    spec: SourceFilter | None = None,
    *,
    registry: SourceRegistryStore | None = None,
    **criteria: Any,
) -> tuple[SourceRegistryEntry, ...]:
    """Select from the packaged registry (or a supplied one), in id order."""
    return (registry or default_registry()).filter(spec, **criteria)


def add_source(
    registry: SourceRegistryStore,
    entry: SourceRegistryEntry | Mapping[str, Any],
    *,
    verified: bool = False,
    replace: bool = False,
) -> SourceRegistryEntry:
    """Add a source to a registry, accepting either a model or a raw mapping.

    A raw mapping goes through the same forbidden-field and authoring-key
    handling as a file entry, so a source added at run time cannot smuggle in a
    trust weight that a file-loaded one could not.
    """
    if isinstance(entry, SourceRegistryEntry):
        return registry.add(entry, verified=verified, replace=replace)

    problems: list[RegistryProblem] = []
    built = _build_entry(dict(entry), index=len(registry), problems=problems)
    errors = [p for p in problems if p.severity == "error"]
    if errors or built is None:
        raise SchemaMismatchError(
            "source entry is invalid: " + "; ".join(str(p) for p in errors),
            schema_name=SCHEMA_NAME,
        )
    model, entry_verified = built
    return registry.add(model, verified=verified or entry_verified, replace=replace)


# ---------------------------------------------------------------------------
# Validation (the function CI calls)
# ---------------------------------------------------------------------------


def validate_registry(
    path: str | Path | None = None,
    *,
    check_json_schema: bool = True,
    schema_dir: str | Path | None = None,
) -> RegistryValidationReport:
    """Check a registry file and return every problem found.

    Unlike :func:`load_registry` this never raises for bad data: CI wants the
    complete list, and an exception carrying only the first failure turns fixing
    a file into a sequence of builds.

    The check runs on two levels. Pydantic validation always runs and mirrors the
    contract field for field. JSON Schema validation runs additionally when
    ``jsonschema`` and ``/schemas`` are both available — it is the authoritative
    contract check, and the report says plainly when it was skipped rather than
    letting a partial check pass for a full one.

    Args:
        path: Registry file. Defaults to the packaged one.
        check_json_schema: Whether to attempt the JSON Schema pass.
        schema_dir: Where the schemas live. Defaults to ``<repo>/schemas``
            discovered relative to this file.
    """
    resolved = Path(path) if path is not None else PACKAGED_REGISTRY_PATH
    problems: list[RegistryProblem] = []

    if not resolved.is_file():
        return RegistryValidationReport(
            path=resolved,
            ok=False,
            problems=(RegistryProblem("error", None, f"registry file not found at {resolved}"),),
        )

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return RegistryValidationReport(
            path=resolved,
            ok=False,
            problems=(RegistryProblem("error", None, f"YAML is not parseable: {exc}"),),
        )
    if not isinstance(raw, dict):
        return RegistryValidationReport(
            path=resolved,
            ok=False,
            problems=(RegistryProblem("error", None, "top level must be a mapping", pointer="/"),),
        )

    store, build_problems = _build_store(raw, source_path=resolved)
    problems.extend(build_problems)

    schema_checked = False
    if check_json_schema and not any(p.severity == "error" for p in problems):
        schema_checked, schema_problems = _json_schema_check(store, schema_dir=schema_dir)
        problems.extend(schema_problems)

    unverified = tuple(e.id for e in store if not store.is_verified(e.id))
    if unverified:
        problems.append(
            RegistryProblem(
                "warning",
                None,
                f"{len(unverified)} of {len(store)} entries are unverified; their URLs, "
                "feeds, robots policies and paywall states have not been confirmed "
                "against the live web. Run scripts/verify_sources.py deliberately — "
                "this is not something CI may do.",
            )
        )

    return RegistryValidationReport(
        path=resolved,
        ok=not any(p.severity == "error" for p in problems),
        problems=tuple(problems),
        entry_count=len(store),
        unresolved=store.unresolved,
        unverified_ids=unverified,
        json_schema_checked=schema_checked,
    )


def _json_schema_check(
    store: SourceRegistryStore, *, schema_dir: str | Path | None
) -> tuple[bool, list[RegistryProblem]]:
    """Validate the rendered registry against ``source_registry.json``.

    Returns ``(checked, problems)``. ``checked`` is False when the tooling or the
    schema directory is unavailable — reported honestly rather than treated as a
    pass, because "we could not check" and "we checked and it was fine" are
    different states and only one of them licenses confidence.
    """
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        return False, []

    directory = Path(schema_dir) if schema_dir is not None else _discover_schema_dir()
    if directory is None:
        return False, []
    main = directory / f"{SCHEMA_NAME}.json"
    if not main.is_file():
        return False, []

    resources: list[tuple[str, Any]] = []
    for schema_file in sorted(directory.glob("*.json")):
        try:
            contents = json.loads(schema_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        resource = Resource.from_contents(contents)
        # Register under the bare filename as well as the declared $id, because
        # the schemas cross-reference each other with relative paths.
        resources.append((schema_file.name, resource))
        declared = contents.get("$id")
        if isinstance(declared, str):
            resources.append((declared, resource))

    registry = Registry().with_resources(resources)
    schema = json.loads(main.read_text(encoding="utf-8"))
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema, registry=registry)

    problems: list[RegistryProblem] = []
    for error in sorted(validator.iter_errors(store.to_jsonable()), key=lambda e: list(e.path)):
        pointer = "/" + "/".join(str(p) for p in error.path)
        entry_id: str | None = None
        parts = list(error.path)
        if len(parts) >= 2 and parts[0] == "sources" and isinstance(parts[1], int):
            entry = store.to_model().sources[parts[1]]
            entry_id = entry.id
        problems.append(RegistryProblem("error", entry_id, error.message, pointer=pointer))
    return True, problems


def _discover_schema_dir() -> Path | None:
    """Find ``/schemas`` relative to this file, if the checkout is present.

    Returns ``None`` in an installed-wheel layout where the schemas were not
    shipped. That is a legitimate state: the schema check is a development and CI
    concern, not a runtime capability, which is why ``jsonschema`` is a dev
    dependency.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "schemas"
        if (candidate / f"{SCHEMA_NAME}.json").is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Parsing internals
# ---------------------------------------------------------------------------


def _build_store(
    raw: Mapping[str, Any], *, source_path: Path | None
) -> tuple[SourceRegistryStore, list[RegistryProblem]]:
    """Turn parsed YAML into a store plus a list of problems.

    Accepts both file shapes: the schema-native flat ``sources:`` list, and the
    authoring-friendly ``jurisdictions:`` mapping whose blocks carry a shared
    ``jurisdiction`` and ``defaults``. The second is flattened into the first, so
    the grouping is ergonomics rather than a competing data model.
    """
    problems: list[RegistryProblem] = []
    store = SourceRegistryStore(
        schema_version=_opt_str(raw.get("schema_version")),
        registry_version=_opt_str(raw.get("registry_version")),
        notes=_opt_str(raw.get("notes")),
        source_path=source_path,
    )

    default_limit = raw.get("default_rate_limit")
    if isinstance(default_limit, Mapping):
        try:
            store.default_rate_limit = RateLimit(**dict(default_limit))
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            problems.append(RegistryProblem("error", None, f"default_rate_limit: {exc}"))

    unresolved: list[UnresolvedSource] = []
    index = 0

    for entry_dict, pointer in _iter_raw_entries(raw, problems):
        index += 1
        entry_id = _opt_str(entry_dict.get("id")) or f"<entry {index}>"

        forbidden = sorted(FORBIDDEN_FIELDS & set(entry_dict))
        if forbidden:
            problems.append(
                RegistryProblem(
                    "error",
                    entry_id,
                    f"forbidden field(s) {forbidden}. The registry records what a source "
                    "IS, never how much to trust it: a per-outlet trust, bias, prestige or "
                    "ranking weight would let institutional standing substitute for "
                    "evidence and would turn every downstream verdict into a judgement "
                    "about who was speaking. If the intent was to describe the ARTEFACT "
                    "the source produces, use evidence_tier; if it was to describe whether "
                    "the source originates or republishes material, use "
                    "typical_independence.",
                    pointer=pointer,
                )
            )
            continue

        if entry_dict.get("base_url") in (None, ""):
            unresolved.append(
                UnresolvedSource(
                    id=entry_id,
                    name=_opt_str(entry_dict.get("name")) or entry_id,
                    kind=_coerce_enum(SourceKind, entry_dict.get("kind")),
                    jurisdiction_code=_jurisdiction_code(entry_dict),
                    reason=(
                        "base_url is null: the address is not known with confidence and was "
                        "deliberately not guessed. The entry is retained as an actionable "
                        "gap and is never retrieved from."
                    ),
                )
            )
            problems.append(
                RegistryProblem(
                    "warning",
                    entry_id,
                    "no base_url; recorded as an unresolved source and excluded from "
                    "retrieval until an address is verified",
                    pointer=pointer,
                )
            )
            continue

        built = _build_entry(entry_dict, index=index, problems=problems, pointer=pointer)
        if built is None:
            continue
        model, verified = built
        if model.id in store:
            problems.append(
                RegistryProblem(
                    "error",
                    model.id,
                    "duplicate id. Two entries sharing an id would silently shadow one "
                    "another and the shadowed source would never be searched.",
                    pointer=pointer,
                )
            )
            continue
        store.add(model, verified=verified)

    store.unresolved = tuple(unresolved)
    return store, problems


def _iter_raw_entries(
    raw: Mapping[str, Any], problems: list[RegistryProblem]
) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield ``(entry_mapping, pointer)`` for both supported file shapes."""
    flat = raw.get("sources")
    if isinstance(flat, list):
        for i, item in enumerate(flat):
            if isinstance(item, Mapping):
                yield dict(item), f"/sources/{i}"
            else:
                problems.append(
                    RegistryProblem(
                        "error", None, "entry is not a mapping", pointer=f"/sources/{i}"
                    )
                )

    blocks = raw.get("jurisdictions")
    if blocks is None:
        return
    if not isinstance(blocks, Mapping):
        problems.append(
            RegistryProblem(
                "error", None, "jurisdictions must be a mapping", pointer="/jurisdictions"
            )
        )
        return

    # Sorted so that two files differing only in key order load identically.
    for code in sorted(blocks):
        block = blocks[code]
        base = f"/jurisdictions/{code}"
        if not isinstance(block, Mapping):
            problems.append(
                RegistryProblem("error", None, "jurisdiction block must be a mapping", pointer=base)
            )
            continue
        jurisdiction = block.get("jurisdiction")
        if not isinstance(jurisdiction, Mapping):
            jurisdiction = {"code": code, "level": "unknown"}
        defaults = block.get("defaults")
        defaults = dict(defaults) if isinstance(defaults, Mapping) else {}
        entries = block.get("sources")
        if not isinstance(entries, list):
            problems.append(
                RegistryProblem(
                    "error", None, "jurisdiction block has no sources list", pointer=base
                )
            )
            continue
        for i, item in enumerate(entries):
            if not isinstance(item, Mapping):
                problems.append(
                    RegistryProblem(
                        "error", None, "entry is not a mapping", pointer=f"{base}/sources/{i}"
                    )
                )
                continue
            merged: dict[str, Any] = {**defaults, **dict(item)}
            merged.setdefault("jurisdiction", dict(jurisdiction))
            yield merged, f"{base}/sources/{i}"


def _build_entry(
    entry_dict: dict[str, Any],
    *,
    index: int,
    problems: list[RegistryProblem],
    pointer: str | None = None,
) -> tuple[SourceRegistryEntry, bool] | None:
    """Translate one raw entry into a model plus its verification flag.

    ``verified`` is an authoring convenience, not a contract field. It is
    translated here rather than carried through: ``verified: true`` without a
    ``last_verified_at`` is refused, because a verification with no date cannot
    be audited or expired, and a timestamp invented at load time would assert
    that this process performed a check it did not perform.
    """
    data = dict(entry_dict)
    entry_id = _opt_str(data.get("id")) or f"<entry {index}>"

    forbidden = sorted(FORBIDDEN_FIELDS & set(data))
    if forbidden:
        problems.append(
            RegistryProblem(
                "error", entry_id, f"forbidden trust/bias field(s) {forbidden}", pointer=pointer
            )
        )
        return None

    verified = bool(data.pop("verified", False))
    last_verified_at = data.get("last_verified_at")
    if verified and not last_verified_at:
        problems.append(
            RegistryProblem(
                "error",
                entry_id,
                "verified: true with no last_verified_at. A verification with no date "
                "cannot be audited or expired, and this loader will not invent one.",
                pointer=pointer,
            )
        )
        return None
    if not verified and last_verified_at:
        # A recorded check outranks a stale authoring flag.
        verified = True

    leftover_authoring = _AUTHORING_KEYS & set(data)
    for key in sorted(leftover_authoring):
        data.pop(key, None)

    jurisdiction = data.get("jurisdiction")
    if isinstance(jurisdiction, Mapping):
        juris_data = {k: v for k, v in jurisdiction.items() if k in _JURISDICTION_KEYS}
        juris_data.setdefault("level", "unknown")
        try:
            data["jurisdiction"] = Jurisdiction(**juris_data)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            problems.append(
                RegistryProblem("error", entry_id, f"jurisdiction: {exc}", pointer=pointer)
            )
            return None
    elif jurisdiction is None:
        data["jurisdiction"] = Jurisdiction(level=JurisdictionLevel.UNKNOWN)

    try:
        model = SourceRegistryEntry(**data)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        problems.append(RegistryProblem("error", entry_id, str(exc), pointer=pointer))
        return None

    try:
        validate_id(model.id, expected_prefix="src")
    except ValueError as exc:
        problems.append(RegistryProblem("error", entry_id, str(exc), pointer=pointer))
        return None

    if model.enabled and not model.feeds:
        problems.append(
            RegistryProblem(
                "warning",
                model.id,
                "no feeds declared. Polling a declared feed is both more complete and "
                "less intrusive than crawling; scripts/verify_sources.py discovers them.",
                pointer=pointer,
            )
        )
    return model, verified


def _jurisdiction_code(entry_dict: Mapping[str, Any]) -> str | None:
    juris = entry_dict.get("jurisdiction")
    if isinstance(juris, Mapping):
        return _opt_str(juris.get("code"))
    return None


def _coerce_enum(enum_cls: type[Any], value: Any) -> Any | None:
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return None


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _main() -> int:
    """``python -m aleph.news.registry`` — the CI entry point.

    Prints the full report and exits non-zero only on errors. Warnings (no feeds
    yet, nothing verified, an unresolved address) describe the honest state of a
    freshly authored registry and must not fail a build: making them fatal would
    pressure an author into inventing a URL to get green.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Validate an Aleph source registry.")
    parser.add_argument("path", nargs="?", default=None, help="registry YAML (default: packaged)")
    parser.add_argument(
        "--no-json-schema",
        action="store_true",
        help="skip the JSON Schema pass and check only the pydantic contract mirror",
    )
    args = parser.parse_args()

    report = validate_registry(args.path, check_json_schema=not args.no_json_schema)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())
