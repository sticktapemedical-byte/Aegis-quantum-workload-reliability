# AEGIS Test A Three-Backend Follow-Up - 2026-05-29

## Scope

Test A repeats the accepted-vs-rejected GHZ quality split across available IBM Cloud QPUs using the same 4-qubit GHZ workload, frozen `0.94` GHZ acceptance threshold, `30` batches per backend, and `256` shots per batch.

Success condition:

> `F_accepted > F_all > F_rejected` on at least 2 of 3 backends.

## Completed Results

| Backend | Batches | Shots | All Mean GHZ | Accepted Mean GHZ | Rejected Mean GHZ | Accepted Cohort | Success |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `ibm_marrakesh` | 30 | 7,680 | `94.17%` | `95.10%` | `92.77%` | 18 | yes |
| `ibm_kingston` | 30 | 7,680 | `88.91%` | n/a | `88.91%` | 0 | no |

## Deferred Backend

The `ibm_fez` run was cancelled after it remained pending/unresponsive for investigation. No Fez result artifact is claimed for this follow-up.

## Current Interpretation

The cross-backend success condition is not yet earned because only one completed backend passed and the Fez run is deferred.

The Marrakesh result supports a narrower claim:

> On the completed `ibm_marrakesh` follow-up run, AEGIS separated a stronger accepted-output cohort from weaker returned outputs under the frozen quality threshold.

The Kingston result is preserved as a negative result. Its lack of an accepted cohort at the frozen threshold is useful evidence for backend-routing decisions, not a failure to report.
