### hybrid_heuristic on `test` (254 invoices)

Generated 2026-10-07T10:44:20+00:00

- Extraction field accuracy: **75.7%** (invoices extracted perfectly: 75.2%)
- Detection: recall **68.6%**, precision **100.0%** (TP 192, FN 88, FP 0)
- False alarms: 0.0% of clean lines, 0.0% of clean invoices
- Money: injected USD 242,514.04, correctly identified USD 183,042.71 (75.5%), falsely claimed USD 0.00
- Failures: 62, routed to review: 63
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 0.084s, p95 0.126s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 28 | 12 | 0 | 70.0% | 100.0% |
| currency_tax | 25 | 15 | 0 | 62.5% | 100.0% |
| detention_demurrage | 23 | 18 | 0 | 56.1% | 100.0% |
| duplicate_invoice | 10 | 4 | 0 | 71.4% | 100.0% |
| duplicate_line | 38 | 10 | 0 | 79.2% | 100.0% |
| expired_rate | 11 | 3 | 0 | 78.6% | 100.0% |
| unauthorized_charge | 25 | 14 | 0 | 64.1% | 100.0% |
| wrong_rate | 32 | 12 | 0 | 72.7% | 100.0% |
