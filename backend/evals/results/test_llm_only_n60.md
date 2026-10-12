### llm_only on `test` (60 invoices)

Generated 2026-10-12T12:51:18+00:00, model `gemma-4-26b-a4b-it`

- Detection: recall **72.4%**, precision **51.9%** (TP 42, FN 16, FP 39)
- False alarms: 10.3% of clean lines, 36.0% of clean invoices
- Money: injected USD 24,643.72, correctly identified USD 18,456.83 (74.9%), falsely claimed USD 58,681.99
- Failures: 4, routed to review: 4
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 896.815s, p95 8030.164s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 5 | 6 | 3 | 45.5% | 62.5% |
| currency_tax | 5 | 1 | 0 | 83.3% | 100.0% |
| detention_demurrage | 9 | 0 | 4 | 100.0% | 69.2% |
| duplicate_line | 10 | 0 | 0 | 100.0% | 100.0% |
| expired_rate | 2 | 3 | 0 | 40.0% | 100.0% |
| unauthorized_charge | 5 | 2 | 3 | 71.4% | 62.5% |
| wrong_rate | 6 | 4 | 29 | 60.0% | 17.1% |
