"""
Evaluation dataset — 50 hardcoded product queries across 5 categories.

Ground-truth labels are derived from expected_brand, expected_category,
expected_product_type, and keyword lists. No external data source is used.

Categories (10 queries each): footwear, electronics, watches, apparel, home_goods
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Keywords that, if present in a listing title, indicate SUSPICIOUS/counterfeit
_DEFAULT_SUSPICIOUS_KEYWORDS: list[str] = [
    "replica",
    "fake",
    "counterfeit",
    "knockoff",
    "knock off",
    "knock-off",
    "aaa",
    "aaa+",
    "bootleg",
    "imitation",
    "dupe",
    "inspired by",
    "not authentic",
    "1:1",
]


@dataclass
class EvalQuery:
    query_id: str
    text: str
    category: str                        # one of: footwear, electronics, watches, apparel, home_goods
    expected_brand: str | None
    expected_category: str               # normalised category string
    expected_product_type: str           # e.g. "running shoe", "smartwatch"
    suspicious_title_keywords: list[str] = field(default_factory=lambda: list(_DEFAULT_SUSPICIOUS_KEYWORDS))
    authentic_brand_keywords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.authentic_brand_keywords and self.expected_brand:
            self.authentic_brand_keywords = [self.expected_brand]


# ── FOOTWEAR (10 queries) ─────────────────────────────────────────────────────

_FOOTWEAR: list[EvalQuery] = [
    EvalQuery(
        query_id="fw-01",
        text="Nike Air Max running shoes size 10",
        category="footwear",
        expected_brand="nike",
        expected_category="footwear",
        expected_product_type="running shoe",
        authentic_brand_keywords=["nike", "nike inc"],
    ),
    EvalQuery(
        query_id="fw-02",
        text="Adidas Ultraboost white sneakers",
        category="footwear",
        expected_brand="adidas",
        expected_category="footwear",
        expected_product_type="sneaker",
        authentic_brand_keywords=["adidas", "adidas originals"],
    ),
    EvalQuery(
        query_id="fw-03",
        text="New Balance 990 grey men's",
        category="footwear",
        expected_brand="new balance",
        expected_category="footwear",
        expected_product_type="sneaker",
        authentic_brand_keywords=["new balance"],
    ),
    EvalQuery(
        query_id="fw-04",
        text="Jordan 1 Retro High OG black toe",
        category="footwear",
        expected_brand="jordan",
        expected_category="footwear",
        expected_product_type="basketball shoe",
        authentic_brand_keywords=["jordan", "air jordan", "nike"],
    ),
    EvalQuery(
        query_id="fw-05",
        text="Timberland 6 inch waterproof boots",
        category="footwear",
        expected_brand="timberland",
        expected_category="footwear",
        expected_product_type="boot",
        authentic_brand_keywords=["timberland"],
    ),
    EvalQuery(
        query_id="fw-06",
        text="Vans Old Skool black white",
        category="footwear",
        expected_brand="vans",
        expected_category="footwear",
        expected_product_type="skate shoe",
        authentic_brand_keywords=["vans"],
    ),
    EvalQuery(
        query_id="fw-07",
        text="Converse Chuck Taylor All Star",
        category="footwear",
        expected_brand="converse",
        expected_category="footwear",
        expected_product_type="sneaker",
        authentic_brand_keywords=["converse", "chuck taylor"],
    ),
    EvalQuery(
        query_id="fw-08",
        text="Puma RS-X bold sneakers",
        category="footwear",
        expected_brand="puma",
        expected_category="footwear",
        expected_product_type="sneaker",
        authentic_brand_keywords=["puma"],
    ),
    EvalQuery(
        query_id="fw-09",
        text="Reebok Classic Leather white",
        category="footwear",
        expected_brand="reebok",
        expected_category="footwear",
        expected_product_type="sneaker",
        authentic_brand_keywords=["reebok"],
    ),
    EvalQuery(
        query_id="fw-10",
        text="Asics Gel-Nimbus running shoe",
        category="footwear",
        expected_brand="asics",
        expected_category="footwear",
        expected_product_type="running shoe",
        authentic_brand_keywords=["asics", "asics gel"],
    ),
]

# ── ELECTRONICS (10 queries) ──────────────────────────────────────────────────

_ELECTRONICS: list[EvalQuery] = [
    EvalQuery(
        query_id="el-01",
        text="Apple AirPods Pro 2nd generation",
        category="electronics",
        expected_brand="apple",
        expected_category="electronics",
        expected_product_type="wireless earbuds",
        authentic_brand_keywords=["apple", "airpods"],
    ),
    EvalQuery(
        query_id="el-02",
        text="Sony WH-1000XM5 headphones",
        category="electronics",
        expected_brand="sony",
        expected_category="electronics",
        expected_product_type="headphones",
        authentic_brand_keywords=["sony"],
    ),
    EvalQuery(
        query_id="el-03",
        text="Samsung Galaxy S24 unlocked",
        category="electronics",
        expected_brand="samsung",
        expected_category="electronics",
        expected_product_type="smartphone",
        authentic_brand_keywords=["samsung", "galaxy"],
    ),
    EvalQuery(
        query_id="el-04",
        text="iPad Air 5th generation 64GB",
        category="electronics",
        expected_brand="apple",
        expected_category="electronics",
        expected_product_type="tablet",
        authentic_brand_keywords=["apple", "ipad"],
    ),
    EvalQuery(
        query_id="el-05",
        text="Logitech MX Master 3 mouse",
        category="electronics",
        expected_brand="logitech",
        expected_category="electronics",
        expected_product_type="mouse",
        authentic_brand_keywords=["logitech"],
    ),
    EvalQuery(
        query_id="el-06",
        text="Anker 65W USB-C charger",
        category="electronics",
        expected_brand="anker",
        expected_category="electronics",
        expected_product_type="charger",
        authentic_brand_keywords=["anker"],
    ),
    EvalQuery(
        query_id="el-07",
        text="JBL Flip 6 portable speaker",
        category="electronics",
        expected_brand="jbl",
        expected_category="electronics",
        expected_product_type="speaker",
        authentic_brand_keywords=["jbl"],
    ),
    EvalQuery(
        query_id="el-08",
        text="GoPro Hero 12 Black",
        category="electronics",
        expected_brand="gopro",
        expected_category="electronics",
        expected_product_type="action camera",
        authentic_brand_keywords=["gopro"],
    ),
    EvalQuery(
        query_id="el-09",
        text="Garmin Forerunner 265 GPS watch",
        category="electronics",
        expected_brand="garmin",
        expected_category="electronics",
        expected_product_type="gps watch",
        authentic_brand_keywords=["garmin", "forerunner"],
    ),
    EvalQuery(
        query_id="el-10",
        text="Kindle Paperwhite 11th gen",
        category="electronics",
        expected_brand="amazon",
        expected_category="electronics",
        expected_product_type="e-reader",
        authentic_brand_keywords=["kindle", "amazon", "paperwhite"],
    ),
]

# ── WATCHES (10 queries) ──────────────────────────────────────────────────────

_WATCHES: list[EvalQuery] = [
    EvalQuery(
        query_id="wa-01",
        text="Casio G-Shock GA-2100 black",
        category="watches",
        expected_brand="casio",
        expected_category="watches",
        expected_product_type="digital watch",
        authentic_brand_keywords=["casio", "g-shock", "g shock"],
    ),
    EvalQuery(
        query_id="wa-02",
        text="Seiko 5 Sports automatic watch",
        category="watches",
        expected_brand="seiko",
        expected_category="watches",
        expected_product_type="automatic watch",
        authentic_brand_keywords=["seiko"],
    ),
    EvalQuery(
        query_id="wa-03",
        text="Citizen Eco-Drive titanium",
        category="watches",
        expected_brand="citizen",
        expected_category="watches",
        expected_product_type="solar watch",
        authentic_brand_keywords=["citizen", "eco-drive"],
    ),
    EvalQuery(
        query_id="wa-04",
        text="Fossil Gen 6 smartwatch",
        category="watches",
        expected_brand="fossil",
        expected_category="watches",
        expected_product_type="smartwatch",
        authentic_brand_keywords=["fossil"],
    ),
    EvalQuery(
        query_id="wa-05",
        text="Timex Weekender 40mm",
        category="watches",
        expected_brand="timex",
        expected_category="watches",
        expected_product_type="casual watch",
        authentic_brand_keywords=["timex"],
    ),
    EvalQuery(
        query_id="wa-06",
        text="Orient Bambino classic dress watch",
        category="watches",
        expected_brand="orient",
        expected_category="watches",
        expected_product_type="dress watch",
        authentic_brand_keywords=["orient"],
    ),
    EvalQuery(
        query_id="wa-07",
        text="Invicta Pro Diver 8926OB",
        category="watches",
        expected_brand="invicta",
        expected_category="watches",
        expected_product_type="dive watch",
        authentic_brand_keywords=["invicta"],
    ),
    EvalQuery(
        query_id="wa-08",
        text="MVMT Boulevard minimalist watch",
        category="watches",
        expected_brand="mvmt",
        expected_category="watches",
        expected_product_type="minimalist watch",
        authentic_brand_keywords=["mvmt"],
    ),
    EvalQuery(
        query_id="wa-09",
        text="Daniel Wellington Classic 40mm",
        category="watches",
        expected_brand="daniel wellington",
        expected_category="watches",
        expected_product_type="dress watch",
        authentic_brand_keywords=["daniel wellington", "dw"],
    ),
    EvalQuery(
        query_id="wa-10",
        text="Hamilton Khaki Field automatic",
        category="watches",
        expected_brand="hamilton",
        expected_category="watches",
        expected_product_type="field watch",
        authentic_brand_keywords=["hamilton"],
    ),
]

# ── APPAREL (10 queries) ──────────────────────────────────────────────────────

_APPAREL: list[EvalQuery] = [
    EvalQuery(
        query_id="ap-01",
        text="Levi's 501 original fit jeans",
        category="apparel",
        expected_brand="levis",
        expected_category="apparel",
        expected_product_type="jeans",
        authentic_brand_keywords=["levi", "levis", "levi's", "501"],
    ),
    EvalQuery(
        query_id="ap-02",
        text="Patagonia Better Sweater fleece",
        category="apparel",
        expected_brand="patagonia",
        expected_category="apparel",
        expected_product_type="fleece jacket",
        authentic_brand_keywords=["patagonia"],
    ),
    EvalQuery(
        query_id="ap-03",
        text="The North Face Nuptse jacket",
        category="apparel",
        expected_brand="the north face",
        expected_category="apparel",
        expected_product_type="puffer jacket",
        authentic_brand_keywords=["north face", "the north face", "tnf"],
    ),
    EvalQuery(
        query_id="ap-04",
        text="Champion reverse weave hoodie",
        category="apparel",
        expected_brand="champion",
        expected_category="apparel",
        expected_product_type="hoodie",
        authentic_brand_keywords=["champion"],
    ),
    EvalQuery(
        query_id="ap-05",
        text="Ralph Lauren Polo classic fit shirt",
        category="apparel",
        expected_brand="ralph lauren",
        expected_category="apparel",
        expected_product_type="polo shirt",
        authentic_brand_keywords=["ralph lauren", "polo ralph lauren", "polo"],
    ),
    EvalQuery(
        query_id="ap-06",
        text="Arc'teryx Atom LT hoody",
        category="apparel",
        expected_brand="arcteryx",
        expected_category="apparel",
        expected_product_type="insulated jacket",
        authentic_brand_keywords=["arcteryx", "arc'teryx", "arc teryx"],
    ),
    EvalQuery(
        query_id="ap-07",
        text="Carhartt WIP active jacket",
        category="apparel",
        expected_brand="carhartt",
        expected_category="apparel",
        expected_product_type="work jacket",
        authentic_brand_keywords=["carhartt"],
    ),
    EvalQuery(
        query_id="ap-08",
        text="Uniqlo Ultra Light Down jacket",
        category="apparel",
        expected_brand="uniqlo",
        expected_category="apparel",
        expected_product_type="down jacket",
        authentic_brand_keywords=["uniqlo"],
    ),
    EvalQuery(
        query_id="ap-09",
        text="Columbia Omni-Heat thermal shirt",
        category="apparel",
        expected_brand="columbia",
        expected_category="apparel",
        expected_product_type="base layer",
        authentic_brand_keywords=["columbia", "omni-heat"],
    ),
    EvalQuery(
        query_id="ap-10",
        text="Fjallraven Kanken mini backpack",
        category="apparel",
        expected_brand="fjallraven",
        expected_category="apparel",
        expected_product_type="backpack",
        authentic_brand_keywords=["fjallraven", "kanken"],
    ),
]

# ── HOME GOODS (10 queries) ───────────────────────────────────────────────────

_HOME_GOODS: list[EvalQuery] = [
    EvalQuery(
        query_id="hg-01",
        text="Instant Pot Duo 7-in-1 pressure cooker",
        category="home_goods",
        expected_brand="instant pot",
        expected_category="home_goods",
        expected_product_type="pressure cooker",
        authentic_brand_keywords=["instant pot", "instapot"],
    ),
    EvalQuery(
        query_id="hg-02",
        text="Dyson V15 Detect cordless vacuum",
        category="home_goods",
        expected_brand="dyson",
        expected_category="home_goods",
        expected_product_type="vacuum cleaner",
        authentic_brand_keywords=["dyson"],
    ),
    EvalQuery(
        query_id="hg-03",
        text="Vitamix E310 blender",
        category="home_goods",
        expected_brand="vitamix",
        expected_category="home_goods",
        expected_product_type="blender",
        authentic_brand_keywords=["vitamix"],
    ),
    EvalQuery(
        query_id="hg-04",
        text="Le Creuset dutch oven 5.5 qt",
        category="home_goods",
        expected_brand="le creuset",
        expected_category="home_goods",
        expected_product_type="dutch oven",
        authentic_brand_keywords=["le creuset"],
    ),
    EvalQuery(
        query_id="hg-05",
        text="Nespresso Vertuo Next coffee maker",
        category="home_goods",
        expected_brand="nespresso",
        expected_category="home_goods",
        expected_product_type="coffee maker",
        authentic_brand_keywords=["nespresso", "vertuo"],
    ),
    EvalQuery(
        query_id="hg-06",
        text="Philips Hue starter kit white",
        category="home_goods",
        expected_brand="philips",
        expected_category="home_goods",
        expected_product_type="smart light",
        authentic_brand_keywords=["philips", "philips hue", "hue"],
    ),
    EvalQuery(
        query_id="hg-07",
        text="iRobot Roomba j7 robot vacuum",
        category="home_goods",
        expected_brand="irobot",
        expected_category="home_goods",
        expected_product_type="robot vacuum",
        authentic_brand_keywords=["irobot", "roomba"],
    ),
    EvalQuery(
        query_id="hg-08",
        text="Cuisinart 14-cup food processor",
        category="home_goods",
        expected_brand="cuisinart",
        expected_category="home_goods",
        expected_product_type="food processor",
        authentic_brand_keywords=["cuisinart"],
    ),
    EvalQuery(
        query_id="hg-09",
        text="KitchenAid stand mixer tilt head",
        category="home_goods",
        expected_brand="kitchenaid",
        expected_category="home_goods",
        expected_product_type="stand mixer",
        authentic_brand_keywords=["kitchenaid", "kitchen aid"],
    ),
    EvalQuery(
        query_id="hg-10",
        text="Ember temperature control mug",
        category="home_goods",
        expected_brand="ember",
        expected_category="home_goods",
        expected_product_type="smart mug",
        authentic_brand_keywords=["ember"],
    ),
]

# ── Full dataset ──────────────────────────────────────────────────────────────

QUERIES: list[EvalQuery] = (
    _FOOTWEAR + _ELECTRONICS + _WATCHES + _APPAREL + _HOME_GOODS
)

assert len(QUERIES) == 50, f"Expected 50 queries, got {len(QUERIES)}"

# Index by query_id for fast lookup
QUERY_BY_ID: dict[str, EvalQuery] = {q.query_id: q for q in QUERIES}
