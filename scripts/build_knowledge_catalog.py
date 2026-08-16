from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge_catalog import build_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the lightweight Knowledge browser catalog.")
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data" / "literature" / "literature.db",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "literature" / "knowledge_catalog.db",
    )
    args = parser.parse_args()
    result = build_catalog(args.source, args.output)
    print(
        f"Built {result['path']} ({result['size']} bytes, "
        f"{result['visible_documents']} visible documents, "
        f"{result['visible_chunks']} visible chunks)"
    )


if __name__ == "__main__":
    main()
