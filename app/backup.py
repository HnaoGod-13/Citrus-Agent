"""Portable database snapshots and private local-file backups (archive format 2)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from sqlalchemy.engine import make_url
from app.platform_db import database_url, runtime_dir


def _digest(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return _digest(stream)


def sqlite_snapshot(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError("尚未找到数据库，请先初始化试点。")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst, pages=256, sleep=0.05)
    finally:
        dst.close()
        src.close()


def _copy_tree(source: Path, destination: Path, *, excluded=()) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        if any(path == item or item in path.parents for item in excluded):
            continue
        if not path.is_file() or path.name.endswith(("-wal", "-shm", "-journal")):
            continue
        if not path.resolve().is_relative_to(source):
            raise ValueError("运行目录包含指向外部的链接，无法备份。")
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".db":
            sqlite_snapshot(path, target)
        else:
            shutil.copy2(path, target)


def create_backup(output: Path, *, db_url: str | None = None, runtime: Path | None = None, blobs: Path | None = None) -> Path:
    output = Path(output).expanduser().resolve()
    runtime = Path(runtime or runtime_dir()).expanduser().resolve()
    blobs = Path(blobs or os.getenv("CITRUS_BLOB_DIR") or runtime / "attachments").expanduser().resolve()
    backend = os.getenv("CITRUS_BLOB_BACKEND", "local").strip().lower()
    if backend not in {"local", "s3"}:
        raise ValueError("附件存储类型无效。")
    if output.is_relative_to(runtime) or (backend == "local" and output.is_relative_to(blobs)):
        raise ValueError("备份文件必须保存在运行目录和附件目录之外。")
    if backend == "local" and runtime.is_relative_to(blobs):
        raise ValueError("附件目录不能包含整个运行目录，请为附件设置独立子目录。")
    parsed = make_url(db_url or database_url())
    database_backend = parsed.get_backend_name()
    if database_backend not in {"sqlite", "postgresql"}:
        raise ValueError("备份仅支持 SQLite 和 PostgreSQL。")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("备份文件已存在，请指定新文件名。")
    # Stage on the same filesystem so publication can use an atomic rename.
    with tempfile.TemporaryDirectory(prefix=".citrus-backup-", dir=output.parent) as temp:
        staging = Path(temp) / "content"
        database = staging / "database"
        database.mkdir(parents=True)
        source = None
        if database_backend == "sqlite":
            if not parsed.database or parsed.database == ":memory:":
                raise ValueError("内存数据库不能作为持久备份来源。")
            source = Path(parsed.database).expanduser().resolve()
            snapshot = database / "pilot.db"
            sqlite_snapshot(source, snapshot)
        else:
            snapshot = database / "postgres.dump"
            command_env = os.environ.copy()
            if parsed.password is not None:
                command_env["PGPASSWORD"] = parsed.password
            connection = parsed.set(drivername="postgresql", password=None).render_as_string(hide_password=False)
            try:
                subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-password", "--file", str(snapshot),
                                "--dbname", connection], env=command_env, check=True, capture_output=True, text=True)
            except FileNotFoundError:
                raise RuntimeError("PostgreSQL 备份需要安装匹配数据库版本的 pg_dump 客户端。") from None
            except subprocess.CalledProcessError:
                raise RuntimeError("PostgreSQL 备份失败，请检查连接、权限和客户端版本；未生成可用备份。") from None
        excluded = [source] if source and source.is_relative_to(runtime) else []
        if backend == "local" and blobs.is_relative_to(runtime):
            excluded.append(blobs)
        _copy_tree(runtime, staging / "runtime", excluded=excluded)
        if backend == "local":
            _copy_tree(blobs, staging / "attachments")
        files = []
        for area in ("runtime", "attachments"):
            for path in (staging / area).rglob("*"):
                if path.is_file():
                    files.append({"area": area, "path": path.relative_to(staging / area).as_posix(),
                                  "size": path.stat().st_size, "sha256": _sha256(path)})
        manifest = {"format": 2, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "database_url_backend": database_backend, "database_file": snapshot.relative_to(staging).as_posix(),
                    "database_size": snapshot.stat().st_size, "database_sha256": _sha256(snapshot),
                    "blob_backend": backend, "attachments_included": backend == "local", "files": files}
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        staged_archive = Path(temp) / "backup.zip"
        with zipfile.ZipFile(staged_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in staging.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
        verify_backup(staged_archive)
        staged_archive.replace(output)
    return output


def _safe_member(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(name and parts and not name.startswith("/") and chr(92) not in name
                and ":" not in name and ".." not in parts and "." not in name.split("/")
                and "//" not in name and all(not p.endswith((".", " ")) for p in parts))


def _verify(archive: zipfile.ZipFile) -> dict:
    names = archive.namelist()
    if len(names) != len(set(names)) or any(not _safe_member(n) for n in names):
        raise ValueError("备份包含重复或无效路径。")
    if "manifest.json" not in names:
        raise ValueError("备份缺少 manifest.json。")
    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != 2:
        raise ValueError("备份格式版本不受支持。")
    database_member = {"sqlite": "database/pilot.db", "postgresql": "database/postgres.dump"}.get(manifest.get("database_url_backend"))
    if not database_member or manifest.get("database_file") != database_member:
        raise ValueError("备份数据库类型或路径无效。")
    expected = {"manifest.json", database_member}
    entries = [(database_member, manifest.get("database_size"), manifest.get("database_sha256"))]
    if not isinstance(manifest.get("files"), list):
        raise ValueError("备份缺少文件清单。")
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("备份文件清单无效。")
        relative = str(item.get("path") or "")
        area = item.get("area")
        if not _safe_member(relative) or area not in {"runtime", "attachments"}:
            raise ValueError("备份清单包含无效路径。")
        member = f"{area}/{relative}"
        if member in expected:
            raise ValueError("备份清单包含重复路径。")
        expected.add(member)
        entries.append((member, item.get("size"), item.get("sha256")))
    if set(names) != expected:
        raise ValueError("备份文件与清单不一致。")
    for member, size, digest in entries:
        if not isinstance(size, int) or size < 0 or archive.getinfo(member).file_size != size:
            raise ValueError("备份文件大小校验失败。")
        with archive.open(member) as stream:
            if _digest(stream) != digest:
                raise ValueError("备份文件内容校验失败。")
    return manifest


def verify_backup(archive_path: Path) -> dict:
    try:
        with zipfile.ZipFile(Path(archive_path).expanduser().resolve()) as archive:
            return _verify(archive)
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError) as error:
        raise ValueError("备份格式损坏或清单不完整。") from error


def restore_local_backup(archive_path: Path, destination: Path, *, replace: bool = False) -> Path:
    destination = Path(destination).expanduser().resolve()
    if destination.exists() and (not destination.is_dir() or (any(destination.iterdir()) and not replace)):
        raise ValueError("恢复目录非空；请指定新目录，或明确使用 --replace 覆盖同名文件。")
    # Verify the exact open archive, including every member, before touching destination.
    with zipfile.ZipFile(Path(archive_path).expanduser().resolve()) as archive:
        manifest = _verify(archive)
        if manifest["database_url_backend"] != "sqlite" or manifest.get("blob_backend") != "local":
            raise ValueError("此命令仅自动恢复 SQLite 和本地附件；PostgreSQL / S3 请按部署文档恢复。")
        targets = [(name, (destination / name).resolve()) for name in archive.namelist() if name != "manifest.json"]
        if any(not target.is_relative_to(destination) for _, target in targets):
            raise ValueError("恢复目录包含指向外部的路径，已停止恢复。")
        # Extract into a temporary directory first: corrupt archives never overwrite live files.
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".citrus-restore-", dir=destination.parent) as temp:
            for name, _ in targets:
                staged = Path(temp) / name
                staged.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, staged.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            destination.mkdir(parents=True, exist_ok=True)
            for name, target in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                (Path(temp) / name).replace(target)
    return destination
