### hybrid_heuristic on `test` (60 invoices)

Generated 2026-10-07T15:06:54+00:00

- Extraction field accuracy: **77.3%** (invoices extracted perfectly: 76.7%)
- Detection: recall **79.7%**, precision **100.0%** (TP 47, FN 12, FP 0)
- False alarms: 0.0% of clean lines, 0.0% of clean invoices
- Money: injected USD 25,797.16, correctly identified USD 20,734.11 (80.4%), falsely claimed USD 0.00
- Failures: 14, routed to review: 14
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 0.086s, p95 0.139s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 7 | 1 | 0 | 87.5% | 100.0% |
| currency_tax | 8 | 2 | 0 | 80.0% | 100.0% |
| detention_demurrage | 3 | 1 | 0 | 75.0% | 100.0% |
| duplicate_line | 8 | 3 | 0 | 72.7% | 100.0% |
| expired_rate | 5 | 1 | 0 | 83.3% | 100.0% |
| unauthorized_charge | 9 | 2 | 0 | 81.8% | 100.0% |
| wrong_rate | 7 | 2 | 0 | 77.8% | 100.0% |
