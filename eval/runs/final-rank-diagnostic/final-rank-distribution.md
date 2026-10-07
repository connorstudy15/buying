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
- Median RRF score gap to rank 3: `0.0034165985`

## Lost evidence

| Run | Case | Rank | Bucket | Gap to rank 3 |
|---:|---|---:|---|---:|
| 1 | blind-006 | 5 | rank_4_5 | None |
| 1 | blind-008 | 25 | rank_gt_10 | None |
| 1 | blind-014 | 23 | rank_gt_10 | None |
| 1 | blind-025 | 12 | rank_gt_10 | 0.0061839718 |
| 1 | human-mh-001 | 25 | rank_gt_10 | None |
| 1 | human-mh-002 | 4 | rank_4_5 | None |
| 1 | v4-006 | 17 | rank_gt_10 | None |
| 1 | v4-022 | 25 | rank_gt_10 | None |
| 1 | v4-043 | 6 | rank_6_10 | 0.0006492252 |
| 1 | v4-060 | 25 | rank_gt_10 | None |
| 1 | v4-060 | 21 | rank_gt_10 | None |
| 1 | v4-060 | 3 | rank_1_3 | None |
