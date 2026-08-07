"""Run the comparative-evidence layer on the local GPU and freeze the result."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aleph.dossier.theory import synthesize_theory_analysis  # noqa: E402
from aleph.llm.qwen import QwenProvider  # noqa: E402
from api.database import AnalysisRunRow, Database, utcnow  # noqa: E402

OUT = ROOT / "frontend/public/data/megareforma/theory.json"
MODEL = "nvidia/Qwen3.5-122B-A10B-NVFP4"
REVISION = "98915d837c4e7c87ac8296d02e89de19b3207e6d"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--database-url", default="sqlite:///./data/aleph.db")
    args = parser.parse_args()

    provider = QwenProvider(
        base_url=args.base_url,
        model=MODEL,
        temperature=0.0,
        timeout=900,
        enable_thinking=False,
    )
    result = synthesize_theory_analysis(provider)
    provider.close()
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "execution": "local_gpu_offline",
        "runtime_calls": 0,
        "methodology": (
            "Síntesis Qwen local sobre paquetes de evidencia con fuentes permitidas por tema; "
            "el código rechaza temas duplicados y referencias fuera del paquete. Las notas "
            "comparadas no sustituyen una evaluación causal específica para Chile."
        ),
        **result,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(canonical).hexdigest()

    database = Database(args.database_url)
    with database.sessions.begin() as session:
        parent = session.scalar(
            select(AnalysisRunRow)
            .where(AnalysisRunRow.model_provider == "qwen")
            .order_by(AnalysisRunRow.completed_at.desc())
        )
        if parent is None:
            raise SystemExit("no canonical Qwen document run found")
        now = utcnow()
        session.add(
            AnalysisRunRow(
                id=uuid.uuid4().hex,
                document_id=parent.document_id,
                supersedes_run_id=parent.id,
                source_snapshot_id=parent.source_snapshot_id,
                state="complete",
                allow_network=False,
                model_provider="qwen",
                model_name=MODEL,
                model_revision=REVISION,
                pipeline_version="megareforma-theory-v1",
                prompt_version="comparative-evidence-v1",
                schema_version="1.0.0",
                config_fingerprint=hashlib.sha256(b"comparative-evidence-v1").hexdigest(),
                result_json={"theory_analysis": payload},
                result_sha256=digest,
                created_at=now,
                started_at=now,
                completed_at=now,
                updated_at=now,
            )
        )
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    database.dispose()
    print(json.dumps({"topics": len(payload["topics"]), "sha256": digest, "output": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
