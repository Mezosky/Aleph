from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts.export_site_analytics import _query, _visits

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
    assert "countries" not in snapshot
    assert "referrers" not in snapshot
    assert "page_views" not in snapshot


def test_cloudflare_query_requests_only_visit_total() -> None:
    query = _query("account123", "site456", "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z")
    assert "countryName" not in query
    assert "refererHost" not in query
    assert "clientIP" not in query
    assert "city" not in query
    assert "refererPath" not in query
    assert "requestPath" not in query


def test_new_site_without_aggregate_rows_starts_at_zero() -> None:
    assert _visits({}) == 0
    assert _visits({"sum": {"visits": None}}) == 0
