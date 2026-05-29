from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aegis_kernel import AegisContinuityKernel
from examples.fast_coherence_check import build_phase_rotation_circuit, telemetry_from_single_qubit_counts
from examples.ibm_bridge import require_runtime, select_real_backend


def extract_pub_counts(pub_result: Any) -> dict[str, int]:
    data = getattr(pub_result, "data", None)
    if data is None:
        raise ValueError("Sampler pub result did not expose data")
    for register_name in ("meas", "c", "bits"):
        register = getattr(data, register_name, None)
        if register is not None and hasattr(register, "get_counts"):
            return dict(register.get_counts())
    for name in dir(data):
        if name.startswith("_"):
            continue
        register = getattr(data, name, None)
        if hasattr(register, "get_counts"):
            return dict(register.get_counts())
    raise ValueError(f"Could not locate counts in sampler pub result fields: {dir(data)}")


def run_long_form_phase_sweep(
    backend_name: str = "ibm_marrakesh",
    shots: int = 256,
    seed: int = 2026,
    channel: str = "ibm_quantum_platform",
) -> dict[str, object]:
    _, sampler_cls, generate_preset_pass_manager = require_runtime()
    _, backend = select_real_backend(channel=channel, backend_name=backend_name)
    print(f"[AEGIS LONG FORM] Connected to IBM QPU: {backend.name}", flush=True)
    phases = [0.0, math.pi / 4.0, math.pi / 2.0, 3.0 * math.pi / 4.0, math.pi]
    circuits = [build_phase_rotation_circuit(phase) for phase in phases]
    pass_manager = generate_preset_pass_manager(optimization_level=1, backend=backend)
    isa_circuits = [pass_manager.run(circuit) for circuit in circuits]
    sampler = sampler_cls(mode=backend)
    started = time.perf_counter()
    job = sampler.run(isa_circuits, shots=shots)
    job_id = job.job_id() if hasattr(job, "job_id") else "unknown"
    print(
        f"[AEGIS LONG FORM] Submitted job {job_id}: {len(phases)} phase circuits x {shots} shots. Waiting for result...",
        flush=True,
    )
    result = job.result()
    elapsed = time.perf_counter() - started
    kernel = AegisContinuityKernel(seed=seed)
    phase_records = []
    for index, phase in enumerate(phases):
        counts = extract_pub_counts(result[index])
        telemetry, phase_metrics = telemetry_from_single_qubit_counts(
            counts,
            shots=shots,
            latency_seconds=elapsed / len(phases),
            seed=seed + index,
        )
        cycle = kernel.execute_cycle(telemetry, scenario=f"ibm_long_form_phase_{index}_{backend.name}")
        phase_records.append(
            {
                "index": index,
                "requested_phase_radians": phase,
                "counts": counts,
                "total_counts": sum(int(value) for value in counts.values()),
                **phase_metrics,
                "q_conf": cycle.q_conf,
                "trust_index": cycle.trust_index,
                "continuity_gate_passed": cycle.continuity_gate_passed,
                "governance_states": cycle.governance_states,
                "qom_compact_payload_hex": cycle.qom_compact_payload_hex,
                "merkle_root": cycle.merkle_root,
            }
        )
    passed = sum(1 for record in phase_records if record["continuity_gate_passed"])
    mean_q_conf = sum(float(record["q_conf"]) for record in phase_records) / len(phase_records)
    mean_phase_balance_error = sum(float(record["phase_balance_error"]) for record in phase_records) / len(phase_records)
    return {
        "source": "ibm_real_hardware_long_form_single_qubit_phase_sweep",
        "backend": backend.name,
        "job_id": job_id,
        "circuits": len(phases),
        "shots_per_circuit": shots,
        "total_shots": shots * len(phases),
        "round_trip_seconds": elapsed,
        "mean_q_conf": mean_q_conf,
        "mean_phase_balance_error": mean_phase_balance_error,
        "continuity_gates_passed": passed,
        "continuity_gates_total": len(phase_records),
        "final_qom_compact_payload_bits": 176,
        "final_qom_compact_payload_hex": phase_records[-1]["qom_compact_payload_hex"],
        "final_merkle_root": phase_records[-1]["merkle_root"],
        "phase_records": phase_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Long-form IBM single-qubit phase-sweep validation for AEGIS.")
    parser.add_argument("--backend", default="ibm_marrakesh")
    parser.add_argument("--channel", default="ibm_quantum_platform")
    parser.add_argument("--shots", type=int, default=256)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=Path("ibm_long_form_marrakesh.json"))
    args = parser.parse_args()
    payload = run_long_form_phase_sweep(
        backend_name=args.backend,
        shots=args.shots,
        seed=args.seed,
        channel=args.channel,
    )
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
