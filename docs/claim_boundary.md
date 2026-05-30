# Claim Boundary

AEGIS is an experimental quantum workload reliability framework for returned QPU outputs and probabilistic telemetry. It is designed to test whether adaptive selection, classical governance, fail-closed rules, compact metadata, and lineage can improve accepted-result quality and resource efficiency under tested conditions.

## Safe Current Claim

AEGIS ingests simulator outputs or real IBM Quantum count histograms, maps them into telemetry, applies classical governance, emits `.QOM` metadata, and writes Merkle lineage over returned job outputs.

AEGIS terminology such as scheduler, vault, register, and kernel refers to software-side control-plane models in this repository unless a section explicitly identifies external hardware integration evidence.

## Improved Claim Supported By Current Harnesses

AEGIS can reject, warn on, or fail-close lower-quality returned outputs and can use probe results to select later execution paths such as backend, layout, and mitigation policy.

## Claim To Earn With More Controlled Evidence

AEGIS-selected control policies may improve measured coherence-sensitive workload survival under tested conditions when validated against matched baselines.

This wording is intentionally narrower than claiming a change to hardware-level coherence.

## Do Not Claim

- AEGIS improves intrinsic qubit coherence.
- AEGIS changes chip materials, device physics, refrigerator behavior, or hardware calibration.
- AEGIS solves decoherence.
- AEGIS replaces quantum error correction.
- AEGIS controls a public IBM QPU while a circuit is actively running, except where an explicit IBM-supported dynamic-circuit feature is used and reported as such.
- AEGIS is a universal physical quantum operating system.
- AEGIS contains production RTL, FPGA firmware, ASIC implementation, certified HSM/enclave hardware, or refrigerator-control software.
- AEGIS has broad real-world adoption or community validation beyond the evidence linked in this repository.

## Future Claim Class Only After Stronger Evidence

Any stronger claim about hardware-level behavior must be reserved for future controlled results with matched baselines, higher shot counts, confidence intervals, and negative-result handling.

Until then, use:

> AEGIS-selected control policies improved measured workload survival metrics under tested conditions.
