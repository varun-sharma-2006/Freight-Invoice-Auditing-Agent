### hybrid_heuristic on `test` (254 invoices)

Generated 2026-10-10T09:26:07+00:00

- Extraction field accuracy: **78.4%** (invoices extracted perfectly: 77.6%)
- Detection: recall **79.5%**, precision **100.0%** (TP 229, FN 59, FP 0)
- False alarms: 0.0% of clean lines, 0.0% of clean invoices
- Money: injected USD 220,085.37, correctly identified USD 163,525.67 (74.3%), falsely claimed USD 0.00
- Failures: 54, routed to review: 57
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 0.079s, p95 0.116s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 37 | 5 | 0 | 88.1% | 100.0% |
| currency_tax | 28 | 7 | 0 | 80.0% | 100.0% |
| detention_demurrage | 32 | 14 | 0 | 69.6% | 100.0% |
| duplicate_invoice | 10 | 4 | 0 | 71.4% | 100.0% |
| duplicate_line | 34 | 6 | 0 | 85.0% | 100.0% |
| expired_rate | 19 | 4 | 0 | 82.6% | 100.0% |
| unauthorized_charge | 36 | 7 | 0 | 83.7% | 100.0% |
| wrong_rate | 33 | 12 | 0 | 73.3% | 100.0% |
