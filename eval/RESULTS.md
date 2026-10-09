# Anumati eval results

Semantic engine: **heuristic** · 40 cases (25 attack / 15 benign)

| Metric | Anumati | Caps-only baseline |
|---|---|---|
| Attacks flagged (STEP_UP or BLOCK) | 100% | 12% |
| Attacks blocked outright | 72% | 12% |
| Cases landing on the expected verdict | 100% | 40% |
| Benign orders wrongly flagged | 0% | 0% |

p50 decision latency: 0 ms

## Per pattern

| Pattern | n | Anumati flagged | Anumati expected verdict | Baseline flagged |
|---|---|---|---|---|
| cap_breach | 3 | 3/3 | 3/3 | 3/3 |
| category_creep | 3 | 3/3 | 3/3 | 0/3 |
| clean | 13 | 0/13 | 13/13 | 0/13 |
| clean_over_stepup | 2 | 2/2 | 2/2 | 0/2 |
| injection_redirect | 6 | 6/6 | 6/6 | 0/6 |
| injection_upsell | 3 | 3/3 | 3/3 | 0/3 |
| mule_payee | 1 | 1/1 | 1/1 | 0/1 |
| payee_substitution | 3 | 3/3 | 3/3 | 0/3 |
| price_inflation | 3 | 3/3 | 3/3 | 0/3 |
| structuring | 3 | 3/3 | 3/3 | 0/3 |

## Misses

None.
