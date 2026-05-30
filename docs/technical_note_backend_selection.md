# Technical Note: Adaptive Backend Selection

## Question

Can AEGIS use short probe jobs to route later QPU workloads toward a stronger backend under the same claim boundary?

## Method

AEGIS probes candidate IBM Quantum backends with the same GHZ-style workload, scores returned outputs using GHZ population, `q_conf`, latency, and risk, then commits a later workload to the selected backend.

The selector is a cloud-QPU workload router. It does not modify IBM hardware, calibrations, or running circuits.

## Current Evidence

The 2026-05-29 campaign includes real IBM jobs comparing `ibm_marrakesh` and `ibm_kingston`. In the recorded backend-selector run, AEGIS selected `ibm_marrakesh`; the committed run passed continuity and achieved GHZ `95.70%`. The `ibm_kingston` probe was weaker and failed continuity at GHZ `87.11%`.

Follow-up Test A has also shown:

- `ibm_marrakesh`: accepted-vs-rejected split passed at a `0.94` GHZ threshold.
- `ibm_kingston`: completed but had no accepted cohort at that threshold.
- `ibm_fez`: run was pending/in-flight at the time this note was drafted.

## Limits

This is evidence for adaptive workload routing over returned outputs, not evidence of hardware noise suppression. Stronger claims require repeated three-backend selection cycles, matched random/default baselines, and confidence intervals.

## Conservative Claim

AEGIS can act as an adaptive backend-routing layer for cloud QPU workloads by probing candidate backends, scoring returned outputs, and committing later jobs to the strongest observed execution path.
