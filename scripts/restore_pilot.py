"""Verify and restore a local SQLite pilot backup into a new directory."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from app.backup import restore_local_backup, verify_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="恢复柑橘产业链试点本地备份")
    parser.add_argument("archive", type=Path, help="备份 zip 文件")
    parser.add_argument("destination", type=Path, help="恢复目标目录")
    parser.add_argument("--replace", action="store_true", help="允许覆盖非空目标目录")
    args = parser.parse_args()
    try:
        manifest = verify_backup(args.archive)
        destination = restore_local_backup(args.archive, args.destination, replace=args.replace)
    except (OSError, ValueError) as error:
        print(f"恢复失败：{error}", file=sys.stderr)
        return 2
    print(f"备份校验通过：{manifest.get('created_at', '未知时间')}")
    print(f"已恢复到：{destination}")
    print("如需使用恢复后的 SQLite 数据库，请将 CITRUS_RUNTIME_DIR 指向该目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
