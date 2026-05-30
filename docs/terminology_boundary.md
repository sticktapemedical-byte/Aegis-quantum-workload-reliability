# Terminology Boundary

AEGIS uses compact engineering names for software models. For public review, interpret these names conservatively.

| Project Term | Meaning In This Repo | Not Evidence Of |
| --- | --- | --- |
| Coherence-sensitive workload | A workload whose returned count/survival metric is affected by idle time, DD-style gates, or backend noise. | Intrinsic device coherence improvement. |
| Cryogenic scheduler | A software cost proxy that penalizes simulated thermal pressure. | Refrigerator control or cryogenic hardware scheduling. |
| Secure enclave vault | A software HSM-style key-lineage and delayed-erasure model. | Certified HSM use, secure enclave silicon, or hardware root of trust. |
| Hardware register target | A conceptual register-map proposal for future integration review. | Synthesized RTL, FPGA firmware, ASIC logic, or active hardware control. |
| Verilog stub | A non-synthesizable documentation snippet. | Validated RTL or an implemented hardware datapath. |
| Kernel | The Python governance core. | An operating-system kernel or physical quantum hardware kernel. |

The safest public framing is:

> AEGIS is a quantum workload reliability control plane that governs returned outputs, selects later execution paths, and preserves proof lineage.

Avoid:

> AEGIS controls quantum hardware, cryogenic systems, secure enclaves, or physical coherence.
