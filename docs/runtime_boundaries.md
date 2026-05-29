# Runtime Boundary Rules

These rules describe simulated kernel behavior when timing, branch lineage, cryptographic status, or physical-resource proxy metrics become unsafe.

## Low-Order Adaptive Fallback

If the full second-order phase projection cannot complete within the epoch budget, the kernel drops the acceleration term and falls back to a linear velocity projection. If calculation latency exceeds the configured holdover ceiling, the kernel triggers `CIRCUIT_ABORT` rather than emitting a stale track.

## Backaction Contamination Labeling

The simulator separates environmental and observer-induced disturbance. Nodes under heavy measurement pressure can be marked as contaminated rather than automatically treated as faulty, preserving observability into why trust degraded.

## Phase-Branch Recovery

Large angular jumps are treated as possible lost phase-unwrapping branches. `RECOVERY_VALIDATE` freezes phase commits and re-synchronizes against the rolling anchor window before reopening active paths.

## Orphaned Branch Resolution

During a simulated branch collision, the active branch is selected by anchor agreement, trust channels, continuity health, epoch recency, and cryptographic validity. Losing branches are preserved as forensic tombstones while live subkeys are removed from active use.

## Staged Cryptographic Sealing

When cryptographic sealing is required under thermal pressure, the simulator first freezes external I/O, locks enclave state read-only, and ratchets forward once. More expensive cleanup is deferred until simulated thermal headroom returns.
