# Evaluation · October 9, 2026

The batch contains 78 conversations evaluated at October 9, 2026, 18:00 Asia/Kolkata. Outcomes come from actual model runs and matching saved assessments. Expected labels were fixed before evaluation and were not changed to match output.

The first pass accepted 77 assessments and rejected one. A subsequent model retry produced an accepted result for the remaining conversation: **78 accepted assessments in total**. Acceptance means schema and evidence validation passed; it does not establish semantic correctness. The first-pass report, rejected responses and final job identities remain in the JSON artifacts.

## Tier agreement

| Actual model | Accepted assessments | Labelled conversations | Agreement | Missed T1 | False T1 |
|---|---:|---:|---:|---:|---:|
| GLM-4.7-Flash | 37 | 30 | 28/30 | 0 | 2 |
| Qwen 3.5 4B | 41 | 33 | 30/33 | 0 | 0 |
| Combined | 78 | 63 | 58/63 | 0 | 2 |

Fifteen additional conversations have no frozen expected labels and are excluded from agreement metrics. The models handled different subsets, so this is not a head-to-head model comparison.

| Evaluation split | Agreement | Label authorship |
|---|---:|---|
| Development | 49/53 | Implementer-authored before model evaluation |
| Original held-out | 4/5 | User-reviewed before model evaluation |
| Expansion held-out | 5/5 | Implementer-authored before model evaluation |

## Interpretation and limits

Five conversations disagree with their expected tier. Manual review also found an incorrect open obligation and date interpretation in an assessment whose tier matched its label. This shows why tier agreement alone does not establish a correct obligation ledger. There has not been a complete manual semantic audit of all 78 assessments.

The data is synthetic and the labelled subsets are small. Most labels were authored by the implementer, so agreement measures consistency with those expectations rather than independently established accuracy. Real-inbox performance remains a separate evaluation.

API availability and output interpretation are different failure sources. The final accepted batch includes genuine local fallback results with their own provider provenance. Earlier provider failures and invalid outputs are retained rather than represented as successful analyses.

## Supporting artifacts

- [Final results](batch78-evaluation.json): per-conversation output, agreement, provider provenance and review notes.
- [First pass](batch78-fallback-first-pass.json): initial accepted and rejected outcomes.
- [Earlier API run](batch78-overnight-glm.json): operational failure evidence before bounded fallback recovery.

Replay bundles contain completed model outputs and can be loaded without issuing a new model request. Private Gmail conversations are excluded from shareable replay.
