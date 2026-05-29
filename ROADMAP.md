# AEGIS Roadmap

This roadmap separates implemented software from simulation models, future hardware targets, and speculative research ideas.

## Implemented Now

- Standard-library Python site reliability control-plane simulation.
- Deterministic scenario runner in `aegis_os.py`.
- Core kernel logic in `aegis_kernel.py`.
- Local HTTP monitor in `aegis_monitor.py`.
- `.QOM` compact metadata frame generation with 176-bit payload checks.
- Merkle/HMAC lineage blocks and forensic JSON artifacts.
- Reviewer-mode output and grounded metrics.
- Unit and grounding tests under `tests/`.
- Optional Qiskit Aer bridge under `examples/`.
- Dockerfile for reproducible local test execution.

## Simulated

- Environmental telemetry vectors.
- Weighted Byzantine node filtering.
- Wrapped-delta phase unwrapping.
- Fail-closed governance states.
- Hardware register boundary diagnostics.
- Cryogenic scheduler telemetry.
- Secure enclave/key lineage visualization.
- Qiskit noise, crosstalk, leakage, and measurement-efficiency stressors.

## Future Hardware Target

- Hardware-in-the-loop telemetry ingestion.
- FPGA/ASIC register mapping for `G(t)` gate control.
- Real device timing traces and scheduler latency measurements.
- Integration with laboratory quantum device logs or vendor simulator traces.
- Larger multi-node parameter sweeps beyond the current 12-node default.

## Speculative Research

- Site reliability engineering patterns for probabilistic hardware interfaces.
- Production-grade `.QOM` middleware semantics.
- Long-distance mesh telemetry orchestration.
- Hardware-aware economic scheduling models.

## Naming Guidance

For technical review, use **site reliability control plane** or **simulation framework for probabilistic telemetry**. Avoid presenting the project as a physical “Quantum OS” unless explicitly discussing long-term vision or historical branding.
