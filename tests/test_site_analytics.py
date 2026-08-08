from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts.export_site_analytics import _query

ROOT = Path(__file__).resolve().parents[1]


def test_public_analytics_snapshot_is_aggregate_and_schema_valid() -> None:
    schema = json.loads((ROOT / "schemas" / "site_analytics.json").read_text(encoding="utf-8"))
    snapshot = json.loads(
        (ROOT / "frontend" / "public" / "data" / "site-analytics.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(snapshot)

    serialized = json.dumps(snapshot).lower()
    assert "ip_address" not in serialized
    assert "clientip" not in serialized
    assert "city" not in serialized
    assert snapshot["status"] == "awaiting_configuration"
    assert snapshot["visits"] is None


def test_cloudflare_query_requests_only_aggregate_dimensions() -> None:
    query = _query("account123", "site456", "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z")
    assert "countryName" in query
    assert "refererHost" in query
    assert "clientIP" not in query
    assert "city" not in query
    assert "refererPath" not in query
    assert "requestPath" not in query
