from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.ibm_bridge import (
    build_measured_ghz_circuit,
    extract_sampler_counts,
    process_counts,
    require_qiskit_core,
    require_runtime,
    select_real_backend,
)


def run_fake_batch_loop(batches: int, shots: int, seed: int) -> dict[str, object]:
    _, _, _, transpile = require_qiskit_core()
    try:
        from qiskit_aer import AerSimulator
        from qiskit_ibm_runtime.fake_provider import FakeOsaka
    except ImportError as exc:
        raise SystemExit("Fake session loop requires qiskit-aer and qiskit-ibm-runtime.") from exc
    fake_backend = FakeOsaka()
    simulator = AerSimulator.from_backend(fake_backend)
    circuit = transpile(build_measured_ghz_circuit(), simulator, seed_transpiler=seed)
    records = []
    started = time.perf_counter()
    for batch in range(1, batches + 1):
        batch_start = time.perf_counter()
        result = simulator.run(circuit, shots=shots, seed_simulator=seed + batch).result()
        elapsed = time.perf_counter() - batch_start
        counts = dict(result.get_counts())
        payload = process_counts(
            counts,
            shots=shots,
            seed=seed + batch,
            backend_name=fake_backend.name,
            elapsed_seconds=elapsed,
            source=f"ibm_fake_session_batch_{batch}",
        )
        records.append({"batch": batch, **payload})
        print(
            f"[AEGIS SESSION FAKE] batch={batch} GHZ={payload['ghz_population']:.4f} "
            f"q_conf={payload['q_conf']:.4f} gate={payload['continuity_gate_passed']}",
            flush=True,
        )
    return summarize_records(
        source="ibm_fake_session_batch_loop",
        backend=fake_backend.name,
        session_id="local_fake_session",
        records=records,
        elapsed_seconds=time.perf_counter() - started,
    )


def run_real_session_batch_loop(
    backend_name: str,
    batches: int,
    shots: int,
    seed: int,
    channel: str,
) -> dict[str, object]:
    _, sampler_cls, generate_preset_pass_manager = require_runtime()
    from qiskit_ibm_runtime import Session

    _, backend = select_real_backend(channel=channel, backend_name=backend_name)
    print(f"[AEGIS SESSION] Connected to IBM QPU: {backend.name}", flush=True)
    pass_manager = generate_preset_pass_manager(optimization_level=1, backend=backend)
    isa_circuit = pass_manager.run(build_measured_ghz_circuit())
    records = []
    started = time.perf_counter()
    with Session(backend=backend) as session:
        sampler = sampler_cls(mode=session)
        session_id = session.session_id
        for batch in range(1, batches + 1):
            batch_start = time.perf_counter()
            job = sampler.run([isa_circuit], shots=shots)
            job_id = job.job_id() if hasattr(job, "job_id") else "unknown"
            print(f"[AEGIS SESSION] batch={batch}/{batches} job={job_id} shots={shots}", flush=True)
            result = job.result()
            elapsed = time.perf_counter() - batch_start
            counts = extract_sampler_counts(result)
            payload = process_counts(
                counts,
                shots=shots,
                seed=seed + batch,
                backend_name=backend.name,
                elapsed_seconds=elapsed,
                source=f"ibm_real_session_batch_{batch}",
            )
            records.append({"batch": batch, "job_id": job_id, **payload})
            print(
                f"[AEGIS SESSION] batch={batch} GHZ={payload['ghz_population']:.4f} "
                f"q_conf={payload['q_conf']:.4f} gate={payload['continuity_gate_passed']}",
                flush=True,
            )
    return summarize_records(
        source="ibm_real_session_batch_loop",
        backend=backend.name,
        session_id=session_id,
        records=records,
        elapsed_seconds=time.perf_counter() - started,
    )


def summarize_records(source: str, backend: str, session_id: str, records: list[dict[str, Any]], elapsed_seconds: float) -> dict[str, object]:
    mean_ghz = sum(float(record["ghz_population"]) for record in records) / max(1, len(records))
    mean_q_conf = sum(float(record["q_conf"]) for record in records) / max(1, len(records))
    gates_passed = sum(1 for record in records if record["continuity_gate_passed"])
    return {
        "source": source,
        "backend": backend,
        "session_id": session_id,
        "batches": len(records),
        "shots_per_batch": records[0]["shots"] if records else 0,
        "total_shots": sum(int(record["shots"]) for record in records),
        "round_trip_seconds": elapsed_seconds,
        "mean_ghz_population": mean_ghz,
        "mean_raw_error_rate": 1.0 - mean_ghz,
        "mean_q_conf": mean_q_conf,
        "continuity_gates_passed": gates_passed,
        "continuity_gates_total": len(records),
        "final_qom_compact_payload_bits": records[-1]["qom_compact_payload_bits"] if records else 0,
        "final_qom_compact_payload_hex": records[-1]["qom_compact_payload_hex"] if records else "",
        "final_merkle_root": records[-1]["merkle_root"] if records else "",
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Qiskit Runtime Session-style batch loop for AEGIS.")
    parser.add_argument("--real", action="store_true", help="Use IBM Runtime Session on real hardware.")
    parser.add_argument("--backend", default="ibm_marrakesh")
    parser.add_argument("--channel", default="ibm_quantum_platform")
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--shots", type=int, default=256)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=Path("ibm_session_batch_loop.json"))
    args = parser.parse_args()
    if args.real:
        payload = run_real_session_batch_loop(args.backend, args.batches, args.shots, args.seed, args.channel)
    else:
        payload = run_fake_batch_loop(args.batches, args.shots, args.seed)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
