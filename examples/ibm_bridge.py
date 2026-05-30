from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aegis_kernel import AegisContinuityKernel
from examples.qiskit_bridge import telemetry_from_counts


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def require_qiskit_core():
    try:
        from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
    except ImportError as exc:
        raise SystemExit("Install optional Qiskit packages with: python -m pip install -r requirements-qiskit.txt") from exc
    return ClassicalRegister, QuantumCircuit, QuantumRegister, transpile


def require_runtime():
    try:
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
        from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
    except ImportError as exc:
        raise SystemExit("Install IBM Runtime with: python -m pip install qiskit-ibm-runtime python-dotenv") from exc
    return QiskitRuntimeService, Sampler, generate_preset_pass_manager


def build_measured_ghz_circuit(delay_ms: float = 0.0) -> Any:
    classical_register, quantum_circuit, quantum_register, _ = require_qiskit_core()
    qreg = quantum_register(4, "q")
    creg = classical_register(4, "meas")
    circuit = quantum_circuit(qreg, creg)
    circuit.h(qreg[0])
    if delay_ms > 0:
        circuit.delay(delay_ms, qreg, unit="ms")
    circuit.cx(qreg[0], qreg[1])
    circuit.cx(qreg[1], qreg[2])
    circuit.cx(qreg[2], qreg[3])
    circuit.measure(qreg, creg)
    return circuit


def env_instance() -> str | None:
    load_dotenv_if_available()
    value = os.environ.get("IBM_QUANTUM_INSTANCE")
    return value.strip() if value and value.strip() else None


def save_account_from_env(channel: str, instance: str | None = None, overwrite: bool = True) -> dict[str, object]:
    load_dotenv_if_available()
    token = os.environ.get("IBM_QUANTUM_TOKEN")
    if not token:
        raise SystemExit("IBM_QUANTUM_TOKEN is not set. Put it in local .env or set it in your shell.")
    instance = instance or env_instance()
    qiskit_runtime_service, _, _ = require_runtime()
    qiskit_runtime_service.save_account(channel=channel, token=token, instance=instance, overwrite=overwrite, set_as_default=True)
    return {"status": "saved", "channel": channel, "instance_configured": bool(instance), "token_loaded_from_env": True}


def select_real_backend(channel: str, backend_name: str | None = None, instance: str | None = None):
    qiskit_runtime_service, _, _ = require_runtime()
    instance = instance or env_instance()
    service = qiskit_runtime_service(channel=channel, instance=instance)
    if backend_name:
        backend = service.backend(backend_name, instance=instance)
    else:
        backend = service.least_busy(operational=True, simulator=False, min_num_qubits=4, instance=instance)
    return service, backend


def extract_sampler_counts(result: Any) -> dict[str, int]:
    pub_result = result[0]
    data = getattr(pub_result, "data", None)
    if data is None:
        raise ValueError("Sampler result did not expose pub_result.data")
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
    raise ValueError(f"Could not locate bit counts in sampler result data fields: {dir(data)}")


def run_real_hardware_once(
    shots: int = 1024,
    seed: int = 2026,
    channel: str = "ibm_quantum_platform",
    backend_name: str | None = None,
    delay_ms: float = 0.0,
    instance: str | None = None,
) -> dict[str, object]:
    _, sampler_cls, generate_preset_pass_manager = require_runtime()
    _, backend = select_real_backend(channel=channel, backend_name=backend_name, instance=instance)
    print(f"[AEGIS HARDWARE HANDSHAKE] Connected to real IBM QPU: {backend.name}", flush=True)
    circuit = build_measured_ghz_circuit(delay_ms=delay_ms)
    pass_manager = generate_preset_pass_manager(optimization_level=1, backend=backend)
    isa_circuit = pass_manager.run(circuit)
    sampler = sampler_cls(mode=backend)
    started = time.perf_counter()
    job = sampler.run([isa_circuit], shots=shots)
    job_id = job.job_id() if hasattr(job, "job_id") else "unknown"
    print(f"[AEGIS HARDWARE QUEUE] Submitted job {job_id} with {shots} shots. Waiting for IBM result...", flush=True)
    result = job.result()
    elapsed = time.perf_counter() - started
    counts = extract_sampler_counts(result)
    payload = process_counts(
        counts,
        shots=shots,
        seed=seed,
        backend_name=backend.name,
        elapsed_seconds=elapsed,
        source="ibm_real_hardware",
        delay_ms=delay_ms,
    )
    payload["job_id"] = job_id
    return payload


def run_fake_backend_once(shots: int = 1024, seed: int = 2026, delay_ms: float = 0.0) -> dict[str, object]:
    _, _, _, transpile = require_qiskit_core()
    try:
        from qiskit_aer import AerSimulator
        from qiskit_ibm_runtime.fake_provider import FakeOsaka
    except ImportError as exc:
        raise SystemExit("Fake backend path requires qiskit-aer and qiskit-ibm-runtime.") from exc
    fake_backend = FakeOsaka()
    simulator = AerSimulator.from_backend(fake_backend)
    circuit = transpile(build_measured_ghz_circuit(delay_ms=delay_ms), simulator, seed_transpiler=seed)
    started = time.perf_counter()
    result = simulator.run(circuit, shots=shots, seed_simulator=seed).result()
    elapsed = time.perf_counter() - started
    counts = dict(result.get_counts())
    return process_counts(counts, shots=shots, seed=seed, backend_name=fake_backend.name, elapsed_seconds=elapsed, source="ibm_fake_backend", delay_ms=delay_ms)


def process_counts(
    counts: dict[str, int],
    shots: int,
    seed: int,
    backend_name: str,
    elapsed_seconds: float,
    source: str,
    delay_ms: float = 0.0,
) -> dict[str, object]:
    rng = random.Random(seed)
    good_counts = int(counts.get("0000", 0)) + int(counts.get("1111", 0))
    total_counts = max(1, sum(int(value) for value in counts.values()))
    ghz_population = good_counts / total_counts
    raw_error_rate = 1.0 - ghz_population
    telemetry = telemetry_from_counts(
        counts,
        total_counts,
        epoch=1,
        rng=rng,
        leakage_lambda=min(1.0, raw_error_rate),
        measurement_efficiency=max(0.1, 1.0 - raw_error_rate),
        crosstalk_inject=False,
    )
    for item in telemetry:
        item.environment.latency = min(1.0, elapsed_seconds / 600.0)
    kernel = AegisContinuityKernel(seed=seed)
    cycle = kernel.execute_cycle(telemetry, scenario=f"{source}_{backend_name}")
    return {
        "source": source,
        "backend": backend_name,
        "shots": shots,
        "delay_ms": delay_ms,
        "counts": counts,
        "good_counts_0000_1111": good_counts,
        "total_counts": total_counts,
        "ghz_population": ghz_population,
        "raw_error_rate": raw_error_rate,
        "round_trip_seconds": elapsed_seconds,
        "q_conf": cycle.q_conf,
        "continuity_gate_passed": cycle.continuity_gate_passed,
        "governance_states": cycle.governance_states,
        "qom_compact_payload_bits": cycle.qom_compact_payload_bits,
        "qom_compact_payload_hex": cycle.qom_compact_payload_hex,
        "merkle_root": cycle.merkle_root,
        "opte_policy_context_hash": cycle.opte_policy_context_hash,
        "reviewer_telemetry": cycle.reviewer_telemetry,
    }


def main() -> None:
    load_dotenv_if_available()
    parser = argparse.ArgumentParser(description="Optional IBM Quantum hardware/fake-backend bridge for AEGIS.")
    parser.add_argument("--save-account", action="store_true", help="Save IBM_QUANTUM_TOKEN from local .env or shell.")
    parser.add_argument("--real", action="store_true", help="Submit to real IBM hardware. This may wait in queue.")
    parser.add_argument("--backend", default=None, help="Specific IBM backend name. Defaults to least busy real backend.")
    parser.add_argument("--channel", default=os.environ.get("IBM_QUANTUM_CHANNEL", "ibm_quantum_platform"))
    parser.add_argument("--instance", default=os.environ.get("IBM_QUANTUM_INSTANCE"), help="Optional IBM Quantum Runtime instance CRN or service name.")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Optional GHZ idle delay after H and before CX cascade.")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=Path("ibm_bridge_result.json"))
    args = parser.parse_args()

    if args.save_account:
        print(json.dumps(save_account_from_env(args.channel, args.instance), indent=2))
        return

    if args.real:
        payload = run_real_hardware_once(
            shots=args.shots,
            seed=args.seed,
            channel=args.channel,
            backend_name=args.backend,
            delay_ms=args.delay_ms,
            instance=args.instance,
        )
    else:
        payload = run_fake_backend_once(shots=args.shots, seed=args.seed, delay_ms=args.delay_ms)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
