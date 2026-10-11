"""Build an attributed, capped demo catalog from the independently sampled ABO data.

Prices, inventory and shipping are explicitly simulated, never source facts.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import html
import json
import re
from pathlib import Path

# Ordered rules: narrow uses precede broad ambiguous matches. Bands are operator
# estimates in CNY, not scraped quotes, FX conversions, or statistical medians.
GROUPS = [
    ("汽车用品", 20, 300, "AUTO VEHICLE CAR_ FUEL_PUMP POWERSPORTS"),
    ("母婴用品", 15, 200, "BABY INFANT DIAPER"),
    ("宠物用品", 15, 300, "PET_ ANIMAL_ VIVARIUM AQUARIUM"),
    ("乐器配件", 30, 500, "INSTRUMENT GUITAR PERCUSSION MICROPHONE"),
    ("玩具游戏", 15, 250, "TOY GAME_DICE TABLETOP_GAME JIGSAW_PUZZLE"),
    ("箱包旅行", 30, 500, "BAG BACKPACK SUITCASE LUGGAGE WALLET PASSPORT"),
    ("鞋靴", 50, 500, "SHOES BOOT SANDAL SLIPPER SNEAKER"),
    ("服装服饰", 20, 300, "APPAREL SHIRT PANTS DRESS SOCK HAT CLOTHING SUIT_SET TRACK_SUIT OVERALLS CINCHER SUSPENDER LEHENGA EARMUFF GLOVE BELT"),
    ("珠宝配饰", 20, 500, "JEWEL FINEEARRING FINERING FINENECKLACE FASHIONRING EARRING NECKLACE BRACELET RING WATCH EYEWEAR ACCESSORY"),
    ("园艺庭院", 20, 500, "GARDEN PLANT AGRICULTURAL SHOVEL FOUNTAIN OUTBUILDING OUTDOOR_LIVING SWING"),
    ("运动户外", 20, 500, "SPORT FITNESS EXERCISE CYCLING GOLF CAMPING WALKING_STICK RECREATION YOGA BALL_ SPORT_RACKET"),
    ("照明灯具", 15, 300, "LIGHT_ LAMP LANTERN"),
    ("家具", 100, 3000, "CHAIR SOFA TABLE DESK CABINET SHELF DRESSER STOOL BED_FRAME FURNITURE"),
    ("床品家纺", 20, 400, "BED BATH TEXTILE TOWEL SHEET CURTAIN BLANKET PILLOW RUG MATTRESS"),
    ("美妆个护", 10, 200, "BEAUTY SKIN HAIR LIP_ COSMETIC EYELID EYEBROW FOUNDATION SHAMPOO PERFUME ORAL TOOTH BRUSH COMB SHAVING RAZOR NAIL MASSAGE"),
    ("清洁日用", 10, 150, "CLEANING DETERGENT JANITORIAL LAUNDRY DISINFECT TISSUE TRASH WASTE BROOM MOP_ CLEANER"),
    ("食品饮料", 5, 150, "GROCERY FOOD NUTS HERB SAUCE DAIRY SNACK CAKE COFFEE BREAD NOODLE WINE FRUIT VEGETABLE MEAT FISH SHELLFISH SPICE TEA_ TEA BEVERAGE DRINK JUICE MILK CHEESE CHOCOLATE CANDY SUGAR COOKIE CEREAL RICE PASTA CONDIMENT FLOUR HONEY PRETZEL LEAVENING THICKENING COOKING_OIL"),
    ("营养保健", 20, 200, "SUPPLEMENT VITAMIN HEALTH_PERSONAL_CARE NUTRITION"),
    ("家用电器", 100, 3000, "APPLIANCE AIR_CONDITIONER REFRIGERAT WASHER DISHWASHER VACUUM COOKING_OVEN BLENDER MIXER FOOD_PROCESSOR FOOD_DEHYDRATOR FRYER BURNER SLOW_COOKER SOUS_VIDE KETTLE TOASTER FAN_ HEATER HUMIDIFIER"),
    ("数码电脑", 30, 1500, "COMPUTER PHONE ELECTRONIC DIGITAL HEADPHONE AUDIO VIDEO CAMERA MONITOR SCANNER PRINTER NETWORK MEMORY FLASH_ CHARGING BATTERY AV_RECEIVER RECEIVER_OR_AMPLIFIER INPUT_PEN SCREEN_PROTECTOR DVD"),
    ("办公文具", 5, 200, "OFFICE WRITING PAPER PENCIL PEN_ NOTEBOOK BINDER STATIONERY LABEL BADGE INK TONER STAPLER"),
    ("五金工具", 10, 500, "TOOL HARDWARE WRENCH DRILL SAW_ CUTTER MECHANICAL TERMINAL SAFETY BISS PAINT CABLE ELECTRICAL LOCK FASTENER SCREW TAPE ADHESIVE"),
    ("厨房餐具", 10, 300, "KITCHEN DINNERWARE COOKWARE BAKEWARE PAN_ PAN POT_ POT BAKING ROASTING KNIFE SPOON FORK PLATE BOWL MUG GLASS CUP STRAW GARLIC_PRESS SLICER UTENSIL GRILL"),
    ("家居收纳装饰", 15, 500, "HOME STORAGE ORGANIZER DECOR WALL_ART SCULPTURE PICTURE_FRAME WALLPAPER MIRROR HOOK CADDY SWATCH"),
]
LABELS = {"HEADPHONES":"耳机", "SUITCASE":"行李箱", "BACKPACK":"双肩包", "CHAIR":"椅子", "SOFA":"沙发", "COFFEE":"咖啡", "NOTEBOOK_COMPUTER":"笔记本电脑", "CELLULAR_PHONE":"手机", "TABLE":"桌子", "LIGHT_BULB":"灯泡", "LAMP":"灯具", "TELEVISION":"电视", "REFRIGERATOR":"冰箱", "WASHER_DRYER_COMBINATION":"洗烘机", "AIR_CONDITIONER":"空调", "CELLULAR_PHONE_CASE":"手机壳", "PHONE_ACCESSORY":"手机配件", "BATTERY":"电池", "SHOES":"鞋", "SANDAL":"凉鞋", "BOOT":"靴子", "PET_SUPPLIES":"宠物用品", "BABY_PRODUCT":"母婴用品", "HOME":"家居用品", "GROCERY":"食品", "KITCHEN":"厨房用品", "LIGHT_FIXTURE":"照明灯具", "WALLET":"钱包", "SHAMPOO":"洗发水", "VACUUM_CLEANER":"吸尘器", "FOOD_BLENDER":"搅拌机", "HAT":"帽子", "RUG":"地毯", "OFFICE_PRODUCTS":"办公用品", "HANDBAG":"手提包", "SPORTING_GOODS":"运动用品"}
SPECIAL_PRICES = {"CELLULAR_PHONE_CASE":(15,100), "SOFA":(1500,6000), "CHAIR":(150,1500), "TABLE":(200,2500), "NOTEBOOK_COMPUTER":(2500,9000), "PERSONAL_COMPUTER":(2000,9000), "COMPUTER":(2000,9000), "CELLULAR_PHONE":(800,5000), "TELEVISION":(1000,6000), "REFRIGERATOR":(1500,7000), "AIR_CONDITIONER":(1800,6000), "WASHER_DRYER_COMBINATION":(1800,7000), "HEADPHONES":(30,600), "SUITCASE":(150,900), "BACKPACK":(60,400)}

# Explicit overrides handle ambiguous source names (TABLE in PORTABLE, etc.).
EXACT_TYPES = {
    "汽车用品": "STEERING_WHEEL_COVER LICENSE_PLATE_ATTACHMENT CARGO_STRAP",
    "母婴用品": "INFANT_TODDLER_CAR_SEAT STROLLER PACIFIER CHANGING_PAD_COVER",
    "玩具游戏": "NON_RIDING_TOY_VEHICLE PUZZLES VIDEO_GAME_ACCESSORIES ABIS_VIDEO_GAMES",
    "运动户外": "BOXING_GLOVE FISHING_EQUIPMENT SLEEPING_BAG PUNCHING_BAG GOLF_CLUB_BAG BARBELL ICE_CHEST KICK_SCOOTER MUSCLE_ROLLER ROWING_MACHINE SKATEBOARD STATIONARY_BICYCLE SWEATBAND TENT TREADMILL WATER_FLOTATION_DEVICE FREESTANDING_SHELTER",
    "鞋靴": "TECHNICAL_SPORT_SHOE SHOE_INSERT",
    "服装服饰": "CHILDRENS_COSTUME LEOTARD NECKTIE VEST",
    "珠宝配饰": "ACCESSORY CHARM FASHIONOTHER FINEOTHER SUNGLASSES",
    "家具": "BED DRESSER BEAN_BAG_CHAIR BENCH HEADBOARD OTTOMAN ROOM_DIVIDER",
    "床品家纺": "WINDOW_SHADE BODY_POSITIONER",
    "家居收纳装饰": "CANDLE CANDLE_HOLDER CLOCK BASKET BOTTLE_RACK CLOTHES_HANGER CLOTHES_RACK DRYING_RACK FIGURINE INCENSE LAUNDRY_HAMPER STORAGE_BAG VASE WALLPAPER JEWELRY_STORAGE SWATCH",
    "园艺庭院": "ARTIFICIAL_TREE VINE WILDLIFE_FEEDER WATER_PUMP",
    "照明灯具": "HOME_LIGHTING_ACCESSORY STRING_LIGHT",
    "厨房餐具": "BOTTLE THERMOS JAR PITCHER FLATWARE PLACEMAT BOTTLE_OPENER CAN_OPENER CASSEROLES CUTTING_BOARD DISHWARE_PLACE_SETTING DRINKING_CUP DRINKING_STRAW DRINK_COASTER DUTCH_OVENS ICE_CUBE_TRAY MEAL_HOLDER MEASURING_CUP PAPER_TOWEL_HOLDER SHEET_PAN BAKING_PAPER KITCHEN_TOOLS KNIFE_BLOCK_SET",
    "家用电器": "BREAD_MAKING_MACHINE COFFEE_MAKER JUICER RICE_COOKERS WASHER_DRYER_COMBINATION LAUNDRY_APPLIANCE ROBOTIC_VACUUM_CLEANER AIR_PURIFIER COUNTERTOP_OVEN ELECTRIC_FAN ELECTRIC_WATER_BOILER MICROWAVE_OVEN PRESSURE_COOKER WATER_PURIFICATION_UNIT PORTABLE_STOVE",
    "数码电脑": "AMAZON_BOOK_READER_ACCESSORY AMAZON_TABLET_ACCESSORY CE_ACCESSORY COMPUTER_INPUT_DEVICE_ACCESSORY GPS_OR_NAVIGATION_ACCESSORY PHONE_ACCESSORY WIRELESS_ACCESSORY PORTABLE_AUDIO PORTABLE_AV_DEVICE PORTABLE_ELECTRONIC_DEVICE_COVER PORTABLE_ELECTRONIC_DEVICE_MOUNT PORTABLE_ELECTRONIC_DEVICE_STAND ANTENNA BINOCULAR BLANK_MEDIA CALCULATOR CAMCORDER FLAT_SCREEN_DISPLAY_MOUNT GPS_OR_NAVIGATION_SYSTEM INPUT_MOUSE KEYBOARDS MICROSCOPES MOUSE_PAD MULTIPORT_HUB POWER_BANK POWER_CONVERTER POWER_STRIP POWER_SUPPLIES_OR_PROTECTION RADIO REMOTE_CONTROL SOUND_AND_RECORDING_EQUIPMENT SPEAKERS SURVEILANCE_SYSTEMS SYSTEM_POWER_DEVICE TELESCOPE TELEVISION TWO_WAY_RADIO",
    "办公文具": "INKJET_PRINTER_INK WRITING_INSTRUMENT ABIS_BOOK ART_AND_CRAFT_SUPPLY BOOKEND CARD_STOCK EDUCATIONAL_SUPPLIES ENVELOPE FILE_FOLDER MARKING_PEN PINBOARD SCISSORS SELF_STICK_NOTE SHIPPING_BOX STICKER_DECAL TEACHING_EQUIPMENT",
    "五金工具": "HARDWARE_CLAMP_VISE PAINT_BRUSH PORTABLE_TOOL_BOX UTILITY_KNIFE AIR_COMPRESSOR AIR_PUMP BUILDING_MATERIAL DOORSTOP FAUCET LADDER LAB_SUPPLY PLIERS PLUMBING_FIXTURE SAFE SEALS SHOWERHEAD THERMOPLASTIC_FILAMENT TOILET_SEAT UTILITY_CART_WAGON VALVE WHEEL",
    "美妆个护": "HAIR_COLORING_AGENT ASTRINGENT_SUBSTANCE BATHWATER_ADDITIVE BODY_DEODORANT BODY_LUBRICANT CONDITIONER EARPLUG ESSENTIAL_OIL FACE_SHAPING_MAKEUP MASCARA MOUTHWASH SLEEP_MASK SUNSCREEN",
    "清洁日用": "CLEANING_BRUSH TOOTHBRUSH_HOLDER TOILET_PAPER_HOLDER TOWEL_HOLDER WASTE_BAG AREA_DEODORIZER BUCKET PUMP_DISPENSER",
    "食品饮料": "EDIBLE_OIL_VEGETABLE VEGETABLE SALAD_DRESSING BAKING_MIX CRACKER JERKY LEGUME NUT_BUTTER PACKAGED_SOUP_AND_STEW PASTRY POPCORN POULTRY SPIRITS VINEGAR WATER",
    "营养保健": "HERBAL_SUPPLEMENT HEALTH_PERSONAL_CARE BLOOD_PRESSURE_MONITOR THERMOMETER WEIGH_SCALE FIRST_AID_KIT ORTHOPEDIC_BRACE PERSONAL_PILL_DISPENSER WOUND_DRESSING",
    "宠物用品": "LITTER_BOX",
}
EXACT_TYPES["家用电器"] += " DEHUMIDIFIER REFRIGERATOR FIREPLACE"
EXACT_TYPES["五金工具"] += " ELECTROMECHANICAL_GAUGE MULTITOOL SCREWDRIVER"
EXACT_TYPES["珠宝配饰"] += " FASHIONEARRING FASHIONNECKLACEBRACELETANKLET FINENECKLACEBRACELETANKLET JEWELRY JEWELRY_SET"
EXACT_TYPES["箱包旅行"] = "HANDBAG UMBRELLA"
EXACT_TYPES["美妆个护"] += " MASSAGER TOOTHBRUSH"
EXACT_TYPES["数码电脑"] += " NETWORKING_DEVICE NETWORKING_ROUTER"
EXACT_TYPES["厨房餐具"] += " PANTRY TIMER"
EXACT_TYPES["园艺庭院"] += " PLANTER"
EXACT_TYPES["运动户外"] += " SPORTING_GOODS TRANSPORT_RACK"
EXACT_TYPES["玩具游戏"] += " TOYS_AND_GAMES"
EXACT_GROUP = {kind: name for name, kinds in EXACT_TYPES.items() for kind in kinds.split()}
PRIORITY_TYPES = set("HEADPHONES CELLULAR_PHONE CELLULAR_PHONE_CASE NOTEBOOK_COMPUTER TELEVISION REFRIGERATOR CHAIR SOFA TABLE BACKPACK SUITCASE COFFEE BABY_PRODUCT PET_SUPPLIES SHOES GROCERY HOME KITCHEN VITAMIN GUITARS LIGHT_BULB OFFICE_PRODUCTS SPORTING_GOODS".split())


def field(row: dict, name: str) -> tuple[list[str], str]:
    raw = row.get(name) or []
    if isinstance(raw, str):
        return [raw], ""
    available = [v.get("language_tag", "") for v in raw if isinstance(v, dict) and v.get("value")]
    preferred = ["zh_CN", "en_US", "en_GB", "zh_TW"] + sorted({lang for lang in available if lang.startswith("en_")}) + available
    for lang in dict.fromkeys(preferred):
        selected = [str(v["value"]) for v in raw if isinstance(v, dict) and v.get("value") and v.get("language_tag", "") == lang]
        if selected:
            return selected, lang
    return [str(v["value"]) for v in raw if isinstance(v, dict) and v.get("value")], ""


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", text))).strip()


def classify(kind: str):
    if kind in {"MEDICATION", "OTC_MEDICATION", "PROFESSIONAL_HEALTHCARE", "ACCESSORY_OR_PART_OR_SUPPLY", "ABIS_DRUGSTORE"}:
        return None  # Unclear generic/medical types are not demo retail stock.
    if kind in EXACT_GROUP:
        return next(g for g in GROUPS if g[0] == EXACT_GROUP[kind])
    # These are kitchen uses, not edible foods or generic cleaning products.
    if kind in {"FOOD_SERVICE_SUPPLY", "FOOD_STORAGE_BAG", "FOOD_PREPARATION_MOLD", "FOOD_SLICER", "FOOD_PROCESSOR", "FOOD_BLENDER", "FOOD_MIXER", "FOOD_DEHYDRATOR"}:
        return next(g for g in GROUPS if g[0] == ("家用电器" if kind in {"FOOD_PROCESSOR", "FOOD_BLENDER", "FOOD_MIXER", "FOOD_DEHYDRATOR"} else "厨房餐具"))
    if kind in {"VACUUM_CLEANER", "CARPET_CLEANER"}:
        return next(g for g in GROUPS if g[0] == "家用电器")
    for group in GROUPS:
        if any(re.search(r"(?:^|_)" + re.escape(word.rstrip("_")) + r"(?:_|S?$)", kind) for word in group[3].split()):
            return group
    return None


def numeric(item: dict, units: dict[str, float]) -> float | None:
    value = item.get("normalized_value") or item
    try:
        number = float(value["value"])
        factor = units.get(str(value["unit"]).lower())
        if factor is not None and 0 < number < 1e8:
            return round(number * factor, 4)
    except (KeyError, ValueError, TypeError):
        pass
    return None


def convert(row: dict, group: tuple) -> dict:
    kind = field(row, "product_type")[0][0]
    name, low, high, _ = group
    identity = f"{row['domain_name']}:{row['item_id']}"
    # Preserve the application's P<digits> identity contract; reserve a long range.
    pid = "P" + str(int(hashlib.sha256(identity.encode()).hexdigest()[:20], 16)).zfill(25)
    title, language = field(row, "item_name")
    brand = field(row, "brand")[0]
    desc = field(row, "product_description")[0] or field(row, "bullet_point")[0]
    material = field(row, "material")[0]
    color = field(row, "color")[0]
    model = field(row, "model_number")[0]
    label = LABELS.get(kind, kind.replace("_", " ").title())
    low, high = SPECIAL_PRICES.get(kind, (low, high))
    fraction = int(hashlib.sha256((identity + ':price:v1').encode()).hexdigest()[:8], 16) / 0xffffffff
    price = min(high, max(low, round(low * ((high / low) ** fraction), 0) - 0.01))
    dimensions = {}
    for axis, value in (row.get("item_dimensions") or {}).items():
        cm = numeric(value, {"inches":2.54, "centimeters":1, "millimeters":0.1, "meters":100})
        if axis in {"length", "width", "height"} and cm is not None:
            dimensions[axis] = cm
    weight = next((v for value in row.get("item_weight", []) if (v := numeric(value, {"pounds":0.45359237,"kilograms":1,"grams":0.001,"ounces":0.028349523125})) is not None), 0)
    highlights = [{"label":"商品类型", "detail":label}, {"label":"数据说明", "detail":"商品资料来自 ABO；价格、库存、配送为演示规则，非实时销售报价。"}]
    if material:
        highlights.append({"label":"材质", "detail":" / ".join(map(clean, material))})
    provenance = {"dataset":"Amazon Berkeley Objects", "source":"https://amazon-berkeley-objects.s3.amazonaws.com/index.html", "license":"CC-BY-4.0", "source_type":kind, "source_country":row.get("country", ""), "price_kind":"demo", "price_basis":"operator_estimate_not_market_calibrated", "price_band_cny":[low,high], "inventory_kind":"simulated", "shipping_kind":"simulated", "imported_on":"2026-10-11"}
    return {
        "product_id":pid, "title":clean(title[0]), "brand":clean(brand[0]) if brand else "",
        "category":name, "localized_category":name + " " + label, "origin_country":"",
        "description":clean(" ".join(desc)) or clean(title[0]), "highlights":highlights,
        "ships_to":["CN","US","SG"], "skus":[{"sku_id":pid+"-S1", "spec":clean(" / ".join(color[:1]+model[:1])) or "来源默认规格", "price_major":round(price,2), "currency":"CNY", "stock":20}],
        "source_platform":"amazon_abo", "external_product_id":identity,
        "canonical_product_id":"", "material_tags":list(map(clean,material)), "localized_material":" / ".join(map(clean,material)),
        "weight_kg":weight, "dimensions_cm":dimensions, "tax_category":name,
        "rating_summary":None, "updated_at":"", "source_language":language or "unknown",
        "source_locale":row.get("country", ""), "data_provenance":json.dumps(provenance,ensure_ascii=False),
        "price_kind":"demo", "image_id":row.get("main_image_id", ""),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--image-metadata", type=Path, help="Official images.csv.gz; URLs only, images are not copied")
    args = parser.parse_args()
    groups = collections.defaultdict(lambda:collections.defaultdict(list))
    excluded = collections.Counter()
    for line in args.sample.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        kind = field(row,"product_type")[0][0]
        group = classify(kind)
        if group is None:
            excluded[kind] += 1
        else:
            groups[group[0]][kind].append((row,group))
    products = []
    for name, by_type in sorted(groups.items()):
        # One item from each subtype before taking another from the same subtype.
        ordered = sorted(by_type.items(), key=lambda pair: (pair[0] not in PRIORITY_TYPES, hashlib.sha256(pair[0].encode()).hexdigest()))
        queues = [sorted(v,key=lambda pair:(not field(pair[0], "item_name")[1].startswith(("zh_", "en_")), hashlib.sha256((pair[0]['item_id']+pair[0]['domain_name']).encode()).hexdigest())) for _,v in ordered]
        selected = []
        seen_ids = set()
        while queues and len(selected)<30:
            remaining = []
            for queue in queues:
                row,group = queue.pop(0)
                if row['item_id'] not in seen_ids:
                    seen_ids.add(row['item_id'])
                    selected.append(convert(row,group))
                if queue:
                    remaining.append(queue)
                if len(selected)==30:
                    break
            queues = remaining
        products.extend(selected)
    if args.image_metadata:
        wanted = {p["image_id"] for p in products}
        with gzip.open(args.image_metadata, "rt", encoding="utf-8", newline="") as stream:
            images = {r["image_id"]: r["path"] for r in csv.DictReader(stream) if r["image_id"] in wanted}
        for product in products:
            path = images.get(product["image_id"], "")
            if re.fullmatch(r"[a-zA-Z0-9/_-]+\.jpg", path) and ".." not in path:
                product["image_url"] = "https://amazon-berkeley-objects.s3.amazonaws.com/images/small/" + path
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in products),encoding="utf-8")
    report = {"total":len(products), "categories":dict(collections.Counter(p['category'] for p in products)), "unmapped_types":dict(excluded), "source_subtypes_selected":len({json.loads(p['data_provenance'])['source_type'] for p in products}), "images":sum(bool(p.get('image_url')) for p in products), "languages":dict(collections.Counter(p['source_language'] for p in products)), "price_kind":"demo_operator_estimate_not_live", "currency":"CNY"}
    args.output.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
