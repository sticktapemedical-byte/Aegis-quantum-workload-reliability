from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from examples.verify_workload_archive import verify_archive


def test_workload_archive_verifier_pairs_hashes_and_counts(tmp_path: Path):
    archive_path = tmp_path / "workloads.zip"
    manifest_path = tmp_path / "job_manifest.json"
    index_path = tmp_path / "WORKLOAD_ARCHIVE_INDEX.md"
    job_id = "abc123"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            f"job-{job_id}-info.json",
            json.dumps({"id": job_id, "backend": "ibm_test", "created": "2026-05-29T00:00:00Z", "status": "Completed"}),
        )
        archive.writestr(f"job-{job_id}-result.json", json.dumps({"counts": {"00": 5, "11": 7}}))
    manifest_path.write_text(json.dumps({"artifacts": [{"job_id": job_id}]}), encoding="utf-8")

    payload = verify_archive(archive_path, manifest_path, index_path)

    assert payload["success"] is True
    assert payload["job_count"] == 1
    assert payload["jobs"][0]["shots"] == 12
    assert payload["jobs"][0]["included_in_report"] is True
    assert index_path.exists()
