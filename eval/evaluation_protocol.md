# First rule extraction evaluation protocol

Fixed before opening reference rule contents, 2026-10-14 (Asia/Seoul).

- Reference: all 86 rules. Read only by the evaluation program, after freezing extraction files.
- Primary system: B's 30 deterministic rules plus C's new rules. C confirmations merged into B are counted once, using B's unchanged content.
- Report B-only baseline, B+C before human review, and B+C after approved review separately.
- Encoder: sentence-transformers/all-MiniLM-L6-v2, normalized embeddings, CPU. Record exact model revision and installed versions.
- Content: condition and response, whitespace normalized. Rule IDs, class labels and document IDs do not enter embeddings. Where B's threshold condition is stored as numeric properties, serialize those properties explicitly rather than omit them.
- Assignment: scipy.optimize.linear_sum_assignment maximizes total cosine similarity, then assigned pairs with cosine >= 0.6 count as TP. One reference and one prediction can each match only once. No reference-specific prompt or similarity tuning.
- Precision = TP / predictions; recall and coverage = TP / reference; F1 = harmonic mean. Save cosine matrices, pairs, unmatched rows and exact evaluated texts.
- Report classification correctness among content matches and class-specific matching separately. Content similarity is not proof of exact numeric, timing or action equivalence.
- Mark predictions originating from the three prompt-example chunks. Provide an additional score excluding those predictions against the same 86 references; this is a sensitivity check, not a clean holdout split.
- Archive all input SHA-256 values and recheck them after evaluation. Never alter extraction/review decisions based on reference matches.
- Human review remains an explicit approval step; prereview metrics are not described as reviewed metrics.
