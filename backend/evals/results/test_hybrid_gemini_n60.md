### hybrid_gemini on `test` (60 invoices)

Generated 2026-10-07T18:51:22+00:00, model `gemma-4-26b-a4b-it`

- Extraction field accuracy: **90.6%** (invoices extracted perfectly: 70.0%)
- Detection: recall **89.8%**, precision **98.1%** (TP 53, FN 6, FP 1)
- False alarms: 0.3% of clean lines, 0.0% of clean invoices
- Money: injected USD 25,797.16, correctly identified USD 23,949.50 (92.8%), falsely claimed USD 138.00
- Failures: 5, routed to review: 16
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 403.581s, p95 136.621s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 5 | 3 | 0 | 62.5% | 100.0% |
| currency_tax | 8 | 2 | 0 | 80.0% | 100.0% |
| detention_demurrage | 4 | 0 | 1 | 100.0% | 80.0% |
| duplicate_line | 11 | 0 | 0 | 100.0% | 100.0% |
| expired_rate | 6 | 0 | 0 | 100.0% | 100.0% |
| unauthorized_charge | 10 | 1 | 0 | 90.9% | 100.0% |
| wrong_rate | 9 | 0 | 0 | 100.0% | 100.0% |
