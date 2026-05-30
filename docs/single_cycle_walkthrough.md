# Single-Cycle Walkthrough

This walkthrough describes one AEGIS cycle after a simulator or IBM Quantum job has returned counts.

1. Ingest returned output.
   The IBM bridge converts count histograms into telemetry records. No circuit is modified while the job is running.

2. Score telemetry.
   AEGIS estimates environment severity, node trust (`kappa`), quorum weight, anchor drift, and `q_conf`. These are workload-quality and governance proxies, not direct physical-device measurements.

3. Govern state.
   The state governor sets software governance flags such as phase hold, anchor dispute, crypto seal, or abort states when thresholds are crossed.

4. Gate the result.
   The continuity gate compares normalized meaningful continuity, `q_conf`, and anchor status against frozen thresholds. A failed gate prevents the result from being treated as accepted evidence.

5. Emit metadata.
   Accepted and rejected cycles can emit compact `.QOM` metadata, reviewer telemetry, and policy-context hashes. The compression ratio is computed from raw telemetry JSON bytes divided by compact `.QOM` payload bytes.

6. Write lineage.
   The cycle writes a ledger block with a Merkle root, parent hash, governance mask, and signature. This makes later artifact verification and tamper checks possible.

7. Select later work.
   Adaptive scripts may use the result to choose a future backend, layout, mitigation policy, or control-policy candidate. This is later workload selection, not real-time control of a running public QPU job.

For implementation details, see `AegisContinuityKernel.execute_cycle()` and the stateless scoring helpers in `aegis_scoring.py`.
