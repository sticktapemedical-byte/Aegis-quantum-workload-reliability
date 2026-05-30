from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.ibm_bridge import run_fake_backend_once, run_real_hardware_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure AEGIS reviewer telemetry compression ratio on fake or real backend output.")
    parser.add_argument("--real", action="store_true", help="Submit one real IBM job.")
    parser.add_argument("--backend", default="ibm_marrakesh")
    parser.add_argument("--channel", default="ibm_quantum_platform")
    parser.add_argument("--shots", type=int, default=256)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=Path("compression_telemetry_check.json"))
    args = parser.parse_args()

    payload = (
        run_real_hardware_once(shots=args.shots, seed=args.seed, channel=args.channel, backend_name=args.backend)
        if args.real
        else run_fake_backend_once(shots=args.shots, seed=args.seed)
    )
    reviewer = payload.get("reviewer_telemetry")
    if not reviewer:
        raise SystemExit("reviewer_telemetry missing from backend payload")
    result = {
        "source": "aegis_compression_telemetry_check",
        "real": args.real,
        "backend": payload.get("backend"),
        "job_id": payload.get("job_id"),
        "shots": payload.get("shots"),
        "data_compression_ratio": reviewer.get("data_compression_ratio"),
        "data_compression_ratio_method": reviewer.get("data_compression_ratio_method"),
        "raw_telemetry_payload_bytes": reviewer.get("raw_telemetry_payload_bytes"),
        "qom_compact_payload_bytes": reviewer.get("qom_compact_payload_bytes"),
        "qom_compact_payload_bits": payload.get("qom_compact_payload_bits"),
        "qom_compact_payload_hex": payload.get("qom_compact_payload_hex"),
        "merkle_root": payload.get("merkle_root"),
        "claim_boundary": "Compression ratio is measured as raw telemetry JSON bytes divided by compact .QOM payload bytes for this returned-output processing run.",
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
