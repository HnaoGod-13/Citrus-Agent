"""Provision the first platform administrator and initialize pilot tables.

Run this once from a trusted deployment shell:
    python scripts/init_platform.py admin@example.com
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from app.platform_store import PlatformStore, normalize_email


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    args = parser.parse_args()
    try:
        email = normalize_email(args.email)
        store = PlatformStore()
        store.initialize()
        user_id = store.bootstrap_admin(email)
    except ValueError as error:
        print(f"初始化失败：{error}", file=sys.stderr)
        return 2
    print(f"平台管理员已初始化：{email} ({user_id})")
    print("下一步：配置 OIDC，并把 CITRUS_AUTH_REQUIRED=true 后启动应用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
