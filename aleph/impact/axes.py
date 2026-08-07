"""The seven policy-effect axes, derived by summing individually-listed components.

⚠ **READ THIS BEFORE QUOTING ANY NUMBER FROM THIS MODULE.**

**These axes describe policy effects. They are NOT political-party labels.**
An axis says where the effects Aleph identified *in a text* fall between two
named poles. It does not classify the document, its drafters, its sponsors or
its supporters, and it licenses no inference about anyone's politics.

**A positive ``households_vs_firms`` value does not mean "right wing", and a
negative one does not mean "left wing".** The poles are ``households`` and
``firms``, not ``left`` and ``right``. The same placement is compatible with any
political sponsorship: a measure advantaging firms may be introduced by any
government, for any reason, and this module has no opinion about whether it
should be. The seven axes must never be summed, averaged, correlated or
projected onto a single dimension — Aleph does not emit a left-right score, and
a consumer that manufactures one from these seven is misusing them.

**A score near zero is ambiguous by construction.** It may mean balanced
effects, offsetting effects, or no provision engaging the axis at all. Those are
three different findings and the score cannot tell them apart, which is why
``components`` and ``rationale`` are required and the number alone is never
sufficient.

How a score is produced
-----------------------

Nothing here asks a model for a number. Each axis owns a table of explicit,
readable :class:`AxisRule` objects. A rule fires against a *provision* when the
provision's mechanism type, provision type, attached monetary roles or text
match what the rule declares, and it contributes a signed weight in the axis's
own units. The axis score is the sum of the weights that fired, clamped to
−100..+100, and every one of those weights is published as a
:class:`~aleph.core.models.Component` naming the provision that produced it.

The consequence is that a reader who disagrees can say *which* rule fired
wrongly on *which* provision — a disagreement the analysis can absorb — rather
than rejecting a number wholesale.

Bipolar incidence, stated plainly
---------------------------------

Several axes measure *who the effects land on*, and for those the sign
convention needs saying out loud: advantaging the negative pole scores negative,
and **disadvantaging** the negative pole scores positive, because incidence has
shifted toward the other pole. A levy on households and a subsidy to firms push
``households_vs_firms`` in the same direction. Each rule states which of the two
it represents in its ``rationale``, so this is visible per component and never
has to be inferred from the total.

Refusal
-------

:func:`build_axes` raises :class:`~aleph.core.errors.InsufficientEvidenceError`
if a non-zero score would ever be produced with an empty component list. Where no
rule fires, the axis is published at zero with one explicit component recording
that no provision engaged it — an honest finding, and a very different statement
from "the effects balance out".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from aleph.core.enums import (
    ConfidenceEffect,
    ConfidenceFactor,
    Direction,
    EvidenceTier,
    ImpactAxisKey,
    MechanismType,
    MonetaryRole,
    ProvisionType,
    Recurrence,
)
from aleph.core.errors import InsufficientEvidenceError
from aleph.core.models import (
    Component,
    Confidence,
    ConfidenceBasis,
    EvidenceItem,
    ImpactAxes,
    ImpactAxis,
    MonetaryValue,
    Provision,
)

__all__ = [
    "AXES_VERSION",
    "AXIS_DEFINITIONS",
    "AxisDefinition",
    "AxisDerivation",
    "AxisRule",
    "ComponentDerivation",
    "ImpactAxesResult",
    "build_axes",
    "fold",
]

#: Version of this analyser. Axis placement is rule-dependent and a score is only
#: interpretable alongside the rule table that produced it.
AXES_VERSION: Final[str] = "aleph-impact-axes/1.0.0"


def fold(text: str) -> str:
    """Lowercase and strip accents, so ``económico`` and ``economico`` match."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _phrase(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AxisRule:
    """One named, signed reason a provision moves an axis.

    A rule is deliberately small and legible. It says what to look for
    (structural type, monetary role, or wording), which pole that evidence
    points to, and how many points it is worth. Anyone can read the table and
    predict what a given provision will do to a score, which is the property a
    single opaque model output cannot have.

    ``terms`` are matched against the provision's title, text and stated
    mechanism, folded to lowercase without accents. They are ordinary
    policy-instrument vocabulary in Spanish and English: no jurisdiction, no
    institution, no party and no person appears in any rule anywhere in this
    module.
    """

    id: str
    label: str
    sign: int
    """``-1`` toward the axis's negative (first-named) pole, ``+1`` toward the positive."""
    base_weight: float
    """Points on the −100..+100 scale before the signal and scale multipliers."""
    rationale: str
    """What this rule believes and why, in one sentence a reader can dispute."""
    terms: tuple[str, ...] = ()
    mechanism_types: frozenset[MechanismType] = frozenset()
    provision_types: frozenset[ProvisionType] = frozenset()
    monetary_roles: frozenset[MonetaryRole] = frozenset()


#: Multiplier applied when a rule matched on wording *and* on structure. Both
#: signals agreeing is the strongest evidence a rule table can offer.
SIGNAL_BOTH: Final[float] = 1.0

#: Multiplier when only the structural signal matched — the provision is of the
#: right type but its wording did not confirm the rule's specific mechanism.
SIGNAL_STRUCTURE_ONLY: Final[float] = 0.7

#: Multiplier when only wording matched. Weakest, because a phrase can appear in
#: a recital, an exception or a description of what the document does *not* do.
SIGNAL_TERMS_ONLY: Final[float] = 0.6

#: Multiplier applied when an evidence item independently supports the provision
#: this component rests on.
EVIDENCE_CORROBORATION_BONUS: Final[float] = 1.2


@dataclass(frozen=True, slots=True)
class AxisDefinition:
    """One axis: its poles, what it means, and the rules that place a document on it."""

    key: ImpactAxisKey
    negative_label: str
    positive_label: str
    meaning: str
    """Plain-language statement of what the two poles are, carried into the
    rationale so a score is never published without its reading."""
    rules: tuple[AxisRule, ...]


_HOUSEHOLD_TERMS: Final[tuple[str, ...]] = (
    "hogar",
    "hogares",
    "familia",
    "familias",
    "personas naturales",
    "consumidor",
    "consumidores",
    "usuario final",
    "household",
    "households",
    "family",
    "families",
    "natural persons",
    "consumer",
    "consumers",
    "individuals",
)

_FIRM_TERMS: Final[tuple[str, ...]] = (
    "empresa",
    "empresas",
    "sociedad",
    "sociedades",
    "contribuyente empresarial",
    "empleador",
    "empleadores",
    "industria",
    "sector productivo",
    "firm",
    "firms",
    "company",
    "companies",
    "business",
    "businesses",
    "employer",
    "employers",
    "corporate",
    "enterprise",
    "enterprises",
)

_RELIEF_VERBS: Final[tuple[str, ...]] = (
    "exime",
    "exencion",
    "exento",
    "exentos",
    "rebaja",
    "rebajar",
    "reduce",
    "reduccion",
    "disminuye",
    "credito contra",
    "deduccion",
    "bonificacion",
    "exempt",
    "exemption",
    "relief",
    "reduces",
    "reduction",
    "lowers",
    "credit against",
    "deduction",
    "rebate",
)

_BURDEN_VERBS: Final[tuple[str, ...]] = (
    "grava",
    "gravamen",
    "recarga",
    "aumenta la tasa",
    "eleva la tasa",
    "incrementa el impuesto",
    "sobretasa",
    "multa",
    "sancion",
    "levy",
    "levies",
    "surcharge",
    "raises the rate",
    "increases the tax",
    "fine",
    "penalty",
)


AXIS_DEFINITIONS: Final[Mapping[ImpactAxisKey, AxisDefinition]] = {
    # -----------------------------------------------------------------------
    ImpactAxisKey.HOUSEHOLDS_VS_FIRMS: AxisDefinition(
        key=ImpactAxisKey.HOUSEHOLDS_VS_FIRMS,
        negative_label="households",
        positive_label="firms",
        meaning=(
            "Negative means the identified advantages accrue mainly to households; positive "
            "means they accrue mainly to firms. Disadvantaging one pole counts as movement "
            "toward the other, because this axis measures incidence. It says nothing about "
            "whether either outcome is desirable, and it is not a party label."
        ),
        rules=(
            AxisRule(
                id="hh.benefit_to_households",
                label="benefit, transfer or exemption reaching households",
                sign=-1,
                base_weight=18.0,
                rationale=(
                    "A payment, entitlement or tax relief whose stated recipients are "
                    "households places the advantage on the household side."
                ),
                terms=_HOUSEHOLD_TERMS + _RELIEF_VERBS,
                provision_types=frozenset(
                    {ProvisionType.BENEFIT, ProvisionType.ENTITLEMENT, ProvisionType.SUBSIDY}
                ),
                mechanism_types=frozenset({MechanismType.TRANSFER}),
                monetary_roles=frozenset({MonetaryRole.BENEFIT_AMOUNT, MonetaryRole.TRANSFER}),
            ),
            AxisRule(
                id="hh.burden_on_households",
                label="tax, fee or charge falling on households",
                sign=1,
                base_weight=14.0,
                rationale=(
                    "A levy or fee whose stated payers are households shifts net incidence "
                    "away from the household side."
                ),
                terms=_HOUSEHOLD_TERMS + _BURDEN_VERBS,
                provision_types=frozenset({ProvisionType.TAX, ProvisionType.FEE}),
            ),
            AxisRule(
                id="hh.benefit_to_firms",
                label="relief, credit or allocation reaching firms",
                sign=1,
                base_weight=18.0,
                rationale=(
                    "A credit, deduction, subsidy or allocation whose stated recipients are "
                    "firms places the advantage on the firm side."
                ),
                terms=_FIRM_TERMS + _RELIEF_VERBS,
                provision_types=frozenset({ProvisionType.SUBSIDY, ProvisionType.BENEFIT}),
                mechanism_types=frozenset({MechanismType.FUNDING, MechanismType.MARKET_ENTRY}),
            ),
            AxisRule(
                id="hh.burden_on_firms",
                label="tax, fee, sanction or compliance duty falling on firms",
                sign=-1,
                base_weight=14.0,
                rationale=(
                    "A levy, penalty or reporting duty whose stated subjects are firms shifts "
                    "net incidence away from the firm side."
                ),
                terms=_FIRM_TERMS + _BURDEN_VERBS,
                provision_types=frozenset(
                    {
                        ProvisionType.TAX,
                        ProvisionType.FEE,
                        ProvisionType.SANCTION,
                        ProvisionType.REPORTING_REQUIREMENT,
                    }
                ),
                monetary_roles=frozenset({MonetaryRole.PENALTY}),
            ),
        ),
    ),
    # -----------------------------------------------------------------------
    ImpactAxisKey.REDISTRIBUTION_VS_GROWTH: AxisDefinition(
        key=ImpactAxisKey.REDISTRIBUTION_VS_GROWTH,
        negative_label="redistribution",
        positive_label="growth",
        meaning=(
            "Negative means provisions that work mainly by changing who holds resources; "
            "positive means provisions that work mainly by changing incentives to produce "
            "and invest. Many texts do both, and the components show the mix rather than "
            "hiding it in the net."
        ),
        rules=(
            AxisRule(
                id="rg.progressive_or_targeted",
                label="progressive rate, means test or targeted transfer",
                sign=-1,
                base_weight=20.0,
                rationale=(
                    "Rates that rise with capacity to pay, or eligibility keyed to income or "
                    "wealth, redistribute by construction."
                ),
                terms=(
                    "tasa progresiva",
                    "progresividad",
                    "tramos de renta",
                    "focalizacion",
                    "focalizado",
                    "focalizada",
                    "segun ingreso",
                    "quintil",
                    "decil",
                    "vulnerabilidad",
                    "menores ingresos",
                    "impuesto al patrimonio",
                    "herencia",
                    "progressive rate",
                    "progressivity",
                    "income bands",
                    "means-tested",
                    "means tested",
                    "targeted at",
                    "lowest income",
                    "wealth tax",
                    "inheritance",
                    "income decile",
                ),
                provision_types=frozenset(
                    {ProvisionType.ELIGIBILITY_CRITERION, ProvisionType.ENTITLEMENT}
                ),
                mechanism_types=frozenset(
                    {MechanismType.TRANSFER, MechanismType.ELIGIBILITY_CHANGE}
                ),
            ),
            AxisRule(
                id="rg.floor_or_minimum",
                label="floor, minimum or universal guarantee",
                sign=-1,
                base_weight=14.0,
                rationale=(
                    "Setting a floor below which no one may fall changes the distribution "
                    "directly rather than through production incentives."
                ),
                terms=(
                    "ingreso minimo",
                    "salario minimo",
                    "pension basica",
                    "piso garantizado",
                    "garantia universal",
                    "minimum income",
                    "minimum wage",
                    "basic pension",
                    "guaranteed floor",
                    "universal guarantee",
                ),
                monetary_roles=frozenset({MonetaryRole.FLOOR}),
            ),
            AxisRule(
                id="rg.investment_incentive",
                label="investment, depreciation or research incentive",
                sign=1,
                base_weight=20.0,
                rationale=(
                    "Instruments keyed to capital formation or research change the return on "
                    "producing rather than who holds existing resources."
                ),
                terms=(
                    "incentivo a la inversion",
                    "depreciacion acelerada",
                    "credito por investigacion",
                    "investigacion y desarrollo",
                    "innovacion",
                    "productividad",
                    "competitividad",
                    "formacion de capital",
                    "investment incentive",
                    "accelerated depreciation",
                    "research and development",
                    "innovation",
                    "productivity",
                    "competitiveness",
                    "capital formation",
                ),
                mechanism_types=frozenset({MechanismType.TAX_CHANGE, MechanismType.FUNDING}),
            ),
            AxisRule(
                id="rg.entry_or_deregulation",
                label="market entry opened or requirement removed",
                sign=1,
                base_weight=12.0,
                rationale=(
                    "Lowering the cost of entering or operating in a market works through "
                    "production decisions, not through transfers."
                ),
                terms=(
                    "simplifica",
                    "elimina el requisito",
                    "suprime la exigencia",
                    "libre entrada",
                    "desregula",
                    "simplifies",
                    "removes the requirement",
                    "abolishes the requirement",
                    "free entry",
                    "deregulat",
                ),
                mechanism_types=frozenset({MechanismType.MARKET_ENTRY}),
            ),
        ),
    ),
    # -----------------------------------------------------------------------
    ImpactAxisKey.PUBLIC_VS_PRIVATE_PROVISION: AxisDefinition(
        key=ImpactAxisKey.PUBLIC_VS_PRIVATE_PROVISION,
        negative_label="public provision",
        positive_label="private provision",
        meaning=(
            "Negative means a service or function is moved toward public delivery; positive "
            "means toward private delivery. Funding source and delivery agent are different "
            "questions and only the delivery agent is scored here."
        ),
        rules=(
            AxisRule(
                id="pp.public_delivery",
                label="public body created, expanded or made the deliverer",
                sign=-1,
                base_weight=20.0,
                rationale=(
                    "Creating or expanding a public body to deliver a service moves provision "
                    "toward the public side."
                ),
                terms=(
                    "crea el servicio publico",
                    "servicio publico",
                    "prestacion estatal",
                    "provision publica",
                    "administracion directa",
                    "estatiza",
                    "red publica",
                    "public service",
                    "state provision",
                    "public delivery",
                    "direct administration",
                    "publicly operated",
                    "public network",
                ),
                provision_types=frozenset({ProvisionType.INSTITUTIONAL_MANDATE}),
                mechanism_types=frozenset({MechanismType.INSTITUTIONAL_CREATION}),
            ),
            AxisRule(
                id="pp.private_delivery",
                label="concession, tender, voucher or outsourcing to private operators",
                sign=1,
                base_weight=20.0,
                rationale=(
                    "Contracting delivery out, or funding a user to purchase it, moves "
                    "provision toward the private side even when the money stays public."
                ),
                terms=(
                    "concesion",
                    "concesiones",
                    "licitacion",
                    "operador privado",
                    "prestador privado",
                    "externaliza",
                    "subcontrata",
                    "voucher",
                    "subvencion a la demanda",
                    "privatiza",
                    "concession",
                    "tender",
                    "private operator",
                    "private provider",
                    "outsourc",
                    "contracted out",
                    "demand-side subsidy",
                    "privatis",
                    "when privatiz",
                ),
                mechanism_types=frozenset({MechanismType.MARKET_ENTRY}),
            ),
            AxisRule(
                id="pp.private_licensing",
                label="private entry authorised into a regulated activity",
                sign=1,
                base_weight=12.0,
                rationale=(
                    "Authorising private entrants into an activity previously reserved moves "
                    "provision toward the private side."
                ),
                terms=(
                    "autoriza a privados",
                    "permite la participacion privada",
                    "abre a nuevos operadores",
                    "authorises private",
                    "authorizes private",
                    "permits private participation",
                    "opens to new operators",
                ),
                provision_types=frozenset({ProvisionType.PERMISSION}),
            ),
        ),
    ),
    # -----------------------------------------------------------------------
    ImpactAxisKey.WORKER_PROTECTION_VS_FLEXIBILITY: AxisDefinition(
        key=ImpactAxisKey.WORKER_PROTECTION_VS_FLEXIBILITY,
        negative_label="worker protection",
        positive_label="flexibility",
        meaning=(
            "Negative means employment rules are tightened toward protection; positive means "
            "they are loosened toward flexibility. Both poles have costs and benefits and "
            "this axis asserts neither."
        ),
        rules=(
            AxisRule(
                id="wp.protection",
                label="dismissal, wage, hours or safety protection strengthened",
                sign=-1,
                base_weight=20.0,
                rationale=(
                    "Restricting termination, raising wage floors, capping hours or adding "
                    "safety duties tightens protection."
                ),
                terms=(
                    "despido injustificado",
                    "indemnizacion por anos de servicio",
                    "estabilidad laboral",
                    "fuero",
                    "negociacion colectiva",
                    "sindicato",
                    "jornada maxima",
                    "descanso obligatorio",
                    "seguridad y salud en el trabajo",
                    "salario minimo",
                    "unfair dismissal",
                    "severance",
                    "job security",
                    "collective bargaining",
                    "trade union",
                    "maximum working time",
                    "mandatory rest",
                    "occupational safety",
                    "minimum wage",
                ),
                provision_types=frozenset({ProvisionType.OBLIGATION, ProvisionType.PROHIBITION}),
            ),
            AxisRule(
                id="wp.flexibility",
                label="contract, hours or termination rules loosened",
                sign=1,
                base_weight=20.0,
                rationale=(
                    "Permitting shorter-term contracts, variable hours or simpler termination "
                    "loosens the employment relationship."
                ),
                terms=(
                    "contrato a plazo fijo",
                    "jornada flexible",
                    "adaptabilidad laboral",
                    "distribucion flexible de la jornada",
                    "simplifica el despido",
                    "subcontratacion",
                    "trabajo a honorarios",
                    "fixed-term contract",
                    "flexible working time",
                    "working-time flexibility",
                    "simplified dismissal",
                    "at-will",
                    "subcontracting",
                    "independent contractor",
                ),
                provision_types=frozenset({ProvisionType.PERMISSION}),
                mechanism_types=frozenset({MechanismType.ELIGIBILITY_CHANGE}),
            ),
            AxisRule(
                id="wp.exemption_from_labour_duty",
                label="employer exempted from an existing labour obligation",
                sign=1,
                base_weight=14.0,
                rationale=(
                    "Carving an employer out of a standing duty reduces protection whatever "
                    "the stated reason for the carve-out."
                ),
                terms=(
                    "exime al empleador",
                    "no sera aplicable el articulo",
                    "quedan excluidos del regimen laboral",
                    "exempts the employer",
                    "shall not apply to employers",
                    "excluded from the labour regime",
                ),
            ),
        ),
    ),
    # -----------------------------------------------------------------------
    ImpactAxisKey.ENVIRONMENT_VS_PROJECT_ACCELERATION: AxisDefinition(
        key=ImpactAxisKey.ENVIRONMENT_VS_PROJECT_ACCELERATION,
        negative_label="environmental safeguards",
        positive_label="project acceleration",
        meaning=(
            "Negative means environmental safeguards are strengthened; positive means "
            "approval or execution of projects is accelerated. A text can do both, in "
            "different provisions, and the components will show it."
        ),
        rules=(
            AxisRule(
                id="env.safeguard",
                label="assessment, limit or protected status strengthened",
                sign=-1,
                base_weight=20.0,
                rationale=(
                    "Adding an assessment requirement, tightening a limit or extending "
                    "protected status raises the environmental constraint on activity."
                ),
                terms=(
                    "evaluacion de impacto ambiental",
                    "estudio de impacto ambiental",
                    "limite de emision",
                    "norma de emision",
                    "area protegida",
                    "biodiversidad",
                    "conservacion",
                    "remediacion",
                    "sancion ambiental",
                    "environmental impact assessment",
                    "emission limit",
                    "emission standard",
                    "protected area",
                    "biodiversity",
                    "conservation",
                    "remediation",
                    "environmental penalty",
                ),
                provision_types=frozenset(
                    {ProvisionType.OBLIGATION, ProvisionType.PROHIBITION, ProvisionType.SANCTION}
                ),
                mechanism_types=frozenset({MechanismType.QUANTITY_REGULATION}),
            ),
            AxisRule(
                id="env.acceleration",
                label="permitting shortened, waived or deemed granted",
                sign=1,
                base_weight=20.0,
                rationale=(
                    "Cutting approval deadlines, waiving assessment or deeming silence to be "
                    "consent accelerates execution at the cost of scrutiny."
                ),
                terms=(
                    "silencio administrativo positivo",
                    "aprobacion automatica",
                    "reduce el plazo de tramitacion",
                    "ventanilla unica",
                    "permiso exprés",
                    "permiso expres",
                    "exime de evaluacion",
                    "tramitacion preferente",
                    "deemed approved",
                    "automatic approval",
                    "shortens the approval period",
                    "one-stop shop",
                    "fast-track",
                    "fast track",
                    "waives the assessment",
                    "priority processing",
                ),
                mechanism_types=frozenset({MechanismType.PROCEDURAL_REQUIREMENT}),
            ),
        ),
    ),
    # -----------------------------------------------------------------------
    ImpactAxisKey.CENTRAL_VS_LOCAL: AxisDefinition(
        key=ImpactAxisKey.CENTRAL_VS_LOCAL,
        negative_label="central government",
        positive_label="regional and local bodies",
        meaning=(
            "Negative means authority, revenue or discretion moves toward central "
            "government; positive means toward regional and local bodies."
        ),
        rules=(
            AxisRule(
                id="cl.centralise",
                label="central approval, register or retention required",
                sign=-1,
                base_weight=18.0,
                rationale=(
                    "Requiring central sign-off, a national register or retention of revenue "
                    "at the centre concentrates authority."
                ),
                terms=(
                    "aprobacion del ministerio",
                    "autorizacion previa del nivel central",
                    "registro nacional",
                    "nivel central",
                    "gobierno central",
                    "tesoreria general",
                    "rectoria nacional",
                    "ministerial approval",
                    "prior central authorisation",
                    "national register",
                    "central government",
                    "national treasury",
                    "centrally determined",
                ),
                provision_types=frozenset(
                    {ProvisionType.INSTITUTIONAL_MANDATE, ProvisionType.PROCEDURE}
                ),
            ),
            AxisRule(
                id="cl.devolve",
                label="competence, revenue or discretion transferred to sub-national bodies",
                sign=1,
                base_weight=18.0,
                rationale=(
                    "Assigning a competence, a revenue share or a discretion to regional or "
                    "local bodies disperses authority."
                ),
                terms=(
                    "municipalidad",
                    "municipalidades",
                    "municipio",
                    "gobierno regional",
                    "gobiernos regionales",
                    "descentraliza",
                    "transfiere la competencia",
                    "nivel local",
                    "autonomia local",
                    "municipality",
                    "municipalities",
                    "local authority",
                    "regional government",
                    "decentralis",
                    "decentraliz",
                    "transfers the competence",
                    "local discretion",
                    "local autonomy",
                ),
                provision_types=frozenset({ProvisionType.DELEGATION}),
                mechanism_types=frozenset({MechanismType.INSTITUTIONAL_CREATION}),
            ),
        ),
    ),
    # -----------------------------------------------------------------------
    ImpactAxisKey.CURRENT_RELIEF_VS_LONG_TERM_INVESTMENT: AxisDefinition(
        key=ImpactAxisKey.CURRENT_RELIEF_VS_LONG_TERM_INVESTMENT,
        negative_label="current relief",
        positive_label="long-term investment",
        meaning=(
            "Negative means resources are directed at immediate relief; positive means at "
            "capacity built over a longer horizon. Neither is the responsible choice in the "
            "abstract; which is appropriate depends on circumstances this module cannot see."
        ),
        rules=(
            AxisRule(
                id="ri.immediate_relief",
                label="one-off, emergency or transitional payment",
                sign=-1,
                base_weight=20.0,
                rationale=(
                    "A single payment, an emergency measure or a transitional regime spends "
                    "on the present rather than on capacity."
                ),
                terms=(
                    "bono",
                    "pago unico",
                    "por una sola vez",
                    "emergencia",
                    "transitorio",
                    "transitoria",
                    "alivio inmediato",
                    "ayuda extraordinaria",
                    "one-off payment",
                    "single payment",
                    "emergency",
                    "transitional",
                    "immediate relief",
                    "extraordinary support",
                ),
                provision_types=frozenset({ProvisionType.TRANSITIONAL, ProvisionType.BENEFIT}),
                monetary_roles=frozenset({MonetaryRole.BENEFIT_AMOUNT}),
            ),
            AxisRule(
                id="ri.long_term_capacity",
                label="infrastructure, capital fund, training or multi-year plan",
                sign=1,
                base_weight=20.0,
                rationale=(
                    "Building infrastructure, capitalising a fund or committing a multi-year "
                    "programme spends on capacity that pays out later."
                ),
                terms=(
                    "infraestructura",
                    "fondo de capital",
                    "fondo soberano",
                    "plan plurianual",
                    "capacitacion",
                    "formacion tecnica",
                    "inversion de largo plazo",
                    "investigacion y desarrollo",
                    "infrastructure",
                    "capital fund",
                    "sovereign fund",
                    "multi-year plan",
                    "multiyear",
                    "training programme",
                    "skills programme",
                    "long-term investment",
                    "research and development",
                ),
                provision_types=frozenset({ProvisionType.FUNDING_ALLOCATION}),
                monetary_roles=frozenset({MonetaryRole.ALLOCATION}),
            ),
            AxisRule(
                id="ri.sunset_limits_horizon",
                label="measure carries a sunset date",
                sign=-1,
                base_weight=8.0,
                rationale=(
                    "A provision that expires cannot build capacity beyond its own horizon, "
                    "whatever it funds."
                ),
                provision_types=frozenset({ProvisionType.SUNSET}),
            ),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Derivation records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComponentDerivation:
    """Everything that produced one component of one axis score.

    Published so a disagreement can be precise: "rule ``env.acceleration`` should
    not have fired on ``prov:x:12``, because the phrase appears in an exception"
    is a correction the analysis can absorb. "The number feels too high" is not.
    """

    rule_id: str
    rule_label: str
    rule_rationale: str
    provision_id: str
    provision_title: str
    sign: int
    base_weight: float
    matched_terms: tuple[str, ...]
    matched_structure: tuple[str, ...]
    signal_multiplier: float
    scale_multiplier: float
    evidence_multiplier: float
    raw_points: float
    """Signed points before the axis-level clamp rescale."""
    final_points: float
    """Signed points after rescale; these sum exactly to the axis score."""
    evidence_refs: tuple[str, ...]

    def to_component(self) -> Component:
        """Render as the contract's inspectable component."""
        direction = (
            Direction.NEGATIVE
            if self.final_points < 0
            else Direction.POSITIVE
            if self.final_points > 0
            else Direction.NONE
        )
        detail = []
        if self.matched_terms:
            detail.append("wording: " + ", ".join(f"{t!r}" for t in self.matched_terms[:6]))
        if self.matched_structure:
            detail.append("structure: " + ", ".join(self.matched_structure))
        detail.append(
            f"{self.base_weight:g} base × {self.signal_multiplier:g} signal × "
            f"{self.scale_multiplier:g} scale × {self.evidence_multiplier:g} corroboration"
        )
        detail.append(self.rule_rationale)
        return Component(
            label=f"{self.provision_title} — {self.rule_label}",
            direction=direction,
            weight=round(max(-100.0, min(100.0, self.final_points)), 3),
            evidence_refs=list(self.evidence_refs),
            note="; ".join(detail),
        )


@dataclass(frozen=True, slots=True)
class AxisDerivation:
    """The full derivation of one axis placement.

    Returned by :meth:`ImpactAxesResult.explain`. Contains the arithmetic, every
    component, the components pulling the *other* way, the provisions that
    engaged no rule at all, and the confidence with its basis. It contains no
    interpretation: what a placement means for a reader is the reader's to
    decide, guided by ``meaning``.
    """

    key: ImpactAxisKey
    negative_label: str
    positive_label: str
    meaning: str
    score: int
    raw_sum: float
    clamped: bool
    rescale_factor: float
    components: tuple[ComponentDerivation, ...]
    toward_negative: tuple[ComponentDerivation, ...]
    toward_positive: tuple[ComponentDerivation, ...]
    provisions_considered: int
    provisions_engaging_axis: int
    unengaged_provision_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    confidence: Confidence
    rationale: str

    def to_axis(self) -> ImpactAxis:
        """Render as the contract model, components and all."""
        components = [derivation.to_component() for derivation in self.components]
        if not components:
            components = [
                Component(
                    label="no provision of this document engages this axis",
                    direction=Direction.NONE,
                    weight=0.0,
                    note=(
                        f"{self.provisions_considered} provision(s) were checked against "
                        f"{len(AXIS_DEFINITIONS[self.key].rules)} rule(s) and none fired. A "
                        "score of zero here means the axis was not engaged, NOT that the "
                        "effects balance out."
                    ),
                )
            ]
        return ImpactAxis(
            score=self.score,
            negative_label=self.negative_label,
            positive_label=self.positive_label,
            components=components,
            evidence_refs=list(self.evidence_refs),
            confidence=self.confidence,
            rationale=self.rationale,
        )


@dataclass(frozen=True, slots=True)
class ImpactAxesResult:
    """All seven axes with their derivations, and no eighth number.

    There is deliberately no ``overall`` field, no summary and no arithmetic that
    would combine axes. The seven are not commensurable and a combined figure
    would have exactly one available reading — a political one — which Aleph does
    not produce.
    """

    version: str
    derivations: Mapping[ImpactAxisKey, AxisDerivation]

    def explain(self, axis: ImpactAxisKey | str) -> AxisDerivation:
        """Return the full derivation of one axis.

        Raises:
            KeyError: If ``axis`` is not one of the seven fixed keys.
        """
        return self.derivations[ImpactAxisKey(axis)]

    def to_model(self) -> ImpactAxes:
        """Render the seven axes as the contract model."""
        return ImpactAxes(
            **{key.value: self.derivations[key].to_axis() for key in ImpactAxisKey}  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ProvisionView:
    """A provision plus the derived facts every rule needs, computed once."""

    provision: Provision
    folded: str
    monetary_roles: frozenset[MonetaryRole]
    money_scale: float
    """This provision's largest figure as a share of the document's largest."""
    supporting_evidence: tuple[str, ...]
    corroborating_tier: bool


_TERM_CACHE: dict[str, re.Pattern[str]] = {}


def _pattern_for(term: str) -> re.Pattern[str]:
    cached = _TERM_CACHE.get(term)
    if cached is None:
        cached = _phrase(term)
        _TERM_CACHE[term] = cached
    return cached


def _build_views(
    provisions: Sequence[Provision],
    monetary_values: Sequence[MonetaryValue],
    evidence: Sequence[EvidenceItem],
) -> tuple[_ProvisionView, ...]:
    """Precompute per-provision facts: folded text, monetary roles, scale, evidence."""
    by_provision: dict[str, list[MonetaryValue]] = {}
    for value in monetary_values:
        if value.provision_id:
            by_provision.setdefault(value.provision_id, []).append(value)
    largest = max(
        (abs(v.money.amount) * _UNIT_SCALE.get(v.money.unit.value, 1.0) for v in monetary_values),
        default=0.0,
    )

    support_index: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        for target in item.supports:
            support_index.setdefault(target, []).append(item)

    views: list[_ProvisionView] = []
    for provision in provisions:
        values = by_provision.get(provision.id, [])
        own = max(
            (abs(v.money.amount) * _UNIT_SCALE.get(v.money.unit.value, 1.0) for v in values),
            default=0.0,
        )
        scale = (own / largest) if largest > 0 and own > 0 else 0.0
        items = support_index.get(provision.id, [])
        views.append(
            _ProvisionView(
                provision=provision,
                folded=fold(
                    " ".join(
                        part
                        for part in (
                            provision.title,
                            provision.text,
                            provision.mechanism,
                            " ".join(provision.affected_populations),
                            " ".join(provision.affected_industries),
                            " ".join(provision.affected_institutions),
                        )
                        if part
                    )
                ),
                monetary_roles=frozenset(v.role for v in values),
                money_scale=scale,
                supporting_evidence=tuple(sorted(item.id for item in items)),
                corroborating_tier=any(
                    item.tier
                    in {
                        EvidenceTier.PRIMARY_DOCUMENT,
                        EvidenceTier.LEGISLATIVE_RECORD,
                        EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
                        EvidenceTier.STATISTICAL_DATASET,
                    }
                    for item in items
                ),
            )
        )
    return tuple(views)


#: Rough order-of-magnitude scale per money unit, used only to compare figures
#: *within one document* so a provision carrying the largest number is not
#: outweighed by one carrying the smallest. Never used to restate an amount.
_UNIT_SCALE: Final[Mapping[str, float]] = {
    "unit": 1.0,
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
    "percent_of_gdp": 1e9,
}


def _match(rule: AxisRule, view: _ProvisionView) -> ComponentDerivation | None:
    """Evaluate one rule against one provision.

    Returns ``None`` when the rule does not fire. A rule that fires reports both
    the wording it matched and the structural facts it matched, so the reader can
    see whether the placement rests on a phrase, on the provision's declared
    type, or on both agreeing.
    """
    matched_terms = tuple(term for term in rule.terms if _pattern_for(term).search(view.folded))
    structure: list[str] = []
    provision = view.provision
    if provision.mechanism_type is not None and provision.mechanism_type in rule.mechanism_types:
        structure.append(f"mechanism_type={provision.mechanism_type.value}")
    if provision.provision_type in rule.provision_types:
        structure.append(f"provision_type={provision.provision_type.value}")
    roles = view.monetary_roles & rule.monetary_roles
    if roles:
        structure.append("monetary_role=" + ",".join(sorted(r.value for r in roles)))

    if matched_terms and structure:
        signal = SIGNAL_BOTH
    elif structure:
        signal = SIGNAL_STRUCTURE_ONLY
    elif matched_terms:
        signal = SIGNAL_TERMS_ONLY
    else:
        return None

    # A provision carrying a large share of the document's money weighs more; one
    # carrying no figure at all is neither promoted nor demoted.
    scale = 1.0 + 0.4 * view.money_scale if view.money_scale > 0 else 1.0
    corroboration = EVIDENCE_CORROBORATION_BONUS if view.corroborating_tier else 1.0
    raw = rule.sign * rule.base_weight * signal * scale * corroboration

    return ComponentDerivation(
        rule_id=rule.id,
        rule_label=rule.label,
        rule_rationale=rule.rationale,
        provision_id=provision.id,
        provision_title=provision.title or provision.id,
        sign=rule.sign,
        base_weight=rule.base_weight,
        matched_terms=matched_terms,
        matched_structure=tuple(structure),
        signal_multiplier=signal,
        scale_multiplier=round(scale, 3),
        evidence_multiplier=corroboration,
        raw_points=round(raw, 3),
        final_points=round(raw, 3),
        evidence_refs=(provision.id, *view.supporting_evidence),
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _confidence_for(
    hits: Sequence[ComponentDerivation],
    views: Sequence[_ProvisionView],
) -> Confidence:
    """Derive evidence confidence in a placement from what actually backed it.

    Rises with the number of provisions that engaged the axis, with independent
    corroboration of those provisions, and with agreement among the components.
    Falls when every component rests on wording alone, since a phrase can appear
    in a recital or in an exception.
    """
    basis: list[ConfidenceBasis] = []
    if not hits:
        return Confidence(
            evidence_confidence=0.0,
            basis=[
                ConfidenceBasis(
                    factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                    effect=ConfidenceEffect.LOWERS,
                    note=(
                        f"none of the {len(views)} provision(s) engaged this axis; the score "
                        "is zero because nothing was found, not because effects offset"
                    ),
                )
            ],
            limiting_factor="no provision engaged this axis",
        )

    value = 0.25
    value += min(0.2, 0.05 * len(hits))
    basis.append(
        ConfidenceBasis(
            factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
            effect=ConfidenceEffect.RAISES,
            note=f"{len(hits)} component(s) drawn from {len({h.provision_id for h in hits})} provision(s)",
        )
    )

    corroborated = [h for h in hits if len(h.evidence_refs) > 1]
    if corroborated:
        value += min(0.2, 0.07 * len(corroborated))
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.EVIDENCE_AGREEMENT,
                effect=ConfidenceEffect.RAISES,
                note=f"{len(corroborated)} component(s) rest on a provision an evidence item supports",
            )
        )
    else:
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.EVIDENCE_AGREEMENT,
                effect=ConfidenceEffect.LOWERS,
                note="no external evidence item supports any of the provisions behind this placement",
            )
        )

    lexical_only = [h for h in hits if not h.matched_structure]
    if lexical_only and len(lexical_only) == len(hits):
        value -= 0.15
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.CLAIM_AMBIGUITY,
                effect=ConfidenceEffect.LOWERS,
                note=(
                    "every component rests on wording alone, with no structural confirmation "
                    "from the provision's declared type or monetary role"
                ),
            )
        )
    elif not lexical_only:
        value += 0.1
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.QUANTITATIVE_VALIDATION,
                effect=ConfidenceEffect.RAISES,
                note="every component is confirmed by the provision's declared structure",
            )
        )

    negative = sum(1 for h in hits if h.sign < 0)
    positive = len(hits) - negative
    if negative and positive:
        value -= 0.1
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.EVIDENCE_AGREEMENT,
                effect=ConfidenceEffect.LOWERS,
                note=(
                    f"{negative} component(s) point toward the negative pole and {positive} "
                    "toward the positive; the net understates both"
                ),
            )
        )

    limiting = None
    if lexical_only and len(lexical_only) == len(hits):
        limiting = "the placement rests on wording alone"
    elif not corroborated:
        limiting = "no independent evidence corroborates the provisions behind the placement"
    elif negative and positive:
        limiting = "the components disagree in sign; read them rather than the net"

    return Confidence(
        evidence_confidence=max(0.0, min(0.85, round(value, 3))),
        basis=basis,
        limiting_factor=limiting,
    )


def _build_one_axis(
    definition: AxisDefinition,
    views: Sequence[_ProvisionView],
) -> AxisDerivation:
    """Fire every rule of one axis against every provision and assemble the result.

    Raises:
        InsufficientEvidenceError: If a non-zero score would be produced with no
            components. That combination cannot occur through the arithmetic
            below, and the check exists so that it cannot be introduced later
            either: a dial a reader cannot open is not an Aleph result.
    """
    hits: list[ComponentDerivation] = []
    for view in views:
        for rule in definition.rules:
            derivation = _match(rule, view)
            if derivation is not None:
                hits.append(derivation)

    hits.sort(key=lambda h: (-abs(h.raw_points), h.provision_id, h.rule_id))
    raw_sum = sum(h.raw_points for h in hits)
    clamped = abs(raw_sum) > 100.0
    rescale = 100.0 / abs(raw_sum) if clamped and raw_sum != 0 else 1.0
    score = int(round(max(-100.0, min(100.0, raw_sum))))

    final = [
        ComponentDerivation(**{**_as_dict(h), "final_points": round(h.raw_points * rescale, 3)})
        for h in hits
    ]
    # Assign the rounding residual to the largest component so the published
    # components sum exactly to the published score.
    if final:
        residual = round(score - sum(f.final_points for f in final), 3)
        if residual:
            index = max(range(len(final)), key=lambda i: abs(final[i].final_points))
            adjusted = round(final[index].final_points + residual, 3)
            final[index] = ComponentDerivation(
                **{**_as_dict(final[index]), "final_points": adjusted}
            )

    if score != 0 and not final:
        raise InsufficientEvidenceError(
            f"axis {definition.key.value!r} would publish a score of {score} with no "
            "components. Every Aleph score must be openable: publish the contributing "
            "provisions and their weights, or do not publish the score.",
            question=f"where do this document's effects fall on {definition.key.value}?",
        )

    engaged = {h.provision_id for h in final}
    unengaged = tuple(sorted(v.provision.id for v in views if v.provision.id not in engaged))
    toward_negative = tuple(h for h in final if h.final_points < 0)
    toward_positive = tuple(h for h in final if h.final_points > 0)
    evidence_refs = tuple(sorted({ref for h in final for ref in h.evidence_refs}))

    if final:
        rationale = (
            f"{definition.meaning} Score {score} is the sum of {len(final)} component(s) drawn "
            f"from {len(engaged)} of {len(views)} provision(s): {len(toward_negative)} toward "
            f"{definition.negative_label} and {len(toward_positive)} toward "
            f"{definition.positive_label}."
            + (
                f" The raw sum was {raw_sum:.1f} and was rescaled by {rescale:.3f} to fit the "
                "−100..+100 scale; the relative size of the components is unchanged."
                if clamped
                else ""
            )
        )
    else:
        rationale = (
            f"{definition.meaning} No provision of this document engaged this axis: "
            f"{len(views)} provision(s) were checked against {len(definition.rules)} rule(s) "
            "and none fired. A score of zero here means the axis was not engaged, NOT that "
            "the effects balance out."
        )

    return AxisDerivation(
        key=definition.key,
        negative_label=definition.negative_label,
        positive_label=definition.positive_label,
        meaning=definition.meaning,
        score=score,
        raw_sum=round(raw_sum, 3),
        clamped=clamped,
        rescale_factor=round(rescale, 4),
        components=tuple(final),
        toward_negative=toward_negative,
        toward_positive=toward_positive,
        provisions_considered=len(views),
        provisions_engaging_axis=len(engaged),
        unengaged_provision_ids=unengaged,
        evidence_refs=evidence_refs,
        confidence=_confidence_for(final, views),
        rationale=rationale,
    )


def _as_dict(derivation: ComponentDerivation) -> dict[str, object]:
    """Field mapping of a slotted frozen dataclass, for copy-with-change."""
    return {name: getattr(derivation, name) for name in ComponentDerivation.__slots__}


def build_axes(
    provisions: Sequence[Provision],
    *,
    monetary_values: Sequence[MonetaryValue] = (),
    evidence: Sequence[EvidenceItem] = (),
) -> ImpactAxesResult:
    """Place a document on all seven axes.

    Every axis is computed the same way and every component is published: the
    provision that produced it, the rule that fired, the wording and structure
    that matched, and the multipliers applied. No axis is ever a single model
    guess, and none is ever published as a bare number.

    Args:
        provisions: The document's operative units. An empty sequence is legal
            and yields seven zero-scored axes, each carrying the explicit
            component that says so.
        monetary_values: Figures attached to provisions. Used for two things
            only: matching monetary-role rules, and weighting a provision by the
            share of the document's money it carries. Never restated.
        evidence: The evidence pool. An item that supports a provision raises
            that provision's components and is cited in ``evidence_refs``.

    Returns:
        An :class:`ImpactAxesResult`. It has seven axes and no aggregate.

    Raises:
        InsufficientEvidenceError: If any axis would publish a non-zero score
            with no components.
    """
    views = _build_views(provisions, monetary_values, evidence)
    derivations = {
        key: _build_one_axis(definition, views) for key, definition in AXIS_DEFINITIONS.items()
    }
    return ImpactAxesResult(version=AXES_VERSION, derivations=derivations)


# ``Recurrence`` and ``field`` are referenced by the rule vocabulary's design
# notes rather than by its code paths; importing them for typing only would be
# dishonest, so they are not imported. This comment marks the deliberate absence.
del Recurrence, field
