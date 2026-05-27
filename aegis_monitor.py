from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aegis_kernel import (
    AegisContinuityKernel,
    EnvironmentVector,
    KernelConfig,
    build_nominal_telemetry,
    calculate_projection_validation,
    estimate_observed_cascade_efficiencies,
    normalize_vector,
    run_advanced_performance_report,
    run_deterministic_suite,
    run_monte_carlo,
)


WORKSPACE = Path(__file__).resolve().parent
SNAPSHOT_DIR = WORKSPACE / "monitor_snapshots"
LATEST_QISKIT_BRIDGE: dict[str, object] | None = None
QISKIT_STOP_EVENT = threading.Event()
QISKIT_RUNNING = False


def build_monitor_payload(cycles: int = 1000, seed: int = 2026) -> dict[str, object]:
    deterministic = run_deterministic_suite(seed=seed)
    monte_carlo = run_monte_carlo(cycles=cycles, seed=seed)
    projection = calculate_projection_validation()
    observed_eta = estimate_observed_cascade_efficiencies(seed=seed)
    advanced = run_advanced_performance_report(seed=seed)
    return {
        "kernel": "AegisContinuityKernel",
        "discipline": "Quantum Site Reliability Engineering",
        "generated_at_unix": time.time(),
        "cycles": cycles,
        "seed": seed,
        "projection_validation": projection,
        "observed_cascade_efficiency_estimates": observed_eta,
        "advanced_performance_report": advanced,
        "deterministic_suite": [asdict(result) for result in deterministic],
        "monte_carlo": monte_carlo,
        "scope": {
            "uop_definition": "unsafe outputs prevented / unsafe-output opportunities",
            "continuity_gate": "M_c_norm >= scenario threshold AND Q_conf >= scenario threshold AND anchor accepted",
            "integrity_preserved": "fail-closed intervention that prevents unsafe state emission or valid ledger pollution",
            "qom": "Quantum Orchestration Middleware / Mesh control-plane frame",
            "opte": "Operational Proxy Transfer Engine with policy context hash embedded in .QOM frame",
            "hardware_register_target": "FPGA/ASIC register abstraction for Layer 1 G(t) boundary gating",
            "secure_enclave_vault": "HSM-style isolated branch-key ratchet and delayed-erasure buffer model",
            "cryogenic_scheduler": "milli-watt thermal load balancing model for cryogenic-aware execution",
            "pipeline": [
                "INGEST_TELEMETRY",
                "RECOMPUTE_KAPPA_VECTOR",
                "TAYLOR_KINETIC_PROJECTION",
                "RIEMANN_MANIFOLD_UNWRAP",
                "ESTIMATE_PROXY_STATE",
                "VERIFY_WEIGHTED_BFT_QUORUM",
                "CROSS_CHECK_ROLLING_ANCHOR",
                "STATE_GOVERNOR_BITMASK",
                "EMIT_QOM_SNAPSHOT",
                "WRITE_MERKLE_LEDGER",
            ],
        },
    }


def write_json_artifact(prefix: str, payload: dict[str, object]) -> Path:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = SNAPSHOT_DIR / f"{prefix}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def run_qiskit_bridge_payload(
    cycles: int = 6,
    shots: int = 2048,
    seed: int = 2026,
    noise_scale: float = 1.0,
    crosstalk_inject: bool = False,
    leakage_lambda: float = 0.0,
    measurement_efficiency: float = 0.82,
) -> dict[str, object]:
    from examples.qiskit_bridge import run_bridge

    results = run_bridge(
        cycles=cycles,
        shots=shots,
        seed=seed,
        noise_scale=noise_scale,
        crosstalk_inject=crosstalk_inject,
        leakage_lambda=leakage_lambda,
        measurement_efficiency=measurement_efficiency,
        stop_event=QISKIT_STOP_EVENT,
    )
    return {
        "artifact_type": "qiskit_bridge_run",
        "generated_at_unix": time.time(),
        "seed": seed,
        "cycles": cycles,
        "shots": shots,
        "stopped_by_operator": QISKIT_STOP_EVENT.is_set(),
        "bridge_parameters": {
            "noise_scale": noise_scale,
            "crosstalk_inject": crosstalk_inject,
            "leakage_lambda": leakage_lambda,
            "measurement_efficiency": measurement_efficiency,
        },
        "results": results,
        "summary": {
            "epochs": len(results),
            "mean_q_conf": sum(float(item["q_conf"]) for item in results) / max(1, len(results)),
            "gate_pass_count": sum(1 for item in results if item["continuity_gate_passed"]),
            "qom_payload_bits": sorted({item["qom_compact_payload_bits"] for item in results}),
            "final_merkle_root": results[-1]["merkle_root"] if results else None,
        },
    }


def latest_qiskit_bridge_payload() -> dict[str, object] | None:
    global LATEST_QISKIT_BRIDGE
    if LATEST_QISKIT_BRIDGE is not None:
        return LATEST_QISKIT_BRIDGE
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    candidates = sorted(
        list(SNAPSHOT_DIR.glob("qiskit_bridge_*.json")) + list(SNAPSHOT_DIR.glob("qiskit_import_*.json")),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    try:
        loaded = json.loads(candidates[0].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        LATEST_QISKIT_BRIDGE = loaded
        return LATEST_QISKIT_BRIDGE
    return None


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def normalize_hex_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_forensic_certificate(cycle: dict[str, object]) -> dict[str, object]:
    return {
        "certificate_type": "FORENSIC_BOUNDARY_BIRTH_CERTIFICATE",
        "generated_at_unix": time.time(),
        "chain_id": "AEGIS-QOM-SIMNET",
        "epoch": cycle.get("epoch"),
        "tick": cycle.get("tick"),
        "scenario": cycle.get("scenario"),
        "live_scenario": cycle.get("live_scenario"),
        "governance_mask": cycle.get("governance_mask"),
        "governance_states": cycle.get("governance_states"),
        "ledger_certificate_type": cycle.get("ledger_certificate_type"),
        "continuity_gate_passed": cycle.get("continuity_gate_passed"),
        "integrity_preserved": cycle.get("integrity_preserved"),
        "unsafe_output_opportunity": cycle.get("unsafe_output_opportunity"),
        "unsafe_output_prevented": cycle.get("unsafe_output_prevented"),
        "merkle_root": cycle.get("merkle_root"),
        "block_hash": cycle.get("block_hash"),
        "opte_policy_context_hash": cycle.get("opte_policy_context_hash"),
        "qom_compact_payload_bits": cycle.get("qom_compact_payload_bits"),
        "qom_compact_payload_hex": cycle.get("qom_compact_payload_hex"),
        "trust_index": cycle.get("trust_index"),
        "trust_channels": cycle.get("trust_channels"),
        "kappa_vector_mean": cycle.get("kappa_vector_mean"),
        "reviewer_telemetry": cycle.get("reviewer_telemetry"),
        "hardware_boundary_slippage": cycle.get("hardware_boundary_slippage"),
        "key_mutation_lineage_map": cycle.get("key_mutation_lineage_map"),
        "energy_efficiency": cycle.get("energy_efficiency"),
        "quantum_ingestion_telemetry": cycle.get("quantum_ingestion_telemetry"),
        "pulse_controls": cycle.get("pulse_controls"),
        "relativistic_clock_compensation": cycle.get("relativistic_clock_compensation"),
        "zne_tuning": cycle.get("zne_tuning"),
        "rtos_scheduler_diagnostics": cycle.get("rtos_scheduler_diagnostics"),
    }


def list_artifacts() -> list[dict[str, object]]:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    artifacts = []
    for path in sorted(SNAPSHOT_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        artifacts.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_unix": stat.st_mtime,
            }
        )
    return artifacts[:25]


def build_health_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "monitor": "AEGIS Q-SRE Monitor",
        "url": "http://127.0.0.1:8765",
        "controls": {
            "cycles_input": True,
            "seed_input": True,
            "disruption_injection_dropdown": True,
            "spoof_percentage_input": True,
            "pid_tuning_sliders": True,
            "theta_backaction_slider": True,
            "anchor_decay_slider": True,
            "omega_drive_slider": True,
            "innovation_eta_slider": True,
            "rb_interleave_toggle": True,
            "zne_lambda_slider": True,
            "qiskit_noise_scale_slider": True,
            "qem_calibration_toggle": True,
            "qiskit_crosstalk_injection_toggle": True,
            "qiskit_leakage_lambda_slider": True,
            "qiskit_measurement_efficiency_slider": True,
            "run_qiskit_bridge_button": True,
            "stop_qiskit_bridge_button": True,
            "save_qiskit_bridge_json_button": True,
            "export_qiskit_bridge_json_button": True,
            "import_qiskit_bridge_json_button": True,
            "relativistic_compensation_toggle": True,
            "reviewer_mode_toggle": True,
            "start_live_button": True,
            "stop_live_button": True,
            "reset_live_kernel_button": True,
            "reset_hard_abort_button": True,
            "init_recovery_validate_button": True,
            "refresh_button": True,
            "export_qom_hex_button": True,
            "forensic_certificate_button": True,
            "snapshot_json_button": True,
            "full_report_json_button": True,
            "copy_summary_button": True,
            "download_current_json_button": True,
            "stop_server_button": True,
        },
        "endpoints": {
            "html_monitor": "/",
            "current_payload": "/api/data",
            "live_tick_stream": "/api/live",
            "live_control_update": "/api/live/control",
            "reset_live_kernel": "/api/live/reset",
            "reset_hard_abort": "/api/override/reset_hard_abort",
            "init_recovery_validate": "/api/override/recovery_validate",
            "export_qom_hex": "/api/export/qom",
            "forensic_birth_certificate": "/api/export/birth_certificate",
            "snapshot_json": "/api/snapshot",
            "full_report_json": "/api/report",
            "qiskit_bridge_run": "/api/qiskit/run",
            "qiskit_bridge_latest": "/api/qiskit/latest",
            "qiskit_bridge_export": "/api/qiskit/export",
            "qiskit_bridge_import": "/api/qiskit/import",
            "qiskit_bridge_stop": "/api/qiskit/stop",
            "artifact_list": "/api/artifacts",
            "server_stop": "/api/stop",
            "health_check": "/api/health",
        },
        "scope_modules": {
            "canonical_runtime_loop": True,
            "live_moving_graphs": True,
            "disruption_injection_matrix": True,
            "dynamic_pid_tuning": True,
            "manual_override_resets": True,
            "hardware_boundary_slippage": True,
            "multi_branch_key_lineage_map": True,
            "joule_density_cost_tracker": True,
            "advanced_hardware_realism_modes": True,
            "pulse_level_hardware_knobs": True,
            "relativistic_clock_skew_compensation": True,
            "zero_noise_extrapolation_tuning": True,
            "rtos_priority_inversion_diagnostics": True,
            "multivariant_kappa_canvas": True,
            "cascade_efficiency_histograms": True,
            "carbon_neutral_resource_sheet": True,
            "unsafe_output_prevention_ledger": True,
            "uop_efficiency": True,
            "unnecessary_shutdown_rate": True,
            "mc_raw_and_norm": True,
            "kappa_vector": True,
            "multiplicative_trust": True,
            "layered_governance_bitmask": True,
            "phase_hold_certificates": True,
            "soft_and_hard_abort_causes": True,
            "recovery_validate": True,
            "qom_frame": True,
            "opte_policy_context_hash": True,
            "merkle_ledger": True,
            "birth_boundary_certificates": True,
            "coherence_market": True,
            "observed_eta_estimates": True,
            "hardware_register_target": True,
            "secure_enclave_vault": True,
            "cryogenic_scheduler": True,
            "reviewer_mode_metrics": True,
            "reviewer_mode_panel": True,
            "reviewer_mode_api_state": True,
            "reviewer_mode_grounded_view": True,
            "qiskit_ingestion_panel": True,
            "qst_overlap_fidelity": True,
            "t1_t2_relaxation_tracking": True,
            "qem_calibration_controls": True,
            "qiskit_bridge_run_save_import_export": True,
            "qiskit_independent_stop_control": True,
            "snapshot_and_report_exports": True,
        },
    }


class LiveRuntime:
    def __init__(self, seed: int = 2026):
        self.seed = seed
        self.lock = threading.Lock()
        self.control_state = {
            "disruption": "auto",
            "spoof_percent": 0.33,
            "kp": 1.00,
            "kd": 0.45,
            "theta_backaction": 0.40,
            "anchor_decay_lambda": 0.55,
            "reviewer_mode": False,
            "omega_drive": 0.35,
            "innovation_eta": 0.82,
            "rb_interleave": False,
            "zne_lambda": 1.00,
            "qiskit_noise_scale": 1.00,
            "qiskit_leakage_lambda": 0.00,
            "qiskit_crosstalk_inject": False,
            "qem_calibration": False,
            "relativistic_comp": True,
        }
        self.reset(seed)

    def reset(self, seed: int | None = None) -> dict[str, object]:
        with self.lock:
            if seed is not None:
                self.seed = seed
            self.kernel = AegisContinuityKernel(config=self.build_config(), seed=self.seed)
            self.rng = random.Random(self.seed + 4242)
            self.tick_count = 0
            self.recent: list[dict[str, object]] = []
            return {"status": "reset", "seed": self.seed}

    def build_config(self) -> KernelConfig:
        return KernelConfig(
            theta_backaction=float(self.control_state["theta_backaction"]),
            anchor_decay_lambda=float(self.control_state["anchor_decay_lambda"]),
        )

    def update_controls(self, payload: dict[str, object]) -> dict[str, object]:
        with self.lock:
            if "disruption" in payload:
                self.control_state["disruption"] = str(payload["disruption"])
            for key in [
                "spoof_percent",
                "kp",
                "kd",
                "theta_backaction",
                "anchor_decay_lambda",
                "omega_drive",
                "innovation_eta",
                "zne_lambda",
                "qiskit_noise_scale",
                "qiskit_leakage_lambda",
            ]:
                if key in payload:
                    self.control_state[key] = float(payload[key])
            if "reviewer_mode" in payload:
                self.control_state["reviewer_mode"] = bool(payload["reviewer_mode"])
            if "rb_interleave" in payload:
                self.control_state["rb_interleave"] = bool(payload["rb_interleave"])
            if "qem_calibration" in payload:
                self.control_state["qem_calibration"] = bool(payload["qem_calibration"])
            if "qiskit_crosstalk_inject" in payload:
                self.control_state["qiskit_crosstalk_inject"] = bool(payload["qiskit_crosstalk_inject"])
            if "relativistic_comp" in payload:
                self.control_state["relativistic_comp"] = bool(payload["relativistic_comp"])
            self.kernel.config.theta_backaction = float(self.control_state["theta_backaction"])
            self.kernel.config.anchor_decay_lambda = float(self.control_state["anchor_decay_lambda"])
            return {"status": "updated", "control_state": self.control_state}

    def reset_hard_abort(self) -> dict[str, object]:
        with self.lock:
            self.kernel = AegisContinuityKernel(config=self.build_config(), seed=self.seed + self.tick_count + 9000)
            self.recent = []
            return {
                "status": "RESET_HARD_ABORT_COMPLETE",
                "detail": "Memory caches flushed and live kernel re-initialized.",
                "control_state": self.control_state,
            }

    def init_recovery_validate(self) -> dict[str, object]:
        with self.lock:
            self.kernel.abort_latched = False
            self.kernel.anchor_history = []
            self.kernel.authorize_recovery_validation()
            return {
                "status": "RECOVERY_VALIDATE_INITIALIZED",
                "remaining_validation_cycles": self.kernel.recovery_validation_remaining,
            }

    def resolve_scenario(self) -> str:
        disruption = str(self.control_state["disruption"])
        if disruption == "auto":
            scenario_plan = [
                "normal",
                "normal",
                "storm",
                "normal",
                "transient_drift",
                "normal",
                "attack",
                "crypto_seal",
                "phase_hold",
                "normal",
                "anchor_dispute",
                "normal",
            ]
            return scenario_plan[(self.tick_count - 1) % len(scenario_plan)]
        return {
            "solar_flare": "storm",
            "spoof_attack": "attack",
            "thermal_spike": "storm",
            "crypto_jitter": "crypto_seal",
            "gps_denied_drift": "transient_drift",
            "holdover_decay_stress": "anchor_dispute",
            "crypto_seal_failover": "crypto_seal",
            "marginal_source_strat": "storm",
            "crosstalk_leakage": "attack",
            "state_leakage_recon": "phase_hold",
            "phase_hold": "phase_hold",
            "anchor_dispute": "anchor_dispute",
            "normal": "normal",
        }.get(disruption, "normal")

    def apply_live_controls(self, telemetry: list[object], disruption: str) -> None:
        drive_cancel = 0.030 * float(self.control_state["omega_drive"])
        damping = max(
            0.35,
            min(
                1.20,
                1.0
                - (0.035 * float(self.control_state["kp"]))
                - (0.025 * float(self.control_state["kd"]))
                - drive_cancel,
            ),
        )
        eta_scale = max(0.10, min(1.0, float(self.control_state["innovation_eta"])))
        for item in telemetry:
            item.phase_velocity *= damping
            item.phase_acceleration *= damping
            item.signal_mu *= eta_scale

        if self.control_state["rb_interleave"]:
            for item in telemetry[1::4]:
                item.phase_acceleration *= 0.82
                item.phase_velocity *= 0.88

        zne_lambda = max(0.5, min(3.0, float(self.control_state["zne_lambda"])))
        if zne_lambda > 1.0:
            for item in telemetry:
                item.phase_acceleration *= 1.0 + (0.035 * (zne_lambda - 1.0))
                item.phase_velocity *= 1.0 + (0.018 * (zne_lambda - 1.0))

        if self.control_state["relativistic_comp"]:
            for index, item in enumerate(telemetry):
                # Simulated rest-frame timestamp compensation before phase fusion.
                item.phase_velocity -= (index - (len(telemetry) / 2.0)) * 0.00042

        if disruption == "thermal_spike":
            for item in telemetry:
                item.environment = EnvironmentVector(0.96, 0.42, 0.62, 0.35, 0.58)
                item.signal_mu = max(item.signal_mu, 0.92)
                item.mission_priority = max(item.mission_priority, 0.86)

        if disruption == "spoof_attack":
            compromised = max(1, min(len(telemetry), int(round(len(telemetry) * float(self.control_state["spoof_percent"])))))
            for item in telemetry[:compromised]:
                item.bloch_vector = normalize_vector([0.0, 1.0, 0.0])
                item.signal_mu = 0.94
                item.suspected_attack = True
                item.mission_priority = 0.95

        if disruption == "crypto_jitter":
            for item in telemetry[::3]:
                item.crypto_valid = False
                item.signal_mu = max(item.signal_mu, 0.82)

        if disruption == "gps_denied_drift":
            for item in telemetry:
                item.environment = EnvironmentVector(0.52, 0.91, 0.54, 0.88, 0.76)
                item.phase_velocity *= self.rng.uniform(1.8, 2.7)
                item.phase_acceleration += self.rng.uniform(2.1, 4.4)
                item.mission_priority = 0.92

        if disruption == "holdover_decay_stress":
            self.kernel.anchor_history = []
            self.kernel.anchor_trust_memory *= 0.72
            for item in telemetry:
                item.environment = EnvironmentVector(0.34, 0.46, 0.42, 0.55, 0.93)
                item.phase_acceleration += self.rng.uniform(3.0, 5.2)
                item.mission_priority = 0.88

        if disruption == "crypto_seal_failover":
            for item in telemetry[::2]:
                item.crypto_valid = False
                item.phase_velocity *= 1.9
                item.mission_priority = 0.98

        if disruption == "marginal_source_strat":
            for index, item in enumerate(telemetry):
                item.signal_mu = max(0.12, item.signal_mu * (0.38 if index % 2 == 0 else 0.58))
                item.environment = EnvironmentVector(0.44, 0.28, 0.34, 0.50, 0.48)
                item.bloch_vector = normalize_vector([item.bloch_vector[0] * 0.88, item.bloch_vector[1] + 0.16, item.bloch_vector[2] * 0.82])

        if disruption == "crosstalk_leakage":
            for index, item in enumerate(telemetry):
                if index in {3, 4, 5, 8, 9}:
                    item.suspected_attack = True
                    item.bloch_vector = normalize_vector([0.28, 0.84, 0.18])
                    item.signal_mu = max(item.signal_mu, 0.86)
                    item.environment = EnvironmentVector(0.58, 0.82, 0.64, 0.36, 0.52)

        if disruption == "state_leakage_recon":
            for index, item in enumerate(telemetry):
                if index % 3 == 0:
                    item.bloch_vector = normalize_vector([0.12, 0.12, 0.08])
                    item.phase_acceleration += 5.8
                    item.signal_mu = max(item.signal_mu, 0.74)
                    item.suspected_attack = True
                    item.mission_priority = 0.93

        qiskit_noise_scale = max(0.1, min(5.0, float(self.control_state["qiskit_noise_scale"])))
        if qiskit_noise_scale != 1.0:
            for item in telemetry:
                item.phase_velocity *= 1.0 + (0.055 * (qiskit_noise_scale - 1.0))
                item.phase_acceleration *= 1.0 + (0.085 * (qiskit_noise_scale - 1.0))
                item.signal_mu = min(0.99, item.signal_mu * (1.0 + (0.045 * (qiskit_noise_scale - 1.0))))

        if self.control_state["qem_calibration"]:
            for item in telemetry:
                item.phase_velocity *= 0.94
                item.phase_acceleration *= 0.88
                item.signal_mu *= 0.96

    def build_boundary_slippage(self, cycle: dict[str, object]) -> dict[str, object]:
        reviewer = cycle.get("reviewer_telemetry", {})
        jitter_ns = float(reviewer.get("packet_transmission_jitter_ns", 0.0))
        gate_open = bool(cycle.get("hardware_register_target", {}).get("gate_open", False))
        slippage_ps = max(0.0, jitter_ns * 1000.0 * (0.16 + (0.04 * float(self.control_state["kd"]))))
        slack_budget_ps = 250.0
        return {
            "delta_slack_ps": slippage_ps,
            "slack_budget_ps": slack_budget_ps,
            "handoff_status": "CALIBRATE" if slippage_ps > slack_budget_ps else "LOCKED",
            "gate_open": gate_open,
            "layer_boundary": "L1_Q_CHIP_GATE_G_T_TO_L2_Q_GPU_PIPELINE",
        }

    def build_key_lineage_map(self, cycle: dict[str, object]) -> dict[str, object]:
        root = str(cycle.get("opte_policy_context_hash", "0" * 64))
        block_hash = str(cycle.get("block_hash", "0" * 64))
        branches = []
        for suffix in ["A", "B", "C"]:
            digest = normalize_hex_hash(f"{root}:{block_hash}:{suffix}:{self.tick_count}")[:16]
            branches.append(
                {
                    "branch_id": f"{self.kernel.branch_id}.{suffix}",
                    "subkey_hash_prefix": digest,
                    "status": "ACTIVE" if suffix == "B" else "GHOST_PRUNED",
                    "delayed_erasure": suffix != "B",
                }
            )
        return {
            "tree": "EPHEMERAL_MULTI_KEY_RATCHET",
            "active_branch": branches[1]["branch_id"],
            "branches": branches,
        }

    def build_energy_efficiency(self, cycle: dict[str, object]) -> dict[str, object]:
        cryo = cycle.get("cryogenic_scheduler", {})
        p_therm = max(1e-9, float(cryo.get("p_therm_mw", 1.0)))
        useful_score = (
            float(cycle.get("q_conf", 0.0))
            * float(cycle.get("meaningful_continuity_norm", 0.0))
            * max(1, int(cycle.get("active_nodes", 1)))
        )
        return {
            "useful_compute_per_mw": useful_score / p_therm,
            "joule_density_cost_index": p_therm / max(1e-9, useful_score),
            "p_therm_mw": p_therm,
            "cooling_capacity_used": cryo.get("saturation", 0.0),
        }

    def build_relativistic_clock_compensation(self, cycle: dict[str, object]) -> dict[str, object]:
        latency_bound_ms = float(cycle.get("reviewer_telemetry", {}).get("packet_latency_bound_ms", 0.0))
        environmental_severity = float(cycle.get("environmental_severity", 0.0))
        raw_skew_us = (latency_bound_ms * 0.18) + (environmental_severity * 3.2)
        correction_ratio = 0.985 if self.control_state["relativistic_comp"] else 0.0
        corrected_skew_us = raw_skew_us * (1.0 - correction_ratio)
        return {
            "routine": "LORENTZ_REST_FRAME_TIMESTAMP_SYNC",
            "enabled": bool(self.control_state["relativistic_comp"]),
            "canonical_timestamp_bits": 64,
            "delta_t_relativistic_us": raw_skew_us,
            "corrected_residual_skew_us": corrected_skew_us,
            "correction_ratio": correction_ratio,
        }

    def build_zne_tuning(self, cycle: dict[str, object]) -> dict[str, object]:
        zne_lambda = float(self.control_state["zne_lambda"])
        q_conf = float(cycle.get("q_conf", 0.0))
        risk = float(cycle.get("raw_unsafe_output_risk", 0.0))
        extrapolated_zero_noise_confidence = max(0.0, min(1.0, q_conf + ((zne_lambda - 1.0) * (1.0 - risk) * 0.035)))
        return {
            "register": "ZNE_NOISE_SCALING_FACTOR",
            "lambda_zne": zne_lambda,
            "pulse_stretch_factor": 1.0 + (0.20 * (zne_lambda - 1.0)),
            "extrapolated_zero_noise_confidence": extrapolated_zero_noise_confidence,
            "qem_mode": "ACTIVE" if zne_lambda > 1.0 else "NOMINAL",
        }

    def build_quantum_ingestion_telemetry(
        self,
        cycle: dict[str, object],
        telemetry: list[object],
        disruption: str,
    ) -> dict[str, object]:
        noise_scale = max(0.1, min(5.0, float(self.control_state["qiskit_noise_scale"])))
        leakage_lambda = max(0.0, min(1.0, float(self.control_state["qiskit_leakage_lambda"])))
        qem_enabled = bool(self.control_state["qem_calibration"])
        q_conf = float(cycle.get("q_conf", 0.0))
        risk = float(cycle.get("raw_unsafe_output_risk", 0.0))
        environmental_severity = float(cycle.get("environmental_severity", 0.0))
        leakage_active = disruption == "state_leakage_recon" or leakage_lambda > 0.0
        crosstalk_active = disruption == "crosstalk_leakage" or bool(self.control_state["qiskit_crosstalk_inject"])
        qem_delta = 0.035 + (0.018 * min(noise_scale, 3.0)) if qem_enabled else 0.0
        qst_overlap_fidelity = max(
            0.0,
            min(
                0.999,
                0.91
                + (0.080 * q_conf)
                - (0.115 * risk)
                - (0.035 * max(0.0, noise_scale - 1.0))
                - (0.040 if leakage_active else 0.0)
                - (0.025 if crosstalk_active else 0.0)
                + qem_delta,
            ),
        )
        t1_us = max(8.0, 72.0 / (1.0 + (0.42 * noise_scale) + (0.85 * environmental_severity)))
        t2_us = max(5.0, 58.0 / (1.0 + (0.58 * noise_scale) + (1.15 * environmental_severity)))
        relaxation_slope = 1.0 / max(t1_us, 1e-9)
        dephasing_slope = 1.0 / max(t2_us, 1e-9)
        leakage_probability = max(
            0.0,
            min(
                1.0,
                (0.018 * noise_scale)
                + (0.24 * max(leakage_lambda, 1.0 if disruption == "state_leakage_recon" else 0.0))
                + (0.10 if crosstalk_active else 0.0),
            ),
        )
        leaked_channels = [
            index
            for index, item in enumerate(telemetry)
            if leakage_active and index % 3 == 0
        ]
        solve_for_x_score = max(0.0, min(1.0, q_conf - (0.30 * leakage_probability) + (0.09 if qem_enabled else 0.0)))
        return {
            "source": "QISKIT_AER_BRIDGE_COMPATIBLE_NOISE_MODEL",
            "qst_overlap_fidelity": qst_overlap_fidelity,
            "qst_qos_threshold": 0.90,
            "qst_status": "PASS" if qst_overlap_fidelity >= 0.90 else "WARN",
            "t1_thermal_relaxation_us": t1_us,
            "t2_dephasing_us": t2_us,
            "t1_relaxation_slope": relaxation_slope,
            "t2_dephasing_slope": dephasing_slope,
            "lambda_noise": noise_scale,
            "qem_calibration_enabled": qem_enabled,
            "qem_mode": "ZNE_PEC_CALIBRATION" if qem_enabled else "OFF",
            "qem_estimated_fidelity_delta": qem_delta,
            "coherent_crosstalk_active": crosstalk_active,
            "state_leakage_active": leakage_active,
            "state_leakage_probability": leakage_probability,
            "leaked_channel_indices": leaked_channels,
            "solve_for_x_reconstruction_score": solve_for_x_score,
            "quarantine_latency_seconds": 0.0007 if leaked_channels else 0.0,
            "density_matrix_trace": 1.0,
            "proxy_density_trace": 1.0,
        }

    def build_rtos_scheduler_diagnostics(self, cycle: dict[str, object]) -> dict[str, object]:
        active_nodes = max(1, int(cycle.get("active_nodes", 1)))
        states = set(cycle.get("governance_states", []))
        severity = float(cycle.get("environmental_severity", 0.0))
        queue_depth = active_nodes + int(severity * 18) + (6 if "SECURITY_LOCKDOWN" in states else 0) + (4 if "PHASE_HOLD" in states else 0)
        base_lockhold_us = 18.0 + (severity * 42.0) + (queue_depth * 0.75)
        inherited = bool(states & {"CIRCUIT_ABORT", "HARD_ABORT", "CRYPTO_SEAL", "PHASE_HOLD"})
        damped_lockhold_us = base_lockhold_us * (0.34 if inherited else 0.72)
        return {
            "protocol": "PRIORITY_INHERITANCE",
            "thread_queue_depth": queue_depth,
            "sre_lockhold_latency_us": damped_lockhold_us,
            "priority_inversion_damped": inherited,
            "preemption_lane": "SAFETY_CRITICAL" if inherited else "STANDARD_RTOS",
        }

    def next_tick(self) -> dict[str, object]:
        with self.lock:
            self.tick_count += 1
            self.kernel.config.theta_backaction = float(self.control_state["theta_backaction"])
            self.kernel.config.anchor_decay_lambda = float(self.control_state["anchor_decay_lambda"])
            disruption = str(self.control_state["disruption"])
            scenario = self.resolve_scenario()
            if self.kernel.abort_latched and scenario == "normal":
                self.kernel = AegisContinuityKernel(config=self.build_config(), seed=self.seed + self.tick_count)
            telemetry = build_nominal_telemetry(self.kernel.config.node_count, self.rng, scenario)
            self.apply_live_controls(telemetry, disruption)
            result = self.kernel.execute_cycle(telemetry, scenario=f"live_{scenario}")
            payload = asdict(result)
            payload["tick"] = self.tick_count
            payload["live_scenario"] = scenario
            payload["active_disruption"] = disruption
            payload["control_state"] = dict(self.control_state)
            payload["timestamp_unix"] = time.time()
            payload["ledger_depth"] = len(self.kernel.ledger)
            payload["anchor_depth"] = len(self.kernel.anchor_history)
            payload["hardware_boundary_slippage"] = self.build_boundary_slippage(payload)
            payload["key_mutation_lineage_map"] = self.build_key_lineage_map(payload)
            payload["energy_efficiency"] = self.build_energy_efficiency(payload)
            payload["relativistic_clock_compensation"] = self.build_relativistic_clock_compensation(payload)
            payload["zne_tuning"] = self.build_zne_tuning(payload)
            payload["quantum_ingestion_telemetry"] = self.build_quantum_ingestion_telemetry(payload, telemetry, disruption)
            payload["rtos_scheduler_diagnostics"] = self.build_rtos_scheduler_diagnostics(payload)
            payload["pulse_controls"] = {
                "omega_drive": self.control_state["omega_drive"],
                "innovation_eta": self.control_state["innovation_eta"],
                "rb_interleave": self.control_state["rb_interleave"],
                "zne_lambda": self.control_state["zne_lambda"],
                "qiskit_noise_scale": self.control_state["qiskit_noise_scale"],
                "qiskit_leakage_lambda": self.control_state["qiskit_leakage_lambda"],
                "qiskit_crosstalk_inject": self.control_state["qiskit_crosstalk_inject"],
                "qem_calibration": self.control_state["qem_calibration"],
                "relativistic_comp": self.control_state["relativistic_comp"],
            }
            self.recent.append(payload)
            self.recent = self.recent[-96:]
            return {
                "current": payload,
                "recent": self.recent,
                "seed": self.seed,
                "control_state": self.control_state,
                "status": "running",
            }

    def current_payload(self) -> dict[str, object] | None:
        with self.lock:
            return self.recent[-1] if self.recent else None


LIVE_RUNTIME = LiveRuntime()


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AEGIS Q-SRE Monitor</title>
  <style>
    :root {
      --bg: #111111;
      --panel: #1b1b1b;
      --panel2: #242424;
      --line: #3a3a3a;
      --text: #f4f4f4;
      --muted: #b9b9b9;
      --green: #36d17d;
      --amber: #f2b84b;
      --red: #ff6961;
      --cyan: #47c7d8;
      --white: #ffffff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(17, 17, 17, 0.95);
      border-bottom: 1px solid var(--line);
      padding: 14px 20px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
    }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 20px; }
    h2 { font-size: 15px; margin-bottom: 10px; }
    h3 { font-size: 13px; color: var(--muted); font-weight: 600; }
    .sub { color: var(--muted); margin-top: 2px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .controls { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    label { color: var(--muted); font-size: 12px; display: grid; gap: 3px; }
    input {
      width: 96px;
      min-height: 36px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--panel2);
      color: var(--text);
      padding: 7px 8px;
    }
    select {
      min-height: 36px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--panel2);
      color: var(--text);
      padding: 7px 8px;
    }
    input[type="range"] {
      width: 132px;
      padding: 0;
      min-height: 28px;
    }
    button {
      background: var(--panel2);
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      cursor: pointer;
      min-height: 36px;
    }
    button:hover { border-color: var(--cyan); }
    button.primary { border-color: var(--green); }
    button.danger { border-color: var(--red); }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    main { padding: 18px 20px 28px; max-width: 1680px; margin: 0 auto; }
    .grid { display: grid; gap: 14px; }
    .top { grid-template-columns: repeat(6, minmax(140px, 1fr)); }
    .scopegrid { grid-template-columns: repeat(4, minmax(180px, 1fr)); margin-top: 14px; }
    .mid { grid-template-columns: 1.2fr 1fr; margin-top: 14px; }
    .wide { grid-template-columns: 1fr 1fr 1fr; margin-top: 14px; }
    .live { grid-template-columns: 1fr 1fr; margin-top: 14px; }
    section, .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .metric .label { color: var(--muted); font-size: 12px; }
    .metric .value { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .metric .hint { color: var(--muted); font-size: 12px; margin-top: 4px; min-height: 18px; }
    .ok { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }
    .info { color: var(--cyan); }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 7px 6px;
      vertical-align: top;
      white-space: nowrap;
    }
    th { color: var(--muted); font-weight: 600; font-size: 12px; }
    td.wrap { white-space: normal; }
    .bar {
      height: 8px;
      background: #333;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 6px;
    }
    .fill { height: 100%; background: var(--green); width: 0%; }
    .fill.warn { background: var(--amber); }
    .fill.bad { background: var(--red); }
    .mono { font-family: Consolas, ui-monospace, monospace; font-size: 12px; }
    .stack { display: grid; gap: 10px; }
    .pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      margin: 2px 4px 2px 0;
      background: var(--panel2);
    }
    .footer { color: var(--muted); margin-top: 14px; }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .badge {
      display: inline-block;
      color: var(--bg);
      background: var(--green);
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
    }
    canvas {
      width: 100%;
      height: 220px;
      display: block;
      background: #151515;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .eventlog {
      max-height: 224px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .event {
      display: grid;
      grid-template-columns: 58px 1fr auto;
      gap: 8px;
      padding: 7px 8px;
      border-bottom: 1px solid var(--line);
      align-items: center;
    }
    .scopeitem {
      background: var(--panel2);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 104px;
    }
    .scopeitem strong { display: block; margin-bottom: 6px; }
    .scopeitem .check { color: var(--green); font-weight: 800; margin-right: 6px; }
    .reviewerPanel {
      display: none;
      border-color: rgba(242, 184, 75, 0.55);
      background: #201b12;
    }
    .reviewerPanel .metric { background: #17140f; }
    .reviewerPanel .badge { background: var(--amber); }
    .reviewerNote {
      color: var(--muted);
      border-left: 3px solid var(--amber);
      padding-left: 10px;
      margin-top: 10px;
      line-height: 1.45;
    }
    body.reviewer .visionary { display: none; }
    body.reviewer .reviewerPanel { display: block; }
    body.reviewer h1::after { content: " - reviewer mode"; color: var(--amber); font-size: 13px; margin-left: 8px; }
    .controlPanel {
      display: grid;
      grid-template-columns: repeat(4, minmax(180px, 1fr));
      gap: 10px;
      margin: 14px 0;
    }
    .controlTile {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .controlTile label { margin-top: 8px; }
    .controlTile button, header button { white-space: nowrap; }
    @media (max-width: 1100px) {
      .top, .mid, .wide, .live { grid-template-columns: 1fr 1fr; }
      .controlPanel { grid-template-columns: 1fr 1fr; }
      header { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .top, .mid, .wide, .live { grid-template-columns: 1fr; }
      .controlPanel { grid-template-columns: 1fr; }
      .actions, .controls { width: 100%; }
      header button, .controlTile button { flex: 1 1 160px; }
      select, input { width: 100%; }
      th, td { white-space: normal; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>AEGIS Q-SRE Monitor</h1>
      <div class="sub">Continuity kernel, unsafe-output prevention, trust mesh, .QOM snapshot lineage</div>
    </div>
    <div class="actions">
      <div class="controls">
        <label>Cycles<input id="cycles" type="number" min="100" max="10000" step="100" value="1000"></label>
        <label>Seed<input id="seed" type="number" min="1" max="999999" step="1" value="2026"></label>
      </div>
      <button id="startLive" class="primary">Start Live</button>
      <button id="stopLive">Stop Live</button>
      <button id="refresh">Refresh</button>
      <button id="reviewerModeToggle">Reviewer Mode: OFF</button>
      <button id="exportQom">Export .QOM Hex</button>
      <button id="birthCert">Forensic Certificate</button>
      <button id="snapshot">Create Snapshot JSON</button>
      <button id="report">Create Full Report JSON</button>
      <button id="copySummary">Copy Summary</button>
      <button id="downloadCurrent">Download Current JSON</button>
      <button id="stopServer" class="danger">Stop Server</button>
    </div>
  </header>
  <main>
    <div id="status" class="footer">Loading monitor data...</div>
    <section id="reviewerPanel" class="reviewerPanel">
      <div class="toolbar">
        <div>
          <h2>Reviewer Mode: Grounded Metrics</h2>
          <div class="sub">Visionary terminology is hidden. This panel reports signal-processing, distributed-systems, packet, and scheduler diagnostics only.</div>
        </div>
        <span id="reviewerState" class="badge">OFF</span>
      </div>
      <div class="grid top" id="reviewerMetrics" style="grid-template-columns: repeat(4, minmax(120px, 1fr));"></div>
      <div id="reviewerDetail" class="stack"></div>
      <div class="reviewerNote">Use this mode for skeptical technical review: RMSE phase skew, packet jitter, entropy bounds, latency, queue depth, lockhold latency, register slack, compression, UOP, and USR remain visible without product-language framing.</div>
    </section>
    <section class="controlPanel">
      <div class="controlTile">
        <h2>Disruption Injection</h2>
        <label>Active stressor
          <select id="disruption">
            <option value="auto">Auto scenario loop</option>
            <option value="normal">Normal baseline</option>
            <option value="solar_flare">Solar flare / space weather</option>
            <option value="spoof_attack">Asymmetric core spoofing</option>
            <option value="thermal_spike">Thermal over-saturation</option>
            <option value="crypto_jitter">Crypto key sync jitter</option>
            <option value="gps_denied_drift">GPS-denied drift run</option>
            <option value="holdover_decay_stress">Holdover decay stress</option>
            <option value="crypto_seal_failover">Crypto-seal failover</option>
            <option value="marginal_source_strat">Marginal source stratification</option>
            <option value="crosstalk_leakage">Coherent crosstalk leakage</option>
            <option value="state_leakage_recon">State leakage reconstruction</option>
            <option value="phase_hold">Phase-hold acceleration spike</option>
            <option value="anchor_dispute">Anchor dispute drift</option>
          </select>
        </label>
        <label>Spoofed nodes <span id="spoofVal">33%</span>
          <input id="spoofPercent" type="range" min="0" max="75" step="1" value="33">
        </label>
      </div>
      <div class="controlTile">
        <h2>Runtime Tuning</h2>
        <label>Kp phase damping <span id="kpVal">1.00</span>
          <input id="kpGain" type="range" min="0" max="3" step="0.05" value="1">
        </label>
        <label>Kd phase damping <span id="kdVal">0.45</span>
          <input id="kdGain" type="range" min="0" max="2" step="0.05" value="0.45">
        </label>
        <label>Omega drive <span id="omegaVal">0.35</span>
          <input id="omegaDrive" type="range" min="0" max="1.50" step="0.01" value="0.35">
        </label>
        <label>ZNE lambda <span id="zneVal">1.00</span>
          <input id="zneLambda" type="range" min="0.50" max="3.00" step="0.01" value="1.00">
        </label>
        <label>Qiskit noise <span id="qiskitNoiseVal">1.00</span>
          <input id="qiskitNoise" type="range" min="0.10" max="5.00" step="0.05" value="1.00">
        </label>
        <label>Leakage lambda <span id="qiskitLeakVal">0.00</span>
          <input id="qiskitLeakage" type="range" min="0.00" max="1.00" step="0.01" value="0.00">
        </label>
        <label><input id="qiskitXtalk" type="checkbox" style="width:auto; min-height:auto;"> X_TALK_INJECT</label>
        <label><input id="qemCalibration" type="checkbox" style="width:auto; min-height:auto;"> QEM calibration</label>
      </div>
      <div class="controlTile">
        <h2>Safety Registers</h2>
        <label>Theta backaction <span id="thetaVal">0.40</span>
          <input id="thetaBackaction" type="range" min="0.10" max="1.00" step="0.01" value="0.40">
        </label>
        <label>Anchor decay lambda <span id="lambdaVal">0.55</span>
          <input id="anchorLambda" type="range" min="0.05" max="1.50" step="0.01" value="0.55">
        </label>
        <label>Innovation eta <span id="etaVal">0.82</span>
          <input id="innovationEta" type="range" min="0.10" max="1.00" step="0.01" value="0.82">
        </label>
      </div>
      <div class="controlTile">
        <h2>Operator Overrides</h2>
        <label><input id="reviewerMode" type="checkbox" style="width:auto; min-height:auto;"> Reviewer mode</label>
        <label><input id="rbInterleave" type="checkbox" style="width:auto; min-height:auto;"> RB calibration interleave</label>
        <label><input id="relativisticComp" type="checkbox" style="width:auto; min-height:auto;" checked> Relativistic timestamp compensation</label>
        <div class="actions" style="margin-top:10px">
          <button id="resetHardAbort" class="danger">RESET_HARD_ABORT</button>
          <button id="initRecovery">INIT_RECOVERY_VALIDATE</button>
        </div>
        <div id="overrideStatus" class="sub" style="margin-top:8px">No override issued.</div>
      </div>
    </section>
    <section style="margin-top:14px">
      <div class="toolbar">
        <h2>Full Scope Coverage</h2>
        <span id="coverageState" class="badge">CHECKING</span>
      </div>
      <div class="grid scopegrid" id="coverage"></div>
    </section>
    <div class="grid live">
      <section>
        <div class="toolbar">
          <h2>Live Runtime Feed</h2>
          <span id="liveScenario" class="badge">WAITING</span>
        </div>
        <div class="sub" style="margin-bottom:10px">Start Live streams one kernel cycle every 1.2 seconds. Refresh below rebuilds the heavier Monte Carlo/report view.</div>
        <div class="grid top" id="liveMetrics" style="grid-template-columns: repeat(4, minmax(120px, 1fr));"></div>
        <canvas id="liveGraph" width="900" height="260"></canvas>
        <h3 style="margin-top:10px">Kappa Vector Topology</h3>
        <canvas id="kappaGraph" width="900" height="210"></canvas>
      </section>
      <section>
        <div class="toolbar">
          <h2>Live Event Log</h2>
          <button id="resetLive">Reset Live Kernel</button>
        </div>
        <div id="liveDetail" class="stack"></div>
        <div id="eventLog" class="eventlog" style="margin-top:10px"></div>
      </section>
    </div>
    <div class="grid mid">
      <section>
        <div class="toolbar">
          <h2>Qiskit Simulator Ingestion</h2>
          <div class="actions">
            <button id="runQiskit">Run Qiskit Pass</button>
            <button id="stopQiskit" class="danger">Stop Qiskit Only</button>
            <button id="saveQiskit">Save Qiskit JSON</button>
            <button id="exportQiskit">Export Qiskit JSON</button>
            <button id="importQiskit">Import Qiskit JSON</button>
            <input id="qiskitImportFile" type="file" accept="application/json,.json" style="display:none">
            <span id="qiskitState" class="badge">WAITING</span>
          </div>
        </div>
        <div class="sub" style="margin-bottom:10px">Runs the optional Qiskit Aer bridge, saves server artifacts, exports local JSON, and can import prior Qiskit bridge runs for review.</div>
        <div class="grid top" id="qiskitMetrics" style="grid-template-columns: repeat(4, minmax(120px, 1fr));"></div>
        <canvas id="qiskitGraph" width="900" height="220"></canvas>
        <div id="qiskitArtifact" class="mono" style="margin-top:10px">No Qiskit bridge artifact loaded yet.</div>
      </section>
      <section>
        <h2>Quantum Leakage / QEM Detail</h2>
        <div id="qiskitDetail" class="stack"></div>
      </section>
    </div>
    <div class="grid mid">
      <section>
        <h2>Cascade Efficiency Histograms</h2>
        <canvas id="cascadeGraph" width="900" height="220"></canvas>
      </section>
      <section>
        <h2>Carbon-Neutral Resource Sheet</h2>
        <canvas id="cryoGraph" width="900" height="220"></canvas>
      </section>
      <section>
        <h2>Unsafe-Output Prevention Ledger</h2>
        <div id="uopLedger" class="stack"></div>
      </section>
    </div>
    <div class="grid wide">
      <section>
        <h2>Register Handoff Slack</h2>
        <div id="slippage" class="stack"></div>
      </section>
      <section>
        <h2>Key Mutation Lineage</h2>
        <div id="keyLineage" class="stack"></div>
      </section>
      <section>
        <h2>Energy Efficiency</h2>
        <div id="energyCost" class="stack"></div>
      </section>
    </div>
    <div class="grid wide">
      <section>
        <h2>Relativistic Clock Compensation</h2>
        <div id="clockComp" class="stack"></div>
      </section>
      <section>
        <h2>ZNE QEM Tuning</h2>
        <div id="zneTuning" class="stack"></div>
      </section>
      <section>
        <h2>RTOS Priority Inversion</h2>
        <div id="rtosDiag" class="stack"></div>
      </section>
    </div>
    <div class="grid top" id="metrics"></div>
    <div class="grid mid">
      <section>
        <h2>Benchmark Tiers</h2>
        <div id="tiers"></div>
      </section>
      <section>
        <h2>Targets And Cascade</h2>
        <div id="targets" class="stack"></div>
      </section>
    </div>
    <div class="grid wide">
      <section>
        <h2>Deterministic Scenario Trace</h2>
        <div id="deterministic"></div>
      </section>
      <section>
        <h2>Trust And Kappa Scope</h2>
        <div id="trust" class="stack"></div>
      </section>
      <section>
        <h2>.QOM / OPTE / Ledger Scope</h2>
        <div id="qom" class="stack"></div>
      </section>
    </div>
    <div class="grid wide">
      <section>
        <h2>Hardware Register Target</h2>
        <div id="hardware" class="stack"></div>
      </section>
      <section>
        <h2>Secure Enclave Vault</h2>
        <div id="enclave" class="stack"></div>
      </section>
      <section>
        <h2>Cryogenic / Reviewer Metrics</h2>
        <div id="physical" class="stack"></div>
      </section>
    </div>
    <section style="margin-top:14px">
      <div class="toolbar">
        <h2>Generated Artifacts</h2>
        <span id="liveState" class="badge">LIVE OFF</span>
      </div>
      <div id="artifact" class="mono">No artifact created in this browser session yet.</div>
      <div id="artifactList" style="margin-top:10px"></div>
    </section>
  </main>
<script>
const fmt = (n, d=3) => n === null || n === undefined ? "N/A" : Number(n).toFixed(d);
const pct = (n) => n === null || n === undefined ? "N/A" : (Number(n) * 100).toFixed(3) + "%";
const cls = (n, ok, warn) => n >= ok ? "ok" : n >= warn ? "warn" : "bad";
const el = (id) => document.getElementById(id);
let current = null;
let liveTimer = null;
let liveHistory = [];
let latestQiskitArtifact = null;

function metric(label, value, hint, kind="") {
  return `<div class="metric"><div class="label">${label}</div><div class="value ${kind}">${value}</div><div class="hint">${hint || ""}</div></div>`;
}

function bar(value, good=true) {
  const width = Math.max(0, Math.min(100, Number(value || 0) * 100));
  const klass = good ? (width >= 99 ? "" : width >= 95 ? "warn" : "bad") : (width <= 5 ? "" : width <= 10 ? "warn" : "bad");
  return `<div class="bar"><div class="fill ${klass}" style="width:${width}%"></div></div>`;
}

function render(data) {
  current = data;
  const mc = data.monte_carlo;
  const target = data.projection_validation.target_boundary;
  el("status").textContent = `Generated ${new Date(data.generated_at_unix * 1000).toLocaleString()} | seed ${data.seed} | cycles ${data.cycles}`;
  el("metrics").innerHTML = [
    metric("UOP Efficiency", pct(mc.unsafe_output_prevention_efficiency), `target ${pct(target.public_v1_target_unsafe_output_prevention_efficiency)}`, cls(mc.unsafe_output_prevention_efficiency, target.public_v1_target_unsafe_output_prevention_efficiency, .99)),
    metric("Continuity Yield", pct(mc.empirical_continuity_yield), "composite gate pass rate", cls(mc.empirical_continuity_yield, .7, .5)),
    metric("Integrity Preserved", pct(mc.integrity_preserved_yield), "fail-closed safe interventions", "info"),
    metric("USR", pct(mc.unnecessary_shutdown_rate), `target < ${pct(mc.unnecessary_shutdown_target)}`, mc.unnecessary_shutdown_target_met ? "ok" : "bad"),
    metric("Unsafe Opportunities", mc.unsafe_output_opportunities, `${mc.unsafe_output_prevented_cycles} prevented`, "info"),
    metric("Circuit Aborts", mc.circuit_abort_count, "hard fail-closed events", mc.circuit_abort_count ? "warn" : "ok")
  ].join("");
  renderCoverage(data);
  drawCascadeGraph(data.observed_cascade_efficiency_estimates);
  drawCryoGraph();
  renderUopLedger();

  const tiers = Object.keys(mc.tier_yields).map(t => `
    <tr>
      <td>${t}</td>
      <td>${pct(mc.tier_yields[t])}${bar(mc.tier_yields[t])}</td>
      <td>${mc.tier_unsafe_output_opportunities[t]}</td>
      <td>${pct(mc.tier_unsafe_output_prevention_efficiency[t])}${bar(mc.tier_unsafe_output_prevention_efficiency[t] ?? 1)}</td>
      <td>${pct(mc.tier_unnecessary_shutdown_rates[t])}</td>
    </tr>`).join("");
  el("tiers").innerHTML = `<table><thead><tr><th>Tier</th><th>Continuity</th><th>UO Opps</th><th>UOP</th><th>USR</th></tr></thead><tbody>${tiers}</tbody></table>`;

  const eta = data.observed_cascade_efficiency_estimates;
  el("targets").innerHTML = `
    <div><h3>Performance Targets</h3>
      <div>Public v1: <b>${pct(target.public_v1_target_unsafe_output_prevention_efficiency)}</b></div>
      <div>Stretch: <b>${pct(target.systemic_stretch_target_unsafe_output_prevention_efficiency)}</b></div>
      <div>Theoretical cascade: <b>${pct(target.theoretical_cascade_boundary_unsafe_output_prevention_efficiency)}</b></div>
    </div>
    <div><h3>Observed Eta Estimates</h3>
      <div>Byzantine: <b>${fmt(eta.eta_byzantine_observed, 6)}</b></div>
      <div>Taylor: <b>${fmt(eta.eta_taylor_observed, 6)}</b></div>
      <div>Riemann: <b>${fmt(eta.eta_riemann_observed, 6)}</b></div>
    </div>
    <div><h3>Definition</h3>
      <div>${data.scope.uop_definition}</div>
      <div class="sub">${data.scope.continuity_gate}</div>
    </div>`;

  const detRows = data.deterministic_suite.map(r => `
    <tr>
      <td>${r.scenario}</td>
      <td class="wrap">${r.governance_states.map(s => `<span class="pill">${s}</span>`).join("")}</td>
      <td>${r.continuity_gate_passed ? "PASS" : "HOLD"}</td>
      <td>${r.integrity_preserved ? "YES" : "NO"}</td>
      <td>${r.abort_tier}</td>
      <td class="wrap">${(r.hard_abort_causes || []).join(", ") || "-"}</td>
      <td>${r.ledger_certificate_type}</td>
    </tr>`).join("");
  el("deterministic").innerHTML = `<table><thead><tr><th>Scenario</th><th>States</th><th>Gate</th><th>Integrity</th><th>Abort</th><th>Causes</th><th>Certificate</th></tr></thead><tbody>${detRows}</tbody></table>`;

  const last = data.deterministic_suite[data.deterministic_suite.length - 1];
  const kv = last.kappa_vector_mean;
  const tc = last.trust_channels;
  el("trust").innerHTML = `
    <div><h3>Live Kappa Vector Mean</h3>
      <div>node ${fmt(kv.node)} ${bar(kv.node)}</div>
      <div>recon ${fmt(kv.recon)} ${bar(kv.recon)}</div>
      <div>telemetry ${fmt(kv.telemetry)} ${bar(kv.telemetry)}</div>
    </div>
    <div><h3>Multiplicative Trust Channels</h3>
      <div>physical ${fmt(tc.physical)} ${bar(tc.physical)}</div>
      <div>observer ${fmt(tc.observer)} ${bar(tc.observer)}</div>
      <div>historical ${fmt(tc.historical)} ${bar(tc.historical)}</div>
      <div>consensus ${fmt(tc.consensus)} ${bar(tc.consensus)}</div>
      <div>anchor ${fmt(tc.anchor)} ${bar(tc.anchor)}</div>
      <div>total <b>${fmt(tc.total, 6)}</b></div>
    </div>`;

  el("qom").innerHTML = `
    <div><h3>.QOM</h3><div>${data.scope.qom}</div></div>
    <div><h3>OPTE</h3><div>${data.scope.opte}</div></div>
    <div><h3>Latest Policy Context Hash</h3><div class="mono">${last.opte_policy_context_hash}</div></div>
    <div><h3>Latest Merkle Root</h3><div class="mono">${last.merkle_root}</div></div>
    <div><h3>Latest Block Hash</h3><div class="mono">${last.block_hash}</div></div>
    <div><h3>.QOM Frame Prefix</h3><div class="mono">${last.snapshot_frame_hex_prefix}</div></div>
    <div><h3>.QOM Compact Payload</h3><div>${last.qom_compact_payload_bits} bits</div><div class="mono">${last.qom_compact_payload_hex}</div></div>
    <div><h3>Canonical Runtime Loop</h3><div class="mono">${data.scope.pipeline.join(" -> ")}</div></div>`;

  const hw = last.hardware_register_target;
  const enclave = last.secure_enclave_vault;
  const cryo = last.cryogenic_scheduler;
  const reviewer = last.reviewer_telemetry;
  el("hardware").innerHTML = `
    <div><h3>${hw.target}</h3><div>${data.scope.hardware_register_target}</div></div>
    <div>gate open: <b class="${hw.gate_open ? "ok" : "bad"}">${hw.gate_open}</b></div>
    <div>O-quantization window: <b>${hw.o_quantization_window_ns} ns</b></div>
    <div>register width: <b>${hw.register_width_bits} bits</b></div>
    <div class="mono">${Object.entries(hw.address_map).map(([k,v]) => `${k}=${v}`).join("<br>")}</div>
    <div class="mono">${hw.verilog_stub}</div>`;
  el("enclave").innerHTML = `
    <div><h3>${enclave.architecture}</h3><div>${data.scope.secure_enclave_vault}</div></div>
    <div>ratchet: <b>${enclave.ratchet}</b></div>
    <div>branch: <b>${enclave.branch_id}</b></div>
    <div>delayed erasure pending: <b class="${enclave.delayed_erasure_pending ? "warn" : "ok"}">${enclave.delayed_erasure_pending}</b></div>
    <div>key fingerprint: <span class="mono">${enclave.active_key_fingerprint}</span></div>
    <div>${enclave.isolated_register_banks.map(x => `<span class="pill">${x}</span>`).join("")}</div>`;
  el("physical").innerHTML = `
    <div><h3>${cryo.scheduler}</h3><div>${data.scope.cryogenic_scheduler}</div></div>
    <div>P_therm ${fmt(cryo.p_therm_mw, 4)} mW / budget ${fmt(cryo.thermal_budget_mw, 2)} mW ${bar(cryo.saturation, false)}</div>
    <div>action: <b>${cryo.action}</b></div>
    <div><h3>Reviewer Telemetry</h3></div>
    <div>RMSE phase skew: <b>${fmt(reviewer.rmse_phase_skew_rad, 6)} rad</b></div>
    <div>packet jitter: <b>${fmt(reviewer.packet_transmission_jitter_ns, 6)} ns</b></div>
    <div>Shannon entropy bound: <b>${fmt(reviewer.shannon_entropy_bound_bits, 6)} bits</b></div>
    <div>compression: <b>${fmt(reviewer.data_compression_ratio, 2)}x</b></div>
    <div>latency bound: <b>${fmt(reviewer.packet_latency_bound_ms, 4)} ms</b></div>`;
  renderReviewerPanel(last);
}

function renderReviewerPanel(result) {
  const reviewerOn = el("reviewerMode").checked;
  const state = el("reviewerState");
  if (state) {
    state.textContent = reviewerOn ? "ON" : "OFF";
    state.style.background = reviewerOn ? "var(--amber)" : "var(--line)";
    state.style.color = reviewerOn ? "var(--bg)" : "var(--fg)";
  }
  if (!result) {
    el("reviewerMetrics").innerHTML = [
      metric("Reviewer mode", reviewerOn ? "ON" : "OFF", "waiting for live or report data", reviewerOn ? "warn" : "info")
    ].join("");
    el("reviewerDetail").innerHTML = "<div>No runtime sample loaded yet.</div>";
    return;
  }
  const mc = current ? current.monte_carlo : null;
  const telemetry = result.reviewer_telemetry || {};
  const slip = result.hardware_boundary_slippage || {};
  const rtos = result.rtos_scheduler_diagnostics || {};
  const qomBits = result.qom_compact_payload_bits || 176;
  const uop = mc ? mc.unsafe_output_prevention_efficiency : null;
  const usr = mc ? mc.unnecessary_shutdown_rate : null;
  const slipStatus = slip.handoff_status || (Number(slip.delta_slack_ps || 0) <= 250 ? "LOCKED" : "SLIP_BREACH");
  const rtosStatus = rtos.priority_inversion_damped ? "PRIORITY_INHERITANCE_ACTIVE" : "NORMAL";
  const lockholdMs = Number(rtos.sre_lockhold_latency_us || 0) / 1000;
  el("reviewerMetrics").innerHTML = [
    metric("RMSE phase skew", `${fmt(telemetry.rmse_phase_skew_rad, 6)} rad`, "phase error residual", "info"),
    metric("Packet jitter", `${fmt(telemetry.packet_transmission_jitter_ns, 6)} ns`, "transport timing variance", "info"),
    metric("Entropy bound", `${fmt(telemetry.shannon_entropy_bound_bits, 6)} bits`, "Shannon information bound", "info"),
    metric("Compression", `${fmt(telemetry.data_compression_ratio, 2)}x`, "storage footprint ratio", "ok"),
    metric("Latency bound", `${fmt(telemetry.packet_latency_bound_ms, 4)} ms`, "packet processing ceiling", "info"),
    metric("Register slack", `${fmt(slip.delta_slack_ps, 2)} ps`, `budget ${fmt(slip.slack_budget_ps, 2)} ps`, slipStatus === "LOCKED" ? "ok" : "bad"),
    metric("Queue depth", rtos.thread_queue_depth ?? "N/A", "RTOS scheduler backlog", Number(rtos.thread_queue_depth || 0) <= 6 ? "ok" : "warn"),
    metric("Lockhold latency", `${fmt(lockholdMs, 4)} ms`, rtosStatus, rtosStatus === "PRIORITY_INHERITANCE_ACTIVE" ? "warn" : "ok"),
    metric("UOP efficiency", uop === null ? "N/A" : pct(uop), "unsafe-output prevention", uop === null ? "info" : cls(uop, .9949, .99)),
    metric("USR", usr === null ? "N/A" : pct(usr), "unnecessary shutdown rate", usr === null ? "info" : (usr < .05 ? "ok" : "bad")),
    metric(".QOM payload", `${qomBits} bits`, "compact metadata frame", "info"),
    metric("Reviewer API", reviewerOn ? "ACTIVE" : "READY", "control state propagated", reviewerOn ? "ok" : "info")
  ].join("");
  el("reviewerDetail").innerHTML = `
    <div>Scenario: <b>${result.scenario || result.live_scenario || "N/A"}</b></div>
    <div>Governance states: <b>${(result.governance_states || []).join(" | ") || "NORMAL"}</b></div>
    <div>Continuity gate: <b>${result.continuity_gate_passed ? "PASS" : "HOLD"}</b> | Integrity preserved: <b>${result.integrity_preserved ? "YES" : "NO"}</b></div>
    <div>Register handoff status: <b class="${slipStatus === "LOCKED" ? "ok" : "bad"}">${slipStatus}</b></div>
    <div>RTOS scheduler status: <b class="${rtosStatus === "PRIORITY_INHERITANCE_ACTIVE" ? "warn" : "ok"}">${rtosStatus}</b></div>
    <div>Packet context hash: <span class="mono">${result.opte_policy_context_hash || "N/A"}</span></div>
    <div>Lineage root: <span class="mono">${result.merkle_root || "N/A"}</span></div>`;
}

function renderCoverage(data) {
  const last = data.deterministic_suite[data.deterministic_suite.length - 1];
  const mc = data.monte_carlo;
  const checks = [
    {
      title: "Canonical Kernel Loop",
      ok: Array.isArray(data.scope.pipeline) && data.scope.pipeline.length === 10,
      detail: `${data.scope.pipeline.length}/10 runtime stages loaded`
    },
    {
      title: "150-Cycle Simulation",
      ok: data.advanced_performance_report.step_count === 150,
      detail: "baseline + storm + adversarial report present"
    },
    {
      title: "Unsafe-Output Metrics",
      ok: mc.unsafe_output_prevention_efficiency >= data.projection_validation.target_boundary.public_v1_target_unsafe_output_prevention_efficiency,
      detail: `UOP ${pct(mc.unsafe_output_prevention_efficiency)} over ${mc.unsafe_output_opportunities} opportunities`
    },
    {
      title: "Layered Governance",
      ok: last.governance_states && last.governance_states.length > 0,
      detail: `latest ${last.governance_states.join(" | ")}`
    },
    {
      title: ".QOM + OPTE Frame",
      ok: last.qom_compact_payload_bits === 176 && !!last.opte_policy_context_hash,
      detail: `${last.qom_compact_payload_bits} bit compact payload with policy hash`
    },
    {
      title: "Merkle Ledger",
      ok: !!last.merkle_root && !!last.block_hash,
      detail: `certificate ${last.ledger_certificate_type}`
    },
    {
      title: "Hardware Register Target",
      ok: !!last.hardware_register_target,
      detail: last.hardware_register_target ? `${last.hardware_register_target.target}, ${last.hardware_register_target.o_quantization_window_ns} ns` : "missing"
    },
    {
      title: "Secure Enclave Vault",
      ok: !!last.secure_enclave_vault,
      detail: last.secure_enclave_vault ? `${last.secure_enclave_vault.architecture}, branch ${last.secure_enclave_vault.branch_id}` : "missing"
    },
    {
      title: "Cryogenic Scheduler",
      ok: !!last.cryogenic_scheduler,
      detail: last.cryogenic_scheduler ? `${fmt(last.cryogenic_scheduler.p_therm_mw, 3)} mW, ${last.cryogenic_scheduler.action}` : "missing"
    },
    {
      title: "Reviewer Telemetry",
      ok: !!last.reviewer_telemetry,
      detail: last.reviewer_telemetry ? `RMSE ${fmt(last.reviewer_telemetry.rmse_phase_skew_rad, 5)}, jitter ${fmt(last.reviewer_telemetry.packet_transmission_jitter_ns, 2)} ns` : "missing"
    },
    {
      title: "Live Runtime Feed",
      ok: liveHistory.length > 0,
      detail: liveHistory.length > 0 ? `${liveHistory.length} live ticks buffered` : "click Start Live to stream moving values"
    },
    {
      title: "Snapshot / Report Export",
      ok: true,
      detail: "snapshot, full report, current JSON, artifact list"
    }
  ];
  const allOk = checks.every(item => item.ok || item.title === "Live Runtime Feed");
  el("coverageState").textContent = allOk ? "CORE LOADED" : "CHECK ITEMS";
  el("coverageState").style.background = allOk ? "var(--green)" : "var(--amber)";
  el("coverage").innerHTML = checks.map(item => `
    <div class="scopeitem">
      <strong><span class="check">${item.ok ? "OK" : "--"}</span>${item.title}</strong>
      <div class="sub">${item.detail}</div>
    </div>`).join("");
}

function renderLive(payload) {
  const r = payload.current;
  liveHistory = payload.recent || [];
  el("liveScenario").textContent = `${r.active_disruption || "auto"} -> ${r.live_scenario} / epoch ${r.epoch}`;
  el("liveScenario").style.background = r.integrity_preserved ? "var(--amber)" : r.continuity_gate_passed ? "var(--green)" : "var(--red)";
  el("liveMetrics").innerHTML = [
    metric("Q_conf", fmt(r.q_conf, 4), `threshold ${fmt(r.gate_q_conf_threshold, 2)}`, cls(r.q_conf, r.gate_q_conf_threshold, .75)),
    metric("M_c norm", fmt(r.meaningful_continuity_norm, 4), `raw ${fmt(r.meaningful_continuity_raw, 2)}x`, cls(r.meaningful_continuity_norm, r.gate_mc_norm_threshold, .5)),
    metric("Risk", fmt(r.raw_unsafe_output_risk, 4), r.unsafe_output_opportunity ? "unsafe opportunity" : "quiet cycle", r.unsafe_output_opportunity ? "warn" : "ok"),
    metric("Trust", fmt(r.trust_index, 4), `anchor ${fmt(r.trust_channels.anchor, 3)}`, cls(r.trust_index, .7, .3))
  ].join("");
  el("liveDetail").innerHTML = `
    <div><h3>Current Governance</h3><div>${r.governance_states.map(s => `<span class="pill">${s}</span>`).join("")}</div></div>
    <div><h3>Current Outcome</h3>
      <div>gate: <b>${r.continuity_gate_passed ? "PASS" : "HOLD"}</b> | integrity: <b>${r.integrity_preserved ? "YES" : "NO"}</b> | abort: <b>${r.abort_tier}</b></div>
      <div class="sub">causes: ${(r.hard_abort_causes || []).join(", ") || "-"}</div>
    </div>
    <div><h3>Kappa Vector</h3>
      <div>node ${fmt(r.kappa_vector_mean.node)} | recon ${fmt(r.kappa_vector_mean.recon)} | telemetry ${fmt(r.kappa_vector_mean.telemetry)}</div>
    </div>
    <div><h3>Lineage</h3>
      <div class="mono">merkle ${r.merkle_root}</div>
      <div class="mono">opte ${r.opte_policy_context_hash}</div>
      <div class="mono">qom ${r.qom_compact_payload_bits}b ${r.qom_compact_payload_hex}</div>
      <div class="mono">cryo ${fmt(r.cryogenic_scheduler.p_therm_mw, 4)}mW ${r.cryogenic_scheduler.action}</div>
    </div>
    <div><h3>Runtime Controls</h3>
      <div>Kp ${fmt(r.control_state.kp, 2)} | Kd ${fmt(r.control_state.kd, 2)} | theta_b ${fmt(r.control_state.theta_backaction, 2)} | lambda_a ${fmt(r.control_state.anchor_decay_lambda, 2)}</div>
      <div>Omega ${fmt(r.pulse_controls.omega_drive, 2)} | eta ${fmt(r.pulse_controls.innovation_eta, 2)} | ZNE ${fmt(r.pulse_controls.zne_lambda, 2)} | RB ${r.pulse_controls.rb_interleave}</div>
    </div>`;
  renderAdvancedLiveDiagnostics(r);
  renderQuantumIngestion(r);
  renderReviewerPanel(r);
  el("eventLog").innerHTML = liveHistory.slice().reverse().map(item => `
    <div class="event">
      <span class="mono">#${item.tick}</span>
      <span>${item.live_scenario} ${item.governance_states.map(s => `<span class="pill">${s}</span>`).join("")}</span>
      <span class="${item.integrity_preserved ? "warn" : item.continuity_gate_passed ? "ok" : "bad"}">${item.integrity_preserved ? "INTEGRITY" : item.continuity_gate_passed ? "PASS" : "HOLD"}</span>
    </div>`).join("");
  drawLiveGraph();
  drawKappaGraph();
  drawQiskitGraph();
  drawCryoGraph();
  renderUopLedger();
  if (current) renderCoverage(current);
}

function renderAdvancedLiveDiagnostics(r) {
  const slip = r.hardware_boundary_slippage || {};
  const lineage = r.key_mutation_lineage_map || {branches: []};
  const energy = r.energy_efficiency || {};
  const clock = r.relativistic_clock_compensation || {};
  const zne = r.zne_tuning || {};
  const rtos = r.rtos_scheduler_diagnostics || {};
  el("slippage").innerHTML = `
    <div>delta_slack: <b class="${slip.handoff_status === "LOCKED" ? "ok" : "warn"}">${fmt(slip.delta_slack_ps, 3)} ps</b></div>
    <div>budget: <b>${fmt(slip.slack_budget_ps, 1)} ps</b></div>
    <div>handoff: <b>${slip.handoff_status || "N/A"}</b></div>
    <div class="mono">${slip.layer_boundary || ""}</div>`;
  el("keyLineage").innerHTML = `
    <div>tree: <b>${lineage.tree || "N/A"}</b></div>
    <div>active branch: <b>${lineage.active_branch || "N/A"}</b></div>
    <div>${(lineage.branches || []).map(b => `<span class="pill">${b.branch_id}: ${b.subkey_hash_prefix} / ${b.status}</span>`).join("")}</div>`;
  el("energyCost").innerHTML = `
    <div>useful compute per mW: <b>${fmt(energy.useful_compute_per_mw, 6)}</b></div>
    <div>joule density cost index: <b>${fmt(energy.joule_density_cost_index, 6)}</b></div>
    <div>P_therm: <b>${fmt(energy.p_therm_mw, 4)} mW</b></div>
    <div>cooling capacity used: <b>${pct(energy.cooling_capacity_used)}</b></div>`;
  el("clockComp").innerHTML = `
    <div>routine: <b>${clock.routine || "N/A"}</b></div>
    <div>enabled: <b>${clock.enabled}</b></div>
    <div>canonical timestamp: <b>${clock.canonical_timestamp_bits || "N/A"} bits</b></div>
    <div>delta_t_relativistic: <b>${fmt(clock.delta_t_relativistic_us, 6)} us</b></div>
    <div>corrected residual: <b>${fmt(clock.corrected_residual_skew_us, 6)} us</b></div>
    <div>correction ratio: <b>${pct(clock.correction_ratio)}</b></div>`;
  el("zneTuning").innerHTML = `
    <div>register: <b>${zne.register || "N/A"}</b></div>
    <div>lambda_ZNE: <b>${fmt(zne.lambda_zne, 3)}</b></div>
    <div>pulse stretch factor: <b>${fmt(zne.pulse_stretch_factor, 3)}</b></div>
    <div>zero-noise extrapolated confidence: <b>${fmt(zne.extrapolated_zero_noise_confidence, 6)}</b></div>
    <div>QEM mode: <b>${zne.qem_mode || "N/A"}</b></div>`;
  el("rtosDiag").innerHTML = `
    <div>protocol: <b>${rtos.protocol || "N/A"}</b></div>
    <div>thread queue depth: <b>${rtos.thread_queue_depth || 0}</b></div>
    <div>SRE lockhold latency: <b>${fmt(rtos.sre_lockhold_latency_us, 6)} us</b></div>
    <div>priority inversion damped: <b>${rtos.priority_inversion_damped}</b></div>
    <div>preemption lane: <b>${rtos.preemption_lane || "N/A"}</b></div>`;
}

function renderQuantumIngestion(r) {
  const q = r.quantum_ingestion_telemetry || {};
  const status = q.qst_status || "WAITING";
  el("qiskitState").textContent = status;
  el("qiskitState").style.background = status === "PASS" ? "var(--green)" : "var(--amber)";
  el("qiskitMetrics").innerHTML = [
    metric("QST overlap F", fmt(q.qst_overlap_fidelity, 5), `threshold ${fmt(q.qst_qos_threshold, 2)}`, Number(q.qst_overlap_fidelity || 0) >= Number(q.qst_qos_threshold || .9) ? "ok" : "warn"),
    metric("T1 relaxation", `${fmt(q.t1_thermal_relaxation_us, 2)} us`, `slope ${fmt(q.t1_relaxation_slope, 5)}`, "info"),
    metric("T2 dephasing", `${fmt(q.t2_dephasing_us, 2)} us`, `slope ${fmt(q.t2_dephasing_slope, 5)}`, "info"),
    metric("Noise lambda", fmt(q.lambda_noise, 2), "Qiskit noise-model scale", Number(q.lambda_noise || 1) > 2 ? "warn" : "info"),
    metric("QEM delta", fmt(q.qem_estimated_fidelity_delta, 5), q.qem_mode || "OFF", q.qem_calibration_enabled ? "ok" : "info"),
    metric("Leakage probability", pct(q.state_leakage_probability), q.state_leakage_active ? "state leakage active" : "nominal subspace", q.state_leakage_active ? "warn" : "ok"),
    metric("Solve-for-X", fmt(q.solve_for_x_reconstruction_score, 4), "reconstruction score", cls(q.solve_for_x_reconstruction_score || 0, .75, .55)),
    metric("Quarantine latency", `${fmt(q.quarantine_latency_seconds, 4)} s`, "leaking channel isolation", q.leaked_channel_indices && q.leaked_channel_indices.length ? "warn" : "ok")
  ].join("");
  el("qiskitDetail").innerHTML = `
    <div>source: <b>${q.source || "N/A"}</b></div>
    <div>QEM: <b>${q.qem_calibration_enabled ? "ON" : "OFF"}</b> | mode: <b>${q.qem_mode || "OFF"}</b></div>
    <div>coherent crosstalk: <b>${q.coherent_crosstalk_active}</b> | state leakage: <b>${q.state_leakage_active}</b></div>
    <div>leaked channel indices: <b>${(q.leaked_channel_indices || []).join(", ") || "-"}</b></div>
    <div>density trace: <b>${fmt(q.density_matrix_trace, 3)}</b> | proxy trace: <b>${fmt(q.proxy_density_trace, 3)}</b></div>`;
  renderQiskitArtifactStatus();
}

function renderQiskitArtifactStatus() {
  const target = el("qiskitArtifact");
  if (!target) return;
  if (!latestQiskitArtifact) {
    target.textContent = "No Qiskit bridge artifact loaded yet.";
    return;
  }
  const summary = latestQiskitArtifact.summary || {};
  const generated = latestQiskitArtifact.generated_at_unix
    ? new Date(latestQiskitArtifact.generated_at_unix * 1000).toLocaleString()
    : "imported artifact";
  target.textContent = [
    `Qiskit artifact: ${latestQiskitArtifact.artifact_type || "qiskit_bridge_run"}`,
    `generated=${generated}`,
    `epochs=${summary.epochs ?? latestQiskitArtifact.cycles ?? "N/A"}`,
    `stopped=${latestQiskitArtifact.stopped_by_operator ? "yes" : "no"}`,
    `mean_q_conf=${fmt(summary.mean_q_conf, 6)}`,
    `gate_pass_count=${summary.gate_pass_count ?? "N/A"}`,
    `final_merkle_root=${summary.final_merkle_root || "N/A"}`
  ].join(" | ");
}

function drawLiveGraph() {
  const canvas = el("liveGraph");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#151515";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#333";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i++) {
    const y = (h / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  const series = [
    ["Q_conf", "#36d17d", item => item.q_conf],
    ["M_c_norm", "#47c7d8", item => item.meaningful_continuity_norm],
    ["Risk", "#f2b84b", item => item.raw_unsafe_output_risk],
    ["Trust", "#ffffff", item => item.trust_index]
  ];
  const data = liveHistory.slice(-72);
  series.forEach(([name, color, getter], si) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((item, idx) => {
      const x = data.length <= 1 ? 0 : (idx / (data.length - 1)) * (w - 20) + 10;
      const y = h - 18 - Math.max(0, Math.min(1, getter(item))) * (h - 38);
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.fillText(name, 12 + si * 112, 16);
  });
}

function drawKappaGraph() {
  const canvas = el("kappaGraph");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#151515";
  ctx.fillRect(0, 0, w, h);
  const series = [
    ["k_node", "#36d17d", item => item.kappa_vector_mean.node],
    ["k_recon", "#47c7d8", item => item.kappa_vector_mean.recon],
    ["k_telemetry", "#f2b84b", item => item.kappa_vector_mean.telemetry]
  ];
  const data = liveHistory.slice(-72);
  series.forEach(([name, color, getter], si) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((item, idx) => {
      const x = data.length <= 1 ? 10 : (idx / (data.length - 1)) * (w - 20) + 10;
      const y = h - 18 - Math.max(0, Math.min(1, getter(item))) * (h - 38);
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.fillText(name, 12 + si * 132, 16);
  });
}

function drawQiskitGraph() {
  const canvas = el("qiskitGraph");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#151515";
  ctx.fillRect(0, 0, w, h);
  const series = [
    ["Fidelity", "#36d17d", item => item.quantum_ingestion_telemetry?.qst_overlap_fidelity ?? 0],
    ["T1 norm", "#47c7d8", item => Math.min(1, (item.quantum_ingestion_telemetry?.t1_thermal_relaxation_us ?? 0) / 72)],
    ["T2 norm", "#f2b84b", item => Math.min(1, (item.quantum_ingestion_telemetry?.t2_dephasing_us ?? 0) / 58)],
    ["Leakage", "#ff6961", item => item.quantum_ingestion_telemetry?.state_leakage_probability ?? 0]
  ];
  const data = liveHistory.slice(-72);
  series.forEach(([name, color, getter], si) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((item, idx) => {
      const x = data.length <= 1 ? 10 : (idx / (data.length - 1)) * (w - 20) + 10;
      const y = h - 18 - Math.max(0, Math.min(1, getter(item))) * (h - 38);
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.fillText(name, 12 + si * 120, 16);
  });
}

function drawCascadeGraph(eta) {
  if (!eta) return;
  const canvas = el("cascadeGraph");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#151515";
  ctx.fillRect(0, 0, w, h);
  const rows = [
    ["Byzantine", eta.byzantine_raw_mean_error, eta.byzantine_filtered_mean_error, eta.eta_byzantine_observed],
    ["Taylor", eta.taylor_raw_mean_error, eta.taylor_projected_mean_error, eta.eta_taylor_observed],
    ["Riemann", eta.riemann_wrapped_accel_variance, eta.riemann_unwrapped_accel_variance, eta.eta_riemann_observed],
  ];
  rows.forEach(([name, raw, filtered, eff], idx) => {
    const y = 38 + idx * 58;
    const rawW = Math.max(4, Math.min(w * 0.38, raw * w * 0.80));
    const filteredW = Math.max(2, Math.min(w * 0.38, filtered * w * 0.80));
    ctx.fillStyle = "#f2b84b";
    ctx.fillRect(140, y, rawW, 16);
    ctx.fillStyle = "#36d17d";
    ctx.fillRect(140, y + 20, filteredW, 16);
    ctx.fillStyle = "#f4f4f4";
    ctx.fillText(`${name} eta ${fmt(eff, 6)}`, 14, y + 13);
    ctx.fillStyle = "#b9b9b9";
    ctx.fillText(`raw ${Number(raw).toExponential(3)} -> filtered ${Number(filtered).toExponential(3)}`, 140, y + 50);
  });
}

function drawCryoGraph() {
  const canvas = el("cryoGraph");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#151515";
  ctx.fillRect(0, 0, w, h);
  const data = liveHistory.slice(-72);
  ctx.strokeStyle = "#47c7d8";
  ctx.lineWidth = 2;
  ctx.beginPath();
  data.forEach((item, idx) => {
    const x = data.length <= 1 ? 10 : (idx / (data.length - 1)) * (w - 20) + 10;
    const y = h - 18 - Math.max(0, Math.min(1, item.cryogenic_scheduler.saturation)) * (h - 38);
    if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const last = data[data.length - 1];
  ctx.fillStyle = "#f4f4f4";
  ctx.fillText("thermal saturation", 12, 16);
  if (last) {
    ctx.fillText(`${fmt(last.cryogenic_scheduler.p_therm_mw, 4)} mW / ${fmt(last.cryogenic_scheduler.thermal_budget_mw, 2)} mW`, 12, 34);
    ctx.fillText(last.cryogenic_scheduler.action, 12, 52);
  }
}

function renderUopLedger() {
  const mc = current ? current.monte_carlo : null;
  const recent = liveHistory.slice(-30);
  const liveOpp = recent.filter(item => item.unsafe_output_opportunity).length;
  const livePrevented = recent.filter(item => item.unsafe_output_opportunity && item.unsafe_output_prevented).length;
  const liveUsr = recent.length ? recent.filter(item => item.unnecessary_shutdown).length / recent.length : 0;
  const uop = liveOpp ? livePrevented / liveOpp : null;
  el("uopLedger").innerHTML = `
    <div>Total UO opportunities: <b>${mc ? mc.unsafe_output_opportunities : "N/A"}</b></div>
    <div>Unsafe outputs prevented: <b>${mc ? mc.unsafe_output_prevented_cycles : "N/A"}</b></div>
    <div>Monte Carlo UOP_eff: <b>${mc ? pct(mc.unsafe_output_prevention_efficiency) : "N/A"}</b></div>
    <div>Live window UOP_eff: <b>${uop === null ? "No live opportunities yet" : pct(uop)}</b></div>
    <div>USR: <b class="${mc && mc.unnecessary_shutdown_target_met ? "ok" : "warn"}">${mc ? pct(mc.unnecessary_shutdown_rate) : "N/A"}</b> | live ${pct(liveUsr)}</div>
    <div class="sub">Target: public v1 99.49%, theoretical boundary 99.925%, USR below 5%.</div>`;
}

function params() {
  const cycles = Number(el("cycles").value || 1000);
  const seed = Number(el("seed").value || 2026);
  return `cycles=${encodeURIComponent(cycles)}&seed=${encodeURIComponent(seed)}`;
}

function summaryText() {
  if (!current) return "No AEGIS monitor data loaded.";
  const mc = current.monte_carlo;
  return [
    "AEGIS Q-SRE Monitor Summary",
    `Generated: ${new Date(current.generated_at_unix * 1000).toLocaleString()}`,
    `Cycles: ${mc.cycles}`,
    `Continuity Yield: ${pct(mc.empirical_continuity_yield)}`,
    `Integrity Preserved: ${pct(mc.integrity_preserved_yield)}`,
    `UOP Efficiency: ${pct(mc.unsafe_output_prevention_efficiency)}`,
    `Unsafe Opportunities: ${mc.unsafe_output_opportunities}`,
    `USR: ${pct(mc.unnecessary_shutdown_rate)}`,
    `Circuit Aborts: ${mc.circuit_abort_count}`
  ].join("\n");
}

function refreshLiveBadge() {
  el("liveState").textContent = liveTimer ? "LIVE ON" : "LIVE OFF";
  el("liveState").style.background = liveTimer ? "var(--green)" : "var(--amber)";
}

async function loadData() {
  el("status").textContent = "Refreshing monitor data...";
  const res = await fetch(`/api/data?${params()}`);
  render(await res.json());
  await loadLatestQiskitArtifact();
  await loadArtifacts();
}

function downloadBlob(filename, content, contentType) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function safeStamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function createArtifact(kind) {
  const res = await fetch(`/api/${kind}?${params()}`, { method: "POST" });
  const data = await res.json();
  if (data.payload) {
    downloadBlob(`aegis_${kind}_${safeStamp()}.json`, JSON.stringify(data.payload, null, 2), "application/json");
  }
  el("artifact").textContent = `${kind.toUpperCase()} saved on server and downloaded: ${data.path}`;
  if (data.payload) render(data.payload);
  await loadArtifacts();
}

async function loadLatestQiskitArtifact() {
  const res = await fetch("/api/qiskit/latest");
  const data = await res.json();
  latestQiskitArtifact = data.payload || null;
  renderQiskitArtifactStatus();
}

async function runQiskitPass() {
  const seed = Number(el("seed").value || 2026);
  const params = new URLSearchParams({
    cycles: "24",
    shots: "2048",
    seed: String(seed),
    noise_scale: String(Number(el("qiskitNoise").value || 1.00)),
    crosstalk_inject: String(el("qiskitXtalk").checked),
    leakage_lambda: String(Number(el("qiskitLeakage").value || 0.00)),
    measurement_efficiency: String(Number(el("innovationEta").value || 0.82))
  });
  el("qiskitArtifact").textContent = "Running Qiskit Aer bridge and saving server artifact...";
  el("runQiskit").disabled = true;
  try {
  const res = await fetch(`/api/qiskit/run?${params.toString()}`, { method: "POST" });
  const data = await res.json();
  if (data.status === "error") {
    el("qiskitArtifact").textContent = `Qiskit bridge error: ${data.error}`;
    return;
  }
  latestQiskitArtifact = data.payload || null;
  if (latestQiskitArtifact) {
    downloadBlob(`aegis_qiskit_bridge_${safeStamp()}.json`, JSON.stringify(latestQiskitArtifact, null, 2), "application/json");
  }
  el("artifact").textContent = `Qiskit bridge run saved on server and downloaded: ${data.path}`;
  renderQiskitArtifactStatus();
  await loadArtifacts();
  } finally {
    el("runQiskit").disabled = false;
  }
}

async function stopQiskitPass() {
  const res = await fetch("/api/qiskit/stop", { method: "POST" });
  const data = await res.json();
  el("qiskitArtifact").textContent = `${data.status}: Qiskit stop requested. Live monitor remains active.`;
}

async function saveQiskitJson() {
  if (!latestQiskitArtifact) {
    await loadLatestQiskitArtifact();
  }
  if (!latestQiskitArtifact) {
    await runQiskitPass();
    return;
  }
  const res = await fetch("/api/qiskit/import", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(latestQiskitArtifact)
  });
  const data = await res.json();
  latestQiskitArtifact = data.payload || latestQiskitArtifact;
  el("artifact").textContent = `Qiskit artifact saved on server: ${data.path}`;
  renderQiskitArtifactStatus();
  await loadArtifacts();
}

async function exportQiskitJson() {
  let res = await fetch("/api/qiskit/export");
  let data = await res.json();
  if (!data.payload) {
    await runQiskitPass();
    return;
  }
  latestQiskitArtifact = data.payload;
  downloadBlob(`aegis_qiskit_bridge_${safeStamp()}.json`, JSON.stringify(latestQiskitArtifact, null, 2), "application/json");
  el("artifact").textContent = "Qiskit bridge JSON exported.";
  renderQiskitArtifactStatus();
}

function importQiskitJson() {
  el("qiskitImportFile").click();
}

async function handleQiskitImport(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const res = await fetch("/api/qiskit/import", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.status === "error") {
      el("qiskitArtifact").textContent = `Qiskit import error: ${data.error}`;
      return;
    }
    latestQiskitArtifact = data.payload;
    el("artifact").textContent = `Qiskit bridge JSON imported and saved: ${data.path}`;
    renderQiskitArtifactStatus();
    await loadArtifacts();
  } catch (err) {
    el("qiskitArtifact").textContent = `Qiskit import error: ${err.message}`;
  } finally {
    event.target.value = "";
  }
}

async function loadArtifacts() {
  const res = await fetch("/api/artifacts");
  const artifacts = await res.json();
  if (!artifacts.length) {
    el("artifactList").innerHTML = "<div class='sub'>No artifacts written yet.</div>";
    return;
  }
  el("artifactList").innerHTML = `<table><thead><tr><th>Name</th><th>Size</th><th>Modified</th></tr></thead><tbody>${
    artifacts.map(a => `<tr><td class="mono">${a.name}</td><td>${a.size_bytes}</td><td>${new Date(a.modified_unix * 1000).toLocaleString()}</td></tr>`).join("")
  }</tbody></table>`;
}

function startLive() {
  if (liveTimer) return;
  liveTimer = setInterval(loadLive, 1200);
  refreshLiveBadge();
  loadLive();
}

function stopLive() {
  if (liveTimer) clearInterval(liveTimer);
  liveTimer = null;
  refreshLiveBadge();
}

async function loadLive() {
  const seed = Number(el("seed").value || 2026);
  const res = await fetch(`/api/live?seed=${encodeURIComponent(seed)}`);
  renderLive(await res.json());
}

function controlPayload() {
  return {
    disruption: el("disruption").value,
    spoof_percent: Number(el("spoofPercent").value || 0) / 100,
    kp: Number(el("kpGain").value || 1),
    kd: Number(el("kdGain").value || 0.45),
    theta_backaction: Number(el("thetaBackaction").value || 0.40),
    anchor_decay_lambda: Number(el("anchorLambda").value || 0.55),
    omega_drive: Number(el("omegaDrive").value || 0.35),
    innovation_eta: Number(el("innovationEta").value || 0.82),
    zne_lambda: Number(el("zneLambda").value || 1.00),
    qiskit_noise_scale: Number(el("qiskitNoise").value || 1.00),
    qiskit_leakage_lambda: Number(el("qiskitLeakage").value || 0.00),
    qiskit_crosstalk_inject: el("qiskitXtalk").checked,
    reviewer_mode: el("reviewerMode").checked,
    rb_interleave: el("rbInterleave").checked,
    qem_calibration: el("qemCalibration").checked,
    relativistic_comp: el("relativisticComp").checked
  };
}

function syncControlLabels() {
  el("spoofVal").textContent = `${el("spoofPercent").value}%`;
  el("kpVal").textContent = Number(el("kpGain").value).toFixed(2);
  el("kdVal").textContent = Number(el("kdGain").value).toFixed(2);
  el("thetaVal").textContent = Number(el("thetaBackaction").value).toFixed(2);
  el("lambdaVal").textContent = Number(el("anchorLambda").value).toFixed(2);
  el("omegaVal").textContent = Number(el("omegaDrive").value).toFixed(2);
  el("etaVal").textContent = Number(el("innovationEta").value).toFixed(2);
  el("zneVal").textContent = Number(el("zneLambda").value).toFixed(2);
  el("qiskitNoiseVal").textContent = Number(el("qiskitNoise").value).toFixed(2);
  el("qiskitLeakVal").textContent = Number(el("qiskitLeakage").value).toFixed(2);
  const reviewer = el("reviewerMode").checked;
  document.body.classList.toggle("reviewer", reviewer);
  el("reviewerModeToggle").textContent = reviewer ? "Reviewer Mode: ON" : "Reviewer Mode: OFF";
  el("reviewerModeToggle").className = reviewer ? "primary" : "";
  let latest = liveHistory.length ? liveHistory[liveHistory.length - 1] : null;
  if (!latest && current && current.deterministic_suite && current.deterministic_suite.length) {
    latest = current.deterministic_suite[current.deterministic_suite.length - 1];
  }
  if (el("reviewerMetrics")) renderReviewerPanel(latest);
}

async function pushControls() {
  syncControlLabels();
  const res = await fetch("/api/live/control", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(controlPayload())
  });
  const data = await res.json();
  el("overrideStatus").textContent = `Controls updated: ${data.control_state.disruption}`;
}

async function toggleReviewerMode() {
  el("reviewerMode").checked = !el("reviewerMode").checked;
  await pushControls();
}

async function resetHardAbort() {
  const res = await fetch("/api/override/reset_hard_abort", { method: "POST" });
  const data = await res.json();
  liveHistory = [];
  el("overrideStatus").textContent = data.status;
  await loadLive();
}

async function initRecoveryValidate() {
  const res = await fetch("/api/override/recovery_validate", { method: "POST" });
  const data = await res.json();
  el("overrideStatus").textContent = `${data.status}: ${data.remaining_validation_cycles} cycles`;
  await loadLive();
}

async function exportQomHex() {
  let res = await fetch("/api/export/qom");
  let data = await res.json();
  if (!data.qom_compact_payload_hex) {
    await loadLive();
    res = await fetch("/api/export/qom");
    data = await res.json();
  }
  const hex = data.qom_compact_payload_hex || "";
  const text = [
    "AEGIS .QOM Compact Payload Export",
    `generated_at=${new Date().toISOString()}`,
    `bits=${data.qom_compact_payload_bits || "N/A"}`,
    `opte_policy_context_hash=${data.opte_policy_context_hash || "N/A"}`,
    `merkle_root=${data.merkle_root || "N/A"}`,
    `qom_compact_payload_hex=${hex}`
  ].join("\n");
  downloadBlob(`aegis_qom_frame_${safeStamp()}.txt`, text, "text/plain");
  try {
    await navigator.clipboard.writeText(hex);
    el("artifact").textContent = `.QOM hex downloaded and copied to clipboard: ${hex || "no live frame yet"}`;
  } catch (err) {
    el("artifact").textContent = `.QOM hex downloaded: ${hex || "no live frame yet"}`;
  }
}

async function forensicCertificate() {
  const res = await fetch("/api/export/birth_certificate", { method: "POST" });
  const data = await res.json();
  if (data.payload) {
    downloadBlob(`aegis_forensic_certificate_${safeStamp()}.json`, JSON.stringify(data.payload, null, 2), "application/json");
  }
  el("artifact").textContent = `FORENSIC CERTIFICATE saved on server and downloaded: ${data.path}`;
  await loadArtifacts();
}

async function resetLive() {
  const seed = Number(el("seed").value || 2026);
  const res = await fetch(`/api/live/reset?seed=${encodeURIComponent(seed)}`, { method: "POST" });
  await res.json();
  liveHistory = [];
  await loadLive();
}

function downloadCurrent() {
  if (!current) return;
  downloadBlob(`aegis_monitor_current_${safeStamp()}.json`, JSON.stringify(current, null, 2), "application/json");
}

async function stopServer() {
  stopLive();
  el("status").textContent = "Stopping monitor server...";
  try {
    await fetch("/api/stop", { method: "POST" });
    el("status").textContent = "Monitor server stopped. Restart it with: python aegis_monitor.py";
  } catch (err) {
    el("status").textContent = "Stop signal sent. Restart it with: python aegis_monitor.py";
  }
}

el("startLive").addEventListener("click", startLive);
el("stopLive").addEventListener("click", stopLive);
el("resetLive").addEventListener("click", resetLive);
el("refresh").addEventListener("click", loadData);
el("reviewerModeToggle").addEventListener("click", toggleReviewerMode);
["disruption", "spoofPercent", "kpGain", "kdGain", "thetaBackaction", "anchorLambda", "omegaDrive", "innovationEta", "zneLambda", "qiskitNoise", "qiskitLeakage", "qiskitXtalk", "reviewerMode", "rbInterleave", "qemCalibration", "relativisticComp"].forEach(id => {
  el(id).addEventListener("input", pushControls);
  el(id).addEventListener("change", pushControls);
});
el("resetHardAbort").addEventListener("click", resetHardAbort);
el("initRecovery").addEventListener("click", initRecoveryValidate);
el("exportQom").addEventListener("click", exportQomHex);
el("birthCert").addEventListener("click", forensicCertificate);
el("snapshot").addEventListener("click", () => createArtifact("snapshot"));
el("report").addEventListener("click", () => createArtifact("report"));
el("runQiskit").addEventListener("click", runQiskitPass);
el("stopQiskit").addEventListener("click", stopQiskitPass);
el("saveQiskit").addEventListener("click", saveQiskitJson);
el("exportQiskit").addEventListener("click", exportQiskitJson);
el("importQiskit").addEventListener("click", importQiskitJson);
el("qiskitImportFile").addEventListener("change", handleQiskitImport);
el("copySummary").addEventListener("click", async () => {
  await navigator.clipboard.writeText(summaryText());
  el("artifact").textContent = "Summary copied to clipboard.";
});
el("downloadCurrent").addEventListener("click", downloadCurrent);
el("stopServer").addEventListener("click", stopServer);
syncControlLabels();
refreshLiveBadge();
loadData();
</script>
</body>
</html>
"""


class MonitorHandler(BaseHTTPRequestHandler):
    server_version = "AegisQSRMonitor/1.0"

    def send_payload(self, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_payload(HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/data":
            query = parse_qs(parsed.query)
            cycles = int(query.get("cycles", ["1000"])[0])
            seed = int(query.get("seed", ["2026"])[0])
            self.send_payload(json_bytes(build_monitor_payload(cycles=cycles, seed=seed)))
            return
        if parsed.path == "/api/live":
            query = parse_qs(parsed.query)
            seed = int(query.get("seed", [str(LIVE_RUNTIME.seed)])[0])
            if seed != LIVE_RUNTIME.seed:
                LIVE_RUNTIME.reset(seed)
            self.send_payload(json_bytes(LIVE_RUNTIME.next_tick()))
            return
        if parsed.path == "/api/artifacts":
            self.send_payload(json_bytes(list_artifacts()))
            return
        if parsed.path == "/api/health":
            payload = build_health_payload()
            payload["qiskit_bridge_running"] = QISKIT_RUNNING
            payload["qiskit_stop_requested"] = QISKIT_STOP_EVENT.is_set()
            self.send_payload(json_bytes(payload))
            return
        if parsed.path in {"/api/qiskit/latest", "/api/qiskit/export"}:
            payload = latest_qiskit_bridge_payload()
            self.send_payload(
                json_bytes(
                    {
                        "status": "ok" if payload else "no_qiskit_artifact",
                        "payload": payload,
                    }
                )
            )
            return
        if parsed.path == "/api/export/qom":
            current = LIVE_RUNTIME.current_payload()
            self.send_payload(
                json_bytes(
                    {
                        "status": "ok" if current else "no_live_frame",
                        "qom_compact_payload_bits": current.get("qom_compact_payload_bits") if current else None,
                        "qom_compact_payload_hex": current.get("qom_compact_payload_hex") if current else None,
                        "opte_policy_context_hash": current.get("opte_policy_context_hash") if current else None,
                        "merkle_root": current.get("merkle_root") if current else None,
                    }
                )
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        global LATEST_QISKIT_BRIDGE, QISKIT_RUNNING
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        cycles = int(query.get("cycles", ["1000"])[0])
        seed = int(query.get("seed", ["2026"])[0])
        if parsed.path == "/api/snapshot":
            payload = build_monitor_payload(cycles=cycles, seed=seed)
            path = write_json_artifact("snapshot", payload)
            self.send_payload(json_bytes({"path": str(path), "payload": payload}))
            return
        if parsed.path == "/api/report":
            payload = build_monitor_payload(cycles=max(cycles, 2500), seed=seed)
            path = write_json_artifact("report", payload)
            self.send_payload(json_bytes({"path": str(path), "payload": payload}))
            return
        if parsed.path == "/api/live/reset":
            self.send_payload(json_bytes(LIVE_RUNTIME.reset(seed)))
            return
        if parsed.path == "/api/live/control":
            self.send_payload(json_bytes(LIVE_RUNTIME.update_controls(self.read_json_body())))
            return
        if parsed.path == "/api/override/reset_hard_abort":
            self.send_payload(json_bytes(LIVE_RUNTIME.reset_hard_abort()))
            return
        if parsed.path == "/api/override/recovery_validate":
            self.send_payload(json_bytes(LIVE_RUNTIME.init_recovery_validate()))
            return
        if parsed.path == "/api/export/birth_certificate":
            current = LIVE_RUNTIME.current_payload()
            if not current:
                LIVE_RUNTIME.next_tick()
                current = LIVE_RUNTIME.current_payload()
            certificate = build_forensic_certificate(current or {})
            path = write_json_artifact("forensic_birth_certificate", certificate)
            self.send_payload(json_bytes({"path": str(path), "payload": certificate}))
            return
        if parsed.path == "/api/qiskit/run":
            if QISKIT_RUNNING:
                self.send_payload(json_bytes({"status": "error", "error": "Qiskit bridge is already running."}))
                return
            QISKIT_STOP_EVENT.clear()
            q_cycles = max(1, min(50, int(query.get("cycles", ["6"])[0])))
            shots = max(128, min(8192, int(query.get("shots", ["2048"])[0])))
            noise_scale = max(0.1, min(5.0, float(query.get("noise_scale", ["1.0"])[0])))
            crosstalk_inject = str(query.get("crosstalk_inject", ["false"])[0]).lower() in {"1", "true", "yes", "on"}
            leakage_lambda = max(0.0, min(1.0, float(query.get("leakage_lambda", ["0.0"])[0])))
            measurement_efficiency = max(0.1, min(1.0, float(query.get("measurement_efficiency", ["0.82"])[0])))
            try:
                QISKIT_RUNNING = True
                payload = run_qiskit_bridge_payload(
                    cycles=q_cycles,
                    shots=shots,
                    seed=seed,
                    noise_scale=noise_scale,
                    crosstalk_inject=crosstalk_inject,
                    leakage_lambda=leakage_lambda,
                    measurement_efficiency=measurement_efficiency,
                )
            except Exception as exc:
                self.send_payload(json_bytes({"status": "error", "error": str(exc)}))
                return
            finally:
                QISKIT_RUNNING = False
            LATEST_QISKIT_BRIDGE = payload
            path = write_json_artifact("qiskit_bridge", payload)
            self.send_payload(json_bytes({"status": "ok", "path": str(path), "payload": payload}))
            return
        if parsed.path == "/api/qiskit/stop":
            QISKIT_STOP_EVENT.set()
            self.send_payload(json_bytes({"status": "QISKIT_STOP_REQUESTED", "qiskit_bridge_running": QISKIT_RUNNING}))
            return
        if parsed.path == "/api/qiskit/import":
            try:
                payload = self.read_json_body()
                if not isinstance(payload, dict):
                    raise ValueError("Imported Qiskit payload must be a JSON object.")
                payload.setdefault("artifact_type", "qiskit_bridge_import")
                payload["imported_at_unix"] = time.time()
            except Exception as exc:
                self.send_payload(json_bytes({"status": "error", "error": str(exc)}))
                return
            LATEST_QISKIT_BRIDGE = payload
            path = write_json_artifact("qiskit_import", payload)
            self.send_payload(json_bytes({"status": "ok", "path": str(path), "payload": payload}))
            return
        if parsed.path == "/api/stop":
            self.send_payload(json_bytes({"status": "stopping"}))
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS Q-SRE local monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MonitorHandler)
    print(f"AEGIS monitor running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
