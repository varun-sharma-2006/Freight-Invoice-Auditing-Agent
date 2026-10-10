### llm_only on `test` (60 invoices)

Generated 2026-10-08T13:27:11+00:00, model `gemma-4-26b-a4b-it`

- Detection: recall **74.6%**, precision **65.7%** (TP 44, FN 15, FP 23)
- False alarms: 5.4% of clean lines, 9.5% of clean invoices
- Money: injected USD 25,797.16, correctly identified USD 19,532.65 (75.7%), falsely claimed USD 7,029.59
- Failures: 4, routed to review: 4
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 288.95s, p95 2479.576s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 4 | 4 | 0 | 50.0% | 100.0% |
| currency_tax | 7 | 3 | 0 | 70.0% | 100.0% |
| detention_demurrage | 2 | 2 | 6 | 50.0% | 25.0% |
| duplicate_line | 11 | 0 | 0 | 100.0% | 100.0% |
| expired_rate | 4 | 2 | 0 | 66.7% | 100.0% |
| unauthorized_charge | 9 | 2 | 1 | 81.8% | 90.0% |
| wrong_rate | 7 | 2 | 16 | 77.8% | 30.4% |
