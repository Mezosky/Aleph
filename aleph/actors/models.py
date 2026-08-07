"""Validated model mirror of ``schemas/actor_profile.json``."""

from __future__ import annotations

from datetime import date as DateValue
from datetime import datetime as DateTimeValue
from typing import Annotated, Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator

from aleph.core.enums import DataStatus, EvidenceTier, Verdict


class ActorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class SourceRef(ActorModel):
    id: str
    title: str
    url: AnyUrl | None = None
    publisher: str | None = None
    published_at: DateValue | DateTimeValue | None = None
    tier: EvidenceTier
    independence: str | None = None
    language: str | None = None


class Role(ActorModel):
    title: str
    institution: str | None = None
    level: Literal[
        "national_executive",
        "national_legislative",
        "regional",
        "municipal",
        "judicial",
        "central_bank",
        "agency",
        "civil_society",
        "private_sector",
        "other",
    ]
    from_: DateValue | None = Field(None, alias="from")
    to: DateValue | None = None
    source: SourceRef


class Affiliation(ActorModel):
    organisation: str
    kind: Literal[
        "party",
        "coalition",
        "union",
        "business_association",
        "ngo",
        "professional_body",
        "other",
    ]
    from_: DateValue | None = Field(None, alias="from")
    to: DateValue | None = None
    source: SourceRef


class DeclaredInterest(ActorModel):
    kind: Literal[
        "asset",
        "shareholding",
        "directorship",
        "employment",
        "consultancy",
        "property",
        "debt",
        "family_interest",
        "other",
    ]
    description: str
    declared_on: DateValue | None = None
    relevance_to_document: Annotated[str, Field(min_length=1)]
    relevant_provision_ids: tuple[str, ...] = ()
    source: SourceRef

    @model_validator(mode="after")
    def _official_source_only(self) -> DeclaredInterest:
        allowed = {
            EvidenceTier.PRIMARY_DOCUMENT,
            EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
            EvidenceTier.LEGISLATIVE_RECORD,
            EvidenceTier.STATISTICAL_DATASET,
        }
        if EvidenceTier(self.source.tier) not in allowed:
            raise ValueError("declared interests require an official primary source")
        return self


RESOLVED_LEGAL_STATUSES = {
    "convicted",
    "acquitted",
    "dismissed",
    "case_closed",
    "sanction_overturned",
}


class LegalRecordEntry(ActorModel):
    summary: str
    status: Literal[
        "investigation_reported",
        "formally_investigated",
        "charged",
        "trial_ongoing",
        "convicted",
        "acquitted",
        "dismissed",
        "case_closed",
        "administrative_sanction",
        "sanction_overturned",
        "unknown",
    ]
    resolved: bool
    body: str
    date: DateValue | None = None
    presumption_note: str | None
    source: SourceRef
    additional_coverage: tuple[SourceRef, ...] = ()

    @model_validator(mode="after")
    def _legal_safeguards(self) -> LegalRecordEntry:
        expected_resolved = self.status in RESOLVED_LEGAL_STATUSES
        if self.resolved != expected_resolved:
            raise ValueError("resolved must agree with the legal status")
        if not self.source.url:
            raise ValueError("legal records require a link to the official record")
        if EvidenceTier(self.source.tier) not in {
            EvidenceTier.PRIMARY_DOCUMENT,
            EvidenceTier.LEGISLATIVE_RECORD,
            EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
        }:
            raise ValueError("legal records require a primary official source")
        if not self.resolved and (not self.presumption_note or len(self.presumption_note) < 30):
            raise ValueError("unresolved legal records require a presumption note")
        if self.resolved and self.presumption_note is not None:
            raise ValueError("resolved legal records must use a null presumption note")
        return self


class ClaimTrackRecord(ActorModel):
    sample_size: Annotated[int, Field(ge=0)]
    by_verdict: dict[Verdict, Annotated[int, Field(ge=0)]]
    by_statement_type: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    evaluated_claim_ids: tuple[str, ...]
    period: dict[Literal["from", "to"], DateValue] | None = None
    caveat: Annotated[str, Field(min_length=40)]

    @model_validator(mode="after")
    def _counts_are_auditably_complete(self) -> ClaimTrackRecord:
        if len(set(self.evaluated_claim_ids)) != len(self.evaluated_claim_ids):
            raise ValueError("evaluated_claim_ids must be unique")
        if len(self.evaluated_claim_ids) != self.sample_size:
            raise ValueError("sample_size must equal the number of evaluated claim ids")
        if sum(self.by_verdict.values()) != self.sample_size:
            raise ValueError("verdict counts must sum to sample_size")
        if self.by_statement_type and sum(self.by_statement_type.values()) != self.sample_size:
            raise ValueError("statement-type counts must sum to sample_size")
        return self


class FramingPattern(ActorModel):
    recurring_emphases: tuple[str, ...] = ()
    recurring_omissions: tuple[str, ...] = ()
    certainty_tendency: (
        Literal["overstates", "calibrated", "understates", "insufficient_data"] | None
    ) = None
    components: tuple[dict, ...]
    confidence: dict


class ActorProfile(ActorModel):
    id: Annotated[str, Field(pattern=r"^actor:[A-Za-z0-9._:-]+$")]
    display_name: str
    is_natural_person: bool
    jurisdiction: str | None = None
    roles: tuple[Role, ...]
    affiliations: tuple[Affiliation, ...] = ()
    declared_interests: tuple[DeclaredInterest, ...] = ()
    legal_record: tuple[LegalRecordEntry, ...] = ()
    claim_track_record: ClaimTrackRecord | None = None
    framing_pattern: FramingPattern | None = None
    profile_uncertainties: tuple[dict, ...] = ()
    sources: tuple[SourceRef, ...]

    @model_validator(mode="after")
    def _organisations_have_no_personal_legal_record(self) -> ActorProfile:
        if not self.is_natural_person and self.legal_record:
            raise ValueError("organisations cannot carry a personal legal record")
        return self


class ActorProfileSet(ActorModel):
    schema_version: str = "1.0.0"
    data_status: DataStatus
    generated_at: DateTimeValue
    usable_in_blind_evaluation: Literal[False] = False
    actors: tuple[ActorProfile, ...]
