"""Reading the numbers in a document without inventing what they mean.

Almost every contested claim about a policy document is a claim about one of its
numbers: how much it costs, who pays, by what date, at what rate. Getting those
numbers out is therefore not a preprocessing chore — it is the point at which an
analysis either becomes checkable or becomes a paraphrase.

The hard part is not finding digits. It is refusing to guess.

**Decimal conventions.** ``1.234`` is one thousand two hundred and thirty-four in
half the world and one and a bit in the other half, and a parser that silently
picks one is wrong by a factor of a thousand roughly half the time it matters.
This module infers the convention from the document as a whole
(:func:`detect_decimal_convention`) using tokens that *cannot* be read both ways —
``1.234,56`` fixes the answer, ``1.234`` does not — and marks any figure that
remains ambiguous so the caller can publish a warning rather than a number.

**Currencies.** A bare ``$`` names no currency: it is used by dozens of
countries. Aleph will not resolve it by guessing a jurisdiction from context, so
a bare symbol with no configured default becomes ISO-4217 ``XXX`` ("no currency
involved") with ``ambiguous_currency`` set. A caller that knows the jurisdiction
supplies ``default_currency`` from a registry file — which is where
jurisdiction knowledge is allowed to live, and the only place.

**Units of account.** Index-linked units such as UF, UDI or UVT are not
currencies and have no ISO code unless a registry supplies one. They are returned
as :class:`~aleph.core.models.Quantity` of kind ``index`` carrying the unit's own
label, rather than being forced into a currency field they do not fit.

**Long and short scales.** Spanish ``billón`` is 10¹², English ``billion`` is
10⁹. Both are converted to the contract's ``billion`` multiplier with the amount
adjusted, so the stored figure means the same thing whichever word the document
used.

Everything here is a pure function of its arguments — no configuration, no
clock, no network, no shared state — so the whole module can be exercised on
string literals. ``raw_text`` is preserved on every result because a
transcription error that cannot be audited is indistinguishable from a fact.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from aleph.core.enums import MonetaryRole, MoneyUnit, QuantityKind
from aleph.core.models import Money, Quantity
from aleph.ingestion.normalize import fold_preserving_length

__all__ = [
    "UNKNOWN_CURRENCY",
    "DecimalConvention",
    "DateOrder",
    "DatePrecision",
    "ParsedNumber",
    "NumberToken",
    "MoneyMatch",
    "QuantityMatch",
    "DateMatch",
    "DurationMatch",
    "DeadlineMatch",
    "QuantityExtraction",
    "detect_decimal_convention",
    "parse_number",
    "iter_number_tokens",
    "extract_money",
    "extract_percentages",
    "extract_dates",
    "extract_durations",
    "extract_deadlines",
    "extract_counts",
    "extract_years",
    "extract_all",
]

#: ISO-4217's own code for "no currency involved". Used rather than a guessed
#: national currency whenever a document writes a bare symbol: naming the wrong
#: currency is a factual error, whereas naming none is a recorded gap.
UNKNOWN_CURRENCY: Final[str] = "XXX"


class DecimalConvention(StrEnum):
    """Which separator a document uses for the decimal point."""

    POINT_DECIMAL = "point_decimal"
    """``1,234.56`` — comma groups, point separates the fraction."""

    COMMA_DECIMAL = "comma_decimal"
    """``1.234,56`` — point groups, comma separates the fraction."""

    UNKNOWN = "unknown"
    """No token in the document settled the question."""


class DateOrder(StrEnum):
    """How to read a purely numeric date whose components are all ≤ 12."""

    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"
    UNKNOWN = "unknown"


class DatePrecision(StrEnum):
    """How much of a date the source actually stated."""

    DAY = "day"
    MONTH = "month"
    YEAR = "year"


# ---------------------------------------------------------------------------
# Numeric grammar
# ---------------------------------------------------------------------------

#: A numeric literal. The grouped alternative uses a backreference so the
#: thousands separator must be used consistently within one number: that is what
#: stops ``1.234,567.89`` — which is not a number in any convention — from being
#: read as though it were.
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\d.,])"
    r"(?:"
    r"\d{1,3}(?:(?P<grp>[., ])\d{3})(?:(?P=grp)\d{3})*(?:[.,]\d+)?"
    r"|"
    r"\d+(?:[.,]\d+)?"
    r")"
    r"(?![\d]|[.,]\d)"
)

_YEAR_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)((?:1[89]|20|21)\d{2})(?!\d)")


@dataclass(frozen=True, slots=True)
class ParsedNumber:
    """A numeric literal resolved to a value, with any doubt recorded.

    ``ambiguous`` is the field that matters. It means the literal could have been
    read another way and the reading chosen rests on a convention rather than on
    evidence, which is exactly the sort of thing that must reach a reader as a
    warning instead of disappearing into a float.
    """

    value: float
    raw_text: str
    ambiguous: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class NumberToken:
    """A numeric literal located in a string."""

    raw_text: str
    start: int
    end: int


def iter_number_tokens(text: str) -> Iterable[NumberToken]:
    """Yield every numeric literal in ``text``, in order."""
    for match in _NUMBER_RE.finditer(text):
        yield NumberToken(match.group(0), match.start(), match.end())


def detect_decimal_convention(text: str) -> DecimalConvention:
    """Infer whether a document writes ``1,234.56`` or ``1.234,56``.

    Only tokens that can be read exactly one way are allowed to vote:

    * both separators present — the last one is the decimal point, decisively;
    * the same separator twice — it must be the grouping separator;
    * one separator with other than three digits after it — it cannot be a
      thousands group, so it is the decimal point.

    ``1.234`` casts no vote in either direction, which is the whole reason a
    document-level pass exists: one such token is unreadable alone, but the
    document that contains it usually contains a decisive one elsewhere.

    Returns:
        The convention, or :attr:`DecimalConvention.UNKNOWN` when the document
        offered no decisive evidence.
    """
    point = comma = 0
    for token in iter_number_tokens(text):
        raw = token.raw_text.replace(" ", "")
        dots, commas = raw.count("."), raw.count(",")
        if dots and commas:
            if raw.rfind(".") > raw.rfind(","):
                point += 3
            else:
                comma += 3
            continue
        if dots > 1:
            comma += 2  # '.' can only be the grouping separator
            continue
        if commas > 1:
            point += 2
            continue
        if dots == 1:
            if len(raw.split(".")[1]) != 3:
                point += 2
        elif commas == 1 and len(raw.split(",")[1]) != 3:
            comma += 2
    if point > comma:
        return DecimalConvention.POINT_DECIMAL
    if comma > point:
        return DecimalConvention.COMMA_DECIMAL
    return DecimalConvention.UNKNOWN


def parse_number(
    raw: str,
    convention: DecimalConvention = DecimalConvention.UNKNOWN,
) -> ParsedNumber:
    """Resolve one numeric literal against a decimal convention.

    Spaces are always thousands groups (they are never a decimal point). When
    both ``.`` and ``,`` appear, the rightmost is the decimal point regardless of
    convention, because no writing system groups after the fraction. A single
    separator followed by exactly three digits is the genuinely ambiguous case
    and is resolved by ``convention``; when the convention is unknown the token
    is read as grouped — documents group far more often than they write three
    decimal places — and flagged.

    Raises:
        ValueError: ``raw`` contains no digits.
    """
    text = raw.strip()
    if not any(char.isdigit() for char in text):
        raise ValueError(f"{raw!r} contains no digits")

    spaced = " " in text
    body = text.replace(" ", "")
    dots, commas = body.count("."), body.count(",")
    ambiguous = False
    note: str | None = None

    if dots and commas:
        decimal_sep = "." if body.rfind(".") > body.rfind(",") else ","
    elif dots > 1:
        decimal_sep = None
    elif commas > 1:
        decimal_sep = None
    elif dots == 1 or commas == 1:
        sep = "." if dots == 1 else ","
        fraction = body.split(sep)[1]
        integer = body.split(sep)[0]
        if len(fraction) == 3 and len(integer) <= 3:
            grouping_sep = "," if convention is DecimalConvention.POINT_DECIMAL else "."
            if convention is DecimalConvention.UNKNOWN:
                decimal_sep = None
                ambiguous = True
                note = (
                    f"{text!r} could be a grouped thousand or a three-decimal "
                    "fraction and the document gave no decisive evidence either "
                    "way; read as grouped"
                )
            elif sep == grouping_sep:
                decimal_sep = None
            else:
                decimal_sep = sep
        else:
            decimal_sep = sep
            expected = "." if convention is DecimalConvention.POINT_DECIMAL else ","
            if convention is not DecimalConvention.UNKNOWN and sep != expected:
                ambiguous = True
                note = (
                    f"{text!r} uses {sep!r} as a decimal separator although the "
                    f"document otherwise uses {expected!r}"
                )
    else:
        decimal_sep = None

    if decimal_sep is None:
        digits = body.replace(".", "").replace(",", "")
        value = float(digits)
    else:
        other = "," if decimal_sep == "." else "."
        value = float(body.replace(other, "").replace(decimal_sep, "."))

    if spaced and decimal_sep is None and note is None:
        note = "space-grouped thousands"
    return ParsedNumber(value=value, raw_text=raw, ambiguous=ambiguous, note=note)


# ---------------------------------------------------------------------------
# Currency and scale vocabularies (data, deliberately jurisdiction-free)
# ---------------------------------------------------------------------------

#: Symbols that name exactly one currency. Matched longest-first, so ``US$``
#: wins over ``$``.
_CURRENCY_SYMBOLS: Final[dict[str, str]] = {
    "US$": "USD",
    "U$S": "USD",
    "CA$": "CAD",
    "A$": "AUD",
    "NZ$": "NZD",
    "HK$": "HKD",
    "NT$": "TWD",
    "MX$": "MXN",
    "R$": "BRL",
    "S/": "PEN",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₩": "KRW",
    "₹": "INR",
    "₽": "RUB",
    "₪": "ILS",
    "₫": "VND",
    "₺": "TRY",
    "₴": "UAH",
    "₦": "NGN",
    "₱": "PHP",
    "₡": "CRC",
    "₲": "PYG",
    "₸": "KZT",
    "฿": "THB",
    "₮": "MNT",
    "₾": "GEL",
}

#: Symbols used by many currencies at once. Recorded as ambiguous rather than
#: resolved: which country's dollar or peso this is cannot be read off the glyph,
#: and Aleph does not infer a jurisdiction in order to fill a field.
_AMBIGUOUS_SYMBOLS: Final[frozenset[str]] = frozenset({"$", "¢", "₨", "kr", "R"})

#: ISO-4217 alphabetic codes recognised when they appear beside a figure. Not the
#: complete register; extend as documents require. A code not listed here is
#: simply not treated as a currency, which is safer than treating any three
#: capitals beside a number as one.
_ISO_CURRENCIES: Final[frozenset[str]] = frozenset(
    """
    AED ARS AUD BGN BOB BRL CAD CHF CLP CNY COP CRC CZK DKK DOP EGP EUR GBP
    GTQ HKD HNL HRK HUF IDR ILS INR ISK JPY KES KRW MAD MXN MYR NGN NIO NOK
    NZD PAB PEN PHP PKR PLN PYG RON RSD RUB SAR SEK SGD THB TRY TWD UAH USD
    UYU VND ZAR XDR XAF XOF XCD XPF XXX
    """.split()
)

#: Index-linked units of account. These are not currencies and have no ISO code
#: unless a registry supplies one, so by default they surface as an ``index``
#: quantity carrying the unit's own label. A caller holding jurisdiction data can
#: pass ``unit_of_account_currencies={"UF": "CLF"}`` to promote one to money —
#: which is exactly where that knowledge belongs.
_UNITS_OF_ACCOUNT: Final[frozenset[str]] = frozenset(
    {"UF", "UTM", "UDI", "UMA", "UVT", "UVR", "SMLV"}
)

#: Currency names that resolve to exactly one code.
_CURRENCY_WORDS: Final[dict[str, str]] = {
    "euro": "EUR",
    "euros": "EUR",
    "libra esterlina": "GBP",
    "libras esterlinas": "GBP",
    "pound sterling": "GBP",
    "pounds sterling": "GBP",
    "yen": "JPY",
    "yenes": "JPY",
    "franco suizo": "CHF",
    "francos suizos": "CHF",
    "swiss franc": "CHF",
    "swiss francs": "CHF",
}

#: Currency names used by many countries. Present so the figure is recognised as
#: money at all, but the code is left unresolved.
_AMBIGUOUS_CURRENCY_WORDS: Final[frozenset[str]] = frozenset(
    {
        "dolar",
        "dolares",
        "dollar",
        "dollars",
        "peso",
        "pesos",
        "real",
        "reais",
        "libra",
        "libras",
        "pound",
        "pounds",
        "corona",
        "coronas",
        "krona",
        "kronor",
        "rupia",
        "rupias",
        "rupee",
        "rupees",
        "dinar",
        "dinares",
        "franco",
        "francos",
        "franc",
        "francs",
        "escudo",
        "escudos",
        "guarani",
        "guaranies",
        "sol",
        "soles",
    }
)

#: Scale words, longest phrase first. The third element is a multiplier applied
#: to the amount, which is how the long-scale/short-scale trap is defused:
#: ``billón`` is 10¹², so it is stored as 1000 × the ``billion`` (10⁹) unit and
#: means the same quantity as the English word would have.
_SCALE_TERMS: Final[tuple[tuple[str, MoneyUnit, float], ...]] = (
    ("miles de millones", MoneyUnit.BILLION, 1.0),
    ("mil millones", MoneyUnit.BILLION, 1.0),
    ("mil milhoes", MoneyUnit.BILLION, 1.0),
    ("thousand million", MoneyUnit.BILLION, 1.0),
    ("billones", MoneyUnit.BILLION, 1000.0),
    ("billon", MoneyUnit.BILLION, 1000.0),
    ("bilhoes", MoneyUnit.BILLION, 1000.0),
    ("bilhao", MoneyUnit.BILLION, 1000.0),
    ("billionen", MoneyUnit.BILLION, 1000.0),
    ("trillions", MoneyUnit.BILLION, 1000.0),
    ("trillion", MoneyUnit.BILLION, 1000.0),
    ("milliards", MoneyUnit.BILLION, 1.0),
    ("milliard", MoneyUnit.BILLION, 1.0),
    ("millardos", MoneyUnit.BILLION, 1.0),
    ("millardo", MoneyUnit.BILLION, 1.0),
    ("billions", MoneyUnit.BILLION, 1.0),
    ("billion", MoneyUnit.BILLION, 1.0),
    ("millones", MoneyUnit.MILLION, 1.0),
    ("millon", MoneyUnit.MILLION, 1.0),
    ("milhoes", MoneyUnit.MILLION, 1.0),
    ("milhao", MoneyUnit.MILLION, 1.0),
    ("millionen", MoneyUnit.MILLION, 1.0),
    ("millions", MoneyUnit.MILLION, 1.0),
    ("million", MoneyUnit.MILLION, 1.0),
    ("milioni", MoneyUnit.MILLION, 1.0),
    ("milione", MoneyUnit.MILLION, 1.0),
    ("mio", MoneyUnit.MILLION, 1.0),
    ("miles", MoneyUnit.THOUSAND, 1.0),
    ("milhares", MoneyUnit.THOUSAND, 1.0),
    ("thousands", MoneyUnit.THOUSAND, 1.0),
    ("thousand", MoneyUnit.THOUSAND, 1.0),
    ("tausend", MoneyUnit.THOUSAND, 1.0),
    ("mille", MoneyUnit.THOUSAND, 1.0),
    ("mil", MoneyUnit.THOUSAND, 1.0),
    ("bn", MoneyUnit.BILLION, 1.0),
    ("bln", MoneyUnit.BILLION, 1.0),
    ("mn", MoneyUnit.MILLION, 1.0),
)

#: Terms naming gross domestic product, in the languages the cue tables cover.
_GDP_TERMS: Final[tuple[str, ...]] = (
    "producto interno bruto",
    "produto interno bruto",
    "producto interior bruto",
    "gross domestic product",
    "produit interieur brut",
    "pib",
    "pbi",
    "gdp",
    "pil",
    "bip",
)

#: Cues that say what a figure *is*. The same amount can be a cost, a cap or a
#: penalty, and conflating those is a standard route to a false summary, so the
#: role is extracted rather than assumed.
_MONETARY_ROLE_CUES: Final[tuple[tuple[MonetaryRole, tuple[str, ...]], ...]] = (
    (
        MonetaryRole.PENALTY,
        ("multa", "multas", "penalty", "penalties", "fine of", "sancion pecuniaria"),
    ),
    (
        MonetaryRole.CAP,
        (
            "tope",
            "no podra exceder",
            "hasta un maximo",
            "maximo de",
            "cap of",
            "up to a maximum",
            "not exceed",
        ),
    ),
    (
        MonetaryRole.FLOOR,
        ("minimo de", "no inferior a", "at least", "floor of", "piso de", "no menos de"),
    ),
    (
        MonetaryRole.THRESHOLD,
        ("umbral", "threshold", "a partir de", "superior a", "in excess of", "exceeds"),
    ),
    (
        MonetaryRole.REVENUE,
        ("ingreso", "ingresos", "recaudacion", "revenue", "revenues", "receipts", "yield of"),
    ),
    (
        MonetaryRole.COST,
        ("costo", "coste", "costos", "cost of", "gasto", "gastos", "expenditure", "expense"),
    ),
    (
        MonetaryRole.ALLOCATION,
        (
            "se asigna",
            "asignacion",
            "asignan",
            "se destina",
            "destinan",
            "presupuesto de",
            "allocation of",
            "appropriat",
            "budget of",
        ),
    ),
    (
        MonetaryRole.TRANSFER,
        (
            "transferencia",
            "transferencias",
            "transfer of",
            "subsidio de",
            "subsidy of",
            "bono de",
            "grant of",
        ),
    ),
    (
        MonetaryRole.BENEFIT_AMOUNT,
        ("monto del beneficio", "prestacion de", "benefit of", "pension de", "allowance of"),
    ),
    (
        MonetaryRole.RATE_BASE,
        ("base imponible", "taxable base", "tax base", "base de calculo"),
    ),
    (
        MonetaryRole.BASELINE,
        ("linea base", "escenario base", "baseline"),
    ),
    (
        MonetaryRole.PROJECTION,
        ("proyeccion", "proyecta", "projected", "forecast of", "se proyecta"),
    ),
)

#: Cues marking a figure as a projection rather than a settled amount. A
#: projected number reported as a fact is one of the commonest ways a document's
#: own caution is stripped out in the retelling.
_ESTIMATE_CUES: Final[tuple[str, ...]] = (
    "estimad",
    "estimat",
    "se estima",
    "it is estimated",
    "proyect",
    "project",
    "aproximad",
    "approximat",
    "cerca de",
    "alrededor de",
    "around",
    "about",
    "se espera",
    "expected",
    "previst",
    "forecast",
)

#: Cues describing the basis on which a money figure is stated.
_BASIS_CUES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "constant",
        (
            "constante",
            "constantes",
            "constant prices",
            "en moneda de",
            "real terms",
            "terminos reales",
        ),
    ),
    ("nominal", ("nominal", "nominales", "corrientes", "current prices", "precios corrientes")),
    ("cumulative", ("acumulad", "cumulative", "en total", "en conjunto", "aggregate")),
    ("annual", ("anual", "anuales", "annually", "per year", "por ano", "al ano", "yearly")),
    ("monthly", ("mensual", "mensuales", "monthly", "per month", "al mes")),
)

#: Cues that make a nearby four-digit number a *reference year* for a figure
#: rather than an unrelated number. Without one, no year is recorded: an invented
#: reference year would make a nominal figure look like a real one.
_YEAR_CONTEXT_CUES: Final[tuple[str, ...]] = (
    "de ",
    "del ",
    "ano ",
    "anos ",
    "year ",
    "moneda de ",
    "precios de ",
    "prices",
    "constant",
    "constante",
    "fiscal",
    "ejercicio",
    "presupuesto",
    "budget",
    "para ",
    "for ",
    "en ",
    "in ",
)


def _longest_first(terms: Iterable[str]) -> list[str]:
    return sorted(set(terms), key=lambda term: (-len(term), term))


_SYMBOL_ALTERNATION: Final[str] = "|".join(
    re.escape(symbol) for symbol in _longest_first([*_CURRENCY_SYMBOLS, *_AMBIGUOUS_SYMBOLS])
)
_CODE_ALTERNATION: Final[str] = "|".join(_longest_first([*_ISO_CURRENCIES, *_UNITS_OF_ACCOUNT]))
_SCALE_ALTERNATION: Final[str] = "|".join(re.escape(term) for term, _unit, _factor in _SCALE_TERMS)
_CURRENCY_WORD_ALTERNATION: Final[str] = "|".join(
    re.escape(word) for word in _longest_first([*_CURRENCY_WORDS, *_AMBIGUOUS_CURRENCY_WORDS])
)

# Two coordinate systems meet here, and conflating them silently loses matches.
# Currency CODES and SYMBOLS are written in the document's own case ("EUR", "US$")
# and must be matched against the raw text. Scale words and currency NAMES carry
# accents and case ("millón", "dólares") and must be matched against the
# length-preserving folded text. So they get separate patterns applied to
# separate strings at the same offsets, rather than one pattern that would work
# for one family and quietly fail for the other.

#: A currency code or symbol immediately before a figure. Raw text.
_CURRENCY_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:(?P<code>\b(?:{_CODE_ALTERNATION})\b)|(?P<symbol>{_SYMBOL_ALTERNATION}))\s*$"
)

#: A scale word immediately after a figure. Folded text.
_SCALE_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(rf"[ ]*(?P<scale>{_SCALE_ALTERNATION})\b")

#: A currency code or symbol after a figure (and after any scale word). Raw text.
_CURRENCY_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    rf"[ ]*(?:de[l]?[ ]+|of[ ]+|in[ ]+|em[ ]+)?"
    rf"(?:(?P<code>\b(?:{_CODE_ALTERNATION})\b)|(?P<symbol>{_SYMBOL_ALTERNATION}))"
)

#: A currency name after a figure. Folded text.
_CURRENCY_WORD_RE: Final[re.Pattern[str]] = re.compile(
    rf"[ ]*(?:de[l]?[ ]+|of[ ]+|in[ ]+|em[ ]+)?(?P<word>\b(?:{_CURRENCY_WORD_ALTERNATION})\b)"
)

_GDP_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]*(?:%|por[ ]ciento|percent|per[ ]cent|puntos?)[ ]*"
    r"(?:de[l]?[ ]+|of[ ]+|do[ ]+)?"
    rf"(?:{'|'.join(re.escape(term) for term in _longest_first(_GDP_TERMS))})\b"
)

_PERCENT_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]*(?:%|(?:por[ ]ciento|porciento|per[ ]cent|percent|pour[ ]cent|prozent)\b)"
)
_PERCENT_POINT_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]*(?:puntos?[ ]porcentuales?|percentage[ ]points?|pontos?[ ]percentuais?"
    r"|p\.?[ ]?p\.?(?![a-z])|pp(?![a-z.]))"
)
_BASIS_POINT_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]*(?:puntos?[ ]base|basis[ ]points?|bps(?![a-z])|bp(?![a-z]))"
)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MoneyMatch:
    """A monetary figure with the context needed to interpret it.

    ``ambiguous_currency`` and ``ambiguous_number`` exist so that a caller can
    tell a figure Aleph read confidently from one it read on a convention. Both
    end up as extraction warnings rather than as silent values.
    """

    money: Money
    raw_text: str
    start: int
    end: int
    label: str
    role: MonetaryRole | None = None
    is_estimate: bool = False
    ambiguous_currency: bool = False
    ambiguous_number: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class QuantityMatch:
    """A non-monetary figure located in the text."""

    quantity: Quantity
    raw_text: str
    start: int
    end: int
    label: str = ""
    ambiguous_number: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DateMatch:
    """A calendar date, with an honest account of how much was actually written.

    ``precision`` distinguishes "August 2027" from "7 August 2027"; ``iso_date``
    is populated only at day precision, because completing a partial date with an
    invented day would fabricate the timeline that every later temporal check
    depends on.
    """

    raw_text: str
    start: int
    end: int
    year: int
    month: int | None = None
    day: int | None = None
    precision: DatePrecision = DatePrecision.DAY
    iso_date: str | None = None
    ambiguous_order: bool = False
    ambiguous_century: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DurationMatch:
    """A length of time, normalised to a named unit."""

    quantity: Quantity
    raw_text: str
    start: int
    end: int
    unit: str
    value: float
    is_business_time: bool = False
    """True for 'working days' and equivalents, where the calendar length differs."""


@dataclass(frozen=True, slots=True)
class DeadlineMatch:
    """A time bound attached to an obligation.

    Either an absolute date or a period relative to a trigger. Both forms are
    kept because a document usually gives one or the other, and converting a
    relative period to a date would require assuming when the trigger occurred.
    """

    raw_text: str
    start: int
    end: int
    cue: str
    date: DateMatch | None = None
    duration: DurationMatch | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class QuantityExtraction:
    """Everything numeric found in one passage, with overlaps already resolved."""

    convention: DecimalConvention
    money: tuple[MoneyMatch, ...] = ()
    percentages: tuple[QuantityMatch, ...] = ()
    counts: tuple[QuantityMatch, ...] = ()
    dates: tuple[DateMatch, ...] = ()
    durations: tuple[DurationMatch, ...] = ()
    deadlines: tuple[DeadlineMatch, ...] = ()

    @property
    def has_ambiguous_number(self) -> bool:
        return any(m.ambiguous_number for m in self.money) or any(
            q.ambiguous_number for q in (*self.percentages, *self.counts)
        )

    @property
    def has_ambiguous_currency(self) -> bool:
        return any(m.ambiguous_currency for m in self.money)

    @property
    def has_ambiguous_date(self) -> bool:
        return any(d.ambiguous_order or d.ambiguous_century for d in self.dates)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def extract_money(
    text: str,
    *,
    convention: DecimalConvention | None = None,
    default_currency: str | None = None,
    unit_of_account_currencies: Mapping[str, str] | None = None,
    window: int = 90,
) -> tuple[MoneyMatch, ...]:
    """Find monetary figures, refusing to invent a currency.

    A figure counts as money when a currency marker sits next to it — a symbol, a
    recognised ISO code, or a currency name — or when it is expressed as a share
    of GDP. A bare number with no marker is not money and is left to
    :func:`extract_counts`; treating every number in a budget document as a sum
    of money produces a great deal of confident nonsense.

    Args:
        text: The passage to scan.
        convention: Decimal convention. Inferred from ``text`` when omitted,
            though callers analysing a fragment should pass the convention
            detected over the whole document.
        default_currency: ISO code to use for a bare ambiguous symbol such as
            ``$``. Supply this from a jurisdiction registry; never from a guess
            about the document's contents. Without it such figures carry
            :data:`UNKNOWN_CURRENCY` and are flagged.
        unit_of_account_currencies: Registry mapping from an index-linked unit's
            label to an ISO code (for instance ``{"UF": "CLF"}``). Units not
            listed are returned by :func:`extract_counts` as ``index``
            quantities instead of being forced into a currency field.
        window: How far either side of a figure context cues are read.

    Returns:
        Matches in document order.
    """
    conv = convention or detect_decimal_convention(text)
    folded = fold_preserving_length(text)
    promotions = {key.upper(): value for key, value in (unit_of_account_currencies or {}).items()}
    results: list[MoneyMatch] = []

    for token in iter_number_tokens(text):
        left_raw = text[max(0, token.start - 24) : token.start]
        right_raw = text[token.end : token.end + 60]
        right_folded = folded[token.end : token.end + 60]

        currency: str | None = None
        ambiguous_currency = False
        unit = MoneyUnit.UNIT
        factor = 1.0
        end = token.end
        declined = False

        gdp = _GDP_SUFFIX_RE.match(right_folded)
        if gdp:
            currency = default_currency or UNKNOWN_CURRENCY
            ambiguous_currency = default_currency is None
            unit = MoneyUnit.PERCENT_OF_GDP
            end = token.end + gdp.end()
        else:
            prefix = _CURRENCY_PREFIX_RE.search(left_raw)
            if prefix:
                currency, ambiguous_currency, declined = _resolve_currency_marker(
                    prefix, left_raw, promotions, default_currency
                )

            scale = _SCALE_SUFFIX_RE.match(right_folded)
            after_scale = 0
            if scale:
                unit, factor = _SCALE_LOOKUP[scale.group("scale")]
                after_scale = scale.end()
                end = token.end + after_scale

            if currency is None and not declined:
                marker = _CURRENCY_MARKER_RE.match(right_raw, after_scale)
                if marker:
                    currency, ambiguous_currency, declined = _resolve_currency_marker(
                        marker, right_raw, promotions, default_currency
                    )
                    if currency is not None:
                        end = max(end, token.end + marker.end())
            if currency is None and not declined:
                word = _CURRENCY_WORD_RE.match(right_folded, after_scale)
                if word:
                    currency, ambiguous_currency, declined = _resolve_currency_marker(
                        word, right_folded, promotions, default_currency
                    )
                    if currency is not None:
                        end = max(end, token.end + word.end())
            if currency is None:
                # Either no currency marker at all, or a unit of account that no
                # registry promoted. Both belong to extract_counts, not here.
                continue

        parsed = parse_number(token.raw_text, conv)
        amount = parsed.value * factor
        results.append(
            MoneyMatch(
                money=Money(
                    amount=amount,
                    currency=currency,
                    unit=unit,
                    year=_reference_year(folded, token.start, end, window),
                    basis=_basis(folded, token.start, end, window),
                ),
                raw_text=text[token.start : end],
                start=token.start,
                end=end,
                label=_label_for(text, token.start),
                role=_role_for(folded, token.start, end, window),
                is_estimate=_matches_any(folded, token.start, end, window, _ESTIMATE_CUES),
                ambiguous_currency=ambiguous_currency,
                ambiguous_number=parsed.ambiguous,
                note=parsed.note,
            )
        )
    return tuple(results)


_SCALE_LOOKUP: Final[dict[str, tuple[MoneyUnit, float]]] = {
    term: (unit, factor) for term, unit, factor in _SCALE_TERMS
}


def _resolve_currency_marker(
    match: re.Match[str],
    segment: str,
    promotions: Mapping[str, str],
    default_currency: str | None,
) -> tuple[str | None, bool, bool]:
    """Turn a matched currency marker into an ISO code, or decline to.

    Returns ``(currency, ambiguous, declined)``. ``declined`` is set for a unit
    of account that no registry promoted to a currency: that figure is a real
    amount but not money, so the caller must stop looking for a currency rather
    than fall through to a weaker marker and mislabel it.
    """
    groups = match.groupdict()

    code = groups.get("code")
    if code:
        upper = code.upper()
        if upper in promotions:
            return promotions[upper], False, False
        if upper in _UNITS_OF_ACCOUNT:
            return None, False, True
        return upper, False, False

    if groups.get("symbol") is not None:
        literal = segment[match.start("symbol") : match.end("symbol")]
        for candidate in (literal, literal.upper()):
            if candidate in _CURRENCY_SYMBOLS:
                return _CURRENCY_SYMBOLS[candidate], False, False
        return (default_currency or UNKNOWN_CURRENCY), default_currency is None, False

    word = groups.get("word")
    if word:
        if word in _CURRENCY_WORDS:
            return _CURRENCY_WORDS[word], False, False
        if word in _AMBIGUOUS_CURRENCY_WORDS:
            return (default_currency or UNKNOWN_CURRENCY), default_currency is None, False
    return None, False, False


def _reference_year(folded: str, start: int, end: int, window: int) -> int | None:
    """Find a reference year stated near a figure, or return ``None``.

    Only a year introduced by an explicit cue counts. A four-digit number that
    happens to sit nearby is not a price base, and recording it as one would turn
    a nominal figure into a spurious real one.
    """
    segment = folded[max(0, start - window) : min(len(folded), end + window)]
    for match in _YEAR_RE.finditer(segment):
        lead = segment[max(0, match.start() - 22) : match.start()]
        if any(cue in lead for cue in _YEAR_CONTEXT_CUES):
            return int(match.group(1))
    return None


def _basis(folded: str, start: int, end: int, window: int) -> str | None:
    segment = folded[max(0, start - window) : min(len(folded), end + window)]
    for basis, cues in _BASIS_CUES:
        if any(cue in segment for cue in cues):
            return basis
    return None


def _role_for(folded: str, start: int, end: int, window: int) -> MonetaryRole | None:
    """Pick the role whose cue sits closest before the figure.

    Proximity beats table order: in "the cost is capped at X" both cues are
    present, and the one nearer the number is the one that describes it.
    """
    left = folded[max(0, start - window) : start]
    right = folded[end : min(len(folded), end + window)]
    best: tuple[int, MonetaryRole] | None = None
    for role, cues in _MONETARY_ROLE_CUES:
        for cue in cues:
            position = left.rfind(cue)
            if position != -1:
                distance = len(left) - position
                if best is None or distance < best[0]:
                    best = (distance, role)
            position = right.find(cue)
            if position != -1:
                distance = position + len(left) + 1
                if best is None or distance < best[0]:
                    best = (distance, role)
    return best[1] if best else None


def _matches_any(folded: str, start: int, end: int, window: int, cues: Sequence[str]) -> bool:
    segment = folded[max(0, start - window) : min(len(folded), end + window)]
    return any(cue in segment for cue in cues)


def _label_for(text: str, start: int, *, max_words: int = 9) -> str:
    """A short human-readable label: the words immediately before the figure.

    Deliberately literal. A generated description would be an interpretation of
    the passage, and the whole point of a label here is to help a reader find the
    figure in the original.
    """
    lead = text[max(0, start - 140) : start]
    for boundary in (". ", ";", ":", "\n"):
        cut = lead.rfind(boundary)
        if cut != -1:
            lead = lead[cut + len(boundary) :]
    words = lead.split()
    return " ".join(words[-max_words:]).strip() or "unlabelled figure"


# ---------------------------------------------------------------------------
# Percentages and counts
# ---------------------------------------------------------------------------


def extract_percentages(
    text: str,
    *,
    convention: DecimalConvention | None = None,
) -> tuple[QuantityMatch, ...]:
    """Find percentages, percentage points and basis points, kept distinct.

    The distinction is not pedantry. "The rate rises by 2%" and "the rate rises by
    2 percentage points" describe different changes to a 20% rate — one gives
    20.4%, the other 22% — and treating them as the same figure is a standard way
    for a factual claim to become false in the retelling. Basis points are
    converted to percentage points (1 bp = 0.01 pp) so magnitudes are comparable.
    """
    conv = convention or detect_decimal_convention(text)
    folded = fold_preserving_length(text)
    results: list[QuantityMatch] = []

    for token in iter_number_tokens(text):
        tail = folded[token.end : token.end + 30]
        kind: QuantityKind
        scale = 1.0
        unit: str | None

        if match := _PERCENT_POINT_SUFFIX_RE.match(tail):
            kind, unit = QuantityKind.PERCENTAGE_POINT, "percentage_point"
        elif match := _BASIS_POINT_SUFFIX_RE.match(tail):
            kind, unit, scale = QuantityKind.PERCENTAGE_POINT, "percentage_point", 0.01
        elif match := _PERCENT_SUFFIX_RE.match(tail):
            kind, unit = QuantityKind.PERCENTAGE, "percent"
        else:
            continue

        end = token.end + match.end()
        parsed = parse_number(token.raw_text, conv)
        raw = text[token.start : end]
        results.append(
            QuantityMatch(
                quantity=Quantity(
                    value=parsed.value * scale,
                    kind=kind,
                    unit=unit,
                    raw_text=raw,
                ),
                raw_text=raw,
                start=token.start,
                end=end,
                label=_label_for(text, token.start),
                ambiguous_number=parsed.ambiguous,
                note=parsed.note,
            )
        )
    return tuple(results)


#: Units of account rendered as index quantities when no registry promoted them
#: to a currency, plus generic countable units worth recognising.
_INDEX_UNIT_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?P<unit>{'|'.join(_longest_first(_UNITS_OF_ACCOUNT))})\b"
)


def extract_counts(
    text: str,
    *,
    convention: DecimalConvention | None = None,
    exclude: Sequence[tuple[int, int]] = (),
    unit_of_account_currencies: Mapping[str, str] | None = None,
) -> tuple[QuantityMatch, ...]:
    """Find plain counts and index-linked amounts not claimed by another extractor.

    ``exclude`` carries the ranges already consumed by money, percentage, date
    and duration extraction, so one figure never appears twice under two
    readings. Bare four-digit years are skipped: a year is a date, and listing it
    as a count of 2027 things is noise that makes the real counts harder to find.
    """
    conv = convention or detect_decimal_convention(text)
    promoted = {key.upper() for key in (unit_of_account_currencies or {})}
    blocked = tuple(exclude)
    results: list[QuantityMatch] = []

    for token in iter_number_tokens(text):
        if _overlaps(token.start, token.end, blocked):
            continue
        raw = token.raw_text
        if _YEAR_RE.fullmatch(raw):
            continue

        parsed = parse_number(raw, conv)
        suffix = text[token.end : token.end + 12]
        prefix = text[max(0, token.start - 10) : token.start]
        # Units of account sit on either side of the figure ("500 UF", "UF 500").
        after = _INDEX_UNIT_RE.search(suffix)
        before = _INDEX_UNIT_RE.search(prefix) if after is None else None
        unit_match = after or before

        if unit_match and unit_match.group("unit").upper() not in promoted:
            unit_label = unit_match.group("unit").upper()
            end = token.end + after.end() if after is not None else token.end
            results.append(
                QuantityMatch(
                    quantity=Quantity(
                        value=parsed.value,
                        kind=QuantityKind.INDEX,
                        unit=unit_label,
                        raw_text=text[token.start : end],
                    ),
                    raw_text=text[token.start : end],
                    start=token.start,
                    end=end,
                    label=_label_for(text, token.start),
                    ambiguous_number=parsed.ambiguous,
                    note=(
                        f"{unit_label} is an index-linked unit of account, not a "
                        "currency; no ISO code was supplied for it, so it is recorded "
                        "as an index quantity rather than as money"
                    ),
                )
            )
            continue

        results.append(
            QuantityMatch(
                quantity=Quantity(
                    value=parsed.value,
                    kind=QuantityKind.COUNT,
                    unit=None,
                    raw_text=raw,
                ),
                raw_text=raw,
                start=token.start,
                end=token.end,
                label=_label_for(text, token.start),
                ambiguous_number=parsed.ambiguous,
                note=parsed.note,
            )
        )
    return tuple(results)


def extract_years(text: str) -> tuple[int, ...]:
    """Every plausible four-digit year in the passage, de-duplicated and sorted.

    Used to populate fiscal-year lists. Deliberately unfiltered by context: this
    answers "which years does this passage mention", not "which year is this
    figure denominated in", which is :func:`extract_money`'s job.
    """
    return tuple(sorted({int(match.group(1)) for match in _YEAR_RE.finditer(text)}))


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

#: Month names and common abbreviations, accent-folded and lowercased. Calendar
#: months are linguistic, not jurisdictional, so this table is safe to grow.
_MONTH_NAMES: Final[dict[str, int]] = {}


def _register_months(names: Sequence[Sequence[str]]) -> None:
    for index, variants in enumerate(names, start=1):
        for variant in variants:
            _MONTH_NAMES[fold_preserving_length(variant)] = index


_register_months(
    [
        ("january", "jan", "enero", "ene", "janeiro", "janvier", "janv", "gennaio", "januar"),
        ("february", "feb", "febrero", "fev", "fevereiro", "fevrier", "febbraio", "februar"),
        ("march", "mar", "marzo", "marco", "mars", "marzo", "maerz", "marz"),
        ("april", "apr", "abril", "abr", "avril", "aprile"),
        ("may", "mayo", "maio", "mai", "maggio"),
        ("june", "jun", "junio", "junho", "juin", "giugno", "juni"),
        ("july", "jul", "julio", "julho", "juillet", "juil", "luglio", "juli"),
        ("august", "aug", "agosto", "ago", "aout", "august"),
        ("september", "sep", "sept", "septiembre", "setembro", "septembre", "settembre"),
        ("october", "oct", "octubre", "outubro", "octobre", "ottobre", "oktober", "out"),
        ("november", "nov", "noviembre", "novembro", "novembre", "novembre"),
        (
            "december",
            "dec",
            "diciembre",
            "dic",
            "dezembro",
            "decembre",
            "dicembre",
            "dezember",
            "dez",
        ),
    ]
)

_MONTH_ALTERNATION: Final[str] = "|".join(_longest_first(_MONTH_NAMES))

_ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NUMERIC_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?!\d)"
)
_DMY_DATE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:º|°|ª|st|nd|rd|th)?[ ]*(?:de[ ]+|of[ ]+)?"
    rf"(?P<month>{_MONTH_ALTERNATION})\b"
    r"(?:[ ]*(?:,|de[l]?|of|do)?[ ]*(?<!\d)(\d{4})(?!\d))?"
)
_MDY_DATE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?P<month>{_MONTH_ALTERNATION})\b[ ]+(\d{{1,2}})(?:st|nd|rd|th)?[ ]*,?[ ]*(?<!\d)(\d{{4}})(?!\d)"
)
_MY_DATE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?P<month>{_MONTH_ALTERNATION})\b[ ]*(?:de[l]?[ ]+|of[ ]+|do[ ]+)?(?<!\d)(\d{{4}})(?!\d)"
)


def extract_dates(
    text: str,
    *,
    date_order: DateOrder = DateOrder.DAY_FIRST,
) -> tuple[DateMatch, ...]:
    """Find calendar dates, recording what remained undecidable.

    ``03/04/2027`` is 3 April or 4 March depending on convention, and nothing in
    the string settles it. Where one component exceeds 12 the order is determined
    by the data; otherwise ``date_order`` decides and the result carries
    ``ambiguous_order``. Two-digit years are expanded on the POSIX rule
    (69–99 → 1900s, 00–68 → 2000s) and flagged.

    Month-only and year-only readings are returned with the matching
    :class:`DatePrecision` and a null ``iso_date``, because inventing a day to
    complete a partial date fabricates the timeline downstream checks rely on.
    """
    folded = fold_preserving_length(text)
    found: list[DateMatch] = []
    taken: list[tuple[int, int]] = []

    for match in _ISO_DATE_RE.finditer(text):
        year, month, day = (int(group) for group in match.groups())
        found.append(_build_date(text, match.start(), match.end(), year, month, day))
        taken.append((match.start(), match.end()))

    for pattern, order in ((_MDY_DATE_RE, "mdy"), (_DMY_DATE_RE, "dmy")):
        for match in pattern.finditer(folded):
            if _overlaps(match.start(), match.end(), taken):
                continue
            month = _MONTH_NAMES[match.group("month")]
            if order == "mdy":
                day, year = int(match.group(2)), int(match.group(3))
            else:
                day = int(match.group(1))
                year_group = match.group(3)
                if year_group is None:
                    continue
                year = int(year_group)
            found.append(_build_date(text, match.start(), match.end(), year, month, day))
            taken.append((match.start(), match.end()))

    for match in _MY_DATE_RE.finditer(folded):
        if _overlaps(match.start(), match.end(), taken):
            continue
        month = _MONTH_NAMES[match.group("month")]
        found.append(
            _build_date(
                text,
                match.start(),
                match.end(),
                int(match.group(2)),
                month,
                None,
                precision=DatePrecision.MONTH,
            )
        )
        taken.append((match.start(), match.end()))

    for match in _NUMERIC_DATE_RE.finditer(text):
        if _overlaps(match.start(), match.end(), taken):
            continue
        first, second, raw_year = (int(group) for group in match.groups())
        ambiguous_century = len(match.group(3)) == 2
        year = (
            raw_year
            if not ambiguous_century
            else (2000 + raw_year if raw_year <= 68 else 1900 + raw_year)
        )
        ambiguous_order = False
        if first > 12 >= second:
            day, month = first, second
        elif second > 12 >= first:
            day, month = second, first
        elif date_order is DateOrder.MONTH_FIRST:
            month, day, ambiguous_order = first, second, True
        else:
            day, month, ambiguous_order = first, second, date_order is DateOrder.UNKNOWN or True
        candidate = _build_date(text, match.start(), match.end(), year, month, day)
        if candidate.iso_date is None and day != month:
            # The chosen order produced an impossible date. Try the other one:
            # the document is more likely to have used the convention that yields
            # a real calendar date than to have written a nonexistent one.
            swapped = _build_date(text, match.start(), match.end(), year, day, month)
            if swapped.iso_date is not None:
                candidate = swapped
                ambiguous_order = True
        if candidate.iso_date is None:
            continue
        found.append(
            DateMatch(
                raw_text=candidate.raw_text,
                start=candidate.start,
                end=candidate.end,
                year=candidate.year,
                month=candidate.month,
                day=candidate.day,
                precision=candidate.precision,
                iso_date=candidate.iso_date,
                ambiguous_order=ambiguous_order,
                ambiguous_century=ambiguous_century,
                note=(
                    "day and month could not be told apart from the text; read as "
                    f"{date_order.value}"
                )
                if ambiguous_order
                else None,
            )
        )
        taken.append((match.start(), match.end()))

    return tuple(sorted(found, key=lambda item: item.start))


def _build_date(
    text: str,
    start: int,
    end: int,
    year: int,
    month: int | None,
    day: int | None,
    *,
    precision: DatePrecision = DatePrecision.DAY,
) -> DateMatch:
    """Validate a parsed date and render it, or record that it was impossible."""
    iso: str | None = None
    note: str | None = None
    if precision is DatePrecision.DAY and month is not None and day is not None:
        try:
            iso = _dt.date(year, month, day).isoformat()
        except ValueError:
            note = f"'{text[start:end]}' is not a valid calendar date and was not resolved"
            precision = DatePrecision.MONTH if 1 <= month <= 12 else DatePrecision.YEAR
            day = None
    return DateMatch(
        raw_text=text[start:end],
        start=start,
        end=end,
        year=year,
        month=month,
        day=day,
        precision=precision,
        iso_date=iso,
        note=note,
    )


# ---------------------------------------------------------------------------
# Durations and deadlines
# ---------------------------------------------------------------------------

#: Time units, folded. The canonical label on the right is what ends up in
#: ``Quantity.unit``, so a duration written in any covered language compares with
#: one written in any other.
_DURATION_UNITS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (
        ("dias habiles", "dias utiles", "business days", "working days", "jours ouvrables"),
        "business_days",
    ),
    (("dias corridos", "calendar days", "dias calendario"), "days"),
    (("dias", "dia", "days", "day", "jours", "jour", "giorni", "tage"), "days"),
    (("semanas", "semana", "weeks", "week", "semaines", "wochen"), "weeks"),
    (("meses", "mes", "months", "month", "mois", "mesi", "monate"), "months"),
    (("trimestres", "trimestre", "quarters", "quarter"), "quarters"),
    (("anos", "ano", "years", "year", "ans", "annees", "anni", "jahre"), "years"),
    (("horas", "hora", "hours", "hour", "heures", "ore", "stunden"), "hours"),
)

#: Small number words, for "within thirty days". Deliberately limited: a general
#: number-word parser would add a lot of surface area for very little coverage,
#: and a missed word costs a duration, not a wrong one.
_NUMBER_WORDS: Final[dict[str, int]] = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "one": 1,
    "dos": 2,
    "two": 2,
    "duas": 2,
    "tres": 3,
    "three": 3,
    "cuatro": 4,
    "four": 4,
    "quatro": 4,
    "cinco": 5,
    "five": 5,
    "seis": 6,
    "six": 6,
    "siete": 7,
    "seven": 7,
    "sete": 7,
    "ocho": 8,
    "eight": 8,
    "oito": 8,
    "nueve": 9,
    "nine": 9,
    "nove": 9,
    "diez": 10,
    "ten": 10,
    "dez": 10,
    "once": 11,
    "eleven": 11,
    "doce": 12,
    "twelve": 12,
    "doze": 12,
    "quince": 15,
    "fifteen": 15,
    "quinze": 15,
    "dieciocho": 18,
    "eighteen": 18,
    "veinte": 20,
    "twenty": 20,
    "vinte": 20,
    "treinta": 30,
    "thirty": 30,
    "trinta": 30,
    "sesenta": 60,
    "sixty": 60,
    "sessenta": 60,
    "noventa": 90,
    "ninety": 90,
    "cien": 100,
    "ciento": 100,
    "hundred": 100,
    "cem": 100,
    "ciento veinte": 120,
    "cientoveinte": 120,
    "ciento ochenta": 180,
}

_DURATION_UNIT_ALTERNATION: Final[str] = "|".join(
    _longest_first(term for terms, _label in _DURATION_UNITS for term in terms)
)
_NUMBER_WORD_ALTERNATION: Final[str] = "|".join(_longest_first(_NUMBER_WORDS))

_DURATION_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?<![\w])(?:(?P<digits>\d{{1,4}})|(?P<word>{_NUMBER_WORD_ALTERNATION}))"
    rf"[ ]+(?:\([^)]{{0,20}}\)[ ]*)?(?P<unit>{_DURATION_UNIT_ALTERNATION})\b"
)

_DURATION_UNIT_LOOKUP: Final[dict[str, str]] = {
    term: label for terms, label in _DURATION_UNITS for term in terms
}


def extract_durations(text: str) -> tuple[DurationMatch, ...]:
    """Find lengths of time, normalising the unit and keeping working days apart.

    "Within 30 working days" and "within 30 days" are different obligations, and
    a system that silently equated them would report a deadline as met or missed
    on the wrong date. The distinction is preserved in the unit rather than
    resolved into a calendar figure, which would require a holiday calendar Aleph
    does not have.
    """
    folded = fold_preserving_length(text)
    results: list[DurationMatch] = []
    for match in _DURATION_RE.finditer(folded):
        digits, word = match.group("digits"), match.group("word")
        value = float(digits) if digits else float(_NUMBER_WORDS[word])
        unit = _DURATION_UNIT_LOOKUP[match.group("unit")]
        raw = text[match.start() : match.end()]
        results.append(
            DurationMatch(
                quantity=Quantity(
                    value=value,
                    kind=QuantityKind.DURATION,
                    unit=unit,
                    raw_text=raw,
                ),
                raw_text=raw,
                start=match.start(),
                end=match.end(),
                unit=unit,
                value=value,
                is_business_time=unit == "business_days",
            )
        )
    return tuple(results)


#: Phrases that introduce a time bound. Multi-language, and data rather than
#: literals scattered through the code, so that adding a language is one edit.
_DEADLINE_CUES: Final[tuple[str, ...]] = (
    "a mas tardar",
    "dentro del plazo de",
    "dentro de un plazo de",
    "en un plazo maximo de",
    "en un plazo de",
    "dentro de los",
    "dentro de",
    "antes del",
    "antes de",
    "hasta el",
    "plazo de",
    "no mas alla de",
    "a contar de",
    "no later than",
    "not later than",
    "on or before",
    "no fewer than",
    "within",
    "by no later than",
    "deadline",
    "due date",
    "due by",
    "shall be completed by",
    "prazo de",
    "ate o",
    "au plus tard",
    "dans un delai de",
)

_DEADLINE_CUE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:{'|'.join(re.escape(cue) for cue in _longest_first(_DEADLINE_CUES))})\b"
)

#: How far after a cue a date or duration may sit and still be its object.
_DEADLINE_REACH: Final[int] = 90


def extract_deadlines(
    text: str,
    *,
    dates: Sequence[DateMatch] | None = None,
    durations: Sequence[DurationMatch] | None = None,
    date_order: DateOrder = DateOrder.DAY_FIRST,
) -> tuple[DeadlineMatch, ...]:
    """Attach each time-bound cue to the date or period it governs.

    A cue with nothing after it is discarded rather than recorded as an
    unspecified deadline: "within" on its own is not a time bound, and a deadline
    list padded with them would make the real ones harder to see.
    """
    folded = fold_preserving_length(text)
    all_dates = (
        list(dates) if dates is not None else list(extract_dates(text, date_order=date_order))
    )
    all_durations = list(durations) if durations is not None else list(extract_durations(text))
    results: list[DeadlineMatch] = []

    for cue in _DEADLINE_CUE_RE.finditer(folded):
        reach = cue.end() + _DEADLINE_REACH
        date = next((d for d in all_dates if cue.end() <= d.start < reach), None)
        duration = next((d for d in all_durations if cue.end() <= d.start < reach), None)
        if date is None and duration is None:
            continue
        if date is not None and duration is not None:
            # Whichever the cue reaches first is the one it governs.
            if duration.start < date.start:
                date = None
            else:
                duration = None
        end = max(cue.end(), date.end if date else 0, duration.end if duration else 0)
        results.append(
            DeadlineMatch(
                raw_text=text[cue.start() : end],
                start=cue.start(),
                end=end,
                cue=cue.group(0),
                date=date,
                duration=duration,
                label=_label_for(text, cue.start()),
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# Combined pass
# ---------------------------------------------------------------------------


def extract_all(
    text: str,
    *,
    convention: DecimalConvention | None = None,
    date_order: DateOrder = DateOrder.DAY_FIRST,
    default_currency: str | None = None,
    unit_of_account_currencies: Mapping[str, str] | None = None,
    include_counts: bool = True,
) -> QuantityExtraction:
    """Run every extractor over one passage, resolving overlaps by specificity.

    Order matters and encodes a precedence: a figure that is money is not also a
    count, a figure that is a percentage is not also a bare number, and a year
    inside a date is not a quantity. Each extractor claims its ranges and the
    next sees what is left, so the same characters never appear twice under two
    incompatible readings.
    """
    conv = convention or detect_decimal_convention(text)
    money = extract_money(
        text,
        convention=conv,
        default_currency=default_currency,
        unit_of_account_currencies=unit_of_account_currencies,
    )
    claimed: list[tuple[int, int]] = [(m.start, m.end) for m in money]

    percentages = tuple(
        match
        for match in extract_percentages(text, convention=conv)
        if not _overlaps(match.start, match.end, claimed)
    )
    claimed.extend((match.start, match.end) for match in percentages)

    dates = extract_dates(text, date_order=date_order)
    claimed.extend((date.start, date.end) for date in dates)

    durations = tuple(
        match for match in extract_durations(text) if not _overlaps(match.start, match.end, claimed)
    )
    claimed.extend((match.start, match.end) for match in durations)

    deadlines = extract_deadlines(text, dates=dates, durations=durations, date_order=date_order)

    counts: tuple[QuantityMatch, ...] = ()
    if include_counts:
        counts = extract_counts(
            text,
            convention=conv,
            exclude=claimed,
            unit_of_account_currencies=unit_of_account_currencies,
        )

    return QuantityExtraction(
        convention=conv,
        money=money,
        percentages=percentages,
        counts=counts,
        dates=dates,
        durations=durations,
        deadlines=deadlines,
    )


def _overlaps(start: int, end: int, ranges: Sequence[tuple[int, int]]) -> bool:
    """Whether ``[start, end)`` intersects any claimed range."""
    return any(start < other_end and other_start < end for other_start, other_end in ranges)
