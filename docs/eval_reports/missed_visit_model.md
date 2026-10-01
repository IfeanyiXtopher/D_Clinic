# Missed-visit risk model — evaluation report

Generated 2026-09-26 22:50 UTC by `python -m ml.train`. Model version `missed_visit_v1`.

**Selected model: `logistic`** (rule: keep logistic regression unless boosting beats it on validation AUC by > 0.01).

## Splits

Patients hashed into pools (0.6, 0.15, 0.25); train = pool train & scheduled < 2026-03-01; valid = pool valid & [2026-03-01, 2026-06-01); test = pool test & ≥ 2026-06-01. No patient in two splits; no future information in training rows.

| split | rows | missed rate |
| --- | --- | --- |
| train | 12,797 | 0.269 |
| valid | 914 | 0.296 |
| test | 2,063 | 0.277 |

## Metrics

Capacity metric: within each facility-week, rank appointments by score and select the top 30%. `precision@k` is the share of selected appointments that were actually missed; `lift` is precision@k ÷ base rate.

| split | model | n | base rate | AUC | PR-AUC | Brier | ECE | precision@k | recall@k | lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| valid | rules | 914 | 0.296 | 0.621 | 0.378 | – | – | 0.420 | 0.476 | 1.42 |
| valid | logistic | 914 | 0.296 | 0.643 | 0.418 | 0.199 | 0.040 | 0.378 | 0.428 | 1.27 |
| valid | boosting | 914 | 0.296 | 0.620 | 0.411 | 0.201 | 0.037 | 0.368 | 0.417 | 1.24 |
| test | rules | 2,063 | 0.277 | 0.623 | 0.363 | – | – | 0.364 | 0.417 | 1.31 |
| test | logistic | 2,063 | 0.277 | 0.640 | 0.407 | 0.191 | 0.041 | 0.370 | 0.424 | 1.34 |
| test | boosting | 2,063 | 0.277 | 0.610 | 0.391 | 0.193 | 0.029 | 0.349 | 0.399 | 1.26 |

## Signal ceiling (synthetic data only)

The generator's hidden per-patient propensity is available for synthetic cohorts. Scoring the test rows with that hidden truth gives the best AUC any model could reach, because each appointment still carries irreducible randomness.

| oracle | AUC |
| --- | --- |
| latent propensity only | 0.684 |
| latent propensity + known lead-time / distance / streak effects | 0.713 |
| **selected model (observable history only)** | **0.640** |

## Calibration on test (selected model)

|   n |   predicted |   observed |
|----:|------------:|-----------:|
| 207 |       0.148 |      0.116 |
| 206 |       0.185 |      0.165 |
| 206 |       0.21  |      0.233 |
| 206 |       0.233 |      0.184 |
| 207 |       0.256 |      0.271 |
| 206 |       0.284 |      0.32  |
| 206 |       0.314 |      0.291 |
| 206 |       0.353 |      0.398 |
| 206 |       0.41  |      0.335 |
| 207 |       0.543 |      0.454 |

## Risk bands

Thresholds from training-score quantiles: medium ≥ 0.242 (50th pct), high ≥ 0.347 (80th pct).

| band   |   n |   observed_miss_rate |
|:-------|----:|---------------------:|
| low    | 793 |                0.172 |
| medium | 734 |                0.308 |
| high   | 536 |                0.39  |

## Cold start (test rows with no personal history)

| basis    |    n |   observed |   predicted |
|:---------|-----:|-----------:|------------:|
| group    |  204 |      0.319 |       0.301 |
| mixed    |  787 |      0.247 |       0.304 |
| personal | 1072 |      0.291 |       0.284 |

## Fairness (test, selected model)

### by gender

| gender   |    n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:---------|-----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| female   | 1208 |       0.272 |       0.279 | 0.639 |            0.261 |             0.634 | 0.023 |
| male     |  855 |       0.284 |       0.314 | 0.642 |            0.396 |             0.498 | 0.032 |

### by age_band

| age_band   |   n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:-----------|----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| 40-49      | 438 |       0.281 |       0.284 | 0.652 |            0.269 |             0.65  | 0.034 |
| 50-59      | 712 |       0.254 |       0.287 | 0.656 |            0.287 |             0.569 | 0.033 |
| 60-69      | 521 |       0.28  |       0.281 | 0.644 |            0.286 |             0.603 | 0.032 |
| 70+        | 159 |       0.296 |       0.306 | 0.596 |            0.377 |             0.574 | 0.054 |
| <40        | 233 |       0.318 |       0.352 | 0.553 |            0.528 |             0.419 | 0.103 |

### by region

| region   |    n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:---------|-----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| Lagos    | 1010 |       0.26  |       0.269 | 0.653 |            0.313 |             0.555 | 0.01  |
| Ogun     |  904 |       0.289 |       0.317 | 0.632 |            0.316 |             0.586 | 0.037 |
| Oyo      |  149 |       0.315 |       0.321 | 0.559 |            0.349 |             0.638 | 0.068 |

### by facility_id

| facility_id                          |   n |   base_rate |   mean_pred |   auc |   selection_rate |   fnr_at_capacity |   ece |
|:-------------------------------------|----:|------------:|------------:|------:|-----------------:|------------------:|------:|
| 0540ebea-e3f5-484b-9c62-2f6f575c73a9 | 233 |       0.3   |       0.352 | 0.544 |            0.33  |             0.7   | 0.079 |
| 356b91c4-74fa-4ed5-8a5c-6a6f740905ce | 457 |       0.324 |       0.345 | 0.617 |            0.317 |             0.608 | 0.05  |
| 6efab8db-f0a2-4fd3-acb9-d94610c2b4a1 | 571 |       0.296 |       0.295 | 0.66  |            0.312 |             0.55  | 0.039 |
| 8826d916-cdfb-41c6-81ff-91a761565a70 | 521 |       0.228 |       0.235 | 0.652 |            0.315 |             0.546 | 0.02  |
| fc85e6da-3f50-4390-b347-461412f7d6c3 | 281 |       0.231 |       0.266 | 0.63  |            0.32  |             0.492 | 0.035 |

## Notes

- `region` is **not** a model feature; it appears only in this audit. The synthetic generator gives region no causal effect; any gap seen here is mediated by distance band.
- Rows with basis `group` are scored from similar patients (facility × diabetes × drug count × age band) with partial pooling; the UI must label them as group estimates.
- Reasons shown to users come from the logistic model's per-row contributions (`ml.train.explain_rows`).