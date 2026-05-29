from __future__ import annotations

import math
import random
import statistics
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aegis_kernel import (  # noqa: E402
    AegisContinuityKernel,
    GovernanceState,
    KernelConfig,
    QOM_COMPACT_PAYLOAD_BITS,
    QOM_COMPACT_STRUCT_FORMAT,
    build_nominal_telemetry,
    normalize_vector,
    vector_distance,
)


def test_crypto_invalidation_closes_hardware_gate_and_sets_crypto_seal() -> None:
    kernel = AegisContinuityKernel(seed=7)
    rng = random.Random(7)

    telemetry = build_nominal_telemetry(kernel.config.node_count, rng, "crypto_seal")
    result = kernel.execute_cycle(telemetry, scenario="crypto_signature_slip")

    assert result.governance_mask & GovernanceState.CRYPTO_SEAL
    assert not result.continuity_gate_passed
    assert result.hardware_register_target["gate_open"] is False
    assert result.unsafe_output_prevented is True


def test_holdover_ceiling_breach_triggers_circuit_abort() -> None:
    config = KernelConfig(epsilon_p_max=0.01)
    kernel = AegisContinuityKernel(config=config, seed=11)
    rng = random.Random(11)

    telemetry = build_nominal_telemetry(kernel.config.node_count, rng, "normal")
    for sample in telemetry:
        sample.phase_velocity = 10.0
        sample.phase_acceleration = 0.0

    result = kernel.execute_cycle(telemetry, scenario="holdover_decay_stress")

    assert result.governance_mask & GovernanceState.CIRCUIT_ABORT
    assert "HOLDOVER_BREACH" in result.hard_abort_causes
    assert result.hardware_register_target["gate_open"] is False
    assert result.integrity_preserved is True


def test_riemann_unwrap_continuity_across_branch_cut() -> None:
    kernel = AegisContinuityKernel(seed=17)
    node_id = "Q_NODE_0"
    entry = kernel.track_registry[node_id]

    true_phases = [3.10 + index * 0.02 for index in range(24)]
    wrapped = [((phase + math.pi) % (2.0 * math.pi)) - math.pi for phase in true_phases]
    entry.last_raw_phase = wrapped[0]
    entry.unwrapped_phase = wrapped[0]

    unwrapped_track = [entry.unwrapped_phase]
    for phase in wrapped[1:]:
        unwrapped_track.append(kernel.manifold_unwrap({node_id: phase})[node_id])

    deltas = [right - left for left, right in zip(unwrapped_track, unwrapped_track[1:])]
    acceleration = [right - left for left, right in zip(deltas, deltas[1:])]
    accel_variance = statistics.pvariance(acceleration)

    assert all(abs(delta - 0.02) < 1e-12 for delta in deltas)
    assert accel_variance < 8.09e-8


def test_byzantine_quorum_filtering_effectiveness() -> None:
    """Synthetic poisoned-node trial showing weighted filtering beats raw centroiding."""
    kernel = AegisContinuityKernel(seed=42)
    reference = normalize_vector([0.7071, 0.0, 0.7071])
    raw_errors = []
    filtered_errors = []

    for trial in range(100):
        rng = random.Random(42 + trial)
        vectors = []
        for idx in range(12):
            if idx in {2, 5, 7, 9}:
                vector = normalize_vector([rng.uniform(-0.1, 0.1), 1.0, rng.uniform(-0.1, 0.1)])
                weight = rng.uniform(0.08, 0.24)
            else:
                drift = rng.uniform(-0.08, 0.08)
                vector = normalize_vector([reference[0] + drift, rng.uniform(-0.02, 0.02), reference[2] - drift])
                weight = rng.uniform(0.78, 0.99)
            vectors.append((f"node_{idx}", vector, weight))

        raw_centroid = normalize_vector([statistics.fmean(item[1][axis] for item in vectors) for axis in range(3)])
        filtered = [item for item in vectors if item[2] >= 0.35 and vector_distance(item[1], reference) <= 0.55]
        filtered_centroid = kernel.weighted_average_vector(filtered) if filtered else reference
        raw_errors.append(vector_distance(raw_centroid, reference))
        filtered_errors.append(vector_distance(filtered_centroid, reference))

    raw_mean = statistics.fmean(raw_errors)
    filtered_mean = statistics.fmean(filtered_errors)
    reduction = (raw_mean - filtered_mean) / max(1e-12, raw_mean)

    assert filtered_mean < raw_mean
    assert reduction > 0.80


def test_unsafe_output_prevention_grounded() -> None:
    """Governance should prevent most unsafe outputs in synthetic stress scenarios."""
    rng = random.Random(99)
    opportunities = 0
    prevented = 0

    for scenario in ["normal", "storm", "attack", "crypto_seal", "anchor_dispute", "phase_hold"]:
        kernel = AegisContinuityKernel(seed=99)
        for step in range(10):
            telemetry = build_nominal_telemetry(kernel.config.node_count, rng, scenario)
            result = kernel.execute_cycle(telemetry, scenario=f"{scenario}_step_{step}")
            opportunities += int(result.unsafe_output_opportunity)
            prevented += int(result.unsafe_output_prevented)

    efficiency = prevented / max(1, opportunities)
    assert opportunities > 0
    assert efficiency > 0.85


def test_qom_compact_payload_is_exact_176_bit_struct() -> None:
    """The compact .QOM payload is a real 22-byte big-endian struct, not a JSON placeholder."""
    kernel = AegisContinuityKernel(seed=123)
    rng = random.Random(123)
    telemetry = build_nominal_telemetry(kernel.config.node_count, rng, "normal")
    result = kernel.execute_cycle(telemetry, scenario="qom_layout_check")
    payload = bytes.fromhex(result.qom_compact_payload_hex)

    assert result.qom_compact_payload_bits == 176
    assert QOM_COMPACT_PAYLOAD_BITS == 176
    assert len(payload) == 22

    unpacked = struct.unpack(QOM_COMPACT_STRUCT_FORMAT, payload)
    phase_u32, coherence_u16, lifecycle_u16, trust_u16, backaction_u16, governance_u16, opte_u64 = unpacked

    assert 0 <= phase_u32 <= 0xFFFFFFFF
    assert 0 <= coherence_u16 <= 0xFFFF
    assert lifecycle_u16 == result.epoch
    assert 0 <= trust_u16 <= 0xFFFF
    assert 0 <= backaction_u16 <= 0xFFFF
    assert governance_u16 == result.governance_mask
    assert opte_u64 == int(result.opte_policy_context_hash[:16], 16)
