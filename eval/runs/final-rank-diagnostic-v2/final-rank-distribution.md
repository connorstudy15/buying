# Final Rank Distribution Diagnostic

- Strategy: `decompose_per_need_rerank`
- Top-K loss evidence observations: 29

| Fusion rank | Count | Rate |
|---|---:|---:|
| Rank 1-3 | 7 | 24.14% |
| Rank 4-5 | 4 | 13.79% |
| Rank 6-10 | 2 | 6.90% |
| Rank >10 | 16 | 55.17% |
| Missing | 0 | 0.00% |

## Selection diagnostics

- Information-need coverage lost: `blind-005,blind-006,blind-008,blind-010,blind-012,blind-014,blind-019,blind-021,blind-025,human-mh-001,human-mh-002,v4-002,v4-006,v4-022,v4-028,v4-037,v4-038,v4-043,v4-048,v4-049,v4-051,v4-060`
- Final selection contains repeated documents: `none`
- Final selection contains repeated document sections: `none`
- Median same-scale ranking score gap to rank 3: `0.0234779527`

## Lost evidence

| Run | Case | Rank | Bucket | Score type | Gap to rank 3 |
|---:|---|---:|---|---|---:|
| 1 | blind-005 | 4 | rank_4_5 | retrieval_similarity | 0.0020841177 |
| 1 | blind-006 | 5 | rank_4_5 | retrieval_similarity | 0.0274108347 |
| 1 | blind-008 | 25 | rank_gt_10 | retrieval_similarity | 0.1159471194 |
| 1 | blind-010 | 2 | rank_1_3 | retrieval_similarity | -0.1065210747 |
| 1 | blind-012 | 2 | rank_1_3 | retrieval_similarity | -0.033768297 |
| 1 | blind-014 | 23 | rank_gt_10 | retrieval_similarity | 0.114704658 |
| 1 | blind-019 | 4 | rank_4_5 | retrieval_similarity | 0.0040118426 |
| 1 | blind-021 | 12 | rank_gt_10 | retrieval_similarity | 0.0379966509 |
| 1 | blind-025 | 25 | rank_gt_10 | retrieval_similarity | 0.1081041108 |
| 1 | human-mh-001 | 25 | rank_gt_10 | retrieval_similarity | 0.0703950197 |
| 1 | human-mh-002 | 4 | rank_4_5 | retrieval_similarity | 0.0005401815 |
| 1 | v4-002 | 2 | rank_1_3 | retrieval_similarity | -0.0278210127 |
| 1 | v4-006 | 17 | rank_gt_10 | retrieval_similarity | 0.0371923247 |
| 1 | v4-022 | 25 | rank_gt_10 | retrieval_similarity | 0.122296533 |
| 1 | v4-028 | 16 | rank_gt_10 | retrieval_similarity | 0.067810753 |
| 1 | v4-037 | 6 | rank_6_10 | retrieval_similarity | 0.0080266317 |
| 1 | v4-038 | 26 | rank_gt_10 | retrieval_similarity | 0.0887910193 |
| 1 | v4-043 | 26 | rank_gt_10 | retrieval_similarity | 0.1427857801 |
| 1 | v4-043 | 16 | rank_gt_10 | retrieval_similarity | 0.0234779527 |
| 1 | v4-048 | 12 | rank_gt_10 | retrieval_similarity | 0.0181388675 |
| 1 | v4-048 | 12 | rank_gt_10 | retrieval_similarity | 0.0181388675 |
| 1 | v4-048 | 26 | rank_gt_10 | retrieval_similarity | 0.0816732901 |
| 1 | v4-049 | 2 | rank_1_3 | retrieval_similarity | -0.0820216217 |
| 1 | v4-049 | 2 | rank_1_3 | retrieval_similarity | -0.0820216217 |
| 1 | v4-051 | 6 | rank_6_10 | retrieval_similarity | 0.0039891565 |
| 1 | v4-060 | 25 | rank_gt_10 | retrieval_similarity | 0.1595726241 |
| 1 | v4-060 | 2 | rank_1_3 | retrieval_similarity | -0.0304237136 |
| 1 | v4-060 | 21 | rank_gt_10 | retrieval_similarity | 0.0531476747 |
| 1 | v4-060 | 3 | rank_1_3 | retrieval_similarity | 0.0 |
