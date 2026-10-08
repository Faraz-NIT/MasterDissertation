"""Package the completed cloud study without changing original evidence bytes.

This preserves every results/ file, prepared dataset and external study helper.
The existing full V2 archive is reused; all other bytes go into a supplemental
ZIP. Equal-content supplemental files share one member. A complete per-path
inventory restores the original layout, including intermediate and partial runs.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path("/workspace/tools")
OUT = ROOT / "study_results"
PART_BYTES = 48 * 1024 * 1024


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    (OUT / "archive_parts").mkdir(parents=True, exist_ok=False)
    full = ROOT / "results/v2_report/M5_v2_complete_logs_and_evidence.zip"
    frozen = json.loads((full.parent / "M5_v2_full_export_inventory.json").read_text())["members"]
    frozen_by_hash = {(r["sha256"], r["bytes"]): member for member, r in frozen.items()}
    if sha(full) != "1095db66afb2d34d059b9d702a670e21f433f7c22773407a4797277312606234":
        raise ValueError("Original complete V2 archive changed")
    candidates = []
    for folder, prefix in [(ROOT / "results", "results"), (ROOT / "data/processed", "data/processed")]:
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Unexpected evidence symlink: {path}")
            if path.is_file():
                candidates.append((prefix + "/" + path.relative_to(folder).as_posix(), path))
    excluded = {"__pycache__", "cache", "huggingface", "ollama"}
    for path in sorted(TOOLS.rglob("*")):
        relative = path.relative_to(TOOLS)
        if relative.parts[0] not in excluded and "__pycache__" not in relative.parts and path.is_file():
            candidates.append(("external_helpers/" + relative.as_posix(), path))
    records = []
    extra_payloads = {}
    metadata = {
        "format": "m5-git-study-delivery-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Every existing results/ file, prepared data file, and external study helper; completed, development, superseded and paused runs retained without alteration.",
        "excluded": ["Full raw M5 competition download", "Model weights and runtime binaries", "Virtual environments and installed dependencies", "Authentication files and compiled/runtime caches"],
        "archives": {},
    }
    with tempfile.TemporaryDirectory(prefix="m5-git-delivery-", dir="/tmp") as temporary:
        supplemental = Path(temporary) / "M5_other_study_files.zip"
        with zipfile.ZipFile(supplemental, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for index, (relative, path) in enumerate(candidates, 1):
                size = path.stat().st_size
                checksum = sha(path)
                record = {"path": relative, "bytes": size, "sha256": checksum}
                key = (checksum, size)
                if path == full:
                    record.update(archive="v2_complete", archive_file=True)
                elif key in frozen_by_hash:
                    record.update(archive="v2_complete", member=frozen_by_hash[key])
                else:
                    if key not in extra_payloads:
                        extra_payloads[key] = relative
                        archive.write(path, relative)
                    record.update(archive="supplemental", member=extra_payloads[key])
                records.append(record)
                if index % 10000 == 0:
                    print(json.dumps({"phase": "inventory", "files": index}), flush=True)
        with zipfile.ZipFile(supplemental) as archive:
            for (checksum, size), member in extra_payloads.items():
                with archive.open(member) as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != checksum or archive.getinfo(member).file_size != size:
                    raise ValueError(f"Supplemental archive changed bytes: {member}")
        for key, path in [("v2_complete", full), ("supplemental", supplemental)]:
            entry = {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha(path), "parts": []}
            combined = hashlib.sha256()
            with path.open("rb") as source:
                index = 0
                while chunk := source.read(PART_BYTES):
                    index += 1
                    name = f"archive_parts/{key}.zip.part{index:03d}"
                    target = OUT / name
                    target.write_bytes(chunk)
                    checksum = sha(target)
                    if checksum != hashlib.sha256(chunk).hexdigest():
                        raise ValueError(f"Archive part changed bytes: {name}")
                    combined.update(chunk)
                    entry["parts"].append({"path": name, "bytes": len(chunk), "sha256": checksum})
            if combined.hexdigest() != entry["sha256"]:
                raise ValueError(f"Archive part sequence changed bytes: {key}")
            metadata["archives"][key] = entry
    inventory = {"format": "m5-git-study-file-inventory-v1", "files": records}
    inventory_bytes = json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode()
    inventory_path = OUT / "study_file_inventory.json.gz"
    inventory_path.write_bytes(gzip.compress(inventory_bytes, compresslevel=6, mtime=0))
    metadata["inventory"] = {"path": inventory_path.name, "sha256": sha(inventory_path), "files": len(records), "source_bytes": sum(r["bytes"] for r in records)}
    (OUT / "archives.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"status": "VERIFIED", "source_files": len(records), "supplemental_unique_files": len(extra_payloads), "archive_bytes": sum(r["bytes"] for r in metadata["archives"].values()), "original_v2_archive_sha256": metadata["archives"]["v2_complete"]["sha256"]}), flush=True)


if __name__ == "__main__":
    main()
