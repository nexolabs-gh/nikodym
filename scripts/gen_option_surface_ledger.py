"""Regenera el ledger interno y revisable de opciones D-RDY-ABA-6."""

from __future__ import annotations

import json
from pathlib import Path

from nikodym.ui.option_surface import classified_option_surface

_TARGET = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "option_surface_ledger.json"
)


def main() -> None:
    """Escribe la fotografía canónica del censo medido."""
    payload = classified_option_surface()
    _TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{_TARGET}: {len(payload['entries'])} pares + {len(payload['aliases'])} aliases")


if __name__ == "__main__":
    main()
