from __future__ import annotations

import json
import math
import statistics
from typing import Callable, Iterable, Sequence


Q_CONF_WEIGHTS = {
    # Calibration note: these heuristic weights were frozen for the 2026-05
    # IBM GHZ validation campaign to blend node trust, vector consistency, and
    # environmental quality. They are not theoretically derived constants.
    "mean_kappa": 0.45,
    "vector_norm": 0.35,
    "weather_quality": 0.20,
}

ENVIRONMENT_SEVERITY_WEIGHTS = {
    # Heuristic operational-risk mix used by the simulator. Radiation and
    # electromagnetic pressure are weighted slightly higher because historical
    # stress scenarios made them better predictors of unsafe-output risk.
    "thermal": 0.18,
    "electromagnetic": 0.22,
    "voltage": 0.18,
    "radiation": 0.24,
    "latency": 0.18,
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def environment_severity(thermal: float, electromagnetic: float, voltage: float, radiation: float, latency: float) -> float:
    weights = ENVIRONMENT_SEVERITY_WEIGHTS
    return clamp(
        weights["thermal"] * thermal
        + weights["electromagnetic"] * electromagnetic
        + weights["voltage"] * voltage
        + weights["radiation"] * radiation
        + weights["latency"] * latency
    )


def calculate_q_conf_score(fused_vector: Sequence[float], kappa_values: Iterable[float], environmental_severity: float) -> float:
    kappa_list = list(kappa_values)
    mean_kappa = statistics.fmean(kappa_list) if kappa_list else 0.0
    vector_norm = clamp(math.sqrt(sum(axis * axis for axis in fused_vector)))
    weather_quality = 1.0 - environmental_severity
    weights = Q_CONF_WEIGHTS
    return clamp(
        weights["mean_kappa"] * mean_kappa
        + weights["vector_norm"] * vector_norm
        + weights["weather_quality"] * weather_quality
    )


def normalize_meaningful_continuity_score(raw_score: float, normalization_target: float) -> float:
    return clamp(raw_score / max(1e-12, normalization_target))


def resolve_gate_thresholds_for_scenario(
    scenario: str,
    normal_thresholds: tuple[float, float],
    storm_thresholds: tuple[float, float],
    adversarial_thresholds: tuple[float, float],
) -> tuple[float, float]:
    lowered = scenario.lower()
    if "storm" in lowered:
        return storm_thresholds
    if any(label in lowered for label in ("attack", "adversarial", "anchor_dispute", "crypto_seal")):
        return adversarial_thresholds
    return normal_thresholds


def compact_payload_compression_ratio(raw_payload: object, compact_payload_bytes: int) -> tuple[float, int, int]:
    raw_bytes = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    compact_bytes = max(1, int(compact_payload_bytes))
    return len(raw_bytes) / compact_bytes, len(raw_bytes), compact_bytes
