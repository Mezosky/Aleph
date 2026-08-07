"""Guard the semantic colour-token contract in both themes."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "frontend" / "src" / "styles" / "index.css"
REQUIRED = {
    "surface-page",
    "surface-card",
    "ink-primary",
    "ink-secondary",
    "line-hairline",
    "status-good",
    "status-warning",
    "status-serious",
    "status-critical",
    *(f"div-neg-{index}" for index in range(1, 5)),
    "div-mid",
    *(f"div-pos-{index}" for index in range(1, 5)),
    *(f"seq-{index}" for index in range(1, 5)),
}


def rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def luminance(value: str) -> float:
    channels = []
    for channel in rgb(value):
        component = channel / 255
        channels.append(
            component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(left: str, right: str) -> float:
    light, dark = sorted((luminance(left), luminance(right)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def values(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", block))


def main() -> int:
    css = CSS.read_text(encoding="utf-8")
    root_match = re.search(r":root\s*\{(.*?)\n\s*\}", css, re.DOTALL)
    dark_match = re.search(r"\.dark\s*\{(.*?)\n\s*\}", css, re.DOTALL)
    if not root_match or not dark_match:
        print("could not locate :root and .dark token blocks", file=sys.stderr)
        return 1
    failures: list[str] = []
    for label, tokens in (
        ("light", values(root_match.group(1))),
        ("dark", values(dark_match.group(1))),
    ):
        missing = sorted(REQUIRED - tokens.keys())
        if missing:
            failures.append(f"{label}: missing {', '.join(missing)}")
        if contrast(tokens["ink-primary"], tokens["surface-page"]) < 7:
            failures.append(f"{label}: primary ink/page contrast is below 7:1")
        ramp = [
            tokens[name]
            for name in sorted(name for name in REQUIRED if name.startswith(("div-", "seq-")))
        ]
        if len(ramp) != len(set(ramp)):
            failures.append(f"{label}: data-ramp colours must be unique")
    if "red-vs-blue" not in css and "political side" not in css:
        failures.append("token rationale must state the political-colour prohibition")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("design tokens valid in light and dark themes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
