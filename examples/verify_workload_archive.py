from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SECRET_PATTERNS = [
    re.compile(rb"IBM_QUANTUM_TOKEN", re.IGNORECASE),
    re.compile(rb"ApiKey-[0-9a-fA-F-]{36}"),
    re.compile(rb'"apikey"\s*:'),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_report_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"artifacts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def report_jobs(manifest: dict[str, Any]) -> set[str]:
    return {str(row.get("job_id")) for row in manifest.get("artifacts", []) if row.get("job_id")}


def extract_counts_from_runtime_json(raw: bytes) -> dict[str, int]:
    payload = json.loads(raw.decode("utf-8-sig"))
    if "counts" in payload and isinstance(payload["counts"], dict):
        return {str(k): int(v) for k, v in payload["counts"].items()}
    try:
        from qiskit_ibm_runtime import RuntimeDecoder

        decoded = json.loads(raw.decode("utf-8-sig"), cls=RuntimeDecoder)
        pub = decoded[0]
        data = getattr(pub, "data", None)
        if data is not None:
            for name in dir(data):
                if name.startswith("_"):
                    continue
                register = getattr(data, name)
                if hasattr(register, "get_counts"):
                    return {str(k): int(v) for k, v in register.get_counts().items()}
    except Exception:
        pass
    return {}


def job_id_from_name(name: str) -> str | None:
    match = re.match(r"job-(.+?)-(info|result)\.json$", Path(name).name)
    return match.group(1) if match else None


def verify_archive(zip_path: Path, manifest_path: Path, index_path: Path) -> dict[str, Any]:
    manifest = load_report_manifest(manifest_path)
    included_jobs = report_jobs(manifest)
    rows: list[dict[str, Any]] = []
    leaks: list[str] = []
    with ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".json")]
        by_job: dict[str, dict[str, str]] = {}
        entry_hashes: dict[str, str] = {}
        for name in names:
            raw = archive.read(name)
            entry_hashes[name] = sha256_bytes(raw)
            if any(pattern.search(raw) for pattern in SECRET_PATTERNS):
                leaks.append(name)
            job_id = job_id_from_name(name)
            if job_id:
                kind = "info" if name.endswith("-info.json") else "result"
                by_job.setdefault(job_id, {})[kind] = name

        for job_id in sorted(by_job):
            pair = by_job[job_id]
            info_name = pair.get("info")
            result_name = pair.get("result")
            info: dict[str, Any] = {}
            counts: dict[str, int] = {}
            if info_name:
                info = json.loads(archive.read(info_name).decode("utf-8-sig"))
            if result_name:
                counts = extract_counts_from_runtime_json(archive.read(result_name))
            shots = sum(counts.values()) if counts else None
            rows.append(
                {
                    "job_id": job_id,
                    "backend": info.get("backend"),
                    "created": info.get("created"),
                    "status": info.get("status") or info.get("state"),
                    "shots": shots,
                    "info_file": info_name,
                    "result_file": result_name,
                    "info_sha256": entry_hashes.get(info_name or ""),
                    "result_sha256": entry_hashes.get(result_name or ""),
                    "counts_parse_ok": bool(counts),
                    "included_in_report": job_id in included_jobs,
                }
            )

    missing_pairs = [row["job_id"] for row in rows if not row["info_file"] or not row["result_file"]]
    counts_failures = [row["job_id"] for row in rows if not row["counts_parse_ok"]]
    report_matched = sum(1 for row in rows if row["included_in_report"])
    payload = {
        "source": "aegis_workload_archive_verifier",
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "zip": str(zip_path),
        "zip_sha256": sha256_bytes(zip_path.read_bytes()),
        "job_count": len(rows),
        "missing_pair_count": len(missing_pairs),
        "counts_parse_failure_count": len(counts_failures),
        "private_token_leak_count": len(leaks),
        "report_matched_job_count": report_matched,
        "success": not missing_pairs and not counts_failures and not leaks,
        "jobs": rows,
        "missing_pairs": missing_pairs,
        "counts_parse_failures": counts_failures,
        "private_token_leak_files": leaks,
    }
    write_index(index_path, payload)
    return payload


def write_index(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# AEGIS Workload Archive Index",
        "",
        f"- Archive: `{payload['zip']}`",
        f"- Archive SHA256: `{payload['zip_sha256']}`",
        f"- Jobs: `{payload['job_count']}`",
        f"- Missing pairs: `{payload['missing_pair_count']}`",
        f"- Counts parse failures: `{payload['counts_parse_failure_count']}`",
        f"- Private token leaks: `{payload['private_token_leak_count']}`",
        f"- Jobs matched to report manifest: `{payload['report_matched_job_count']}`",
        "",
        "| Job ID | Backend | Created | Status | Shots | Result File | Artifact Hash | Included in Report |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in payload["jobs"]:
        lines.append(
            "| {job_id} | {backend} | {created} | {status} | {shots} | {result_file} | `{result_sha256}` | {included} |".format(
                job_id=row.get("job_id") or "",
                backend=row.get("backend") or "",
                created=row.get("created") or "",
                status=row.get("status") or "",
                shots=row.get("shots") if row.get("shots") is not None else "",
                result_file=row.get("result_file") or "",
                result_sha256=(row.get("result_sha256") or "")[:16],
                included="yes" if row.get("included_in_report") else "no",
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify downloaded IBM workload archive pairs, hashes, counts, and report linkage.")
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("docs/validation/job_manifest.json"))
    parser.add_argument("--index", type=Path, default=Path("docs/validation/WORKLOAD_ARCHIVE_INDEX.md"))
    parser.add_argument("--output", type=Path, default=Path("docs/validation/workload_archive_verification.json"))
    args = parser.parse_args()
    payload = verify_archive(args.zip, args.manifest, args.index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("success", "job_count", "missing_pair_count", "counts_parse_failure_count", "private_token_leak_count", "report_matched_job_count")}, indent=2))


if __name__ == "__main__":
    main()
