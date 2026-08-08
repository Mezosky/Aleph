"""Freeze licensed, non-analytical site imagery for the static publication."""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "AlephResearch/0.2 (https://github.com/mezosky/Aleph)"
LA_MONEDA_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/79/"
    "128_-_Santiago_-_Panorama_de_La_Moneda_-_Janvier_2010.jpg/"
    "1920px-128_-_Santiago_-_Panorama_de_La_Moneda_-_Janvier_2010.jpg"
)
OUT = ROOT / "frontend/public/la-moneda.jpg"
EXPECTED_SHA256 = "f610a6d2aa1abda7bc4afc165ae5ca54940dd9594d09183aa2a3574ee74678b6"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="explicitly allow downloading the licensed Wikimedia asset",
    )
    args = parser.parse_args()
    if not args.allow_network:
        parser.error("network access is disabled; pass --allow-network to download")
    request = urllib.request.Request(LA_MONEDA_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        content = response.read()
        content_type = response.headers.get_content_type()
    if content_type != "image/jpeg" or len(content) < 100_000:
        raise RuntimeError(f"unexpected La Moneda response: {content_type}, {len(content)} bytes")
    digest = hashlib.sha256(content).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(
            f"La Moneda image changed upstream: expected {EXPECTED_SHA256}, got {digest}"
        )
    OUT.write_bytes(content)
    print(f"{OUT.relative_to(ROOT)} {len(content)} bytes sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
