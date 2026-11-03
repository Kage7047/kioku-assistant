# Matching algorithm
Candidate generation by amount ±0.5% and date window of 10 days, then a scorer over IBAN, reference text similarity and payer name.
The reference text often contains the invoice number like INV-2026-0412.
Threshold 0.82 auto-matches; below goes to the review queue.
