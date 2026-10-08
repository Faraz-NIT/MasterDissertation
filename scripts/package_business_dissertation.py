"""Package the completed rewrite and verify every delivered byte."""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "study_results/business_dissertation"
ZIP = OUT / "LLM_Replenishment_Dissertation_download.zip"
MANIFEST = OUT / "delivery_manifest.json"
EXCLUDED = {ZIP.name, MANIFEST.name, "git_staging_verification.json"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def package() -> None:
    receipt = json.loads((OUT / "validation_receipt.json").read_text())
    if receipt["status"] != "VERIFIED":
        raise ValueError("The document must pass validation before packaging")
    for suffix in ("docx", "pdf"):
        path = OUT / f"LLM_Replenishment_Business_Dissertation.{suffix}"
        if digest(path) != receipt[f"{suffix}_sha256"]:
            raise ValueError(f"Validated {suffix} has changed")

    paths = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name not in EXCLUDED)
    entries = []
    with zipfile.ZipFile(ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            member = path.relative_to(OUT).as_posix()
            entries.append({"path": member, "bytes": path.stat().st_size, "sha256": digest(path)})
            archive.write(path, member)

    with zipfile.ZipFile(ZIP) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity failure")
        if set(archive.namelist()) != {entry["path"] for entry in entries}:
            raise ValueError("ZIP membership differs from manifest")
        for entry in entries:
            contents = archive.read(entry["path"])
            if len(contents) != entry["bytes"] or hashlib.sha256(contents).hexdigest() != entry["sha256"]:
                raise ValueError(f"ZIP member differs: {entry['path']}")

    files = entries + [{"path": ZIP.name, "bytes": ZIP.stat().st_size, "sha256": digest(ZIP)}]
    if any(entry["bytes"] >= 100 * 1024 * 1024 for entry in files):
        raise ValueError("A delivery file exceeds the ordinary Git size limit")
    result = {
        "status": "VERIFIED",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "zip": {"path": ZIP.name, "bytes": ZIP.stat().st_size, "sha256": digest(ZIP)},
        "zip_members_verified": len(entries),
        "files": files,
        "excluded_self_referential_or_later_receipts": sorted(EXCLUDED),
    }
    MANIFEST.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "zip_members_verified": len(entries), "zip_bytes": ZIP.stat().st_size}))


if __name__ == "__main__":
    package()
