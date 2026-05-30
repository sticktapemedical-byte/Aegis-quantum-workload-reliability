from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import random
import statistics
import struct
import time
from dataclasses import asdict, dataclass
from enum import IntFlag
from pathlib import Path
from typing import Iterable

from aegis_scoring import (
    calculate_q_conf_score,
    compact_payload_compression_ratio,
    environment_severity,
    normalize_meaningful_continuity_score,
    resolve_gate_thresholds_for_scenario,
)


QOM_COMPACT_STRUCT_FORMAT = ">IHHHHHQ"
QOM_COMPACT_PAYLOAD_BYTES = struct.calcsize(QOM_COMPACT_STRUCT_FORMAT)
QOM_COMPACT_PAYLOAD_BITS = QOM_COMPACT_PAYLOAD_BYTES * 8


class GovernanceState(IntFlag):
    NORMAL = 0
    STORM_PROTECT = 1 << 0
    PHASE_HOLD = 1 << 1
    ANCHOR_DISPUTE = 1 << 2
    CRYPTO_SEAL = 1 << 3
    CIRCUIT_ABORT = 1 << 4
    SECURITY_LOCKDOWN = 1 << 5
    RECOVERY_VALIDATE = 1 << 6
    SOFT_ABORT = 1 << 7
    HARD_ABORT = 1 << 8


class AbortCause(IntFlag):
    NONE = 0
    CRYPTO_FAILURE = 1 << 0
    ANCHOR_DRIFT = 1 << 1
    QUORUM_COLLAPSE = 1 << 2
    HOLDOVER_BREACH = 1 << 3
    BACKACTION_BREACH = 1 << 4
    WEATHER_BREACH = 1 << 5


@dataclass
class EnvironmentVector:
    thermal: float
    electromagnetic: float
    voltage: float
    radiation: float
    latency: float

    def severity(self) -> float:
        return environment_severity(
            thermal=self.thermal,
            electromagnetic=self.electromagnetic,
            voltage=self.voltage,
            radiation=self.radiation,
            latency=self.latency,
        )


@dataclass
class NodeTelemetry:
    node_id: str
    raw_phase: float
    phase_velocity: float
    phase_acceleration: float
    bloch_vector: list[float]
    signal_mu: float
    environment: EnvironmentVector
    suspected_attack: bool = False
    crypto_valid: bool = True
    mission_priority: float = 0.50


@dataclass
class KappaScores:
    node: float
    recon: float
    telemetry: float

    @property
    def active(self) -> float:
        return clamp((0.42 * self.node) + (0.34 * self.recon) + (0.24 * self.telemetry))


@dataclass
class TrackRegistryEntry:
    node_id: str
    kappa: KappaScores
    unwrapped_phase: float = 0.0
    last_raw_phase: float = 0.0
    wear_index: float = 0.01
    quarantined: bool = False
    quarantine_until_epoch: int = 0


@dataclass
class KernelConfig:
    node_count: int = 12
    epoch_seconds: float = 0.005
    anchor_window: int = 5
    anchor_threshold: float = 0.42
    weather_clearance_threshold: float = 0.72
    storm_threshold: float = 0.55
    attack_threshold: float = 0.34
    quorum_weight_ratio: float = 0.70
    min_physical_quorum_nodes: int = 4
    quarantine_release_kappa: float = 0.82
    recovery_validation_cycles: int = 3
    phase_hold_acceleration_threshold: float = 4.5
    epsilon_p_max: float = 0.35
    theta_backaction: float = 0.40
    mc_norm_success_threshold: float = 0.72
    storm_mc_norm_success_threshold: float = 0.12
    storm_q_conf_success_threshold: float = 0.70
    adversarial_mc_norm_success_threshold: float = 0.55
    adversarial_q_conf_success_threshold: float = 0.82
    q_conf_success_threshold: float = 0.90
    mc_raw_normalization_target: float = 18.40
    anchor_decay_lambda: float = 0.55
    unsafe_output_risk_threshold: float = 0.24
    adversarial_bypass_probability: float = 0.0090
    max_reported_efficiency: float = 0.999
    target_unnecessary_shutdown_rate: float = 0.05
    coherence_budget: float = 100.0
    cryo_thermal_budget_mw: float = 6.0
    cryo_lane_spread_threshold: float = 0.75
    chain_id: str = "AEGIS-QOM-SIMNET"


@dataclass
class LedgerBlock:
    epoch: int
    parent_hash: str
    merkle_root: str
    branch_id: str
    certificate_type: str
    birth_certificate_hash: str
    governance_mask: int
    meaningful_continuity: float
    signature: str
    block_hash: str


@dataclass
class TrustChannels:
    physical: float
    observer: float
    historical: float
    consensus: float
    anchor: float
    total: float
    normalized: float


@dataclass
class KernelCycleResult:
    epoch: int
    scenario: str
    governance_mask: int
    governance_states: list[str]
    environmental_severity: float
    weighted_quorum: bool
    quorum_weight: float
    required_quorum_weight: float
    anchor_accepted: bool
    anchor_delta: float
    q_conf: float
    trust_index: float
    trust_channels: TrustChannels
    kappa_vector_mean: KappaScores
    meaningful_continuity_raw: float
    meaningful_continuity_norm: float
    meaningful_continuity: float
    continuity_gate_passed: bool
    integrity_preserved: bool
    unsafe_output_opportunity: bool
    unsafe_output_prevented: bool
    unnecessary_shutdown: bool
    raw_unsafe_output_risk: float
    gate_mc_norm_threshold: float
    gate_q_conf_threshold: float
    abort_tier: str
    hard_abort_causes: list[str]
    coherence_price: float
    coherence_spend: float
    active_nodes: int
    quarantined_nodes: list[str]
    ledger_certificate_type: str
    fused_vector: list[float]
    merkle_root: str
    block_hash: str
    opte_policy_context_hash: str
    qom_compact_payload_bits: int
    qom_compact_payload_hex: str
    hardware_register_target: dict[str, object]
    secure_enclave_vault: dict[str, object]
    cryogenic_scheduler: dict[str, object]
    reviewer_telemetry: dict[str, object]
    snapshot_frame_hex_prefix: str


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize_vector(vector: Iterable[float]) -> list[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 1e-12:
        return [1.0, 0.0, 0.0]
    return [v / norm for v in values]


def vector_distance(left: Iterable[float], right: Iterable[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def hkdf_sha256(input_key_material: bytes, info: bytes, salt: bytes = b"AEGIS_QOM_BRANCH_SALT", length: int = 32) -> bytes:
    pseudo_random_key = hmac.new(salt, input_key_material, hashlib.sha256).digest()
    output = b""
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(pseudo_random_key, previous + info + bytes([counter]), hashlib.sha256).digest()
        output += previous
        counter += 1
    return output[:length]


class AegisContinuityKernel:
    def __init__(self, config: KernelConfig | None = None, seed: int | None = 2026):
        self.config = config or KernelConfig()
        self.random = random.Random(seed)
        self.epoch = 0
        self.governance_mask = GovernanceState.NORMAL
        self.abort_latched = False
        self.recovery_validation_remaining = 0
        self.master_key = hashlib.sha256(b"aegis_continuity_kernel_master_key_v1").digest()
        self.current_key = self.master_key
        self.branch_id = "ROOT"
        self.parent_hash = "0" * 64
        self.anchor_history: list[list[float]] = []
        self.anchor_trust_memory = 1.0
        self.hard_abort_cause_mask = AbortCause.NONE
        self.last_boundary_certificate_mask = GovernanceState.NORMAL
        self.ledger: list[LedgerBlock] = []
        self.last_snapshot_frame = b""
        self.track_registry = {
            f"Q_NODE_{i}": TrackRegistryEntry(
                node_id=f"Q_NODE_{i}",
                kappa=KappaScores(node=1.0 - (0.006 * i), recon=0.98, telemetry=0.98),
            )
            for i in range(self.config.node_count)
        }

    def execute_cycle(self, telemetry_batch: list[NodeTelemetry], scenario: str = "runtime") -> KernelCycleResult:
        # Pipeline shape: ingest -> score -> govern/gate -> ledger/report.
        # The stage helpers keep the stateful orchestration narrow while the
        # stateless scoring math lives in aegis_scoring.py for direct tests.
        self.epoch += 1
        self.governance_mask = GovernanceState.CIRCUIT_ABORT if self.abort_latched else GovernanceState.NORMAL
        self.hard_abort_cause_mask = AbortCause.NONE
        if self.recovery_validation_remaining > 0:
            self.governance_mask |= GovernanceState.RECOVERY_VALIDATE

        environment, kappa_map, fused_vector, quorum_ok, quorum_weight, required_weight, active_nodes, anchor_ok, anchor_delta = self._stage_ingest_and_score(telemetry_batch)
        q_conf = self.calculate_q_conf(fused_vector, kappa_map, environment)
        kappa_vector_mean = self.calculate_kappa_vector_mean(kappa_map)
        trust_channels = self.calculate_trust_channels(
            kappa_map=kappa_map,
            environment=environment,
            quorum_weight=quorum_weight,
            required_weight=required_weight,
            anchor_ok=anchor_ok,
            anchor_delta=anchor_delta,
        )
        coherence_price, coherence_spend = self.execute_coherence_market(environment, q_conf, active_nodes)
        opte_policy_context_hash = self.calculate_opte_policy_context_hash(kappa_vector_mean)
        meaningful_continuity_raw = self.calculate_meaningful_continuity_raw(
            q_conf=q_conf,
            quorum_ok=quorum_ok,
            anchor_ok=anchor_ok,
            environmental_severity=environment.severity(),
            coherence_spend=coherence_spend,
        )
        meaningful_continuity_norm = self.normalize_meaningful_continuity(meaningful_continuity_raw)
        gate_mc_threshold, gate_q_threshold = self.resolve_gate_thresholds(scenario)
        self._stage_govern(
            telemetry_batch,
            environment,
            quorum_ok,
            anchor_ok,
            anchor_delta,
            q_conf,
            kappa_map,
        )
        continuity_gate_passed = self.evaluate_continuity_gate(
            meaningful_continuity_norm,
            q_conf,
            anchor_ok,
            gate_mc_threshold,
            gate_q_threshold,
        )
        if self.governance_mask & (
            GovernanceState.CRYPTO_SEAL
            | GovernanceState.CIRCUIT_ABORT
            | GovernanceState.HARD_ABORT
        ):
            continuity_gate_passed = False
        raw_unsafe_output_risk = self.calculate_raw_unsafe_output_risk(
            telemetry_batch=telemetry_batch,
            environment=environment,
            anchor_ok=anchor_ok,
            anchor_delta=anchor_delta,
            q_conf=q_conf,
        )
        unsafe_output_opportunity = raw_unsafe_output_risk > self.config.unsafe_output_risk_threshold
        unsafe_output_prevented = self.evaluate_unsafe_output_prevention(
            continuity_gate_passed=continuity_gate_passed,
            quorum_ok=quorum_ok,
            anchor_ok=anchor_ok,
            unsafe_output_opportunity=unsafe_output_opportunity,
        )
        integrity_preserved = (not continuity_gate_passed) and unsafe_output_prevented
        clean_recoverable_cycle = (
            (not unsafe_output_opportunity)
            and quorum_ok
            and anchor_ok
            and environment.severity() < self.config.storm_threshold
            and telemetry_batch
            and all(not item.suspected_attack for item in telemetry_batch)
            and all(item.crypto_valid for item in telemetry_batch)
        )
        unnecessary_shutdown = clean_recoverable_cycle and bool(
            self.governance_mask
            & (
                GovernanceState.SOFT_ABORT
                | GovernanceState.HARD_ABORT
            )
        )
        abort_tier, compact_qom_payload, snapshot_frame, block = self._stage_ledger(
            fused_vector,
            q_conf,
            meaningful_continuity_norm,
            meaningful_continuity_raw,
            raw_unsafe_output_risk,
            trust_channels.normalized,
            environment,
            opte_policy_context_hash,
        )
        hardware_register_target = self.build_hardware_register_target(environment)
        secure_enclave_vault = self.build_secure_enclave_vault(block)
        cryogenic_scheduler = self.build_cryogenic_scheduler(telemetry_batch, environment, active_nodes)
        reviewer_telemetry = self.build_reviewer_telemetry(telemetry_batch, environment, compact_qom_payload)

        quarantined_nodes = [
            node_id for node_id, entry in self.track_registry.items() if self.is_quarantined(entry)
        ]
        return KernelCycleResult(
            epoch=self.epoch,
            scenario=scenario,
            governance_mask=int(self.governance_mask),
            governance_states=self.describe_governance_states(),
            environmental_severity=environment.severity(),
            weighted_quorum=quorum_ok,
            quorum_weight=quorum_weight,
            required_quorum_weight=required_weight,
            anchor_accepted=anchor_ok,
            anchor_delta=anchor_delta,
            q_conf=q_conf,
            trust_index=trust_channels.normalized,
            trust_channels=trust_channels,
            kappa_vector_mean=kappa_vector_mean,
            meaningful_continuity_raw=meaningful_continuity_raw,
            meaningful_continuity_norm=meaningful_continuity_norm,
            meaningful_continuity=meaningful_continuity_raw,
            continuity_gate_passed=continuity_gate_passed,
            integrity_preserved=integrity_preserved,
            unsafe_output_opportunity=unsafe_output_opportunity,
            unsafe_output_prevented=unsafe_output_prevented,
            unnecessary_shutdown=unnecessary_shutdown,
            raw_unsafe_output_risk=raw_unsafe_output_risk,
            gate_mc_norm_threshold=gate_mc_threshold,
            gate_q_conf_threshold=gate_q_threshold,
            abort_tier=abort_tier,
            hard_abort_causes=self.describe_abort_causes(),
            coherence_price=coherence_price,
            coherence_spend=coherence_spend,
            active_nodes=active_nodes,
            quarantined_nodes=quarantined_nodes,
            ledger_certificate_type=block.certificate_type,
            fused_vector=fused_vector,
            merkle_root=block.merkle_root,
            block_hash=block.block_hash,
            opte_policy_context_hash=opte_policy_context_hash,
            qom_compact_payload_bits=len(compact_qom_payload) * 8,
            qom_compact_payload_hex=compact_qom_payload.hex(),
            hardware_register_target=hardware_register_target,
            secure_enclave_vault=secure_enclave_vault,
            cryogenic_scheduler=cryogenic_scheduler,
            reviewer_telemetry=reviewer_telemetry,
            snapshot_frame_hex_prefix=snapshot_frame[:24].hex(),
        )

    def _stage_ingest_and_score(
        self,
        telemetry_batch: list[NodeTelemetry],
    ) -> tuple[EnvironmentVector, dict[str, KappaScores], list[float], bool, float, float, int, bool, float]:
        environment = self.ingest_telemetry(telemetry_batch)
        kappa_map = self.recompute_kappa(telemetry_batch)
        projected = self.kinetic_projection(telemetry_batch)
        unwrapped = self.manifold_unwrap(projected)
        estimated_vectors = self.estimate_state(telemetry_batch, kappa_map, unwrapped)
        fused_vector, quorum_ok, quorum_weight, required_weight, active_nodes = self.verify_quorum(estimated_vectors, kappa_map)
        anchor_ok, anchor_delta = self.cross_check_anchor(fused_vector, environment)
        return environment, kappa_map, fused_vector, quorum_ok, quorum_weight, required_weight, active_nodes, anchor_ok, anchor_delta

    def _stage_govern(
        self,
        telemetry_batch: list[NodeTelemetry],
        environment: EnvironmentVector,
        quorum_ok: bool,
        anchor_ok: bool,
        anchor_delta: float,
        q_conf: float,
        kappa_map: dict[str, KappaScores],
    ) -> None:
        self.state_governor(
            telemetry_batch=telemetry_batch,
            environment=environment,
            quorum_ok=quorum_ok,
            anchor_ok=anchor_ok,
            anchor_delta=anchor_delta,
            q_conf=q_conf,
        )
        if self.governance_mask & GovernanceState.CIRCUIT_ABORT:
            self.abort_latched = True
        self.release_recovered_quarantines(kappa_map, environment, anchor_ok)
        self.advance_recovery_validation(anchor_ok, quorum_ok, environment)

    def _stage_ledger(
        self,
        fused_vector: list[float],
        q_conf: float,
        meaningful_continuity_norm: float,
        meaningful_continuity_raw: float,
        raw_unsafe_output_risk: float,
        trust_index: float,
        environment: EnvironmentVector,
        opte_policy_context_hash: str,
    ) -> tuple[str, bytes, bytes, LedgerBlock]:
        abort_tier = self.resolve_abort_tier()
        compact_qom_payload = self.emit_compact_qom_payload(
            q_conf=q_conf,
            meaningful_continuity_norm=meaningful_continuity_norm,
            raw_unsafe_output_risk=raw_unsafe_output_risk,
            trust_index=trust_index,
            opte_policy_context_hash=opte_policy_context_hash,
        )
        snapshot_frame = self.emit_snapshot(fused_vector, q_conf, meaningful_continuity_raw, environment, opte_policy_context_hash)
        block = self.write_ledger(snapshot_frame, fused_vector, meaningful_continuity_raw)
        return abort_tier, compact_qom_payload, snapshot_frame, block

    def ingest_telemetry(self, telemetry_batch: list[NodeTelemetry]) -> EnvironmentVector:
        if not telemetry_batch:
            return EnvironmentVector(1.0, 1.0, 1.0, 1.0, 1.0)
        return EnvironmentVector(
            thermal=statistics.fmean(item.environment.thermal for item in telemetry_batch),
            electromagnetic=statistics.fmean(item.environment.electromagnetic for item in telemetry_batch),
            voltage=statistics.fmean(item.environment.voltage for item in telemetry_batch),
            radiation=statistics.fmean(item.environment.radiation for item in telemetry_batch),
            latency=statistics.fmean(item.environment.latency for item in telemetry_batch),
        )

    def recompute_kappa(self, telemetry_batch: list[NodeTelemetry]) -> dict[str, KappaScores]:
        kappa_map = {}
        for telemetry in telemetry_batch:
            entry = self.track_registry[telemetry.node_id]
            environmental_quality = 1.0 - telemetry.environment.severity()
            acceleration_penalty = clamp(abs(telemetry.phase_acceleration) / 10.0)
            phase_stability = 1.0 - acceleration_penalty
            signal_quality = clamp(1.0 - abs(telemetry.signal_mu - 0.35))
            attack_penalty = 0.34 if telemetry.suspected_attack else 0.0
            crypto_penalty = 0.22 if not telemetry.crypto_valid else 0.0

            entry.wear_index = clamp(entry.wear_index + 0.0008, 0.0, 0.35)
            entry.kappa = KappaScores(
                node=clamp(entry.kappa.node - entry.wear_index * 0.001 - attack_penalty - crypto_penalty),
                recon=clamp((0.62 * phase_stability) + (0.38 * signal_quality) - attack_penalty),
                telemetry=clamp(environmental_quality - attack_penalty - crypto_penalty),
            )
            kappa_map[telemetry.node_id] = entry.kappa
        return kappa_map

    def kinetic_projection(self, telemetry_batch: list[NodeTelemetry]) -> dict[str, float]:
        projected = {}
        for telemetry in telemetry_batch:
            projected_phase = (
                telemetry.raw_phase
                + telemetry.phase_velocity * self.config.epoch_seconds
                + 0.5 * telemetry.phase_acceleration * (self.config.epoch_seconds**2)
            )
            if abs(telemetry.phase_acceleration) > self.config.phase_hold_acceleration_threshold:
                self.governance_mask |= GovernanceState.PHASE_HOLD
            projected[telemetry.node_id] = projected_phase
        return projected

    def manifold_unwrap(self, projected_phases: dict[str, float]) -> dict[str, float]:
        """Lift wrapped phase samples onto a continuous phase track.

        This is the signal-processing core behind the project's "Riemann"
        language. Operationally it is the standard wrapped-delta phase
        unwrapping step used in PLL-style tracking loops and Itoh-style phase
        unwrapping: only the incremental delta is wrapped into [-pi, pi), then
        accumulated onto the prior unwrapped track.
        """
        unwrapped = {}
        for node_id, projected_phase in projected_phases.items():
            entry = self.track_registry[node_id]
            delta_phase = projected_phase - entry.last_raw_phase
            wrapped_delta = ((delta_phase + math.pi) % (2.0 * math.pi)) - math.pi
            entry.unwrapped_phase += wrapped_delta
            entry.last_raw_phase = projected_phase
            unwrapped[node_id] = entry.unwrapped_phase
        return unwrapped

    def estimate_state(
        self,
        telemetry_batch: list[NodeTelemetry],
        kappa_map: dict[str, KappaScores],
        unwrapped_phases: dict[str, float],
    ) -> dict[str, list[float]]:
        estimates = {}
        for telemetry in telemetry_batch:
            phase = unwrapped_phases[telemetry.node_id]
            vector = normalize_vector(telemetry.bloch_vector)
            phase_hint = [math.cos(phase) * 0.7071, math.sin(phase) * 0.7071, 0.7071]
            kappa = kappa_map[telemetry.node_id].active
            estimates[telemetry.node_id] = normalize_vector(
                [
                    (vector[0] * kappa) + (phase_hint[0] * (1.0 - kappa)),
                    (vector[1] * kappa) + (phase_hint[1] * (1.0 - kappa)),
                    (vector[2] * kappa) + (phase_hint[2] * (1.0 - kappa)),
                ]
            )
        return estimates

    def verify_quorum(
        self,
        estimated_vectors: dict[str, list[float]],
        kappa_map: dict[str, KappaScores],
    ) -> tuple[list[float], bool, float, float, int]:
        # Weighted Byzantine isolation is grounded in classical BFT assumptions:
        # consensus must keep enough independent physical participants while
        # filtering outliers by trust-weighted distance from a medoid reference.
        # The implementation preserves a minimum physical node count in addition
        # to trust weight, avoiding a single high-score node becoming a quorum.
        active_items = [
            (node_id, vector, kappa_map[node_id].active)
            for node_id, vector in estimated_vectors.items()
            if not self.is_quarantined(self.track_registry[node_id])
        ]
        if not active_items:
            return [1.0, 0.0, 0.0], False, 0.0, 0.0, 0

        provisional = self.weighted_medoid_reference(active_items)
        filtered = [
            item for item in active_items if vector_distance(item[1], provisional) <= 0.55 and item[2] >= 0.35
        ]
        for node_id, vector, active_kappa in active_items:
            if vector_distance(vector, provisional) > 0.90 or active_kappa < 0.25:
                self.quarantine_node(node_id)
                self.governance_mask |= GovernanceState.SECURITY_LOCKDOWN

        possible_weight = sum(kappa.active for kappa in kappa_map.values())
        quorum_weight = sum(item[2] for item in filtered)
        required_weight = possible_weight * self.config.quorum_weight_ratio
        quorum_ok = quorum_weight >= required_weight and len(filtered) >= self.config.min_physical_quorum_nodes
        if not quorum_ok:
            self.governance_mask |= GovernanceState.SECURITY_LOCKDOWN
            return [1.0, 0.0, 0.0], False, quorum_weight, required_weight, len(filtered)
        return self.weighted_average_vector(filtered), True, quorum_weight, required_weight, len(filtered)

    def weighted_average_vector(self, items: list[tuple[str, list[float], float]]) -> list[float]:
        total_weight = max(1e-12, sum(weight for _, _, weight in items))
        return normalize_vector(
            [
                sum(vector[axis] * weight for _, vector, weight in items) / total_weight
                for axis in range(3)
            ]
        )

    def weighted_medoid_reference(self, items: list[tuple[str, list[float], float]]) -> list[float]:
        best_item = min(
            items,
            key=lambda candidate: sum(
                vector_distance(candidate[1], other_vector) * other_weight
                for _, other_vector, other_weight in items
            ),
        )
        return best_item[1]

    def cross_check_anchor(self, fused_vector: list[float], environment: EnvironmentVector) -> tuple[bool, float]:
        if not self.anchor_history:
            self.anchor_history.append(fused_vector)
            return True, 0.0

        window = self.anchor_history[-self.config.anchor_window :]
        smoothed_anchor = normalize_vector(
            [
                statistics.fmean(anchor[axis] for anchor in window)
                for axis in range(3)
            ]
        )
        anchor_delta = vector_distance(fused_vector, smoothed_anchor)
        accepted = anchor_delta <= self.config.anchor_threshold and environment.severity() <= self.config.weather_clearance_threshold
        if accepted:
            self.anchor_history.append(fused_vector)
        else:
            self.governance_mask |= GovernanceState.ANCHOR_DISPUTE
        return accepted, anchor_delta

    def calculate_q_conf(
        self,
        fused_vector: list[float],
        kappa_map: dict[str, KappaScores],
        environment: EnvironmentVector,
    ) -> float:
        return calculate_q_conf_score(fused_vector, [kappa.active for kappa in kappa_map.values()], environment.severity())

    def calculate_kappa_vector_mean(self, kappa_map: dict[str, KappaScores]) -> KappaScores:
        if not kappa_map:
            return KappaScores(node=0.0, recon=0.0, telemetry=0.0)
        return KappaScores(
            node=statistics.fmean(kappa.node for kappa in kappa_map.values()),
            recon=statistics.fmean(kappa.recon for kappa in kappa_map.values()),
            telemetry=statistics.fmean(kappa.telemetry for kappa in kappa_map.values()),
        )

    def calculate_trust_channels(
        self,
        kappa_map: dict[str, KappaScores],
        environment: EnvironmentVector,
        quorum_weight: float,
        required_weight: float,
        anchor_ok: bool,
        anchor_delta: float,
    ) -> TrustChannels:
        physical = clamp(1.0 - environment.severity())
        observer = statistics.fmean(kappa.node for kappa in kappa_map.values()) if kappa_map else 0.0
        historical = clamp(len(self.anchor_history) / max(1, self.config.anchor_window))
        consensus = clamp(quorum_weight / max(required_weight, 1e-12))
        if anchor_ok:
            immediate_anchor = clamp(1.0 - (anchor_delta / max(self.config.anchor_threshold, 1e-12)))
            self.anchor_trust_memory = clamp((0.70 * self.anchor_trust_memory) + (0.30 * immediate_anchor))
        else:
            self.anchor_trust_memory = clamp(self.anchor_trust_memory * math.exp(-self.config.anchor_decay_lambda))
        anchor = self.anchor_trust_memory
        total = physical * observer * historical * consensus * anchor
        return TrustChannels(
            physical=physical,
            observer=observer,
            historical=historical,
            consensus=consensus,
            anchor=anchor,
            total=total,
            normalized=total,
        )

    def execute_coherence_market(
        self,
        environment: EnvironmentVector,
        q_conf: float,
        active_nodes: int,
    ) -> tuple[float, float]:
        congestion = clamp(environment.severity() + (1.0 - q_conf) + max(0, self.config.node_count - active_nodes) * 0.03)
        price = 1.0 + (8.0 * congestion * congestion)
        priority_bid = 1.6 if self.governance_mask & (GovernanceState.SECURITY_LOCKDOWN | GovernanceState.ANCHOR_DISPUTE) else 1.0
        mission_priority = 1.5 if self.governance_mask & (GovernanceState.SECURITY_LOCKDOWN | GovernanceState.CRYPTO_SEAL) else 1.0
        continuity_bid = 1.0 + (1.0 - q_conf)
        spend = min(self.config.coherence_budget, active_nodes * price * priority_bid * mission_priority * continuity_bid)
        return price, spend

    def calculate_meaningful_continuity_raw(
        self,
        q_conf: float,
        quorum_ok: bool,
        anchor_ok: bool,
        environmental_severity: float,
        coherence_spend: float,
    ) -> float:
        adaptation = 0.88 if self.governance_mask != GovernanceState.NORMAL else 0.72
        history = clamp(len(self.anchor_history) / max(1, self.config.anchor_window))
        confidence = q_conf
        recovery = 1.0 if quorum_ok and anchor_ok else 0.24
        distribution = clamp(self.config.node_count / 12.0)
        entropy = environmental_severity
        latency = environmental_severity * 0.35
        disturbance = clamp(coherence_spend / max(1.0, self.config.coherence_budget))
        numerator = adaptation + history + confidence + recovery + distribution
        denominator = max(0.05, entropy + latency + disturbance)
        continuity = numerator / denominator
        if not quorum_ok or not anchor_ok:
            continuity *= 0.22
        return continuity

    def normalize_meaningful_continuity(self, meaningful_continuity_raw: float) -> float:
        return normalize_meaningful_continuity_score(meaningful_continuity_raw, self.config.mc_raw_normalization_target)

    def resolve_gate_thresholds(self, scenario: str) -> tuple[float, float]:
        return resolve_gate_thresholds_for_scenario(
            scenario,
            (self.config.mc_norm_success_threshold, self.config.q_conf_success_threshold),
            (self.config.storm_mc_norm_success_threshold, self.config.storm_q_conf_success_threshold),
            (self.config.adversarial_mc_norm_success_threshold, self.config.adversarial_q_conf_success_threshold),
        )

    def evaluate_continuity_gate(
        self,
        meaningful_continuity_norm: float,
        q_conf: float,
        anchor_ok: bool,
        mc_threshold: float,
        q_conf_threshold: float,
    ) -> bool:
        return (
            meaningful_continuity_norm >= mc_threshold
            and q_conf >= q_conf_threshold
            and anchor_ok
        )

    def calculate_raw_unsafe_output_risk(
        self,
        telemetry_batch: list[NodeTelemetry],
        environment: EnvironmentVector,
        anchor_ok: bool,
        anchor_delta: float,
        q_conf: float,
    ) -> float:
        if not telemetry_batch:
            return 1.0
        attack_ratio = statistics.fmean(1.0 if item.suspected_attack else 0.0 for item in telemetry_batch)
        crypto_ratio = statistics.fmean(0.0 if item.crypto_valid else 1.0 for item in telemetry_batch)
        accel_risk = clamp(
            max(abs(item.phase_acceleration) for item in telemetry_batch)
            / max(1e-12, self.config.phase_hold_acceleration_threshold)
        )
        anchor_risk = 0.0 if anchor_ok else clamp(anchor_delta / max(1e-12, self.config.anchor_threshold))
        confidence_risk = 1.0 - q_conf
        return max(environment.severity(), attack_ratio, crypto_ratio, accel_risk, anchor_risk, confidence_risk)

    def evaluate_unsafe_output_prevention(
        self,
        continuity_gate_passed: bool,
        quorum_ok: bool,
        anchor_ok: bool,
        unsafe_output_opportunity: bool,
    ) -> bool:
        if not unsafe_output_opportunity:
            return True
        if continuity_gate_passed:
            return True
        fail_closed_mask = (
            GovernanceState.STORM_PROTECT
            | GovernanceState.PHASE_HOLD
            | GovernanceState.ANCHOR_DISPUTE
            | GovernanceState.CRYPTO_SEAL
            | GovernanceState.CIRCUIT_ABORT
            | GovernanceState.SECURITY_LOCKDOWN
            | GovernanceState.RECOVERY_VALIDATE
            | GovernanceState.SOFT_ABORT
            | GovernanceState.HARD_ABORT
        )
        return bool(self.governance_mask & fail_closed_mask) or not quorum_ok or not anchor_ok

    def resolve_abort_tier(self) -> str:
        if self.governance_mask & GovernanceState.HARD_ABORT:
            return "HARD_ABORT"
        if self.governance_mask & GovernanceState.SOFT_ABORT:
            return "SOFT_ABORT"
        if self.governance_mask & GovernanceState.CIRCUIT_ABORT:
            return "CIRCUIT_ABORT"
        return "NONE"

    def describe_abort_causes(self) -> list[str]:
        if self.hard_abort_cause_mask == AbortCause.NONE:
            return []
        return [
            cause.name
            for cause in AbortCause
            if cause != AbortCause.NONE and self.hard_abort_cause_mask & cause
        ]

    def calculate_opte_policy_context_hash(self, kappa_vector_mean: KappaScores) -> str:
        payload = {
            "governance_mask": int(self.governance_mask),
            "kappa_vector_mean": {
                "node": kappa_vector_mean.node,
                "recon": kappa_vector_mean.recon,
                "telemetry": kappa_vector_mean.telemetry,
            },
            "ledger_parent_root": self.parent_hash,
            "branch_id": self.branch_id,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def state_governor(
        self,
        telemetry_batch: list[NodeTelemetry],
        environment: EnvironmentVector,
        quorum_ok: bool,
        anchor_ok: bool,
        anchor_delta: float,
        q_conf: float,
    ) -> None:
        attack_ratio = statistics.fmean(1.0 if item.suspected_attack else 0.0 for item in telemetry_batch) if telemetry_batch else 1.0
        max_acceleration = max((abs(item.phase_acceleration) for item in telemetry_batch), default=0.0)
        if environment.severity() >= self.config.storm_threshold:
            self.governance_mask |= GovernanceState.STORM_PROTECT
        if attack_ratio >= self.config.attack_threshold:
            self.governance_mask |= GovernanceState.SECURITY_LOCKDOWN
        if telemetry_batch and any(not item.crypto_valid for item in telemetry_batch):
            self.governance_mask |= GovernanceState.CRYPTO_SEAL
        if max_acceleration > self.config.phase_hold_acceleration_threshold:
            self.governance_mask |= GovernanceState.PHASE_HOLD
            if (
                max_acceleration <= self.config.phase_hold_acceleration_threshold * 1.25
                and quorum_ok
                and anchor_ok
                and telemetry_batch
                and all(item.crypto_valid for item in telemetry_batch)
            ):
                self.governance_mask |= GovernanceState.SOFT_ABORT

        holdover_error = (
            max(abs(item.phase_velocity) for item in telemetry_batch)
            * self.config.epoch_seconds
            + 0.5
            * max(abs(item.phase_acceleration) for item in telemetry_batch)
            * (self.config.epoch_seconds**2)
            + (1.0 - q_conf) * math.sqrt(self.config.epoch_seconds)
        ) if telemetry_batch else 1.0
        backaction = max(
            (item.signal_mu**2) * ((1.0 - item.environment.severity()) ** 2) * self.config.epoch_seconds
            for item in telemetry_batch
        ) if telemetry_batch else 1.0
        unresolved_fail_closed = (
            not quorum_ok
            or not anchor_ok
            or holdover_error > self.config.epsilon_p_max
            or backaction > self.config.theta_backaction
            or anchor_delta > self.config.anchor_threshold * 1.8
        )
        if unresolved_fail_closed:
            self.governance_mask |= GovernanceState.CIRCUIT_ABORT
            if telemetry_batch and any(not item.crypto_valid for item in telemetry_batch):
                self.hard_abort_cause_mask |= AbortCause.CRYPTO_FAILURE
            if not anchor_ok or anchor_delta > self.config.anchor_threshold * 1.8:
                self.hard_abort_cause_mask |= AbortCause.ANCHOR_DRIFT
            if not quorum_ok:
                self.hard_abort_cause_mask |= AbortCause.QUORUM_COLLAPSE
            if holdover_error > self.config.epsilon_p_max:
                self.hard_abort_cause_mask |= AbortCause.HOLDOVER_BREACH
            if backaction > self.config.theta_backaction:
                self.hard_abort_cause_mask |= AbortCause.BACKACTION_BREACH
            if environment.severity() >= self.config.weather_clearance_threshold:
                self.hard_abort_cause_mask |= AbortCause.WEATHER_BREACH
            soft_recoverable = (
                quorum_ok
                and anchor_delta <= self.config.anchor_threshold * 1.8
                and telemetry_batch
                and all(item.crypto_valid for item in telemetry_batch)
                and holdover_error <= self.config.epsilon_p_max * 1.25
            )
            if soft_recoverable:
                self.governance_mask |= GovernanceState.SOFT_ABORT
            else:
                self.governance_mask |= GovernanceState.HARD_ABORT

    def is_quarantined(self, entry: TrackRegistryEntry) -> bool:
        return entry.quarantined

    def quarantine_node(self, node_id: str) -> None:
        entry = self.track_registry[node_id]
        entry.quarantined = True

    def release_recovered_quarantines(
        self,
        kappa_map: dict[str, KappaScores],
        environment: EnvironmentVector,
        anchor_ok: bool,
    ) -> None:
        for node_id, entry in self.track_registry.items():
            if (
                entry.quarantined
                and anchor_ok
                and environment.severity() <= self.config.weather_clearance_threshold
                and kappa_map.get(node_id, entry.kappa).active >= self.config.quarantine_release_kappa
            ):
                entry.quarantined = False

    def authorize_recovery_validation(self) -> None:
        self.abort_latched = False
        self.recovery_validation_remaining = self.config.recovery_validation_cycles

    def advance_recovery_validation(self, anchor_ok: bool, quorum_ok: bool, environment: EnvironmentVector) -> None:
        if self.recovery_validation_remaining <= 0:
            return
        rolling_confidence = clamp(len(self.anchor_history) / max(1, self.config.anchor_window))
        if (
            anchor_ok
            and quorum_ok
            and environment.severity() <= self.config.weather_clearance_threshold
            and rolling_confidence >= 0.80
            and self.anchor_trust_memory >= 0.75
        ):
            self.recovery_validation_remaining -= 1
        else:
            self.recovery_validation_remaining = self.config.recovery_validation_cycles

    def build_hardware_register_model(self, environment: EnvironmentVector) -> dict[str, object]:
        """Return a documentation-only software register-map model, not deployed RTL."""
        gate_open = not bool(
            self.governance_mask
            & (GovernanceState.HARD_ABORT | GovernanceState.CIRCUIT_ABORT | GovernanceState.CRYPTO_SEAL)
        )
        timing_window_ns = max(20, int((self.config.epoch_seconds * 1_000_000_000) / 1024))
        return {
            "target": "SOFTWARE_REGISTER_MAP_PROPOSAL",
            "layer": "WORKLOAD_CONTROL_PLANE_MODEL",
            "implementation_status": "conceptual_software_mapping_not_rtl",
            "claim_boundary": "This is a software-side register-map sketch for future integration review, not synthesized RTL, FPGA firmware, ASIC logic, or hardware control.",
            "gate_open": gate_open,
            "o_quantization_window_ns": timing_window_ns,
            "environment_severity": environment.severity(),
            "register_width_bits": 32,
            "address_map": {
                "0x0000": "GATE_CONTROL_G_T",
                "0x0004": "GOVERNANCE_BITMASK",
                "0x0008": "O_QUANTIZATION_TIMER_NS",
                "0x000C": "QOM_FRAME_PTR",
                "0x0010": "ANCHOR_STATUS",
                "0x0014": "CRYO_THERMAL_INDEX",
                "0x0018": "ENCLAVE_MAILBOX",
            },
            "verilog_stub": (
                "// NON-SYNTHESIZABLE DOCUMENTATION STUB ONLY; not validated RTL.\n"
                "always_ff @(posedge clk) gate_control <= !hard_abort && !circuit_abort && !crypto_seal;"
            ),
        }

    def build_hardware_register_target(self, environment: EnvironmentVector) -> dict[str, object]:
        return self.build_hardware_register_model(environment)

    def build_secure_enclave_vault(self, block: LedgerBlock) -> dict[str, object]:
        delayed_erasure_pending = bool(
            self.governance_mask
            & (GovernanceState.SECURITY_LOCKDOWN | GovernanceState.HARD_ABORT | GovernanceState.CRYPTO_SEAL)
        )
        return {
            "architecture": "SOFTWARE_HSM_STYLE_KEY_LINEAGE_MODEL",
            "implementation_status": "software_simulation_not_secure_enclave_hardware",
            "ratchet": "HKDF_SHA256_BRANCH_ISOLATED",
            "branch_id": self.branch_id,
            "block_hash": block.block_hash,
            "active_key_fingerprint": hashlib.sha256(self.current_key).hexdigest()[:16],
            "delayed_erasure_pending": delayed_erasure_pending,
            "isolated_register_banks": [
                "BRANCH_KEY_REGS",
                "FORENSIC_COMMIT_CAPSULE",
                "DELAYED_ERASURE_QUEUE",
                "ENCLAVE_ONLY_PARENT_SECRET",
            ],
        }

    def build_cryogenic_scheduler(
        self,
        telemetry_batch: list[NodeTelemetry],
        environment: EnvironmentVector,
        active_nodes: int,
    ) -> dict[str, object]:
        mean_mu = statistics.fmean(item.signal_mu for item in telemetry_batch) if telemetry_batch else 1.0
        pulse_load = active_nodes * 0.018
        observer_load = (mean_mu**2) * 5.2
        weather_load = environment.severity() * 1.4
        thermal_mw = pulse_load + observer_load + weather_load
        saturation = thermal_mw / max(1e-12, self.config.cryo_thermal_budget_mw)
        if saturation >= self.config.cryo_lane_spread_threshold:
            action = "SPREAD_LOAD_ACROSS_ALT_LANES"
        elif self.governance_mask & GovernanceState.STORM_PROTECT:
            action = "THROTTLE_OBSERVER_POLLING"
        else:
            action = "NOMINAL"
        return {
            "scheduler": "CRYOGENIC_AWARE_COST_PROXY",
            "implementation_status": "software_cost_model_not_refrigerator_control",
            "p_therm_mw": thermal_mw,
            "thermal_budget_mw": self.config.cryo_thermal_budget_mw,
            "saturation": clamp(saturation),
            "action": action,
            "active_nodes": active_nodes,
            "mean_observer_mu": mean_mu,
        }

    def build_reviewer_telemetry(
        self,
        telemetry_batch: list[NodeTelemetry],
        environment: EnvironmentVector,
        compact_qom_payload: bytes,
    ) -> dict[str, object]:
        # The reported compression ratio models high-utility telemetry trimming:
        # low-value floating-point tails and repeated sensor noise are discarded
        # before archival. This is a lossy telemetry-compression model, not a
        # claim of reversible physical-state compression.
        if telemetry_batch:
            phases = [item.raw_phase for item in telemetry_batch]
            phase_mean = statistics.fmean(phases)
            rmse_phase = math.sqrt(statistics.fmean((phase - phase_mean) ** 2 for phase in phases))
            velocities = [item.phase_velocity for item in telemetry_batch]
            jitter_ns = statistics.pstdev(velocities) * self.config.epoch_seconds * 1_000_000
            kappas = [self.track_registry[item.node_id].kappa.active for item in telemetry_batch]
        else:
            rmse_phase = 0.0
            jitter_ns = 0.0
            kappas = [1.0]
        total = max(1e-12, sum(kappas))
        probabilities = [max(1e-12, item / total) for item in kappas]
        entropy_bits = -sum(prob * math.log2(prob) for prob in probabilities)
        raw_payload = {
            "epoch": self.epoch,
            "telemetry": [
                {
                    "node_id": item.node_id,
                    "raw_phase": item.raw_phase,
                    "phase_velocity": item.phase_velocity,
                    "phase_acceleration": item.phase_acceleration,
                    "bloch_vector": item.bloch_vector,
                    "signal_mu": item.signal_mu,
                    "environment": asdict(item.environment),
                    "suspected_attack": item.suspected_attack,
                    "crypto_valid": item.crypto_valid,
                    "mission_priority": item.mission_priority,
                }
                for item in telemetry_batch
            ],
        }
        ratio, raw_bytes, compact_bytes = compact_payload_compression_ratio(raw_payload, len(compact_qom_payload))
        return {
            "rmse_phase_skew_rad": rmse_phase,
            "packet_transmission_jitter_ns": jitter_ns,
            "shannon_entropy_bound_bits": entropy_bits,
            "data_compression_ratio": ratio,
            "data_compression_ratio_method": "raw_telemetry_json_bytes / compact_qom_payload_bytes",
            "raw_telemetry_payload_bytes": raw_bytes,
            "packet_latency_bound_ms": environment.latency * 50.0,
            "qom_compact_payload_bytes": compact_bytes,
        }

    def emit_compact_qom_payload(
        self,
        q_conf: float,
        meaningful_continuity_norm: float,
        raw_unsafe_output_risk: float,
        trust_index: float,
        opte_policy_context_hash: str,
    ) -> bytes:
        phase_values = [entry.unwrapped_phase for entry in self.track_registry.values()]
        mean_phase = statistics.fmean(phase_values) if phase_values else 0.0
        phase_u32 = int(((mean_phase + math.pi) % (2.0 * math.pi)) / (2.0 * math.pi) * 0xFFFFFFFF)
        coherence_u16 = int(clamp(q_conf) * 0xFFFF)
        lifecycle_u16 = int((self.epoch % 0x10000))
        trust_u16 = int(clamp(trust_index) * 0xFFFF)
        backaction_u16 = int(clamp(raw_unsafe_output_risk) * 0xFFFF)
        governance_u16 = int(self.governance_mask) & 0xFFFF
        opte_u64 = int(opte_policy_context_hash[:16], 16)
        return struct.pack(
            QOM_COMPACT_STRUCT_FORMAT,
            phase_u32,
            coherence_u16,
            lifecycle_u16,
            trust_u16,
            backaction_u16,
            governance_u16,
            opte_u64,
        )

    def emit_snapshot(
        self,
        fused_vector: list[float],
        q_conf: float,
        meaningful_continuity: float,
        environment: EnvironmentVector,
        opte_policy_context_hash: str,
    ) -> bytes:
        magic = b"QOM1"
        version = 1
        header = struct.pack(
            ">4sHHIQ",
            magic,
            version,
            int(self.governance_mask),
            self.epoch,
            int(time.time_ns()),
        )
        body = struct.pack(
            ">11f",
            float(fused_vector[0]),
            float(fused_vector[1]),
            float(fused_vector[2]),
            float(q_conf),
            float(meaningful_continuity),
            float(environment.thermal),
            float(environment.electromagnetic),
            float(environment.voltage),
            float(environment.radiation),
            float(environment.latency),
            float(environment.severity()),
        )
        policy_context = bytes.fromhex(opte_policy_context_hash)
        frame = header + body + policy_context
        checksum = hashlib.sha256(frame).digest()[:16]
        audit_signature = hmac.new(self.current_key, frame + checksum, hashlib.sha256).digest()[:16]
        self.last_snapshot_frame = frame + checksum + audit_signature
        return self.last_snapshot_frame

    def write_ledger(self, snapshot_frame: bytes, fused_vector: list[float], meaningful_continuity: float) -> LedgerBlock:
        certificate_type = self.resolve_certificate_type()
        event_hashes = [
            hashlib.sha256(snapshot_frame).hexdigest(),
            hashlib.sha256(json.dumps(fused_vector, sort_keys=True).encode()).hexdigest(),
            hashlib.sha256(str(int(self.governance_mask)).encode()).hexdigest(),
            hashlib.sha256(certificate_type.encode()).hexdigest(),
        ]
        merkle_root = self.calculate_merkle_root(event_hashes)
        if self.governance_mask & GovernanceState.SECURITY_LOCKDOWN:
            self.branch_id = f"BRANCH_{self.epoch:06d}"
        info = f"{self.config.chain_id}|{self.branch_id}|{self.epoch}|{self.parent_hash}".encode()
        branch_key = hkdf_sha256(self.current_key, info)
        birth_certificate_hash = hashlib.sha256(
            json.dumps(
                {
                    "epoch": self.epoch,
                    "governance_mask": int(self.governance_mask),
                    "certificate_type": certificate_type,
                    "meaningful_continuity": meaningful_continuity,
                    "merkle_root": merkle_root,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        unsigned_header = (
            f"{self.epoch}|{self.parent_hash}|{merkle_root}|{self.branch_id}|"
            f"{certificate_type}|{birth_certificate_hash}|{int(self.governance_mask)}|{meaningful_continuity:.12f}"
        ).encode()
        signature = hmac.new(branch_key, unsigned_header, hashlib.sha256).hexdigest()
        block_hash = hashlib.sha256(unsigned_header + signature.encode()).hexdigest()
        self.current_key = hashlib.sha256(branch_key + block_hash.encode()).digest()
        self.parent_hash = block_hash
        block = LedgerBlock(
            epoch=self.epoch,
            parent_hash=self.ledger[-1].block_hash if self.ledger else "0" * 64,
            merkle_root=merkle_root,
            branch_id=self.branch_id,
            certificate_type=certificate_type,
            birth_certificate_hash=birth_certificate_hash,
            governance_mask=int(self.governance_mask),
            meaningful_continuity=meaningful_continuity,
            signature=signature,
            block_hash=block_hash,
        )
        self.ledger.append(block)
        if self.governance_mask != GovernanceState.NORMAL:
            self.last_boundary_certificate_mask = self.governance_mask
        else:
            self.last_boundary_certificate_mask = GovernanceState.NORMAL
        return block

    def resolve_certificate_type(self) -> str:
        if (
            self.governance_mask != GovernanceState.NORMAL
            and self.governance_mask == self.last_boundary_certificate_mask
        ):
            return "BOUNDARY_CERTIFICATE"
        if self.governance_mask & GovernanceState.HARD_ABORT:
            return "HARD_ABORT_CERTIFICATE"
        if self.governance_mask & GovernanceState.SOFT_ABORT:
            return "SOFT_ABORT_CERTIFICATE"
        if self.governance_mask & GovernanceState.CIRCUIT_ABORT:
            return "CIRCUIT_ABORT_CERTIFICATE"
        if self.governance_mask & GovernanceState.PHASE_HOLD:
            return "PHASE_HOLD_CERTIFICATE"
        if self.governance_mask & GovernanceState.CRYPTO_SEAL:
            return "CRYPTO_SEAL_CERTIFICATE"
        if self.governance_mask & GovernanceState.RECOVERY_VALIDATE:
            return "RECOVERY_VALIDATE_CERTIFICATE"
        if self.governance_mask != GovernanceState.NORMAL:
            return "BIRTH_CERTIFICATE"
        return "SNAPSHOT_COMMIT"

    def calculate_merkle_root(self, hashes: list[str]) -> str:
        level = hashes[:]
        while len(level) > 1:
            if len(level) % 2 == 1:
                level.append(level[-1])
            level = [
                hashlib.sha256((level[index] + level[index + 1]).encode()).hexdigest()
                for index in range(0, len(level), 2)
            ]
        return level[0]

    def describe_governance_states(self) -> list[str]:
        if self.governance_mask == GovernanceState.NORMAL:
            return ["NORMAL"]
        return [
            state.name
            for state in GovernanceState
            if state != GovernanceState.NORMAL and self.governance_mask & state
        ]


def build_nominal_telemetry(node_count: int, rng: random.Random, scenario: str) -> list[NodeTelemetry]:
    telemetry = []
    true_vector = normalize_vector([0.7071, 0.0, 0.7071])
    for index in range(node_count):
        noise = rng.uniform(-0.012, 0.012)
        environment = EnvironmentVector(0.08, 0.06, 0.05, 0.04, 0.06)
        vector = normalize_vector([true_vector[0] + noise, rng.uniform(-0.004, 0.004), true_vector[2] - noise])
        raw_phase = 0.12 + rng.uniform(-0.03, 0.03)
        phase_velocity = rng.uniform(0.08, 0.18)
        phase_acceleration = rng.uniform(-0.30, 0.30)
        signal_mu = rng.uniform(0.28, 0.38)
        suspected_attack = False
        crypto_valid = True
        mission_priority = 0.50

        if scenario == "storm":
            environment = EnvironmentVector(0.62, 0.58, 0.45, 0.66, 0.55)
            vector = normalize_vector([vector[0] - 0.10, 0.38 + noise, vector[2] - 0.08])
            signal_mu = rng.uniform(0.45, 0.65)
            mission_priority = 0.72
        elif scenario == "attack" and index in {2, 5, 7, 9}:
            vector = normalize_vector([0.0, 1.0, 0.0])
            signal_mu = 0.92
            suspected_attack = True
            mission_priority = 0.90
        elif scenario == "crypto_seal" and index in {1, 4, 8}:
            crypto_valid = False
            signal_mu = 0.78
            mission_priority = 0.95
        elif scenario == "phase_hold" and index % 3 == 0:
            phase_acceleration = 6.4 + rng.uniform(0.0, 1.0)
            mission_priority = 0.82
        elif scenario == "transient_drift" and index % 4 == 0:
            phase_acceleration = 4.7 + rng.uniform(0.0, 0.35)
            signal_mu = rng.uniform(0.38, 0.48)
            mission_priority = 0.76
        elif scenario == "anchor_dispute" and index >= node_count // 2:
            vector = normalize_vector([-0.7071, 0.0, 0.7071])
            mission_priority = 0.88
        elif scenario == "circuit_abort":
            environment = EnvironmentVector(0.94, 0.92, 0.91, 0.95, 0.90)
            phase_acceleration = 9.0
            signal_mu = 0.98
            mission_priority = 1.0

        telemetry.append(
            NodeTelemetry(
                node_id=f"Q_NODE_{index}",
                raw_phase=raw_phase,
                phase_velocity=phase_velocity,
                phase_acceleration=phase_acceleration,
                bloch_vector=vector,
                signal_mu=signal_mu,
                environment=environment,
                suspected_attack=suspected_attack,
                crypto_valid=crypto_valid,
                mission_priority=mission_priority,
            )
        )
    return telemetry


def run_deterministic_suite(seed: int = 2026) -> list[KernelCycleResult]:
    kernel = AegisContinuityKernel(seed=seed)
    scenarios = [
        "baseline",
        "storm",
        "attack",
        "crypto_seal",
        "phase_hold",
        "transient_drift",
        "anchor_dispute",
        "circuit_abort",
        "normal_after_abort",
    ]
    results = []
    for scenario in scenarios:
        telemetry_scenario = "normal" if scenario in {"baseline", "normal_after_abort"} else scenario
        telemetry = build_nominal_telemetry(kernel.config.node_count, kernel.random, telemetry_scenario)
        results.append(kernel.execute_cycle(telemetry, scenario=scenario))
    return results


def variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.pvariance(values)


def rate_or_none(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def estimate_observed_cascade_efficiencies(samples: int = 4000, seed: int = 2026) -> dict[str, float]:
    rng = random.Random(seed + 99)

    byz_raw_errors = []
    byz_filtered_errors = []
    reference = normalize_vector([0.7071, 0.0, 0.7071])
    for _ in range(samples):
        vectors = []
        weighted = []
        for index in range(12):
            if index in {2, 5, 7, 9} and rng.random() < 0.88:
                vector = normalize_vector([rng.uniform(-0.1, 0.1), 1.0, rng.uniform(-0.1, 0.1)])
                weight = rng.uniform(0.08, 0.24)
            else:
                drift = rng.uniform(-0.08, 0.08)
                vector = normalize_vector([reference[0] + drift, rng.uniform(-0.02, 0.02), reference[2] - drift])
                weight = rng.uniform(0.78, 0.99)
            vectors.append(vector)
            if weight >= 0.35 and vector_distance(vector, reference) <= 0.55:
                weighted.append((f"node_{index}", vector, weight))
        raw_centroid = normalize_vector([statistics.fmean(v[axis] for v in vectors) for axis in range(3)])
        filtered_centroid = (
            AegisContinuityKernel(seed=seed).weighted_average_vector(weighted)
            if weighted
            else [1.0, 0.0, 0.0]
        )
        byz_raw_errors.append(vector_distance(raw_centroid, reference))
        byz_filtered_errors.append(vector_distance(filtered_centroid, reference))

    taylor_raw_errors = []
    taylor_projected_errors = []
    for _ in range(samples):
        canonical_t = 0.0
        true_phase = rng.uniform(-math.pi, math.pi)
        phase_velocity = rng.uniform(-5.0, 5.0)
        phase_acceleration = rng.uniform(-8.0, 8.0)
        sample_t = rng.uniform(-0.050, 0.050)
        measured_phase = (
            true_phase
            + phase_velocity * sample_t
            + 0.5 * phase_acceleration * (sample_t**2)
            + rng.gauss(0.0, 0.005)
        )
        projected_phase = measured_phase + phase_velocity * (canonical_t - sample_t) + 0.5 * phase_acceleration * (
            canonical_t - sample_t
        ) ** 2
        taylor_raw_errors.append(abs(measured_phase - true_phase))
        taylor_projected_errors.append(abs(projected_phase - true_phase))

    wrapped_accel = []
    unwrapped_accel = []
    previous_raw = math.pi - 0.08
    previous_unwrapped = previous_raw
    previous_raw_delta = 0.0
    previous_unwrapped_delta = 0.0
    for step in range(samples):
        true_phase = math.pi - 0.08 + 0.018 * step
        raw = ((true_phase + math.pi) % (2.0 * math.pi)) - math.pi
        raw_delta = raw - previous_raw
        unwrapped_delta = ((raw - previous_raw + math.pi) % (2.0 * math.pi)) - math.pi
        previous_unwrapped += unwrapped_delta
        wrapped_accel.append(abs(raw_delta - previous_raw_delta))
        unwrapped_accel.append(abs(unwrapped_delta - previous_unwrapped_delta))
        previous_raw = raw
        previous_raw_delta = raw_delta
        previous_unwrapped_delta = unwrapped_delta

    byz_eta = 1.0 - (statistics.fmean(byz_filtered_errors) / max(1e-12, statistics.fmean(byz_raw_errors)))
    taylor_eta = 1.0 - (
        statistics.fmean(taylor_projected_errors) / max(1e-12, statistics.fmean(taylor_raw_errors))
    )
    riemann_eta = 1.0 - (variance(unwrapped_accel) / max(1e-12, variance(wrapped_accel)))

    return {
        "samples": samples,
        "eta_byzantine_observed": min(0.999, clamp(byz_eta)),
        "eta_taylor_observed": min(0.999, clamp(taylor_eta)),
        "eta_riemann_observed": min(0.999, clamp(riemann_eta)),
        "byzantine_raw_mean_error": statistics.fmean(byz_raw_errors),
        "byzantine_filtered_mean_error": statistics.fmean(byz_filtered_errors),
        "taylor_raw_mean_error": statistics.fmean(taylor_raw_errors),
        "taylor_projected_mean_error": statistics.fmean(taylor_projected_errors),
        "riemann_wrapped_accel_variance": variance(wrapped_accel),
        "riemann_unwrapped_accel_variance": variance(unwrapped_accel),
    }


def run_monte_carlo(cycles: int = 1000, seed: int = 2026) -> dict[str, object]:
    rng = random.Random(seed + 7)
    successful = 0
    integrity_preserved = 0
    unsafe_output_opportunities = 0
    unsafe_output_prevented = 0
    unnecessary_shutdowns = 0
    circuit_aborts = 0
    continuity_scores = []
    continuity_norm_scores = []
    tier_counts = {"baseline": 0, "storm": 0, "transient": 0, "adversarial": 0}
    tier_success = {"baseline": 0, "storm": 0, "transient": 0, "adversarial": 0}
    tier_integrity = {"baseline": 0, "storm": 0, "transient": 0, "adversarial": 0}
    tier_opportunities = {"baseline": 0, "storm": 0, "transient": 0, "adversarial": 0}
    tier_uop = {"baseline": 0, "storm": 0, "transient": 0, "adversarial": 0}
    tier_usr = {"baseline": 0, "storm": 0, "transient": 0, "adversarial": 0}
    scenarios = ["normal", "normal", "normal", "normal", "storm", "attack", "crypto_seal", "transient_drift", "anchor_dispute"]
    for index in range(cycles):
        kernel = AegisContinuityKernel(seed=seed + index)
        scenario = rng.choice(scenarios)
        telemetry = build_nominal_telemetry(kernel.config.node_count, rng, scenario)
        result = kernel.execute_cycle(telemetry, scenario=f"monte_carlo_{scenario}")
        ok = result.continuity_gate_passed and result.abort_tier in {"NONE", "SOFT_ABORT"}
        prevented = result.unsafe_output_prevented
        tier = (
            "storm"
            if scenario == "storm"
            else "transient"
            if scenario in {"phase_hold", "transient_drift"}
            else "adversarial"
            if scenario in {"attack", "crypto_seal", "anchor_dispute"}
            else "baseline"
        )
        if (
            tier == "adversarial"
            and result.unsafe_output_opportunity
            and rng.random() < kernel.config.adversarial_bypass_probability
        ):
            prevented = False
        successful += int(ok)
        integrity_preserved += int(result.integrity_preserved)
        unsafe_output_opportunities += int(result.unsafe_output_opportunity)
        unsafe_output_prevented += int(result.unsafe_output_opportunity and prevented)
        unnecessary_shutdowns += int(result.unnecessary_shutdown)
        circuit_aborts += int("CIRCUIT_ABORT" in result.governance_states)
        continuity_scores.append(result.meaningful_continuity)
        continuity_norm_scores.append(result.meaningful_continuity_norm)
        tier_counts[tier] += 1
        tier_success[tier] += int(ok)
        tier_integrity[tier] += int(result.integrity_preserved)
        tier_opportunities[tier] += int(result.unsafe_output_opportunity)
        tier_uop[tier] += int(result.unsafe_output_opportunity and prevented)
        tier_usr[tier] += int(result.unnecessary_shutdown)
    return {
        "cycles": cycles,
        "successful_continuity_cycles": successful,
        "empirical_continuity_yield": successful / max(1, cycles),
        "integrity_preserved_cycles": integrity_preserved,
        "integrity_preserved_yield": integrity_preserved / max(1, cycles),
        "unsafe_output_opportunities": unsafe_output_opportunities,
        "unsafe_output_prevented_cycles": unsafe_output_prevented,
        "unsafe_output_prevention_efficiency": unsafe_output_prevented / max(1, unsafe_output_opportunities),
        "unnecessary_shutdowns": unnecessary_shutdowns,
        "unnecessary_shutdown_rate": unnecessary_shutdowns / max(1, cycles),
        "unnecessary_shutdown_target": AegisContinuityKernel(seed=seed).config.target_unnecessary_shutdown_rate,
        "unnecessary_shutdown_target_met": (unnecessary_shutdowns / max(1, cycles))
        < AegisContinuityKernel(seed=seed).config.target_unnecessary_shutdown_rate,
        "tier_yields": {
            tier: tier_success[tier] / max(1, tier_counts[tier])
            for tier in tier_counts
        },
        "tier_integrity_preserved_yields": {
            tier: tier_integrity[tier] / max(1, tier_counts[tier])
            for tier in tier_counts
        },
        "tier_unsafe_output_prevention_efficiency": {
            tier: rate_or_none(tier_uop[tier], tier_opportunities[tier])
            for tier in tier_counts
        },
        "tier_unsafe_output_opportunities": tier_opportunities,
        "tier_unnecessary_shutdown_rates": {
            tier: tier_usr[tier] / max(1, tier_counts[tier])
            for tier in tier_counts
        },
        "circuit_abort_count": circuit_aborts,
        "mean_meaningful_continuity": statistics.fmean(continuity_scores),
        "min_meaningful_continuity": min(continuity_scores),
        "max_meaningful_continuity": max(continuity_scores),
        "mean_meaningful_continuity_norm": statistics.fmean(continuity_norm_scores),
        "min_meaningful_continuity_norm": min(continuity_norm_scores),
        "max_meaningful_continuity_norm": max(continuity_norm_scores),
    }


def calculate_projection_validation() -> dict[str, dict[str, float]]:
    tiers = {
        "baseline": 0.35,
        "storm": 0.58,
        "adversarial": 0.58,
    }
    eta_byzantine = 0.85
    eta_taylor = 0.90
    eta_riemann = 0.95
    projection = {}
    for tier, raw_error in tiers.items():
        aegis_error = raw_error * (1.0 - eta_byzantine) * (1.0 - eta_taylor) * (1.0 - eta_riemann)
        projection[tier] = {
            "raw_unsafe_output_risk": raw_error,
            "eta_byzantine": eta_byzantine,
            "eta_taylor": eta_taylor,
            "eta_riemann": eta_riemann,
            "projected_remaining_unsafe_output_rate": aegis_error,
            "projected_unsafe_output_prevention_efficiency": 1.0 - (aegis_error / raw_error),
        }
    projection["target_boundary"] = {
        "public_v1_target_unsafe_output_prevention_efficiency": 0.9949,
        "systemic_stretch_target_unsafe_output_prevention_efficiency": 0.9990,
        "theoretical_cascade_boundary_unsafe_output_prevention_efficiency": projection["storm"][
            "projected_unsafe_output_prevention_efficiency"
        ],
        "cascade_projection_remaining_unsafe_output_rate": projection["storm"][
            "projected_remaining_unsafe_output_rate"
        ],
    }
    return projection


def run_advanced_performance_report(seed: int = 2026) -> dict[str, object]:
    rng = random.Random(seed + 150)
    tiers = [
        {
            "name": "baseline_ingestion",
            "step_start": 1,
            "step_end": 50,
            "scenario": "normal",
            "description": "Stable planetary tracking environment with standard background noise.",
            "target_fidelity": 0.999995,
            "target_tps": 1_420_000,
            "target_meaningful_continuity": 19.11,
            "target_governance_mask": 0x00,
        },
        {
            "name": "environmental_storm",
            "step_start": 51,
            "step_end": 100,
            "scenario": "storm",
            "description": "Space-weather radiation burst with elevated phase-velocity drift.",
            "raw_hardware_error_rate": 0.58,
            "target_fidelity": 0.99412,
            "target_tps": 240_000,
            "target_meaningful_continuity": 12.45,
            "target_governance_mask": int(GovernanceState.STORM_PROTECT),
        },
        {
            "name": "adversarial_attack",
            "step_start": 101,
            "step_end": 150,
            "scenario": "attack",
            "description": "Coordinated data poisoning and weight-hijacking sweep against readout nodes.",
            "compromised_node_ratio": 0.375,
            "target_fidelity": 0.99104,
            "target_tps": 88_000,
            "target_meaningful_continuity": 8.14,
            "target_governance_mask": int(GovernanceState.STORM_PROTECT | GovernanceState.SECURITY_LOCKDOWN),
        },
    ]

    tier_reports = []
    for tier_index, tier in enumerate(tiers):
        kernel = AegisContinuityKernel(seed=seed + tier_index)
        cycle_results = []
        for step in range(int(tier["step_start"]), int(tier["step_end"]) + 1):
            scenario = str(tier["scenario"])
            if tier["name"] == "adversarial_attack" and step >= 145:
                scenario = "anchor_dispute"
            telemetry = build_nominal_telemetry(kernel.config.node_count, rng, scenario)
            result = kernel.execute_cycle(telemetry, scenario=f"{tier['name']}_step_{step}")
            cycle_results.append(result)

        successful_cycles = [
            result for result in cycle_results
            if result.continuity_gate_passed and result.abort_tier in {"NONE", "SOFT_ABORT"}
        ]
        integrity_preserved_cycles = [
            result for result in cycle_results
            if result.integrity_preserved
        ]
        unsafe_output_prevented_cycles = [
            result for result in cycle_results
            if result.unsafe_output_opportunity and result.unsafe_output_prevented
        ]
        unsafe_output_opportunity_cycles = [
            result for result in cycle_results
            if result.unsafe_output_opportunity
        ]
        unnecessary_shutdown_cycles = [
            result for result in cycle_results
            if result.unnecessary_shutdown
        ]
        quarantined_nodes = sorted({node for result in cycle_results for node in result.quarantined_nodes})
        circuit_abort_steps = [
            int(result.scenario.rsplit("_", 1)[-1])
            for result in cycle_results
            if "CIRCUIT_ABORT" in result.governance_states
        ]
        tier_reports.append(
            {
                **tier,
                "observed_success_cycles": len(successful_cycles),
                "observed_continuity_yield": len(successful_cycles) / max(1, len(cycle_results)),
                "observed_integrity_preserved_cycles": len(integrity_preserved_cycles),
                "observed_integrity_preserved_yield": len(integrity_preserved_cycles) / max(1, len(cycle_results)),
                "observed_unsafe_output_opportunities": len(unsafe_output_opportunity_cycles),
                "observed_unsafe_output_prevention_efficiency": rate_or_none(
                    len(unsafe_output_prevented_cycles),
                    len(unsafe_output_opportunity_cycles),
                ),
                "observed_unnecessary_shutdowns": len(unnecessary_shutdown_cycles),
                "observed_unnecessary_shutdown_rate": len(unnecessary_shutdown_cycles) / max(1, len(cycle_results)),
                "observed_mean_meaningful_continuity": statistics.fmean(
                    result.meaningful_continuity for result in cycle_results
                ),
                "observed_mean_meaningful_continuity_norm": statistics.fmean(
                    result.meaningful_continuity_norm for result in cycle_results
                ),
                "observed_min_meaningful_continuity": min(result.meaningful_continuity for result in cycle_results),
                "observed_max_meaningful_continuity": max(result.meaningful_continuity for result in cycle_results),
                "observed_min_meaningful_continuity_norm": min(
                    result.meaningful_continuity_norm for result in cycle_results
                ),
                "observed_max_meaningful_continuity_norm": max(
                    result.meaningful_continuity_norm for result in cycle_results
                ),
                "observed_final_governance_states": cycle_results[-1].governance_states,
                "observed_final_governance_mask": cycle_results[-1].governance_mask,
                "observed_final_certificate_type": cycle_results[-1].ledger_certificate_type,
                "observed_quarantined_nodes": quarantined_nodes,
                "observed_circuit_abort_steps": circuit_abort_steps,
            }
        )

    projection = calculate_projection_validation()["target_boundary"]
    return {
        "step_count": 150,
        "tier_count": len(tiers),
        "tier_reports": tier_reports,
        "math_note": (
            "The stated cascade 0.58 * 0.15 * 0.10 * 0.05 produces a 0.000435 "
            "remaining unsafe-output rate and 0.99925 theoretical cascade boundary. The 0.9949 value is "
            "kept as the public v1 target boundary."
        ),
        "public_v1_target_unsafe_output_prevention_efficiency": projection[
            "public_v1_target_unsafe_output_prevention_efficiency"
        ],
        "systemic_stretch_target_unsafe_output_prevention_efficiency": projection[
            "systemic_stretch_target_unsafe_output_prevention_efficiency"
        ],
        "theoretical_cascade_boundary_unsafe_output_prevention_efficiency": projection[
            "theoretical_cascade_boundary_unsafe_output_prevention_efficiency"
        ],
    }


def write_results(output_path: Path, deterministic: list[KernelCycleResult], monte_carlo: dict[str, object]) -> None:
    payload = {
        "kernel": "AegisContinuityKernel",
        "generated_at_unix": time.time(),
        "projection_validation": calculate_projection_validation(),
        "observed_cascade_efficiency_estimates": estimate_observed_cascade_efficiencies(seed=2026),
        "advanced_performance_report": run_advanced_performance_report(),
        "deterministic_suite": [asdict(result) for result in deterministic],
        "monte_carlo": monte_carlo,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def print_reviewer_summary(deterministic: list[KernelCycleResult], monte_carlo: dict[str, object], output: Path) -> None:
    final = deterministic[-1]
    telemetry = final.reviewer_telemetry
    cryo = final.cryogenic_scheduler
    hardware = final.hardware_register_target
    print("AEGIS site reliability reviewer metrics")
    print(f"cycles={monte_carlo['cycles']}")
    print(f"continuity_yield={monte_carlo['empirical_continuity_yield']:.6f}")
    print(f"integrity_preserved_yield={monte_carlo['integrity_preserved_yield']:.6f}")
    print(f"unsafe_output_opportunities={monte_carlo['unsafe_output_opportunities']}")
    print(f"uop_efficiency={monte_carlo['unsafe_output_prevention_efficiency']:.6f}")
    print(f"unnecessary_shutdown_rate={monte_carlo['unnecessary_shutdown_rate']:.6f}")
    print(f"unnecessary_shutdown_target={monte_carlo['unnecessary_shutdown_target']:.6f}")
    print(f"rmse_phase_skew_rad={telemetry['rmse_phase_skew_rad']:.6f}")
    print(f"packet_jitter_ns={telemetry['packet_transmission_jitter_ns']:.6f}")
    print(f"shannon_entropy_bound_bits={telemetry['shannon_entropy_bound_bits']:.6f}")
    print(f"data_compression_ratio={telemetry['data_compression_ratio']:.3f}")
    print(f"packet_latency_bound_ms={telemetry['packet_latency_bound_ms']:.6f}")
    print(f"cryo_p_therm_mw={cryo['p_therm_mw']:.6f}")
    print(f"cryo_saturation={cryo['saturation']:.6f}")
    print(f"register_o_quantization_window_ns={hardware['o_quantization_window_ns']}")
    print(f"gate_open={hardware['gate_open']}")
    print(f"deterministic_cases={len(deterministic)}")
    print(f"result_file={output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS continuity-kernel simulation suite")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--monte-carlo-cycles", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("aegis_kernel_results.json"))
    parser.add_argument("--reviewer-mode", action="store_true")
    args = parser.parse_args()

    deterministic = run_deterministic_suite(seed=args.seed)
    monte_carlo = run_monte_carlo(cycles=args.monte_carlo_cycles, seed=args.seed)
    write_results(args.output, deterministic, monte_carlo)

    if args.reviewer_mode:
        print_reviewer_summary(deterministic, monte_carlo, args.output)
        return

    print("AEGIS AegisContinuityKernel simulation complete")
    print(f"Deterministic cycles: {len(deterministic)}")
    print(f"Monte Carlo cycles: {monte_carlo['cycles']}")
    print(f"Empirical continuity yield: {monte_carlo['empirical_continuity_yield']:.6f}")
    print(f"Unsafe-output prevention efficiency: {monte_carlo['unsafe_output_prevention_efficiency']:.6f}")
    print(f"Results written: {args.output}")


if __name__ == "__main__":
    main()
