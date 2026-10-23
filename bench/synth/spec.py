"""Random but realistic purchase-bill specs. A spec is both the recipe a template
renders and the exact ground truth the benchmark scores against.

Everything is driven by a `random.Random` so a seed reproduces the same bill.

Spec layout (all money in rupees, floats rounded to 2 dp):

    {
      "id": "syn001",
      "template": "gst_modern",                # which renderer draws it
      "supplier": {"name", "address_lines", "phone", "gstin" | None, "fssai" | None, "email" | None,
                   "state", "state_code"},
      "buyer":    {"name", "display", "gstin", "address_lines"},
      "invoice_number": "26-27/1064",          # what a correct reader returns
      "invoice_number_printed": "26-27/1064",  # what is printed (differs when struck out)
      "invoice_date": "2026-08-29",            # ISO truth
      "date_printed": "29/08/2026",
      "tax_mode": "none" | "exclusive" | "inclusive",
      "items": [{"description", "hsn", "quantity", "unit", "rate", "tax_percent",
                 "taxable", "cgst", "sgst", "amount", "mrp" | None}],
      "items_on_page": N,                      # rows printed on this photo (< len(items) if continued)
      "totals": {"subtotal", "cgst", "sgst", "igst", "cess", "round_off", "grand_total"},
      "amount_in_words": "Rupees ... Only",
      "continued": bool,                       # page 1 of a multi-page bill: no totals printed
      "handwritten_items": bool,
      "corrections": {"invoice_number": {"printed", "new"} | None,
                      "quantity": {"row", "printed", "new"} | None},
      "notes": ["Bill-641", ...],              # receiver's pen notes
      "expected_review": bool,                 # would a correct system still flag this for a human?
      "expected_review_reasons": [...],
      "photo": {...}                           # degradation recipe, filled by effects
    }

For `inclusive` bills the printed line amount includes GST (like R K Mercantile);
for `exclusive` bills line amounts are pre-tax and CGST/SGST are added in the totals.
"""
import random
from datetime import date, timedelta

STATE_CODES = {"Kerala": "32", "Tamil Nadu": "33", "Karnataka": "29"}
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

BUYER = {
    "name": "GREENS ANGAADI AGRO PVT LTD",
    "gstin": "32AAHCG9621M1ZC",
    "address_lines": ["INFO Park Road, Kusumagiri P.O", "Kakkanad, Ernakulam - 682030"],
}
BUYER_DISPLAYS = [
    "GREENS ANGAADI AGRO PVT LTD (KAKKANAD)", "Greens Angaadi - Kakkanad", "GREENS ANGADI KKD",
    "Aeden Fresh, Kakkanad", "Greens Angaadi (Super Market)", "AEDEN FRESH KAKKANAD",
    "Greens Angadi Agro Pvt Ltd", "M/s Aeden Fresh Kakkanad",
]
# Handwritten customer lines on cash bills, as the vendor's boy writes them
BUYER_HANDWRITTEN = ["Aeden fresh, Kakkanad", "Greens Angadi KKD", "Aeden Fresh kakkanad",
                     "Greens Angaadi", "Aeden fresh KKD", "Green Angadi Kakkanad"]

PLACES = [("Aluva", "683101"), ("Ernakulam", "682011"), ("Kochi", "682016"), ("Tripunithura", "682301"),
          ("Kakkanad", "682030"), ("Edappally", "682024"), ("Perumbavoor", "683542"), ("Angamaly", "683572"),
          ("Thrissur", "680001"), ("Alappuzha", "688001"), ("Kalamassery", "683104"), ("Vyttila", "682019"),
          ("Muvattupuzha", "686661"), ("Kothamangalam", "686691"), ("Chalakudy", "680307")]
OUT_OF_STATE = [("Ooty", "643001", "Tamil Nadu"), ("Coimbatore", "641001", "Tamil Nadu"),
                ("Bengaluru", "560002", "Karnataka"), ("Mettupalayam", "641301", "Tamil Nadu")]
STREETS = ["Market Road", "Main Road", "Near Bus Stand", "Near Panchayath Office", "Wholesale Market",
           "Agricultural Urban Wholesale Market", "Near Railway Station", "Temple Road", "Bypass Junction",
           "M.G. Road", "Church Road", "Banerji Road", "Seaport-Airport Road", "Industrial Estate"]

# (name, kind) - kind picks the catalog. "pvt"/"firm"/"prop" decides the PAN 4th char.
SUPPLIERS = [
    ("GREEN LEAF", "veg", "prop"), ("SREE MURUGAN VEGETABLES", "veg", "prop"),
    ("MALABAR FRESH FARMS PVT LTD", "veg", "pvt"), ("KAIRALI AGRO TRADERS", "veg", "firm"),
    ("PERIYAR VEGETABLE COMPANY", "veg", "firm"), ("ST. JUDE VEGETABLES", "veg", "prop"),
    ("NUTRI LEAVES", "exotic", "firm"), ("HILLTOP EXOTIC FARMS", "exotic", "pvt"),
    ("NILGIRI GREENS", "exotic", "firm"), ("AEDEN FRUITS INTERNATIONAL PVT LTD", "fruit_import", "pvt"),
    ("NKA FRUITS", "fruit", "prop"), ("AL-AMEEN FRUITS", "fruit", "prop"),
    ("COCHIN FRUIT COMPANY", "fruit_import", "firm"), ("ROYAL FRUITS & NUTS", "fruit_import", "firm"),
    ("MURALYA DAIRY PRODUCTS PRIVATE LIMITED", "dairy", "pvt"), ("PERIYAR DAIRY PRODUCTS", "dairy", "firm"),
    ("MILKY WAY DAIRY", "dairy", "prop"), ("EGGS DAILY", "eggs", "firm"), ("A.K.S. TRADERS", "eggs", "prop"),
    ("ST. ANTONY'S EGG CENTRE", "eggs", "prop"), ("AADIDEV MUSHROOM WORLD", "mushroom", "prop"),
    ("MZ FARMS", "mushroom", "prop"), ("THALIR FRESH", "cut_veg", "prop"), ("KUTTANAD FRESH CUTS", "cut_veg", "prop"),
    ("SH FOODS", "beverage", "firm"), ("ALMOVA INTERNATIONAL", "packaged", "prop"),
    ("R K MERCANTILE", "frozen", "prop"), ("ARAYACHERRIL VARKEY & SONS PVT. LTD.", "packaged_food", "pvt"),
    ("UPTOWN URBAN FARMS PVT LTD", "microgreens", "pvt"), ("HYDRO HARVEST FARMS", "microgreens", "firm"),
    ("SEA KING FROZEN FOODS", "frozen", "firm"), ("MALABAR SPICES & MASALA", "spices", "firm"),
    ("KERALA BAKERS SUPPLY", "bakery", "firm"), ("CHAKKARA JAGGERY & SWEETS", "packaged_food", "prop"),
]

# catalog: kind -> [(description, hsn, unit, rate_lo, rate_hi, gst%, mrp_factor or None, qty kind)]
# qty kind: "kg" (decimals ok), "int" (whole units), "box" (small whole numbers)
CATALOG = {
    "veg": [
        ("AMARANTHUS GREEN BUNCH", "0709", "UNT", 12, 22, 0, None, "int"), ("ASH GOURD", "0709", "KGS", 22, 40, 0, None, "kg"),
        ("BAJI CHILLY", "0709", "KGS", 40, 80, 0, None, "kg"), ("BEANS BUSH", "0708", "KGS", 60, 120, 0, None, "kg"),
        ("BEETROOT OOTY", "0706", "KGS", 35, 60, 0, None, "kg"), ("BITTER GOURD GREEN", "0709", "KGS", 40, 70, 0, None, "kg"),
        ("BOTTLE GOURD", "0709", "KGS", 25, 45, 0, None, "kg"), ("BRINJAL GREEN LONG", "0709", "KGS", 30, 55, 0, None, "kg"),
        ("CABBAGE", "0704", "KGS", 20, 40, 0, None, "kg"), ("CAPSICUM GREEN", "0709", "KGS", 50, 90, 0, None, "kg"),
        ("CARROT OOTY", "0706", "KGS", 45, 80, 0, None, "kg"), ("CAULIFLOWER", "0704", "KGS", 35, 60, 0, None, "kg"),
        ("CHILLY GREEN", "0709", "KGS", 40, 90, 0, None, "kg"), ("COCONUT", "0801", "NOS", 25, 45, 0, None, "int"),
        ("CORIANDER LEAVES", "0709", "KGS", 60, 140, 0, None, "kg"), ("CUCUMBER SALAD", "0707", "KGS", 25, 50, 0, None, "kg"),
        ("CURRY LEAVES", "0709", "KGS", 40, 80, 0, None, "kg"), ("DRUMSTICK", "0709", "KGS", 50, 180, 0, None, "kg"),
        ("GARLIC (INDIAN)", "0703", "KGS", 120, 260, 0, None, "kg"), ("GINGER", "0910", "KGS", 80, 180, 0, None, "kg"),
        ("KOVAKKA", "0709", "KGS", 40, 75, 0, None, "kg"), ("LADIES FINGER", "0709", "KGS", 35, 70, 0, None, "kg"),
        ("LEMON", "0805", "KGS", 60, 140, 0, None, "kg"), ("ONION BIG", "0703", "KGS", 28, 55, 0, None, "kg"),
        ("ONION SMALL (SAMBAR)", "0703", "KGS", 50, 110, 0, None, "kg"), ("POTATO", "0701", "KGS", 25, 45, 0, None, "kg"),
        ("PUMPKIN", "0709", "KGS", 18, 35, 0, None, "kg"), ("RAW BANANA (NENDRAN)", "0803", "KGS", 40, 70, 0, None, "kg"),
        ("SNAKE GOURD", "0709", "KGS", 30, 55, 0, None, "kg"), ("SWEET POTATO", "0714", "KGS", 40, 70, 0, None, "kg"),
        ("TOMATO HYBRID", "0702", "KGS", 18, 60, 0, None, "kg"), ("YAM (CHENA)", "0714", "KGS", 40, 70, 0, None, "kg"),
        ("TAPIOCA", "0714", "KGS", 25, 45, 0, None, "kg"), ("MINT LEAVES", "0709", "UNT", 10, 20, 0, None, "int"),
    ],
    "exotic": [
        ("PEELED BABY CORN", "0709", "PACK", 35, 60, 0, None, "int"), ("BASIL LEAVES", "0709", "PACK", 25, 45, 0, None, "int"),
        ("BROCCOLI", "0704", "Kilogram", 180, 280, 0, None, "kg"), ("RED CABBAGE", "0704", "Kilogram", 60, 95, 0, None, "kg"),
        ("CAPSICUM RED", "0709", "Kilogram", 140, 220, 0, None, "kg"), ("CAPSICUM YELLOW", "0709", "Kilogram", 140, 220, 0, None, "kg"),
        ("CELERY", "0709", "Kilogram", 90, 140, 0, None, "kg"), ("CHERRY TOMATO RED", "0702", "PACK", 45, 75, 0, None, "int"),
        ("CHINESE CABBAGE", "0704", "Kilogram", 40, 70, 0, None, "kg"), ("ICEBERG LETTUCE", "0705", "Kilogram", 50, 90, 0, None, "kg"),
        ("ZUCCHINI GREEN", "0709", "Kilogram", 70, 120, 0, None, "kg"), ("ZUCCHINI YELLOW", "0709", "Kilogram", 80, 130, 0, None, "kg"),
        ("LEEKS", "0703", "Kilogram", 150, 240, 0, None, "kg"), ("ROMAINE LETTUCE", "0705", "Kilogram", 110, 160, 0, None, "kg"),
        ("SPRING ONION", "0703", "Kilogram", 90, 140, 0, None, "kg"), ("THYME", "0709", "PACK", 25, 45, 0, None, "int"),
        ("ROSEMARY", "0709", "PACK", 25, 45, 0, None, "int"), ("BABY POTATO", "0701", "Kilogram", 45, 70, 0, None, "kg"),
        ("SWEET CORN", "0709", "PC", 18, 32, 0, None, "int"), ("KALE", "0704", "PACK", 15, 30, 0, None, "int"),
        ("PARSLEY CURLY", "0709", "PACK", 18, 30, 0, None, "int"), ("RED RADISH", "0706", "Kilogram", 55, 90, 0, None, "kg"),
    ],
    "fruit_import": [
        ("BLACK GRAPES CHINA - 5 KG", "0806", "Boxes", 1500, 1900, 0, None, "box"),
        ("RED GLOBE CHINA - 6.5 KG", "0806", "Boxes", 1300, 1700, 0, None, "box"),
        ("BLUEBERRY PERU 1.5 KG - 12 PACK", "0810", "Boxes", 2100, 2600, 0, None, "box"),
        ("KIWI CRATE CHILE - 10 KG", "0810", "Boxes", 3400, 4100, 0, None, "box"),
        ("LONGAN THAILAND - 11.5 KG", "0810", "Boxes", 2200, 2800, 0, None, "box"),
        ("DRAGON WHITE VIETNAM - 9 KG", "0810", "Boxes", 1100, 1500, 0, None, "box"),
        ("PEAR RED SOUTH AFRICA - 12.5 KG", "0808", "Boxes", 4100, 4800, 0, None, "box"),
        ("PEAR GREEN SOUTH AFRICA - 12.5 KG", "0808", "Boxes", 4100, 4800, 0, None, "box"),
        ("GRANNY SMITH NEW ZEALAND - 18 KG", "0808", "Boxes", 4200, 4900, 0, None, "box"),
        ("PINK LADY NEW ZEALAND - 18 KG", "0808", "Boxes", 3900, 4500, 0, None, "box"),
        ("RED DELICIOUS USA - 18 KG", "0808", "Boxes", 4300, 4900, 0, None, "box"),
        ("FUJI APPLE CHINA - 10 KG", "0808", "Boxes", 2900, 3500, 0, None, "box"),
        ("ORANGE MANDARIN EGYPT - 15 KG", "0805", "Boxes", 2400, 3000, 0, None, "box"),
        ("RASPBERRY (PUNNETS)", "0810", "Punnets", 210, 270, 0, None, "int"),
        ("BLACKBERRY (PUNNETS)", "0810", "Punnets", 210, 270, 0, None, "int"),
        ("AVOCADO TANZANIA - 4 KG", "0804", "Boxes", 1400, 1900, 0, None, "box"),
    ],
    "fruit": [
        ("ANAR", "0810", "KG", 160, 240, 0, None, "kg"), ("CAVENDISH BANANA", "0803", "KG", 35, 55, 0, None, "kg"),
        ("NENDRAN BANANA", "0803", "KG", 55, 80, 0, None, "kg"), ("NJALI POOVAN", "0803", "KG", 70, 110, 0, None, "kg"),
        ("PACHAKAYA (RAW BANANA)", "0803", "KG", 50, 75, 0, None, "kg"), ("THAI KOYYA (GUAVA)", "0804", "KG", 90, 130, 0, None, "kg"),
        ("PAPPAYA", "0807", "KG", 30, 50, 0, None, "kg"), ("SAPOTA", "0810", "KG", 60, 100, 0, None, "kg"),
        ("KIRAN WATERMELON", "0807", "KG", 16, 28, 0, None, "kg"), ("SIMLA APPLE", "0808", "KG", 160, 230, 0, None, "kg"),
        ("MOSAMBI", "0805", "KG", 55, 90, 0, None, "kg"), ("PINEAPPLE", "0804", "KG", 45, 75, 0, None, "kg"),
        ("SIMLA GOLDEN APPLE", "0808", "PACK", 50, 70, 0, None, "int"), ("GRAPES SEEDLESS", "0806", "KG", 80, 140, 0, None, "kg"),
        ("MANGO BANGANAPALLI", "0804", "KG", 90, 160, 0, None, "kg"),
    ],
    "dairy": [
        ("SACHET MILK 450 ML", "04012000", "ML", 25, 29, 0, None, "int"), ("PET MILK 1000 ML", "04012000", "L", 62, 70, 0, None, "int"),
        ("WHOLE MILK 1000 ML", "04012000", "L", 70, 78, 0, None, "int"), ("CURD 500 G SACHET", "04031000", "500g", 28, 34, 5, None, "int"),
        ("PROBIOTIC CURD 400 GM", "04031000", "400g", 38, 46, 5, None, "int"), ("BUTTER MILK 200 ML", "04039090", "Nos", 9, 13, 5, None, "int"),
        ("GHEE 500 ML", "04059020", "Nos", 300, 360, 12, None, "int"), ("PANEER 200 G", "04061000", "Nos", 80, 100, 5, None, "int"),
        ("BUTTER 100 G", "04051000", "Nos", 52, 60, 12, None, "int"),
    ],
    "eggs": [
        ("WHITE EGG PACK 6", "0407", "Pack", 46, 54, 0, None, "int"), ("WHITE EGG PACK 12", "0407", "Pack", 92, 104, 0, None, "int"),
        ("WHITE EGG PACK 30", "0407", "Tray", 190, 220, 0, None, "int"), ("BROWN EGG PACK 6", "0407", "Pack", 52, 60, 0, None, "int"),
        ("BROWN EGG PACK 12", "0407", "Pack", 102, 115, 0, None, "int"), ("NADAN EGG PACK 6", "0407", "Pack", 52, 60, 0, None, "int"),
        ("NADAN EGG PACK 12", "0407", "Pack", 104, 118, 0, None, "int"), ("QUAIL EGG PACK 12", "0407", "Pack", 46, 58, 0, None, "int"),
        ("DUCK EGG PACK 6", "0407", "Pack", 70, 90, 0, None, "int"),
    ],
    "mushroom": [
        ("BUTTON MUSHROOM", "0709", "Pkt", 45, 60, 0, None, "int"), ("MILKY MUSHROOM", "0709", "Pkt", 50, 65, 0, None, "int"),
        ("OYSTER MUSHROOM", "0709", "Pkt", 60, 75, 0, None, "int"),
    ],
    "cut_veg": [
        ("AVIAL CUT", "0709", "Pkt", 40, 50, 0, None, "int"), ("SAMBAR CUT", "0709", "Pkt", 32, 40, 0, None, "int"),
        ("KAYAM PAYAR CUT", "0709", "Pkt", 38, 46, 0, None, "int"), ("KOVAKKA CUT", "0709", "Pkt", 38, 46, 0, None, "int"),
        ("PAPPAYA CUT", "0709", "Pkt", 38, 46, 0, None, "int"), ("VENDAKKA CUT", "0709", "Pkt", 38, 46, 0, None, "int"),
        ("BEANS CUT", "0709", "Pkt", 38, 46, 0, None, "int"), ("PLANTAIN FLOWER", "0709", "Pkt", 38, 46, 0, None, "int"),
        ("CHEERA CUT", "0709", "Pkt", 45, 52, 0, None, "int"), ("JACKFRUIT RIPE", "0810", "Pkt", 85, 95, 0, None, "int"),
        ("COCONUT GRATED", "0801", "Pkt", 55, 65, 0, None, "int"),
    ],
    "beverage": [
        ("KUMBAYAH BERRY MIX 275 ML", "2202992", "Nos", 98, 106, 5, 149, "int"),
        ("KUMBAYAH BLACK DETOX 275ML", "2202992", "Nos", 98, 106, 5, 149, "int"),
        ("KUMBAYAH MANGO 275ML", "2202992", "Nos", 98, 106, 5, 149, "int"),
        ("KUMBAYAH PASSION BLOSSOM 275ML", "2202992", "Nos", 98, 106, 5, 149, "int"),
        ("TENDER COCONUT WATER 200 ML", "2202990", "Nos", 30, 38, 12, 50, "int"),
        ("COLD PRESSED ORANGE 250 ML", "2202990", "Nos", 70, 82, 12, 110, "int"),
    ],
    "packaged": [
        ("LANGNESE BLACK FOREST HONEY 125GM", "17026090", "Pcs", 320, 345, 5, None, "int"),
        ("LANGNESE FOREST HONEY 500G", "17029030", "Pcs", 1250, 1350, 5, None, "int"),
        ("LANGNESE WHITE HONEY 500GM", "18069090", "Pcs", 1250, 1350, 5, None, "int"),
        ("ORGANIC JAGGERY POWDER 500G", "17011390", "Pcs", 70, 90, 5, None, "int"),
        ("DATES PREMIUM 500 G", "08041020", "Pcs", 180, 260, 12, None, "int"),
        ("ALMONDS CALIFORNIA 250 G", "08021200", "Pcs", 230, 290, 12, None, "int"),
    ],
    "packaged_food": [
        ("INSTANT EDIYAPPAM 1 KG", "21061000", "Nos", 70, 76, 5, None, "int"),
        ("INSTANT PUNCHA EDIYAPPAM 1 KG", "21061000", "Nos", 66, 72, 5, None, "int"),
        ("INSTANT VEG PALAPPAM 1 LTR", "21061000", "Nos", 66, 72, 5, None, "int"),
        ("INSTANT DOSA BATTER 1 LTR", "21061000", "Nos", 55, 65, 5, None, "int"),
        ("INSTANT IDLY BATTER 1 LTR", "21061000", "Nos", 55, 65, 5, None, "int"),
        ("ROASTED RAVA 1 KG", "11031100", "Nos", 60, 70, 5, None, "int"),
        ("PUTTU PODI 1 KG", "11029090", "Nos", 70, 80, 5, None, "int"),
        ("JAGGERY BALL 1 KG", "17011390", "Nos", 75, 90, 5, None, "int"),
    ],
    "frozen": [
        ("FROZEN CHICKEN BONELESS BREAST", "02071200", "KGS", 330, 390, 5, None, "kg"),
        ("FROZEN CHICKEN DRUMSTICK", "02071400", "KGS", 260, 300, 5, None, "kg"),
        ("FROZEN PRAWNS 500 G", "03061790", "Nos", 280, 340, 5, None, "int"),
        ("FROZEN GREEN PEAS 1 KG", "07102100", "Nos", 140, 170, 5, None, "int"),
        ("FROZEN SWEET CORN 1 KG", "07104000", "Nos", 150, 180, 5, None, "int"),
        ("FROZEN PARATHA 20 PCS", "19059090", "Nos", 160, 190, 18, None, "int"),
    ],
    "microgreens": [
        ("BASIL", "0709", "Units", 45, 52, 0, None, "int"), ("PARSLEY", "0709", "Units", 45, 52, 0, None, "int"),
        ("ROMAINE", "0705", "Units", 52, 60, 0, None, "int"), ("CURLY GREEN", "0705", "Units", 52, 60, 0, None, "int"),
        ("BOK CHOY", "0704", "Units", 45, 52, 0, None, "int"), ("CELERY", "0709", "Units", 42, 50, 0, None, "int"),
        ("CHERRY TOMATO", "0702", "Units", 52, 60, 0, None, "int"), ("MIXED MICROGREENS", "0709", "Units", 100, 110, 0, None, "int"),
        ("SUNFLOWER MICROGREENS", "0709", "Units", 100, 110, 0, None, "int"),
    ],
    "spices": [
        ("PEPPER BLACK 250 G", "09041140", "Pkt", 170, 210, 5, None, "int"), ("CARDAMOM 100 G", "09083120", "Pkt", 260, 340, 5, None, "int"),
        ("TURMERIC POWDER 500 G", "09103030", "Pkt", 110, 140, 5, None, "int"), ("CHILLI POWDER 500 G", "09042211", "Pkt", 140, 180, 5, None, "int"),
        ("CORIANDER POWDER 500 G", "09092200", "Pkt", 90, 120, 5, None, "int"), ("GARAM MASALA 100 G", "09109100", "Pkt", 60, 80, 5, None, "int"),
        ("SAMBAR POWDER 200 G", "21039040", "Pkt", 55, 70, 5, None, "int"),
    ],
    "bakery": [
        ("SANDWICH BREAD 400 G", "19059010", "Nos", 36, 44, 0, None, "int"), ("BROWN BREAD 400 G", "19059010", "Nos", 42, 50, 0, None, "int"),
        ("RUSK 200 G", "19054000", "Nos", 34, 42, 5, None, "int"), ("PLUM CAKE 400 G", "19059020", "Nos", 160, 200, 18, None, "int"),
        ("BUN (PACK OF 4)", "19059090", "Nos", 28, 34, 0, None, "int"), ("COOKIES BUTTER 200 G", "19053100", "Nos", 70, 90, 18, None, "int"),
    ],
}

# Template-specific item count ranges
ITEM_RANGES = {"gst_modern": (3, 14), "tally": (4, 17), "dotmatrix": (12, 48), "handbook": (1, 12),
               "software": (1, 8), "carbon": (2, 8)}

# Which supplier kinds fit which template
TEMPLATE_KINDS = {
    "gst_modern": ["dairy", "beverage", "packaged_food", "frozen", "spices", "bakery", "packaged"],
    "tally": ["fruit_import", "fruit", "exotic", "veg", "spices"],
    "dotmatrix": ["veg", "exotic"],
    "handbook": ["eggs", "mushroom", "cut_veg", "microgreens", "veg", "fruit", "bakery"],
    "software": ["frozen", "packaged", "beverage", "bakery", "dairy"],
    "carbon": ["packaged", "packaged_food", "fruit_import", "spices"],
}

ONES = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen "
        "Sixteen Seventeen Eighteen Nineteen").split()
TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _below_100(n):
    return ONES[n] if n < 20 else TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])


def _below_1000(n, with_and=False):
    h, r = divmod(n, 100)
    parts = []
    if h:
        parts.append(ONES[h] + " Hundred")
    if r:
        parts.append(("and " if (h and with_and) else "") + _below_100(r))
    return " ".join(parts)


def number_to_words(n, with_and=False):
    """Indian numbering: 2,05,00,123 -> 'Two Crore Five Lakh One Hundred Twenty Three'."""
    n = int(n)
    if n == 0:
        return "Zero"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        q, n = divmod(n, size)
        if q:
            parts.append(_below_1000(q) + " " + name)
    if n:
        parts.append(_below_1000(n, with_and))
    return " ".join(parts)


def amount_in_words(total, rng):
    rupees, paise = divmod(int(round(total * 100)), 100)
    with_and = rng.random() < 0.4
    w = number_to_words(rupees, with_and)
    paise_txt = f" and {_below_100(paise)} Paise" if paise else ""
    style = rng.choice(["rupees_only", "inr_only", "only", "indian_rupees"])
    if style == "rupees_only":
        s = f"Rupees {w}{paise_txt} Only"
    elif style == "inr_only":
        s = f"INR {w}{paise_txt} Only"
    elif style == "indian_rupees":
        s = f"{w} INDIAN RUPEES{paise_txt} Only"
    else:
        s = f"{w} Rupees{paise_txt} Only"
    return s.upper() if rng.random() < 0.2 else s


def make_gstin(rng, state_code, entity_kind="firm"):
    """A synthetic GSTIN with a valid check character. PAN 4th char: P person, C company, F firm."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    fourth = {"prop": "P", "pvt": "C", "firm": "F"}[entity_kind]
    pan = "".join(rng.choice(letters) for _ in range(3)) + fourth + rng.choice(letters) + \
        "".join(rng.choice("0123456789") for _ in range(4)) + rng.choice(letters)
    body = state_code + pan + rng.choice("1112") + "Z"
    total = 0
    for i, ch in enumerate(body):
        p = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return body + GSTIN_CHARS[(36 - total % 36) % 36]


def _qty(rng, kind):
    if kind == "kg":
        return rng.choice([rng.randint(1, 40), round(rng.uniform(0.5, 30), rng.choice([1, 2, 3]))])
    if kind == "box":
        return rng.randint(1, 15)
    return rng.choice([rng.randint(1, 12), rng.randint(5, 60), rng.randint(10, 100)])


def _rate(rng, lo, hi):
    r = rng.uniform(lo, hi)
    return round(r) if rng.random() < 0.6 or hi >= 500 else round(r * 4) / 4 if rng.random() < 0.5 else round(r, 2)


def r2(x):
    return round(x + 1e-9, 2)


INVOICE_FORMATS = [
    lambda rng: f"26-27/{rng.randint(100, 9999)}", lambda rng: f"INV/2026/{rng.randint(100000, 199999)}",
    lambda rng: f"B1/FS/{rng.randint(10000, 19999):06d}", lambda rng: f"{rng.choice(['SH', 'KF', 'MF', 'PV'])}/KK/{rng.randint(100, 2999)}/26-27",
    lambda rng: f"{rng.choice(['ALM', 'CFC', 'RFN'])}/B2B/{rng.randint(100, 2999)}", lambda rng: f"COK26-27/{rng.randint(1000, 2999)}",
    lambda rng: f"EKM/2026/{rng.randint(1000, 4999)}", lambda rng: f"GST/{rng.randint(1000, 9999)}/26-27",
    lambda rng: f"TI-{rng.randint(10000, 99999)}", lambda rng: f"{rng.randint(1000, 9999)}",
]


def date_printed(d, rng, handwritten=False):
    if handwritten:
        return rng.choice([f"{d.day}/{d.month}/{d.year % 100}", f"{d.day}/{d.month:02d}/{d.year % 100}",
                           f"{d.day}-{d.month}-{d.year}", f"{d.day:02d}/{d.month:02d}/{d.year}"])
    return rng.choice([d.strftime("%d/%m/%Y"), d.strftime("%d-%m-%Y"), d.strftime("%d-%b-%y"),
                       d.strftime("%d.%m.%Y"), d.strftime("%d/%m/%y"), d.strftime("%d-%b-%Y")])


def make_supplier(rng, template):
    kinds = TEMPLATE_KINDS[template]
    candidates = [s for s in SUPPLIERS if s[1] in kinds]
    name, kind, entity = rng.choice(candidates)
    # Out-of-state suppliers only sell 0%-GST produce here: an inter-state taxed bill would need IGST,
    # which the templates don't model yet.
    if rng.random() < 0.15 and kind in ("exotic", "fruit_import"):
        city, pin, state = rng.choice(OUT_OF_STATE)
    else:
        (city, pin), state = rng.choice(PLACES), "Kerala"
    code = STATE_CODES[state]
    building = rng.choice([f"{rng.randint(1, 60)}/{rng.randint(100, 999)}", f"XIII/{rng.randint(100, 400)}",
                           f"Door No. {rng.randint(1, 80)}/{rng.randint(10, 999)}-{rng.choice('ABC')}",
                           f"P{rng.randint(4, 60)}/{rng.randint(10, 60)}"])
    # Small cash vendors (bill books) often have no GSTIN
    has_gstin = rng.random() < (0.45 if template == "handbook" else 0.97)
    return kind, {
        "name": name,
        "address_lines": [f"{building}, {rng.choice(STREETS)}", f"{city}, {state} - {pin}"],
        "phone": rng.choice(["9", "8", "7"]) + "".join(rng.choice("0123456789") for _ in range(9)),
        "gstin": make_gstin(rng, code, entity) if has_gstin else None,
        "fssai": "1" + "".join(rng.choice("0123456789") for _ in range(13)) if rng.random() < 0.6 else None,
        "email": (name.split()[0].lower().strip(".,'&") + rng.choice(["@gmail.com", "fresh@gmail.com", "@yahoo.in"]))
        if rng.random() < 0.5 else None,
        "state": state, "state_code": code,
    }


def make_items(rng, template, kind, tax_mode):
    lo, hi = ITEM_RANGES[template]
    n = rng.randint(lo, hi)
    pool = list(CATALOG[kind])
    if template == "dotmatrix" and n > len(pool):   # long wholesale sheets mix veg and exotic produce
        pool += [p for k in ("veg", "exotic") if k != kind for p in CATALOG[k]]
    chosen = rng.sample(pool, min(n, len(pool)))
    items = []
    for desc, hsn, unit, rlo, rhi, gst, mrp, qkind in chosen:
        q = _qty(rng, qkind)
        rate = _rate(rng, rlo, rhi)
        if template == "handbook":   # nobody writes paise rates in a cash bill book
            rate = round(rate * 2) / 2 if rng.random() < 0.1 else float(round(rate))
        if tax_mode == "none":
            gst = 0
        taxable = r2(q * rate)
        cgst = sgst = r2(taxable * gst / 200)
        amount = r2(taxable + cgst + sgst) if tax_mode == "inclusive" else taxable
        items.append({"description": desc, "hsn": hsn, "quantity": q, "unit": unit, "rate": rate,
                      "tax_percent": gst, "taxable": taxable, "cgst": cgst, "sgst": sgst, "amount": amount,
                      "mrp": mrp})
    return items


def make_totals(rng, items, tax_mode):
    subtotal = r2(sum(i["taxable"] for i in items))
    cgst = r2(sum(i["cgst"] for i in items))
    sgst = r2(sum(i["sgst"] for i in items))
    raw = subtotal + cgst + sgst if tax_mode != "none" else subtotal
    round_to_rupee = rng.random() < 0.55
    grand = float(round(raw)) if round_to_rupee else r2(raw)
    round_off = r2(grand - raw) if round_to_rupee and abs(grand - raw) >= 0.005 else 0.0
    return {"subtotal": subtotal, "cgst": cgst if tax_mode != "none" else 0.0, "sgst": sgst if tax_mode != "none" else 0.0,
            "igst": 0.0, "cess": 0.0, "round_off": round_off, "grand_total": grand}


def make_spec(rng, bill_id, template, bill_date=None):
    """One random bill for `template`. Modifiers (stamp, rotation, notes, corrections, continued
    pages) are decided here so the ground truth accounts for them; templates and effects render them."""
    kind, supplier = make_supplier(rng, template)
    handwritten = template == "handbook"
    if not supplier["gstin"] or not any(row[5] for row in CATALOG[kind]):
        tax_mode = "none"   # an unregistered supplier cannot charge GST
    elif template in ("gst_modern", "software", "carbon"):
        tax_mode = rng.choice(["exclusive", "exclusive", "inclusive"])
    else:
        tax_mode = "exclusive"
    items = make_items(rng, template, kind, tax_mode)
    if tax_mode != "none" and not any(it["tax_percent"] for it in items):
        tax_mode = "none"   # only 0% items were picked: a plain bill, not a tax invoice
    totals = make_totals(rng, items, tax_mode)
    d = bill_date or date(2026, 8, 24) + timedelta(days=rng.randint(0, 8))
    inv = str(rng.randint(100, 9999)) if handwritten else rng.choice(INVOICE_FORMATS)(rng)

    continued = template in ("dotmatrix", "tally") and len(items) >= 14 and rng.random() < 0.2
    # a real page 1 is full; the rest of the rows are on the next page
    items_on_page = rng.randint(max(8, int(len(items) * 0.75)), len(items) - 2) if continued else len(items)
    if continued:
        # the photo shows only page 1: truth is the rows on this page and no total
        items = items[:items_on_page]
        totals = {k: None for k in totals}

    corrections = {"invoice_number": None, "quantity": None}
    if not handwritten and rng.random() < 0.06:
        new = inv.rsplit("/", 1)[0] + "/" + str(rng.randint(1000, 9999)) if "/" in inv else str(rng.randint(1000, 9999))
        corrections["invoice_number"] = {"printed": inv, "new": new}
    if handwritten and len(items) >= 2 and rng.random() < 0.15:
        row = rng.randrange(len(items))
        it = items[row]
        printed_q = it["quantity"]
        new_q = max(1, printed_q - rng.randint(1, 3)) if isinstance(printed_q, int) else r2(max(0.5, printed_q - 1))
        corrections["quantity"] = {"row": row, "printed": printed_q, "new": new_q}
        # the vendor corrected the qty AND the amount by hand; truth follows the correction
        it["quantity"] = new_q
        it["taxable"] = r2(new_q * it["rate"])
        it["cgst"] = it["sgst"] = r2(it["taxable"] * it["tax_percent"] / 200)
        it["amount"] = r2(it["taxable"] + it["cgst"] + it["sgst"]) if tax_mode == "inclusive" else it["taxable"]
        totals = make_totals(rng, items, tax_mode)

    notes = []
    if rng.random() < 0.8:
        notes.append(rng.choice(["Bill-", "BIL-", "Bill - ", "B/L ", "Bil "]) + str(rng.randint(600, 699)))
    if rng.random() < 0.15:
        notes.append(rng.choice(["quality issue return", "not received", "GRN done", "short 2 kg", "Rate diff"]))

    reasons = []
    if handwritten:
        reasons.append("handwritten")
    if continued:
        reasons.append("continued")
    if corrections["invoice_number"]:
        reasons.append("invoice number corrected")
    if not supplier["gstin"]:
        reasons.append("no supplier GSTIN")

    gt_total = totals["grand_total"]
    spec = {
        "id": bill_id, "template": template, "supplier_kind": kind,
        "supplier": supplier,
        "buyer": {**BUYER, "display": rng.choice(BUYER_HANDWRITTEN if handwritten else BUYER_DISPLAYS)},
        "invoice_number": corrections["invoice_number"]["new"] if corrections["invoice_number"] else inv,
        "invoice_number_printed": inv,
        "invoice_date": d.isoformat(),
        "date_printed": date_printed(d, rng, handwritten),
        "tax_mode": tax_mode,
        "items": items,
        "items_on_page": len(items),
        "totals": totals,
        "amount_in_words": amount_in_words(gt_total, rng) if gt_total is not None else None,
        "continued": continued,
        "handwritten_items": handwritten,
        "corrections": corrections,
        "notes": notes,
        "expected_review": bool(reasons),
        "expected_review_reasons": reasons,
    }
    return spec
