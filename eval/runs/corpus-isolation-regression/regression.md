# Corpus Isolation Regression

- source: `knowledge_dual_tower_exp`
- target: `globex_category_kb_eval`
- chunks: 151
- corpus manifest: `c0473ab320aca136281cc719559ef930bd371b0722f867826c282b8c41a4171b`
- metric match: `True`
- exact ranking match: `True`

# Dual-Tower Experiment D — Retriever-only

## Overall

| Metric | Baseline | Dual Tower | Delta |
|---|---:|---:|---:|
| Recall@5 | 0.7958 | 0.7958 | +0.0000 |
| Recall@10 | 0.8451 | 0.8451 | +0.0000 |
| Recall@24 | 0.8803 | 0.8803 | +0.0000 |
| Recall@50 | 0.9437 | 0.9437 | +0.0000 |
| MRR | 0.7821 | 0.7821 | +0.0000 |
| Gold Mean Rank (miss=51) | 7.838709677419355 | 7.838709677419355 | n/a |
| Gold Median Rank (miss=51) | 1 | 1 | n/a |
| Retrieval Loss gold count | 6 | 6 | n/a |
| Hard-negative outrank positive | 0.08333333333333333 | 0.08333333333333333 | n/a |

## Buckets

- `DECOMPOSE_SUBQUERY`：Recall@24 0.8875 → 0.8875；MRR 0.7769 → 0.7769。
- `DIRECT`：Recall@24 0.8710 → 0.8710；MRR 0.7888 → 0.7888。
- `domain_rule`：Recall@24 0.8068 → 0.8068；MRR 0.7481 → 0.7481。
- `implicit_cross_domain`：Recall@24 0.8750 → 0.8750；MRR 0.7744 → 0.7744。
- `multi_evidence`：Recall@24 0.8900 → 0.8900；MRR 0.7915 → 0.7915。
- `single_evidence`：Recall@24 0.8571 → 0.8571；MRR 0.7597 → 0.7597。

## Rank movement

| Case | Evidence | Old | Dual | Delta | Old score | New score |
|---|---|---:|---:|---:|---:|---:|
| blind-001 | travel-gear.md#避坑点#da17c26d967c | 1 | 1 | +0 | 0.539771141672 | 0.539771141672 |
| blind-002 | travel-gear.md#关键属性与判断口径#6c0b5b589183 | 1 | 1 | +0 | 0.534835272657 | 0.534835272657 |
| blind-005 | travel-gear.md#关键属性与判断口径#8399e109d5dd | 1 | 1 | +0 | 0.553634687216 | 0.553634687216 |
| blind-006 | travel-gear.md#关键属性与判断口径#3cc9021c0b71 | 1 | 1 | +0 | 0.586911046286 | 0.586911046286 |
| blind-007 | digital-accessories.md#关键属性与判断口径#9f98a1a32c70 | 1 | 1 | +0 | 0.542067942646 | 0.542067942646 |
| blind-008 | cross-border-guide.md#材质与合规#f6bfddbb08fc | >50 | >50 | +0 | n/a | n/a |
| blind-008 | digital-accessories.md#当前热卖款型#b365042193b2 | 2 | 2 | +0 | 0.451521870896 | 0.451521870896 |
| blind-010 | digital-accessories.md#关键属性与判断口径#392e8f8f1822 | 2 | 2 | +0 | 0.424753137173 | 0.424753137173 |
| blind-012 | digital-accessories.md#当前热卖款型#93430049f89a | 2 | 2 | +0 | 0.444227358969 | 0.444227358969 |
| blind-012 | digital-accessories.md#避坑点#ec2521f64fb2 | 1 | 1 | +0 | 0.477440038504 | 0.477440038504 |
| blind-013 | home-living.md#关键属性与判断口径#f5ec7a5abc96 | 1 | 1 | +0 | 0.588353742394 | 0.588353742394 |
| blind-014 | home-living.md#避坑点#cc9519301550 | 24 | 24 | +0 | 0.415407878132 | 0.415407878132 |
| blind-016 | outdoor-sports.md#避坑点#8b8289737644 | 1 | 1 | +0 | 0.547276854582 | 0.547276854582 |
| blind-017 | outdoor-sports.md#关键属性与判断口径#fa3c198e9502 | 3 | 3 | +0 | 0.421882981066 | 0.421882981066 |
| blind-018 | outdoor-sports.md#当前热卖款型#1f7549d85ee9 | 1 | 1 | +0 | 0.512996491591 | 0.512996491591 |
| blind-019 | digital-accessories.md#当前热卖款型#b365042193b2 | 10 | 10 | +0 | 0.435370185191 | 0.435370185191 |
| blind-019 | digital-accessories.md#当前热卖款型#b365042193b2 | 1 | 1 | +0 | 0.492527852795 | 0.492527852795 |
| blind-019 | travel-gear.md#避坑点#da17c26d967c | 1 | 1 | +0 | 0.593225559699 | 0.593225559699 |
| blind-019 | travel-gear.md#避坑点#da17c26d967c | 2 | 2 | +0 | 0.471723317409 | 0.471723317409 |
| blind-021 | cross-border-guide.md#运费口径#a9e7150b3956 | >50 | >50 | +0 | n/a | n/a |
| blind-021 | cross-border-guide.md#运费口径#a9e7150b3956 | 5 | 5 | +0 | 0.498754644108 | 0.498754644108 |
| blind-021 | home-living.md#关键属性与判断口径#f5ec7a5abc96 | 1 | 1 | +0 | 0.541190608998 | 0.541190608998 |
| blind-021 | home-living.md#关键属性与判断口径#f5ec7a5abc96 | 27 | 27 | +0 | 0.424535141403 | 0.424535141403 |
| blind-025 | cross-border-guide.md#材质与合规#ec2498127b7d | >50 | >50 | +0 | n/a | n/a |
| blind-025 | cross-border-guide.md#材质与合规#ec2498127b7d | >50 | >50 | +0 | n/a | n/a |
| blind-025 | digital-accessories.md#当前热卖款型#93430049f89a | 1 | 1 | +0 | 0.545700817943 | 0.545700817943 |
| blind-025 | digital-accessories.md#当前热卖款型#93430049f89a | 1 | 1 | +0 | 0.44767508133 | 0.44767508133 |
| blind-030 | eval-policy-us.md#适用范围#70ca23bcc1bc | 33 | 33 | +0 | 0.472998711336 | 0.472998711336 |
| human-mh-001 | cross-border-guide.md#材质与合规#f6bfddbb08fc | 42 | 42 | +0 | 0.33044286707 | 0.33044286707 |
| human-mh-001 | digital-accessories.md#当前热卖款型#b365042193b2 | 1 | 1 | +0 | 0.512113497526 | 0.512113497526 |
| human-mh-002 | travel-gear.md#当前热卖款型#36bc545a10ef | 2 | 2 | +0 | 0.528636180743 | 0.528636180743 |
| human-mh-002 | travel-gear.md#当前热卖款型#36bc545a10ef | 2 | 2 | +0 | 0.516712551075 | 0.516712551075 |
| human-mh-002 | travel-gear.md#避坑点#da17c26d967c | 1 | 1 | +0 | 0.563042903998 | 0.563042903998 |
| human-mh-002 | travel-gear.md#避坑点#da17c26d967c | 1 | 1 | +0 | 0.559734445201 | 0.559734445201 |
| v4-002 | travel-gear.md#关键属性与判断口径#d8c425d3c498 | 2 | 2 | +0 | 0.506995870902 | 0.506995870902 |
| v4-002 | travel-gear.md#避坑点#3b0eb72c48c9 | 1 | 1 | +0 | 0.553988820425 | 0.553988820425 |
| v4-005 | travel-gear.md#价格区间参考-人民币#367632819c96 | 1 | 1 | +0 | 0.60136652569 | 0.60136652569 |
| v4-006 | travel-gear.md#关键属性与判断口径#c8cbfcdaef5e | 36 | 36 | +0 | 0.386144896938 | 0.386144896938 |
| v4-017 | outdoor-sports.md#关键属性与判断口径#9b61dbd87137 | 1 | 1 | +0 | 0.461646596378 | 0.461646596378 |
| v4-020 | cross-border-guide.md#到手价的构成#de0ba9e3c57f | 1 | 1 | +0 | 0.545175401297 | 0.545175401297 |
| v4-021 | cross-border-guide.md#到手价的构成#a0b17273f36c | 1 | 1 | +0 | 0.508955107926 | 0.508955107926 |
| v4-021 | cross-border-guide.md#推荐话术原则#c906abef55d1 | 1 | 1 | +0 | 0.508955107926 | 0.508955107926 |
| v4-022 | cross-border-guide.md#运费口径#a6d0645c2de4 | 49 | 49 | +0 | 0.349767618912 | 0.349767618912 |
| v4-024 | digital-accessories.md#当前热卖款型#4ee1798508d7 | 1 | 1 | +0 | 0.502733450291 | 0.502733450291 |
| v4-024 | digital-accessories.md#当前热卖款型#872432888787 | 1 | 1 | +0 | 0.557941875949 | 0.557941875949 |
| v4-024 | digital-accessories.md#避坑点#11e15de37d9f | 1 | 1 | +0 | 0.557941875949 | 0.557941875949 |
| v4-026 | home-living.md#关键属性与判断口径#1a185f9f045e | 1 | 1 | +0 | 0.59101545468 | 0.59101545468 |
| v4-026 | home-living.md#避坑点#c90d79741f5b | 9 | 9 | +0 | 0.473540852655 | 0.473540852655 |
| v4-027 | outdoor-sports.md#关键属性与判断口径#c6b2a27622bf | 1 | 1 | +0 | 0.571242300272 | 0.571242300272 |
| v4-028 | cross-border-guide.md#运费口径#a6d0645c2de4 | 1 | 1 | +0 | 0.586365371089 | 0.586365371089 |
| v4-028 | outdoor-sports.md#品类定位#1593d1af48ed | 24 | 24 | +0 | 0.446163110006 | 0.446163110006 |
| v4-028 | outdoor-sports.md#当前热卖款型#50283a2bcf4e | 1 | 1 | +0 | 0.602436801618 | 0.602436801618 |
| v4-029 | cross-border-guide.md#到手价的构成#a0b17273f36c | 1 | 1 | +0 | 0.552731659316 | 0.552731659316 |
| v4-029 | cross-border-guide.md#到手价的构成#de0ba9e3c57f | 1 | 1 | +0 | 0.603443995895 | 0.603443995895 |
| v4-030 | cross-border-guide.md#免税额度-de-minimis#d2a31864178f | 1 | 1 | +0 | 0.533031696967 | 0.533031696967 |
| v4-030 | cross-border-guide.md#免税额度-de-minimis#d2a31864178f | >50 | >50 | +0 | n/a | n/a |
| v4-030 | cross-border-guide.md#运费口径#a6d0645c2de4 | 6 | 6 | +0 | 0.404404301015 | 0.404404301015 |
| v4-030 | cross-border-guide.md#运费口径#f6a798520e96 | 6 | 6 | +0 | 0.404404301015 | 0.404404301015 |
| v4-031 | digital-accessories.md#当前热卖款型#748c47767b22 | 1 | 1 | +0 | 0.48699887859 | 0.48699887859 |
| v4-031 | digital-accessories.md#当前热卖款型#872432888787 | 1 | 1 | +0 | 0.538374699383 | 0.538374699383 |
| v4-034 | travel-gear.md#价格区间参考-人民币#367632819c96 | 1 | 1 | +0 | 0.603229578514 | 0.603229578514 |
| v4-034 | travel-gear.md#关键属性与判断口径#31fba82f2588 | 1 | 1 | +0 | 0.576529990196 | 0.576529990196 |
| v4-035 | travel-gear.md#关键属性与判断口径#c8cbfcdaef5e | 1 | 1 | +0 | 0.51505834355 | 0.51505834355 |
| v4-035 | travel-gear.md#当前热卖款型#1b3d8c96309d | 1 | 1 | +0 | 0.51505834355 | 0.51505834355 |
| v4-037 | digital-accessories.md#当前热卖款型#4ee1798508d7 | 1 | 1 | +0 | 0.492108071719 | 0.492108071719 |
| v4-037 | outdoor-sports.md#避坑点#b6ee3fa0d857 | 8 | 8 | +0 | 0.378780173519 | 0.378780173519 |
| v4-038 | cross-border-guide.md#运费口径#a6d0645c2de4 | 5 | 5 | +0 | 0.450785408484 | 0.450785408484 |
| v4-038 | outdoor-sports.md#品类定位#1593d1af48ed | 2 | 2 | +0 | 0.483753423603 | 0.483753423603 |
| v4-038 | outdoor-sports.md#当前热卖款型#bff494e99bef | 1 | 1 | +0 | 0.606142059053 | 0.606142059053 |
| v4-040 | home-living.md#价格区间参考#70bd1ea76dda | 1 | 1 | +0 | 0.495979678681 | 0.495979678681 |
| v4-040 | home-living.md#当前热卖款型#b7d165a9898e | 1 | 1 | +0 | 0.476308370808 | 0.476308370808 |
| v4-041 | cross-border-guide.md#到手价的构成#a0b17273f36c | 1 | 1 | +0 | 0.486893081542 | 0.486893081542 |
| v4-041 | cross-border-guide.md#到手价的构成#a0b17273f36c | 1 | 1 | +0 | 0.467497947023 | 0.467497947023 |
| v4-041 | cross-border-guide.md#运费口径#a6d0645c2de4 | 5 | 5 | +0 | 0.460697033072 | 0.460697033072 |
| v4-041 | cross-border-guide.md#运费口径#f6a798520e96 | 5 | 5 | +0 | 0.460697033072 | 0.460697033072 |
| v4-043 | cross-border-guide.md#材质与合规#19aa6758a0c6 | >50 | >50 | +0 | n/a | n/a |
| v4-043 | digital-accessories.md#当前热卖款型#4ee1798508d7 | 1 | 1 | +0 | 0.5058239459 | 0.5058239459 |
| v4-046 | digital-accessories.md#当前热卖款型#872432888787 | 1 | 1 | +0 | 0.505741315004 | 0.505741315004 |
| v4-046 | digital-accessories.md#避坑点#11e15de37d9f | 1 | 1 | +0 | 0.371432564691 | 0.371432564691 |
| v4-048 | cross-border-guide.md#运费口径#a6d0645c2de4 | 2 | 2 | +0 | 0.496360635274 | 0.496360635274 |
| v4-048 | cross-border-guide.md#运费口径#f6a798520e96 | 1 | 1 | +0 | 0.453605515536 | 0.453605515536 |
| v4-048 | home-living.md#避坑点#4e6f39bf3889 | 27 | 27 | +0 | 0.429695677683 | 0.429695677683 |
| v4-049 | outdoor-sports.md#关键属性与判断口径#c6b2a27622bf | 2 | 2 | +0 | 0.513170719825 | 0.513170719825 |
| v4-051 | cross-border-guide.md#运费口径#a6d0645c2de4 | 5 | 5 | +0 | 0.414229088732 | 0.414229088732 |
| v4-051 | outdoor-sports.md#品类定位#1593d1af48ed | 14 | 14 | +0 | 0.392059456441 | 0.392059456441 |
| v4-060 | eval-policy-battery.md#12-边界#3a0dece099a0 | 2 | 2 | +0 | 0.476708535828 | 0.476708535828 |
| v4-060 | eval-policy-battery.md#适用范围#f12478f064a8 | 3 | 3 | +0 | 0.456624847866 | 0.456624847866 |
| v4-r002 | travel-gear.md#价格区间参考-人民币#d38d7e016981 | 1 | 1 | +0 | 0.600334372571 | 0.600334372571 |
| v4-r006 | digital-accessories.md#关键属性与判断口径#46a24115845b | 1 | 1 | +0 | 0.538411698778 | 0.538411698778 |
| v4-r007 | digital-accessories.md#关键属性与判断口径#05ce2c4df36d | 1 | 1 | +0 | 0.455557029671 | 0.455557029671 |
| v4-r008 | home-living.md#关键属性与判断口径#bf4ef2940112 | 1 | 1 | +0 | 0.542366944178 | 0.542366944178 |
| v4-r010 | outdoor-sports.md#关键属性与判断口径#21dfbd0b1178 | 1 | 1 | +0 | 0.557798335441 | 0.557798335441 |
| v4-r010 | outdoor-sports.md#当前热卖款型#50283a2bcf4e | 1 | 1 | +0 | 0.557798335441 | 0.557798335441 |

## Regression

- Strict regression @24：`none`
- Easy single-evidence regression @5：`none`
