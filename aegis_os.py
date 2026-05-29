from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from aegis_kernel import (
    AegisContinuityKernel,
    build_nominal_telemetry,
    calculate_projection_validation,
    estimate_observed_cascade_efficiencies,
    run_monte_carlo,
)


PIPELINE = [
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
]


def scenario_for_step(step: int) -> str:
    if step <= 50:
        return "normal"
    if step <= 100:
        return "storm"
    if step >= 145:
        return "anchor_dispute"
    return "attack"


def phase_name(step: int) -> str:
    if step <= 50:
        return "BASELINE"
    if step <= 100:
        return "STORM"
    return "ADVERSARIAL"


def print_cycle_line(step: int, result) -> None:
    states = "|".join(result.governance_states)
    causes = ",".join(result.hard_abort_causes) if result.hard_abort_causes else "-"
    print(
        f"{step:03d} {phase_name(step):11s} "
        f"gate={'PASS' if result.continuity_gate_passed else 'HOLD':4s} "
        f"integrity={'YES' if result.integrity_preserved else 'NO ':3s} "
        f"q={result.q_conf:0.4f} mc={result.meaningful_continuity_norm:0.4f} "
        f"risk={result.raw_unsafe_output_risk:0.4f} trust={result.trust_index:0.4f} "
        f"qom={result.qom_compact_payload_bits}b states={states} causes={causes}"
    )


def summarize(results: list, monte_carlo: dict[str, object], eta: dict[str, float], projection: dict[str, object]) -> dict[str, object]:
    unsafe_opportunities = sum(1 for result in results if result.unsafe_output_opportunity)
    unsafe_prevented = sum(1 for result in results if result.unsafe_output_opportunity and result.unsafe_output_prevented)
    continuity_success = sum(1 for result in results if result.continuity_gate_passed and result.abort_tier in {"NONE", "SOFT_ABORT"})
    integrity_preserved = sum(1 for result in results if result.integrity_preserved)
    unnecessary_shutdowns = sum(1 for result in results if result.unnecessary_shutdown)
    return {
        "step_count": len(results),
        "pipeline": PIPELINE,
        "timeline": {
            "baseline": "steps 1-50",
            "storm": "steps 51-100",
            "adversarial": "steps 101-150",
        },
        "continuity_yield": continuity_success / max(1, len(results)),
        "integrity_preserved_yield": integrity_preserved / max(1, len(results)),
        "unsafe_output_opportunities": unsafe_opportunities,
        "unsafe_outputs_prevented": unsafe_prevented,
        "unsafe_output_prevention_efficiency": unsafe_prevented / max(1, unsafe_opportunities),
        "unnecessary_shutdown_rate": unnecessary_shutdowns / max(1, len(results)),
        "monte_carlo": monte_carlo,
        "observed_eta": eta,
        "projection_validation": projection,
        "final_merkle_root": results[-1].merkle_root if results else None,
        "final_qom_compact_payload_bits": results[-1].qom_compact_payload_bits if results else None,
        "final_opte_policy_context_hash": results[-1].opte_policy_context_hash if results else None,
    }


def run_master_suite(seed: int, monte_carlo_cycles: int, reviewer_mode: bool) -> dict[str, object]:
    kernel = AegisContinuityKernel(seed=seed)
    rng = kernel.random
    results = []
    if not reviewer_mode:
        print("=" * 118)
        print("AEGIS Site Reliability Control-Plane Simulation Suite")
        print("Canonical runtime loop: " + " -> ".join(PIPELINE))
        print("=" * 118)
    for step in range(1, 151):
        scenario = scenario_for_step(step)
        telemetry = build_nominal_telemetry(kernel.config.node_count, rng, scenario)
        result = kernel.execute_cycle(telemetry, scenario=f"{phase_name(step).lower()}_step_{step}")
        results.append(result)
        if not reviewer_mode:
            print_cycle_line(step, result)
    monte_carlo = run_monte_carlo(cycles=monte_carlo_cycles, seed=seed)
    eta = estimate_observed_cascade_efficiencies(seed=seed)
    projection = calculate_projection_validation()
    summary = summarize(results, monte_carlo, eta, projection)
    if reviewer_mode:
        final = results[-1]
        telemetry = final.reviewer_telemetry
        cryo = final.cryogenic_scheduler
        hardware = final.hardware_register_target
        print("AEGIS site reliability reviewer metrics")
        print(f"steps={summary['step_count']}")
        print(f"continuity_yield={summary['continuity_yield']:.6f}")
        print(f"integrity_preserved_yield={summary['integrity_preserved_yield']:.6f}")
        print(f"uop_opportunities={summary['unsafe_output_opportunities']}")
        print(f"uop_efficiency={summary['unsafe_output_prevention_efficiency']:.6f}")
        print(f"usr={summary['unnecessary_shutdown_rate']:.6f}")
        print(f"eta_byzantine={eta['eta_byzantine_observed']:.6f}")
        print(f"eta_taylor={eta['eta_taylor_observed']:.6f}")
        print(f"eta_riemann={eta['eta_riemann_observed']:.6f}")
        print(f"qom_payload_bits={summary['final_qom_compact_payload_bits']}")
        print(f"rmse_phase_skew_rad={telemetry['rmse_phase_skew_rad']:.6f}")
        print(f"packet_jitter_ns={telemetry['packet_transmission_jitter_ns']:.6f}")
        print(f"shannon_entropy_bound_bits={telemetry['shannon_entropy_bound_bits']:.6f}")
        print(f"data_compression_ratio={telemetry['data_compression_ratio']:.3f}")
        print(f"packet_latency_bound_ms={telemetry['packet_latency_bound_ms']:.6f}")
        print(f"cryo_p_therm_mw={cryo['p_therm_mw']:.6f}")
        print(f"cryo_saturation={cryo['saturation']:.6f}")
        print(f"register_o_quantization_window_ns={hardware['o_quantization_window_ns']}")
        print(f"gate_open={hardware['gate_open']}")
    else:
        print("=" * 118)
        print("SUMMARY")
        print(f"Continuity yield                 : {summary['continuity_yield']:.6f}")
        print(f"Integrity preserved yield        : {summary['integrity_preserved_yield']:.6f}")
        print(f"Unsafe-output opportunities      : {summary['unsafe_output_opportunities']}")
        print(f"Unsafe-output prevention eff.    : {summary['unsafe_output_prevention_efficiency']:.6f}")
        print(f"Unnecessary shutdown rate        : {summary['unnecessary_shutdown_rate']:.6f}")
        print(f"Observed eta Byzantine/Taylor/Riemann: {eta['eta_byzantine_observed']:.6f} / {eta['eta_taylor_observed']:.6f} / {eta['eta_riemann_observed']:.6f}")
        print(f"Final Merkle root                : {summary['final_merkle_root']}")
        print(f"Final .QOM compact payload       : {summary['final_qom_compact_payload_bits']} bits")
    return {
        "generated_at_unix": time.time(),
        "seed": seed,
        "summary": summary,
        "cycles": [asdict(result) for result in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS site reliability 150-cycle simulation suite")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--monte-carlo-cycles", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("aegis_os_report.json"))
    parser.add_argument("--reviewer-mode", action="store_true")
    parser.add_argument(
        "--mode",
        choices=["standard", "reviewer"],
        default=None,
        help="Output mode. Equivalent to --reviewer-mode when set to reviewer.",
    )
    args = parser.parse_args()
    reviewer_mode = (
        args.reviewer_mode
        or args.mode == "reviewer"
        or os.environ.get("AEGIS_REVIEWER_MODE", "").lower() in {"1", "true", "yes", "on"}
    )
    payload = run_master_suite(args.seed, args.monte_carlo_cycles, reviewer_mode)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not reviewer_mode:
        print(f"Report written: {args.output}")


if __name__ == "__main__":
    main()
