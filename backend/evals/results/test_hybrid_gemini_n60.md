### hybrid_gemini on `test` (60 invoices)

Generated 2026-10-10T10:01:29+00:00, model `gemma-4-26b-a4b-it`

- Extraction field accuracy: **99.8%** (invoices extracted perfectly: 95.0%)
- Detection: recall **100.0%**, precision **100.0%** (TP 58, FN 0, FP 0)
- False alarms: 0.0% of clean lines, 0.0% of clean invoices
- Money: injected USD 24,643.72, correctly identified USD 24,643.72 (100.0%), falsely claimed USD 0.00
- Failures: 0, routed to review: 3
- Cost: USD 0.0 total, USD 0.0/invoice; latency mean 68.08s, p95 132.413s

| Error type | TP | FN | FP | Recall | Precision |
|---|---|---|---|---|---|
| calculation_error | 11 | 0 | 0 | 100.0% | 100.0% |
| currency_tax | 6 | 0 | 0 | 100.0% | 100.0% |
| detention_demurrage | 9 | 0 | 0 | 100.0% | 100.0% |
| duplicate_line | 10 | 0 | 0 | 100.0% | 100.0% |
| expired_rate | 5 | 0 | 0 | 100.0% | 100.0% |
| unauthorized_charge | 7 | 0 | 0 | 100.0% | 100.0% |
| wrong_rate | 10 | 0 | 0 | 100.0% | 100.0% |
