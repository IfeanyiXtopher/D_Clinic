# Missed-visit risk model — evaluation report

Generated 2026-09-26 22:13 UTC by `python -m ml.train`. Model version `missed_visit_v1`.

**Selected model: `logistic`** (rule: keep logistic regression unless boosting beats it on validation AUC by > 0.01).

## Splits

Patients hashed into pools (0.6, 0.15, 0.25); train = pool train & scheduled < 2026-03-01; valid = pool valid & [2026-03-01, 2026-06-01); test = pool test & ≥ 2026-06-01. No patient in two splits; no future information in training rows.

| split | rows | missed rate |
| --- | --- | --- |
| train | 13,422 | 0.281 |
| valid | 977 | 0.276 |
| test | 2,028 | 0.295 |

## Metrics

Capacity metric: within each facility-week, rank appointments by score and select the top 30%. `precision@k` is the share of selected appointments that were actually missed; `lift` is precision@k ÷ base rate.

| split | model | n | base rate | AUC | PR-AUC | Brier | ECE | precision@k | recall@k | lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| valid | rules | 977 | 0.276 | 0.633 | 0.358 | – | – | 0.380 | 0.456 | 1.37 |
| valid | logistic | 977 | 0.276 | 0.666 | 0.418 | 0.188 | 0.040 | 0.398 | 0.478 | 1.44 |
| valid | boosting | 977 | 0.276 | 0.662 | 0.428 | 0.187 | 0.032 | 0.414 | 0.496 | 1.50 |
| test | rules | 2,028 | 0.295 | 0.626 | 0.401 | – | – | 0.421 | 0.453 | 1.43 |
| test | logistic | 2,028 | 0.295 | 0.648 | 0.459 | 0.194 | 0.022 | 0.438 | 0.472 | 1.49 |
| test | boosting | 2,028 | 0.295 | 0.649 | 0.462 | 0.194 | 0.018 | 0.433 | 0.467 | 1.47 |

## Signal ceiling (synthetic data only)

The generator's hidden per-patient propensity is available for synthetic cohorts. Scoring the test rows with that hidden truth gives the best AUC any model could reach, because each appointment still carries irreducible randomness.

| oracle | AUC |
| --- | --- |
| latent propensity only | 0.681 |
| latent propensity + known lead-time / distance / streak effects | 0.704 |
| **selected model (observable history only)** | **0.648** |

## Calibration on test (selected model)

|   n |   predicted |   observed |
|----:|------------:|-----------:|
| 203 |       0.152 |      0.187 |
| 203 |       0.187 |      0.192 |
| 203 |       0.211 |      0.212 |
| 202 |       0.235 |      0.218 |
| 203 |       0.26  |      0.227 |
| 203 |       0.287 |      0.241 |
| 202 |       0.316 |      0.347 |
| 203 |       0.357 |      0.355 |
| 203 |       0.426 |      0.389 |
| 203 |       0.598 |      0.581 |

## Risk bands

Thresholds from training-score quantiles: medium ≥ 0.250 (50th pct), high ≥ 0.361 (80th pct).

| band   |   n |   observed_miss_rate |
|:-------|----:|---------------------:|
| low    | 827 |                0.201 |
| medium | 714 |                0.293 |
| high   | 487 |                0.458 |

## Cold start (test rows with no personal history)

| basis    |    n |   observed |   predicted |
|:---------|-----:|-----------:|------------:|
| group    |  239 |      0.28  |       0.289 |
| mixed    |  769 |      0.307 |       0.293 |
| personal | 1020 |      0.289 |       0.313 |

## Fairness (test, selected model)

### by gender

| gender   |    n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:---------|-----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| female   | 1151 |       0.299 |       0.296 | 0.644 |            0.295 |             0.558 | 0.027 |
| male     |  877 |       0.29  |       0.312 | 0.656 |            0.348 |             0.488 | 0.029 |

### by age_band

| age_band   |   n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:-----------|----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| 40-49      | 479 |       0.269 |       0.288 | 0.642 |            0.276 |             0.651 | 0.036 |
| 50-59      | 680 |       0.301 |       0.299 | 0.633 |            0.306 |             0.522 | 0.02  |
| 60-69      | 456 |       0.292 |       0.297 | 0.62  |            0.307 |             0.556 | 0.035 |
| 70+        | 219 |       0.26  |       0.306 | 0.662 |            0.311 |             0.509 | 0.072 |
| <40        | 194 |       0.381 |       0.364 | 0.735 |            0.495 |             0.297 | 0.064 |

### by region

| region   |   n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:---------|----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| Lagos    | 936 |       0.286 |       0.279 | 0.641 |            0.299 |             0.556 | 0.022 |
| Ogun     | 915 |       0.314 |       0.325 | 0.649 |            0.33  |             0.523 | 0.013 |
| Oyo      | 177 |       0.243 |       0.314 | 0.691 |            0.35  |             0.395 | 0.072 |

### by facility_id

| facility_id                          |   n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:-------------------------------------|----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| 0540ebea-e3f5-484b-9c62-2f6f575c73a9 | 239 |       0.385 |       0.386 | 0.611 |            0.326 |             0.576 | 0.061 |
| 356b91c4-74fa-4ed5-8a5c-6a6f740905ce | 410 |       0.32  |       0.333 | 0.684 |            0.32  |             0.504 | 0.026 |
| 6efab8db-f0a2-4fd3-acb9-d94610c2b4a1 | 611 |       0.303 |       0.305 | 0.619 |            0.311 |             0.541 | 0.033 |
| 8826d916-cdfb-41c6-81ff-91a761565a70 | 433 |       0.249 |       0.246 | 0.634 |            0.319 |             0.519 | 0.017 |
| fc85e6da-3f50-4390-b347-461412f7d6c3 | 335 |       0.245 |       0.276 | 0.645 |            0.319 |             0.5   | 0.036 |

## Notes

- `region` is **not** a model feature; it appears only in this audit. The synthetic generator gives region no causal effect; any gap seen here is mediated by distance band.
- Rows with basis `group` are scored from similar patients (facility × diabetes × drug count × age band) with partial pooling; the UI must label them as group estimates.
- Reasons shown to users come from the logistic model's per-row contributions (`ml.train.explain_rows`).