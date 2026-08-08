from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts.export_site_analytics import MIN_PUBLIC_GROUP_SIZE, _country, _query, _visits

ROOT = Path(__file__).resolve().parents[1]


def test_public_analytics_snapshot_is_aggregate_and_schema_valid() -> None:
    schema = json.loads((ROOT / "schemas" / "site_analytics.json").read_text(encoding="utf-8"))
    snapshot = json.loads(
        (ROOT / "frontend" / "public" / "data" / "site-analytics.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(snapshot)

    serialized = json.dumps(snapshot).lower()
    assert '"ip_address":' not in serialized
    assert '"clientip":' not in serialized
    assert '"city":' not in serialized
    assert snapshot["status"] == "awaiting_configuration"
    assert snapshot["visits"] is None
    assert snapshot["countries"] == []
    assert snapshot["referrers"] == []
    assert "page_views" not in snapshot


def test_cloudflare_query_requests_only_aggregate_public_dimensions() -> None:
    query = _query("account123", "site456", "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z")
    assert "countryName" in query
    assert "refererHost" in query
    assert "clientIP" not in query
    assert "city" not in query
    assert "refererPath" not in query
    assert "requestPath" not in query


def test_new_site_without_aggregate_rows_starts_at_zero() -> None:
    assert _visits({}) == 0
    assert _visits({"sum": {"visits": None}}) == 0


def test_public_origin_groups_use_a_five_visit_floor() -> None:
    assert MIN_PUBLIC_GROUP_SIZE == 5
    chile = _country({"dimensions": {"metric": "CL"}, "sum": {"visits": 7}})
    assert chile == {"code": "CL", "label_es": "Chile", "label_en": "Chile", "visits": 7}
