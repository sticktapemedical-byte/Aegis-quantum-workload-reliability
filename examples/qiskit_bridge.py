from __future__ import annotations

import math
import random
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aegis_kernel import AegisContinuityKernel, EnvironmentVector, NodeTelemetry, normalize_vector


def require_qiskit():
    try:
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error, thermal_relaxation_error
    except ImportError as exc:
        raise SystemExit(
            "Qiskit bridge requires optional packages: qiskit and qiskit-aer. "
            "Install them in a separate environment with: pip install qiskit qiskit-aer"
        ) from exc
    return QuantumCircuit, transpile, AerSimulator, NoiseModel, ReadoutError, depolarizing_error, thermal_relaxation_error


def build_ghz_circuit(quantum_circuit, crosstalk_inject: bool = False, rng: random.Random | None = None):
    circuit = quantum_circuit(4, 4)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.cx(1, 2)
    circuit.cx(2, 3)
    if crosstalk_inject:
        local_rng = rng or random.Random(0)
        circuit.rxx(local_rng.uniform(0.015, 0.055), 0, 1)
        circuit.rzz(local_rng.uniform(0.015, 0.055), 2, 3)
    circuit.measure(range(4), range(4))
    return circuit


def build_noise_model(
    noise_model_cls,
    readout_error_cls,
    depolarizing_error,
    thermal_relaxation_error,
    noise_scale: float = 1.0,
    measurement_efficiency: float = 0.82,
):
    noise_scale = max(0.1, min(5.0, noise_scale))
    measurement_efficiency = max(0.1, min(1.0, measurement_efficiency))
    model = noise_model_cls()
    single_qubit_thermal = thermal_relaxation_error(t1=50_000, t2=70_000, time=120 * noise_scale)
    two_qubit_thermal = thermal_relaxation_error(t1=50_000, t2=70_000, time=350 * noise_scale).expand(
        thermal_relaxation_error(t1=50_000, t2=70_000, time=350 * noise_scale)
    )
    model.add_all_qubit_quantum_error(
        single_qubit_thermal.compose(depolarizing_error(min(0.20, 0.002 * noise_scale), 1)), ["h"]
    )
    model.add_all_qubit_quantum_error(
        two_qubit_thermal.compose(depolarizing_error(min(0.35, 0.006 * noise_scale), 2)), ["cx", "rxx", "rzz"]
    )
    readout_flip = min(0.25, (1.0 - measurement_efficiency) * 0.10 * noise_scale)
    model.add_all_qubit_readout_error(readout_error_cls([[1.0 - readout_flip, readout_flip], [readout_flip, 1.0 - readout_flip]]))
    return model


def counts_to_expectations(counts: dict[str, int], shots: int) -> list[float]:
    expectations = []
    for qubit_index in range(4):
        z_sum = 0.0
        for bitstring, count in counts.items():
            bit = bitstring[::-1][qubit_index]
            z_sum += (1.0 if bit == "0" else -1.0) * count
        expectations.append(z_sum / max(1, shots))
    return expectations


def telemetry_from_counts(
    counts: dict[str, int],
    shots: int,
    epoch: int,
    rng: random.Random,
    leakage_lambda: float = 0.0,
    measurement_efficiency: float = 0.82,
    crosstalk_inject: bool = False,
) -> list[NodeTelemetry]:
    leakage_lambda = max(0.0, min(1.0, leakage_lambda))
    measurement_efficiency = max(0.1, min(1.0, measurement_efficiency))
    expectations = counts_to_expectations(counts, shots)
    parity_mass = sum(count for bitstring, count in counts.items() if bitstring in {"0000", "1111"}) / max(1, shots)
    entropy_proxy = min(1.0, (1.0 - parity_mass) + leakage_lambda * 0.28 + (0.10 if crosstalk_inject else 0.0))
    environment = EnvironmentVector(
        thermal=min(1.0, 0.10 + entropy_proxy * 0.40),
        electromagnetic=min(1.0, 0.08 + abs(expectations[0] - expectations[1]) * 0.30),
        voltage=min(1.0, 0.06 + entropy_proxy * 0.20),
        radiation=min(1.0, 0.05 + (1.0 - abs(sum(expectations) / 4.0)) * 0.18 + leakage_lambda * 0.18),
        latency=min(1.0, 0.06 + epoch * 0.002),
    )
    telemetry = []
    for index, expectation in enumerate(expectations):
        leaked_channel = leakage_lambda > 0.0 and index % 2 == 0
        if leaked_channel:
            expectation *= 1.0 - (0.35 * leakage_lambda)
        phase = math.atan2(math.sqrt(max(0.0, 1.0 - expectation * expectation)), expectation)
        vector = normalize_vector([expectation, entropy_proxy + rng.uniform(-0.01, 0.01), 1.0 - entropy_proxy])
        telemetry.append(
            NodeTelemetry(
                node_id=f"Q_NODE_{index}",
                raw_phase=phase,
                phase_velocity=0.08 + entropy_proxy * 0.22,
                phase_acceleration=rng.uniform(-0.20, 0.20) + entropy_proxy * 0.35 + leakage_lambda * 0.18,
                bloch_vector=vector,
                signal_mu=(0.30 + entropy_proxy * 0.35) * measurement_efficiency,
                environment=environment,
                suspected_attack=crosstalk_inject and index in {1, 2},
                crypto_valid=True,
                mission_priority=0.65,
            )
        )
    return telemetry


def run_bridge(
    cycles: int = 6,
    shots: int = 2048,
    seed: int = 2026,
    noise_scale: float = 1.0,
    crosstalk_inject: bool = False,
    leakage_lambda: float = 0.0,
    measurement_efficiency: float = 0.82,
    stop_event: threading.Event | None = None,
) -> list[dict[str, object]]:
    (
        quantum_circuit,
        transpile,
        simulator_cls,
        noise_model_cls,
        readout_error_cls,
        depolarizing_error,
        thermal_relaxation_error,
    ) = require_qiskit()
    rng = random.Random(seed)
    noise_model = build_noise_model(
        noise_model_cls,
        readout_error_cls,
        depolarizing_error,
        thermal_relaxation_error,
        noise_scale=noise_scale,
        measurement_efficiency=measurement_efficiency,
    )
    simulator = simulator_cls(noise_model=noise_model, seed_simulator=seed)
    circuit = transpile(build_ghz_circuit(quantum_circuit, crosstalk_inject=crosstalk_inject, rng=rng), simulator)
    kernel = AegisContinuityKernel(seed=seed)
    results = []

    for epoch in range(1, cycles + 1):
        if stop_event is not None and stop_event.is_set():
            break
        job = simulator.run(circuit, shots=shots)
        counts = job.result().get_counts()
        telemetry = telemetry_from_counts(
            counts,
            shots,
            epoch,
            rng,
            leakage_lambda=leakage_lambda,
            measurement_efficiency=measurement_efficiency,
            crosstalk_inject=crosstalk_inject,
        )
        cycle = kernel.execute_cycle(telemetry, scenario=f"qiskit_ghz_epoch_{epoch}")
        results.append(
            {
                "epoch": epoch,
                "counts": counts,
                "bridge_parameters": {
                    "noise_scale": noise_scale,
                    "crosstalk_inject": crosstalk_inject,
                    "leakage_lambda": leakage_lambda,
                    "measurement_efficiency": measurement_efficiency,
                },
                "q_conf": cycle.q_conf,
                "continuity_gate_passed": cycle.continuity_gate_passed,
                "governance_states": cycle.governance_states,
                "qom_compact_payload_bits": cycle.qom_compact_payload_bits,
                "qom_compact_payload_hex": cycle.qom_compact_payload_hex,
                "merkle_root": cycle.merkle_root,
            }
        )
    return results


def main() -> None:
    for item in run_bridge():
        states = "|".join(item["governance_states"])
        print(
            f"epoch={item['epoch']} q_conf={item['q_conf']:.4f} "
            f"gate={item['continuity_gate_passed']} qom={item['qom_compact_payload_bits']}b states={states}"
        )


if __name__ == "__main__":
    main()
