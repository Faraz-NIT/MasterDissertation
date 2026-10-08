"""Reassemble and verify the complete study archives stored in ordinary Git.

Run from any directory with Python 3.11+; no third-party packages are needed.
The default writes verified ZIPs into study_results/reassembled (Git-ignored).
Use --restore DIRECTORY to additionally restore every original study output.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or ".." in name.parts:
        raise ValueError(f"Unsafe archive path: {relative}")
    path = root.joinpath(*name.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves the destination: {relative}")
    return path


def reassemble(delivery: Path, output: Path, info: dict) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    archives = {}
    for key, archive in info["archives"].items():
        destination = safe_path(output, archive["filename"])
        if destination.exists():
            if digest(destination) != archive["sha256"]:
                raise ValueError(f"Existing file differs; preserve it: {destination}")
            print(f"Already verified: {destination.name}", flush=True)
        else:
            temporary = destination.with_suffix(destination.suffix + ".partial")
            if temporary.exists():
                raise FileExistsError(f"Preserve unfinished output: {temporary}")
            combined = hashlib.sha256()
            with temporary.open("xb") as target:
                for part in archive["parts"]:
                    source = safe_path(delivery, part["path"])
                    actual = hashlib.sha256()
                    count = 0
                    with source.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            actual.update(chunk)
                            combined.update(chunk)
                            count += len(chunk)
                            target.write(chunk)
                    if count != part["bytes"] or actual.hexdigest() != part["sha256"]:
                        raise ValueError(f"Archive part failed verification: {source}")
            if temporary.stat().st_size != archive["bytes"] or combined.hexdigest() != archive["sha256"]:
                raise ValueError(f"Reassembled archive failed verification: {temporary}")
            temporary.rename(destination)
            print(f"Verified: {destination.name} ({archive['bytes']:,} bytes)", flush=True)
        archives[key] = destination
    return archives


def restore(delivery: Path, destination: Path, info: dict, archives: dict[str, Path]) -> None:
    inventory_path = safe_path(delivery, info["inventory"]["path"])
    if digest(inventory_path) != info["inventory"]["sha256"]:
        raise ValueError("Study file inventory failed verification")
    with gzip.open(inventory_path, "rt", encoding="utf-8") as stream:
        inventory = json.load(stream)
    destination.mkdir(parents=True, exist_ok=True)
    verified = 0
    with ExitStack() as stack:
        opened = {key: stack.enter_context(zipfile.ZipFile(path)) for key, path in archives.items()}
        for record in inventory["files"]:
            target = safe_path(destination, record["path"])
            if target.exists():
                if target.stat().st_size != record["bytes"] or digest(target) != record["sha256"]:
                    raise ValueError(f"Existing study file differs; preserve it: {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if record.get("archive_file"):
                    with archives[record["archive"]].open("rb") as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                else:
                    with opened[record["archive"]].open(record["member"]) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                if target.stat().st_size != record["bytes"] or digest(target) != record["sha256"]:
                    raise ValueError(f"Restored study file failed verification: {target}")
            verified += 1
            if verified % 10000 == 0:
                print(f"Restored and verified {verified:,} files", flush=True)
    print(f"Restored and verified all {verified:,} original study files in {destination}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives-dir", type=Path, default=ROOT / "study_results/reassembled")
    parser.add_argument("--restore", type=Path, help="Restore original results/, prepared data and external_helpers/")
    args = parser.parse_args()
    delivery = ROOT / "study_results"
    info = json.loads((delivery / "archives.json").read_text())
    archives = reassemble(delivery, args.archives_dir, info)
    if args.restore:
        restore(delivery, args.restore, info, archives)


if __name__ == "__main__":
    main()
