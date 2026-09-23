"""Create a consistent pilot backup from the configured database and file store."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from app.backup import create_backup, verify_backup


def main() -> int:
    runtime = Path(os.getenv("CITRUS_RUNTIME_DIR") or ROOT / ".runtime").expanduser()
    target_root = Path(os.getenv("CITRUS_BACKUP_DIR") or runtime.parent / "backups").expanduser()
    target_root.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    archive = target_root / f"citrus-pilot-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.zip"
    try:
        result = create_backup(archive, runtime=runtime)
        manifest = verify_backup(result)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"备份失败：{error}。请先完成平台初始化，并确认数据库和附件目录配置正确。", file=sys.stderr)
        return 2
    print(f"备份已生成：{result}")
    print(f"数据库：{manifest.get('database_url_backend')}；文件：{len(manifest.get('files') or [])} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
