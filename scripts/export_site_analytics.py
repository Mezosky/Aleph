"""Export a public, aggregate Cloudflare Web Analytics snapshot.

The API token is read only in CI. The emitted JSON contains only the aggregate
visit total; it deliberately excludes dimensions and event-level data.
When credentials are absent, the committed awaiting-configuration snapshot is
left untouched so local builds remain deterministic.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "data" / "site-analytics.json"
ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"
DEFAULT_START = "2026-08-08T00:00:00Z"


def _safe_identifier(value: str, label: str) -> str:
    if not value or not all(character.isalnum() or character in "-_" for character in value):
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _query(account_id: str, site_tag: str, start: str, end: str) -> str:
    account_id = _safe_identifier(account_id, "account id")
    site_tag = _safe_identifier(site_tag, "site tag")
    common_filter = (
        f'{{AND:[{{datetime_geq:"{start}",datetime_leq:"{end}"}},'
        f'{{OR:[{{siteTag:"{site_tag}"}}]}}]}}'
    )
    return f"""
    query PublicAudienceSnapshot {{
      viewer {{
        accounts(filter: {{accountTag: "{account_id}"}}) {{
          total: rumPageloadEventsAdaptiveGroups(filter: {common_filter}, limit: 1) {{
            count
            sum {{ visits }}
          }}
        }}
      }}
    }}
    """


def _request(token: str, query: str) -> dict:
    body = json.dumps({"query": query}).encode()
    request = Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS endpoint
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    accounts = payload.get("data", {}).get("viewer", {}).get("accounts", [])
    if not accounts:
        raise RuntimeError(
            "Cloudflare returned no accessible account; verify "
            "CLOUDFLARE_ANALYTICS_ACCOUNT_ID and Account Analytics Read permission"
        )
    return accounts[0]


def _visits(row: dict) -> int:
    return max(0, int(row.get("sum", {}).get("visits") or 0))


def main() -> int:
    account_id = os.environ.get("CLOUDFLARE_ANALYTICS_ACCOUNT_ID", "").strip()
    site_tag = os.environ.get("CLOUDFLARE_ANALYTICS_SITE_TAG", "").strip()
    token = os.environ.get("CLOUDFLARE_ANALYTICS_API_TOKEN", "").strip()
    if not all((account_id, site_tag, token)):
        missing = [
            name
            for name, value in (
                ("CLOUDFLARE_ANALYTICS_ACCOUNT_ID", account_id),
                ("CLOUDFLARE_ANALYTICS_SITE_TAG", site_tag),
                ("CLOUDFLARE_ANALYTICS_API_TOKEN", token),
            )
            if not value
        ]
        print(
            "Cloudflare analytics credentials absent; keeping public placeholder: "
            + ", ".join(missing)
        )
        return 0

    start = os.environ.get("CLOUDFLARE_ANALYTICS_START", DEFAULT_START).strip()
    end = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        result = _request(token, _query(account_id, site_tag, start, end))
        # A newly installed beacon legitimately has no aggregate row yet. Treat
        # that as zero visits, not as a credential failure.
        total_rows = result.get("total") or []
        total = total_rows[0] if total_rows else {}
        snapshot = {
            "schema_version": "1.0.0",
            "status": "active",
            "source": "cloudflare_web_analytics",
            "period_start": start,
            "generated_at": end,
            "visits": _visits(total),
            "privacy_note_es": (
                "Sólo se publica el total agregado de visitas; nunca ubicaciones, "
                "referentes, direcciones IP ni recorridos individuales."
            ),
            "privacy_note_en": (
                "Only the aggregate visit total is published; never locations, referrers, "
                "IP addresses, or individual browsing histories."
            ),
        }
        OUTPUT.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Exported {snapshot['visits']} aggregate visits")
        return 0
    except (HTTPError, URLError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Cloudflare analytics export failed; keeping prior snapshot: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
