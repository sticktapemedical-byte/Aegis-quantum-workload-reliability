from aegis_scoring import (
    calculate_q_conf_score,
    compact_payload_compression_ratio,
    environment_severity,
    normalize_meaningful_continuity_score,
    resolve_gate_thresholds_for_scenario,
)


def test_environment_severity_uses_weighted_proxy():
    value = environment_severity(thermal=0.1, electromagnetic=0.2, voltage=0.3, radiation=0.4, latency=0.5)
    assert round(value, 4) == 0.302


def test_q_conf_score_rewards_kappa_vector_and_weather():
    low = calculate_q_conf_score([0.6, 0.0, 0.0], [0.5, 0.5], 0.5)
    high = calculate_q_conf_score([1.0, 0.0, 0.0], [0.9, 0.95], 0.1)
    assert high > low


def test_gate_threshold_resolution_is_stateless():
    normal = (0.72, 0.90)
    storm = (0.12, 0.70)
    adversarial = (0.55, 0.82)
    assert resolve_gate_thresholds_for_scenario("runtime", normal, storm, adversarial) == normal
    assert resolve_gate_thresholds_for_scenario("storm_front", normal, storm, adversarial) == storm
    assert resolve_gate_thresholds_for_scenario("crypto_seal", normal, storm, adversarial) == adversarial


def test_compression_ratio_is_measured_from_payload_size():
    ratio, raw_bytes, compact_bytes = compact_payload_compression_ratio({"counts": {"00": 10, "11": 5}}, 5)
    assert compact_bytes == 5
    assert raw_bytes > compact_bytes
    assert ratio == raw_bytes / compact_bytes


def test_meaningful_continuity_normalization_clamps():
    assert normalize_meaningful_continuity_score(9.2, 18.4) == 0.5
    assert normalize_meaningful_continuity_score(100.0, 18.4) == 1.0
