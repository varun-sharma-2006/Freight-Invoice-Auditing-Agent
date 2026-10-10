### hybrid_heuristic on `test` (60 invoices)

Generated 2026-10-10T09:26:12+00:00

- Extraction field accuracy: **77.0%** (invoices extracted perfectly: 78.3%)
- Detection: recall **81.0%**, precision **100.0%** (TP 47, FN 11, FP 0)
- False alarms: 0.0% of clean lines, 0.0% of clean invoices
- Money: injected USD 24,643.72, correctly identified USD 19,192.36 (77.9%), falsely claimed USD 0.00
- Failures: 13, routed to review: 13
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 0.071s, p95 0.09s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 11 | 0 | 0 | 100.0% | 100.0% |
| currency_tax | 6 | 0 | 0 | 100.0% | 100.0% |
| detention_demurrage | 5 | 4 | 0 | 55.6% | 100.0% |
| duplicate_line | 7 | 3 | 0 | 70.0% | 100.0% |
| expired_rate | 4 | 1 | 0 | 80.0% | 100.0% |
| unauthorized_charge | 6 | 1 | 0 | 85.7% | 100.0% |
| wrong_rate | 8 | 2 | 0 | 80.0% | 100.0% |
