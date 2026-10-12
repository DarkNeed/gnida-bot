"""Compressed online snapshots and verified, ordered multipart transport."""

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing

BACKUP_PART_BYTES = 40 * 1024 * 1024
MIN_BACKUP_PART_BYTES = 1024 * 1024


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_snapshot(snapshot):
    snapshot = Path(snapshot)
    archive = snapshot.with_suffix(".zip")
    metadata = dict(format="gnidabot-backup-v1", database=snapshot.name,
                    size=snapshot.stat().st_size, sha256=file_sha256(snapshot))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        package.write(snapshot, snapshot.name)
        package.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
    return archive


def split_archive(archive, part_bytes):
    archive = Path(archive)
    if part_bytes < 1:
        raise ValueError("Некорректный размер части.")
    # Separate batch names prevent mixing files from a failed larger upload.
    prefix = f"{archive.stem}_{part_bytes}"
    parts = []
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for index in range(1, (archive.stat().st_size + part_bytes - 1) // part_bytes + 1):
            path = archive.with_name(f"{prefix}.part{index:04d}")
            with path.open("wb") as target:
                remaining = part_bytes
                part_digest = hashlib.sha256()
                while remaining:
                    block = source.read(min(remaining, 1024 * 1024))
                    if not block:
                        break
                    target.write(block)
                    digest.update(block)
                    part_digest.update(block)
                    remaining -= len(block)
            parts.append(dict(name=path.name, size=path.stat().st_size,
                              sha256=part_digest.hexdigest()))
    manifest = archive.with_name(f"{prefix}.backup.json")
    manifest.write_text(json.dumps(dict(format="gnidabot-parts-v1", archive=archive.name,
                                       size=archive.stat().st_size, sha256=digest.hexdigest(),
                                       parts=parts), ensure_ascii=False, indent=2), encoding="utf-8")
    return [archive.with_name(p["name"]) for p in parts], manifest


def _local_file(folder, name):
    if (not isinstance(name, str) or not name or name in {".", ".."}
            or Path(name).name != name or any(c in name for c in "/\\:")):
        raise ValueError("Небезопасное имя файла резервной копии.")
    path = folder / name
    if path.resolve().parent != folder.resolve():
        raise ValueError("Файл резервной копии за пределами папки.")
    return path


def restore_archive(source, output):
    """Validate everything before creating a new DB. Never replace a live file."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Файл уже существует: {output}")
    with tempfile.TemporaryDirectory(prefix="gnidabot-restore-") as directory:
        folder = Path(directory)
        archive = source
        if source.name.endswith(".backup.json"):
            manifest = json.loads(source.read_text(encoding="utf-8"))
            if manifest.get("format") != "gnidabot-parts-v1" or not manifest.get("parts"):
                raise ValueError("Неверный файл сборки.")
            archive = _local_file(folder, manifest["archive"])
            seen = set()
            with archive.open("xb") as target:
                for part in manifest["parts"]:
                    path = _local_file(source.parent, part["name"])
                    if path.name in seen:
                        raise ValueError("Повтор части резервной копии.")
                    seen.add(path.name)
                    if path.stat().st_size != part["size"] or file_sha256(path) != part["sha256"]:
                        raise ValueError(f"Повреждена часть: {path.name}")
                    with path.open("rb") as stream:
                        shutil.copyfileobj(stream, target)
            if archive.stat().st_size != manifest["size"] or file_sha256(archive) != manifest["sha256"]:
                raise ValueError("Контрольная сумма архива не совпадает.")
        with zipfile.ZipFile(archive) as package:
            metadata = json.loads(package.read("metadata.json"))
            if metadata.get("format") != "gnidabot-backup-v1":
                raise ValueError("Неизвестный формат резервной копии.")
            snapshot = _local_file(folder, metadata["database"])
            if sorted(package.namelist()) != sorted([snapshot.name, "metadata.json"]):
                raise ValueError("Неверное содержимое архива.")
            with package.open(snapshot.name) as stream, snapshot.open("xb") as target:
                shutil.copyfileobj(stream, target)
        if snapshot.stat().st_size != metadata["size"] or file_sha256(snapshot) != metadata["sha256"]:
            raise ValueError("Контрольная сумма базы не совпадает.")
        with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as database:
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("База не прошла проверку целостности.")
        # Exclusive creation also protects against an output appearing during validation.
        with snapshot.open("rb") as stream, output.open("xb") as target:
            try:
                shutil.copyfileobj(stream, target)
            except BaseException:
                target.close()
                output.unlink()
                raise
    return output
