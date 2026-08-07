"""Freeze licensed Wikimedia portraits for municipal actor profiles.

Only files surfaced by the corresponding Spanish Wikipedia biography are
listed. Actors without a page image remain image-less rather than receiving a
search result that might depict a namesake.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend/public/data/megareforma/municipal-actors.json"
IMAGE_DIR = ROOT / "frontend/public/data/megareforma/actors"
USER_AGENT = "AlephResearch/0.2 (https://github.com/mezosky/Aleph)"

PORTRAITS = {
    "Claudio Castro": {
        "file": "claudio-castro.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f1/Claudio_Castro_Salas_%28cropped%29.jpg/500px-Claudio_Castro_Salas_%28cropped%29.jpg",
        "credit": "Vocería de Gobierno",
        "license": "CC BY-SA 2.0",
        "source": "https://commons.wikimedia.org/wiki/File:Claudio_Castro_Salas_(cropped).jpg",
    },
    "Felipe Alessandri": {
        "file": "felipe-alessandri.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/66/Felipe_Alessandri_%2832727066712%29_%28cropped%29.jpg/500px-Felipe_Alessandri_%2832727066712%29_%28cropped%29.jpg",
        "credit": "I. Municipalidad de Santiago",
        "license": "CC BY-SA 2.0",
        "source": "https://commons.wikimedia.org/wiki/File:Felipe_Alessandri_(32727066712)_(cropped).jpg",
    },
    "Jaime Bellolio": {
        "file": "jaime-bellolio.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b6/Ministro_Vocero_de_Gobierno_Jaime_Bellolio.jpg/500px-Ministro_Vocero_de_Gobierno_Jaime_Bellolio.jpg",
        "credit": "KatKirLu",
        "license": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Ministro_Vocero_de_Gobierno_Jaime_Bellolio.jpg",
    },
    "Javiera Reyes": {
        "file": "javiera-reyes.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bc/RETRATOS_ALCALDESA_JAVIERA_REYES_11149.jpg/500px-RETRATOS_ALCALDESA_JAVIERA_REYES_11149.jpg",
        "credit": "Salvador Saez",
        "license": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:RETRATOS_ALCALDESA_JAVIERA_REYES_11149.jpg",
    },
    "José Manuel Palacios": {
        "file": "jose-manuel-palacios.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/95/JmPalacios2025.jpg/500px-JmPalacios2025.jpg",
        "credit": "Cpgonzalezrod",
        "license": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:JmPalacios2025.jpg",
    },
    "Mauro Tamayo": {
        "file": "mauro-tamayo.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/a8/Mauro_Tamayo_%2830663438223%29_%28cropped%29.jpg",
        "credit": "Ministerio Secretaría General de Gobierno",
        "license": "CC BY-SA 2.0",
        "source": "https://commons.wikimedia.org/wiki/File:Mauro_Tamayo_(30663438223)_(cropped).jpg",
    },
    "Tomás Vodanovic": {
        "file": "tomas-vodanovic.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Tom%C3%A1s_Vodanivic_-_2024.jpg/500px-Tom%C3%A1s_Vodanivic_-_2024.jpg",
        "credit": "Municipalidad de Maipú",
        "license": "CC BY 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Tom%C3%A1s_Vodanivic_-_2024.jpg",
    },
}


def main() -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    actors = {actor["name"]: actor for actor in payload["actors"]}
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for name, portrait in PORTRAITS.items():
        request = urllib.request.Request(portrait["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
            content_type = response.headers.get_content_type()
        if content_type not in {"image/jpeg", "image/png"} or len(content) < 10_000:
            raise RuntimeError(f"unexpected portrait response for {name}: {content_type}")
        destination = IMAGE_DIR / portrait["file"]
        destination.write_bytes(content)
        actor = actors[name]
        actor.update(
            {
                "image": f"megareforma/actors/{portrait['file']}",
                "image_alt": f"Retrato de {name}",
                "image_credit": portrait["credit"],
                "image_license": portrait["license"],
                "image_source_url": portrait["source"],
                "image_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        print(f"{name}: {len(content)} bytes")
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
