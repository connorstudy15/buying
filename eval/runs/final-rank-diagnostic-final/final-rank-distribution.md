# Final Rank Distribution Diagnostic

- Strategy: `decompose_per_need_rerank`
- Top-K loss evidence observations: 12

| Fusion rank | Count | Rate |
|---|---:|---:|
| Rank 1-3 | 1 | 8.33% |
| Rank 4-5 | 2 | 16.67% |
| Rank 6-10 | 1 | 8.33% |
| Rank >10 | 8 | 66.67% |
| Missing | 0 | 0.00% |

## Selection diagnostics

- Information-need coverage lost: `blind-006,blind-008,blind-014,blind-025,human-mh-001,human-mh-002,v4-006,v4-022,v4-043,v4-060`
- Final selection contains repeated documents: `blind-025`
- Final selection contains repeated document sections: `none`
- DIRECT ranking hydrated from matched companion pass: `blind-006,blind-008,blind-014,human-mh-001,human-mh-002,v4-006,v4-022,v4-060`
- Final selector chose candidates below raw rank 3: `blind-008,v4-006,v4-022,v4-043,v4-060`
- Gold evidence count exceeds Top-3 capacity: `v4-060`
- Lost evidence by effective mode: `{'DIRECT': 9, 'DECOMPOSE': 2, 'FALLBACK': 1}`
- Score gap to rank 3 (kept separate by score type): `{'retrieval_similarity': {'count': 10, 'median': 0.06177134720000001, 'p95': 0.1595726241}, 'rrf': {'count': 2, 'median': 0.0034165985, 'p95': 0.0061839718}}`

## Lost evidence

| Run | Case | Rank | Bucket | Score type | Gap to rank 3 |
|---:|---|---:|---|---|---:|
| 1 | blind-006 | 5 | rank_4_5 | retrieval_similarity | 0.0274108347 |
| 1 | blind-008 | 25 | rank_gt_10 | retrieval_similarity | 0.1159471194 |
| 1 | blind-014 | 23 | rank_gt_10 | retrieval_similarity | 0.114704658 |
| 1 | blind-025 | 12 | rank_gt_10 | rrf | 0.0061839718 |
| 1 | human-mh-001 | 25 | rank_gt_10 | retrieval_similarity | 0.0703950197 |
| 1 | human-mh-002 | 4 | rank_4_5 | retrieval_similarity | 0.0005401815 |
| 1 | v4-006 | 17 | rank_gt_10 | retrieval_similarity | 0.0371923247 |
| 1 | v4-022 | 25 | rank_gt_10 | retrieval_similarity | 0.122296533 |
| 1 | v4-043 | 6 | rank_6_10 | rrf | 0.0006492252 |
| 1 | v4-060 | 25 | rank_gt_10 | retrieval_similarity | 0.1595726241 |
| 1 | v4-060 | 21 | rank_gt_10 | retrieval_similarity | 0.0531476747 |
| 1 | v4-060 | 3 | rank_1_3 | retrieval_similarity | 0.0 |
