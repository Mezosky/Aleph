"""Generate the bundled SYNTHETIC sample dataset the Aleph frontend renders.

Everything this script emits is invented. It describes no real statement by any
real person, party or publication. The outlets are fictional (Diario Meridiano,
El Contrapunto, Canal Sur Noticias, Boletín Económico, Radio Andes) and every
speaker is a generic institutional ROLE, never a named individual.

The one real-world fact recorded here is the URL of the target document
(``https://www.dipres.gob.cl/604/articles-409825_doc_pdf.pdf``). It is stored as
``document.source.url`` because registering which file an analysis is *meant* to
be about is a fact. The file was never downloaded: ``retrieval_method`` and
``extraction_method`` are both ``fixture`` and an ``extraction_warnings`` entry
of severity ``error`` states in so many words that the analysed text was NOT
extracted from that PDF.

The script is deterministic: no randomness, no clock reads. ``GENERATED_AT`` is a
fixed constant, so running it twice produces byte-identical output.

Usage::

    /home/ignacio/Aleph/.venv/bin/python scripts/generate_sample_data.py
    /home/ignacio/Aleph/.venv/bin/python scripts/generate_sample_data.py --check

``--check`` validates the files already on disk without rewriting them.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Paths and fixed instants
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
OUT_DIR = REPO_ROOT / "frontend" / "public" / "data"

SCHEMA_VERSION = "1.0.0"
DATA_STATUS = "synthetic"

#: Fixed generation instant. Never read from the clock: the output must be
#: reproducible byte-for-byte so a diff means a content change, not a re-run.
GENERATED_AT = "2026-08-07T12:00:00Z"
RETRIEVED_AT = "2026-08-07T09:00:00Z"

DOC_SLUG = "18216-05"
DOC_ID = f"doc:{DOC_SLUG}"

#: The real location of the target document. Recorded as configuration only —
#: it was never fetched, and none of the text below came from it.
TARGET_DOCUMENT_URL = "https://www.dipres.gob.cl/604/articles-409825_doc_pdf.pdf"

PIPELINE_VERSION = "aleph-pipeline/0.1.0"
EXTRACTOR = "aleph-fixture/0.1.0"
EVALUATOR_VERSION = "aleph-blind-evaluator/0.1.0-mock"
REDACTION_VERSION = "aleph-redactor/0.1.0"

SYNTHETIC_NOTICE = (
    "Conjunto de datos SINTETICO. Ningun texto, cifra, cita, medio ni declaracion "
    "de este conjunto corresponde a una persona, un organismo o una publicacion "
    "real. Fue generado para demostrar la interfaz de Aleph y no constituye un "
    "analisis de ninguna reforma real."
)

# Fictional outlets. Ids are prefixed `demo-` so they can never be confused with
# the real source registry (aleph/news/sources.yaml), which lists real outlets.
OUTLETS: dict[str, dict[str, str]] = {
    "meridiano": {"id": "src:demo-diario-meridiano", "name": "Diario Meridiano"},
    "contrapunto": {"id": "src:demo-el-contrapunto", "name": "El Contrapunto"},
    "canalsur": {"id": "src:demo-canal-sur-noticias", "name": "Canal Sur Noticias"},
    "boletin": {"id": "src:demo-boletin-economico", "name": "Boletín Económico"},
    "andes": {"id": "src:demo-radio-andes", "name": "Radio Andes"},
}

# Generic speaker ROLES. Never a person, never a party.
ROLE_TREASURY = "vocería de Hacienda"
ROLE_BUSINESS = "economista de una federación empresarial"
ROLE_MUNICIPAL = "presidencia de la asociación de municipios"
ROLE_UNION = "analista de una confederación sindical"
ROLE_OPPOSITION = "diputado/a de oposición"


# --------------------------------------------------------------------------- #
# Small builders for the shared primitives in schemas/common.json
# --------------------------------------------------------------------------- #


def money(
    amount: float,
    unit: str = "million",
    year: int | None = 2026,
    basis: str | None = "nominal",
    currency: str = "CLP",
) -> dict[str, Any]:
    """A structured monetary amount. Aleph never stores a bare number for money."""
    return {
        "amount": amount,
        "currency": currency,
        "unit": unit,
        "year": year,
        "basis": basis,
    }


def quantity(value: float, kind: str, raw_text: str, unit: str | None = None) -> dict[str, Any]:
    """A non-monetary figure with its verbatim source text preserved."""
    return {"value": value, "kind": kind, "unit": unit, "raw_text": raw_text}


def span(
    text: str,
    page: int | None = None,
    section_id: str | None = None,
    char_start: int | None = None,
) -> dict[str, Any]:
    """A located, verbatim passage. Every Aleph assertion must be quotable."""
    return {
        "page": page,
        "section_id": section_id,
        "char_start": char_start,
        "char_end": None if char_start is None else char_start + len(text),
        "text": text,
    }


def conf(
    evidence: float,
    model: float | None = None,
    basis: list[tuple[str, str, str]] | None = None,
    limiting: str | None = None,
) -> dict[str, Any]:
    """Evidence confidence leads; model confidence is a subordinate diagnostic."""
    return {
        "evidence_confidence": evidence,
        "model_confidence": model,
        "basis": [{"factor": f, "effect": e, "note": n} for f, e, n in (basis or [])],
        "limiting_factor": limiting,
    }


def comp(
    label: str,
    direction: str,
    weight: float,
    evidence_refs: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """One inspectable contributor to a composite score."""
    return {
        "label": label,
        "direction": direction,
        "weight": weight,
        "evidence_refs": evidence_refs or [],
        "note": note,
    }


def unc(statement: str, kind: str, resolvable_by: str | None = None) -> dict[str, Any]:
    """An explicit statement of what remains unresolved."""
    return {"statement": statement, "kind": kind, "resolvable_by": resolvable_by}


def source_ref(
    ident: str,
    title: str,
    tier: str,
    publisher: str | None = None,
    published_at: str | None = None,
    independence: str = "unknown",
    url: str | None = None,
) -> dict[str, Any]:
    """A pointer to an external source. Deliberately carries no prestige field."""
    return {
        "id": ident,
        "title": title,
        "url": url,
        "publisher": publisher,
        "published_at": published_at,
        "tier": tier,
        "independence": independence,
        "language": "es-CL",
    }


def relative_time_es(published_at: str, now: str = GENERATED_AT) -> str:
    """Deterministic es-CL relative timestamp, computed from the fixed instants."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    then = datetime.strptime(published_at, fmt).replace(tzinfo=UTC)
    ref = datetime.strptime(now, fmt).replace(tzinfo=UTC)
    minutes = int((ref - then).total_seconds() // 60)
    if minutes < 60:
        return f"hace {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"hace {hours} h" if hours != 1 else "hace 1 h"
    days = hours // 24
    return f"hace {days} días" if days != 1 else "hace 1 día"


def pid(n: int) -> str:
    """Provision id for this document."""
    return f"prov:{DOC_SLUG}:{n}"


def ppid(n: int) -> str:
    """Proposition id for this document."""
    return f"prop:{DOC_SLUG}:{n}"


# --------------------------------------------------------------------------- #
# Warm phase 1 — the document
# --------------------------------------------------------------------------- #

# One source of truth for the ten provisions. `document.provisions[]` and the
# bundle's denormalised `provisions[]` are both projected from this list, so the
# two can never drift apart.
PROVISIONS: list[dict[str, Any]] = [
    {
        "n": 1,
        "ref_label": "Artículo 3°",
        "title": "Sobretasa transitoria a las utilidades",
        "section_id": "sec:2.1",
        "page": 3,
        "char_start": 1840,
        "type": "tax",
        "mechanism_type": "tax_change",
        "text": (
            "Artículo 3°.— Establécese, por los años tributarios 2027 a 2031, una sobretasa "
            "de dos puntos porcentuales sobre la base imponible del impuesto de primera "
            "categoría de los contribuyentes cuyos ingresos brutos anuales del ejercicio "
            "anterior hayan superado las 100.000 unidades de fomento."
        ),
        "summary": (
            "Crea una sobretasa transitoria de 2 puntos porcentuales sobre las utilidades "
            "de empresas con ingresos brutos anuales superiores a 100.000 UF, vigente entre "
            "los años tributarios 2027 y 2031."
        ),
        "mechanism": (
            "Aumenta la tasa efectiva del impuesto a las utilidades del tramo de mayores "
            "ingresos brutos; el efecto recaudatorio depende de la base imponible declarada "
            "y de la respuesta de inversión, que el texto no modela."
        ),
        "effective_date": "2027-01-01",
        "sunset_date": "2031-12-31",
        "effective_condition": None,
        "conditions": ["ingresos brutos anuales del ejercicio anterior superiores a 100.000 UF"],
        "exceptions": [
            "no se aplica a contribuyentes acogidos al régimen de transparencia tributaria"
        ],
        "implementing_body": "administración tributaria",
        "impact_axes": ["households_vs_firms", "redistribution_vs_growth"],
        "topics": ["node:sobretasa-utilidades", "node:grandes-empresas"],
        "props": [1, 2],
        "money": [money(620000.0, "million", 2026, "annual")],
        "quantities": [quantity(2.0, "percentage_point", "dos puntos porcentuales", "pp")],
        "populations": [],
        "industries": ["ind:1"],
        "institutions": ["inst:1"],
    },
    {
        "n": 2,
        "ref_label": "Artículo 4°",
        "title": "Rebaja del impuesto de timbres para pequeñas empresas",
        "section_id": "sec:2.2",
        "page": 4,
        "char_start": 620,
        "type": "tax",
        "mechanism_type": "tax_change",
        "text": (
            "Artículo 4°.— Redúcese a cero, hasta el 31 de diciembre de 2029, la tasa del "
            "impuesto de timbres y estampillas aplicable a las operaciones de crédito de "
            "dinero contratadas por empresas cuyos ingresos anuales no excedan de 25.000 "
            "unidades de fomento."
        ),
        "summary": (
            "Reduce a cero, hasta fines de 2029, el impuesto de timbres sobre operaciones de "
            "crédito contratadas por empresas con ingresos anuales de hasta 25.000 UF."
        ),
        "mechanism": (
            "Elimina un costo de transacción del crédito para el tramo de menor tamaño; el "
            "efecto sobre el acceso al financiamiento depende de que la rebaja se traspase a "
            "la tasa ofrecida, supuesto que el texto no establece."
        ),
        "effective_date": "2027-01-01",
        "sunset_date": "2029-12-31",
        "effective_condition": None,
        "conditions": ["ingresos anuales de la empresa no superiores a 25.000 UF"],
        "exceptions": [],
        "implementing_body": "administración tributaria",
        "impact_axes": ["households_vs_firms", "redistribution_vs_growth"],
        "topics": ["node:rebaja-timbres", "node:pymes"],
        "props": [3],
        "money": [money(-48000.0, "million", 2026, "annual")],
        "quantities": [quantity(25000.0, "count", "25.000 unidades de fomento", "UF")],
        "populations": [],
        "industries": [],
        "institutions": ["inst:1"],
    },
    {
        "n": 3,
        "ref_label": "Artículo 5°",
        "title": "Crédito tributario a la inversión en activo fijo",
        "section_id": "sec:2.3",
        "page": 4,
        "char_start": 2110,
        "type": "subsidy",
        "mechanism_type": "tax_change",
        "text": (
            "Artículo 5°.— Los contribuyentes de primera categoría tendrán derecho a un "
            "crédito equivalente al 15% del valor de las inversiones en activo fijo "
            "productivo efectuadas entre el 1 de enero de 2027 y el 31 de diciembre de 2030, "
            "con un tope anual de 8.000 unidades de fomento por contribuyente."
        ),
        "summary": (
            "Otorga un crédito tributario del 15% sobre inversiones en activo fijo realizadas "
            "entre 2027 y 2030, con tope de 8.000 UF anuales por contribuyente."
        ),
        "mechanism": (
            "Reduce el costo después de impuestos de la inversión en activo fijo. El tope "
            "anual limita el beneficio de las empresas de mayor tamaño, de modo que la "
            "incidencia por tamaño de empresa no está determinada por el texto."
        ),
        "effective_date": "2027-01-01",
        "sunset_date": "2030-12-31",
        "effective_condition": None,
        "conditions": [
            "inversión efectuada entre el 1 de enero de 2027 y el 31 de diciembre de 2030"
        ],
        "exceptions": ["no aplica a la adquisición de bienes raíces no destinados a la producción"],
        "implementing_body": "administración tributaria",
        "impact_axes": [
            "households_vs_firms",
            "redistribution_vs_growth",
            "public_vs_private_provision",
            "current_relief_vs_long_term_investment",
        ],
        "topics": ["node:credito-inversion", "node:sector-construccion"],
        "props": [4],
        "money": [money(-152000.0, "million", 2026, "annual")],
        "quantities": [quantity(15.0, "percentage", "15%", "%")],
        "populations": [],
        "industries": ["ind:2"],
        "institutions": ["inst:1"],
    },
    {
        "n": 4,
        "ref_label": "Artículo 6°",
        "title": "Aporte de estabilización de hogares",
        "section_id": "sec:3.1",
        "page": 5,
        "char_start": 410,
        "type": "benefit",
        "mechanism_type": "transfer",
        "text": (
            "Artículo 6°.— Créase un aporte mensual de estabilización, de $42.000 por hogar, "
            "en favor de los hogares pertenecientes a los cuatro primeros deciles de ingreso "
            "según el instrumento de caracterización socioeconómica vigente. El aporte se "
            "pagará durante veinticuatro meses contados desde la entrada en vigencia de esta ley."
        ),
        "summary": (
            "Crea una transferencia monetaria mensual de $42.000 por hogar para los cuatro "
            "primeros deciles de ingreso, pagadera durante 24 meses."
        ),
        "mechanism": (
            "Transferencia directa en dinero, sin contraprestación, focalizada por el "
            "instrumento de caracterización socioeconómica. El alcance efectivo depende de la "
            "cobertura de ese instrumento, que el texto no evalúa."
        ),
        "effective_date": "2027-01-01",
        "sunset_date": "2028-12-31",
        "effective_condition": None,
        "conditions": ["pertenencia a los cuatro primeros deciles de ingreso"],
        "exceptions": [],
        "implementing_body": "organismo de administración de beneficios sociales",
        "impact_axes": [
            "households_vs_firms",
            "redistribution_vs_growth",
            "current_relief_vs_long_term_investment",
        ],
        "topics": ["node:aporte-hogares", "node:hogares-deciles-1-4"],
        "props": [5, 6],
        "money": [
            money(42000.0, "unit", 2026, "monthly"),
            money(884000.0, "million", 2026, "annual"),
        ],
        "quantities": [quantity(24.0, "duration", "veinticuatro meses", "meses")],
        "populations": ["pop:1"],
        "industries": [],
        "institutions": ["inst:2"],
    },
    {
        "n": 5,
        "ref_label": "Artículo 7°",
        "title": "Fondo de Estabilización Territorial",
        "section_id": "sec:3.2",
        "page": 6,
        "char_start": 300,
        "type": "funding_allocation",
        "mechanism_type": "funding",
        "text": (
            "Artículo 7°.— Créase el Fondo de Estabilización Territorial, destinado a "
            "financiar proyectos de inversión de las municipalidades. El Fondo se dotará "
            "anualmente con recursos equivalentes al 0,18% del producto interno bruto y se "
            "distribuirá conforme a una fórmula que pondere población, ingresos propios "
            "permanentes por habitante e índice de ruralidad."
        ),
        "summary": (
            "Crea un fondo de inversión municipal dotado anualmente con 0,18% del PIB, "
            "distribuido por una fórmula que pondera población, ingresos propios por "
            "habitante y ruralidad."
        ),
        "mechanism": (
            "Transferencia condicionada a inversión desde el nivel central a los municipios. "
            "La fórmula compensa parcialmente a los municipios con menores ingresos propios "
            "por habitante, pero el texto no fija un piso por municipio."
        ),
        "effective_date": None,
        "sunset_date": None,
        "effective_condition": "a contar de la publicación del reglamento a que se refiere el artículo primero transitorio",
        "conditions": ["publicación previa del reglamento"],
        "exceptions": [],
        "implementing_body": "autoridad presupuestaria del ejecutivo",
        "impact_axes": [
            "redistribution_vs_growth",
            "public_vs_private_provision",
            "central_vs_local",
            "current_relief_vs_long_term_investment",
        ],
        "topics": ["node:fondo-territorial", "node:municipios"],
        "props": [7, 8],
        "money": [money(0.18, "percent_of_gdp", 2027, "annual")],
        "quantities": [
            quantity(0.18, "percentage", "0,18% del producto interno bruto", "% del PIB")
        ],
        "populations": [],
        "industries": [],
        "institutions": ["inst:3", "inst:4"],
    },
    {
        "n": 6,
        "ref_label": "Artículo 8°",
        "title": "Extensión del seguro de cesantía",
        "section_id": "sec:3.3",
        "page": 7,
        "char_start": 520,
        "type": "entitlement",
        "mechanism_type": "eligibility_change",
        "text": (
            "Artículo 8°.— Extiéndese de cinco a ocho meses el número máximo de giros con "
            "cargo al Fondo de Cesantía Solidario para los trabajadores con contrato a plazo "
            "fijo o por obra o faena determinada que hayan cotizado al menos doce meses "
            "continuos o discontinuos en los últimos veinticuatro."
        ),
        "summary": (
            "Aumenta de cinco a ocho meses el número máximo de giros del fondo solidario de "
            "cesantía para trabajadores con contrato a plazo fijo o por obra o faena, con un "
            "requisito de 12 cotizaciones en los últimos 24 meses."
        ),
        "mechanism": (
            "Amplía la duración de la prestación para un subconjunto de contratos. No modifica "
            "montos, tasas de reemplazo ni causales de término de contrato."
        ),
        "effective_date": "2027-04-01",
        "sunset_date": None,
        "effective_condition": None,
        "conditions": [
            "doce cotizaciones continuas o discontinuas en los últimos veinticuatro meses"
        ],
        "exceptions": ["no comprende a los trabajadores con contrato indefinido"],
        "implementing_body": "administradora del seguro de cesantía",
        "impact_axes": [
            "worker_protection_vs_flexibility",
            "current_relief_vs_long_term_investment",
        ],
        "topics": ["node:seguro-cesantia", "node:trabajadores-plazo-fijo"],
        "props": [9, 10],
        "money": [money(96000.0, "million", 2026, "annual")],
        "quantities": [quantity(8.0, "count", "de cinco a ocho meses", "meses")],
        "populations": ["pop:2"],
        "industries": [],
        "institutions": ["inst:5"],
    },
    {
        "n": 7,
        "ref_label": "Artículo 9°",
        "title": "Regla de crecimiento del gasto corriente",
        "section_id": "sec:4.1",
        "page": 8,
        "char_start": 240,
        "type": "obligation",
        "mechanism_type": "procedural_requirement",
        "text": (
            "Artículo 9°.— El gasto corriente del gobierno central no podrá crecer, en "
            "términos reales, más de un 2,5% anual durante los ejercicios presupuestarios "
            "2027 a 2030."
        ),
        "summary": (
            "Fija un límite de crecimiento real de 2,5% anual para el gasto corriente del "
            "gobierno central entre 2027 y 2030."
        ),
        "mechanism": (
            "Restricción cuantitativa sobre la formulación presupuestaria. El texto no "
            "establece consecuencia alguna en caso de incumplimiento, de modo que su "
            "exigibilidad depende de normas externas a esta ley."
        ),
        "effective_date": "2027-01-01",
        "sunset_date": "2030-12-31",
        "effective_condition": None,
        "conditions": [],
        "exceptions": ["no se aplica al gasto asociado a estados de excepción constitucional"],
        "implementing_body": "autoridad presupuestaria del ejecutivo",
        "impact_axes": ["public_vs_private_provision", "central_vs_local"],
        "topics": ["node:regla-gasto", "node:autoridad-presupuestaria"],
        "props": [11],
        "money": [],
        "quantities": [quantity(2.5, "percentage", "2,5% anual", "% real anual")],
        "populations": [],
        "industries": [],
        "institutions": ["inst:3"],
    },
    {
        "n": 8,
        "ref_label": "Artículo 10",
        "title": "Procedimiento abreviado de evaluación ambiental",
        "section_id": "sec:4.2",
        "page": 8,
        "char_start": 1460,
        "type": "procedure",
        "mechanism_type": "procedural_requirement",
        "text": (
            "Artículo 10.— Los proyectos de infraestructura pública cuyo monto de inversión "
            "no exceda de 200.000 unidades de fomento se sujetarán a un procedimiento "
            "abreviado de evaluación ambiental, cuyo plazo total no podrá exceder de noventa "
            "días hábiles, manteniéndose la obligación de recabar los informes de los "
            "organismos sectoriales competentes."
        ),
        "summary": (
            "Somete los proyectos de infraestructura pública de hasta 200.000 UF a un "
            "procedimiento ambiental abreviado de 90 días hábiles, conservando la consulta a "
            "los organismos sectoriales."
        ),
        "mechanism": (
            "Acorta el plazo del procedimiento sin eliminar la consulta sectorial. El efecto "
            "ambiental depende de si el plazo abreviado permite completar los informes, "
            "cuestión que el texto no aborda."
        ),
        "effective_date": "2027-01-01",
        "sunset_date": None,
        "effective_condition": None,
        "conditions": ["monto de inversión no superior a 200.000 UF"],
        "exceptions": ["no aplica a proyectos localizados en áreas bajo protección oficial"],
        "implementing_body": "organismo de evaluación ambiental",
        "impact_axes": [
            "environment_vs_project_acceleration",
            "public_vs_private_provision",
        ],
        "topics": ["node:procedimiento-ambiental", "node:sector-construccion"],
        "props": [12],
        "money": [],
        "quantities": [quantity(90.0, "duration", "noventa días hábiles", "días hábiles")],
        "populations": [],
        "industries": ["ind:2"],
        "institutions": ["inst:6"],
    },
    {
        "n": 9,
        "ref_label": "Artículo 11",
        "title": "Reporte trimestral de ejecución",
        "section_id": "sec:4.3",
        "page": 9,
        "char_start": 180,
        "type": "reporting_requirement",
        "mechanism_type": "information_requirement",
        "text": (
            "Artículo 11.— Las municipalidades y los organismos ejecutores informarán "
            "trimestralmente a la autoridad presupuestaria del ejecutivo el estado de "
            "ejecución de los recursos recibidos con cargo al Fondo de Estabilización "
            "Territorial, dentro de los treinta días siguientes al término de cada trimestre."
        ),
        "summary": (
            "Obliga a municipios y organismos ejecutores a informar trimestralmente la "
            "ejecución de los recursos del fondo territorial, dentro de 30 días del cierre "
            "de cada trimestre."
        ),
        "mechanism": (
            "Requisito de información periódica. El texto no asocia sanción al incumplimiento "
            "del plazo, por lo que el efecto sobre la ejecución es indirecto."
        ),
        "effective_date": None,
        "sunset_date": None,
        "effective_condition": "una vez efectuada la primera transferencia del Fondo",
        "conditions": [],
        "exceptions": [],
        "implementing_body": "autoridad presupuestaria del ejecutivo",
        "impact_axes": ["central_vs_local"],
        "topics": ["node:municipios", "node:autoridad-presupuestaria"],
        "props": [13],
        "money": [],
        "quantities": [quantity(30.0, "duration", "treinta días", "días")],
        "populations": [],
        "industries": [],
        "institutions": ["inst:3", "inst:4"],
    },
    {
        "n": 10,
        "ref_label": "Artículo primero transitorio",
        "title": "Reglamento del Fondo de Estabilización Territorial",
        "section_id": "sec:4.4",
        "page": 9,
        "char_start": 1520,
        "type": "delegation",
        "mechanism_type": "other",
        "text": (
            "Artículo primero transitorio.— Un reglamento, dictado dentro de los ciento "
            "ochenta días siguientes a la publicación de esta ley, establecerá la fórmula de "
            "distribución del Fondo de Estabilización Territorial, los requisitos de "
            "elegibilidad de los proyectos y los mecanismos de rendición."
        ),
        "summary": (
            "Delega en un reglamento, a dictarse dentro de 180 días desde la publicación de "
            "la ley, la fórmula de distribución, la elegibilidad de proyectos y la rendición "
            "del fondo territorial."
        ),
        "mechanism": (
            "Delegación normativa. Mientras el reglamento no se dicte, el Fondo carece de "
            "fórmula de distribución operativa y no puede transferir recursos."
        ),
        "effective_date": None,
        "sunset_date": None,
        "effective_condition": "a contar de la publicación de la ley",
        "conditions": [],
        "exceptions": [],
        "implementing_body": "autoridad presupuestaria del ejecutivo",
        "impact_axes": ["central_vs_local"],
        "topics": ["node:reglamento-fondo", "node:fondo-territorial"],
        "props": [14],
        "money": [],
        "quantities": [quantity(180.0, "duration", "ciento ochenta días", "días")],
        "populations": [],
        "industries": [],
        "institutions": ["inst:3"],
    },
]


def _provision_span(p: dict[str, Any]) -> dict[str, Any]:
    return span(p["text"], page=p["page"], section_id=p["section_id"], char_start=p["char_start"])


def build_sections() -> list[dict[str, Any]]:
    """The document outline. Held apart from the provisions so navigation survives
    incomplete provision extraction."""

    def sec(
        sid: str,
        number: str | None,
        heading: str,
        level: int,
        stype: str,
        pages: tuple[int, int],
        prov_ids: list[str],
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": sid,
            "number": number,
            "heading": heading,
            "level": level,
            "section_type": stype,
            "page_range": {"start": pages[0], "end": pages[1]},
            "char_start": None,
            "char_end": None,
            "provision_ids": prov_ids,
            "children": children or [],
            "is_heuristic": False,
        }

    return [
        sec(
            "sec:1",
            "Título I",
            "Disposiciones generales",
            0,
            "title",
            (1, 2),
            [],
            [
                sec("sec:1.1", "Artículo 1°", "Objeto de la ley", 1, "article", (1, 1), []),
                sec("sec:1.2", "Artículo 2°", "Definiciones", 1, "article", (2, 2), []),
            ],
        ),
        sec(
            "sec:2",
            "Título II",
            "Medidas de ingresos",
            0,
            "title",
            (3, 4),
            [],
            [
                sec(
                    "sec:2.1",
                    "Artículo 3°",
                    "Sobretasa transitoria a las utilidades",
                    1,
                    "article",
                    (3, 3),
                    [pid(1)],
                ),
                sec(
                    "sec:2.2",
                    "Artículo 4°",
                    "Impuesto de timbres y estampillas",
                    1,
                    "article",
                    (4, 4),
                    [pid(2)],
                ),
                sec(
                    "sec:2.3",
                    "Artículo 5°",
                    "Crédito a la inversión en activo fijo",
                    1,
                    "article",
                    (4, 5),
                    [pid(3)],
                ),
            ],
        ),
        sec(
            "sec:3",
            "Título III",
            "Medidas de gasto",
            0,
            "title",
            (5, 7),
            [],
            [
                sec(
                    "sec:3.1",
                    "Artículo 6°",
                    "Aporte de estabilización de hogares",
                    1,
                    "article",
                    (5, 5),
                    [pid(4)],
                ),
                sec(
                    "sec:3.2",
                    "Artículo 7°",
                    "Fondo de Estabilización Territorial",
                    1,
                    "article",
                    (6, 6),
                    [pid(5)],
                ),
                sec("sec:3.3", "Artículo 8°", "Seguro de cesantía", 1, "article", (7, 7), [pid(6)]),
            ],
        ),
        sec(
            "sec:4",
            "Título IV",
            "Reglas fiscales e institucionalidad",
            0,
            "title",
            (8, 9),
            [],
            [
                sec(
                    "sec:4.1",
                    "Artículo 9°",
                    "Regla de crecimiento del gasto corriente",
                    1,
                    "article",
                    (8, 8),
                    [pid(7)],
                ),
                sec(
                    "sec:4.2",
                    "Artículo 10",
                    "Procedimiento abreviado de evaluación ambiental",
                    1,
                    "article",
                    (8, 9),
                    [pid(8)],
                ),
                sec(
                    "sec:4.3",
                    "Artículo 11",
                    "Reporte trimestral de ejecución",
                    1,
                    "article",
                    (9, 9),
                    [pid(9)],
                ),
                sec(
                    "sec:4.4",
                    "Artículo primero transitorio",
                    "Reglamento del Fondo",
                    1,
                    "article",
                    (9, 9),
                    [pid(10)],
                ),
            ],
        ),
        sec(
            "sec:5",
            None,
            "Informe financiero adjunto",
            0,
            "annex",
            (10, 12),
            [],
            [
                sec("sec:5.1", "II", "Supuestos utilizados", 1, "clause", (10, 10), []),
                sec("sec:5.2", "III", "Efecto fiscal estimado", 1, "clause", (11, 11), []),
                sec("sec:5.3", "IV", "Limitaciones del ejercicio", 1, "clause", (12, 12), []),
            ],
        ),
    ]


def build_document() -> dict[str, Any]:
    """Warm phase 1: the document as parsed.

    ``source.url`` records the real target file. It was never downloaded, and the
    first extraction warning says so at severity ``error``.
    """
    document_provisions = []
    for p in PROVISIONS:
        document_provisions.append(
            {
                "id": pid(p["n"]),
                "title": p["title"],
                "text": p["text"],
                "provision_type": p["type"],
                "section_id": p["section_id"],
                "span": _provision_span(p),
                "effective_date": p["effective_date"],
                "effective_condition": p["effective_condition"],
                "sunset_date": p["sunset_date"],
                "amends": [],
                "depends_on": [pid(10)] if p["n"] in (5, 9) else [],
                "implementing_body": p["implementing_body"],
                "mechanism": p["mechanism"],
                "mechanism_type": p["mechanism_type"],
                "conditions": p["conditions"],
                "exceptions": p["exceptions"],
                "monetary_value_ids": [f"mv:{p['n']}.{i + 1}" for i in range(len(p["money"]))],
                "quantity_ids": [f"qt:{p['n']}.{i + 1}" for i in range(len(p["quantities"]))],
                "deadline_ids": [f"dl:{p['n']}"] if p["n"] in (9, 10) else [],
                "affected_institutions": p["institutions"],
                "affected_populations": p["populations"],
                "affected_industries": p["industries"],
                "affected_regions": [],
                "confidence": conf(
                    0.88,
                    0.79,
                    [
                        (
                            "primary_source_coverage",
                            "raises",
                            "El articulado del fixture delimita el artículo completo.",
                        )
                    ],
                    "El texto es un fixture sintético, no una extracción del archivo original.",
                ),
            }
        )

    monetary_values = []
    money_roles = {
        1: ("Recaudación anual estimada de la sobretasa", "revenue", True),
        2: ("Menor recaudación anual por la rebaja de timbres", "cost", True),
        3: ("Costo fiscal anual del crédito a la inversión", "cost", True),
        4: ("Aporte mensual por hogar", "benefit_amount", False),
        5: ("Dotación anual del Fondo de Estabilización Territorial", "allocation", False),
        6: ("Costo anual de la extensión del seguro de cesantía", "cost", True),
    }
    for p in PROVISIONS:
        for i, m in enumerate(p["money"]):
            label, role, is_est = money_roles.get(
                p["n"], ("Cifra monetaria del articulado", "other", False)
            )
            if p["n"] == 4 and i == 1:
                label, role, is_est = ("Costo anual del aporte de estabilización", "cost", True)
            monetary_values.append(
                {
                    "id": f"mv:{p['n']}.{i + 1}",
                    "label": label,
                    "money": m,
                    "role": role,
                    "recurrence": "monthly" if m["unit"] == "unit" else "annual",
                    "fiscal_years": [2027, 2028],
                    "is_estimate": is_est,
                    "provision_id": pid(p["n"]),
                    "span": _provision_span(p),
                }
            )

    quantities = []
    for p in PROVISIONS:
        for i, q in enumerate(p["quantities"]):
            quantities.append(
                {
                    "id": f"qt:{p['n']}.{i + 1}",
                    "label": f"Parámetro cuantitativo de {p['ref_label']}",
                    "quantity": q,
                    "role": "rate"
                    if q["kind"] in ("percentage", "percentage_point")
                    else "threshold",
                    "provision_id": pid(p["n"]),
                    "span": _provision_span(p),
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "id": DOC_ID,
        "identity": {
            "slug": DOC_SLUG,
            "title": (
                "Proyecto de ley de estabilización fiscal y financiamiento territorial "
                "— texto sintético de demostración"
            ),
            "subtitle": (
                "Articulado e informe financiero adjunto. Contenido generado para demostrar "
                "la interfaz de Aleph; no reproduce ningún documento real."
            ),
            "short_title": "Paquete fiscal de demostración",
            "jurisdiction": {"code": "CL", "name": "Chile", "level": "national"},
            "institution": "poder ejecutivo (rol genérico; ningún organismo real está representado)",
            "document_type": "bill",
            "document_type_raw": "Proyecto de ley con informe financiero adjunto",
            "language": "es-CL",
            "additional_languages": [],
            "version": "primer trámite constitucional",
            "legislative_identifier": "18.216-05",
            "identifiers": [
                {"scheme": "bill_number", "value": "18.216-05", "issuer": None},
                {
                    "scheme": "internal_file",
                    "value": "aleph-demo-18216-05",
                    "issuer": "Aleph (demo)",
                },
            ],
            "status": "in_committee",
            "dates": {
                "introduced": "2026-05-12",
                "published": "2026-05-12",
                "retrieved": None,
                "last_amended": "2026-06-18",
                "effective_from": "2027-01-01",
            },
            "authorship": [
                {
                    "role": "patrocinante",
                    "entity_kind": "institution",
                    "entity": "ministerio a cargo de la hacienda pública",
                    "is_personal_name": False,
                    "span": span(
                        "Mensaje del Ejecutivo con el que se inicia un proyecto de ley.",
                        page=1,
                        section_id="sec:1.1",
                        char_start=120,
                    ),
                },
                {
                    "role": "órgano elaborador del informe financiero",
                    "entity_kind": "office",
                    "entity": "autoridad presupuestaria del ejecutivo",
                    "is_personal_name": False,
                    "span": span(
                        "Informe financiero elaborado por la autoridad presupuestaria.",
                        page=10,
                        section_id="sec:5",
                        char_start=60,
                    ),
                },
            ],
            "summary": (
                "El proyecto combina medidas de ingresos (una sobretasa transitoria sobre "
                "utilidades de grandes empresas, una rebaja del impuesto de timbres para "
                "empresas pequeñas y un crédito a la inversión en activo fijo) con medidas de "
                "gasto (una transferencia mensual a hogares de los cuatro primeros deciles, un "
                "fondo de inversión municipal y una extensión del seguro de cesantía), más una "
                "regla de crecimiento del gasto corriente y un procedimiento ambiental "
                "abreviado para infraestructura pública."
            ),
            "keywords": [
                "sobretasa",
                "impuesto de timbres",
                "crédito a la inversión",
                "aporte de estabilización",
                "fondo territorial",
                "seguro de cesantía",
                "regla de gasto",
            ],
        },
        "source": {
            "url": TARGET_DOCUMENT_URL,
            "file_name": None,
            "media_type": "application/pdf",
            "file_hash": None,
            "hash_algorithm": None,
            "file_size_bytes": None,
            "page_count": 12,
            "retrieved_at": None,
            "retrieval_method": "fixture",
            "extraction_method": "fixture",
            "extractor_version": EXTRACTOR,
            "extraction_quality": {
                "state": "good",
                "text_coverage": 1.0,
                "chars_extracted": 18432,
                "pages_without_text": [],
                "ocr_used": False,
                "ocr_confidence": None,
                "tables_detected": 3,
                "note": (
                    "La calidad reportada corresponde al fixture sintético, no a la extracción "
                    "de ningún archivo. No se ejecutó ningún extractor de PDF."
                ),
            },
            "license_note": (
                "La URL registrada identifica el documento objetivo de esta configuración. El "
                "archivo no fue descargado: la recuperación en línea está deshabilitada."
            ),
        },
        "structure": {
            "sections": build_sections(),
            "numbering_scheme": "roman_title_arabic_article",
            "max_depth": 1,
            "has_table_of_contents": True,
        },
        "provisions": document_provisions,
        "definitions": [
            {
                "id": "def:1",
                "term": "hogar",
                "definition_text": (
                    "Para los efectos de esta ley, se entenderá por hogar el grupo de personas "
                    "registradas bajo un mismo folio en el instrumento de caracterización "
                    "socioeconómica vigente."
                ),
                "scope": "para los efectos de esta ley",
                "span": span(
                    "se entenderá por hogar el grupo de personas registradas bajo un mismo folio",
                    page=2,
                    section_id="sec:1.2",
                    char_start=340,
                ),
                "provision_id": pid(4),
            },
            {
                "id": "def:2",
                "term": "ingresos propios permanentes",
                "definition_text": (
                    "Se entenderá por ingresos propios permanentes los ingresos municipales de "
                    "carácter recurrente, excluidas las transferencias del gobierno central."
                ),
                "scope": "para los efectos del Título III",
                "span": span(
                    "excluidas las transferencias del gobierno central",
                    page=2,
                    section_id="sec:1.2",
                    char_start=880,
                ),
                "provision_id": pid(5),
            },
        ],
        "monetary_values": monetary_values,
        "quantities": quantities,
        "deadlines": [
            {
                "id": "dl:9",
                "label": "Informe trimestral de ejecución del Fondo",
                "date": None,
                "relative_period": "treinta días siguientes al término de cada trimestre",
                "trigger": "término de cada trimestre calendario",
                "obligated_party": "municipalidades y organismos ejecutores",
                "consequence_of_missing": (
                    "El texto no establece consecuencia alguna. Registrar ese silencio es parte "
                    "del hallazgo."
                ),
                "provision_id": pid(9),
                "span": _provision_span(PROVISIONS[8]),
            },
            {
                "id": "dl:10",
                "label": "Dictación del reglamento del Fondo de Estabilización Territorial",
                "date": None,
                "relative_period": "ciento ochenta días siguientes a la publicación de esta ley",
                "trigger": "publicación de la ley",
                "obligated_party": "autoridad presupuestaria del ejecutivo",
                "consequence_of_missing": (
                    "El texto no fija consecuencia. Sin reglamento el Fondo no puede transferir "
                    "recursos, de modo que el incumplimiento suspende de hecho el artículo 7°."
                ),
                "provision_id": pid(10),
                "span": _provision_span(PROVISIONS[9]),
            },
        ],
        "assumptions": [
            {
                "id": "asm:1",
                "statement": (
                    "El informe financiero proyecta sus cifras suponiendo un crecimiento real "
                    "del producto de 2,3% anual entre 2027 y 2030."
                ),
                "assumption_type": "macroeconomic",
                "is_explicit": True,
                "stated_by": "autoridad presupuestaria del ejecutivo",
                "quantified_money": None,
                "quantified_value": quantity(2.3, "percentage", "2,3% anual", "% real anual"),
                "sensitivity_note": (
                    "El informe indica que un crecimiento un punto menor reduce la recaudación "
                    "proyectada de la sobretasa en aproximadamente un 12%."
                ),
                "applies_to_provision_ids": [pid(1), pid(5)],
                "span": span(
                    "Las proyecciones suponen un crecimiento real del producto de 2,3% anual.",
                    page=10,
                    section_id="sec:5.1",
                    char_start=210,
                ),
            },
            {
                "id": "asm:2",
                "statement": (
                    "El informe financiero supone una tasa de toma del aporte de estabilización "
                    "de 92% de los hogares elegibles."
                ),
                "assumption_type": "take_up",
                "is_explicit": True,
                "stated_by": "autoridad presupuestaria del ejecutivo",
                "quantified_money": None,
                "quantified_value": quantity(
                    92.0, "percentage", "92% de los hogares elegibles", "%"
                ),
                "sensitivity_note": None,
                "applies_to_provision_ids": [pid(4)],
                "span": span(
                    "Se supone una tasa de toma de 92% de los hogares elegibles.",
                    page=10,
                    section_id="sec:5.1",
                    char_start=640,
                ),
            },
            {
                "id": "asm:3",
                "statement": (
                    "El informe financiero declara no modelar la respuesta de la inversión "
                    "privada a la sobretasa."
                ),
                "assumption_type": "behavioural",
                "is_explicit": True,
                "stated_by": "autoridad presupuestaria del ejecutivo",
                "quantified_money": None,
                "quantified_value": None,
                "sensitivity_note": (
                    "El propio informe advierte que, de existir una respuesta de inversión "
                    "relevante, la recaudación neta sería menor que la proyectada."
                ),
                "applies_to_provision_ids": [pid(1), pid(3)],
                "span": span(
                    "El presente ejercicio no incorpora una respuesta conductual de la inversión.",
                    page=12,
                    section_id="sec:5.3",
                    char_start=150,
                ),
            },
            {
                "id": "asm:4",
                "statement": (
                    "El informe financiero supone que el reglamento del Fondo se dicta dentro "
                    "del plazo legal y que las transferencias comienzan en 2027."
                ),
                "assumption_type": "implementation",
                "is_explicit": False,
                "stated_by": "autoridad presupuestaria del ejecutivo",
                "quantified_money": None,
                "quantified_value": None,
                "sensitivity_note": None,
                "applies_to_provision_ids": [pid(5), pid(10)],
                "span": span(
                    "El gasto del Fondo se imputa íntegramente al ejercicio 2027.",
                    page=11,
                    section_id="sec:5.2",
                    char_start=980,
                ),
            },
        ],
        "citations": [
            {
                "id": "cit:1",
                "cited_text": "instrumento de caracterización socioeconómica vigente",
                "target_kind": "regulation",
                "target_identifier": None,
                "target_title": "Instrumento de caracterización socioeconómica (referencia genérica)",
                "url": None,
                "provision_id": pid(4),
                "span": span(
                    "según el instrumento de caracterización socioeconómica vigente",
                    page=5,
                    section_id="sec:3.1",
                    char_start=560,
                ),
            },
            {
                "id": "cit:2",
                "cited_text": "Fondo de Cesantía Solidario",
                "target_kind": "statute",
                "target_identifier": None,
                "target_title": "Normativa del seguro de cesantía (referencia genérica)",
                "url": None,
                "provision_id": pid(6),
                "span": span(
                    "con cargo al Fondo de Cesantía Solidario",
                    page=7,
                    section_id="sec:3.3",
                    char_start=610,
                ),
            },
        ],
        "amendments": [
            {
                "id": "amd:1",
                "operation": "replace",
                "target_identifier": None,
                "target_title": "Normativa del seguro de cesantía (referencia genérica)",
                "target_locator": "número máximo de giros con cargo al fondo solidario",
                "before_text": "cinco meses",
                "after_text": "ocho meses",
                "provision_id": pid(6),
                "span": span(
                    "Extiéndese de cinco a ocho meses el número máximo de giros",
                    page=7,
                    section_id="sec:3.3",
                    char_start=520,
                ),
            }
        ],
        "legal_dependencies": [
            {
                "id": "dep:1",
                "dependency_kind": "requires_regulation",
                "identifier": None,
                "title": "Reglamento del Fondo de Estabilización Territorial",
                "status": "unmet",
                "note": (
                    "El artículo 7° no puede transferir recursos mientras no exista la fórmula "
                    "de distribución que el reglamento debe fijar. El registro no contiene "
                    "evidencia de que el reglamento haya sido dictado."
                ),
                "provision_ids": [pid(5), pid(9)],
                "span": _provision_span(PROVISIONS[9]),
            },
            {
                "id": "dep:2",
                "dependency_kind": "requires_appropriation",
                "identifier": None,
                "title": "Imputación presupuestaria anual del Fondo",
                "status": "unknown",
                "note": (
                    "El texto fija la dotación como porcentaje del producto, pero no señala si "
                    "requiere una imputación anual en la ley de presupuestos."
                ),
                "provision_ids": [pid(5)],
                "span": None,
            },
        ],
        "affected_institutions": [
            {
                "id": "inst:1",
                "name": "administración tributaria",
                "role_in_document": "implementing",
                "provision_ids": [pid(1), pid(2), pid(3)],
                "span": None,
            },
            {
                "id": "inst:2",
                "name": "organismo de administración de beneficios sociales",
                "role_in_document": "implementing",
                "provision_ids": [pid(4)],
                "span": None,
            },
            {
                "id": "inst:3",
                "name": "autoridad presupuestaria del ejecutivo",
                "role_in_document": "supervising",
                "provision_ids": [pid(5), pid(7), pid(9), pid(10)],
                "span": None,
            },
            {
                "id": "inst:4",
                "name": "municipalidades",
                "role_in_document": "beneficiary",
                "provision_ids": [pid(5), pid(9)],
                "span": None,
            },
            {
                "id": "inst:5",
                "name": "administradora del seguro de cesantía",
                "role_in_document": "implementing",
                "provision_ids": [pid(6)],
                "span": None,
            },
            {
                "id": "inst:6",
                "name": "organismo de evaluación ambiental",
                "role_in_document": "regulated",
                "provision_ids": [pid(8)],
                "span": None,
            },
        ],
        "affected_populations": [
            {
                "id": "pop:1",
                "label": "hogares de los cuatro primeros deciles de ingreso",
                "definition_criteria": (
                    "pertenencia a los cuatro primeros deciles según el instrumento de "
                    "caracterización socioeconómica vigente"
                ),
                "estimated_size": quantity(1420000.0, "count", "1.420.000 hogares", "hogares"),
                "provision_ids": [pid(4)],
                "span": span(
                    "los hogares pertenecientes a los cuatro primeros deciles de ingreso",
                    page=5,
                    section_id="sec:3.1",
                    char_start=470,
                ),
            },
            {
                "id": "pop:2",
                "label": "trabajadores con contrato a plazo fijo o por obra o faena",
                "definition_criteria": (
                    "haber cotizado al menos doce meses continuos o discontinuos en los "
                    "últimos veinticuatro"
                ),
                "estimated_size": None,
                "provision_ids": [pid(6)],
                "span": span(
                    "trabajadores con contrato a plazo fijo o por obra o faena determinada",
                    page=7,
                    section_id="sec:3.3",
                    char_start=600,
                ),
            },
        ],
        "affected_industries": [
            {
                "id": "ind:1",
                "label": "empresas con ingresos brutos anuales superiores a 100.000 UF",
                "classification_code": None,
                "classification_system": None,
                "provision_ids": [pid(1)],
                "span": None,
            },
            {
                "id": "ind:2",
                "label": "construcción e infraestructura",
                "classification_code": "F",
                "classification_system": "CIIU rev.4",
                "provision_ids": [pid(3), pid(8)],
                "span": None,
            },
        ],
        "extraction_warnings": [
            {
                "code": "other",
                "severity": "error",
                "message": (
                    "CONTENIDO SINTÉTICO. El texto, las cifras y la estructura de este documento "
                    "NO fueron extraídos del archivo indicado en source.url ni de ninguna otra "
                    "fuente real. La URL se registra únicamente como configuración del documento "
                    "objetivo; el archivo nunca fue descargado (retrieval_method='fixture', "
                    "extraction_method='fixture', retrieved_at=null). Nada de lo que sigue "
                    "describe el contenido del Boletín 18.216-05."
                ),
                "page": None,
                "affected_field": None,
                "span": None,
            },
            {
                "code": "provision_boundary_uncertain",
                "severity": "warning",
                "message": (
                    "El límite entre el artículo 5° y el artículo 6° se fijó por la numeración "
                    "impresa; si el articulado incluyera incisos adicionales, el texto atribuido "
                    "a cada provisión podría desplazarse."
                ),
                "page": 5,
                "affected_field": "provisions[2].span",
                "span": None,
            },
            {
                "code": "table_extraction_failed",
                "severity": "warning",
                "message": (
                    "La tabla de efecto fiscal por año del informe financiero no pudo "
                    "estructurarse; las cifras anuales se leyeron del texto corrido."
                ),
                "page": 11,
                "affected_field": "monetary_values",
                "span": None,
            },
            {
                "code": "ambiguous_numbering",
                "severity": "info",
                "message": (
                    "El documento numera los artículos transitorios con ordinales en palabras, "
                    "de modo que el orden lexicográfico no coincide con el orden legal."
                ),
                "page": 9,
                "affected_field": "structure.sections",
                "span": None,
            },
        ],
        "notes": (
            "Fixture de demostración. La lectura describe un articulado inventado; ninguna "
            "cifra corresponde a una estimación oficial de ningún organismo."
        ),
    }


# --------------------------------------------------------------------------- #
# Warm phase 2 — atomic propositions
# --------------------------------------------------------------------------- #

# (n, provision_n, text, proposition_type, subject, predicate, object, verbatim span,
#  modality, negated, scope_temporal, scope_population, conditions, exceptions, hedges)
PROPOSITION_ROWS: list[dict[str, Any]] = [
    {
        "n": 1,
        "prov": 1,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "La sobretasa sobre la base imponible del impuesto de primera categoría es de dos puntos porcentuales.",
        "subject": "sobretasa transitoria",
        "predicate": "tiene una tasa de",
        "object": "dos puntos porcentuales",
        "quote": "una sobretasa de dos puntos porcentuales sobre la base imponible del impuesto de primera categoría",
        "modality": "obligatory",
        "negated": False,
        "temporal": "años tributarios 2027 a 2031",
        "population": "contribuyentes de primera categoría",
        "conditions": ["ingresos brutos anuales del ejercicio anterior superiores a 100.000 UF"],
        "exceptions": [],
        "hedges": [],
        "quantities": [quantity(2.0, "percentage_point", "dos puntos porcentuales", "pp")],
        "money": [],
    },
    {
        "n": 2,
        "prov": 1,
        "type": "conditional",
        "statement_type": "fact",
        "text": "La sobretasa sólo se aplica a los contribuyentes cuyos ingresos brutos anuales del ejercicio anterior superaron las 100.000 unidades de fomento.",
        "subject": "sobretasa transitoria",
        "predicate": "se aplica sólo a",
        "object": "contribuyentes sobre 100.000 UF de ingresos brutos",
        "quote": "cuyos ingresos brutos anuales del ejercicio anterior hayan superado las 100.000 unidades de fomento",
        "modality": "conditional",
        "negated": False,
        "temporal": "años tributarios 2027 a 2031",
        "population": "contribuyentes de primera categoría",
        "conditions": ["ingresos brutos anuales superiores a 100.000 UF"],
        "exceptions": ["contribuyentes acogidos al régimen de transparencia tributaria"],
        "hedges": [],
        "quantities": [quantity(100000.0, "count", "100.000 unidades de fomento", "UF")],
        "money": [],
    },
    {
        "n": 3,
        "prov": 2,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "La tasa del impuesto de timbres aplicable a las operaciones de crédito de empresas con ingresos anuales de hasta 25.000 UF se reduce a cero.",
        "subject": "impuesto de timbres y estampillas",
        "predicate": "se reduce a",
        "object": "cero",
        "quote": "Redúcese a cero, hasta el 31 de diciembre de 2029, la tasa del impuesto de timbres y estampillas",
        "modality": "obligatory",
        "negated": False,
        "temporal": "hasta el 31 de diciembre de 2029",
        "population": "empresas con ingresos anuales de hasta 25.000 UF",
        "conditions": ["ingresos anuales no superiores a 25.000 UF"],
        "exceptions": [],
        "hedges": [],
        "quantities": [quantity(0.0, "rate", "Redúcese a cero", "%")],
        "money": [],
    },
    {
        "n": 4,
        "prov": 3,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "El crédito por inversión en activo fijo equivale al 15% del valor de la inversión, con un tope anual de 8.000 unidades de fomento por contribuyente.",
        "subject": "crédito a la inversión en activo fijo",
        "predicate": "equivale a",
        "object": "15% de la inversión, con tope de 8.000 UF anuales",
        "quote": "un crédito equivalente al 15% del valor de las inversiones en activo fijo productivo",
        "modality": "permissive",
        "negated": False,
        "temporal": "inversiones efectuadas entre el 1 de enero de 2027 y el 31 de diciembre de 2030",
        "population": "contribuyentes de primera categoría",
        "conditions": [],
        "exceptions": ["bienes raíces no destinados a la producción"],
        "hedges": [],
        "quantities": [
            quantity(15.0, "percentage", "15%", "%"),
            quantity(8000.0, "count", "8.000 unidades de fomento", "UF"),
        ],
        "money": [],
    },
    {
        "n": 5,
        "prov": 4,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "El aporte de estabilización asciende a $42.000 mensuales por hogar.",
        "subject": "aporte de estabilización",
        "predicate": "asciende a",
        "object": "$42.000 mensuales por hogar",
        "quote": "un aporte mensual de estabilización, de $42.000 por hogar",
        "modality": "obligatory",
        "negated": False,
        "temporal": "veinticuatro meses desde la entrada en vigencia",
        "population": "hogares de los cuatro primeros deciles",
        "conditions": [],
        "exceptions": [],
        "hedges": [],
        "quantities": [],
        "money": [money(42000.0, "unit", 2026, "monthly")],
    },
    {
        "n": 6,
        "prov": 4,
        "type": "temporal",
        "statement_type": "fact",
        "text": "El aporte de estabilización se paga durante veinticuatro meses contados desde la entrada en vigencia de la ley.",
        "subject": "aporte de estabilización",
        "predicate": "se paga durante",
        "object": "veinticuatro meses",
        "quote": "El aporte se pagará durante veinticuatro meses contados desde la entrada en vigencia de esta ley",
        "modality": "obligatory",
        "negated": False,
        "temporal": "veinticuatro meses desde la entrada en vigencia",
        "population": "hogares de los cuatro primeros deciles",
        "conditions": [],
        "exceptions": [],
        "hedges": [],
        "quantities": [quantity(24.0, "duration", "veinticuatro meses", "meses")],
        "money": [],
    },
    {
        "n": 7,
        "prov": 5,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "El Fondo de Estabilización Territorial se dota anualmente con recursos equivalentes al 0,18% del producto interno bruto.",
        "subject": "Fondo de Estabilización Territorial",
        "predicate": "se dota anualmente con",
        "object": "0,18% del producto interno bruto",
        "quote": "se dotará anualmente con recursos equivalentes al 0,18% del producto interno bruto",
        "modality": "obligatory",
        "negated": False,
        "temporal": "anual",
        "population": "municipalidades",
        "conditions": ["publicación previa del reglamento"],
        "exceptions": [],
        "hedges": [],
        "quantities": [
            quantity(0.18, "percentage", "0,18% del producto interno bruto", "% del PIB")
        ],
        "money": [money(0.18, "percent_of_gdp", 2027, "annual")],
    },
    {
        "n": 8,
        "prov": 5,
        "type": "procedural",
        "statement_type": "fact",
        "text": "La distribución del Fondo de Estabilización Territorial pondera población, ingresos propios permanentes por habitante e índice de ruralidad.",
        "subject": "distribución del Fondo",
        "predicate": "pondera",
        "object": "población, ingresos propios por habitante y ruralidad",
        "quote": "una fórmula que pondere población, ingresos propios permanentes por habitante e índice de ruralidad",
        "modality": "obligatory",
        "negated": False,
        "temporal": None,
        "population": "municipalidades",
        "conditions": ["la fórmula concreta la fija el reglamento"],
        "exceptions": [],
        "hedges": [],
        "quantities": [],
        "money": [],
    },
    {
        "n": 9,
        "prov": 6,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "El número máximo de giros con cargo al Fondo de Cesantía Solidario aumenta de cinco a ocho meses.",
        "subject": "giros del Fondo de Cesantía Solidario",
        "predicate": "aumentan de",
        "object": "cinco a ocho meses",
        "quote": "Extiéndese de cinco a ocho meses el número máximo de giros con cargo al Fondo de Cesantía Solidario",
        "modality": "obligatory",
        "negated": False,
        "temporal": "a contar del 1 de abril de 2027",
        "population": "trabajadores con contrato a plazo fijo o por obra o faena",
        "conditions": ["doce cotizaciones en los últimos veinticuatro meses"],
        "exceptions": [],
        "hedges": [],
        "quantities": [quantity(8.0, "count", "de cinco a ocho meses", "meses")],
        "money": [],
    },
    {
        "n": 10,
        "prov": 6,
        "type": "assertion_of_content",
        "statement_type": "fact",
        "text": "La extensión de los giros del seguro de cesantía no comprende a los trabajadores con contrato indefinido.",
        "subject": "extensión de los giros del seguro de cesantía",
        "predicate": "no comprende a",
        "object": "trabajadores con contrato indefinido",
        "quote": "no comprende a los trabajadores con contrato indefinido",
        "modality": "asserted",
        "negated": True,
        "negated_element": "el alcance de la extensión respecto de los contratos indefinidos",
        "cue_text": "no comprende",
        "temporal": None,
        "population": "trabajadores con contrato indefinido",
        "conditions": [],
        "exceptions": [],
        "hedges": [],
        "quantities": [],
        "money": [],
    },
    {
        "n": 11,
        "prov": 7,
        "type": "quantitative",
        "statement_type": "fact",
        "text": "El gasto corriente del gobierno central no puede crecer más de 2,5% real anual durante los ejercicios 2027 a 2030.",
        "subject": "gasto corriente del gobierno central",
        "predicate": "no puede crecer más de",
        "object": "2,5% real anual",
        "quote": "no podrá crecer, en términos reales, más de un 2,5% anual durante los ejercicios presupuestarios 2027 a 2030",
        "modality": "prohibitive",
        "negated": True,
        "negated_element": "el crecimiento por sobre el límite",
        "cue_text": "no podrá",
        "temporal": "ejercicios presupuestarios 2027 a 2030",
        "population": "gobierno central",
        "conditions": [],
        "exceptions": ["gasto asociado a estados de excepción constitucional"],
        "hedges": [],
        "quantities": [quantity(2.5, "percentage", "2,5% anual", "% real anual")],
        "money": [],
    },
    {
        "n": 12,
        "prov": 8,
        "type": "procedural",
        "statement_type": "fact",
        "text": "El procedimiento abreviado de evaluación ambiental tiene un plazo total máximo de noventa días hábiles.",
        "subject": "procedimiento abreviado de evaluación ambiental",
        "predicate": "tiene un plazo máximo de",
        "object": "noventa días hábiles",
        "quote": "cuyo plazo total no podrá exceder de noventa días hábiles",
        "modality": "obligatory",
        "negated": False,
        "temporal": None,
        "population": "proyectos de infraestructura pública de hasta 200.000 UF",
        "conditions": ["monto de inversión no superior a 200.000 UF"],
        "exceptions": ["proyectos localizados en áreas bajo protección oficial"],
        "hedges": [],
        "quantities": [quantity(90.0, "duration", "noventa días hábiles", "días hábiles")],
        "money": [],
    },
    {
        "n": 13,
        "prov": 9,
        "type": "procedural",
        "statement_type": "fact",
        "text": "Las municipalidades informan trimestralmente el estado de ejecución de los recursos del Fondo dentro de los treinta días siguientes al término de cada trimestre.",
        "subject": "municipalidades y organismos ejecutores",
        "predicate": "informan",
        "object": "estado de ejecución de los recursos del Fondo",
        "quote": "informarán trimestralmente a la autoridad presupuestaria del ejecutivo el estado de ejecución",
        "modality": "obligatory",
        "negated": False,
        "temporal": "dentro de los treinta días siguientes al término de cada trimestre",
        "population": "municipalidades y organismos ejecutores",
        "conditions": [],
        "exceptions": [],
        "hedges": [],
        "quantities": [quantity(30.0, "duration", "treinta días", "días")],
        "money": [],
    },
    {
        "n": 14,
        "prov": 10,
        "type": "temporal",
        "statement_type": "fact",
        "text": "El reglamento que fija la fórmula de distribución del Fondo debe dictarse dentro de los ciento ochenta días siguientes a la publicación de la ley.",
        "subject": "reglamento del Fondo de Estabilización Territorial",
        "predicate": "debe dictarse dentro de",
        "object": "ciento ochenta días desde la publicación",
        "quote": "dictado dentro de los ciento ochenta días siguientes a la publicación de esta ley",
        "modality": "obligatory",
        "negated": False,
        "temporal": "ciento ochenta días desde la publicación de la ley",
        "population": "autoridad presupuestaria del ejecutivo",
        "conditions": [],
        "exceptions": [],
        "hedges": [],
        "quantities": [quantity(180.0, "duration", "ciento ochenta días", "días")],
        "money": [],
    },
]


def build_propositions() -> dict[str, Any]:
    """Warm phase 2. Every proposition carries a verbatim span: an unquotable
    proposition is invalid, not merely low-confidence."""
    by_prov = {p["n"]: p for p in PROVISIONS}
    items = []
    for row in PROPOSITION_ROWS:
        prov = by_prov[row["prov"]]
        items.append(
            {
                "id": ppid(row["n"]),
                "text": row["text"],
                "proposition_type": row["type"],
                "statement_type": row["statement_type"],
                "subject": row["subject"],
                "predicate_summary": row["predicate"],
                "object": row["object"],
                "quantities": row["quantities"],
                "money": row["money"],
                "provenance": {
                    "source_id": DOC_ID,
                    "source_kind": "document",
                    "url": TARGET_DOCUMENT_URL,
                    "retrieved_at": None,
                    "span": span(
                        row["quote"],
                        page=prov["page"],
                        section_id=prov["section_id"],
                        char_start=prov["char_start"] + 40,
                    ),
                    "extractor": EXTRACTOR,
                },
                "derived_from_provision_id": pid(row["prov"]),
                "derived_from_section_id": prov["section_id"],
                "confidence": conf(
                    0.86,
                    0.8,
                    [
                        (
                            "primary_source_coverage",
                            "raises",
                            "El pasaje citado contiene la proposición completa.",
                        ),
                        (
                            "claim_ambiguity",
                            "lowers",
                            "La normalización resuelve elipsis del texto legal.",
                        ),
                    ],
                    "El documento primario real no fue leído; el pasaje proviene de un fixture.",
                ),
                "negation": {
                    "is_negated": row["negated"],
                    "negated_element": row.get("negated_element"),
                    "cue_text": row.get("cue_text"),
                },
                "scope": {
                    "temporal": row["temporal"],
                    "geographic": None,
                    "population": row["population"],
                    "conditions": row["conditions"],
                    "exceptions": row["exceptions"],
                },
                "modality": row["modality"],
                "hedges": row["hedges"],
                "is_atomic": True,
                "is_self_contained": True,
                "related_proposition_ids": [ppid(14)] if row["n"] in (7, 8) else [],
                "tags": [f"prov-{row['prov']}", row["type"]],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "document_id": DOC_ID,
        "generated_at": GENERATED_AT,
        "extractor": EXTRACTOR,
        "propositions": items,
        "coverage": {
            "provisions_total": len(PROVISIONS),
            "provisions_with_propositions": len({r["prov"] for r in PROPOSITION_ROWS}),
            "sections_not_processed": ["sec:1.1", "sec:5.2"],
            "note": (
                "No se extrajeron proposiciones del preámbulo ni de la tabla de efecto fiscal "
                "por año, cuya estructura no pudo recuperarse."
            ),
        },
        "notes": SYNTHETIC_NOTICE,
    }


# --------------------------------------------------------------------------- #
# Warm phase 3 — topic graph
# --------------------------------------------------------------------------- #

# (id, kind, label, salience, provision_ids, description)
NODE_ROWS: list[tuple[str, str, str, float, list[int], str]] = [
    (
        "paquete-fiscal",
        "policy",
        "Paquete de estabilización fiscal",
        1.0,
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "El conjunto de medidas de ingreso y gasto que el proyecto agrupa.",
    ),
    (
        "sobretasa-utilidades",
        "tax",
        "Sobretasa transitoria a las utilidades",
        0.92,
        [1],
        "Recargo de 2 puntos porcentuales sobre la base imponible de primera categoría.",
    ),
    (
        "rebaja-timbres",
        "tax",
        "Rebaja del impuesto de timbres",
        0.54,
        [2],
        "Reducción a cero de la tasa para operaciones de crédito de empresas pequeñas.",
    ),
    (
        "credito-inversion",
        "benefit",
        "Crédito a la inversión en activo fijo",
        0.76,
        [3],
        "Crédito tributario del 15% con tope anual por contribuyente.",
    ),
    (
        "aporte-hogares",
        "benefit",
        "Aporte de estabilización de hogares",
        0.95,
        [4],
        "Transferencia mensual de $42.000 por hogar durante 24 meses.",
    ),
    (
        "fondo-territorial",
        "benefit",
        "Fondo de Estabilización Territorial",
        0.9,
        [5, 9, 10],
        "Fondo de inversión municipal dotado con 0,18% del PIB anual.",
    ),
    (
        "regla-gasto",
        "obligation",
        "Regla de crecimiento del gasto corriente",
        0.62,
        [7],
        "Límite de 2,5% real anual al gasto corriente del gobierno central.",
    ),
    (
        "procedimiento-ambiental",
        "obligation",
        "Procedimiento abreviado de evaluación ambiental",
        0.58,
        [8],
        "Plazo máximo de 90 días hábiles para infraestructura pública bajo umbral.",
    ),
    (
        "seguro-cesantia",
        "right",
        "Extensión del seguro de cesantía",
        0.68,
        [6],
        "Aumento de cinco a ocho giros para contratos a plazo fijo o por obra.",
    ),
    (
        "reglamento-fondo",
        "obligation",
        "Reglamento del Fondo territorial",
        0.5,
        [10],
        "Norma pendiente que debe fijar la fórmula de distribución del Fondo.",
    ),
    (
        "hogares-deciles-1-4",
        "social_group",
        "Hogares de los cuatro primeros deciles",
        0.88,
        [4],
        "Grupo definido por el instrumento de caracterización socioeconómica.",
    ),
    (
        "trabajadores-plazo-fijo",
        "social_group",
        "Trabajadores con contrato a plazo fijo o por obra",
        0.6,
        [6],
        "Subconjunto de asalariados al que se extiende la cobertura del seguro.",
    ),
    (
        "pymes",
        "company",
        "Empresas con ingresos de hasta 25.000 UF",
        0.55,
        [2],
        "Tramo de menor tamaño alcanzado por la rebaja de timbres.",
    ),
    (
        "grandes-empresas",
        "company",
        "Empresas con ingresos sobre 100.000 UF",
        0.84,
        [1],
        "Tramo alcanzado por la sobretasa transitoria.",
    ),
    (
        "municipios",
        "institution",
        "Municipalidades",
        0.86,
        [5, 9],
        "Receptores de las transferencias del Fondo y obligados a informar su ejecución.",
    ),
    (
        "autoridad-presupuestaria",
        "institution",
        "Autoridad presupuestaria del ejecutivo",
        0.72,
        [5, 7, 9, 10],
        "Órgano que elabora el informe financiero, dicta el reglamento y recibe los reportes.",
    ),
    (
        "vocaria-hacienda",
        "person_role",
        "Vocería de Hacienda",
        0.65,
        [],
        "Rol institucional que comunica la posición del ejecutivo. Rol, nunca una persona.",
    ),
    (
        "asociacion-municipios",
        "person_role",
        "Presidencia de la asociación de municipios",
        0.6,
        [],
        "Rol gremial que representa a los municipios en el debate público.",
    ),
    (
        "federacion-empresarial",
        "person_role",
        "Economista de una federación empresarial",
        0.58,
        [],
        "Rol técnico que interviene por el sector empresarial.",
    ),
    (
        "confederacion-sindical",
        "person_role",
        "Analista de una confederación sindical",
        0.46,
        [],
        "Rol técnico que interviene por el sector sindical.",
    ),
    (
        "sector-construccion",
        "sector",
        "Construcción e infraestructura",
        0.44,
        [3, 8],
        "Sector alcanzado por el crédito a la inversión y el procedimiento abreviado.",
    ),
    (
        "costo-fiscal-neto",
        "fiscal_effect",
        "Costo fiscal neto del paquete",
        0.93,
        [1, 2, 3, 4, 5, 6],
        "Resultado agregado de las medidas de ingreso y gasto en un ejercicio.",
    ),
    (
        "prov-sobretasa",
        "provision",
        "Artículo 3° — Sobretasa transitoria",
        0.5,
        [1],
        "Ancla del grafo en el texto del articulado.",
    ),
]

# (id, kind, source, target, label, basis, direction, magnitude, horizon, causality, mechanism, refs)
EDGE_ROWS: list[tuple[str, ...]] = [
    (
        "e1",
        "taxes",
        "sobretasa-utilidades",
        "grandes-empresas",
        "grava las utilidades del tramo mayor",
        "document_explicit",
        "negative",
        "medium",
        "short_term",
        "direct",
        "Aumenta en 2 pp la tasa efectiva sobre la base imponible declarada.",
        ["prov:18216-05:1", "ev:1"],
    ),
    (
        "e2",
        "benefits",
        "aporte-hogares",
        "hogares-deciles-1-4",
        "transfiere ingreso mensual",
        "document_explicit",
        "positive",
        "large",
        "immediate",
        "direct",
        "Pago mensual de $42.000 por hogar sin contraprestación.",
        ["prov:18216-05:4", "ev:2"],
    ),
    (
        "e3",
        "funds",
        "fondo-territorial",
        "municipios",
        "financia inversión municipal",
        "document_explicit",
        "positive",
        "medium",
        "medium_term",
        "direct",
        "Transferencia anual equivalente a 0,18% del PIB destinada a proyectos.",
        ["prov:18216-05:5", "ev:3"],
    ),
    (
        "e4",
        "depends_on",
        "fondo-territorial",
        "reglamento-fondo",
        "no opera sin reglamento",
        "document_explicit",
        None,
        None,
        "short_term",
        "direct",
        "El artículo 7° carece de fórmula de distribución hasta que se dicte el reglamento.",
        ["prov:18216-05:10", "ev:4"],
    ),
    (
        "e5",
        "benefits",
        "credito-inversion",
        "sector-construccion",
        "abarata la inversión en activo fijo",
        "document_implicit",
        "positive",
        "medium",
        "medium_term",
        "indirect",
        "Reduce el costo después de impuestos de la inversión productiva.",
        ["prov:18216-05:3"],
    ),
    (
        "e6",
        "benefits",
        "rebaja-timbres",
        "pymes",
        "reduce el costo del crédito",
        "document_explicit",
        "positive",
        "small",
        "short_term",
        "indirect",
        "Elimina un impuesto de transacción sobre operaciones de crédito.",
        ["prov:18216-05:2"],
    ),
    (
        "e7",
        "expands",
        "seguro-cesantia",
        "trabajadores-plazo-fijo",
        "amplía la cobertura",
        "document_explicit",
        "positive",
        "medium",
        "short_term",
        "direct",
        "Aumenta de cinco a ocho el número máximo de giros del fondo solidario.",
        ["prov:18216-05:6"],
    ),
    (
        "e8",
        "restricts",
        "regla-gasto",
        "autoridad-presupuestaria",
        "limita el crecimiento del gasto",
        "document_explicit",
        "negative",
        "medium",
        "medium_term",
        "direct",
        "Fija un techo de 2,5% real anual a la formulación del gasto corriente.",
        ["prov:18216-05:7"],
    ),
    (
        "e9",
        "modifies",
        "procedimiento-ambiental",
        "sector-construccion",
        "acorta el plazo de evaluación",
        "document_explicit",
        "positive",
        "medium",
        "short_term",
        "direct",
        "Reduce a 90 días hábiles el plazo total del procedimiento bajo umbral.",
        ["prov:18216-05:8"],
    ),
    (
        "e10",
        "costs",
        "sobretasa-utilidades",
        "costo-fiscal-neto",
        "aporta recaudación",
        "document_implicit",
        "positive",
        "large",
        "short_term",
        "direct",
        "La recaudación proyectada compensa parte del gasto del paquete.",
        ["ev:5"],
    ),
    (
        "e11",
        "costs",
        "aporte-hogares",
        "costo-fiscal-neto",
        "aumenta el gasto",
        "document_implicit",
        "negative",
        "large",
        "immediate",
        "direct",
        "El gasto anual de la transferencia es el principal componente del costo.",
        ["ev:5", "prov:18216-05:4"],
    ),
    (
        "e12",
        "costs",
        "fondo-territorial",
        "costo-fiscal-neto",
        "aumenta el gasto",
        "document_implicit",
        "negative",
        "medium",
        "medium_term",
        "direct",
        "La dotación anual del Fondo se imputa al presupuesto central.",
        ["ev:5", "prov:18216-05:3"],
    ),
    (
        "e13",
        "assumes",
        "costo-fiscal-neto",
        "paquete-fiscal",
        "supone un crecimiento de 2,3%",
        "document_explicit",
        "uncertain",
        "unknown",
        "medium_term",
        "unknown",
        "La proyección de recaudación depende del crecimiento real supuesto.",
        ["ev:5", "ev:6"],
    ),
    (
        "e14",
        "assumes",
        "aporte-hogares",
        "hogares-deciles-1-4",
        "supone 92% de toma",
        "document_explicit",
        "uncertain",
        "medium",
        "short_term",
        "indirect",
        "El costo proyectado depende de que 92% de los hogares elegibles cobren el aporte.",
        ["ev:5"],
    ),
    (
        "e15",
        "regulates",
        "autoridad-presupuestaria",
        "municipios",
        "exige reporte trimestral",
        "document_explicit",
        "none",
        "small",
        "medium_term",
        "direct",
        "Obligación de informar la ejecución de los recursos del Fondo.",
        ["prov:18216-05:9"],
    ),
    (
        "e16",
        "affects",
        "paquete-fiscal",
        "costo-fiscal-neto",
        "determina el resultado fiscal",
        "document_implicit",
        "mixed",
        "large",
        "medium_term",
        "direct",
        "El resultado neto es la suma de las medidas de ingreso y de gasto.",
        ["ev:5"],
    ),
    (
        "e17",
        "costs",
        "sobretasa-utilidades",
        "sector-construccion",
        "encarece el capital de las firmas mayores",
        "inferred",
        "negative",
        "small",
        "medium_term",
        "indirect",
        "Efecto de segundo orden vía costo del capital; no está en el texto.",
        ["ev:10"],
    ),
    (
        "e18",
        "benefits",
        "fondo-territorial",
        "sector-construccion",
        "aumenta la demanda de obras",
        "inferred",
        "positive",
        "medium",
        "medium_term",
        "indirect",
        "La inversión municipal se ejecuta mayoritariamente vía contratos de obra.",
        ["ev:11"],
    ),
    (
        "e19",
        "depends_on",
        "fondo-territorial",
        "autoridad-presupuestaria",
        "depende de la fórmula central",
        "document_explicit",
        None,
        None,
        "medium_term",
        "direct",
        "La fórmula de distribución la fija el nivel central, no el municipal.",
        ["prov:18216-05:10"],
    ),
    (
        "e20",
        "affects",
        "regla-gasto",
        "aporte-hogares",
        "compite por espacio fiscal",
        "inferred",
        "uncertain",
        "unknown",
        "medium_term",
        "indirect",
        "Un techo al gasto corriente restringe la prórroga de la transferencia.",
        [],
    ),
    (
        "e21",
        "replaces",
        "seguro-cesantia",
        "trabajadores-plazo-fijo",
        "sustituye el tope anterior de cinco giros",
        "document_explicit",
        None,
        None,
        "short_term",
        "direct",
        "El nuevo tope de ocho giros reemplaza al de cinco.",
        ["prov:18216-05:6"],
    ),
    (
        "e22",
        "modifies",
        "credito-inversion",
        "grandes-empresas",
        "acota el beneficio por el tope anual",
        "document_explicit",
        "mixed",
        "small",
        "medium_term",
        "direct",
        "El tope de 8.000 UF limita el crédito para contribuyentes de mayor tamaño.",
        ["prov:18216-05:3"],
    ),
    (
        "e23",
        "affects",
        "vocaria-hacienda",
        "costo-fiscal-neto",
        "comunica la cifra del informe",
        "external_evidence",
        "none",
        "unknown",
        "immediate",
        "unknown",
        "La vocería difunde la estimación del informe financiero.",
        ["ev:14"],
    ),
    (
        "e24",
        "affects",
        "asociacion-municipios",
        "fondo-territorial",
        "cuestiona el calendario de entrada en vigor",
        "external_evidence",
        "none",
        "unknown",
        "short_term",
        "unknown",
        "El gremio municipal sostiene que el Fondo no operará en 2027.",
        ["ev:15"],
    ),
    (
        "e25",
        "affects",
        "federacion-empresarial",
        "sobretasa-utilidades",
        "proyecta una caída de inversión",
        "external_evidence",
        "uncertain",
        "unknown",
        "medium_term",
        "unknown",
        "La federación proyecta una respuesta de inversión que el informe no modela.",
        ["ev:10"],
    ),
    (
        "e26",
        "affects",
        "confederacion-sindical",
        "aporte-hogares",
        "valora el alivio inmediato",
        "external_evidence",
        "none",
        "unknown",
        "immediate",
        "unknown",
        "La confederación interpreta el diseño del paquete como alivio de corto plazo.",
        ["ev:11"],
    ),
    (
        "e27",
        "restricts",
        "procedimiento-ambiental",
        "municipios",
        "acorta los plazos de tramitación de obras",
        "document_implicit",
        "positive",
        "small",
        "short_term",
        "indirect",
        "Muchos proyectos municipales caen bajo el umbral de 200.000 UF.",
        ["prov:18216-05:8", "ev:11"],
    ),
    (
        "e28",
        "taxes",
        "paquete-fiscal",
        "grandes-empresas",
        "concentra la carga en el tramo mayor",
        "document_implicit",
        "negative",
        "medium",
        "short_term",
        "direct",
        "La única medida de mayor recaudación recae sobre el tramo sobre 100.000 UF.",
        ["prov:18216-05:1", "ev:1"],
    ),
    (
        "e29",
        "expands",
        "paquete-fiscal",
        "municipios",
        "amplía los recursos de inversión local",
        "document_explicit",
        "positive",
        "medium",
        "medium_term",
        "direct",
        "El Fondo es la principal medida de descentralización del paquete.",
        ["prov:18216-05:5"],
    ),
    (
        "e30",
        "depends_on",
        "prov-sobretasa",
        "paquete-fiscal",
        "ancla el grafo en el articulado",
        "document_explicit",
        None,
        None,
        "immediate",
        "direct",
        "El artículo 3° es la disposición que crea la sobretasa.",
        ["prov:18216-05:1"],
    ),
]


def build_topic_graph() -> dict[str, Any]:
    """Warm phase 3. Every edge names its evidence and says whether the document
    asserted the relation or Aleph inferred it."""
    nodes = []
    for nid, kind, label, salience, provs, description in NODE_ROWS:
        nodes.append(
            {
                "id": f"node:{nid}",
                "kind": kind,
                "label": label,
                "aliases": [],
                "description": description,
                "salience": salience,
                "provision_ids": [pid(n) for n in provs],
                "proposition_ids": [ppid(r["n"]) for r in PROPOSITION_ROWS if r["prov"] in provs][
                    :3
                ],
                "evidence_refs": [pid(n) for n in provs][:2],
                "mentions": [],
                "attributes": [],
                "external_ids": [],
                "confidence": conf(0.8, 0.74, [], None)
                if kind != "person_role"
                else conf(0.7, 0.66, [], "Rol genérico sintético."),
            }
        )

    edges = []
    for row in EDGE_ROWS:
        (
            eid,
            kind,
            src,
            tgt,
            label,
            basis,
            direction,
            magnitude,
            horizon,
            causality,
            mechanism,
            refs,
        ) = row
        edges.append(
            {
                "id": f"edge:{eid}",
                "kind": kind,
                "source": f"node:{src}",
                "target": f"node:{tgt}",
                "label": label,
                "basis": basis,
                "direction": direction,
                "magnitude": magnitude,
                "time_horizon": horizon,
                "causality": causality,
                "mechanism": mechanism,
                "quantity": None,
                "money": None,
                "conditions": [],
                "evidence_refs": list(refs),
                "provenance": {
                    "source_id": DOC_ID,
                    "source_kind": "document" if basis.startswith("document") else "derived",
                    "url": None,
                    "retrieved_at": None,
                    "span": None,
                    "extractor": EXTRACTOR,
                },
                "confidence": conf(
                    0.82 if basis.startswith("document") else 0.48,
                    0.75,
                    [
                        (
                            "primary_source_coverage",
                            "raises" if basis.startswith("document") else "lowers",
                            "Relación leída del texto."
                            if basis.startswith("document")
                            else "Relación inferida por Aleph, no afirmada por el documento.",
                        )
                    ],
                    None
                    if basis.startswith("document")
                    else "Arista inferida: debe mostrarse como provisional.",
                ),
                "note": None,
            }
        )

    inferred = sum(1 for e in edges if e["basis"] == "inferred")
    unsupported = sum(1 for e in edges if not e["evidence_refs"])
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "document_id": DOC_ID,
        "generated_at": GENERATED_AT,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "inferred_edge_count": inferred,
            "unsupported_edge_count": unsupported,
            "isolated_node_count": sum(1 for n in nodes if n["id"] not in linked),
        },
        "notes": (
            "Las aristas con basis 'inferred' o 'external_evidence' NO son afirmaciones del "
            "documento y deben mostrarse como razonamiento de Aleph."
        ),
    }


# --------------------------------------------------------------------------- #
# Warm phase 4 — search vocabulary
# --------------------------------------------------------------------------- #


def _term(
    text: str,
    source: str,
    weight: float,
    must_quote: bool = False,
    derived_from: str | None = None,
    ambiguity: str | None = None,
    queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": None,
        "text": text,
        "language": "es-CL",
        "weight": weight,
        "source": source,
        "normalized_form": text.lower(),
        "must_quote": must_quote,
        "ambiguity_note": ambiguity,
        "derived_from": derived_from,
        "span": None,
        "generated_queries": queries or [],
    }


def _query(
    text: str,
    target: str,
    tier: str | None,
    priority: int,
    rationale: str,
    syntax: str = "plain",
    date_from: str | None = "2026-05-01",
) -> dict[str, Any]:
    return {
        "id": None,
        "query_text": text,
        "target_source_type": target,
        "target_source_ids": [],
        "expected_evidence_tier": tier,
        "language": "es-CL",
        "syntax": syntax,
        "date_from": date_from,
        "date_to": None,
        "additional_terms": [],
        "priority": priority,
        "rationale": rationale,
    }


def build_search_vocabulary() -> dict[str, Any]:
    """Warm phase 4. Published because the vocabulary determines what evidence
    could possibly have been found."""
    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "document_id": DOC_ID,
        "generated_at": GENERATED_AT,
        "primary_language": "es-CL",
        "target_languages": ["es-CL", "es"],
        "term_sets": {
            "official_names": [
                _term(
                    "Proyecto de ley de estabilización fiscal y financiamiento territorial",
                    "title",
                    0.72,
                    must_quote=True,
                    derived_from="identity.title",
                    queries=[
                        _query(
                            '"proyecto de ley de estabilización fiscal y financiamiento territorial"',
                            "legislature",
                            "legislative_record",
                            1,
                            "El título formal encuentra el expediente, aunque casi nadie lo use en la discusión pública.",
                            syntax="phrase",
                        ),
                        _query(
                            '"estabilización fiscal y financiamiento territorial" informe financiero',
                            "government_body",
                            "official_technical_report",
                            2,
                            "Busca el informe financiero adjunto en repositorios oficiales.",
                        ),
                    ],
                ),
                _term(
                    "Fondo de Estabilización Territorial",
                    "heading",
                    0.66,
                    must_quote=True,
                    derived_from="sec:3.2",
                ),
            ],
            "common_names": [
                _term(
                    "paquete fiscal",
                    "model_expansion",
                    0.58,
                    ambiguity="Colisiona con cualquier otro paquete tributario; requiere filtrado por fecha.",
                    queries=[
                        _query(
                            "paquete fiscal municipios aporte hogares",
                            "news_outlet",
                            "journalism",
                            2,
                            "Recupera cobertura que nunca nombra el número de boletín.",
                        ),
                    ],
                ),
                _term("aporte de estabilización", "provision_heading", 0.62, derived_from=pid(4)),
            ],
            "identifiers": [
                _term(
                    "18.216-05",
                    "identifier",
                    0.94,
                    must_quote=True,
                    derived_from="identity.legislative_identifier",
                    queries=[
                        _query(
                            '"18.216-05"',
                            "legislature",
                            "legislative_record",
                            1,
                            "Precisión muy alta: encuentra el expediente y no el comentario sobre él.",
                            syntax="phrase",
                            date_from=None,
                        ),
                        _query(
                            '"18.216-05" tramitación comisión',
                            "government_body",
                            "legislative_record",
                            3,
                            "Recupera actas y estados de tramitación.",
                        ),
                    ],
                ),
                _term(
                    "boletín 18216-05", "identifier", 0.7, derived_from="identity.identifiers[0]"
                ),
            ],
            "abbreviations": [
                _term(
                    "UF",
                    "abbreviation_expansion",
                    0.2,
                    ambiguity="Sigla de uso masivo; sólo sirve combinada con otro término.",
                ),
                _term("unidad de fomento", "abbreviation_expansion", 0.28),
            ],
            "political_terminology": [
                _term(
                    "alza de impuestos",
                    "model_expansion",
                    0.55,
                    ambiguity="Término en disputa. Se recoge para ENCONTRAR todas las posiciones, no para ponderar ninguna.",
                ),
                _term(
                    "alivio a los hogares",
                    "model_expansion",
                    0.5,
                    ambiguity="Encuadre favorable en circulación; registrarlo no implica adoptarlo.",
                ),
                _term("descentralización fiscal", "model_expansion", 0.52),
            ],
            "technical_terminology": [
                _term(
                    "impuesto de primera categoría",
                    "definition",
                    0.64,
                    queries=[
                        _query(
                            "elasticidad inversión sobretasa impuesto primera categoría",
                            "academic",
                            "peer_reviewed",
                            2,
                            "El vocabulario técnico alcanza literatura que la prensa nunca cita.",
                            date_from=None,
                        ),
                    ],
                ),
                _term("ingresos propios permanentes", "definition", 0.6, derived_from="def:2"),
                _term("Fondo de Cesantía Solidario", "definition", 0.58, must_quote=True),
            ],
            "sector_terminology": [
                _term(
                    "inversión municipal",
                    "entity",
                    0.56,
                    queries=[
                        _query(
                            "ejecución inversión municipal rezago serie",
                            "statistics_agency",
                            "statistical_dataset",
                            1,
                            "Dirigida a portales estadísticos, no a prensa: sin ella el conjunto se llena de comentario.",
                        ),
                    ],
                ),
                _term("activo fijo productivo", "entity", 0.46),
            ],
            "synonyms": [],
            "provision_names": [
                _term(
                    "sobretasa transitoria a las utilidades",
                    "provision_heading",
                    0.78,
                    derived_from=pid(1),
                    queries=[
                        _query(
                            '"sobretasa" utilidades 100.000 UF',
                            "news_outlet",
                            "journalism",
                            2,
                            "El debate se concentra en una cláusula; las consultas de documento completo no la encuentran.",
                        ),
                    ],
                ),
                _term(
                    "procedimiento abreviado de evaluación ambiental",
                    "provision_heading",
                    0.68,
                    derived_from=pid(8),
                ),
                _term(
                    "regla de crecimiento del gasto corriente",
                    "provision_heading",
                    0.6,
                    derived_from=pid(7),
                ),
            ],
            "actor_terms": [
                _term("vocería de Hacienda", "entity", 0.5),
                _term("asociación de municipios", "entity", 0.54),
                _term("federación empresarial", "entity", 0.44),
                _term("confederación sindical", "entity", 0.42),
            ],
        },
        "expansion_notes": (
            "Los términos con source 'title', 'heading', 'definition', 'identifier' y "
            "'provision_heading' provienen del texto. Los marcados 'model_expansion' son "
            "conjeturas del generador y deben pesar menos al juzgar la cobertura."
        ),
        "known_gaps": [
            "synonyms: vacío. No se generaron traducciones ni parafraseos: la expansión multilingüe requiere recuperación en línea, que está deshabilitada.",
            "common_names: sólo dos términos, ambos generados. No se observó un nombre de circulación pública para el documento.",
            "Ninguna consulta se ejecutó realmente: bajo ALEPH_RETRIEVAL_MODE=manual la recuperación no realiza peticiones de red.",
        ],
    }


# --------------------------------------------------------------------------- #
# Warm phase 5 — evidence pool
# --------------------------------------------------------------------------- #

EVIDENCE_ROWS: list[dict[str, Any]] = [
    {
        "n": 1,
        "tier": "primary_document",
        "strength": "high",
        "independence": "original_reporting",
        "src": (DOC_ID, "Articulado del proyecto — artículo 3°", None, "2026-05-12"),
        "statement": "El artículo 3° del articulado establece una sobretasa de dos puntos porcentuales para contribuyentes con ingresos brutos anuales sobre 100.000 UF, por los años tributarios 2027 a 2031.",
        "spans": [
            span(
                "una sobretasa de dos puntos porcentuales sobre la base imponible del impuesto de primera categoría",
                page=3,
                section_id="sec:2.1",
                char_start=1880,
            )
        ],
        "question": "¿Qué tasa y qué umbral fija el texto para la sobretasa?",
        "relevance": 0.98,
        "can": [
            "que el texto fija una sobretasa de 2 puntos porcentuales",
            "que el umbral de aplicación son 100.000 UF de ingresos brutos anuales",
        ],
        "cannot": [
            "que la sobretasa recaudará el monto proyectado",
            "que la sobretasa se mantendrá tras 2031",
        ],
        "supports": ["clm:3"],
        "contradicts": [],
        "quantities": [quantity(2.0, "percentage_point", "dos puntos porcentuales", "pp")],
        "money": [],
        "why": "El texto operativo es decisivo sobre lo que la norma dice y no dice nada sobre sus efectos.",
    },
    {
        "n": 2,
        "tier": "primary_document",
        "strength": "high",
        "independence": "original_reporting",
        "src": (DOC_ID, "Articulado del proyecto — artículo 6°", None, "2026-05-12"),
        "statement": "El artículo 6° crea un aporte mensual de $42.000 por hogar para los cuatro primeros deciles, pagadero durante veinticuatro meses.",
        "spans": [
            span(
                "un aporte mensual de estabilización, de $42.000 por hogar",
                page=5,
                section_id="sec:3.1",
                char_start=450,
            )
        ],
        "question": "¿Qué monto y qué duración fija el texto para la transferencia a hogares?",
        "relevance": 0.97,
        "can": ["que el monto mensual por hogar es $42.000", "que el pago dura veinticuatro meses"],
        "cannot": [
            "que todos los hogares elegibles lo recibirán",
            "que el aporte compensará el efecto de otras medidas",
        ],
        "supports": ["clm:4"],
        "contradicts": [],
        "quantities": [quantity(24.0, "duration", "veinticuatro meses", "meses")],
        "money": [money(42000.0, "unit", 2026, "monthly")],
        "why": "Establece el contenido de la norma; la incidencia efectiva es otra cuestión.",
    },
    {
        "n": 3,
        "tier": "primary_document",
        "strength": "high",
        "independence": "original_reporting",
        "src": (DOC_ID, "Articulado del proyecto — artículo 7°", None, "2026-05-12"),
        "statement": "El artículo 7° dota el Fondo de Estabilización Territorial con recursos anuales equivalentes al 0,18% del producto interno bruto.",
        "spans": [
            span(
                "se dotará anualmente con recursos equivalentes al 0,18% del producto interno bruto",
                page=6,
                section_id="sec:3.2",
                char_start=420,
            )
        ],
        "question": "¿Qué dotación anual fija el texto para el fondo municipal?",
        "relevance": 0.96,
        "can": [
            "que la dotación anual es 0,18% del PIB",
            "que la fórmula pondera población, ingresos propios por habitante y ruralidad",
        ],
        "cannot": [
            "que los recursos se transferirán efectivamente en 2027",
            "qué recibirá cada municipio en particular",
        ],
        "supports": ["clm:2"],
        "contradicts": [],
        "quantities": [
            quantity(0.18, "percentage", "0,18% del producto interno bruto", "% del PIB")
        ],
        "money": [money(0.18, "percent_of_gdp", 2027, "annual")],
        "why": "Fija la magnitud de la dotación; nada dice sobre el calendario de ejecución.",
    },
    {
        "n": 4,
        "tier": "primary_document",
        "strength": "high",
        "independence": "original_reporting",
        "src": (
            DOC_ID,
            "Articulado del proyecto — artículo primero transitorio",
            None,
            "2026-05-12",
        ),
        "statement": "El artículo primero transitorio entrega a un reglamento, a dictarse dentro de 180 días desde la publicación, la fórmula de distribución del Fondo.",
        "spans": [
            span(
                "Un reglamento, dictado dentro de los ciento ochenta días siguientes a la publicación de esta ley",
                page=9,
                section_id="sec:4.4",
                char_start=1540,
            )
        ],
        "question": "¿De qué depende que el Fondo pueda transferir recursos?",
        "relevance": 0.93,
        "can": [
            "que la fórmula de distribución no está en la ley sino en un reglamento pendiente",
            "que el plazo para dictarlo es de 180 días desde la publicación",
        ],
        "cannot": [
            "que el reglamento se dictará dentro del plazo",
            "en qué fecha comenzarán las transferencias",
        ],
        "supports": ["clm:14"],
        "contradicts": ["clm:13"],
        "quantities": [quantity(180.0, "duration", "ciento ochenta días", "días")],
        "money": [],
        "why": "Establece una dependencia normativa; no permite predecir el comportamiento administrativo.",
    },
    {
        "n": 5,
        "tier": "official_technical_report",
        "strength": "medium",
        "independence": "original_reporting",
        "src": (
            "src:demo-informe-financiero",
            "Informe financiero adjunto (documento de demostración)",
            "autoridad presupuestaria del ejecutivo (rol genérico)",
            "2026-07-02",
        ),
        "statement": "El informe financiero adjunto proyecta un costo fiscal neto de 0,4% del PIB para 2027, bajo un supuesto de crecimiento real de 2,3% anual.",
        "spans": [
            span(
                "El costo fiscal neto del conjunto de medidas se estima en 0,4% del PIB para el ejercicio 2027.",
                page=11,
                section_id="sec:5.2",
                char_start=320,
            ),
            span(
                "Las proyecciones suponen un crecimiento real del producto de 2,3% anual.",
                page=10,
                section_id="sec:5.1",
                char_start=210,
            ),
        ],
        "question": "¿Cuál es el costo fiscal neto estimado del paquete para 2027?",
        "relevance": 0.9,
        "can": [
            "que el órgano responsable estimó un costo neto de 0,4% del PIB para 2027",
            "que esa estimación depende de un crecimiento supuesto de 2,3%",
        ],
        "cannot": [
            "que el costo efectivo será 0,4% del PIB",
            "que no existan otras estimaciones con supuestos distintos",
        ],
        "supports": ["clm:1"],
        "contradicts": [],
        "quantities": [
            quantity(0.4, "percentage", "0,4% del PIB", "% del PIB"),
            quantity(2.3, "percentage", "2,3% anual", "% real anual"),
        ],
        "money": [money(0.4, "percent_of_gdp", 2027, "annual")],
        "why": "Un informe de costeo es decisivo sobre lo que su autor estimó y no sobre si la estimación se cumplirá.",
    },
    {
        "n": 6,
        "tier": "official_technical_report",
        "strength": "medium",
        "independence": "original_reporting",
        "src": (
            "src:demo-informe-financiero",
            "Informe financiero adjunto — sección de limitaciones",
            "autoridad presupuestaria del ejecutivo (rol genérico)",
            "2026-07-02",
        ),
        "statement": "El propio informe financiero declara que no incorpora una respuesta conductual de la inversión privada a la sobretasa.",
        "spans": [
            span(
                "El presente ejercicio no incorpora una respuesta conductual de la inversión.",
                page=12,
                section_id="sec:5.3",
                char_start=150,
            )
        ],
        "question": "¿La estimación oficial incluye el efecto de la sobretasa sobre la inversión?",
        "relevance": 0.88,
        "can": [
            "que la estimación oficial excluye explícitamente la respuesta de inversión",
            "que el propio órgano advierte que la recaudación neta podría ser menor",
        ],
        "cannot": [
            "cuál sería la magnitud de esa respuesta",
            "que la respuesta de inversión sea grande o pequeña",
        ],
        "supports": ["clm:5"],
        "contradicts": [],
        "quantities": [],
        "money": [],
        "why": "Una limitación declarada acota lo que la propia estimación puede sostener; no cuantifica lo omitido.",
    },
    {
        "n": 7,
        "tier": "statistical_dataset",
        "strength": "medium",
        "independence": "original_reporting",
        "src": (
            "src:demo-serie-carga-tributaria",
            "Serie sintética de carga tributaria 1995–2025 (conjunto de demostración Aleph)",
            "conjunto de demostración Aleph",
            "2026-06-30",
        ),
        "statement": "En la serie sintética de carga tributaria del conjunto de demostración, dos aumentos anuales de los últimos treinta años superan el aumento proyectado para este paquete.",
        "spans": [
            span(
                "1998: +1,4 pp del PIB · 2014: +1,1 pp del PIB · proyección 2027: +0,6 pp del PIB",
                page=None,
                section_id=None,
                char_start=0,
            )
        ],
        "question": "¿Es el aumento tributario proyectado el mayor de los últimos treinta años?",
        "relevance": 0.85,
        "can": [
            "que en la serie de demostración existen dos aumentos anuales mayores que el proyectado"
        ],
        "cannot": [
            "que la serie describa la recaudación real de ninguna jurisdicción",
            "que la comparación se sostenga bajo otra definición de carga tributaria",
        ],
        "supports": [],
        "contradicts": ["clm:3"],
        "quantities": [
            quantity(1.4, "percentage_point", "+1,4 pp del PIB", "pp del PIB"),
            quantity(0.6, "percentage_point", "+0,6 pp del PIB", "pp del PIB"),
        ],
        "money": [],
        "why": "Una serie permite ordenar magnitudes; su validez depende íntegramente de la definición usada, y esta serie es sintética.",
    },
    {
        "n": 8,
        "tier": "statistical_dataset",
        "strength": "medium",
        "independence": "original_reporting",
        "src": (
            "src:demo-serie-municipal",
            "Serie sintética de ingresos propios municipales por habitante (conjunto de demostración Aleph)",
            "conjunto de demostración Aleph",
            "2026-06-30",
        ),
        "statement": "En la serie municipal sintética, la razón entre el decil superior e inferior de ingresos propios por habitante es de 9,3 a 1.",
        "spans": [
            span(
                "Razón decil 10 / decil 1 de ingresos propios por habitante: 9,3",
                page=None,
                section_id=None,
                char_start=0,
            )
        ],
        "question": "¿Qué tan desigual es la base de ingresos propios que la fórmula del Fondo debe compensar?",
        "relevance": 0.72,
        "can": [
            "que la dispersión de ingresos propios por habitante es amplia en la serie de demostración"
        ],
        "cannot": [
            "que la fórmula del Fondo compense esa dispersión",
            "que estas razones correspondan a municipios reales",
        ],
        "supports": ["clm:2"],
        "contradicts": [],
        "quantities": [quantity(9.3, "ratio", "9,3", None)],
        "money": [],
        "why": "Describe la dispersión de la base, no el efecto de la fórmula que aún no existe.",
    },
    {
        "n": 9,
        "tier": "legislative_record",
        "strength": "low",
        "independence": "original_reporting",
        "src": (
            "src:demo-acta-comision",
            "Acta sintética de la comisión — sesión del 18 de junio de 2026",
            "registro legislativo de demostración",
            "2026-06-18",
        ),
        "statement": "El acta sintética registra que la indicación que incorporó el procedimiento ambiental abreviado fue presentada por la comisión sin dejar constancia de su origen.",
        "spans": [
            span(
                "Se aprueba la indicación que incorpora el artículo 10, sin constancia del origen de la propuesta.",
                page=4,
                section_id=None,
                char_start=1180,
            )
        ],
        "question": "¿Quién propuso el procedimiento ambiental abreviado?",
        "relevance": 0.6,
        "can": ["que el acta no consigna el origen de la indicación"],
        "cannot": [
            "que la indicación se haya originado en algún sector en particular",
            "que no exista otro registro donde conste el origen",
        ],
        "supports": [],
        "contradicts": ["clm:8"],
        "quantities": [],
        "money": [],
        "why": "Un acta establece lo que quedó consignado. El silencio del acta no prueba una hipótesis sobre el origen ni la refuta.",
    },
    {
        "n": 10,
        "tier": "peer_reviewed",
        "strength": "medium",
        "independence": "original_reporting",
        "src": (
            "src:demo-estudio-elasticidad",
            "Estudio sintético sobre elasticidad de la inversión a sobretasas transitorias",
            "revista de demostración Aleph",
            "2025-11-14",
        ),
        "statement": "El estudio sintético reporta un rango de respuesta de la inversión de entre -0,2 y -1,8 puntos ante sobretasas transitorias de dos puntos, con intervalos amplios.",
        "spans": [
            span(
                "El efecto estimado se sitúa entre -0,2 y -1,8 puntos, con intervalos de confianza que incluyen cero en cuatro de las siete especificaciones.",
                page=12,
                section_id=None,
                char_start=430,
            )
        ],
        "question": "¿Cuánto cae la inversión privada ante una sobretasa transitoria de dos puntos?",
        "relevance": 0.78,
        "can": [
            "que las estimaciones disponibles cubren un rango amplio",
            "que en varias especificaciones el efecto no se distingue de cero",
        ],
        "cannot": [
            "que el efecto sea exactamente -1,2 puntos",
            "que el rango se traslade a esta jurisdicción y a este diseño",
        ],
        "supports": [],
        "contradicts": ["clm:6"],
        "quantities": [
            quantity(-1.8, "percentage_point", "-1,8 puntos", "pp"),
            quantity(-0.2, "percentage_point", "-0,2 puntos", "pp"),
        ],
        "money": [],
        "why": "Un rango amplio es evidencia contra una cifra puntual, no evidencia a favor de otra cifra puntual.",
    },
    {
        "n": 11,
        "tier": "expert_analysis",
        "strength": "low",
        "independence": "original_reporting",
        "src": (
            "src:demo-centro-estudios",
            "Nota sintética sobre rezago de ejecución de inversión municipal",
            "centro de estudios de demostración",
            "2026-07-20",
        ),
        "statement": "La nota sintética estima que la ejecución de nuevos fondos de inversión municipal comienza, en promedio, catorce meses después de su creación legal.",
        "spans": [
            span(
                "El rezago medio entre creación legal y primera ejecución es de catorce meses en los cinco casos revisados.",
                page=3,
                section_id=None,
                char_start=220,
            )
        ],
        "question": "¿Cuánto tarda un fondo de inversión municipal en ejecutar recursos?",
        "relevance": 0.66,
        "can": ["que en los cinco casos revisados el rezago medio fue de catorce meses"],
        "cannot": [
            "que este Fondo tendrá el mismo rezago",
            "que cinco casos sean una base suficiente para una expectativa general",
        ],
        "supports": ["clm:14"],
        "contradicts": [],
        "quantities": [quantity(14.0, "duration", "catorce meses", "meses")],
        "money": [],
        "why": "Cinco casos son un indicio, no una base. La relevancia es real pero acotada.",
    },
    {
        "n": 12,
        "tier": "journalism",
        "strength": "low",
        "independence": "original_reporting",
        "src": (
            "src:demo-boletin-economico",
            "Boletín Económico — análisis del informe financiero",
            "Boletín Económico",
            "2026-08-05",
        ),
        "statement": "Un artículo de análisis contrasta la proyección oficial con el rango del estudio de elasticidad y señala que el informe no modela la respuesta de inversión.",
        "spans": [
            span(
                "El informe deja fuera la respuesta de inversión, que la literatura sitúa en un rango amplio.",
                page=None,
                section_id=None,
                char_start=1240,
            )
        ],
        "question": "¿Qué diferencias señala la cobertura entre la proyección oficial y la literatura?",
        "relevance": 0.5,
        "can": ["que un medio publicó ese contraste el 5 de agosto de 2026"],
        "cannot": ["que el contraste sea correcto", "que la proyección oficial sea errónea"],
        "supports": [],
        "contradicts": [],
        "quantities": [],
        "money": [],
        "why": "Un artículo establece que algo fue publicado. Lo que afirma se decide con la evidencia primaria, no con el artículo.",
    },
    {
        "n": 13,
        "tier": "journalism",
        "strength": "low",
        "independence": "original_reporting",
        "src": (
            "src:demo-el-contrapunto",
            "El Contrapunto — reportaje sobre el calendario del Fondo",
            "El Contrapunto",
            "2026-08-05",
        ),
        "statement": "Un reportaje informa que, a la fecha de publicación, no constaba la dictación del reglamento del Fondo.",
        "spans": [
            span(
                "A la fecha no consta la dictación del reglamento que debe fijar la fórmula de distribución.",
                page=None,
                section_id=None,
                char_start=860,
            )
        ],
        "question": "¿Se ha dictado el reglamento del Fondo?",
        "relevance": 0.55,
        "can": ["que al 5 de agosto de 2026 el medio no encontró constancia del reglamento"],
        "cannot": ["que el reglamento no exista", "que no vaya a dictarse dentro del plazo legal"],
        "supports": ["clm:14"],
        "contradicts": [],
        "quantities": [],
        "money": [],
        "why": "La ausencia de constancia en una búsqueda periodística no equivale a la ausencia del acto.",
    },
    {
        "n": 14,
        "tier": "political_statement",
        "strength": "low",
        "independence": "original_reporting",
        "src": (
            "src:demo-declaracion-hacienda",
            "Punto de prensa de la vocería de Hacienda (declaración de demostración)",
            "vocería de Hacienda (rol genérico)",
            "2026-08-04",
        ),
        "statement": "En un punto de prensa, la vocería de Hacienda afirmó que el costo neto del paquete es de 0,4% del PIB y que ningún hogar de los cuatro primeros deciles pagará más impuestos.",
        "spans": [
            span(
                "El costo neto es de cuatro décimas del producto y ningún hogar de los primeros cuatro deciles pagará más impuestos.",
                page=None,
                section_id=None,
                char_start=0,
            )
        ],
        "question": "¿Qué afirmó públicamente el ejecutivo sobre el costo del paquete?",
        "relevance": 0.95,
        "can": ["que la afirmación fue hecha públicamente el 4 de agosto de 2026"],
        "cannot": [
            "que la cifra sea correcta",
            "que la afirmación sobre los deciles cubra la incidencia indirecta",
        ],
        "supports": ["clm:1", "clm:4"],
        "contradicts": [],
        "quantities": [],
        "money": [],
        "why": "Una declaración es evidencia máxima de que se dijo algo y evidencia débil de que lo dicho sea verdadero.",
    },
    {
        "n": 15,
        "tier": "political_statement",
        "strength": "low",
        "independence": "original_reporting",
        "src": (
            "src:demo-declaracion-municipios",
            "Declaración de la presidencia de la asociación de municipios (declaración de demostración)",
            "presidencia de la asociación de municipios (rol genérico)",
            "2026-08-05",
        ),
        "statement": "La presidencia de la asociación de municipios declaró que el Fondo no operará antes de 2028 porque el reglamento aún no existe.",
        "spans": [
            span(
                "Sin reglamento no hay fórmula, y sin fórmula no hay transferencia: esto no parte antes de 2028.",
                page=None,
                section_id=None,
                char_start=0,
            )
        ],
        "question": "¿Qué sostiene el gremio municipal sobre el calendario del Fondo?",
        "relevance": 0.92,
        "can": ["que la afirmación fue hecha públicamente el 5 de agosto de 2026"],
        "cannot": ["que el Fondo efectivamente no operará antes de 2028"],
        "supports": ["clm:14"],
        "contradicts": [],
        "quantities": [],
        "money": [],
        "why": "Igual que cualquier declaración: establece la posición del actor, no el hecho del mundo.",
    },
    {
        "n": 16,
        "tier": "primary_document",
        "strength": "insufficient",
        "independence": "original_reporting",
        "src": (
            DOC_ID,
            "Articulado del proyecto — ausencia de norma de difusión",
            None,
            "2026-05-12",
        ),
        "statement": "El articulado no contiene ninguna disposición sobre difusión o información a los contribuyentes acerca de la rebaja del impuesto de timbres.",
        "spans": [
            span(
                "Artículo 4°.— Redúcese a cero, hasta el 31 de diciembre de 2029, la tasa del impuesto de timbres y estampillas",
                page=4,
                section_id="sec:2.2",
                char_start=620,
            )
        ],
        "question": "¿Qué proporción de las empresas pequeñas conoce la rebaja del impuesto de timbres?",
        "relevance": 0.08,
        "can": ["que el texto no impone una obligación de difusión"],
        "cannot": [
            "qué proporción de empresas conoce la medida",
            "que el desconocimiento sea alto o bajo",
        ],
        "supports": [],
        "contradicts": [],
        "quantities": [],
        "money": [],
        "why": "El texto no puede responder una pregunta sobre conocimiento del público. Se registra precisamente para mostrar que la pregunta quedó sin evidencia.",
    },
]


def build_evidence_items() -> list[dict[str, Any]]:
    """Warm phase 5. Every item records what it can and cannot establish."""
    items = []
    for row in EVIDENCE_ROWS:
        sid, title, publisher, published = row["src"]
        items.append(
            {
                "id": f"ev:{row['n']}",
                "source_ref": source_ref(
                    sid,
                    title,
                    row["tier"],
                    publisher,
                    published,
                    row["independence"],
                    url=TARGET_DOCUMENT_URL if sid == DOC_ID else None,
                ),
                "tier": row["tier"],
                "statement": row["statement"],
                "spans": row["spans"],
                "retrieved_at": RETRIEVED_AT,
                "supports": row["supports"],
                "contradicts": row["contradicts"],
                "evidential_relevance": {
                    "question": row["question"],
                    "relevance": row["relevance"],
                    "can_establish": row["can"],
                    "cannot_establish": row["cannot"],
                    "why": row["why"],
                },
                "strength": row["strength"],
                "independence": row["independence"],
                "derived_from_evidence_id": None,
                "quantities": row["quantities"],
                "money": row["money"],
                "confidence": conf(
                    {"high": 0.9, "medium": 0.68, "low": 0.42, "insufficient": 0.15}[
                        row["strength"]
                    ],
                    0.74,
                    [
                        (
                            "primary_source_coverage",
                            "raises" if row["tier"] == "primary_document" else "neutral",
                            "Pasaje citado del texto operativo."
                            if row["tier"] == "primary_document"
                            else "El ítem no es el documento primario.",
                        ),
                        (
                            "source_independence",
                            "neutral",
                            "Ítem original, no una reproducción de otro.",
                        ),
                    ],
                    "Todo el conjunto es sintético: ninguna fuente real fue consultada.",
                ),
                "uncertainties": [
                    unc(
                        "El ítem pertenece a un conjunto sintético y no corresponde a ninguna fuente real.",
                        "out_of_scope",
                        "Ejecutar la recuperación en línea sobre el registro de fuentes real.",
                    )
                ],
                "extraction_method": EXTRACTOR,
                "notes": None,
            }
        )
    return items


def build_evidence_file() -> dict[str, Any]:
    """The standalone evidence export, including question-scoped sets and the
    searches that returned nothing."""
    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "document_id": DOC_ID,
        "evidence": build_evidence_items(),
        "evidence_sets": [
            {
                "id": "ev:set-costo-neto",
                "question": "¿Cuál será el costo fiscal neto del paquete en 2027?",
                "evidence_ids": ["ev:5", "ev:6", "ev:10", "ev:12", "ev:14"],
                "strength": "medium",
                "independent_source_count": 3,
                "gaps": [
                    "No hay una estimación independiente del costo neto elaborada fuera del ejecutivo.",
                    "Falta el anexo metodológico con la elasticidad de inversión supuesta.",
                ],
                "summary": (
                    "El conjunto establece qué estimó el órgano responsable y que su ejercicio "
                    "excluye la respuesta de inversión. No establece cuál será el costo efectivo: "
                    "ninguna pieza del conjunto observa el resultado, sólo proyecciones."
                ),
                "confidence": conf(
                    0.55,
                    0.7,
                    [
                        (
                            "evidence_agreement",
                            "neutral",
                            "Las piezas no se contradicen; responden preguntas distintas.",
                        ),
                        (
                            "source_independence",
                            "lowers",
                            "Dos de cinco piezas provienen del mismo informe.",
                        ),
                        (
                            "retrieval_completeness",
                            "lowers",
                            "La recuperación en línea está deshabilitada.",
                        ),
                    ],
                    "Ninguna evidencia observa el resultado; todas son proyecciones o declaraciones.",
                ),
            },
            {
                "id": "ev:set-calendario-fondo",
                "question": "¿Comenzarán las transferencias del Fondo territorial durante 2027?",
                "evidence_ids": ["ev:4", "ev:11", "ev:13", "ev:14", "ev:15"],
                "strength": "low",
                "independent_source_count": 4,
                "gaps": [
                    "No hay constancia documental del estado de tramitación del reglamento.",
                    "No hay una serie de rezagos de ejecución con base suficiente.",
                ],
                "summary": (
                    "El conjunto establece que la operación del Fondo depende de un reglamento "
                    "pendiente y que dos actores discrepan sobre el calendario. No permite "
                    "decidir la fecha: el hecho que la decidiría todavía no ocurre."
                ),
                "confidence": conf(
                    0.34,
                    0.62,
                    [
                        (
                            "primary_source_coverage",
                            "raises",
                            "La dependencia normativa está en el texto.",
                        ),
                        (
                            "retrieval_completeness",
                            "lowers",
                            "Falta el registro administrativo del reglamento.",
                        ),
                    ],
                    "El hecho decisivo es futuro; ninguna evidencia actual puede establecerlo.",
                ),
            },
            {
                "id": "ev:set-magnitud-historica",
                "question": "¿Es este el mayor aumento tributario de los últimos treinta años?",
                "evidence_ids": ["ev:1", "ev:7"],
                "strength": "medium",
                "independent_source_count": 2,
                "gaps": [
                    "La serie disponible es sintética; no hay una serie oficial en el conjunto.",
                    "No está fijada la definición de 'aumento tributario' que la comparación usa.",
                ],
                "summary": (
                    "Bajo la definición de la serie disponible, dos aumentos anuales previos "
                    "superan al proyectado. La conclusión cambia si se adopta otra definición, "
                    "y la serie no describe ninguna jurisdicción real."
                ),
                "confidence": conf(
                    0.48,
                    0.66,
                    [
                        (
                            "claim_ambiguity",
                            "lowers",
                            "La comparación depende de la definición elegida.",
                        )
                    ],
                    "La serie es sintética.",
                ),
            },
        ],
        "retrieval_gaps": [
            {
                "question": "¿Qué proporción de las empresas pequeñas conoce la rebaja del impuesto de timbres?",
                "queries_tried": [
                    "encuesta conocimiento rebaja impuesto de timbres pequeñas empresas",
                    "difusión medidas tributarias pymes serie",
                ],
                "expected_source_kind": "statistical_dataset",
                "note": (
                    "No se recuperó ninguna encuesta. Bajo ALEPH_RETRIEVAL_MODE=manual no se "
                    "realizan peticiones de red, de modo que la ausencia refleja la política de "
                    "recuperación y no necesariamente la inexistencia de la fuente."
                ),
            },
            {
                "question": "¿Existe una estimación del costo del paquete elaborada fuera del ejecutivo?",
                "queries_tried": [
                    "estimación independiente costo fiscal paquete estabilización",
                    "contra-informe costeo proyecto 18.216-05",
                ],
                "expected_source_kind": "expert_analysis",
                "note": (
                    "No hay contra-estimación en el conjunto. Es la razón principal por la que "
                    "la diversidad de evidencia está baja."
                ),
            },
            {
                "question": "¿Consta administrativamente el estado de tramitación del reglamento del Fondo?",
                "queries_tried": [
                    "reglamento fondo estabilización territorial estado de tramitación"
                ],
                "expected_source_kind": "legislative_record",
                "note": "No se recuperó registro administrativo alguno; la recuperación está deshabilitada.",
            },
        ],
    }


# --------------------------------------------------------------------------- #
# Impact map — seven fixed axes. NOT party labels, never aggregated.
# --------------------------------------------------------------------------- #

# Every axis's components sum EXACTLY to its score, so opening the number in the
# UI reproduces it. A score whose parts do not add up would be an assertion.
AXIS_ROWS: list[dict[str, Any]] = [
    {
        "key": "households_vs_firms",
        "neg": "hogares",
        "pos": "empresas",
        "components": [
            (
                "Aporte mensual de estabilización a hogares de los cuatro primeros deciles",
                "negative",
                -46,
                [pid(4), "ev:2"],
                "Transferencia directa, sin intermediación.",
            ),
            (
                "Sobretasa transitoria de 2 pp sobre utilidades de empresas grandes",
                "negative",
                -22,
                [pid(1), "ev:1"],
                "La carga recae sobre firmas, lo que desplaza el eje hacia el polo hogares.",
            ),
            (
                "Crédito tributario del 15% a la inversión en activo fijo",
                "positive",
                18,
                [pid(3)],
                "Beneficio dirigido a contribuyentes de primera categoría.",
            ),
            (
                "Rebaja a cero del impuesto de timbres para empresas de hasta 25.000 UF",
                "positive",
                12,
                [pid(2)],
                None,
            ),
        ],
        "refs": [pid(1), pid(2), pid(3), pid(4), "ev:1", "ev:2"],
        "ec": 0.72,
        "mc": 0.68,
        "rationale": (
            "Las dos medidas de mayor magnitud del paquete apuntan en direcciones opuestas: la "
            "transferencia a hogares es la partida de gasto más grande y la sobretasa la única "
            "medida de mayor recaudación. Los beneficios dirigidos a empresas existen pero son "
            "menores en monto. El resultado neto se inclina hacia hogares sin que ello implique "
            "que las empresas resulten perjudicadas en términos absolutos."
        ),
    },
    {
        "key": "redistribution_vs_growth",
        "neg": "redistribución",
        "pos": "crecimiento",
        "components": [
            (
                "Transferencia focalizada en los cuatro primeros deciles",
                "negative",
                -40,
                [pid(4), "ev:2"],
                "Cambia la distribución del ingreso disponible sin alterar incentivos productivos.",
            ),
            (
                "Fondo territorial con fórmula que compensa menores ingresos propios",
                "negative",
                -14,
                [pid(5), "ev:8"],
                "Redistribución entre territorios, no entre personas.",
            ),
            (
                "Crédito a la inversión en activo fijo",
                "positive",
                26,
                [pid(3)],
                "Opera sobre el incentivo a invertir.",
            ),
            (
                "Rebaja del impuesto de timbres sobre operaciones de crédito",
                "positive",
                10,
                [pid(2)],
                "Reduce un costo de transacción del financiamiento.",
            ),
        ],
        "refs": [pid(2), pid(3), pid(4), pid(5), "ev:8"],
        "ec": 0.64,
        "mc": 0.7,
        "rationale": (
            "El paquete contiene mecanismos de ambos tipos. Los de distribución son mayores en "
            "monto; los de incentivo son mayores en horizonte. La cifra resume esa mezcla y no "
            "dice cuál de las dos vías es preferible."
        ),
    },
    {
        "key": "public_vs_private_provision",
        "neg": "provisión pública",
        "pos": "provisión privada",
        "components": [
            (
                "Fondo territorial destinado a inversión ejecutada por municipios",
                "negative",
                -30,
                [pid(5), "ev:3"],
                "Amplía la capacidad de inversión del sector público local.",
            ),
            (
                "Crédito tributario a la inversión privada en activo fijo",
                "positive",
                14,
                [pid(3)],
                None,
            ),
            (
                "Procedimiento abreviado que acelera la ejecución de obras contratadas a privados",
                "positive",
                6,
                [pid(8)],
                "El efecto es indirecto: la obra es pública, la ejecución contratada.",
            ),
            (
                "No se identificaron normas que trasladen funciones de provisión entre sectores",
                "none",
                0,
                [],
                "Componente de peso cero: registrado para mostrar que no hubo hallazgo, no para rellenar.",
            ),
        ],
        "refs": [pid(3), pid(5), pid(8), "ev:3"],
        "ec": 0.55,
        "mc": 0.6,
        "rationale": (
            "Ninguna disposición traslada la titularidad de un servicio de un sector a otro. El "
            "desplazamiento hacia el polo público proviene de un aumento de recursos de "
            "inversión municipal, no de una sustitución de proveedor."
        ),
    },
    {
        "key": "worker_protection_vs_flexibility",
        "neg": "protección laboral",
        "pos": "flexibilidad",
        "components": [
            (
                "Extensión de cinco a ocho giros del fondo solidario de cesantía",
                "negative",
                -28,
                [pid(6)],
                "Amplía la duración de la prestación.",
            ),
            (
                "La extensión excluye a los contratos indefinidos",
                "positive",
                6,
                [pid(6), ppid(10)],
                "Acota el alcance de la protección al segmento con contratos temporales.",
            ),
            (
                "No se identificaron normas sobre jornada, causales de término ni negociación colectiva",
                "none",
                0,
                [],
                "Componente de peso cero: la ausencia de hallazgo se publica en lugar de omitirse.",
            ),
        ],
        "refs": [pid(6), ppid(9), ppid(10)],
        "ec": 0.6,
        "mc": 0.63,
        "rationale": (
            "Una sola disposición toca la materia laboral y lo hace ampliando una prestación "
            "para un subconjunto de contratos. No hay medidas de flexibilización que compensen "
            "ni que refuercen el desplazamiento."
        ),
    },
    {
        "key": "environment_vs_project_acceleration",
        "neg": "salvaguardas ambientales",
        "pos": "aceleración de proyectos",
        "components": [
            (
                "Procedimiento abreviado de 90 días hábiles para infraestructura pública bajo 200.000 UF",
                "positive",
                34,
                [pid(8)],
                "Reduce el plazo total del procedimiento.",
            ),
            (
                "El procedimiento conserva la obligación de recabar informes sectoriales",
                "negative",
                -8,
                [pid(8), ppid(12)],
                "El acortamiento es de plazo, no de contenido.",
            ),
            (
                "No se identificaron normas que refuercen salvaguardas ambientales",
                "none",
                0,
                [],
                "Componente de peso cero: registrado como ausencia de hallazgo.",
            ),
        ],
        "refs": [pid(8), ppid(12)],
        "ec": 0.5,
        "mc": 0.58,
        "rationale": (
            "El desplazamiento proviene de una única disposición procedimental. El texto no "
            "elimina exigencias sustantivas, de modo que el efecto ambiental depende de si el "
            "plazo abreviado permite completar los informes — cuestión que el texto no resuelve "
            "y que ninguna evidencia del conjunto responde."
        ),
    },
    {
        "key": "central_vs_local",
        "neg": "gobierno central",
        "pos": "gobiernos regionales y locales",
        "components": [
            (
                "Fondo territorial: transferencia anual de 0,18% del PIB a municipios",
                "positive",
                42,
                [pid(5), "ev:3"],
                "La principal medida de descentralización del paquete.",
            ),
            (
                "La fórmula de distribución y la elegibilidad las fija un reglamento del nivel central",
                "negative",
                -16,
                [pid(10), "ev:4"],
                "El municipio recibe recursos cuya asignación no controla.",
            ),
            (
                "Obligación de reporte trimestral de ejecución a la autoridad presupuestaria central",
                "negative",
                -8,
                [pid(9)],
                "Aumenta la supervisión central sobre el gasto local.",
            ),
        ],
        "refs": [pid(5), pid(9), pid(10), "ev:3", "ev:4"],
        "ec": 0.68,
        "mc": 0.66,
        "rationale": (
            "El paquete entrega recursos al nivel local y retiene en el nivel central la "
            "decisión sobre cómo se reparten y la fiscalización de su uso. La cifra neta es "
            "positiva porque el monto pesa más que los contrapesos institucionales, pero los "
            "contrapesos son reales y aparecen como componentes negativos."
        ),
    },
    {
        "key": "current_relief_vs_long_term_investment",
        "neg": "alivio inmediato",
        "pos": "inversión de largo plazo",
        "components": [
            (
                "Aporte mensual a hogares durante 24 meses",
                "negative",
                -44,
                [pid(4), "ev:2"],
                "Alivio inmediato, con sunset explícito.",
            ),
            (
                "Extensión transitoria de la cobertura del seguro de cesantía",
                "negative",
                -10,
                [pid(6)],
                None,
            ),
            (
                "Crédito a la inversión en activo fijo hasta 2030",
                "positive",
                20,
                [pid(3)],
                "Efecto sobre capacidad productiva a horizonte medio.",
            ),
            (
                "Fondo territorial destinado exclusivamente a proyectos de inversión",
                "positive",
                18,
                [pid(5), "ev:3"],
                "La dotación no puede usarse en gasto corriente municipal.",
            ),
        ],
        "refs": [pid(3), pid(4), pid(5), pid(6), "ev:2", "ev:3"],
        "ec": 0.62,
        "mc": 0.64,
        "rationale": (
            "Las partidas de alivio son mayores y expiran; las de inversión son menores y "
            "duran más. Una cifra cercana a cero aquí significaría equilibrio, no ausencia de "
            "medidas: por eso los componentes son el hallazgo y el número sólo su resumen."
        ),
    },
]

GROUP_ROWS: list[dict[str, Any]] = [
    {
        "side": "beneficiaries",
        "group": "low_income_households",
        "detail": "hogares de los cuatro primeros deciles",
        "direction": "positive",
        "magnitude": "large",
        "quality": "high",
        "horizon": "immediate",
        "causality": "direct",
        "evidence": [pid(4), "ev:2", "ev:5"],
        "rationale": "El artículo 6° transfiere $42.000 mensuales por hogar durante 24 meses, sin contraprestación ni trámite adicional al de la focalización existente.",
        "uncertainties": [
            (
                "La cobertura efectiva depende del instrumento de caracterización socioeconómica, cuya tasa de error el documento no evalúa.",
                "missing_evidence",
                "Una evaluación de cobertura del instrumento de focalización.",
            ),
            (
                "El informe supone una tasa de toma de 92%; una toma menor reduce el alcance sin cambiar el diseño.",
                "model_dependency",
                "Datos de ejecución del primer trimestre de pago.",
            ),
        ],
        "money": [money(42000.0, "unit", 2026, "monthly")],
        "ec": 0.82,
        "mc": 0.78,
    },
    {
        "side": "beneficiaries",
        "group": "municipalities",
        "detail": None,
        "direction": "positive",
        "magnitude": "medium",
        "quality": "medium",
        "horizon": "medium_term",
        "causality": "indirect",
        "evidence": [pid(5), "ev:3", "ev:8", "ev:11"],
        "rationale": "El Fondo aporta 0,18% del PIB anual para inversión municipal, pero el efecto llega sólo cuando el reglamento fija la fórmula y comienza la ejecución.",
        "uncertainties": [
            (
                "El reparto entre municipios no está determinado: la fórmula la fija un reglamento aún no dictado.",
                "missing_evidence",
                "La publicación del reglamento.",
            ),
            (
                "La nota de rezago de ejecución se basa en cinco casos, base insuficiente para una expectativa general.",
                "measurement",
                "Una serie de rezagos con más casos.",
            ),
        ],
        "money": [money(0.18, "percent_of_gdp", 2027, "annual")],
        "ec": 0.58,
        "mc": 0.66,
    },
    {
        "side": "beneficiaries",
        "group": "workers",
        "detail": "trabajadores con contrato a plazo fijo o por obra o faena",
        "direction": "positive",
        "magnitude": "medium",
        "quality": "medium",
        "horizon": "short_term",
        "causality": "direct",
        "evidence": [pid(6), ppid(9), ppid(10)],
        "rationale": "El artículo 8° eleva de cinco a ocho el número máximo de giros del fondo solidario para quienes cumplan el requisito de cotizaciones.",
        "uncertainties": [
            (
                "Los trabajadores con contrato indefinido quedan expresamente fuera, de modo que el efecto no alcanza al grueso de los asalariados.",
                "definitional_ambiguity",
                None,
            ),
        ],
        "money": [],
        "ec": 0.7,
        "mc": 0.7,
    },
    {
        "side": "beneficiaries",
        "group": "smes",
        "detail": "empresas con ingresos anuales de hasta 25.000 UF",
        "direction": "positive",
        "magnitude": "small",
        "quality": "low",
        "horizon": "short_term",
        "causality": "indirect",
        "evidence": [pid(2)],
        "rationale": "La rebaja a cero del impuesto de timbres reduce el costo de contratar crédito, pero el beneficio llega al deudor sólo si la rebaja se traspasa a la tasa ofrecida.",
        "uncertainties": [
            (
                "No hay evidencia en el conjunto sobre el traspaso de la rebaja a las condiciones de crédito.",
                "missing_evidence",
                "Un estudio de traspaso de impuestos de transacción a tasas.",
            ),
            (
                "No se recuperó ninguna medición de conocimiento de la medida entre las empresas destinatarias.",
                "missing_evidence",
                "Una encuesta a empresas pequeñas.",
            ),
        ],
        "money": [],
        "ec": 0.3,
        "mc": 0.55,
    },
    {
        "side": "beneficiaries",
        "group": "domestic_investors",
        "detail": "contribuyentes que invierten en activo fijo productivo",
        "direction": "positive",
        "magnitude": "small",
        "quality": "low",
        "horizon": "medium_term",
        "causality": "indirect",
        "evidence": [pid(3), "ev:10"],
        "rationale": "El crédito del 15% reduce el costo después de impuestos de la inversión; el tope de 8.000 UF anuales acota el beneficio para los contribuyentes de mayor tamaño.",
        "uncertainties": [
            (
                "La respuesta de la inversión a incentivos tributarios tiene un rango amplio en la literatura disponible y varias especificaciones no la distinguen de cero.",
                "conflicting_evidence",
                "Estimaciones específicas para esta jurisdicción y este diseño.",
            ),
        ],
        "money": [],
        "ec": 0.34,
        "mc": 0.58,
    },
    {
        "side": "cost_bearers",
        "group": "large_companies",
        "detail": "empresas con ingresos brutos anuales sobre 100.000 UF",
        "direction": "negative",
        "magnitude": "medium",
        "quality": "medium",
        "horizon": "short_term",
        "causality": "direct",
        "evidence": [pid(1), "ev:1", "ev:5"],
        "rationale": "La sobretasa de 2 pp se aplica directamente sobre la base imponible declarada del tramo definido por el artículo 3°.",
        "uncertainties": [
            (
                "La incidencia final depende de si el costo se traslada a precios, salarios o accionistas; el documento no lo modela.",
                "model_dependency",
                "Un estudio de incidencia del impuesto corporativo.",
            ),
            (
                "El crédito a la inversión compensa parcialmente la carga, en una magnitud que depende del perfil de inversión de cada contribuyente.",
                "measurement",
                None,
            ),
        ],
        "money": [money(620000.0, "million", 2026, "annual")],
        "ec": 0.66,
        "mc": 0.72,
    },
    {
        "side": "cost_bearers",
        "group": "central_government",
        "detail": None,
        "direction": "negative",
        "magnitude": "large",
        "quality": "medium",
        "horizon": "medium_term",
        "causality": "direct",
        "evidence": ["ev:5", "ev:6", pid(4), pid(5)],
        "rationale": "El gasto del aporte y del Fondo, más el costo del crédito y de la rebaja de timbres, exceden la recaudación proyectada de la sobretasa: el informe estima un costo neto de 0,4% del PIB en 2027.",
        "uncertainties": [
            (
                "La estimación excluye la respuesta de inversión, que el propio informe declara no modelar.",
                "model_dependency",
                "El anexo metodológico con la elasticidad supuesta.",
            ),
            (
                "La regla de gasto del artículo 9° restringe la prórroga del aporte, pero no tiene consecuencia asociada al incumplimiento.",
                "definitional_ambiguity",
                None,
            ),
        ],
        "money": [money(0.4, "percent_of_gdp", 2027, "annual")],
        "ec": 0.6,
        "mc": 0.7,
    },
    {
        "side": "cost_bearers",
        "group": "future_taxpayers",
        "detail": None,
        "direction": "uncertain",
        "magnitude": "unknown",
        "quality": "insufficient",
        "horizon": "long_term",
        "causality": "indirect",
        "evidence": [],
        "rationale": "Un costo neto sostenido debe financiarse con deuda, mayor recaudación futura o menor gasto futuro. El documento no señala cuál de las tres vías, y el conjunto no contiene evidencia que lo determine.",
        "uncertainties": [
            (
                "No hay en el conjunto ninguna proyección de deuda ni trayectoria fiscal de mediano plazo.",
                "missing_evidence",
                "Una proyección fiscal plurianual.",
            ),
        ],
        "money": None,
        "ec": 0.12,
        "mc": 0.4,
    },
    {
        "side": "cost_bearers",
        "group": "environment",
        "detail": "componentes ambientales sujetos a evaluación en proyectos bajo el umbral",
        "direction": "uncertain",
        "magnitude": "unknown",
        "quality": "insufficient",
        "horizon": "long_term",
        "causality": "indirect",
        "evidence": [pid(8), ppid(12)],
        "rationale": "El procedimiento abreviado acorta el plazo sin eliminar la consulta sectorial. Si 90 días hábiles bastan para emitir los informes, el efecto ambiental es nulo; si no bastan, la evaluación se degrada. El texto no permite decidir cuál de las dos cosas ocurre.",
        "uncertainties": [
            (
                "No hay evidencia sobre la duración habitual de los informes sectoriales en proyectos de este tamaño.",
                "missing_evidence",
                "Una serie de tiempos de tramitación de informes sectoriales.",
            ),
        ],
        "money": None,
        "ec": 0.15,
        "mc": 0.45,
    },
    {
        "side": "cost_bearers",
        "group": "middle_income_households",
        "detail": "hogares de los deciles 5 a 8",
        "direction": "mixed",
        "magnitude": "small",
        "quality": "low",
        "horizon": "medium_term",
        "causality": "indirect",
        "evidence": [pid(1), pid(4), "ev:5"],
        "rationale": "Quedan fuera del aporte y pueden absorber parte de la sobretasa a través de precios o salarios, en una magnitud que el documento no modela. No hay disposición que los alcance directamente.",
        "uncertainties": [
            (
                "El reparto de la incidencia del impuesto corporativo entre precios, salarios y utilidades no está establecido por ninguna evidencia del conjunto.",
                "model_dependency",
                "Un estudio de incidencia con datos de esta jurisdicción.",
            ),
        ],
        "money": None,
        "ec": 0.25,
        "mc": 0.5,
    },
]


def _group_impact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "group": row["group"],
        "group_detail": row["detail"],
        "estimated_direction": row["direction"],
        "magnitude": row["magnitude"],
        "evidence_quality": row["quality"],
        "time_horizon": row["horizon"],
        "direct_or_indirect": row["causality"],
        "supporting_evidence": row["evidence"],
        "rationale": row["rationale"],
        "uncertainties": [unc(s, k, r) for s, k, r in row["uncertainties"]],
        "money": row["money"],
        "confidence": conf(
            row["ec"],
            row["mc"],
            [
                (
                    "primary_source_coverage",
                    "raises" if row["evidence"] else "lowers",
                    "El mecanismo está en el articulado."
                    if row["evidence"]
                    else "Sin evidencia asociada: la calidad se declara insuficiente.",
                ),
                (
                    "retrieval_completeness",
                    "lowers",
                    "La recuperación en línea está deshabilitada.",
                ),
            ],
            "El conjunto de evidencia es sintético y no incluye contra-estimaciones independientes.",
        ),
    }


def build_impact_map() -> dict[str, Any]:
    """Seven fixed axes plus who gains and who pays. Never a single political score."""
    axes = {}
    for row in AXIS_ROWS:
        components = [comp(lbl, d, w, refs, note) for lbl, d, w, refs, note in row["components"]]
        score = sum(int(c["weight"]) for c in components)
        axes[row["key"]] = {
            "score": score,
            "negative_label": row["neg"],
            "positive_label": row["pos"],
            "components": components,
            "evidence_refs": row["refs"],
            "confidence": conf(
                row["ec"],
                row["mc"],
                [
                    (
                        "primary_source_coverage",
                        "raises",
                        "Cada componente cita una disposición del articulado.",
                    ),
                    (
                        "evidence_agreement",
                        "neutral",
                        "Los componentes apuntan en direcciones opuestas por diseño, no por conflicto de fuentes.",
                    ),
                    (
                        "retrieval_completeness",
                        "lowers",
                        "No hay estimaciones externas que contrasten la ponderación.",
                    ),
                ],
                "Las ponderaciones son juicios del analizador de impacto, no mediciones.",
            ),
            "rationale": row["rationale"],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "document_id": DOC_ID,
        "map_version": "aleph-impact/0.1.0",
        "axes": axes,
        "beneficiaries": [_group_impact(r) for r in GROUP_ROWS if r["side"] == "beneficiaries"],
        "cost_bearers": [_group_impact(r) for r in GROUP_ROWS if r["side"] == "cost_bearers"],
        "method_note": (
            "Convención: el signo del peso indica hacia qué polo empuja el componente "
            "(negativo = primer polo del eje) y 'direction' repite ese sentido; los componentes "
            "de peso cero registran ausencias de hallazgo y se publican en lugar de omitirse. "
            "En los siete ejes la suma de los pesos es exactamente el score, de modo que abrir "
            "la cifra en la interfaz la reproduce. Sólo se consideraron las diez disposiciones "
            "operativas extraídas; el preámbulo y las definiciones no ponderan. Estas cifras "
            "describen dónde caen los efectos identificados en el texto y NO son etiquetas "
            "políticas: no deben sumarse, promediarse ni proyectarse sobre un eje izquierda-derecha."
        ),
        "uncertainties": [
            unc(
                "Ninguna respuesta conductual está modelada: el informe financiero declara excluirla y el conjunto no contiene una estimación alternativa.",
                "model_dependency",
                "El anexo metodológico del informe financiero o una estimación externa de elasticidad.",
            ),
            unc(
                "Los efectos del Fondo territorial dependen de un reglamento que aún no existe, de modo que su incidencia por municipio es indeterminada.",
                "missing_evidence",
                "La publicación del reglamento con la fórmula de distribución.",
            ),
            unc(
                "Las ponderaciones de los componentes son juicios del analizador, no mediciones; dos analistas razonables podrían asignar pesos distintos sobre los mismos hechos.",
                "measurement",
                "Una calibración de pesos contra resultados observados en documentos comparables.",
            ),
        ],
    }


# --------------------------------------------------------------------------- #
# Claims — stage one blind, stage two attributed and unable to touch the verdict
# --------------------------------------------------------------------------- #

CHECK_ORDER = [
    "direct_textual_evidence",
    "data_consistency",
    "quantitative_correctness",
    "logical_validity",
    "causal_support",
    "uncertainty_handling",
    "context_completeness",
    "temporal_correctness",
    "independent_corroboration",
    "contradiction_with_stronger_evidence",
]

# Short keys used in the compact rows below.
CHECK_KEYS = ["txt", "data", "quant", "logic", "causal", "unc", "ctx", "time", "corrob", "contra"]

WITHHELD_ALL = [
    "speaker_name",
    "speaker_role",
    "party",
    "coalition",
    "government_or_opposition_status",
    "outlet",
    "outlet_prestige",
    "author",
    "publication_venue",
    "institutional_affiliation",
]

CLAIM_ROWS: list[dict[str, Any]] = [
    {
        "n": 1,
        "text": "El costo neto es de cuatro décimas del producto y ningún hogar de los primeros cuatro deciles pagará más impuestos.",
        "normalised": "El informe financiero adjunto estima el costo fiscal neto del paquete en 0,4% del PIB para el ejercicio 2027.",
        "type": "fact",
        "verdict": "supported",
        "made_at": "2026-08-04T13:00:00Z",
        "article": "art:meridiano:1",
        "role": ROLE_TREASURY,
        "actor": "actor:vocaria-hacienda",
        "outlet": "src:demo-diario-meridiano",
        "topics": ["node:costo-fiscal-neto", "node:paquete-fiscal"],
        "props": [pid(1), pid(4), pid(5)],
        "evidence_shown": ["ev:5", "ev:6", "ev:14", "ev:7"],
        "evidence_used": ["ev:5", "ev:14"],
        "redacted": "Quien habla sostiene que el costo neto del paquete es de 0,4% del producto interno bruto.",
        "reasoning": (
            "El informe financiero adjunto contiene esa cifra para el ejercicio 2027 (ev:5), y "
            "la afirmación se limita a lo que el informe estima. La verificación se detiene ahí: "
            "que el informe estime 0,4% no establece que el costo efectivo sea 0,4%, y la propia "
            "sección de limitaciones declara excluir la respuesta de inversión (ev:6). El "
            "veredicto sostiene la afirmación tal como está formulada, no la proyección subyacente."
        ),
        "assumptions": [],
        "cluster": "cluster:1",
        "quantities": [quantity(0.4, "percentage", "cuatro décimas del producto", "% del PIB")],
        "money": [money(0.4, "percent_of_gdp", 2027, "annual")],
        "ec": 0.78,
        "mc": 0.8,
        "limiting": "Ninguna estimación independiente contrasta la cifra oficial.",
        "checks": {
            "txt": ("pass", "El informe financiero contiene la cifra citada para 2027.", ["ev:5"]),
            "data": (
                "pass",
                "La cifra es consistente con las partidas de gasto e ingreso del articulado.",
                ["ev:1", "ev:2", "ev:3"],
            ),
            "quant": (
                "pass",
                "0,4% del PIB coincide con el saldo de las partidas proyectadas en el informe.",
                ["ev:5"],
            ),
            "logic": (
                "pass",
                "La afirmación no infiere nada más allá de lo que el informe declara.",
                [],
            ),
            "causal": ("na", "La afirmación no asserta una relación causal.", []),
            "unc": (
                "fail",
                "Se enuncia como cifra cerrada, sin mencionar el supuesto de crecimiento de 2,3% ni el rango implícito.",
                ["ev:5", "ev:6"],
            ),
            "ctx": (
                "fail",
                "Omite que el informe excluye explícitamente la respuesta de inversión.",
                ["ev:6"],
            ),
            "time": (
                "pass",
                "La cifra corresponde al ejercicio 2027 y la afirmación se hizo en 2026.",
                ["ev:5"],
            ),
            "corrob": (
                "fail",
                "No hay una segunda estimación independiente del costo neto en el conjunto.",
                [],
            ),
            "contra": (
                "pass",
                "Ninguna evidencia más sólida contradice que el informe contenga esa cifra.",
                ["ev:5"],
            ),
        },
        "framing_notes": [
            "Presenta una proyección con la gramática de un dato observado.",
            "Une en una sola frase una cifra verificable y una afirmación distributiva que exige otra verificación.",
        ],
        "history": (
            "consistent",
            ["clm:13"],
            "Coherente con declaraciones previas del mismo rol sobre el calendario del paquete.",
        ),
        "rhetoric": [
            (
                "urgency_framing",
                "El costo neto es de cuatro décimas",
                "La cifra se entrega sin rango ni supuesto, lo que transmite más certeza que la fuente.",
            )
        ],
        "omitted": [
            (
                "El informe financiero declara no modelar la respuesta de la inversión privada a la sobretasa.",
                "Si esa respuesta es relevante, la recaudación neta sería menor y el costo neto mayor que el estimado.",
                ["ev:6"],
                "medium",
            ),
        ],
    },
    {
        "n": 2,
        "text": "El fondo transfiere a los municipios 0,18% del producto cada año, sin excepciones.",
        "normalised": "El artículo 7° dota anualmente al Fondo de Estabilización Territorial con recursos equivalentes al 0,18% del producto interno bruto.",
        "type": "fact",
        "verdict": "supported",
        "made_at": "2026-08-05T17:40:00Z",
        "article": "art:contrapunto:2",
        "role": ROLE_MUNICIPAL,
        "actor": "actor:asociacion-municipios",
        "outlet": "src:demo-el-contrapunto",
        "topics": ["node:fondo-territorial", "node:municipios"],
        "props": [pid(5), ppid(7)],
        "evidence_shown": ["ev:3", "ev:4", "ev:8"],
        "evidence_used": ["ev:3"],
        "redacted": "Quien habla sostiene que el fondo transfiere anualmente a los municipios el 0,18% del producto interno bruto.",
        "reasoning": (
            "El artículo 7° fija esa dotación en esos términos (ev:3). La afirmación describe el "
            "contenido del texto y es exacta en ese plano. La coletilla 'sin excepciones' se "
            "verifica por separado: el articulado no establece excepciones a la dotación, aunque "
            "sí condiciona la transferencia a un reglamento pendiente (ev:4), lo que afecta al "
            "calendario y no al monto."
        ),
        "assumptions": [],
        "cluster": "cluster:2",
        "quantities": [quantity(0.18, "percentage", "0,18% del producto", "% del PIB")],
        "money": [money(0.18, "percent_of_gdp", 2027, "annual")],
        "ec": 0.86,
        "mc": 0.82,
        "limiting": "El texto fija el monto; la transferencia efectiva depende de un reglamento pendiente.",
        "checks": {
            "txt": ("pass", "El artículo 7° contiene la dotación en esos términos.", ["ev:3"]),
            "data": ("pass", "No hay otra cifra de dotación en el documento.", ["ev:3"]),
            "quant": (
                "pass",
                "0,18% es la cifra impresa; no hay conversión de unidades involucrada.",
                ["ev:3"],
            ),
            "logic": ("pass", "La afirmación no excede lo que el texto dice.", []),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": (
                "pass",
                "No hay proyección involucrada: es una cifra normativa, no estimada.",
                [],
            ),
            "ctx": (
                "fail",
                "Omite que la transferencia no puede efectuarse antes del reglamento.",
                ["ev:4"],
            ),
            "time": (
                "pass",
                "La afirmación describe una norma vigente en su formulación actual.",
                [],
            ),
            "corrob": (
                "pass",
                "El texto primario es corroboración suficiente para el contenido de una norma.",
                ["ev:3"],
            ),
            "contra": ("pass", "Ninguna evidencia más sólida ofrece otra cifra.", []),
        },
        "framing_notes": [
            "'Sin excepciones' introduce un énfasis que el texto no necesita: la norma no contempla excepciones al monto, pero sí una condición de entrada en vigor."
        ],
        "history": (
            "consistent",
            [],
            "El mismo rol ha sostenido la cifra desde el ingreso del proyecto.",
        ),
        "rhetoric": [("none_detected", None, None)],
        "omitted": [
            (
                "El artículo 7° no puede transferir recursos mientras no se dicte el reglamento que fija la fórmula de distribución.",
                "Un lector podría entender que las transferencias ya están operando, cuando la norma aún no tiene fórmula aplicable.",
                ["ev:4"],
                "large",
            ),
        ],
    },
    {
        "n": 3,
        "text": "Este es el mayor aumento de impuestos de los últimos treinta años.",
        "normalised": "El aumento de la carga tributaria que produce este paquete es el mayor registrado en los últimos treinta años.",
        "type": "fact",
        "verdict": "contradicted",
        "made_at": "2026-08-06T18:30:00Z",
        "article": "art:boletin:2",
        "role": ROLE_OPPOSITION,
        "actor": "actor:oposicion-finanzas",
        "outlet": "src:demo-boletin-economico",
        "topics": ["node:sobretasa-utilidades", "node:paquete-fiscal"],
        "props": [pid(1)],
        "evidence_shown": ["ev:7", "ev:1", "ev:5"],
        "evidence_used": ["ev:7", "ev:1"],
        "redacted": "Quien habla sostiene que este es el mayor aumento de impuestos de los últimos treinta años.",
        "reasoning": (
            "La única medida de mayor recaudación del paquete es la sobretasa de 2 pp (ev:1), "
            "cuyo efecto proyectado equivale a +0,6 pp del PIB. La serie disponible registra al "
            "menos dos aumentos anuales mayores dentro de la ventana de treinta años que la "
            "afirmación invoca (ev:7). Bajo la definición de esa serie, la afirmación es falsa. "
            "Se registra que la serie es sintética y que otra definición de 'aumento de "
            "impuestos' podría ordenar los casos de otro modo; eso no rescata la afirmación tal "
            "como fue enunciada, porque quien la hace no propone una definición alternativa."
        ),
        "assumptions": [],
        "cluster": "cluster:4",
        "quantities": [quantity(30.0, "duration", "los últimos treinta años", "años")],
        "money": [],
        "ec": 0.62,
        "mc": 0.74,
        "limiting": "La serie de comparación es sintética y su definición de carga tributaria es la única disponible.",
        "checks": {
            "txt": (
                "fail",
                "Ninguna pieza del conjunto afirma la comparación histórica que se enuncia.",
                [],
            ),
            "data": (
                "fail",
                "La serie disponible registra dos aumentos anuales mayores en la ventana invocada.",
                ["ev:7"],
            ),
            "quant": (
                "fail",
                "El aumento proyectado (+0,6 pp del PIB) es menor que +1,4 y +1,1 pp registrados en la serie.",
                ["ev:7"],
            ),
            "logic": (
                "pass",
                "La afirmación es una comparación bien formada; su problema es empírico, no lógico.",
                [],
            ),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": (
                "fail",
                "Se enuncia como hecho cerrado una comparación que depende por completo de la definición de carga tributaria usada.",
                ["ev:7"],
            ),
            "ctx": (
                "fail",
                "Omite que el paquete contiene además rebajas tributarias que reducen la carga neta.",
                ["ev:1"],
            ),
            "time": (
                "pass",
                "La ventana de treinta años es coherente con la fecha de la afirmación.",
                [],
            ),
            "corrob": (
                "fail",
                "No hay una segunda serie independiente que permita contrastar el orden de magnitudes.",
                [],
            ),
            "contra": (
                "fail",
                "La serie disponible es evidencia más sólida que la afirmación y apunta en sentido contrario.",
                ["ev:7"],
            ),
        },
        "framing_notes": [
            "Elige como clase de comparación 'aumento de impuestos' y no 'efecto neto en la carga', lo que excluye del cálculo las rebajas del mismo paquete.",
        ],
        "history": (
            "insufficient_history",
            [],
            "No hay declaraciones previas de este rol en el conjunto.",
        ),
        "rhetoric": [
            (
                "loaded_comparison",
                "el mayor aumento de impuestos de los últimos treinta años",
                "La comparación superlativa fija el marco antes de que la magnitud sea discutida.",
            )
        ],
        "omitted": [
            (
                "El mismo paquete reduce a cero el impuesto de timbres para empresas pequeñas y crea un crédito del 15% a la inversión.",
                "La carga tributaria neta del paquete es menor que la de su única medida de alza considerada aisladamente.",
                ["ev:1"],
                "large",
            ),
        ],
    },
    {
        "n": 4,
        "text": "Ningún hogar de los primeros cuatro deciles pagará más impuestos por este paquete.",
        "normalised": "Ningún hogar perteneciente a los cuatro primeros deciles de ingreso soportará una carga tributaria mayor como consecuencia de este paquete.",
        "type": "fact",
        "verdict": "partially_supported",
        "made_at": "2026-08-04T13:00:00Z",
        "article": "art:meridiano:1",
        "role": ROLE_TREASURY,
        "actor": "actor:vocaria-hacienda",
        "outlet": "src:demo-diario-meridiano",
        "topics": ["node:hogares-deciles-1-4", "node:sobretasa-utilidades"],
        "props": [pid(1), pid(4)],
        "evidence_shown": ["ev:2", "ev:1", "ev:6", "ev:14"],
        "evidence_used": ["ev:1", "ev:2", "ev:6"],
        "redacted": "Quien habla sostiene que ningún hogar de los cuatro primeros deciles pagará más impuestos por este paquete.",
        "reasoning": (
            "Ninguna disposición del articulado impone un tributo a las personas naturales: la "
            "única medida de alza recae sobre contribuyentes de primera categoría con ingresos "
            "brutos sobre 100.000 UF (ev:1), y los hogares del tramo reciben una transferencia "
            "(ev:2). En el plano de la carga legal directa la afirmación se sostiene. No se "
            "sostiene en el plano de la incidencia: el informe financiero declara no modelar el "
            "traslado del impuesto corporativo a precios o salarios (ev:6), de modo que la parte "
            "de la afirmación que exige ausencia de efecto no está establecida por ninguna "
            "evidencia disponible."
        ),
        "assumptions": [],
        "cluster": "cluster:1",
        "quantities": [],
        "money": [],
        "ec": 0.64,
        "mc": 0.72,
        "limiting": "No hay estudio de incidencia del impuesto corporativo en el conjunto.",
        "checks": {
            "txt": (
                "pass",
                "El articulado no contiene ningún tributo sobre personas naturales.",
                ["ev:1", "ev:2"],
            ),
            "data": (
                "pass",
                "Las partidas del informe son consistentes con esa lectura.",
                ["ev:5"],
            ),
            "quant": ("na", "La afirmación no contiene una cifra que verificar.", []),
            "logic": (
                "fail",
                "De 'no hay tributo legal sobre el grupo' no se sigue 'el grupo no paga más', que es lo afirmado.",
                [],
            ),
            "causal": (
                "fail",
                "La ausencia de efecto indirecto se asevera sin evidencia de incidencia.",
                ["ev:6"],
            ),
            "unc": (
                "fail",
                "Se enuncia como certeza una proposición que el propio informe declara no haber modelado.",
                ["ev:6"],
            ),
            "ctx": (
                "fail",
                "Omite el canal de traslado del impuesto corporativo a precios o salarios.",
                ["ev:6"],
            ),
            "time": ("pass", "La afirmación se refiere al régimen que entra en vigor en 2027.", []),
            "corrob": (
                "fail",
                "Ninguna fuente independiente evalúa la incidencia sobre hogares.",
                [],
            ),
            "contra": (
                "pass",
                "Ninguna evidencia más sólida establece lo contrario; el punto es que nada lo establece en ningún sentido.",
                [],
            ),
        },
        "framing_notes": [
            "Sustituye 'no hay un impuesto dirigido a este grupo' por 'este grupo no pagará más', que es una afirmación más fuerte."
        ],
        "history": ("consistent", ["clm:1"], None),
        "rhetoric": [
            (
                "technical_obfuscation",
                "no pagará más impuestos",
                "La expresión desliza el plano legal al plano económico sin señalarlo.",
            )
        ],
        "omitted": [
            (
                "El informe financiero declara no modelar el traslado de la sobretasa a precios o salarios.",
                "Sin esa modelación, la afirmación sobre incidencia no está respaldada ni refutada por la evidencia disponible.",
                ["ev:6"],
                "medium",
            ),
        ],
    },
    {
        "n": 5,
        "text": "El costo neto será a lo menos el doble del informado una vez que se incorpore la caída de recaudación por menor inversión.",
        "normalised": "El costo fiscal neto efectivo del paquete en 2027 será igual o superior a 0,8% del PIB, una vez incorporada la menor recaudación derivada de una caída de la inversión.",
        "type": "forecast",
        "verdict": "forecast_conditional",
        "made_at": "2026-08-06T12:00:00Z",
        "article": "art:canalsur:2",
        "role": ROLE_BUSINESS,
        "actor": "actor:federacion-empresarial",
        "outlet": "src:demo-canal-sur-noticias",
        "topics": ["node:costo-fiscal-neto", "node:sobretasa-utilidades"],
        "props": [pid(1)],
        "evidence_shown": ["ev:5", "ev:6", "ev:10"],
        "evidence_used": ["ev:6", "ev:10"],
        "redacted": "Quien habla sostiene que el costo fiscal neto será al menos el doble de la cifra oficial una vez incorporada la caída de recaudación por menor inversión.",
        "reasoning": (
            "La afirmación es una proyección sobre un ejercicio futuro y no puede ser verdadera "
            "ni falsa hoy. Su premisa —que la estimación oficial excluye la respuesta de "
            "inversión— es correcta y está declarada en la propia fuente (ev:6). Su conclusión "
            "cuantitativa no lo está: el rango de elasticidad disponible va de -0,2 a -1,8 "
            "puntos y en cuatro de siete especificaciones no se distingue de cero (ev:10), de "
            "modo que 'al menos el doble' se sitúa en el extremo del rango sin justificar por "
            "qué. Se evalúa como condicional y se listan los supuestos que debería cumplir."
        ),
        "assumptions": [
            "Que la elasticidad de la inversión se sitúe en el extremo alto del rango disponible (-1,8 puntos o más).",
            "Que la caída de inversión se traduzca íntegramente en menor recaudación dentro del mismo ejercicio.",
            "Que no operen los efectos compensatorios del crédito a la inversión del artículo 5°.",
        ],
        "cluster": "cluster:1",
        "quantities": [],
        "money": [money(0.8, "percent_of_gdp", 2027, "annual")],
        "ec": 0.36,
        "mc": 0.6,
        "limiting": "Ninguna evidencia observa el resultado; la afirmación versa sobre un ejercicio futuro.",
        "checks": {
            "txt": ("fail", "Ningún texto disponible afirma la magnitud proyectada.", []),
            "data": (
                "fail",
                "El rango de la literatura no sostiene el extremo elegido.",
                ["ev:10"],
            ),
            "quant": (
                "fail",
                "'Al menos el doble' requiere una elasticidad en el extremo del rango, sin justificación.",
                ["ev:10"],
            ),
            "logic": (
                "pass",
                "La inferencia es válida si se conceden sus premisas; el problema está en las premisas.",
                [],
            ),
            "causal": (
                "fail",
                "La cadena sobretasa → menor inversión → menor recaudación se asevera sin cuantificar ningún eslabón.",
                ["ev:10"],
            ),
            "unc": (
                "fail",
                "No se enuncia rango ni condiciones, pese a que la evidencia subyacente es un intervalo amplio.",
                ["ev:10"],
            ),
            "ctx": (
                "pass",
                "Sí menciona que la cifra oficial excluye la respuesta de inversión, que es el punto material.",
                ["ev:6"],
            ),
            "time": ("na", "La afirmación se refiere a un ejercicio que aún no ocurre.", []),
            "corrob": ("fail", "No hay una segunda estimación independiente del efecto.", []),
            "contra": (
                "fail",
                "El rango disponible, que es evidencia más sólida que la afirmación, no sostiene el extremo invocado.",
                ["ev:10"],
            ),
        },
        "framing_notes": ["Elige el extremo del rango disponible y lo presenta como el caso base."],
        "history": ("shifted", [], "El mismo rol había descrito antes el efecto como 'incierto'."),
        "rhetoric": [
            (
                "unfalsifiable_prediction",
                "a lo menos el doble",
                "El 'a lo menos' impide que la predicción sea refutada por cualquier resultado alto.",
            )
        ],
        "omitted": [
            (
                "El crédito tributario del 15% a la inversión en activo fijo opera en sentido contrario a la sobretasa.",
                "El efecto neto sobre la inversión depende del saldo de ambas medidas, no sólo de la sobretasa.",
                [pid(3)],
                "medium",
            ),
        ],
    },
    {
        "n": 6,
        "text": "La sobretasa reducirá la inversión privada en 1,2 puntos en dos años.",
        "normalised": "La sobretasa del artículo 3° reducirá la inversión privada en 1,2 puntos porcentuales dentro de los dos años siguientes a su entrada en vigor.",
        "type": "forecast",
        "verdict": "forecast_conditional",
        "made_at": "2026-08-06T12:00:00Z",
        "article": "art:canalsur:2",
        "role": ROLE_BUSINESS,
        "actor": "actor:federacion-empresarial",
        "outlet": "src:demo-canal-sur-noticias",
        "topics": ["node:sobretasa-utilidades", "node:sector-construccion"],
        "props": [pid(1)],
        "evidence_shown": ["ev:10", "ev:1", "ev:6"],
        "evidence_used": ["ev:10"],
        "redacted": "Quien habla sostiene que la sobretasa reducirá la inversión privada en 1,2 puntos en dos años.",
        "reasoning": (
            "La cifra cae dentro del rango disponible (-0,2 a -1,8 puntos) pero la evidencia no "
            "singulariza un valor: cuatro de siete especificaciones incluyen el cero (ev:10). "
            "Una predicción puntual extraída de un intervalo amplio no es falsa, es condicional: "
            "depende del supuesto de elasticidad, del horizonte y de que el diseño estudiado sea "
            "comparable. Se registra como tal y se listan esos supuestos."
        ),
        "assumptions": [
            "Que la elasticidad aplicable sea la del punto medio del rango publicado y no un valor cercano a cero.",
            "Que los resultados del estudio disponible sean trasladables a esta jurisdicción y a este diseño.",
            "Que el horizonte de dos años baste para que el efecto se materialice.",
        ],
        "cluster": "cluster:1",
        "quantities": [quantity(-1.2, "percentage_point", "1,2 puntos", "pp")],
        "money": [],
        "ec": 0.4,
        "mc": 0.62,
        "limiting": "El intervalo de la evidencia incluye el cero en la mayoría de las especificaciones.",
        "checks": {
            "txt": ("na", "No es una afirmación sobre el contenido de un texto.", []),
            "data": ("pass", "El valor está dentro del rango publicado.", ["ev:10"]),
            "quant": (
                "fail",
                "Se reporta el punto medio de un intervalo amplio como si fuese la estimación.",
                ["ev:10"],
            ),
            "logic": ("pass", "La inferencia es válida bajo sus supuestos.", []),
            "causal": (
                "fail",
                "El vínculo causal se asevera con más firmeza de la que la evidencia sostiene.",
                ["ev:10"],
            ),
            "unc": (
                "fail",
                "No se menciona el intervalo ni que varias especificaciones incluyen el cero.",
                ["ev:10"],
            ),
            "ctx": (
                "fail",
                "Omite el crédito a la inversión, que opera en sentido contrario.",
                [pid(3)],
            ),
            "time": ("na", "El horizonte todavía no transcurre.", []),
            "corrob": (
                "fail",
                "Un único estudio sostiene el rango; no hay corroboración independiente.",
                ["ev:10"],
            ),
            "contra": (
                "fail",
                "El propio estudio invocado es evidencia contra la precisión de la cifra.",
                ["ev:10"],
            ),
        },
        "framing_notes": ["Reporta el punto medio de un rango amplio como si fuera un resultado."],
        "history": ("consistent", ["clm:5"], None),
        "rhetoric": [
            (
                "cherry_picked_statistic",
                "1,2 puntos",
                "Un valor puntual extraído de un intervalo que incluye el cero.",
            )
        ],
        "omitted": [],
    },
    {
        "n": 7,
        "text": "El diseño del paquete privilegia el alivio inmediato por sobre la inversión de largo plazo.",
        "normalised": "En el conjunto de las disposiciones del paquete, las destinadas a alivio inmediato superan en magnitud a las destinadas a inversión de horizonte largo.",
        "type": "interpretation",
        "verdict": "partially_supported",
        "made_at": "2026-08-06T08:00:00Z",
        "article": "art:meridiano:2",
        "role": ROLE_UNION,
        "actor": "actor:confederacion-sindical",
        "outlet": "src:demo-diario-meridiano",
        "topics": ["node:aporte-hogares", "node:credito-inversion", "node:fondo-territorial"],
        "props": [pid(3), pid(4), pid(5), pid(6)],
        "evidence_shown": ["ev:2", "ev:3", "ev:5"],
        "evidence_used": ["ev:2", "ev:3"],
        "redacted": "Quien habla sostiene que el diseño del paquete privilegia el alivio inmediato por sobre la inversión de largo plazo.",
        "reasoning": (
            "Es una lectura defendible y no una afirmación cerrada. Las dos partidas de alivio "
            "(transferencia y seguro de cesantía) superan en monto anual a las dos de inversión "
            "(crédito y Fondo), lo que sostiene la lectura. En contra: el Fondo tiene dotación "
            "permanente mientras la transferencia expira a los 24 meses, de modo que el orden se "
            "invierte si se compara el valor presente en lugar del flujo anual. La interpretación "
            "se sostiene bajo una métrica y no bajo la otra, y ninguna de las dos es la métrica "
            "correcta por definición."
        ),
        "assumptions": [],
        "cluster": "cluster:3",
        "quantities": [],
        "money": [],
        "ec": 0.58,
        "mc": 0.64,
        "limiting": "La conclusión depende de si se compara flujo anual o valor presente.",
        "checks": {
            "txt": (
                "pass",
                "Las cuatro disposiciones citadas existen y tienen los montos indicados.",
                ["ev:2", "ev:3"],
            ),
            "data": (
                "pass",
                "Los montos anuales sostienen la comparación bajo esa métrica.",
                ["ev:5"],
            ),
            "quant": (
                "fail",
                "La comparación no fija la métrica: flujo anual y valor presente ordenan las partidas al revés.",
                ["ev:5"],
            ),
            "logic": ("pass", "La inferencia es válida dentro de la métrica implícita.", []),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": (
                "fail",
                "Se enuncia como lectura única una comparación sensible a la métrica elegida.",
                [],
            ),
            "ctx": (
                "fail",
                "Omite que la transferencia tiene sunset a 24 meses y el Fondo no.",
                [pid(4), pid(5)],
            ),
            "time": (
                "pass",
                "La comparación es coherente con las fechas de vigencia del articulado.",
                [],
            ),
            "corrob": (
                "na",
                "Una interpretación no se corrobora con una segunda fuente; se discute con razones.",
                [],
            ),
            "contra": (
                "pass",
                "Ninguna evidencia más sólida invalida la lectura; sólo la relativiza.",
                [],
            ),
        },
        "framing_notes": ["La comparación implícita es de flujo anual, lo que no se explicita."],
        "history": ("consistent", [], None),
        "rhetoric": [("none_detected", None, None)],
        "omitted": [
            (
                "El aporte de estabilización expira a los 24 meses; la dotación del Fondo territorial es permanente.",
                "Con horizonte largo, la partida de inversión supera a la de alivio, invirtiendo la conclusión.",
                [pid(4), pid(5)],
                "large",
            ),
        ],
    },
    {
        "n": 8,
        "text": "El procedimiento ambiental abreviado se incorporó a pedido de una industria específica.",
        "normalised": "La indicación que incorporó el artículo 10 al proyecto fue propuesta por un actor de una industria determinada.",
        "type": "interpretation",
        "verdict": "unsupported",
        "made_at": "2026-08-06T18:30:00Z",
        "article": "art:boletin:2",
        "role": ROLE_OPPOSITION,
        "actor": "actor:oposicion-finanzas",
        "outlet": "src:demo-boletin-economico",
        "topics": ["node:procedimiento-ambiental", "node:sector-construccion"],
        "props": [pid(8)],
        "evidence_shown": ["ev:9", "ev:1"],
        "evidence_used": ["ev:9"],
        "redacted": "Quien habla sostiene que el procedimiento ambiental abreviado se incorporó a pedido de una industria específica.",
        "reasoning": (
            "El único registro disponible sobre el origen de la indicación es un acta que no "
            "consigna quién la propuso (ev:9). La afirmación no está respaldada por ninguna "
            "pieza del conjunto. Tampoco está refutada: el silencio del acta no prueba lo "
            "contrario. 'Sin respaldo' es el resultado correcto y no debe leerse como 'falso'."
        ),
        "assumptions": [],
        "cluster": None,
        "quantities": [],
        "money": [],
        "ec": 0.2,
        "mc": 0.5,
        "limiting": "No hay registro del origen de la indicación en ninguna fuente del conjunto.",
        "checks": {
            "txt": (
                "fail",
                "Ningún texto disponible atribuye el origen de la indicación.",
                ["ev:9"],
            ),
            "data": ("na", "No hay datos que confrontar.", []),
            "quant": ("na", "La afirmación no contiene cifras.", []),
            "logic": (
                "pass",
                "La afirmación está bien formada; carece de respaldo, no de coherencia.",
                [],
            ),
            "causal": (
                "fail",
                "Atribuye una causa (el pedido de un actor) sin evidencia de esa causa.",
                ["ev:9"],
            ),
            "unc": (
                "fail",
                "Se enuncia como hecho establecido algo sobre lo cual el registro guarda silencio.",
                ["ev:9"],
            ),
            "ctx": (
                "fail",
                "Omite que el acta no consigna el origen de ninguna indicación de esa sesión.",
                ["ev:9"],
            ),
            "time": ("pass", "La fecha de la indicación es coherente con la del acta.", ["ev:9"]),
            "corrob": ("fail", "No hay ninguna fuente, ni una.", []),
            "contra": ("na", "No hay evidencia más sólida en ninguna dirección.", []),
        },
        "framing_notes": [
            "Presenta como establecida una atribución de origen que ninguna fuente consigna."
        ],
        "history": ("insufficient_history", [], None),
        "rhetoric": [
            (
                "anecdote_as_evidence",
                None,
                "La atribución se apoya en la plausibilidad del relato, no en un registro.",
            )
        ],
        "omitted": [],
    },
    {
        "n": 9,
        "text": "Es un error de diseño que el país va a lamentar durante una década.",
        "normalised": "El paquete constituye un error de diseño cuyas consecuencias serán lamentadas durante una década.",
        "type": "opinion",
        "verdict": "not_a_factual_claim",
        "made_at": "2026-08-06T18:30:00Z",
        "article": "art:boletin:2",
        "role": ROLE_OPPOSITION,
        "actor": "actor:oposicion-finanzas",
        "outlet": "src:demo-boletin-economico",
        "topics": ["node:paquete-fiscal"],
        "props": [],
        "evidence_shown": [],
        "evidence_used": [],
        "redacted": "Quien habla sostiene que el paquete es un error de diseño que el país lamentará durante una década.",
        "reasoning": (
            "'Error de diseño' y 'lamentar' son valoraciones, no descripciones de un estado de "
            "cosas: ningún dato las haría verdaderas o falsas. Aleph no fuerza una valoración a "
            "un marco de verdadero/falso, porque hacerlo daría a una opinión la apariencia de un "
            "hecho verificado. Se registra como lo que es y se muestra distinta de un hecho."
        ),
        "assumptions": [],
        "cluster": "cluster:4",
        "quantities": [],
        "money": [],
        "ec": 0.9,
        "mc": 0.86,
        "limiting": None,
        "checks": {
            "txt": ("na", "Una valoración no se contrasta con un pasaje.", []),
            "data": ("na", "No hay proposición empírica que confrontar con datos.", []),
            "quant": ("na", "No hay cifras.", []),
            "logic": ("na", "No hay inferencia que evaluar.", []),
            "causal": ("na", "No se afirma una relación causal verificable.", []),
            "unc": ("na", "No es una proyección con supuestos declarables.", []),
            "ctx": ("na", "La categoría no aplica a una valoración.", []),
            "time": ("na", "No hay fecha que verificar.", []),
            "corrob": ("na", "Una opinión no se corrobora con fuentes.", []),
            "contra": ("na", "Ninguna evidencia puede contradecir una preferencia.", []),
        },
        "framing_notes": ["Enunciada en la gramática de una constatación, no de una opinión."],
        "history": ("not_assessed", [], None),
        "rhetoric": [
            (
                "moral_framing",
                "un error de diseño que el país va a lamentar",
                "La valoración se presenta con la forma de un pronóstico.",
            )
        ],
        "omitted": [],
    },
    {
        "n": 10,
        "text": "Los municipios deberían recibir una proporción fija e irreductible de la recaudación, no un fondo sujeto a reglamento.",
        "normalised": "Corresponde que los municipios reciban una proporción fija de la recaudación en lugar de un fondo cuya distribución dependa de un reglamento.",
        "type": "normative",
        "verdict": "not_a_factual_claim",
        "made_at": "2026-08-05T17:40:00Z",
        "article": "art:contrapunto:2",
        "role": ROLE_MUNICIPAL,
        "actor": "actor:asociacion-municipios",
        "outlet": "src:demo-el-contrapunto",
        "topics": ["node:fondo-territorial", "node:municipios"],
        "props": [pid(5), pid(10)],
        "evidence_shown": ["ev:4"],
        "evidence_used": [],
        "redacted": "Quien habla sostiene que los municipios deberían recibir una proporción fija de la recaudación en lugar de un fondo sujeto a reglamento.",
        "reasoning": (
            "La afirmación dice lo que debería ocurrir, no lo que ocurre. Su premisa fáctica —que "
            "el fondo está sujeto a un reglamento pendiente— es correcta y se verifica por "
            "separado (clm:14). La preferencia entre dos diseños institucionales no es "
            "verificable y no se le asigna veredicto."
        ),
        "assumptions": [],
        "cluster": "cluster:2",
        "quantities": [],
        "money": [],
        "ec": 0.9,
        "mc": 0.84,
        "limiting": None,
        "checks": {
            "txt": ("na", "Una prescripción no se contrasta con un pasaje.", []),
            "data": ("na", "No hay proposición empírica.", []),
            "quant": ("na", "No hay cifras.", []),
            "logic": (
                "pass",
                "La preferencia está formulada de manera coherente con su premisa fáctica.",
                ["ev:4"],
            ),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": ("na", "No es una proyección.", []),
            "ctx": (
                "pass",
                "La premisa fáctica que invoca es exacta y está evidenciada.",
                ["ev:4"],
            ),
            "time": ("na", "No hay fecha que verificar.", []),
            "corrob": ("na", "Una prescripción no se corrobora con fuentes.", []),
            "contra": ("na", "Ninguna evidencia puede contradecir un deber ser.", []),
        },
        "framing_notes": [
            "Combina una premisa fáctica verificable con una prescripción que no lo es."
        ],
        "history": ("consistent", ["clm:2"], None),
        "rhetoric": [("none_detected", None, None)],
        "omitted": [],
    },
    {
        "n": 11,
        "text": "La mitad de las empresas pequeñas ni siquiera sabe que existe la rebaja del impuesto de timbres.",
        "normalised": "Aproximadamente el 50% de las empresas con ingresos anuales de hasta 25.000 UF desconoce la existencia de la rebaja del impuesto de timbres.",
        "type": "fact",
        "verdict": "unverifiable",
        "made_at": "2026-08-06T12:00:00Z",
        "article": "art:canalsur:2",
        "role": ROLE_BUSINESS,
        "actor": "actor:federacion-empresarial",
        "outlet": "src:demo-canal-sur-noticias",
        "topics": ["node:rebaja-timbres", "node:pymes"],
        "props": [pid(2)],
        "evidence_shown": ["ev:16", "ev:1"],
        "evidence_used": ["ev:16"],
        "redacted": "Quien habla sostiene que aproximadamente la mitad de las empresas pequeñas desconoce la rebaja del impuesto de timbres.",
        "reasoning": (
            "La afirmación es empírica y podría comprobarse con una encuesta, pero no hay ninguna "
            "en el conjunto: la búsqueda correspondiente quedó registrada como vacío de "
            "recuperación. Lo único disponible es que el articulado no impone obligación de "
            "difusión (ev:16), que no responde la pregunta. 'No verificable' describe el estado "
            "de la evidencia y no es un juicio sobre quien habla."
        ),
        "assumptions": [],
        "cluster": None,
        "quantities": [quantity(50.0, "percentage", "La mitad", "%")],
        "money": [],
        "ec": 0.1,
        "mc": 0.42,
        "limiting": "No existe en el conjunto ninguna medición del conocimiento de la medida.",
        "checks": {
            "txt": ("na", "No es una afirmación sobre el contenido de un texto.", []),
            "data": ("fail", "No hay datos con los cuales confrontarla.", ["ev:16"]),
            "quant": ("fail", "La cifra de 50% no proviene de ninguna medición disponible.", []),
            "logic": ("pass", "La afirmación está bien formada.", []),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": ("fail", "Se enuncia una proporción precisa sin fuente ni margen.", []),
            "ctx": ("na", "No hay contexto omitido determinable sin la medición.", []),
            "time": (
                "na",
                "La medida entra en vigor en 2027; el conocimiento actual no es contrastable con nada.",
                [],
            ),
            "corrob": ("fail", "Cero fuentes.", []),
            "contra": ("na", "No hay evidencia en ninguna dirección.", []),
        },
        "framing_notes": ["Una proporción redonda presentada sin fuente."],
        "history": ("not_assessed", [], None),
        "rhetoric": [
            ("cherry_picked_statistic", "La mitad", "Cifra redonda sin origen declarado.")
        ],
        "omitted": [],
    },
    {
        "n": 12,
        "text": "La extensión a ocho meses del seguro de cesantía alcanza sólo a los contratos a plazo fijo y por obra o faena.",
        "normalised": "La extensión de cinco a ocho giros del fondo solidario de cesantía se aplica únicamente a trabajadores con contrato a plazo fijo o por obra o faena determinada.",
        "type": "fact",
        "verdict": "supported",
        "made_at": "2026-08-06T08:00:00Z",
        "article": "art:meridiano:2",
        "role": ROLE_UNION,
        "actor": "actor:confederacion-sindical",
        "outlet": "src:demo-diario-meridiano",
        "topics": ["node:seguro-cesantia", "node:trabajadores-plazo-fijo"],
        "props": [pid(6), ppid(9), ppid(10)],
        "evidence_shown": [],
        "evidence_used": [],
        "redacted": "Quien habla sostiene que la extensión a ocho meses del seguro de cesantía alcanza sólo a los contratos a plazo fijo y por obra o faena.",
        "reasoning": (
            "El artículo 8° delimita expresamente el alcance a esos contratos e incluye una "
            "excepción explícita para los contratos indefinidos. La afirmación reproduce el "
            "texto sin ampliarlo ni recortarlo. Es exactamente el tipo de afirmación que la "
            "evidencia primaria puede establecer por completo."
        ),
        "assumptions": [],
        "cluster": "cluster:3",
        "quantities": [quantity(8.0, "count", "ocho meses", "meses")],
        "money": [],
        "ec": 0.88,
        "mc": 0.85,
        "limiting": "El pasaje proviene de un fixture sintético, no del documento real.",
        "checks": {
            "txt": (
                "pass",
                "El artículo 8° delimita el alcance en esos términos y excluye el contrato indefinido.",
                [pid(6)],
            ),
            "data": (
                "pass",
                "No hay otra disposición sobre la materia que pudiera contradecirla.",
                [],
            ),
            "quant": (
                "pass",
                "La cifra de ocho meses corresponde al tope de giros del texto.",
                [pid(6)],
            ),
            "logic": ("pass", "No hay inferencia: es una lectura literal.", []),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": ("pass", "No hay proyección ni estimación involucrada.", []),
            "ctx": (
                "pass",
                "El requisito de doce cotizaciones se menciona en la misma pieza informativa.",
                [pid(6)],
            ),
            "time": ("pass", "La vigencia del artículo comienza el 1 de abril de 2027.", [pid(6)]),
            "corrob": (
                "pass",
                "El texto primario basta para establecer el contenido de una norma.",
                [pid(6)],
            ),
            "contra": ("pass", "Ninguna evidencia más sólida dice otra cosa.", []),
        },
        "framing_notes": [
            "Enuncia la limitación de alcance, que las coberturas resumidas suelen omitir."
        ],
        "history": ("consistent", [], None),
        "rhetoric": [("none_detected", None, None)],
        "omitted": [],
    },
    {
        "n": 13,
        "text": "Las transferencias del fondo territorial comenzarán durante el primer trimestre de 2027.",
        "normalised": "El Fondo de Estabilización Territorial efectuará su primera transferencia a municipios dentro del primer trimestre de 2027.",
        "type": "forecast",
        "verdict": "forecast_conditional",
        "made_at": "2026-08-04T13:00:00Z",
        "article": "art:meridiano:1",
        "role": ROLE_TREASURY,
        "actor": "actor:vocaria-hacienda",
        "outlet": "src:demo-diario-meridiano",
        "topics": ["node:fondo-territorial", "node:reglamento-fondo"],
        "props": [pid(5), pid(10)],
        "evidence_shown": ["ev:4", "ev:11", "ev:13", "ev:14"],
        "evidence_used": ["ev:4"],
        "redacted": "Quien habla sostiene que las transferencias del fondo territorial comenzarán durante el primer trimestre de 2027.",
        "reasoning": (
            "El calendario depende de un acto administrativo que aún no consta: el reglamento que "
            "fija la fórmula de distribución (ev:4). Mientras no exista, el artículo 7° no tiene "
            "regla aplicable. La afirmación es por tanto condicional a que el reglamento se dicte "
            "dentro del plazo y a que la ejecución comience sin rezago. No es verdadera ni falsa "
            "hoy y no se le asigna un veredicto fáctico."
        ),
        "assumptions": [
            "Que el reglamento se dicte dentro de los 180 días que fija el artículo primero transitorio.",
            "Que la primera transferencia no requiera un acto presupuestario adicional.",
            "Que no se produzca el rezago de ejecución observado en fondos comparables.",
        ],
        "cluster": "cluster:2",
        "quantities": [],
        "money": [],
        "ec": 0.32,
        "mc": 0.6,
        "limiting": "El hecho decisivo —la dictación del reglamento— aún no ha ocurrido.",
        "checks": {
            "txt": ("pass", "El plazo de 180 días para el reglamento está en el texto.", ["ev:4"]),
            "data": ("na", "No hay datos de ejecución con los cuales contrastar.", []),
            "quant": ("na", "No hay cifra que verificar.", []),
            "logic": ("pass", "La afirmación es compatible con el plazo legal.", ["ev:4"]),
            "causal": ("na", "No se afirma una relación causal.", []),
            "unc": (
                "fail",
                "Se enuncia como certeza un calendario que depende de un acto pendiente.",
                ["ev:4"],
            ),
            "ctx": (
                "fail",
                "Omite que la transferencia requiere un reglamento que aún no consta dictado.",
                ["ev:4", "ev:13"],
            ),
            "time": ("na", "El período aludido todavía no transcurre.", []),
            "corrob": ("fail", "Ninguna fuente independiente confirma el calendario.", []),
            "contra": (
                "fail",
                "La evidencia de rezago en fondos comparables apunta en sentido contrario.",
                ["ev:11"],
            ),
        },
        "framing_notes": ["Presenta un calendario condicional como un compromiso cerrado."],
        "history": ("consistent", ["clm:1"], None),
        "rhetoric": [("none_detected", None, None)],
        "omitted": [
            (
                "A la fecha de la afirmación no consta la dictación del reglamento que fija la fórmula de distribución.",
                "Sin reglamento el Fondo no tiene regla de reparto aplicable, de modo que el calendario anunciado no está asegurado.",
                ["ev:4", "ev:13"],
                "large",
            ),
        ],
    },
    {
        "n": 14,
        "text": "Sin reglamento no hay fórmula, y sin fórmula no hay transferencia: esto no parte antes de 2028.",
        "normalised": "El Fondo de Estabilización Territorial no efectuará transferencias a municipios antes del año 2028.",
        "type": "forecast",
        "verdict": "forecast_conditional",
        "made_at": "2026-08-05T17:40:00Z",
        "article": "art:contrapunto:2",
        "role": ROLE_MUNICIPAL,
        "actor": "actor:asociacion-municipios",
        "outlet": "src:demo-el-contrapunto",
        "topics": ["node:fondo-territorial", "node:reglamento-fondo"],
        "props": [pid(5), pid(10)],
        "evidence_shown": ["ev:4", "ev:11", "ev:13", "ev:15"],
        "evidence_used": ["ev:4", "ev:11", "ev:13"],
        "redacted": "Quien habla sostiene que el fondo territorial no efectuará transferencias antes de 2028 porque el reglamento aún no existe.",
        "reasoning": (
            "La premisa es correcta y verificable: sin reglamento no hay fórmula de distribución "
            "(ev:4), y al 5 de agosto de 2026 no consta su dictación (ev:13). La conclusión sobre "
            "la fecha no lo es: el plazo legal de 180 días permite que el reglamento exista antes "
            "de 2027, y la evidencia de rezago se basa en cinco casos (ev:11). Es una proyección "
            "condicional, no un hecho, y se registra con los supuestos de los que depende."
        ),
        "assumptions": [
            "Que el reglamento no se dicte dentro del plazo de 180 días.",
            "Que el rezago medio de catorce meses observado en cinco casos comparables se repita aquí.",
        ],
        "cluster": "cluster:2",
        "quantities": [],
        "money": [],
        "ec": 0.42,
        "mc": 0.6,
        "limiting": "La base de comparación para el rezago son cinco casos.",
        "checks": {
            "txt": ("pass", "La dependencia del reglamento está en el texto.", ["ev:4"]),
            "data": (
                "pass",
                "La evidencia de rezago apunta en la dirección de la afirmación.",
                ["ev:11"],
            ),
            "quant": ("na", "No hay cifra que verificar.", []),
            "logic": (
                "pass",
                "La cadena premisa-conclusión es válida bajo los supuestos declarados.",
                ["ev:4"],
            ),
            "causal": (
                "pass",
                "El mecanismo es normativo y directo: sin fórmula no hay reparto posible.",
                ["ev:4"],
            ),
            "unc": (
                "fail",
                "La fecha se enuncia como certeza pese a depender de un acto administrativo pendiente.",
                ["ev:4"],
            ),
            "ctx": (
                "fail",
                "Omite que el plazo legal permite dictar el reglamento antes de 2027.",
                ["ev:4"],
            ),
            "time": ("na", "El período aludido todavía no transcurre.", []),
            "corrob": (
                "pass",
                "Dos fuentes independientes sostienen la premisa: el texto y el reportaje.",
                ["ev:4", "ev:13"],
            ),
            "contra": (
                "pass",
                "Ninguna evidencia más sólida establece que el reglamento ya exista.",
                [],
            ),
        },
        "framing_notes": ["Convierte una premisa verificable en una fecha cerrada."],
        "history": ("consistent", ["clm:2", "clm:10"], None),
        "rhetoric": [
            (
                "urgency_framing",
                "esto no parte antes de 2028",
                "La fecha cerrada dramatiza una dependencia administrativa real.",
            )
        ],
        "omitted": [],
    },
]


def _checks_applied(row: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, name in zip(CHECK_KEYS, CHECK_ORDER, strict=True):
        result, note, refs = row["checks"][key]
        out.append({"check": name, "result": result, "note": note, "evidence_refs": list(refs)})
    return out


def build_claims() -> list[dict[str, Any]]:
    """Every claim carries a speaker-blind verdict and, separately and afterwards,
    an attributed analysis that has no field through which it could alter it."""
    claims = []
    for row in CLAIM_ROWS:
        cid = f"clm:{row['n']}"
        history_kind, prior_refs, history_note = row["history"]
        claims.append(
            {
                "id": cid,
                "text": row["text"],
                "normalised_text": row["normalised"],
                "statement_type": row["type"],
                "topic_refs": row["topics"],
                "made_at": row["made_at"],
                "provenance": {
                    "source_id": row["article"],
                    "source_kind": "article",
                    "url": None,
                    "retrieved_at": RETRIEVED_AT,
                    "span": span(row["text"], page=None, section_id=None, char_start=0),
                    "extractor": EXTRACTOR,
                },
                "quantities": row["quantities"],
                "money": row["money"],
                "blind_evaluation": {
                    "evaluator_version": EVALUATOR_VERSION,
                    "redacted_context": {
                        # No speaker, no role, no outlet: this string is exactly what
                        # the evaluator saw, kept so blindness is auditable.
                        "claim_text": row["redacted"],
                        "context_excerpts": [
                            "El pasaje se presenta sin atribución: no se indica quién lo dijo, en qué medio ni desde qué posición institucional.",
                            "Se acompaña la evidencia listada en evidence_ids, en ese orden.",
                        ],
                        "evidence_ids": row["evidence_shown"],
                        "withheld": WITHHELD_ALL,
                        "redaction_version": REDACTION_VERSION,
                    },
                    "verdict": row["verdict"],
                    "reasoning": row["reasoning"],
                    "evidence_refs": row["evidence_used"],
                    "assumptions_required": row["assumptions"],
                    "confidence": conf(
                        row["ec"],
                        row["mc"],
                        [
                            (
                                "primary_source_coverage",
                                "raises"
                                if any(
                                    e in ("ev:1", "ev:2", "ev:3", "ev:4", "ev:16")
                                    for e in row["evidence_used"]
                                )
                                else "lowers",
                                "El veredicto se apoya en el texto primario."
                                if any(
                                    e in ("ev:1", "ev:2", "ev:3", "ev:4", "ev:16")
                                    for e in row["evidence_used"]
                                )
                                else "El veredicto no se apoya en el texto primario.",
                            ),
                            (
                                "source_independence",
                                "lowers",
                                "El conjunto contiene pocas fuentes originales distintas.",
                            ),
                            (
                                "retrieval_completeness",
                                "lowers",
                                "La recuperación en línea está deshabilitada: la evidencia disponible es la del fixture.",
                            ),
                        ],
                        row["limiting"],
                    ),
                    "uncertainties": [
                        unc(
                            "Todo el conjunto de evidencia es sintético; el veredicto demuestra el procedimiento, no describe ninguna afirmación real.",
                            "out_of_scope",
                            "Ejecutar el mismo procedimiento sobre evidencia recuperada realmente.",
                        )
                    ],
                },
                "attributed_analysis": {
                    "applied_after_verdict": True,
                    "speaker_role": row["role"],
                    "speaker_id": row["actor"],
                    "outlet_id": row["outlet"],
                    "framing_notes": row["framing_notes"],
                    "historical_consistency": {
                        "assessment": history_kind,
                        "prior_claim_refs": prior_refs,
                        "note": history_note,
                    },
                    "rhetorical_pattern": [
                        {
                            "pattern": pat,
                            "span": None
                            if quote is None
                            else span(quote, page=None, section_id=None, char_start=0),
                            "note": note,
                        }
                        for pat, quote, note in row["rhetoric"]
                    ],
                },
                "checks_applied": _checks_applied(row),
                "contradicts": {
                    1: ["clm:5"],
                    5: ["clm:1"],
                    13: ["clm:14"],
                    14: ["clm:13"],
                }.get(row["n"], []),
                "cluster_id": row["cluster"],
                "omitted_context": [
                    {
                        "statement": s,
                        "why_it_matters": w,
                        "evidence_refs": refs,
                        "materiality": mat,
                    }
                    for s, w, refs, mat in row["omitted"]
                ],
                "article_id": row["article"],
                "proposition_refs": row["props"],
            }
        )
    return claims


def build_claims_file() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "document_id": DOC_ID,
        "claims": build_claims(),
    }


# --------------------------------------------------------------------------- #
# Coverage — invented outlets, generic roles, no real person or publication
# --------------------------------------------------------------------------- #

ARTICLE_ROWS: list[dict[str, Any]] = [
    {
        "id": "art:meridiano:1",
        "outlet": "meridiano",
        "type": "news_report",
        "published": "2026-08-04T13:10:00Z",
        "words": 640,
        "independence": "original_reporting",
        "derived_from": None,
        "headline": "El informe financiero cifra en 0,4% del PIB el costo neto del paquete",
        "dek": "La vocería de Hacienda detalló las partidas en un punto de prensa y anunció el calendario del fondo municipal.",
        "author": "Redacción de economía",
        "summary": (
            "El artículo informa que, según el informe financiero adjunto al proyecto, el costo "
            "fiscal neto del paquete asciende a 0,4% del PIB para 2027. Recoge además la "
            "afirmación de la vocería de Hacienda de que ningún hogar de los cuatro primeros "
            "deciles pagará más impuestos y de que las transferencias del fondo municipal "
            "comenzarán en el primer trimestre de 2027. No menciona la sección de limitaciones "
            "del informe."
        ),
        "claims": ["clm:1", "clm:4", "clm:13"],
        "clusters": ["cluster:1"],
        "quotes": [
            (
                ROLE_TREASURY,
                "El costo neto es de cuatro décimas del producto y ningún hogar de los primeros cuatro deciles pagará más impuestos.",
                "clm:1",
            ),
            (
                ROLE_TREASURY,
                "Las transferencias del fondo territorial comenzarán durante el primer trimestre de 2027.",
                "clm:13",
            ),
        ],
        "predictions": [
            (
                "Las transferencias del fondo territorial comenzarán durante el primer trimestre de 2027.",
                ROLE_TREASURY,
                "short_term",
                ["que el reglamento se dicte dentro del plazo de 180 días"],
                True,
                "2027-04-01",
                "clm:13",
            ),
        ],
        "emphasis": [
            ("households_vs_firms", 0.35, "positive"),
            ("central_vs_local", 0.3, "positive"),
            ("current_relief_vs_long_term_investment", 0.2, "negative"),
        ],
        "grounding": [("ev:5", "named_without_link"), (DOC_ID, "paraphrased")],
        "omitted": [
            (
                "El informe financiero declara en su sección de limitaciones que no modela la respuesta de la inversión privada.",
                "El costo neto informado podría ser mayor si esa respuesta es relevante, y el artículo presenta la cifra sin ese matiz.",
                ["ev:6"],
                "medium",
            ),
        ],
        "ec": 0.7,
        "framing": {
            "selection_asymmetry": (
                62,
                "El artículo recoge tres afirmaciones de una sola fuente y ninguna de las otras posiciones disponibles en el mismo período.",
                [
                    ("Tres citas de un único punto de prensa", "negative", 40, ["ev:14"]),
                    (
                        "Ninguna voz municipal ni gremial pese a que ambas habían intervenido",
                        "negative",
                        22,
                        ["ev:15"],
                    ),
                ],
            ),
            "loaded_language": (
                18,
                "El registro es descriptivo; el único término evaluativo es 'histórico' en la bajada.",
                [("Uso de 'histórico' para calificar el fondo municipal", "negative", 18, [])],
            ),
            "context_omission": (
                58,
                "Omite la sección de limitaciones del informe, que es el contexto que más cambia la lectura de la cifra.",
                [
                    (
                        "Silencio sobre la exclusión de la respuesta de inversión",
                        "negative",
                        38,
                        ["ev:6"],
                    ),
                    (
                        "No menciona que el fondo depende de un reglamento pendiente",
                        "negative",
                        20,
                        ["ev:4"],
                    ),
                ],
            ),
            "certainty_inflation": (
                64,
                "Presenta una proyección con la gramática de un dato observado y un calendario condicional como un compromiso.",
                [
                    ("'cifra en 0,4%' en lugar de 'estima en 0,4%'", "negative", 34, ["ev:5"]),
                    (
                        "'comenzarán' sin condicional para el calendario del fondo",
                        "negative",
                        30,
                        ["ev:4"],
                    ),
                ],
            ),
            "unsupported_causal_language": (
                12,
                "No se atribuyen efectos a causas más allá de lo que el informe declara.",
                [("Ausencia de cadenas causales no evidenciadas", "none", 12, [])],
            ),
            "opinion_as_fact": (
                22,
                "Las afirmaciones de la fuente aparecen atribuidas, salvo la bajada, que enuncia el calendario en voz propia.",
                [
                    (
                        "La bajada asume el calendario del fondo sin atribución",
                        "negative",
                        22,
                        ["ev:4"],
                    )
                ],
            ),
            "source_diversity": (
                24,
                "Una sola fuente original: el punto de prensa. El documento se parafrasea, no se cita.",
                [
                    ("Punto de prensa como fuente única", "negative", -20, ["ev:14"]),
                    ("Referencia al informe financiero sin enlace", "positive", 24, ["ev:5"]),
                ],
            ),
            "primary_source_grounding": (
                48,
                "Nombra el informe financiero y parafrasea el articulado, pero no enlaza ni cita textualmente ninguno de los dos.",
                [
                    ("Informe financiero nombrado sin enlace", "positive", 24, ["ev:5"]),
                    ("Articulado parafraseado", "positive", 24, [DOC_ID]),
                ],
            ),
        },
    },
    {
        "id": "art:canalsur:1",
        "outlet": "canalsur",
        "type": "news_report",
        "published": "2026-08-04T14:05:00Z",
        "words": 310,
        "independence": "derivative",
        "derived_from": "art:meridiano:1",
        "headline": "Costo neto del paquete fiscal: 0,4% del PIB según el informe financiero",
        "dek": "Hacienda detalló las partidas del proyecto.",
        "author": None,
        "summary": (
            "Nota breve que reproduce la cifra de 0,4% del PIB y las dos citas de la vocería de "
            "Hacienda publicadas horas antes por otro medio, sin añadir fuentes ni verificación "
            "propia."
        ),
        "claims": ["clm:1"],
        "clusters": ["cluster:1"],
        "quotes": [
            (
                ROLE_TREASURY,
                "El costo neto es de cuatro décimas del producto y ningún hogar de los primeros cuatro deciles pagará más impuestos.",
                "clm:1",
            )
        ],
        "predictions": [],
        "emphasis": [
            ("households_vs_firms", 0.4, "positive"),
            ("central_vs_local", 0.2, "positive"),
        ],
        "grounding": [("ev:5", "named_without_link")],
        "omitted": [
            (
                "La nota no indica que reproduce material publicado previamente por otro medio.",
                "Un lector puede contar dos coberturas como dos observaciones independientes cuando son una sola.",
                ["ev:14"],
                "large",
            ),
        ],
        "ec": 0.5,
        "framing": {
            "selection_asymmetry": (
                70,
                "Reproduce la selección de fuentes del original sin añadir ninguna.",
                [("Selección heredada del artículo de origen", "negative", 70, [])],
            ),
            "loaded_language": (
                14,
                "Registro neutro y breve.",
                [("Sin términos evaluativos identificados", "none", 14, [])],
            ),
            "context_omission": (
                66,
                "Hereda las omisiones del original y suprime además el detalle de las partidas.",
                [
                    ("Omisión heredada sobre limitaciones del informe", "negative", 40, ["ev:6"]),
                    ("Suprime el detalle de partidas del original", "negative", 26, []),
                ],
            ),
            "certainty_inflation": (
                60,
                "El titular convierte la estimación en atributo del paquete.",
                [
                    (
                        "'Costo neto del paquete: 0,4%' como enunciado factual",
                        "negative",
                        60,
                        ["ev:5"],
                    )
                ],
            ),
            "unsupported_causal_language": (
                8,
                "No hay atribuciones causales.",
                [("Sin cadenas causales", "none", 8, [])],
            ),
            "opinion_as_fact": (
                18,
                "La única afirmación en voz propia es la cifra.",
                [("Cifra enunciada sin atribución en el titular", "negative", 18, [])],
            ),
            "source_diversity": (
                10,
                "Cero fuentes propias.",
                [
                    ("Ninguna fuente original", "negative", -10, []),
                    ("Cita heredada de un punto de prensa", "positive", 20, ["ev:14"]),
                ],
            ),
            "primary_source_grounding": (
                20,
                "Menciona el informe financiero sin enlazarlo ni citarlo.",
                [("Informe nombrado sin enlace", "positive", 20, ["ev:5"])],
            ),
        },
    },
    {
        "id": "art:andes:1",
        "outlet": "andes",
        "type": "wire",
        "published": "2026-08-04T14:20:00Z",
        "words": 180,
        "independence": "syndicated",
        "derived_from": "art:meridiano:1",
        "headline": "Informe financiero: costo neto de 0,4% del PIB para el paquete fiscal",
        "dek": None,
        "author": None,
        "summary": (
            "Teletipo que reproduce el titular y el primer párrafo de la cobertura original, con "
            "la misma cita de la vocería de Hacienda y sin material adicional."
        ),
        "claims": ["clm:1"],
        "clusters": ["cluster:1"],
        "quotes": [
            (
                ROLE_TREASURY,
                "El costo neto es de cuatro décimas del producto y ningún hogar de los primeros cuatro deciles pagará más impuestos.",
                "clm:1",
            )
        ],
        "predictions": [],
        "emphasis": [("households_vs_firms", 0.45, "positive")],
        "grounding": [("ev:5", "named_without_link")],
        "omitted": [
            (
                "El teletipo no señala su origen ni que reproduce una cobertura previa.",
                "Sin esa marca, la repetición se contabiliza como corroboración independiente.",
                ["ev:14"],
                "large",
            ),
        ],
        "ec": 0.44,
        "framing": {
            "selection_asymmetry": (
                72,
                "Selección íntegramente heredada.",
                [("Fuente única heredada", "negative", 72, [])],
            ),
            "loaded_language": (
                10,
                "Registro de teletipo.",
                [("Sin términos evaluativos", "none", 10, [])],
            ),
            "context_omission": (
                72,
                "Reduce el original a un párrafo, perdiendo todo el contexto.",
                [("Contexto suprimido por longitud", "negative", 72, ["ev:6"])],
            ),
            "certainty_inflation": (
                58,
                "El titular enuncia la estimación como un hecho del paquete.",
                [("Titular sin marca de estimación", "negative", 58, ["ev:5"])],
            ),
            "unsupported_causal_language": (
                6,
                "No hay atribuciones causales.",
                [("Sin cadenas causales", "none", 6, [])],
            ),
            "opinion_as_fact": (
                14,
                "Todo el contenido está atribuido salvo el titular.",
                [("Titular en voz propia", "negative", 14, [])],
            ),
            "source_diversity": (
                8,
                "Ninguna fuente propia.",
                [
                    ("Sin fuentes originales", "negative", -12, []),
                    ("Cita heredada", "positive", 20, ["ev:14"]),
                ],
            ),
            "primary_source_grounding": (
                16,
                "Nombra el informe sin enlazarlo.",
                [("Informe nombrado sin enlace", "positive", 16, ["ev:5"])],
            ),
        },
    },
    {
        "id": "art:contrapunto:1",
        "outlet": "contrapunto",
        "type": "news_report",
        "published": "2026-08-04T16:40:00Z",
        "words": 420,
        "independence": "derivative",
        "derived_from": "art:meridiano:1",
        "headline": "Gobierno estima el costo del paquete en 0,4% del PIB",
        "dek": "La cifra proviene del informe financiero adjunto al proyecto.",
        "author": "Redacción",
        "summary": (
            "Nota que reproduce la cifra y las citas del punto de prensa difundidas por otro "
            "medio y añade una descripción de las tres medidas de ingreso del proyecto tomada "
            "del articulado. No incorpora fuentes propias."
        ),
        "claims": ["clm:1"],
        "clusters": ["cluster:1"],
        "quotes": [
            (
                ROLE_TREASURY,
                "El costo neto es de cuatro décimas del producto y ningún hogar de los primeros cuatro deciles pagará más impuestos.",
                "clm:1",
            )
        ],
        "predictions": [],
        "emphasis": [
            ("households_vs_firms", 0.3, "mixed"),
            ("redistribution_vs_growth", 0.25, "mixed"),
        ],
        "grounding": [("ev:5", "named_without_link"), (pid(1), "paraphrased")],
        "omitted": [
            (
                "La nota no señala que la cifra y las citas provienen de una cobertura anterior de otro medio.",
                "La repetición sin marca convierte una observación en tres a ojos de un lector.",
                ["ev:14"],
                "medium",
            ),
        ],
        "ec": 0.56,
        "framing": {
            "selection_asymmetry": (
                60,
                "Selección de voces heredada, aunque añade material del articulado.",
                [
                    ("Voces heredadas", "negative", 46, []),
                    ("Añade descripción del articulado", "positive", 14, [pid(1)]),
                ],
            ),
            "loaded_language": (
                16,
                "Registro descriptivo.",
                [("Sin términos evaluativos relevantes", "none", 16, [])],
            ),
            "context_omission": (
                48,
                "Describe las medidas de ingreso pero no las de gasto ni las limitaciones del informe.",
                [
                    ("Sólo el lado de ingresos", "negative", 28, [pid(4)]),
                    ("Sin mención a limitaciones del informe", "negative", 20, ["ev:6"]),
                ],
            ),
            "certainty_inflation": (
                34,
                "El titular usa 'estima', que es la forma correcta.",
                [
                    ("'estima' en el titular", "positive", -12, ["ev:5"]),
                    ("El cuerpo enuncia el calendario sin condicional", "negative", 46, ["ev:4"]),
                ],
            ),
            "unsupported_causal_language": (
                10,
                "No hay atribuciones causales.",
                [("Sin cadenas causales", "none", 10, [])],
            ),
            "opinion_as_fact": (
                16,
                "Contenido atribuido.",
                [("Atribución consistente", "none", 16, [])],
            ),
            "source_diversity": (
                26,
                "Una fuente heredada más el articulado.",
                [
                    ("Fuente heredada", "negative", -8, []),
                    ("Articulado como segunda referencia", "positive", 34, [pid(1)]),
                ],
            ),
            "primary_source_grounding": (
                44,
                "Parafrasea el articulado y nombra el informe sin enlazarlo.",
                [
                    ("Articulado parafraseado", "positive", 26, [pid(1)]),
                    ("Informe nombrado sin enlace", "positive", 18, ["ev:5"]),
                ],
            ),
        },
    },
    {
        "id": "art:boletin:1",
        "outlet": "boletin",
        "type": "analysis",
        "published": "2026-08-05T09:00:00Z",
        "words": 1180,
        "independence": "original_reporting",
        "derived_from": None,
        "headline": "Qué queda fuera del costeo oficial del paquete fiscal",
        "dek": "La sección de limitaciones del informe financiero declara que la respuesta de la inversión no está modelada.",
        "author": "Análisis económico",
        "summary": (
            "Análisis que compara la proyección del informe financiero con el rango de "
            "elasticidad de la literatura disponible y señala que el propio informe declara no "
            "modelar la respuesta de la inversión. Cita textualmente la sección de limitaciones y "
            "enlaza el articulado. Recoge la posición de la federación empresarial y la contrasta "
            "con el rango publicado."
        ),
        "claims": ["clm:1", "clm:5"],
        "clusters": ["cluster:1"],
        "quotes": [
            (
                ROLE_BUSINESS,
                "El costo neto será a lo menos el doble del informado una vez que se incorpore la caída de recaudación por menor inversión.",
                "clm:5",
            )
        ],
        "predictions": [
            (
                "El costo neto será a lo menos el doble del informado.",
                ROLE_BUSINESS,
                "medium_term",
                ["que la elasticidad se sitúe en el extremo alto del rango publicado"],
                True,
                "2028-03-31",
                "clm:5",
            ),
        ],
        "emphasis": [
            ("redistribution_vs_growth", 0.45, "mixed"),
            ("households_vs_firms", 0.25, "mixed"),
        ],
        "grounding": [("ev:6", "quoted_directly"), ("ev:10", "linked"), (DOC_ID, "linked")],
        "omitted": [],
        "ec": 0.78,
        "framing": {
            "selection_asymmetry": (
                28,
                "Recoge la posición empresarial y la contrasta con el rango publicado; no incorpora la posición sindical ni la municipal, que trataban otros aspectos.",
                [
                    ("Una sola voz de actor citada", "negative", 34, []),
                    (
                        "La voz citada se contrasta con evidencia, no se reproduce",
                        "positive",
                        -6,
                        ["ev:10"],
                    ),
                ],
            ),
            "loaded_language": (
                12,
                "Registro técnico y descriptivo.",
                [("Sin términos evaluativos", "none", 12, [])],
            ),
            "context_omission": (
                20,
                "Aporta el contexto que la cobertura del día anterior omitió.",
                [
                    ("Incluye la sección de limitaciones", "positive", -18, ["ev:6"]),
                    (
                        "No menciona el crédito a la inversión como efecto compensatorio",
                        "negative",
                        38,
                        [pid(3)],
                    ),
                ],
            ),
            "certainty_inflation": (
                18,
                "Mantiene el rango y las condiciones en todo el texto.",
                [
                    ("Reporta el intervalo completo del estudio", "positive", -16, ["ev:10"]),
                    ("El titular sugiere una omisión deliberada", "negative", 34, []),
                ],
            ),
            "unsupported_causal_language": (
                26,
                "Describe la cadena causal como hipótesis, no como hecho.",
                [
                    ("Uso sistemático del condicional", "positive", -14, []),
                    (
                        "Un pasaje enuncia la caída de inversión sin condicional",
                        "negative",
                        40,
                        ["ev:10"],
                    ),
                ],
            ),
            "opinion_as_fact": (
                20,
                "La posición del actor aparece siempre atribuida.",
                [("Atribución consistente", "none", 20, [])],
            ),
            "source_diversity": (
                72,
                "Tres orígenes distintos: el informe, el estudio de elasticidad y el articulado, más una voz de actor.",
                [
                    ("Informe financiero citado textualmente", "positive", 26, ["ev:6"]),
                    ("Estudio de elasticidad enlazado", "positive", 26, ["ev:10"]),
                    ("Articulado enlazado", "positive", 20, [DOC_ID]),
                ],
            ),
            "primary_source_grounding": (
                84,
                "Cita textualmente la sección de limitaciones y enlaza tanto el estudio como el articulado.",
                [
                    ("Cita textual del informe", "positive", 38, ["ev:6"]),
                    ("Enlace al estudio", "positive", 24, ["ev:10"]),
                    ("Enlace al articulado", "positive", 22, [DOC_ID]),
                ],
            ),
        },
    },
    {
        "id": "art:contrapunto:2",
        "outlet": "contrapunto",
        "type": "news_report",
        "published": "2026-08-05T18:25:00Z",
        "words": 860,
        "independence": "original_reporting",
        "derived_from": None,
        "headline": "El fondo municipal no puede transferir recursos mientras no exista su reglamento",
        "dek": "La asociación de municipios sostiene que las transferencias no partirán antes de 2028.",
        "author": "Redacción de regiones",
        "summary": (
            "Reportaje que revisa el artículo primero transitorio y constata que, a la fecha de "
            "publicación, no consta la dictación del reglamento que debe fijar la fórmula de "
            "distribución del fondo. Recoge la posición de la presidencia de la asociación de "
            "municipios, que sostiene que las transferencias no comenzarán antes de 2028, y cita "
            "el plazo legal de 180 días."
        ),
        "claims": ["clm:2", "clm:10", "clm:14"],
        "clusters": ["cluster:2"],
        "quotes": [
            (
                ROLE_MUNICIPAL,
                "El fondo transfiere a los municipios 0,18% del producto cada año, sin excepciones.",
                "clm:2",
            ),
            (
                ROLE_MUNICIPAL,
                "Sin reglamento no hay fórmula, y sin fórmula no hay transferencia: esto no parte antes de 2028.",
                "clm:14",
            ),
            (
                ROLE_MUNICIPAL,
                "Los municipios deberían recibir una proporción fija e irreductible de la recaudación, no un fondo sujeto a reglamento.",
                "clm:10",
            ),
        ],
        "predictions": [
            (
                "Las transferencias del fondo no comenzarán antes de 2028.",
                ROLE_MUNICIPAL,
                "medium_term",
                ["que el reglamento no se dicte dentro del plazo de 180 días"],
                True,
                "2028-01-01",
                "clm:14",
            ),
        ],
        "emphasis": [
            ("central_vs_local", 0.6, "mixed"),
            ("public_vs_private_provision", 0.15, "negative"),
        ],
        "grounding": [
            (pid(10), "quoted_directly"),
            ("ev:4", "linked"),
            ("ev:15", "quoted_directly"),
        ],
        "omitted": [
            (
                "El plazo legal de 180 días permite que el reglamento se dicte antes de que termine 2026.",
                "El calendario que el reportaje recoge no es el único compatible con la norma citada.",
                ["ev:4"],
                "medium",
            ),
        ],
        "ec": 0.74,
        "framing": {
            "selection_asymmetry": (
                54,
                "Tres citas de un mismo actor y ninguna respuesta del órgano responsable del reglamento.",
                [
                    ("Tres citas de un único actor", "negative", 40, ["ev:15"]),
                    (
                        "Sin contraparte del órgano obligado a dictar el reglamento",
                        "negative",
                        14,
                        [],
                    ),
                ],
            ),
            "loaded_language": (
                24,
                "El titular usa 'no puede', que es exacto respecto de la norma citada.",
                [
                    (
                        "'no puede transferir' verificado contra el texto",
                        "positive",
                        -10,
                        [pid(10)],
                    ),
                    (
                        "'sujeto a reglamento' con connotación de precariedad en la bajada",
                        "negative",
                        34,
                        [],
                    ),
                ],
            ),
            "context_omission": (
                40,
                "No menciona que el plazo legal admite un calendario distinto del que sostiene la fuente.",
                [
                    (
                        "Silencio sobre el plazo de 180 días como escenario alternativo",
                        "negative",
                        40,
                        ["ev:4"],
                    )
                ],
            ),
            "certainty_inflation": (
                36,
                "Distingue la constatación normativa de la proyección de la fuente, aunque la bajada adopta la fecha de esta última.",
                [
                    ("Distinción explícita entre norma y proyección", "positive", -16, [pid(10)]),
                    ("La bajada adopta 2028 como escenario", "negative", 52, ["ev:4"]),
                ],
            ),
            "unsupported_causal_language": (
                18,
                "La cadena 'sin reglamento no hay transferencia' es normativa y está en el texto.",
                [("Cadena causal verificada contra la norma", "none", 18, [pid(10)])],
            ),
            "opinion_as_fact": (
                30,
                "La afirmación normativa del actor aparece atribuida; la fecha se desliza al titular de sección.",
                [("Fecha de la fuente en la bajada sin atribución", "negative", 30, [])],
            ),
            "source_diversity": (
                58,
                "Dos orígenes: el articulado y la declaración gremial.",
                [
                    ("Articulado citado textualmente", "positive", 34, [pid(10)]),
                    ("Declaración gremial citada", "positive", 24, ["ev:15"]),
                ],
            ),
            "primary_source_grounding": (
                76,
                "Cita textualmente el artículo primero transitorio y enlaza el articulado.",
                [
                    ("Cita textual del transitorio", "positive", 44, [pid(10)]),
                    ("Enlace al articulado", "positive", 32, ["ev:4"]),
                ],
            ),
        },
    },
    {
        "id": "art:meridiano:2",
        "outlet": "meridiano",
        "type": "analysis",
        "published": "2026-08-06T08:15:00Z",
        "words": 940,
        "independence": "original_reporting",
        "derived_from": None,
        "headline": "Quiénes quedan dentro y fuera de la extensión del seguro de cesantía",
        "dek": "La ampliación a ocho giros alcanza a los contratos a plazo fijo y por obra; los indefinidos quedan excluidos.",
        "author": "Análisis laboral",
        "summary": (
            "Análisis del artículo 8° que describe el alcance de la extensión de cinco a ocho "
            "giros del fondo solidario y su requisito de doce cotizaciones. Cita textualmente la "
            "exclusión de los contratos indefinidos y recoge la lectura de una confederación "
            "sindical sobre la orientación general del paquete."
        ),
        "claims": ["clm:7", "clm:12"],
        "clusters": ["cluster:3"],
        "quotes": [
            (
                ROLE_UNION,
                "La extensión a ocho meses del seguro de cesantía alcanza sólo a los contratos a plazo fijo y por obra o faena.",
                "clm:12",
            ),
            (
                ROLE_UNION,
                "El diseño del paquete privilegia el alivio inmediato por sobre la inversión de largo plazo.",
                "clm:7",
            ),
        ],
        "predictions": [],
        "emphasis": [
            ("worker_protection_vs_flexibility", 0.55, "negative"),
            ("current_relief_vs_long_term_investment", 0.25, "negative"),
        ],
        "grounding": [(pid(6), "quoted_directly"), (DOC_ID, "linked")],
        "omitted": [
            (
                "El aporte de estabilización expira a los 24 meses mientras la dotación del fondo territorial es permanente.",
                "La comparación entre alivio e inversión que el artículo recoge se invierte si se mide en valor presente.",
                [pid(4), pid(5)],
                "medium",
            ),
        ],
        "ec": 0.76,
        "framing": {
            "selection_asymmetry": (
                36,
                "Una sola voz de actor, aunque el análisis se apoya sobre todo en el texto.",
                [
                    ("Una voz de actor citada", "negative", 30, []),
                    ("El grueso del artículo es lectura del articulado", "positive", 6, [pid(6)]),
                ],
            ),
            "loaded_language": (
                14,
                "Registro descriptivo.",
                [("Sin términos evaluativos relevantes", "none", 14, [])],
            ),
            "context_omission": (
                44,
                "Recoge la comparación alivio/inversión sin señalar que depende de la métrica.",
                [("No explicita la métrica de la comparación", "negative", 44, [pid(4), pid(5)])],
            ),
            "certainty_inflation": (
                16,
                "El alcance de la norma se describe con exactitud.",
                [
                    ("Alcance descrito con la exclusión incluida", "positive", -14, [pid(6)]),
                    ("La lectura del actor se presenta sin matizar su métrica", "negative", 30, []),
                ],
            ),
            "unsupported_causal_language": (
                14,
                "No hay atribuciones causales.",
                [("Sin cadenas causales", "none", 14, [])],
            ),
            "opinion_as_fact": (
                26,
                "La interpretación del actor aparece atribuida.",
                [("Interpretación atribuida", "none", 26, [])],
            ),
            "source_diversity": (
                54,
                "El articulado y una voz de actor.",
                [
                    ("Articulado citado textualmente", "positive", 34, [pid(6)]),
                    ("Voz de actor", "positive", 20, []),
                ],
            ),
            "primary_source_grounding": (
                80,
                "Cita textualmente la exclusión de los contratos indefinidos y enlaza el articulado.",
                [
                    ("Cita textual del artículo 8°", "positive", 46, [pid(6)]),
                    ("Enlace al articulado", "positive", 34, [DOC_ID]),
                ],
            ),
        },
    },
    {
        "id": "art:canalsur:2",
        "outlet": "canalsur",
        "type": "interview",
        "published": "2026-08-06T12:30:00Z",
        "words": 1320,
        "independence": "original_reporting",
        "derived_from": None,
        "headline": "«El costo neto será a lo menos el doble del informado»",
        "dek": "Entrevista a una economista de una federación empresarial sobre la sobretasa y su efecto en la inversión.",
        "author": "Entrevista",
        "summary": (
            "Entrevista en la que una economista de una federación empresarial sostiene que el "
            "costo neto del paquete duplicará la cifra oficial, proyecta una caída de la "
            "inversión de 1,2 puntos en dos años y afirma que la mitad de las empresas pequeñas "
            "desconoce la rebaja del impuesto de timbres. El texto no contrasta ninguna de las "
            "tres cifras con otra fuente."
        ),
        "claims": ["clm:5", "clm:6", "clm:11"],
        "clusters": ["cluster:3"],
        "quotes": [
            (
                ROLE_BUSINESS,
                "El costo neto será a lo menos el doble del informado una vez que se incorpore la caída de recaudación por menor inversión.",
                "clm:5",
            ),
            (
                ROLE_BUSINESS,
                "La sobretasa reducirá la inversión privada en 1,2 puntos en dos años.",
                "clm:6",
            ),
            (
                ROLE_BUSINESS,
                "La mitad de las empresas pequeñas ni siquiera sabe que existe la rebaja del impuesto de timbres.",
                "clm:11",
            ),
        ],
        "predictions": [
            (
                "La sobretasa reducirá la inversión privada en 1,2 puntos en dos años.",
                ROLE_BUSINESS,
                "medium_term",
                ["que la elasticidad aplicable sea la del punto medio del rango publicado"],
                True,
                "2029-01-01",
                "clm:6",
            ),
        ],
        "emphasis": [
            ("redistribution_vs_growth", 0.5, "positive"),
            ("households_vs_firms", 0.3, "positive"),
        ],
        "grounding": [("ev:5", "named_without_link")],
        "omitted": [
            (
                "El estudio de elasticidad disponible reporta un intervalo de -0,2 a -1,8 puntos, con cuatro de siete especificaciones que incluyen el cero.",
                "La cifra puntual de 1,2 puntos es un valor dentro de un intervalo amplio, no un resultado establecido.",
                ["ev:10"],
                "large",
            ),
            (
                "El mismo paquete crea un crédito del 15% a la inversión en activo fijo.",
                "El efecto neto sobre la inversión depende del saldo de ambas medidas.",
                [pid(3)],
                "medium",
            ),
        ],
        "ec": 0.66,
        "framing": {
            "selection_asymmetry": (
                76,
                "Formato de entrevista con una sola voz y sin contraste de ninguna de las tres cifras.",
                [
                    ("Voz única sin contraparte", "negative", 44, []),
                    ("Ninguna cifra contrastada con evidencia", "negative", 32, ["ev:10"]),
                ],
            ),
            "loaded_language": (
                34,
                "El titular entrecomillado adopta la formulación más fuerte de la entrevistada.",
                [("Titular con la cita más categórica", "negative", 34, [])],
            ),
            "context_omission": (
                78,
                "No menciona el intervalo de la literatura ni el crédito a la inversión.",
                [
                    ("Silencio sobre el intervalo de elasticidad", "negative", 46, ["ev:10"]),
                    ("Silencio sobre el crédito a la inversión", "negative", 32, [pid(3)]),
                ],
            ),
            "certainty_inflation": (
                70,
                "Tres cifras puntuales sin rango ni fuente.",
                [
                    ("'a lo menos el doble' sin rango", "negative", 26, []),
                    ("'1,2 puntos' como resultado establecido", "negative", 26, ["ev:10"]),
                    ("'la mitad' sin fuente", "negative", 18, []),
                ],
            ),
            "unsupported_causal_language": (
                66,
                "La cadena sobretasa → menor inversión → menor recaudación se presenta sin evidencia de ningún eslabón.",
                [("Cadena causal de tres pasos sin cuantificación", "negative", 66, ["ev:10"])],
            ),
            "opinion_as_fact": (
                44,
                "El titular presenta la proyección de la entrevistada como enunciado del medio.",
                [("Titular entrecomillado pero sin sujeto", "negative", 44, [])],
            ),
            "source_diversity": (
                16,
                "Una sola fuente en 1.320 palabras.",
                [
                    ("Fuente única", "negative", -14, []),
                    ("Mención del informe financiero", "positive", 30, ["ev:5"]),
                ],
            ),
            "primary_source_grounding": (
                22,
                "Nombra el informe financiero sin enlazarlo; no cita el articulado.",
                [("Informe nombrado sin enlace", "positive", 22, ["ev:5"])],
            ),
        },
    },
    {
        "id": "art:boletin:2",
        "outlet": "boletin",
        "type": "fact_check",
        "published": "2026-08-06T19:45:00Z",
        "words": 780,
        "independence": "original_reporting",
        "derived_from": None,
        "headline": "¿Es el mayor aumento de impuestos en treinta años? Qué dice la serie",
        "dek": "La comparación depende de la definición de carga tributaria que se use, y bajo la disponible hay dos episodios mayores.",
        "author": "Verificación",
        "summary": (
            "Verificación de la afirmación de que el paquete constituye el mayor aumento de "
            "impuestos de las últimas tres décadas. Reproduce la serie de carga tributaria "
            "disponible, señala dos episodios anuales mayores y advierte que la conclusión "
            "depende de la definición usada. Recoge también dos afirmaciones adicionales del "
            "mismo interviniente: una atribución de origen del artículo 10 y una valoración "
            "sobre el diseño del paquete."
        ),
        "claims": ["clm:3", "clm:8", "clm:9"],
        "clusters": ["cluster:4"],
        "quotes": [
            (
                ROLE_OPPOSITION,
                "Este es el mayor aumento de impuestos de los últimos treinta años.",
                "clm:3",
            ),
            (
                ROLE_OPPOSITION,
                "El procedimiento ambiental abreviado se incorporó a pedido de una industria específica.",
                "clm:8",
            ),
            (
                ROLE_OPPOSITION,
                "Es un error de diseño que el país va a lamentar durante una década.",
                "clm:9",
            ),
        ],
        "predictions": [],
        "emphasis": [
            ("redistribution_vs_growth", 0.4, "mixed"),
            ("environment_vs_project_acceleration", 0.15, "positive"),
        ],
        "grounding": [
            ("ev:7", "linked"),
            ("ev:1", "quoted_directly"),
            ("ev:9", "named_without_link"),
        ],
        "omitted": [],
        "ec": 0.8,
        "framing": {
            "selection_asymmetry": (
                30,
                "Verifica tres afirmaciones de un mismo interviniente sin recoger otras posiciones, lo que es propio del formato.",
                [
                    ("Tres afirmaciones de un solo interviniente", "negative", 36, []),
                    ("El contraste es con evidencia, no con otra voz", "positive", -6, ["ev:7"]),
                ],
            ),
            "loaded_language": (
                16,
                "Registro de verificación, con el titular en forma de pregunta.",
                [
                    ("Titular interrogativo en lugar de afirmativo", "positive", -10, []),
                    ("'episodios mayores' como caracterización propia", "negative", 26, ["ev:7"]),
                ],
            ),
            "context_omission": (
                24,
                "Señala que el paquete también contiene rebajas, que es el contexto material.",
                [
                    ("Menciona las rebajas del mismo paquete", "positive", -20, ["ev:1"]),
                    ("No explicita que la serie usada es sintética", "negative", 44, ["ev:7"]),
                ],
            ),
            "certainty_inflation": (
                14,
                "Enuncia la dependencia de la definición en la bajada.",
                [
                    ("Dependencia de la definición explicitada", "positive", -18, ["ev:7"]),
                    ("La cifra de la serie se presenta sin margen", "negative", 32, ["ev:7"]),
                ],
            ),
            "unsupported_causal_language": (
                12,
                "No hay atribuciones causales propias.",
                [("Sin cadenas causales del medio", "none", 12, [])],
            ),
            "opinion_as_fact": (
                18,
                "Distingue explícitamente la valoración del interviniente de sus afirmaciones fácticas.",
                [
                    ("Valoración marcada como tal", "positive", -14, []),
                    (
                        "La atribución de origen del artículo 10 se recoge sin marcar que carece de registro",
                        "negative",
                        32,
                        ["ev:9"],
                    ),
                ],
            ),
            "source_diversity": (
                66,
                "La serie, el articulado y el acta de comisión.",
                [
                    ("Serie enlazada", "positive", 26, ["ev:7"]),
                    ("Articulado citado", "positive", 22, ["ev:1"]),
                    ("Acta nombrada", "positive", 18, ["ev:9"]),
                ],
            ),
            "primary_source_grounding": (
                78,
                "Enlaza la serie y cita textualmente el artículo 3°; el acta se nombra sin enlace.",
                [
                    ("Serie enlazada", "positive", 32, ["ev:7"]),
                    ("Cita textual del artículo 3°", "positive", 34, ["ev:1"]),
                    ("Acta nombrada sin enlace", "positive", 12, ["ev:9"]),
                ],
            ),
        },
    },
]

LOWER_IS_BETTER = [
    "selection_asymmetry",
    "loaded_language",
    "context_omission",
    "certainty_inflation",
    "unsupported_causal_language",
    "opinion_as_fact",
]
HIGHER_IS_BETTER = ["source_diversity", "primary_source_grounding"]


def framing_profile_id(article_id: str) -> str:
    return "framing:" + article_id.replace("art:", "").replace(":", "-")


def build_articles() -> list[dict[str, Any]]:
    """Coverage collected about the document. An article establishes that an outlet
    published something; whether it is true is settled blind, in `claims`."""
    articles = []
    for row in ARTICLE_ROWS:
        outlet = OUTLETS[row["outlet"]]
        articles.append(
            {
                "id": row["id"],
                # Null: a synthetic item points at nothing because it describes nothing real.
                "url": None,
                "headline": row["headline"],
                "dek": row["dek"],
                "publisher": {"id": outlet["id"], "name": outlet["name"]},
                "author": row["author"],
                "published_at": row["published"],
                "retrieved_at": RETRIEVED_AT,
                "language": "es-CL",
                "article_type": row["type"],
                "word_count": row["words"],
                "neutral_summary": row["summary"],
                "body_available": True,
                "paywalled": False,
                "claim_ids": row["claims"],
                "quotations": [
                    {
                        "text": text,
                        "speaker_role": role,
                        "span": span(text, page=None, section_id=None, char_start=200 + 90 * i),
                        "claim_id": claim_id,
                    }
                    for i, (role, text, claim_id) in enumerate(row["quotes"])
                ],
                "predictions": [
                    {
                        "text": text,
                        "speaker_role": role,
                        "horizon": horizon,
                        "conditions": conditions,
                        "falsifiable": falsifiable,
                        "evaluable_after": after,
                        "claim_id": claim_id,
                    }
                    for text, role, horizon, conditions, falsifiable, after, claim_id in row[
                        "predictions"
                    ]
                ],
                "framing_profile_id": framing_profile_id(row["id"]),
                "impact_emphasis": [
                    {
                        "axis": axis,
                        "emphasis": emph,
                        "direction_emphasised": direction,
                        "note": None,
                    }
                    for axis, emph, direction in row["emphasis"]
                ],
                "omitted_context": [
                    {"statement": s, "why_it_matters": w, "evidence_refs": refs, "materiality": mat}
                    for s, w, refs, mat in row["omitted"]
                ],
                "primary_source_grounding": [
                    {"ref": ref, "kind": kind, "note": None} for ref, kind in row["grounding"]
                ],
                "independence": row["independence"],
                "derived_from_article_id": row["derived_from"],
                "cluster_ids": row["clusters"],
                "confidence": conf(
                    row["ec"],
                    0.72,
                    [
                        (
                            "primary_source_coverage",
                            "raises" if row["ec"] >= 0.7 else "lowers",
                            "El cuerpo del artículo estaba disponible y cita material primario."
                            if row["ec"] >= 0.7
                            else "El artículo se apoya en material de segunda mano.",
                        ),
                        (
                            "source_independence",
                            "lowers" if row["independence"] != "original_reporting" else "neutral",
                            "El ítem reproduce otro y no aporta observación nueva."
                            if row["independence"] != "original_reporting"
                            else "Observación original dentro del conjunto.",
                        ),
                    ],
                    "El artículo es sintético: ningún medio real publicó este texto.",
                ),
            }
        )
    return articles


def build_framing_profiles() -> list[dict[str, Any]]:
    """Eight dimensions, never collapsed into a single bias number. Polarity is
    pinned per dimension so a UI cannot mis-colour a score."""
    profiles = []
    for row in ARTICLE_ROWS:
        dims = {}
        for key, (score, rationale, components) in row["framing"].items():
            polarity = "lower_is_better" if key in LOWER_IS_BETTER else "higher_is_better"
            dims[key] = {
                "score": score,
                "polarity": polarity,
                "components": [comp(lbl, d, w, refs, None) for lbl, d, w, refs in components],
                "evidence_refs": sorted({r for _, _, _, refs in components for r in refs}),
                "confidence": conf(
                    0.62 if row["independence"] == "original_reporting" else 0.44,
                    0.68,
                    [
                        (
                            "primary_source_coverage",
                            "neutral",
                            "La medición se hace sobre el texto del artículo.",
                        ),
                        (
                            "claim_ambiguity",
                            "lowers",
                            "Varias dimensiones dependen de juicios de grado.",
                        ),
                    ],
                    "El texto analizado es sintético.",
                ),
                "rationale": rationale,
            }
        profiles.append(
            {
                "id": framing_profile_id(row["id"]),
                "article_id": row["id"],
                "profile_version": "aleph-framing/0.1.0",
                "generated_at": GENERATED_AT,
                "dimensions": dims,
                "overall_note": (
                    "Léase el patrón, no un promedio: estas ocho cifras describen prácticas "
                    "distintas y no deben colapsarse en un número de sesgo, que no existe en Aleph."
                ),
                "confidence": conf(
                    0.6,
                    0.68,
                    [
                        (
                            "primary_source_coverage",
                            "neutral",
                            "Se dispuso del cuerpo completo del artículo.",
                        )
                    ],
                    "El artículo es sintético; el perfil demuestra el método, no describe a ningún medio real.",
                ),
                "limitations": [
                    "El artículo pertenece a un conjunto sintético: el perfil no describe la práctica de ningún medio real.",
                    "Las dimensiones de grado (lenguaje cargado, inflación de certeza) dependen de juicios del analizador y no de una medición reproducible.",
                ],
            }
        )
    return profiles


# --------------------------------------------------------------------------- #
# Warm phase 6 — clusters. Repeated publication is not independent evidence.
# --------------------------------------------------------------------------- #


def build_clusters() -> list[dict[str, Any]]:
    return [
        {
            "id": "cluster:1",
            "kind": "story_cluster",
            "label": "Costo fiscal neto del paquete según el informe financiero",
            "summary": (
                "Cinco piezas publicadas en poco más de veinticuatro horas informan la misma "
                "cifra. Cuatro de ellas proceden de un único punto de prensa y reproducen la "
                "misma cita; la quinta es un análisis que trabaja sobre el informe y sobre "
                "literatura publicada. El volumen sugiere consenso; la observación independiente "
                "es doble, no quíntuple."
            ),
            "article_ids": [
                "art:meridiano:1",
                "art:canalsur:1",
                "art:andes:1",
                "art:contrapunto:1",
                "art:boletin:1",
            ],
            "claim_ids": ["clm:1", "clm:4", "clm:5", "clm:13"],
            "date_range": {"start": "2026-08-04", "end": "2026-08-05"},
            "independence_analysis": {
                "distinct_original_sources": 2,
                "total_articles": 5,
                "syndication_chains": [
                    {
                        "origin_article_id": "art:meridiano:1",
                        "downstream_article_ids": [
                            "art:canalsur:1",
                            "art:andes:1",
                            "art:contrapunto:1",
                        ],
                        "chain_kind": "verbatim_reuse",
                        "evidence": (
                            "Las cuatro piezas contienen la misma cita textual de veintiuna "
                            "palabras, en el mismo orden y con la misma puntuación, y las tres "
                            "posteriores se publicaron entre 55 y 210 minutos después de la "
                            "primera sin añadir fuentes propias."
                        ),
                        "confidence": conf(
                            0.86,
                            0.8,
                            [
                                (
                                    "evidence_agreement",
                                    "raises",
                                    "Coincidencia literal de la cita y del orden de los párrafos.",
                                )
                            ],
                            "El origen real podría ser el punto de prensa y no la primera pieza publicada.",
                        ),
                    }
                ],
                "shared_origin_evidence": [
                    {
                        "kind": "identical_quote_set",
                        "article_ids": [
                            "art:meridiano:1",
                            "art:canalsur:1",
                            "art:andes:1",
                            "art:contrapunto:1",
                        ],
                        "similarity": 0.97,
                        "detail": (
                            "Cita compartida: «El costo neto es de cuatro décimas del producto y "
                            "ningún hogar de los primeros cuatro deciles pagará más impuestos.» "
                            "Aparece idéntica en las cuatro piezas."
                        ),
                    },
                    {
                        "kind": "same_publication_minute",
                        "article_ids": ["art:canalsur:1", "art:andes:1"],
                        "similarity": 0.9,
                        "detail": "Publicadas con quince minutos de diferencia y con el mismo primer párrafo.",
                    },
                ],
                "independent_corroboration_count": 2,
                "note": (
                    "Cinco artículos, dos observaciones originales. El aparente consenso sobre la "
                    "cifra descansa en un punto de prensa; la única pieza que la examina de forma "
                    "independiente es el análisis, y su conclusión es que el costeo excluye la "
                    "respuesta de inversión."
                ),
            },
            "topic_refs": ["node:costo-fiscal-neto", "node:paquete-fiscal"],
            "confidence": conf(
                0.8,
                0.78,
                [
                    ("source_independence", "lowers", "Cuatro de cinco piezas comparten origen."),
                    (
                        "evidence_agreement",
                        "neutral",
                        "Las piezas coinciden porque repiten la misma fuente.",
                    ),
                ],
                "La cadena se infiere de la coincidencia textual, no de un identificador de agencia.",
            ),
            "uncertainties": [
                unc(
                    "El origen verdadero puede ser el punto de prensa y no la primera pieza observada; en ese caso las cuatro serían derivadas de una fuente externa al conjunto.",
                    "missing_evidence",
                    "El registro horario del punto de prensa.",
                )
            ],
        },
        {
            "id": "cluster:2",
            "kind": "reform_component",
            "label": "Fondo de Estabilización Territorial y su reglamento pendiente",
            "summary": (
                "Cobertura y afirmaciones sobre el fondo municipal. Un reportaje original "
                "constata que el reglamento no consta dictado; la posición del ejecutivo sobre "
                "el calendario proviene del punto de prensa del día anterior."
            ),
            "article_ids": ["art:contrapunto:2"],
            "claim_ids": ["clm:2", "clm:10", "clm:13", "clm:14"],
            "date_range": {"start": "2026-08-04", "end": "2026-08-05"},
            "independence_analysis": {
                "distinct_original_sources": 1,
                "total_articles": 1,
                "syndication_chains": [],
                "shared_origin_evidence": [],
                "independent_corroboration_count": 1,
                "note": (
                    "Una sola pieza original. La constatación sobre el reglamento no ha sido "
                    "corroborada por ninguna otra fuente del conjunto, de modo que descansa "
                    "íntegramente en la búsqueda de un medio."
                ),
            },
            "topic_refs": ["node:fondo-territorial", "node:reglamento-fondo", "node:municipios"],
            "confidence": conf(
                0.6,
                0.7,
                [("source_independence", "lowers", "Una única fuente original.")],
                "Sin corroboración independiente de la ausencia del reglamento.",
            ),
            "uncertainties": [
                unc(
                    "La ausencia de constancia del reglamento se apoya en una búsqueda periodística, no en un registro administrativo consultado.",
                    "missing_evidence",
                    "El registro de actos administrativos del órgano obligado.",
                )
            ],
        },
        {
            "id": "cluster:3",
            "kind": "reform_component",
            "label": "Efectos laborales y de inversión del paquete",
            "summary": (
                "Dos piezas originales que tratan lados distintos del mismo paquete: el alcance "
                "de la extensión del seguro de cesantía y el efecto proyectado de la sobretasa "
                "sobre la inversión. No se contradicen; responden preguntas diferentes."
            ),
            "article_ids": ["art:meridiano:2", "art:canalsur:2"],
            "claim_ids": ["clm:5", "clm:6", "clm:7", "clm:11", "clm:12"],
            "date_range": {"start": "2026-08-06", "end": "2026-08-06"},
            "independence_analysis": {
                "distinct_original_sources": 2,
                "total_articles": 2,
                "syndication_chains": [],
                "shared_origin_evidence": [],
                "independent_corroboration_count": 0,
                "note": (
                    "Dos originales, cero corroboraciones: las piezas son independientes pero no "
                    "confirman el mismo contenido factual, de modo que su independencia no eleva "
                    "la confianza en ninguna afirmación concreta."
                ),
            },
            "topic_refs": ["node:seguro-cesantia", "node:sobretasa-utilidades"],
            "confidence": conf(
                0.66,
                0.7,
                [("source_independence", "raises", "Dos observaciones originales distintas.")],
                "Las dos piezas no se solapan, de modo que ninguna corrobora a la otra.",
            ),
            "uncertainties": [],
        },
        {
            "id": "cluster:4",
            "kind": "claim_cluster",
            "label": "Comparación histórica de la magnitud del alza tributaria",
            "summary": (
                "Agrupa la afirmación sobre el mayor aumento en treinta años y las dos "
                "afirmaciones adicionales recogidas en la misma pieza de verificación."
            ),
            "article_ids": ["art:boletin:2"],
            "claim_ids": ["clm:3", "clm:8", "clm:9"],
            "date_range": {"start": "2026-08-06", "end": "2026-08-06"},
            "independence_analysis": {
                "distinct_original_sources": 1,
                "total_articles": 1,
                "syndication_chains": [],
                "shared_origin_evidence": [],
                "independent_corroboration_count": 1,
                "note": (
                    "Una pieza original. La verificación se apoya en una serie estadística, no en "
                    "el número de medios que repitan la afirmación."
                ),
            },
            "topic_refs": ["node:sobretasa-utilidades", "node:paquete-fiscal"],
            "confidence": conf(
                0.7,
                0.72,
                [
                    (
                        "primary_source_coverage",
                        "raises",
                        "La verificación cita la serie y el articulado.",
                    )
                ],
                "La serie de comparación es sintética.",
            ),
            "uncertainties": [
                unc(
                    "La comparación histórica depende por completo de la definición de carga tributaria adoptada, que la serie fija sin discutir.",
                    "definitional_ambiguity",
                    "Una serie con definición documentada y varias definiciones alternativas.",
                )
            ],
        },
    ]


# --------------------------------------------------------------------------- #
# Contradictions — the same evidence applied to every position
# --------------------------------------------------------------------------- #


def build_contradictions() -> list[dict[str, Any]]:
    return [
        {
            "id": "contra:1",
            "question_at_issue": "¿El costo fiscal neto efectivo del paquete en 2027 será equivalente a 0,4% del PIB?",
            "positions": [
                {
                    "claim_id": "clm:1",
                    "speaker_role": ROLE_TREASURY,
                    "stance": "qualified_affirm",
                    "summary": (
                        "Afirma la cifra de 0,4% del PIB. La afirmación versa sobre lo que el "
                        "informe financiero estima, no sobre el resultado que se observará."
                    ),
                    "evidence_cited_by_actor": ["ev:5"],
                },
                {
                    "claim_id": "clm:5",
                    "speaker_role": ROLE_BUSINESS,
                    "stance": "denies",
                    "summary": (
                        "Sostiene que el costo efectivo será al menos el doble, una vez "
                        "incorporada la menor recaudación por caída de la inversión."
                    ),
                    "evidence_cited_by_actor": ["ev:6"],
                },
            ],
            "shared_evidence": [
                {
                    "evidence_id": "ev:5",
                    "what_it_establishes": "Que el órgano responsable estimó un costo neto de 0,4% del PIB para 2027 bajo un supuesto de crecimiento de 2,3%.",
                    "what_it_cannot_establish": "Que el costo efectivo será esa cifra: el informe proyecta, no observa.",
                    "bears_on_positions": ["clm:1", "clm:5"],
                },
                {
                    "evidence_id": "ev:6",
                    "what_it_establishes": "Que el propio informe declara no modelar la respuesta de la inversión privada.",
                    "what_it_cannot_establish": "Cuál sería la magnitud de esa respuesta, ni que sea grande.",
                    "bears_on_positions": ["clm:1", "clm:5"],
                },
                {
                    "evidence_id": "ev:10",
                    "what_it_establishes": "Que las estimaciones publicadas de elasticidad cubren un rango de -0,2 a -1,8 puntos y que varias especificaciones incluyen el cero.",
                    "what_it_cannot_establish": "Que el efecto sea el del extremo del rango, ni que el rango sea trasladable a esta jurisdicción.",
                    "bears_on_positions": ["clm:1", "clm:5"],
                },
            ],
            "what_the_primary_source_says": {
                "statement": (
                    "El articulado no contiene ninguna estimación de costo: fija tasas, montos y "
                    "plazos. La cifra proviene del informe financiero adjunto, que la presenta "
                    "como proyección."
                ),
                "evidence_refs": ["ev:1", "ev:2", "ev:3"],
                "assumptions": [],
            },
            "what_projections_say": {
                "statement": (
                    "La proyección oficial sitúa el costo neto en 0,4% del PIB excluyendo la "
                    "respuesta de inversión. La literatura disponible no permite cuantificar esa "
                    "respuesta con precisión: su intervalo va de casi nulo a considerable."
                ),
                "evidence_refs": ["ev:5", "ev:6", "ev:10"],
                "assumptions": [
                    "Crecimiento real del producto de 2,3% anual entre 2027 y 2030.",
                    "Tasa de toma del aporte de estabilización de 92%.",
                    "Ausencia de respuesta conductual de la inversión, declarada explícitamente.",
                ],
            },
            "what_is_uncertain": [
                unc(
                    "La magnitud de la respuesta de la inversión a la sobretasa no está establecida por ninguna evidencia disponible.",
                    "conflicting_evidence",
                    "Una estimación de elasticidad para esta jurisdicción y este diseño, o el anexo metodológico del informe.",
                ),
                unc(
                    "El efecto compensatorio del crédito del artículo 5° sobre la inversión no está cuantificado por ninguna fuente.",
                    "missing_evidence",
                    "Un costeo desagregado por medida.",
                ),
            ],
            "aleph_conclusion": {
                "statement": (
                    "La evidencia disponible establece qué estimó el órgano responsable y que su "
                    "ejercicio excluye la respuesta de inversión. No establece cuál será el costo "
                    "efectivo, y por tanto no decide entre las dos posiciones: una describe "
                    "correctamente la proyección, la otra propone una corrección cuya magnitud la "
                    "evidencia no sostiene."
                ),
                "verdict": "forecast_conditional",
                "confidence": conf(
                    0.52,
                    0.68,
                    [
                        (
                            "primary_source_coverage",
                            "raises",
                            "La proyección y su limitación constan en la fuente.",
                        ),
                        (
                            "evidence_agreement",
                            "lowers",
                            "El rango de elasticidad es demasiado amplio para decidir.",
                        ),
                        (
                            "retrieval_completeness",
                            "lowers",
                            "No hay contra-estimación independiente en el conjunto.",
                        ),
                    ],
                    "Ninguna evidencia observa el resultado; ambas posiciones hablan de un ejercicio futuro.",
                ),
                "reasoning": (
                    "Se aplicó el mismo conjunto de tres piezas a las dos posiciones. ev:5 sostiene "
                    "la primera sólo en el plano de lo que el informe estima. ev:6 concede a la "
                    "segunda su premisa: la exclusión de la respuesta de inversión es real y "
                    "declarada. ev:10 le niega su conclusión: el intervalo publicado no singulariza "
                    "un valor y menos el de su extremo. El resultado es que la pregunta no se "
                    "decide con lo disponible, y decirlo es preferible a fabricar un ganador."
                ),
                "evidence_refs": ["ev:5", "ev:6", "ev:10"],
            },
            "resolvable": True,
            "resolvable_by": (
                "El anexo metodológico del informe financiero, con la elasticidad de inversión "
                "supuesta y el desglose por medida, permitiría comparar ambas proyecciones sobre "
                "la misma base."
            ),
            "topic_refs": ["node:costo-fiscal-neto", "node:sobretasa-utilidades"],
            "cluster_id": "cluster:1",
        },
        {
            "id": "contra:2",
            "question_at_issue": "¿El Fondo de Estabilización Territorial efectuará transferencias a municipios durante 2027?",
            "positions": [
                {
                    "claim_id": "clm:13",
                    "speaker_role": ROLE_TREASURY,
                    "stance": "affirms",
                    "summary": "Sostiene que las transferencias comenzarán en el primer trimestre de 2027.",
                    "evidence_cited_by_actor": [],
                },
                {
                    "claim_id": "clm:14",
                    "speaker_role": ROLE_MUNICIPAL,
                    "stance": "denies",
                    "summary": "Sostiene que el Fondo no transferirá recursos antes de 2028 porque el reglamento aún no existe.",
                    "evidence_cited_by_actor": ["ev:13"],
                },
            ],
            "shared_evidence": [
                {
                    "evidence_id": "ev:4",
                    "what_it_establishes": "Que la fórmula de distribución no está en la ley sino en un reglamento que debe dictarse dentro de 180 días desde la publicación.",
                    "what_it_cannot_establish": "Si el reglamento se dictará dentro de ese plazo, ni en qué fecha comenzarán las transferencias.",
                    "bears_on_positions": ["clm:13", "clm:14"],
                },
                {
                    "evidence_id": "ev:13",
                    "what_it_establishes": "Que al 5 de agosto de 2026 una búsqueda periodística no encontró constancia de la dictación del reglamento.",
                    "what_it_cannot_establish": "Que el reglamento no exista ni que no vaya a dictarse dentro del plazo.",
                    "bears_on_positions": ["clm:13", "clm:14"],
                },
                {
                    "evidence_id": "ev:11",
                    "what_it_establishes": "Que en cinco casos revisados el rezago medio entre creación legal y primera ejecución fue de catorce meses.",
                    "what_it_cannot_establish": "Que este Fondo tendrá ese rezago; cinco casos no sostienen una expectativa general.",
                    "bears_on_positions": ["clm:13", "clm:14"],
                },
            ],
            "what_the_primary_source_says": {
                "statement": (
                    "El artículo 7° condiciona su entrada en operación a la publicación del "
                    "reglamento, y el artículo primero transitorio fija un plazo de 180 días "
                    "para dictarlo. El texto no fija fecha de primera transferencia ni "
                    "consecuencia por el incumplimiento del plazo."
                ),
                "evidence_refs": ["ev:3", "ev:4"],
                "assumptions": [],
            },
            "what_projections_say": {
                "statement": (
                    "El informe financiero imputa el gasto del Fondo íntegramente al ejercicio "
                    "2027, lo que supone implícitamente que el reglamento se dicta a tiempo. Ese "
                    "supuesto no se declara como tal en el documento."
                ),
                "evidence_refs": ["ev:5", "ev:11"],
                "assumptions": [
                    "Que el reglamento se dicta dentro del plazo legal.",
                    "Que la primera transferencia no requiere un acto presupuestario adicional.",
                ],
            },
            "what_is_uncertain": [
                unc(
                    "No consta el estado de tramitación del reglamento en ningún registro administrativo consultado.",
                    "missing_evidence",
                    "El registro de actos administrativos del órgano obligado a dictarlo.",
                ),
                unc(
                    "El hecho que decidiría la disputa —la dictación del reglamento— todavía no ha ocurrido.",
                    "temporal",
                    "El transcurso del plazo de 180 días.",
                ),
            ],
            "aleph_conclusion": {
                "statement": (
                    "La disputa no puede resolverse con la evidencia actual porque depende de un "
                    "acto administrativo que aún no ocurre. Lo que sí está establecido es la "
                    "dependencia: sin reglamento no hay fórmula de reparto, y por tanto ninguna "
                    "de las dos fechas está asegurada."
                ),
                "verdict": "forecast_conditional",
                "confidence": conf(
                    0.44,
                    0.66,
                    [
                        (
                            "primary_source_coverage",
                            "raises",
                            "La dependencia normativa consta en el texto.",
                        ),
                        (
                            "retrieval_completeness",
                            "lowers",
                            "No se consultó ningún registro administrativo.",
                        ),
                        ("temporal_consistency", "lowers", "El hecho decisivo es futuro."),
                    ],
                    "El acto que decidiría la cuestión todavía no ha ocurrido.",
                ),
                "reasoning": (
                    "Las tres piezas se aplicaron a ambas posiciones sin excepción. ev:4 acota a "
                    "las dos: ninguna puede afirmar una fecha, porque la norma no la fija. ev:13 "
                    "aporta una constatación negativa que es débil por construcción: no encontrar "
                    "algo no es que no exista. ev:11 apunta en la dirección de la segunda posición "
                    "pero con una base de cinco casos, insuficiente para sostener una fecha. "
                    "Reportar el empate es preferible a inventar un ganador."
                ),
                "evidence_refs": ["ev:4", "ev:11", "ev:13"],
            },
            "resolvable": False,
            "resolvable_by": (
                "Sólo la dictación del reglamento —o el vencimiento del plazo sin dictarlo— "
                "decidirá la cuestión. Ninguna evidencia existente hoy puede hacerlo."
            ),
            "topic_refs": ["node:fondo-territorial", "node:reglamento-fondo"],
            "cluster_id": "cluster:2",
        },
    ]


# --------------------------------------------------------------------------- #
# Neutrality — Aleph's report on its own behaviour, not on the document
# --------------------------------------------------------------------------- #

NEUTRALITY_TESTED = [f"clm:{n}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 14)]

# (family, runs, flips, note, examples)
PERTURBATION_ROWS: list[tuple[str, int, int, str, list[dict[str, Any]]]] = [
    (
        "speaker_swap",
        44,
        1,
        "Cada afirmación se re-atribuyó a otro rol funcional de formalidad equivalente, manteniendo texto y evidencia idénticos.",
        [
            {
                "claim_id": "clm:4",
                "sub": "rol atribuido reemplazado por un rol gremial de formalidad equivalente",
                "ov": "partially_supported",
                "pv": "supported",
                "cd": 0.09,
                "fd": 3.0,
                "esd": 0.31,
                "changed": True,
                "note": "Fuga: al cambiar el rol, el evaluador dejó de exigir evidencia sobre la incidencia indirecta. Revisión humana requerida.",
            },
            {
                "claim_id": "clm:1",
                "sub": "rol atribuido reemplazado por un rol técnico sin vínculo con el ejecutivo",
                "ov": "supported",
                "pv": "supported",
                "cd": 0.01,
                "fd": 0.0,
                "esd": 0.06,
                "changed": False,
                "note": "Sin cambio: el razonamiento sigue apoyándose en el informe y no en quién habla.",
            },
        ],
    ),
    (
        "source_swap",
        44,
        0,
        "Se sustituyó el medio que difundió cada afirmación por otro del mismo conjunto sintético.",
        [
            {
                "claim_id": "clm:3",
                "sub": "medio difusor reemplazado por otro medio del conjunto",
                "ov": "contradicted",
                "pv": "contradicted",
                "cd": 0.0,
                "fd": 0.0,
                "esd": 0.04,
                "changed": False,
                "note": "El veredicto sigue descansando en la serie estadística, que no cambió.",
            }
        ],
    ),
    (
        "party_swap",
        44,
        0,
        "Se intercambiaron las condiciones de gobierno y oposición entre las posiciones. Es el único lugar del sistema donde el partido aparece, y aparece como variable que se revuelve deliberadamente.",
        [
            {
                "claim_id": "clm:13",
                "sub": "condición de gobierno y oposición intercambiada entre las dos posiciones",
                "ov": "forecast_conditional",
                "pv": "forecast_conditional",
                "cd": 0.0,
                "fd": 0.0,
                "esd": 0.03,
                "changed": False,
                "note": "El veredicto depende de un acto administrativo pendiente, que el intercambio no altera.",
            },
            {
                "claim_id": "clm:14",
                "sub": "condición de gobierno y oposición intercambiada entre las dos posiciones",
                "ov": "forecast_conditional",
                "pv": "forecast_conditional",
                "cd": 0.01,
                "fd": 0.0,
                "esd": 0.05,
                "changed": False,
                "note": "Simétrico al anterior: ambas posiciones reciben el mismo tratamiento.",
            },
        ],
    ),
    (
        "authority_removal",
        33,
        2,
        "Se eliminaron las señales de estatus institucional en la presentación de la evidencia, conservando su contenido palabra por palabra.",
        [
            {
                "claim_id": "clm:1",
                "sub": "el informe se presentó como 'un documento de costeo' sin señalar el órgano emisor",
                "ov": "supported",
                "pv": "partially_supported",
                "cd": -0.14,
                "fd": 6.0,
                "esd": 0.35,
                "changed": True,
                "note": "Defecto: el veredicto se apoyaba en parte en el estatus del emisor y no sólo en el contenido. Revisión humana requerida.",
            },
            {
                "claim_id": "clm:2",
                "sub": "el articulado se presentó sin encabezado institucional",
                "ov": "supported",
                "pv": "supported",
                "cd": -0.02,
                "fd": 0.0,
                "esd": 0.08,
                "changed": False,
                "note": "Sin cambio: el contenido normativo es verificable con independencia del encabezado.",
            },
        ],
    ),
    (
        "claim_paraphrase",
        33,
        1,
        "Cada afirmación se reformuló conservando su contenido proposicional. Las paráfrasis que alteraron el contenido se descartaron como errores del arnés y no se contaron como cambios.",
        [
            {
                "claim_id": "clm:7",
                "sub": "reformulación de la comparación conservando su contenido",
                "ov": "partially_supported",
                "pv": "unsupported",
                "cd": -0.11,
                "fd": 4.0,
                "esd": 0.42,
                "changed": True,
                "note": "Fuga de forma: la reformulación hizo explícita la métrica implícita y el evaluador la trató como una afirmación distinta. Revisión humana requerida.",
            }
        ],
    ),
    (
        "evidence_order_shuffle",
        33,
        0,
        "Se presentó el mismo conjunto de evidencia en orden distinto, sin añadir ni quitar piezas.",
        [
            {
                "claim_id": "clm:5",
                "sub": "orden de presentación de las tres piezas de evidencia invertido",
                "ov": "forecast_conditional",
                "pv": "forecast_conditional",
                "cd": 0.0,
                "fd": 0.0,
                "esd": 0.05,
                "changed": False,
                "note": "Sin efectos de primacía observados en esta familia.",
            }
        ],
    ),
]


def _perturbation_example(family: str | None, ex: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": ex["claim_id"],
        "perturbation": family,
        "substitution": ex["sub"],
        "original_verdict": ex["ov"],
        "perturbed_verdict": ex["pv"],
        "delta": {
            "confidence_delta": ex["cd"],
            "framing_delta": ex["fd"],
            "explanation_semantic_delta": ex["esd"],
            "verdict_changed": ex["changed"],
        },
        "note": ex["note"],
    }


def build_neutrality_report() -> dict[str, Any]:
    perturbations = {}
    runs_total = 0
    flips_total = 0
    for family, runs, flips, note, examples in PERTURBATION_ROWS:
        runs_total += runs
        flips_total += flips
        perturbations[family] = {
            "runs": runs,
            "flips": flips,
            "flip_rate": round(flips / runs, 4),
            "examples": [_perturbation_example(None, e) for e in examples],
            "note": note,
        }

    failures = [
        _perturbation_example(family, e)
        for family, _, _, _, examples in PERTURBATION_ROWS
        for e in examples
        if e["changed"]
    ]

    # The components sum EXACTLY to neutrality_health, so opening the number in the
    # interface reproduces it rather than asking the reader to trust it.
    components = [
        comp(
            f"Invariancia de veredicto observada: {runs_total - flips_total} de {runs_total} corridas perturbadas",
            "positive",
            98,
            [],
            "Punto de partida del indicador: la proporción de corridas en que el veredicto no se movió.",
        ),
        comp(
            "Dos cambios al retirar señales de estatus institucional",
            "negative",
            -10,
            ["clm:1"],
            "Indica dependencia parcial de la autoridad de la fuente y no sólo de su contenido.",
        ),
        comp(
            "Un cambio de veredicto en el intercambio de hablante",
            "negative",
            -6,
            ["clm:4"],
            "Toda variación en esta familia es por construcción injustificada.",
        ),
        comp(
            "Un cambio ante reformulación de la afirmación",
            "negative",
            -4,
            ["clm:7"],
            "El veredicto siguió la forma superficial en lugar del contenido.",
        ),
        comp(
            "Muestra de once afirmaciones: insuficiente para estimar una tasa estable",
            "negative",
            -4,
            [],
            "Con esta muestra, un solo caso mueve la tasa agregada en más de dos puntos.",
        ),
        comp(
            "Desviación semántica media del razonamiento de 0,157 pese a veredictos estables",
            "negative",
            -2,
            [],
            "El veredicto se mantiene, pero la justificación se reescribe alrededor de la sustitución.",
        ),
    ]
    health = sum(int(c["weight"]) for c in components)

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "report_version": "aleph-neutrality/0.1.0",
        "evaluator_version": EVALUATOR_VERSION,
        "sample": {
            "claims_tested": len(NEUTRALITY_TESTED),
            "runs_total": runs_total,
            "claim_ids": NEUTRALITY_TESTED,
            "selection_method": (
                "Exhaustiva sobre las afirmaciones con veredicto fáctico o condicional, "
                "estratificada por statement_type. Se excluyeron las tres afirmaciones con "
                "veredicto 'not_a_factual_claim' o 'unverifiable', que no admiten cambio de "
                "veredicto y habrían inflado artificialmente la invariancia."
            ),
        },
        "perturbations": perturbations,
        "metrics": {
            "verdict_flip_rate": round(flips_total / runs_total, 4),
            "confidence_delta": 0.043,
            "framing_delta": 1.9,
            "explanation_semantic_delta": 0.157,
        },
        "neutrality_health": health,
        "neutrality_health_polarity": "higher_is_better",
        "neutrality_health_components": components,
        "confidence": conf(
            0.4,
            0.65,
            [
                (
                    "evidence_agreement",
                    "raises",
                    "Las familias sin cambios son consistentes entre corridas.",
                ),
                (
                    "retrieval_completeness",
                    "lowers",
                    "La muestra es de once afirmaciones sobre un corpus sintético.",
                ),
            ],
            "El tamaño de muestra no permite estimar tasas de cambio con precisión.",
        ),
        "interpretation_caveat": (
            "Este informe mide INVARIANCIA ANTE SUSTITUCIONES IRRELEVANTES y NO establece "
            "neutralidad política. Un sistema puede ser perfectamente invariante al cambio de "
            "hablante y aun así equivocarse de forma sistemática en una dirección. Lo que esta "
            "prueba no puede ver: qué afirmaciones se eligieron examinar y cuáles no; qué "
            "fuentes entraron al corpus de evidencia y cuáles quedaron fuera; qué preguntas se "
            "formularon para recuperar esa evidencia; y las disposiciones que el propio modelo "
            "evaluador arrastra de su entrenamiento. Un valor alto aquí acota una falla concreta "
            "y no autoriza a leer el resto del análisis como imparcial. Además, esta corrida se "
            "ejecutó sobre un conjunto sintético, con un evaluador simulado y una muestra "
            "pequeña: el número demuestra el procedimiento, no certifica el producto."
        ),
        "limitations": [
            "Once afirmaciones son una muestra pequeña: un solo caso mueve la tasa agregada en más de dos puntos porcentuales.",
            "Las familias de reformulación y de retiro de autoridad se ejecutaron con menos corridas que las tres primeras.",
            "No se probaron afirmaciones con veredicto 'unverifiable' ni 'not_a_factual_claim': en ellas un cambio de veredicto es imposible por construcción y su inclusión inflaría la invariancia.",
            "El evaluador es el proveedor determinista simulado; un modelo real puede exhibir sensibilidades distintas.",
            "Todo el corpus es sintético, de modo que el resultado no dice nada sobre el comportamiento del sistema frente a evidencia recuperada realmente.",
        ],
        "failures_to_investigate": failures,
    }


# --------------------------------------------------------------------------- #
# Warm phase 7 — readiness. The gate the rest of the bundle is read through.
# --------------------------------------------------------------------------- #

READINESS_GAPS: dict[str, list[dict[str, Any]]] = {
    "news_coverage": [
        {
            "id": "gap:retrieval-disabled",
            "dimension": "news_coverage",
            "description": (
                "La recuperación en línea está DESHABILITADA por la política de recuperación bajo "
                "demanda (ALEPH_RETRIEVAL_MODE=manual). Ningún medio real fue consultado: los "
                "nueve artículos del conjunto son sintéticos y sus medios son inventados."
            ),
            "severity": "blocking",
            "missing_kind": "independent_reporting",
            "what_would_resolve": (
                "Ejecutar la recuperación con --fetch sobre el registro de fuentes real, con "
                "robots.txt respetado y límite de tasa por host."
            ),
            "affected_claim_ids": ["clm:1", "clm:3", "clm:5", "clm:13", "clm:14"],
            "blocking_since": GENERATED_AT,
        },
        {
            "id": "gap:coverage-window",
            "dimension": "news_coverage",
            "description": "La cobertura del conjunto abarca tres días; no hay material anterior al ingreso del proyecto ni posterior al 6 de agosto.",
            "severity": "major",
            "missing_kind": "time_period",
            "what_would_resolve": "Recuperar cobertura del período de tramitación completo, desde mayo de 2026.",
            "affected_claim_ids": [],
            "blocking_since": None,
        },
    ],
    "evidence_diversity": [
        {
            "id": "gap:no-counter-estimate",
            "dimension": "evidence_diversity",
            "description": (
                "No hay ninguna estimación de costo elaborada fuera del ejecutivo. La única "
                "proyección del conjunto y la única declaración de sus limitaciones provienen "
                "del mismo documento."
            ),
            "severity": "blocking",
            "missing_kind": "counter_evidence",
            "what_would_resolve": "Un costeo independiente del paquete, o el anexo metodológico que permita replicar el oficial.",
            "affected_claim_ids": ["clm:1", "clm:5"],
            "blocking_since": GENERATED_AT,
        },
        {
            "id": "gap:synthetic-datasets",
            "dimension": "evidence_diversity",
            "description": "Las dos series estadísticas del conjunto son sintéticas y no describen ninguna jurisdicción real.",
            "severity": "major",
            "missing_kind": "official_data",
            "what_would_resolve": "Series estadísticas oficiales de carga tributaria y de finanzas municipales.",
            "affected_claim_ids": ["clm:3"],
            "blocking_since": None,
        },
    ],
    "primary_source_coverage": [
        {
            "id": "gap:pdf-not-downloaded",
            "dimension": "primary_source_coverage",
            "description": (
                "El documento primario registrado en source.url no fue descargado: el articulado "
                "analizado es un fixture sintético. Toda la trazabilidad apunta a un texto que "
                "Aleph fabricó."
            ),
            "severity": "major",
            "missing_kind": "primary_document",
            "what_would_resolve": "Descargar y extraer el documento indicado en source.url mediante una llamada explícita de recuperación.",
            "affected_claim_ids": [],
            "blocking_since": None,
        }
    ],
    "temporal_coverage": [
        {
            "id": "gap:no-post-implementation",
            "dimension": "temporal_coverage",
            "description": "No hay evidencia posterior a la entrada en vigor porque el articulado rige desde 2027: las proyecciones no pueden contrastarse con resultados.",
            "severity": "major",
            "missing_kind": "time_period",
            "what_would_resolve": "Datos de ejecución de 2027 en adelante.",
            "affected_claim_ids": ["clm:5", "clm:6", "clm:13", "clm:14"],
            "blocking_since": None,
        }
    ],
    "claim_coverage": [
        {
            "id": "gap:unevidenced-claims",
            "dimension": "claim_coverage",
            "description": "Dos de las catorce afirmaciones no tienen ninguna evidencia asociada: una opinión y una prescripción, que no admiten evidencia por su naturaleza.",
            "severity": "minor",
            "missing_kind": "other",
            "what_would_resolve": None,
            "affected_claim_ids": ["clm:9", "clm:10"],
            "blocking_since": None,
        }
    ],
    "source_independence": [
        {
            "id": "gap:syndication-share",
            "dimension": "source_independence",
            "description": "Tres de los nueve artículos reproducen una misma pieza; sólo seis son observaciones originales.",
            "severity": "major",
            "missing_kind": "independent_reporting",
            "what_would_resolve": "Recuperar cobertura de medios que no reproduzcan el mismo punto de prensa.",
            "affected_claim_ids": ["clm:1"],
            "blocking_since": None,
        }
    ],
    "document_understanding": [
        {
            "id": "gap:table-extraction",
            "dimension": "document_understanding",
            "description": "La tabla de efecto fiscal por año no pudo estructurarse; las cifras anuales se leyeron del texto corrido.",
            "severity": "minor",
            "missing_kind": "document_section",
            "what_would_resolve": "Extracción de tablas sobre el archivo original.",
            "affected_claim_ids": [],
            "blocking_since": None,
        }
    ],
}

# (dimension, score, weight, rationale, components)
READINESS_ROWS: list[tuple[str, int, float, str, list[tuple[str, str, float, list[str]]]]] = [
    (
        "document_understanding",
        86,
        0.20,
        "Las diez disposiciones operativas están delimitadas con texto verbatim, y las cuatro asunciones del informe fueron extraídas con su span. La única pérdida es la tabla de efecto fiscal por año.",
        [
            ("Diez disposiciones extraídas con span verbatim", "positive", 40, [pid(1), pid(10)]),
            ("Catorce proposiciones atómicas con pasaje citable", "positive", 28, [ppid(1)]),
            ("Cuatro asunciones del informe extraídas explícitamente", "positive", 22, []),
            ("La tabla de efecto fiscal por año no se estructuró", "negative", -2, []),
            ("El texto es un fixture: no proviene del archivo original", "negative", -2, []),
        ],
    ),
    (
        "primary_source_coverage",
        78,
        0.20,
        "Cinco de dieciséis piezas de evidencia son el texto operativo mismo y dos son el informe financiero adjunto, incluida su sección de limitaciones. Falta el archivo original.",
        [
            (
                "Cinco piezas de evidencia son el texto operativo",
                "positive",
                40,
                ["ev:1", "ev:2", "ev:3", "ev:4"],
            ),
            (
                "El informe financiero y su sección de limitaciones están citados textualmente",
                "positive",
                30,
                ["ev:5", "ev:6"],
            ),
            ("Un acta de comisión cubre el origen de una indicación", "positive", 12, ["ev:9"]),
            ("El documento indicado en source.url no fue descargado", "negative", -4, []),
        ],
    ),
    (
        "news_coverage",
        34,
        0.12,
        "Nueve artículos en tres días, todos sintéticos. La recuperación en línea está deshabilitada, de modo que esta dimensión no mide cobertura real sino el tamaño del fixture.",
        [
            ("Nueve artículos con cuerpo completo disponible", "positive", 28, []),
            (
                "Cinco tipos de artículo representados, incluida una verificación",
                "positive",
                18,
                [],
            ),
            ("Ventana de sólo tres días", "negative", -6, []),
            ("Ningún medio real fue consultado: recuperación deshabilitada", "negative", -6, []),
        ],
    ),
    (
        "temporal_coverage",
        45,
        0.12,
        "La evidencia cubre desde noviembre de 2025 hasta agosto de 2026, pero no alcanza el período de vigencia del articulado, que comienza en 2027.",
        [
            (
                "Evidencia desde noviembre de 2025 hasta agosto de 2026",
                "positive",
                30,
                ["ev:10", "ev:13"],
            ),
            ("Siete eventos fechados en la línea de tiempo", "positive", 15, []),
            ("Sin evidencia posterior a la entrada en vigor", "negative", 0, []),
        ],
    ),
    (
        "evidence_diversity",
        38,
        0.14,
        "Ocho de los nueve niveles de evidencia están representados, lo que es amplio; pero no hay ninguna contra-estimación independiente del costeo, que es la pieza que más importaría.",
        [
            ("Ocho de nueve tiers representados", "positive", 34, []),
            (
                "Dos series estadísticas y un estudio revisado por pares",
                "positive",
                16,
                ["ev:7", "ev:8", "ev:10"],
            ),
            ("Ninguna estimación de costo elaborada fuera del ejecutivo", "negative", -8, []),
            ("Las series disponibles son sintéticas", "negative", -4, []),
        ],
    ),
    (
        "claim_coverage",
        71,
        0.12,
        "Doce de catorce afirmaciones tienen evidencia asociada. Las dos restantes son una opinión y una prescripción, que no admiten evidencia por su naturaleza y se muestran como tales.",
        [
            ("Doce de catorce afirmaciones con evidencia asociada", "positive", 46, []),
            ("Las diez comprobaciones epistémicas se aplicaron a las catorce", "positive", 26, []),
            (
                "Dos afirmaciones sin evidencia, por su naturaleza no fáctica",
                "negative",
                -1,
                ["clm:9", "clm:10"],
            ),
        ],
    ),
    (
        "source_independence",
        42,
        0.10,
        "Seis observaciones originales sobre nueve artículos. Un tercio de la cobertura reproduce una sola pieza, y sin esta dimensión esa repetición se leería como corroboración.",
        [
            ("Seis fuentes originales identificadas", "positive", 32, []),
            ("Una cadena de sindicación detectada y trazada", "positive", 18, []),
            ("Tres de nueve artículos reproducen la misma pieza", "negative", -8, []),
        ],
    ),
]


def build_readiness() -> dict[str, Any]:
    """The gate. `publishable` is false because two blocking gaps remain, and the
    reason is stated in plain language rather than implied by a low number."""
    dimensions = {}
    weighted = 0.0
    for name, score, weight, rationale, components in READINESS_ROWS:
        dimensions[name] = {
            "score": score,
            "weight": weight,
            "rationale": rationale,
            "components": [comp(lbl, d, w, refs, None) for lbl, d, w, refs in components],
            "gaps": READINESS_GAPS.get(name, []),
            "confidence": conf(
                0.6,
                0.68,
                [
                    (
                        "retrieval_completeness",
                        "lowers",
                        "La recuperación en línea está deshabilitada.",
                    )
                ],
                "El conjunto es sintético.",
            ),
        }
        weighted += score * weight

    blocking = [g for gaps in READINESS_GAPS.values() for g in gaps if g["severity"] == "blocking"]

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "document_id": DOC_ID,
        "generated_at": GENERATED_AT,
        "overall_state": "partial",
        "overall_score": round(weighted),
        "polarity": "higher_is_better",
        "dimensions": dimensions,
        "blocking_gaps": blocking,
        "publishable": False,
        "why_not_publishable": (
            "La lectura del documento y la cobertura de fuentes primarias son sólidas, pero dos "
            "vacíos bloqueantes siguen abiertos. Primero: la recuperación en línea está "
            "deshabilitada por la política de recuperación bajo demanda "
            "(ALEPH_RETRIEVAL_MODE=manual), de modo que ningún medio real fue consultado y los "
            "nueve artículos de este análisis son sintéticos. Segundo: no existe ninguna "
            "estimación de costo elaborada fuera del ejecutivo, por lo que la cifra central del "
            "análisis no tiene contraste independiente. En consecuencia, lo que se muestra a "
            "continuación demuestra cómo funciona el procedimiento de Aleph y NO constituye un "
            "hallazgo sobre ninguna reforma real. Para levantar el bloqueo hay que ejecutar la "
            "recuperación con --fetch sobre el registro de fuentes real y obtener al menos un "
            "costeo independiente."
        ),
        "confidence": conf(
            0.55,
            0.7,
            [
                ("primary_source_coverage", "raises", "El texto operativo está cubierto y citado."),
                (
                    "source_independence",
                    "lowers",
                    "Un tercio de la cobertura reproduce una sola pieza.",
                ),
                ("retrieval_completeness", "lowers", "Ninguna consulta se ejecutó realmente."),
            ],
            "La recuperación en línea está deshabilitada, de modo que los vacíos reflejan una política y no una búsqueda agotada.",
        ),
        "evidence_inventory": {
            "evidence_items": len(EVIDENCE_ROWS),
            "primary_documents": sum(1 for r in EVIDENCE_ROWS if r["tier"] == "primary_document"),
            "statistical_datasets": sum(
                1 for r in EVIDENCE_ROWS if r["tier"] == "statistical_dataset"
            ),
            "articles": len(ARTICLE_ROWS),
            "clusters": 4,
            "independent_sources": sum(
                1 for a in ARTICLE_ROWS if a["independence"] == "original_reporting"
            ),
            "distinct_tiers": len({r["tier"] for r in EVIDENCE_ROWS}),
            "claims_total": len(CLAIM_ROWS),
            "claims_with_evidence": sum(1 for c in CLAIM_ROWS if c["evidence_used"]),
            "propositions_total": len(PROPOSITION_ROWS),
            "earliest_evidence_date": "2025-11-14",
            "latest_evidence_date": "2026-08-06",
        },
        "phase_status": [
            {
                "phase": "document_understanding",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": len(PROVISIONS),
                "note": "Ejecutada sobre un fixture sintético, no sobre el archivo indicado en source.url.",
            },
            {
                "phase": "proposition_extraction",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": len(PROPOSITION_ROWS),
                "note": None,
            },
            {
                "phase": "topic_graph",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": len(NODE_ROWS),
                "note": "Cinco aristas son inferidas y deben mostrarse como razonamiento de Aleph, no como afirmaciones del documento.",
            },
            {
                "phase": "search_vocabulary",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": 24,
                "note": "El grupo de sinónimos quedó vacío: la expansión multilingüe requiere recuperación en línea.",
            },
            {
                "phase": "evidence_collection",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": len(EVIDENCE_ROWS),
                "note": "Ninguna consulta se ejecutó contra la red: bajo ALEPH_RETRIEVAL_MODE=manual la evidencia proviene del fixture.",
            },
            {
                "phase": "news_clustering",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": 4,
                "note": None,
            },
            {
                "phase": "readiness",
                "state": "complete",
                "completed_at": GENERATED_AT,
                "item_count": 7,
                "note": None,
            },
        ],
        "recommended_actions": [
            "Ejecutar scripts/refresh.py --fetch sobre el registro de fuentes real para reemplazar la cobertura sintética por cobertura recuperada.",
            "Descargar y extraer el documento indicado en source.url mediante una llamada explícita de recuperación.",
            "Obtener al menos una estimación de costo elaborada fuera del ejecutivo, o el anexo metodológico del informe financiero.",
            "Ampliar la ventana temporal de cobertura al período completo de tramitación, desde mayo de 2026.",
            "Sustituir las dos series sintéticas por series estadísticas oficiales.",
        ],
        "notes": SYNTHETIC_NOTICE,
    }


# --------------------------------------------------------------------------- #
# Timeline and methodology
# --------------------------------------------------------------------------- #


def build_timeline() -> list[dict[str, Any]]:
    rows = [
        (
            "2026-05-12",
            "Ingreso del proyecto con su informe financiero",
            "document_published",
            "El articulado y el informe financiero adjunto entran a tramitación.",
            ["ev:1", "ev:2", "ev:3"],
        ),
        (
            "2026-05-20",
            "Inicio de la discusión en comisión",
            "committee_stage",
            "La comisión abre la discusión general del proyecto.",
            ["ev:9"],
        ),
        (
            "2026-06-18",
            "Indicación que incorpora el procedimiento ambiental abreviado",
            "amendment",
            "Se aprueba la indicación que agrega el artículo 10. El acta no consigna el origen de la propuesta.",
            ["ev:9"],
        ),
        (
            "2026-07-02",
            "Publicación del informe financiero complementario",
            "official_report",
            "Se publica la versión del informe que incluye la sección de limitaciones.",
            ["ev:5", "ev:6"],
        ),
        (
            "2026-08-04",
            "Punto de prensa sobre el costo neto",
            "statement",
            "La vocería de Hacienda comunica la cifra de 0,4% del PIB y el calendario del fondo municipal.",
            ["ev:14"],
        ),
        (
            "2026-08-05",
            "Declaración del gremio municipal sobre el calendario del fondo",
            "statement",
            "La presidencia de la asociación de municipios sostiene que el fondo no operará antes de 2028.",
            ["ev:15", "ev:13"],
        ),
        (
            "2026-08-06",
            "Verificación pública de la comparación histórica",
            "media_event",
            "Una pieza de verificación contrasta la afirmación sobre el mayor aumento en treinta años con la serie disponible.",
            ["ev:7"],
        ),
    ]
    return [
        {"date": d, "label": label, "description": desc, "kind": kind, "evidence_refs": refs}
        for d, label, kind, desc, refs in rows
    ]


def build_methodology() -> dict[str, Any]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "model_provider": "mock",
        "phases_completed": [
            "document_understanding",
            "proposition_extraction",
            "topic_graph",
            "search_vocabulary",
            "evidence_collection",
            "news_clustering",
            "readiness",
        ],
        "limitations": [
            "TODO EL CONJUNTO ES SINTÉTICO. Ningún texto, cifra, cita, medio ni declaración corresponde a algo real. Los cinco medios son inventados y los hablantes son roles genéricos, nunca personas.",
            "El documento indicado en source.url nunca fue descargado: se registra como configuración del documento objetivo y el articulado analizado es un fixture.",
            "La recuperación en línea está deshabilitada (ALEPH_RETRIEVAL_MODE=manual). Ninguna consulta del vocabulario de búsqueda se ejecutó contra la red, de modo que los vacíos de recuperación reflejan esa política y no una búsqueda agotada.",
            "El proveedor de modelo es el simulador determinista: los veredictos demuestran el procedimiento de evaluación ciega, no el juicio de un modelo de lenguaje real.",
            "Las ponderaciones de los ejes de impacto y de las dimensiones de encuadre son juicios del analizador, no mediciones; se publican con sus componentes para que puedan disputarse pieza por pieza.",
            "El informe de neutralidad mide invariancia ante sustituciones irrelevantes y NO establece neutralidad política; no puede ver sesgos de selección de corpus ni de elección de qué afirmaciones examinar.",
            "Las proyecciones del articulado rigen desde 2027, de modo que ninguna de ellas puede contrastarse todavía con un resultado observado.",
            "Aleph no emite ninguna puntuación agregada de sesgo ni ubicación en un eje izquierda-derecha, y ninguna cifra de este conjunto debe combinarse para producir una.",
        ],
        "generated_by": "scripts/generate_sample_data.py (aleph-export/0.1.0)",
    }


# --------------------------------------------------------------------------- #
# The bundle — the single export the frontend consumes
# --------------------------------------------------------------------------- #


def build_provision_summaries() -> list[dict[str, Any]]:
    """Denormalised projection of the provisions for rendering. `document` remains
    authoritative; where the two disagree, the document wins."""
    return [
        {
            "id": pid(p["n"]),
            "ref_label": p["ref_label"],
            "title": p["title"],
            "summary": p["summary"],
            "text": p["text"],
            "spans": [_provision_span(p)],
            "quantities": p["quantities"],
            "money": p["money"],
            "topic_refs": p["topics"],
            "impact_axis_refs": p["impact_axes"],
            "proposition_refs": [ppid(n) for n in p["props"]],
            "status": "como fue ingresado",
        }
        for p in PROVISIONS
    ]


def build_bundle() -> dict[str, Any]:
    claims = build_claims()
    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "document": build_document(),
        "propositions": build_propositions(),
        "topic_graph": build_topic_graph(),
        "search_vocabulary": build_search_vocabulary(),
        "provisions": build_provision_summaries(),
        "impact_map": build_impact_map(),
        "claims": claims,
        "evidence": build_evidence_items(),
        "articles": build_articles(),
        "clusters": build_clusters(),
        "contradictions": build_contradictions(),
        "neutrality_report": build_neutrality_report(),
        "readiness": build_readiness(),
        "timeline": build_timeline(),
        "methodology": build_methodology(),
        "framing_profiles": build_framing_profiles(),
        "actor_profiles": build_actor_profiles(claims),
    }


def build_actor_profiles(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Build generic-role profiles from verdicts produced in the blind stage."""
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in CLAIM_ROWS:
        actor = row["actor"]
        if actor in seen:
            continue
        seen.add(actor)
        actor_claims = [
            claim
            for claim in claims
            if claim["attributed_analysis"]["speaker_id"] == actor
            and claim["attributed_analysis"]["applied_after_verdict"] is True
        ]
        by_verdict: dict[str, int] = {}
        by_statement_type: dict[str, int] = {}
        for claim in actor_claims:
            verdict = claim["blind_evaluation"]["verdict"]
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
            kind = claim["statement_type"]
            by_statement_type[kind] = by_statement_type.get(kind, 0) + 1
        dates = sorted(claim["made_at"][:10] for claim in actor_claims if claim["made_at"])
        profile_source = source_ref(
            "src:demo-attribution-record",
            "Registro sintético de atribuciones",
            "political_statement",
            publisher="Aleph demo",
        )
        profiles.append(
            {
                "id": actor,
                "display_name": row["role"],
                "is_natural_person": False,
                "jurisdiction": "CL",
                "roles": [
                    {
                        "title": row["role"],
                        "institution": "institución genérica del conjunto sintético",
                        "level": "other",
                        "from": None,
                        "to": None,
                        "source": profile_source,
                    }
                ],
                "affiliations": [],
                "declared_interests": [],
                "legal_record": [],
                "claim_track_record": {
                    "sample_size": len(actor_claims),
                    "by_verdict": by_verdict,
                    "by_statement_type": by_statement_type,
                    "evaluated_claim_ids": [claim["id"] for claim in actor_claims],
                    "period": None if not dates else {"from": dates[0], "to": dates[-1]},
                    "caveat": (
                        "Muestra pequeña y no aleatoria: incluye sólo afirmaciones que Aleph "
                        "analizó a ciegas; no representa una trayectoria completa ni predice "
                        "la veracidad de afirmaciones futuras."
                    ),
                },
                "profile_uncertainties": [
                    unc(
                        "El perfil representa un rol genérico y no una persona real.",
                        "out_of_scope",
                        "Habilitar recuperación contra registros oficiales para perfiles reales.",
                    )
                ],
                "sources": [profile_source],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "usable_in_blind_evaluation": False,
        "actors": profiles,
    }


# --------------------------------------------------------------------------- #
# news/latest.json — the feed the homepage renders
# --------------------------------------------------------------------------- #

VERDICT_ORDER = [
    "supported",
    "partially_supported",
    "unsupported",
    "contradicted",
    "unverifiable",
    "not_a_factual_claim",
    "forecast_conditional",
]

CLUSTER_LABELS = {
    "cluster:1": "Costo fiscal neto del paquete según el informe financiero",
    "cluster:2": "Fondo de Estabilización Territorial y su reglamento pendiente",
    "cluster:3": "Efectos laborales y de inversión del paquete",
    "cluster:4": "Comparación histórica de la magnitud del alza tributaria",
}

TOPIC_LABELS = {row[0]: row[2] for row in NODE_ROWS}


def build_news_feed(bundle: dict[str, Any]) -> dict[str, Any]:
    """Per-article summary metrics for the homepage.

    Shape follows `NewsFeed`/`NewsFeedItem` in frontend/src/types/aleph.ts: each
    item embeds the whole article and its framing profile, so a card can render
    without a second fetch. Both summary scores carry their polarity and their
    components, because a bare number on a feed card would be exactly the opaque
    metric Aleph exists to refuse.
    """
    claims_by_id = {c["id"]: c for c in bundle["claims"]}
    profiles = {p["article_id"]: p for p in bundle["framing_profiles"]}
    articles = {a["id"]: a for a in bundle["articles"]}
    independents = {
        c["id"]: c["independence_analysis"]["distinct_original_sources"] for c in bundle["clusters"]
    }

    items = []
    for row in ARTICLE_ROWS:
        breakdown = dict.fromkeys(VERDICT_ORDER, 0)
        for cid in row["claims"]:
            breakdown[claims_by_id[cid]["blind_evaluation"]["verdict"]] += 1

        profile = profiles[row["id"]]
        grounding = profile["dimensions"]["primary_source_grounding"]

        # Beneficiary emphasis: how much of the article's attention goes to who
        # gains and who pays. Descriptive, hence polarity 'neutral' — a high value
        # is neither good nor bad, it is a shape of coverage.
        emphasis_map = {axis: emph for axis, emph, _ in row["emphasis"]}
        beneficiary_axes = [
            "households_vs_firms",
            "redistribution_vs_growth",
            "central_vs_local",
            "worker_protection_vs_flexibility",
        ]
        beneficiary_score = round(100 * sum(emphasis_map.get(a, 0.0) for a in beneficiary_axes))
        beneficiary_components = [
            comp(
                f"Atención al eje {axis}",
                direction,
                round(100 * emph),
                [],
                None,
            )
            for axis, emph, direction in row["emphasis"]
            if axis in beneficiary_axes
        ] or [comp("El artículo no aborda ninguno de los ejes de incidencia", "none", 0, [], None)]

        cluster_id = row["clusters"][0]
        topic_id = {
            "cluster:1": "node:costo-fiscal-neto",
            "cluster:2": "node:fondo-territorial",
            "cluster:3": "node:seguro-cesantia",
            "cluster:4": "node:sobretasa-utilidades",
        }[cluster_id]

        items.append(
            {
                "article": articles[row["id"]],
                "document_slug": DOC_SLUG,
                "document_title": "Paquete fiscal de demostración",
                "framing_profile": profile,
                "claim_count": len(row["claims"]),
                "verdict_counts": breakdown,
                "cluster_id": cluster_id,
                "independent_source_count": independents[cluster_id],
                # --- additive keys, not yet in the NewsFeedItem interface ---
                "relative_time": relative_time_es(row["published"]),
                "cluster_label": CLUSTER_LABELS[cluster_id],
                "topic": {"id": topic_id, "label": TOPIC_LABELS[topic_id.removeprefix("node:")]},
                "claim_ids": row["claims"],
                "beneficiary_emphasis": {
                    "score": beneficiary_score,
                    "polarity": "neutral",
                    "label": "Énfasis en incidencia",
                    "description": (
                        "Cuánta atención del artículo recae sobre quién gana y quién paga. Es una "
                        "descripción de la atención editorial, no un reproche: un artículo sobre "
                        "finanzas municipales tiene razones legítimas para concentrarse en un eje."
                    ),
                    "components": beneficiary_components,
                },
                "primary_grounding": {
                    "score": grounding["score"],
                    "polarity": grounding["polarity"],
                    "label": "Anclaje en fuente primaria",
                    "description": (
                        "Cuánto de lo que el artículo afirma está anclado en material que el "
                        "lector puede revisar por su cuenta. Nombrar una fuente sin apuntar a "
                        "ella puntúa menos que citarla o enlazarla."
                    ),
                    "components": grounding["components"],
                },
                "framing_profile_id": profile["id"],
            }
        )

    items.sort(key=lambda i: i["article"]["published_at"], reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "notice": SYNTHETIC_NOTICE,
        "retrieval_mode": "manual",
        "retrieval_note": (
            "La recuperación en línea está deshabilitada. Ningún medio real fue consultado y "
            "ninguno de estos titulares fue publicado por nadie."
        ),
        "counts": {
            "articles": len(items),
            "distinct_outlets": len({i["article"]["publisher"]["id"] for i in items}),
            "original_reporting": sum(
                1 for i in items if i["article"]["independence"] == "original_reporting"
            ),
            "clusters": len({i["cluster_id"] for i in items}),
        },
        "items": items,
    }


# --------------------------------------------------------------------------- #
# index.json — the site manifest
# --------------------------------------------------------------------------- #


def build_index(bundle: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any]:
    """The site manifest.

    Shape follows `SiteIndex`/`SiteIndexEntry` in frontend/src/types/aleph.ts. The
    second entry exists so the home page lists a set rather than one orphan card,
    and it is honest about being unanalysed: readiness 'insufficient', no counts,
    no path.
    """
    readiness = bundle["readiness"]
    identity = bundle["document"]["identity"]
    return {
        "schema_version": SCHEMA_VERSION,
        "data_status": DATA_STATUS,
        "generated_at": GENERATED_AT,
        "notice": SYNTHETIC_NOTICE,
        "featured": DOC_SLUG,
        "analyses": [
            {
                "slug": DOC_SLUG,
                "title": "Paquete fiscal de demostración",
                "short_title": identity["short_title"],
                "subtitle": (
                    "Articulado e informe financiero: sobretasa transitoria, transferencia a "
                    "hogares, fondo de inversión municipal y una regla de gasto."
                ),
                "summary": identity["summary"],
                "document_type": identity["document_type"],
                "jurisdiction": "Chile",
                "institution": identity["institution"],
                "language": identity["language"],
                "status": identity["status"],
                "data_status": DATA_STATUS,
                "generated_at": GENERATED_AT,
                "published_at": identity["dates"]["published"],
                "readiness_state": readiness["overall_state"],
                "readiness_score": readiness["overall_score"],
                "publishable": readiness["publishable"],
                "counts": {
                    "provisions": len(bundle["provisions"]),
                    "propositions": len(bundle["propositions"]["propositions"]),
                    "claims": len(bundle["claims"]),
                    "evidence": len(bundle["evidence"]),
                    "articles": len(bundle["articles"]),
                    "clusters": len(bundle["clusters"]),
                    "contradictions": len(bundle["contradictions"]),
                },
                "path": f"reforms/{DOC_SLUG}.json",
                # --- additive keys, not yet in the SiteIndexEntry interface ---
                "state": "published",
                "last_analysed": GENERATED_AT,
                "claims_path": f"claims/{DOC_SLUG}.json",
                "evidence_path": f"evidence/{DOC_SLUG}.json",
            },
            {
                "slug": "presupuesto-demo-2027",
                "title": "Ley de presupuestos de demostración 2027",
                "short_title": None,
                "subtitle": (
                    "Segundo caso de demostración. Todavía sin analizar: la recuperación bajo "
                    "demanda mantiene apagada toda búsqueda hasta que se pida explícitamente."
                ),
                "summary": None,
                "document_type": "budget",
                "jurisdiction": "Chile",
                "institution": None,
                "language": "es-CL",
                "status": "unknown",
                "data_status": DATA_STATUS,
                "generated_at": GENERATED_AT,
                "published_at": None,
                "readiness_state": "insufficient",
                "readiness_score": 0,
                "publishable": False,
                "counts": {
                    "provisions": 0,
                    "propositions": 0,
                    "claims": 0,
                    "evidence": 0,
                    "articles": 0,
                    "clusters": 0,
                    "contradictions": 0,
                },
                "path": None,
                "state": "coming_soon",
                "last_analysed": None,
                "claims_path": None,
                "evidence_path": None,
            },
        ],
        "news": {
            "path": "news/latest.json",
            "article_count": len(feed["items"]),
            "latest_published_at": feed["items"][0]["article"]["published_at"],
        },
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _schema_store() -> dict[str, dict[str, Any]]:
    """Load every schema in schemas/ into a lookup keyed several ways.

    Two views of the same files are needed.

    ``by_id`` keeps the declared https ``$id`` and is what the modern
    ``referencing`` registry uses: a relative ``"$ref": "common.json"`` inside a
    schema whose ``$id`` is ``https://…/proposition.json`` resolves to
    ``https://…/common.json``, which the registry answers from disk.

    ``local`` holds ``$id``-stripped copies keyed by file URI, which is what the
    legacy ``RefResolver`` needs. With the ``$id`` present, jsonschema pushes a
    resolution scope on every descent into a referenced file and never pops it,
    so a later sibling ``"$ref": "#/$defs/provision_summary"`` inside
    analysis_bundle.json would be resolved against document.json instead. Removing
    the ``$id`` and rooting the resolver at the schema's own file URI keeps every
    reference inside this directory.
    """
    by_id: dict[str, Any] = {}
    local: dict[str, Any] = {}
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        uri = path.resolve().as_uri()
        by_id[schema["$id"]] = schema
        by_id[uri] = schema
        # Bare filename too: the root schema handed to the validator has its $id
        # stripped, so its own base URI is empty and a relative ref resolves to
        # exactly "common.json".
        by_id[path.name] = schema
        stripped = {k: v for k, v in schema.items() if k != "$id"}
        local[uri] = stripped
        local[path.name] = stripped
    return {"by_id": by_id, "local": local}


def _local_registry(by_id: dict[str, Any]) -> Any:
    """A `referencing` registry over the same local files, and nothing else.

    Required alongside the RefResolver because jsonschema's
    ``unevaluatedProperties`` implementation resolves ``$ref`` through the modern
    registry directly, bypassing the legacy resolver. Without it,
    proposition.json's ``grounded_provenance`` would try to fetch common.json over
    the network.
    """
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = [
        (uri, Resource.from_contents(schema, default_specification=DRAFT202012))
        for uri, schema in by_id.items()
    ]
    return Registry().with_resources(resources)


def validate_instance(
    instance: Any, schema_name: str, store: dict[str, dict[str, Any]]
) -> list[str]:
    """Validate one in-memory object against one schema. Returns error lines."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from jsonschema import Draft202012Validator
        from jsonschema.validators import RefResolver

    schema_uri = (SCHEMA_DIR / schema_name).resolve().as_uri()
    schema = store["local"][schema_uri]

    with warnings.catch_warnings():
        # RefResolver is deprecated but still supported, and it is what roots $ref
        # resolution at this directory. It and the registry are both supplied so
        # that no code path can fall through to an HTTP fetch of a schema $id.
        warnings.simplefilter("ignore", DeprecationWarning)
        resolver = RefResolver(
            base_uri=schema_uri,
            referrer=schema,
            store=store["local"],
        )
        validator = Draft202012Validator(
            schema,
            resolver=resolver,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
            registry=_local_registry(store["by_id"]),
        )
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))

    lines = []
    for err in errors:
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        lines.append(f"    {where}: {err.message}")
    return lines


def validate_file(path: Path, schema_name: str, store: dict[str, dict[str, Any]]) -> list[str]:
    """Validate one emitted file against one schema. Returns a list of error lines."""
    return validate_instance(json.loads(path.read_text(encoding="utf-8")), schema_name, store)


def validate_feed_payload(feed: dict[str, Any], store: dict[str, dict[str, Any]]) -> list[str]:
    """news/latest.json has no schema of its own, but its payload does.

    Every item embeds a whole article and a whole framing profile, so those are
    lifted out and validated against news_article.json and framing_profile.json.
    Without this the feed would be the one file nothing checks.
    """
    article_set = {
        "schema_version": feed["schema_version"],
        "data_status": feed["data_status"],
        "generated_at": feed["generated_at"],
        "document_id": DOC_ID,
        "articles": [item["article"] for item in feed["items"]],
    }
    errors = [
        f"[articles] {line}" for line in validate_instance(article_set, "news_article.json", store)
    ]
    for item in feed["items"]:
        errors += [
            f"[framing {item['framing_profile']['id']}] {line}"
            for line in validate_instance(item["framing_profile"], "framing_profile.json", store)
        ]
    return errors


def check_internal_consistency(
    bundle: dict[str, Any], feed: dict[str, Any], index: dict[str, Any]
) -> list[str]:
    """Cross-file checks the JSON schemas cannot express.

    Referential integrity, the honesty invariants (data_status everywhere, no real
    outlet on a fabricated article) and the arithmetic that lets a reader open a
    score and reproduce it.
    """
    problems: list[str] = []

    claim_ids = {c["id"] for c in bundle["claims"]}
    evidence_ids = {e["id"] for e in bundle["evidence"]}
    article_ids = {a["id"] for a in bundle["articles"]}
    node_ids = {n["id"] for n in bundle["topic_graph"]["nodes"]}
    provision_ids = {p["id"] for p in bundle["provisions"]}
    proposition_ids = {p["id"] for p in bundle["propositions"]["propositions"]}
    cluster_ids = {c["id"] for c in bundle["clusters"]}
    known = (
        claim_ids
        | evidence_ids
        | article_ids
        | node_ids
        | provision_ids
        | proposition_ids
        | {DOC_ID}
    )

    # Evidence and provision references resolve.
    for claim in bundle["claims"]:
        for ref in claim["blind_evaluation"]["evidence_refs"]:
            if ref not in evidence_ids:
                problems.append(f"claim {claim['id']}: evidence_ref {ref} does not exist")
        for ref in claim["blind_evaluation"]["redacted_context"]["evidence_ids"]:
            if ref not in evidence_ids:
                problems.append(f"claim {claim['id']}: shown evidence {ref} does not exist")
        for ref in claim["topic_refs"]:
            if ref not in node_ids:
                problems.append(f"claim {claim['id']}: topic_ref {ref} does not exist")
        if claim["article_id"] not in article_ids:
            problems.append(f"claim {claim['id']}: article {claim['article_id']} does not exist")
        if claim["cluster_id"] is not None and claim["cluster_id"] not in cluster_ids:
            problems.append(f"claim {claim['id']}: cluster {claim['cluster_id']} does not exist")
        for ref in claim["contradicts"]:
            if ref not in claim_ids:
                problems.append(f"claim {claim['id']}: contradicts unknown claim {ref}")
        # A blind context that names its speaker is not blind.
        redacted = claim["blind_evaluation"]["redacted_context"]["claim_text"]
        for role in (ROLE_TREASURY, ROLE_BUSINESS, ROLE_MUNICIPAL, ROLE_UNION, ROLE_OPPOSITION):
            if role.lower() in redacted.lower():
                problems.append(f"claim {claim['id']}: redacted_context leaks the speaker role")
        for outlet in OUTLETS.values():
            if outlet["name"].lower() in redacted.lower():
                problems.append(f"claim {claim['id']}: redacted_context leaks the outlet")

    for edge in bundle["topic_graph"]["edges"]:
        for endpoint in (edge["source"], edge["target"]):
            if endpoint not in node_ids:
                problems.append(f"edge {edge['id']}: endpoint {endpoint} does not exist")

    for article in bundle["articles"]:
        for cid in article["claim_ids"]:
            if cid not in claim_ids:
                problems.append(f"article {article['id']}: claim {cid} does not exist")
        parent = article["derived_from_article_id"]
        if parent is not None and parent not in article_ids:
            problems.append(f"article {article['id']}: derived_from {parent} does not exist")

    for cluster in bundle["clusters"]:
        analysis = cluster["independence_analysis"]
        if analysis["total_articles"] != len(cluster["article_ids"]):
            problems.append(f"cluster {cluster['id']}: total_articles disagrees with article_ids")
        if analysis["distinct_original_sources"] > analysis["total_articles"]:
            problems.append(f"cluster {cluster['id']}: more originals than articles")

    for contradiction in bundle["contradictions"]:
        for position in contradiction["positions"]:
            if position["claim_id"] not in claim_ids:
                problems.append(f"{contradiction['id']}: position claim does not exist")
        applied = {
            item["evidence_id"]: set(item["bears_on_positions"])
            for item in contradiction["shared_evidence"]
        }
        position_ids = {p["claim_id"] for p in contradiction["positions"]}
        for eid, bears in applied.items():
            if eid not in evidence_ids:
                problems.append(f"{contradiction['id']}: shared evidence {eid} does not exist")
            if bears != position_ids:
                problems.append(
                    f"{contradiction['id']}: {eid} was not applied to every position — "
                    "asymmetric application is what this schema exists to prevent"
                )

    # Every axis score must be exactly the sum of its components.
    for key, axis in bundle["impact_map"]["axes"].items():
        total = sum(c["weight"] for c in axis["components"])
        if total != axis["score"]:
            problems.append(
                f"impact axis {key}: components sum to {total}, score says {axis['score']}"
            )
        for c in axis["components"]:
            for ref in c["evidence_refs"]:
                if ref not in known:
                    problems.append(f"impact axis {key}: component ref {ref} does not exist")

    # Same rule for readiness dimensions and for the neutrality composite.
    for name, dim in bundle["readiness"]["dimensions"].items():
        total = sum(c["weight"] for c in dim["components"])
        if total != dim["score"]:
            problems.append(
                f"readiness {name}: components sum to {total}, score says {dim['score']}"
            )
    weights = sum(d["weight"] for d in bundle["readiness"]["dimensions"].values())
    if abs(weights - 1.0) > 1e-9:
        problems.append(f"readiness: dimension weights sum to {weights}, expected 1.0")

    neutrality = bundle["neutrality_report"]
    total = sum(c["weight"] for c in neutrality["neutrality_health_components"])
    if total != neutrality["neutrality_health"]:
        problems.append(
            f"neutrality: components sum to {total}, neutrality_health says {neutrality['neutrality_health']}"
        )
    runs = sum(p["runs"] for p in neutrality["perturbations"].values())
    flips = sum(p["flips"] for p in neutrality["perturbations"].values())
    if abs(neutrality["metrics"]["verdict_flip_rate"] - flips / runs) > 1e-4:
        problems.append("neutrality: verdict_flip_rate disagrees with the per-family counts")
    if neutrality["sample"]["runs_total"] != runs:
        problems.append("neutrality: sample.runs_total disagrees with the per-family runs")

    # Readiness must explain any refusal.
    if not bundle["readiness"]["publishable"] and not bundle["readiness"]["why_not_publishable"]:
        problems.append("readiness: publishable is false with no stated reason")

    # Honesty invariants.
    if bundle["data_status"] != "synthetic":
        problems.append("bundle: data_status must be 'synthetic'")
    for name, obj in (("feed", feed), ("index", index)):
        if obj.get("data_status") != "synthetic":
            problems.append(f"{name}: data_status must be 'synthetic'")
    for article in bundle["articles"]:
        if not article["publisher"]["id"].startswith("src:demo-"):
            problems.append(f"article {article['id']}: publisher is not a demo outlet")
        if article["url"] is not None:
            problems.append(f"article {article['id']}: synthetic article must not carry a url")
    warning_codes = [w["message"] for w in bundle["document"]["extraction_warnings"]]
    if not any("NO fueron extraídos" in m for m in warning_codes):
        problems.append("document: missing the extraction warning disclaiming the source URL")

    # The feed must agree with the bundle it summarises.
    for item in feed["items"]:
        aid = item["article"]["id"]
        if aid not in article_ids:
            problems.append(f"feed: article {aid} is not in the bundle")
        if sum(item["verdict_counts"].values()) != item["claim_count"]:
            problems.append(f"feed {aid}: verdict counts do not sum to claim_count")
        if item["claim_count"] != len(item["article"]["claim_ids"]):
            problems.append(f"feed {aid}: claim_count disagrees with the article")
        if item["cluster_id"] not in cluster_ids:
            problems.append(f"feed {aid}: cluster {item['cluster_id']} is not in the bundle")
        if item["framing_profile"]["article_id"] != aid:
            problems.append(f"feed {aid}: framing profile belongs to a different article")
        for cid in item["claim_ids"]:
            if cid not in claim_ids:
                problems.append(f"feed {aid}: claim {cid} is not in the bundle")

    # The manifest must agree with the bundle it points at.
    featured = next((a for a in index["analyses"] if a["slug"] == index["featured"]), None)
    if featured is None:
        problems.append("index: featured slug is not present in analyses")
    else:
        expected = {
            "provisions": len(bundle["provisions"]),
            "claims": len(bundle["claims"]),
            "evidence": len(bundle["evidence"]),
            "articles": len(bundle["articles"]),
            "clusters": len(bundle["clusters"]),
            "contradictions": len(bundle["contradictions"]),
        }
        for key, value in expected.items():
            if featured["counts"][key] != value:
                problems.append(
                    f"index: counts.{key} is {featured['counts'][key]}, bundle has {value}"
                )

    return problems


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

OUTPUTS: list[tuple[str, str | None]] = [
    ("index.json", None),
    (f"reforms/{DOC_SLUG}.json", "analysis_bundle.json"),
    ("news/latest.json", None),
    (f"claims/{DOC_SLUG}.json", "claim.json"),
    (f"evidence/{DOC_SLUG}.json", "evidence.json"),
]


def write_outputs() -> dict[str, Any]:
    bundle = build_bundle()
    feed = build_news_feed(bundle)
    index = build_index(bundle, feed)
    payloads = {
        "index.json": index,
        f"reforms/{DOC_SLUG}.json": bundle,
        "news/latest.json": feed,
        f"claims/{DOC_SLUG}.json": build_claims_file(),
        f"evidence/{DOC_SLUG}.json": build_evidence_file(),
    }
    for relative, payload in payloads.items():
        path = OUT_DIR / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the files already on disk without rewriting them.",
    )
    args = parser.parse_args()

    if args.check:
        payloads = {
            rel: json.loads((OUT_DIR / rel).read_text(encoding="utf-8")) for rel, _ in OUTPUTS
        }
        print(f"Checking existing files in {OUT_DIR}")
    else:
        payloads = write_outputs()
        print(f"Wrote {len(payloads)} files to {OUT_DIR}")

    store = _schema_store()
    failed = False

    print("\nSchema validation (jsonschema, RefResolver rooted at schemas/):")
    for relative, schema_name in OUTPUTS:
        path = OUT_DIR / relative
        size = path.stat().st_size
        if schema_name is None:
            if relative == "news/latest.json":
                errors = validate_feed_payload(payloads[relative], store)
                if errors:
                    failed = True
                    print(f"  ✗ {relative:<28} {size:>8,} B   FAILED (embedded payload)")
                    for line in errors[:25]:
                        print(f"    {line}")
                else:
                    print(
                        f"  ✓ {relative:<28} {size:>8,} B   no schema of its own; embedded "
                        "articles valid against news_article.json and profiles against "
                        "framing_profile.json"
                    )
            else:
                print(
                    f"  - {relative:<28} {size:>8,} B   no schema (site manifest) — "
                    "checked structurally below"
                )
            continue
        errors = validate_file(path, schema_name, store)
        if errors:
            failed = True
            print(f"  ✗ {relative:<28} {size:>8,} B   FAILED against {schema_name}")
            for line in errors[:25]:
                print(line)
        else:
            print(f"  ✓ {relative:<28} {size:>8,} B   valid against {schema_name}")

    print("\nInternal consistency:")
    problems = check_internal_consistency(
        payloads[f"reforms/{DOC_SLUG}.json"],
        payloads["news/latest.json"],
        payloads["index.json"],
    )
    if problems:
        failed = True
        for problem in problems:
            print(f"  ✗ {problem}")
    else:
        print("  ✓ referential integrity, score arithmetic and honesty invariants all hold")

    if failed:
        print("\nVALIDATION FAILED")
        return 1
    print("\nAll outputs validate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
