"""Export the newest completed local-Qwen dossier brief into frozen site data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import AnalysisRunRow, Database  # noqa: E402

DOSSIER = ROOT / "frontend/public/data/megareforma/dossier.json"
SOURCES = ROOT / "frontend/public/data/megareforma/sources.json"
DEEP = ROOT / "frontend/public/data/megareforma/deep-analysis.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="sqlite:///./data/aleph.db")
    args = parser.parse_args()

    database = Database(args.database_url)
    with database.sessions() as session:
        rows = session.scalars(
            select(AnalysisRunRow)
            .where(
                AnalysisRunRow.state == "complete",
                AnalysisRunRow.model_provider == "qwen",
                AnalysisRunRow.result_json.is_not(None),
            )
            .order_by(AnalysisRunRow.completed_at.desc())
        ).all()
        run = next(
            (row for row in rows if isinstance(row.result_json.get("dossier_brief"), dict)),
            None,
        )
        completed_count = len(rows)
    if run is None:
        database.dispose()
        raise SystemExit("no completed Qwen run with dossier_brief exists")

    payload = json.loads(DOSSIER.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    brief = run.result_json["dossier_brief"]
    payload["generated_at"] = run.completed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    payload["summary"] = brief["document_summary"]
    payload["objectives"] = brief["objectives"]
    payload["counts"]["model_runs_completed"] = completed_count
    if DEEP.exists():
        deep = json.loads(DEEP.read_text(encoding="utf-8"))
        payload["counts"]["propositions"] = deep["document"]["propositions"]
    payload["counts"]["sources_curated"] = sources["capture_count"] + sources["gap_count"]
    payload["counts"]["sources_captured"] = sources["capture_count"]
    payload["counts"]["capture_gaps"] = sources["gap_count"]

    coverage_groups = {
        "critical": {
            "opposition_claims",
            "critical_analysis",
            "fiscal_analysis",
            "municipal_critical",
        },
        "descriptive": {
            "legislative_update",
            "legal_analysis",
            "negotiation",
            "municipal_negotiation",
            "municipal_cross_party",
        },
        "favourable": {"government"},
    }
    coverage = {key: [] for key in coverage_groups}
    for item in sources["items"]:
        if item["kind"] != "news":
            continue
        for key, perspectives in coverage_groups.items():
            if item["perspective"] in perspectives:
                coverage[key].append(item["id"])
                break
    total = sum(len(items) for items in coverage.values())
    coverage_meter = next(
        meter for meter in payload["meters"] if meter["id"] == "coverage-position"
    )
    coverage_meter["question"] = (
        f"¿Las {total} piezas de prensa capturadas priorizan críticas/oposición o argumentos "
        "favorables del Gobierno?"
    )
    coverage_meter["value"] = round(
        (50 * len(coverage["descriptive"]) + 100 * len(coverage["favourable"])) / total
    )
    for component, key in zip(
        coverage_meter["evidence"], ("critical", "descriptive", "favourable"), strict=True
    ):
        component["value"] = len(coverage[key])
        component["source_ids"] = coverage[key]
    coverage_meter["methodology"] = (
        "Se clasificó cada pieza por el argumento que su título y foco principal presentan: "
        f"{len(coverage['critical'])} críticas/oposición o alertas fiscales, "
        f"{len(coverage['descriptive'])} descriptivas, jurídicas o de negociación y "
        f"{len(coverage['favourable'])} favorables/gubernamentales. Posición = promedio "
        "ponderado 0/50/100. Las fuentes oficiales no entran en este medidor."
    )
    DOSSIER.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    database.dispose()
    print(
        json.dumps(
            {
                "run_id": run.id,
                "result_sha256": run.result_sha256,
                "objectives": len(brief["objectives"]),
                "output": str(DOSSIER.relative_to(ROOT)),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
