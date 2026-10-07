# -*- coding: utf-8 -*-
"""为 Curated Production KB V1 生成小规模、可人工复核的 sanity set。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval.knowledge_evidence import evidence_id, quote_sha256, section_for_quote  # noqa: E402

CORPUS = ROOT / "knowledge" / "production"
OUTPUT = ROOT / "eval" / "knowledge" / "production_sanity_v1.jsonl"


CASES = [
    ("prod-001", "充电宝能不能放托运行李？", "single_evidence", "complete", None,
     [("carry", "确认移动电源的行李类型", "power-bank-air-travel-global.md", "先判断物品类型", "移动电源属于备用锂电池，而不是普通“已安装在设备中的电池”。因此它应放在随身行李中，不能放进托运行李。")]),
    ("prod-002", "20000mAh、3.7V 的充电宝大约是多少Wh？", "single_evidence", "complete", None,
     [("wh", "换算额定能量", "battery-wh-calculation.md", "计算方法", "换算步骤是先把 mAh 除以 1000 得到 Ah，再计算 `Wh = V × Ah`。例如标称 20,000mAh、3.7V 的电芯，按标称值估算为 74Wh。")]),
    ("prod-003", "国内坐飞机，充电宝的3C标志看不清还能带吗？", "single_evidence", "complete", None,
     [("ccc", "中国境内航班 3C 要求", "china-domestic-power-bank-rule.md", "3C 与召回状态", "中国民航局自 2025 年 6 月 28 日起禁止旅客携带没有 3C 标识、3C 标识不清晰，以及属于被召回型号或批次的充电宝乘坐境内航班。")]),
    ("prod-004", "去日本坐ANA，移动电源是托运还是随身？", "single_evidence", "complete", None,
     [("ana", "ANA 对移动电源的行李要求", "japan-ana-battery-baggage.md", "移动电源", "ANA 的国际航班行李说明把移动电源列为只能带入客舱、不能托运的物品。")]),
    ("prod-005", "带充电功能的智能行李箱托运前要看什么？", "single_evidence", "complete", None,
     [("smart", "智能行李箱电池可拆卸性", "smart-luggage-battery.md", "托运场景", "对于可拆卸电池的智能行李箱，托运时通常需要先拆下电池，再把电池随身带入客舱。")]),
    ("prod-006", "东西很轻但箱子很大，DHL运费为什么还可能很贵？", "single_evidence", "complete", None,
     [("volume", "DHL 计费重原则", "dhl-volumetric-weight.md", "为什么轻货也可能贵", "DHL 的公开说明指出，运费会比较包裹实际重量与体积重量，并以较大者作为计费基础。")]),
    ("prod-007", "UPS的尺寸重量怎么算，除数能一直用139吗？", "single_evidence", "complete", None,
     [("factor", "UPS DIM 因子适用范围", "ups-dimensional-weight.md", "因子不能跨场景照搬", "UPS 美国页面列出的日常费率和零售费率可能使用不同除数，其他国家、运输方式和合同也可能不同。")]),
    ("prod-008", "跨境购物的到手价除了商品价还要算什么？", "single_evidence", "complete", None,
     [("cost", "到手成本组成", "cross-border-landed-cost.md", "成本组成", "一个可复核的估算应分开记录商品价、国际运费、保险、关税、进口增值税或销售税、清关/处理费，以及支付或币种转换成本。")]),
    ("prod-009", "从欧盟外网购寄进欧盟，22欧以下是不是还免VAT？", "single_evidence", "complete", None,
     [("vat", "欧盟低值包裹 VAT 规则", "eu-import-vat-ioss.md", "基本变化", "欧盟委员会说明，自 2021 年 7 月 1 日起，价值不超过 22 欧元进口小包的 VAT 豁免被取消，进口欧盟的商品原则上均涉及 VAT。")]),
    ("prod-010", "欧盟买餐具，只写食品级就够了吗？", "single_evidence", "complete", None,
     [("fcm", "食品接触材料证据要求", "eu-food-contact-materials.md", "选购时需要的证据", "不能只凭“食品级”营销词判断。")]),
    ("prod-011", "露营头灯是不是流明越高越好？", "single_evidence", "complete", None,
     [("lamp", "亮度与光束选择", "headlamp-selection-guide.md", "先按使用任务选光型", "流明表示总光输出，但不能单独代表实际照射距离，光学设计也会影响使用效果。")]),
    ("prod-012", "标着20寸登机箱就能上所有航司吗？", "single_evidence", "complete", None,
     [("bag", "登机尺寸并非全球统一", "carry-on-luggage-selection.md", "尺寸没有全球统一答案", "“登机箱”是营销名称，不代表适用于所有航司。")]),
    ("prod-013", "我要带充电宝飞日本，买之前和出发前分别核对什么？", "cross_evidence", "complete", None,
     [("global", "通用容量和随身规则", "power-bank-air-travel-global.md", "核对容量和标识", "先找额定能量 Wh。常见通用边界是：不超过 100Wh 的消费电子备用锂电池通常可随身携带；超过 100Wh、但不超过 160Wh 的产品通常需要航司批准，并可能受数量限制；更高容量通常不适用于普通旅客携带。"),
      ("carrier", "ANA 具体承运规则", "japan-ana-battery-baggage.md", "容量与数量", "规则可能继续更新，所以本条目只用于形成核对清单，不替代订票后查看对应航班页面。")]),
    ("prod-014", "国内飞行带充电宝，满足3C是不是就一定能登机？", "cross_evidence", "complete", None,
     [("china", "中国境内 3C 规则", "china-domestic-power-bank-rule.md", "仍需同时核对的事项", "满足 3C 要求不代表自动满足全部航空要求。"),
      ("general", "通用容量与包装要求", "power-bank-air-travel-global.md", "包装与最终确认", "电池端子需要防短路，可保留原包装、给裸露端子贴绝缘胶带，或单独放进保护袋。")]),
    ("prod-015", "轻量天幕装大箱寄国外，怎么先估运费和到手成本？", "cross_evidence", "complete", None,
     [("weight", "体积重与计费重", "dhl-volumetric-weight.md", "估算方法", "测量应以完成包装后的外箱最大尺寸为准，而不是只用商品裸尺寸。"),
      ("landed", "到手成本字段", "cross-border-landed-cost.md", "必要输入", "估算前需要商品归类线索、申报价值和币种、原产地、发货地、目的国家/地区、运输方式、实际重量、包装尺寸和平台是否预收税费。")]),
    ("prod-016", "买个智能登机箱坐飞机，除了箱子大小还要核对什么？", "cross_evidence", "complete", None,
     [("battery", "智能箱电池要求", "smart-luggage-battery.md", "购买前看什么", "先确认电池用途、化学类型、Wh 标识，以及电池是否能由旅客无需专用工具安全拆下。"),
      ("size", "航司尺寸要求", "carry-on-luggage-selection.md", "尺寸没有全球统一答案", "选择时必须对照实际航司、票价产品和机型的尺寸、重量、件数规则。")]),
    ("prod-017", "从中国买塑料餐盒寄到欧盟，我要核对合规和税费哪些东西？", "cross_evidence", "complete", None,
     [("safety", "欧盟食品接触材料要求", "eu-food-contact-materials.md", "核心安全原则", "材料不应向食品迁移达到危害健康的水平，也不应以不可接受的方式改变食品成分、味道或气味；塑料、陶瓷等材料还可能适用更具体规则。"),
      ("tax", "欧盟进口 VAT 与 IOSS", "eu-import-vat-ioss.md", "用户需要核对什么", "购买时应确认平台或卖家是否使用 IOSS、结账价是否已含目的国 VAT、承运商是否另收清关或处理费，以及商品是否属于消费税商品或其他例外。")]),
    ("prod-018", "明天用DHL把这个箱子寄到法国，精确运费多少？", "unanswerable", "none", "missing_user_context", []),
    ("prod-019", "我这个充电宝现在是不是召回批次？", "unanswerable", "none", "realtime_required", []),
    ("prod-020", "下个月欧盟会不会把IOSS门槛改掉？", "unanswerable", "none", "realtime_required", []),
    ("prod-021", "不知道价格和目的国，直接告诉我这单要交多少税。", "unanswerable", "none", "missing_user_context", []),
    ("prod-022", "竹木餐具寄澳大利亚要过哪些检疫手续？", "knowledge_gap", "none", "knowledge_gap", []),
    ("prod-023", "这个没写型号的露营灯能不能在海水里泡半小时？", "knowledge_gap", "none", "missing_user_context", []),
    ("prod-024", "去加拿大用家里的吹风机，需要什么转换器？", "knowledge_gap", "none", "knowledge_gap", []),
]


def build_case(raw: tuple) -> dict:
    case_id, query, kind, answerability, missing_reason, needs = raw
    evidence, required = [], []
    for need_id, description, source, section, quote in needs:
        markdown = (CORPUS / source).read_text(encoding="utf-8")
        actual_section, occurrences = section_for_quote(markdown, quote)
        if occurrences != 1 or actual_section != section:
            raise ValueError(f"{case_id}/{need_id}: evidence 不唯一或 section 不一致")
        eid = evidence_id(source, section, quote)
        evidence.append({
            "evidence_id": eid, "source": source, "section": section, "quote": quote,
            "quote_sha256": quote_sha256(quote), "grade": 3, "supports": [need_id],
        })
        required.append({"need_id": need_id, "description": description, "gold_evidence_ids": [eid]})
    return {
        "id": case_id, "query": query, "primary_kind": kind, "answerability": answerability,
        "missing_reason": missing_reason, "evidence_ground_truth": evidence,
        "required_information_needs": required,
        "source_validity": "manifest_verified" if evidence else "not_applicable",
        "label_status": "curated_source_reviewed",
        "review_note": "由 Production V1 文档与其登记来源构建；冻结前仍建议抽查。",
        "schema_version": "production-sanity-v1",
    }


def main() -> None:
    rows = [build_case(case) for case in CASES]
    OUTPUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "count": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
