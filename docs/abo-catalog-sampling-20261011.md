# ABO 广品类商品样本：2026-10-11

## 用户要求

尽量覆盖大部分品类，每个品类不超过 30 件商品。
已生成可选演示目录并接入项目，尚未替换服务器运行中的商品库。

## 已完成

- 下载官方 ABO 商品元数据包和 CC BY 4.0 许可证。
- 实读 147,702 条商品记录，包含 576 个原始 product_type。
- 排除没有标题、主图标识、明确类型或足够描述属性的记录，共 10,398 条。
- 优先保留描述属性完整、有中文或英文名称的商品；品牌轮流选取，并剔除
  同类型下完全相同的多语言标题组合。颜色和尺寸近似变体仍需后续进一步合并。
- 输出 9,467 件商品，561 个来源类型，各类型最多 30 件。
- 验证样本数、类型数、最大数量与统计一致，商品 (item_id, domain_name) 组合不重复。
- 保留来源字段和许可证，没有编造价格、库存、配送或产地。

## 本地交付

目录：`.tmp/abo/sample/`。

- `abo-sample.jsonl`：原始商品字段样本。
- `category-counts.csv`：每类原始数量、合格数量、入选数量，可用 Excel 打开。
- `summary.json`：统计、原包及样本 SHA256。
- `LICENSE-CC-BY-4.0.txt`、`ATTRIBUTION.md`：许可及署名。

可复现命令（Python 3.11 及以上，无第三方依赖）：

```powershell
.venv/Scripts/python.exe scripts/prepare_abo_sample.py .tmp/abo/abo-listings.tar .tmp/abo/sample-new --per-category 30
```

必须使用新的输出目录，脚本拒绝覆盖已有结果。

## 样本覆盖示例

| 来源类型 | 入选件数 |
|---|---:|
| HEADPHONES / 耳机 | 30 |
| SUITCASE / 行李箱 | 30 |
| BACKPACK / 双肩包 | 30 |
| CHAIR / 椅子 | 30 |
| SOFA / 沙发 | 30 |
| COFFEE / 咖啡 | 30 |
| BABY_PRODUCT / 母婴泛类 | 30 |
| PET_SUPPLIES / 宠物泛类 | 30 |
| NOTEBOOK_COMPUTER / 笔记本电脑 | 6 |
| CELLULAR_PHONE / 手机这一来源类型 | 1 |

561 是来源类型数，不等于 561 个经过统一的零售类目。
例如 HOME、KITCHEN 是泛类，可能与细类重叠；同类商品也可能有多个来源类型。
后续统一类目时必须再次应用最终类目最多 30 件的上限，不能简单将样本拼接入库。

## 原始样本阶段的接入清单（进展见下文）

1. 清理同义、泛化和重叠分类，中文化，并补充覆盖不足的类目。
2. 将记录映射到 Product/Sku，保留来源与转换记录；marketplace country
   不能作为制造产地或配送范围。跨市场相同 item_id 也不直接推定是同一个商品。
3. 价格参考与演示价格规则；当前文件没有生成价格，不能称为实时销售数据。
4. 库存及配送是独立的演示业务规则，需要明确标注。
5. 图片字段与前端展示支持，来源署名展示。
6. 商品向量重建和检索/下单回归，使用独立测试数据后再更新服务器。

## 最终目录（本地已完成）

以上 9,467 条是原始来源样本。统一零售分类后再次抽样，最终发布文件为
`data/catalog-abo-demo.jsonl`：24 类 × 30 件 = **720 件**，覆盖 430 个来源细类。
每类优先选不同用途，鞋靴等来源细类较少的类目再补不同商品。
分类规则显式修正 PORTABLE_AUDIO、SHEET_PAN、PAINT_BRUSH 等易误分名称。
4 个不明确/药品类来源类型未纳入；这并不代表覆盖了所有零售类目。

| 类别 | 类别 | 类别 | 类别 |
|---|---|---|---|
| 乐器配件 | 五金工具 | 办公文具 | 厨房餐具 |
| 园艺庭院 | 宠物用品 | 家具 | 家居收纳装饰 |
| 家用电器 | 床品家纺 | 数码电脑 | 服装服饰 |
| 母婴用品 | 汽车用品 | 清洁日用 | 照明灯具 |
| 玩具游戏 | 珠宝配饰 | 箱包旅行 | 美妆个护 |
| 营养保健 | 运动户外 | 鞋靴 | 食品饮料 |

- 720 件均有官方图片索引匹配的图片 URL，抽查 3 个 URL 返回 HTTP 200。
  图片直接来自官方 S3，国内访问速度尚未在服务器验证；加载失败会显示占位。
- 162 件标题为简体中文，489 件为英文，其余 69 件保留其他来源语言。
  分类、部分类型名称已中文化，尚未翻译全部商品正文。
- 制造产地保持未知；不将 marketplace country 冒充原产地。
- 库存固定 20、配送 CN/US/SG 都是显式模拟规则，不能当作真实履约承诺。
- 每个来源类型采用估计价格带，按稳定商品编号确定价格，重复生成不变。
  价格是人民币演示价，**尚未用实时市场报价校准**；并非 Amazon 售价或汇率换算。
  不自动生成评论、评分、虚假更新时间或商品不存在的规格。
- 商品卡/详情/比较/收藏/历史/工具小卡显示演示价标记，详情显示模拟库存配送说明，
  图片显示 Amazon.com / ABO / CC BY 4.0 署名与链接。

默认目录仍为原评测集。指定 `PRODUCT_CATALOG_PATH` 后才切换。
新目录使用独立向量集合 `globex_products_abo_demo_v1`，原目录不进入新搜索结果，
旧商品直接查询与订单快照继续保留。来源许可见 `docs/data/abo/`。

可复现命令：

```powershell
.venv/Scripts/python.exe scripts/build_abo_demo_catalog.py .tmp/abo/sample/abo-sample.jsonl data/catalog-abo-demo.jsonl --image-metadata .tmp/abo/images.csv.gz
```

## 验证与上线范围

已验证：数据唯一性/24 类上限/价格带/来源声明、24 类关键词检索、长商品编号精确查询、
旧商品直接查询与搜索隔离、720 件本地 Qdrant 建库及重启复用、每类意向单确认幂等和取消补库存。
这些流程使用隔离 SQLite、真实本地 Qdrant 和确定性 embedding 测试替身，未调用付费模型。
语义检索质量、模型对新目录的回答和服务器端嵌入重建仍需上线环境验收。
原有完整质量成本验收门槛尚未通过，此次结构/流程测试不替代该门槛。

后端首轮 100 项通过；追加索引/交易回归 44 项通过（与首轮部分重叠）。
前端原有 248 项通过，另补充价格标记和图片署名测试，相关文件 40 项通过；生产构建成功。
最终重新抽样后，导入/检索/索引/交易专项 12 项全部通过。

服务器更新文件为 `.tmp/cloud-deploy/globex-update-abo-20261011.tar.gz`。
上传到 `/home/admin/` 后，在 Workbench 执行：

```bash
mkdir -p /home/admin/globex-releases/20261011-abo
tar -xzf /home/admin/globex-update-abo-20261011.tar.gz -C /home/admin/globex-releases/20261011-abo
GLOBEX_CATALOG=abo bash /home/admin/globex-releases/20261011-abo/scripts/update_cloud.sh
```

`mkdir -p` 创建发布目录；`tar -xzf` 解压压缩包到 `-C` 指定目录；
`GLOBEX_CATALOG=abo` 选择新演示目录；`bash` 运行更新脚本。
脚本会先构建、备份三个数据卷，再启动服务。需要 admin 的 sudo 权限。
此次尚未执行服务器更新，旧的 root 目录部署仍为脚本的备份来源；
若之前已经切换到其他 release 或恢复卷，请先核对当前活动发布配置后再使用。

## 官方来源

- https://amazon-berkeley-objects.s3.amazonaws.com/index.html
- https://amazon-berkeley-objects.s3.amazonaws.com/archives/abo-listings.tar
- https://registry.opendata.aws/amazon-berkeley-objects/

ABO 授权为 CC BY 4.0，需要署名、链接许可证并说明修改。
本次修改仅为过滤和抽样，商品原始字段保留。详细署名见样本目录。
