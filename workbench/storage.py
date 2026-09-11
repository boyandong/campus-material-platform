from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_package_id() -> str:
    return f"PRD-{datetime.now(timezone.utc).astimezone():%Y%m%d}-{uuid4().hex[:8]}"


def initialize_package(data_root: Path, package_id: str) -> Path:
    package = data_root / package_id
    if package.exists():
        raise FileExistsError(package)
    for relative in (
        "original/materials",
        "processed",
        "previews",
        "reports",
    ):
        (package / relative).mkdir(parents=True, exist_ok=True)
    return package


def _set_read_only(path: Path) -> None:
    if path.is_file():
        path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def copy_stream_read_only(source: BinaryIO, destination: Path) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    with destination.open("wb") as target:
        shutil.copyfileobj(source, target)
    digest = sha256_file(destination)
    _set_read_only(destination)
    return {
        "path": destination.name,
        "sha256": digest,
        "size_bytes": destination.stat().st_size,
    }


def copy_file_read_only(source: Path, destination: Path) -> dict[str, object]:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copy2(source, destination)
    digest = sha256_file(destination)
    _set_read_only(destination)
    return {
        "path": destination.name,
        "sha256": digest,
        "size_bytes": destination.stat().st_size,
    }


def copy_directory_read_only(
    source: Path, destination: Path
) -> list[dict[str, object]]:
    source = source.resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    if destination.resolve().is_relative_to(source):
        raise ValueError("资料输入目录不能包含工作台输出目录，请选择独立的资料子目录。")
    records: list[dict[str, object]] = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("资料目录含链接，请先复制为普通文件。")
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        record = copy_file_read_only(item, target)
        record["path"] = relative.as_posix()
        records.append(record)
    return records


def extract_zip_read_only(zip_path: Path, destination: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        if (
            len(archive.infolist()) > 10000
            or sum(i.file_size for i in archive.infolist()) > 2_000_000_000
        ):
            raise ValueError("ZIP exceeds extraction limit")
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalized = info.filename.replace("\\", "/")
            pure = PurePosixPath(normalized)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or not pure.parts
                or any(
                    ":" in part
                    or part.endswith((" ", "."))
                    or re.match(
                        r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",
                        part,
                        re.IGNORECASE,
                    )
                    for part in pure.parts
                )
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.file_size > 200_000_000
                or info.file_size / max(info.compress_size, 1) > 1000
            ):
                raise ValueError(f"ZIP contains unsafe path: {info.filename}")
            target = destination.joinpath(*pure.parts)
            target_resolved = target.resolve()
            if os.path.commonpath(
                [str(destination_resolved), str(target_resolved)]
            ) != str(destination_resolved):
                raise ValueError(f"ZIP entry escapes destination: {info.filename}")
            if target.exists():
                raise FileExistsError(target)
            with archive.open(info) as source:
                record = copy_stream_read_only(source, target)
            record["path"] = pure.as_posix()
            records.append(record)
    return records


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def append_audit(
    path: Path, event: str, details: dict[str, object] | None = None
) -> None:
    safe = {
        k: v
        for k, v in (details or {}).items()
        if k not in {"contact", "api_key", "raw_questionnaire"}
    }
    line = json.dumps(
        {
            "time": datetime.now().astimezone().isoformat(),
            "event": event,
            "details": safe,
        },
        ensure_ascii=False,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
