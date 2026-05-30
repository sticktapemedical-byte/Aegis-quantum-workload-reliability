from examples.adaptive_coherence_controller import fit_effective_decay, synthetic_arm


def test_delay_ramp_outputs_teff_fit():
    arm = synthetic_arm([0.0, 1.0, 2.0, 5.0], "aegis_selected")
    assert arm["fit"]["t_eff_ms"] > 0
    assert len(arm["records"]) == 4


def test_effective_decay_fit_orders_longer_survival():
    short = fit_effective_decay([0, 1, 2], [1.0, 0.6, 0.36])
    long = fit_effective_decay([0, 1, 2], [1.0, 0.8, 0.64])
    assert long["t_eff_ms"] > short["t_eff_ms"]


def test_effective_decay_fit_marks_flat_or_improving_data_invalid():
    flat = fit_effective_decay([0, 1, 2], [0.95, 0.95, 0.95])
    improving = fit_effective_decay([0, 1, 2], [0.90, 0.92, 0.94])
    assert flat["valid"] is False
    assert flat["t_eff_ms"] is None
    assert improving["valid"] is False
    assert improving["fit_status"] == "no_negative_decay_slope"
