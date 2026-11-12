"""Fertilizer recommendation: official crop doses x Soil Health Card rating,
converted to urea / DAP / MOP per application stage, shown with live field
conditions from the sensor device.

What each input does:
  * Crop     -> the published recommended dose and split schedule (CROPS below,
                with the source of every number).
  * Soil Health Card rating per nutrient (low / medium / high / unknown)
             -> ICAR's soil-test rule: low = +25 %, medium = the general dose,
                high = -25 % (unknown = the general dose, and the screen says so).
  * Area     -> scales the per-hectare dose.
  * Live sensors (temperature, humidity, soil moisture) -> field conditions and
                timing advice only. They cannot measure N, P or K, so they never
                change a dose.

Nothing here is a trained model: every number traces to the sources listed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ACRE_HA = 0.404686                       # 1 acre = 0.404686 ha

# Nutrient content of the fertilizers (Fertilizer Control Order grades).
UREA_N = 0.46                            # urea 46-0-0
DAP_N, DAP_P = 0.18, 0.46                # DAP 18-46-0
MOP_K = 0.60                             # muriate of potash 0-0-60

# ICAR, Indian Farming: "quantity of fertilizer is increased or decreased by 25%
# over GRD if the soil test falls into low or high category, respectively";
# medium = the general recommended dose.
RATING_FACTOR = {"low": 1.25, "medium": 1.0, "high": 0.75, "unknown": 1.0}
SOIL_TEST_SOURCE = "ICAR Indian Farming: soil test low +25%, high -25% of the general dose"
SOIL_TEST_URL = "https://epubs.icar.org.in/index.php/IndFarm/article/download/154285/63334/498037"


@dataclass
class Stage:
    when: str
    n: float        # fraction of the total N applied at this stage
    p: float
    k: float


@dataclass
class Crop:
    name: str
    note: str                                # which recommendation this is
    npk: tuple[float, float, float]          # N, P2O5, K2O kg/ha
    stages: list[Stage]
    extras: list[tuple[str, float, str]] = field(default_factory=list)   # (what, amount per ha, unit)
    source: str = ""
    url: str = ""


# Recommended doses, retrieved 12 Nov 2026 from the TNAU Agritech portal (Tamil
# Nadu Agricultural University). Ragi uses that page's Karnataka column. Read
# with the official package of practices of your state agricultural university;
# local recommendations can differ.
CROPS: dict[str, Crop] = {
    "tomato": Crop(
        "Tomato", "open-pollinated varieties (not hybrids)", (150, 100, 50),
        # "Basal dose: FYM 25 t/ha, NPK 75:100:50 kg/ha, Borax 10 kg and Zinc sulphate
        #  50 kg/ha. Top dressing: 75 kg N/ha on 30th day of planting or during earthing up."
        [Stage("At planting (basal)", 0.5, 1, 1), Stage("30 days after planting / earthing up", 0.5, 0, 0)],
        [("Farmyard manure (FYM), before planting", 25, "t"), ("Borax, basal", 10, "kg"), ("Zinc sulphate, basal", 50, "kg")],
        "TNAU Agritech - Tomato", "https://agritech.tnau.ac.in/horticulture/horti_vegetables_tomato.html"),
    "paddy": Crop(
        "Paddy", "medium and long duration rice, transplanted", (150, 50, 50),
        # "Apply N and K in four equal splits viz., basal, tillering, panicle initiation
        #  and heading stages." "P may be applied as basal and incorporated."
        [Stage("Basal, at transplanting", 0.25, 1, 0.25), Stage("Tillering", 0.25, 0, 0.25),
         Stage("Panicle initiation", 0.25, 0, 0.25), Stage("Heading", 0.25, 0, 0.25)],
        [],
        "TNAU Agritech - Rice nutrient management",
        "https://agritech.tnau.ac.in/agriculture/agri_cropproduction_cereals_rice_tranpudlow_mainfield_nutrient_mgmt_inorganic.html"),
    "ragi": Crop(
        "Ragi", "irrigated, Karnataka recommendation", (100, 50, 50),
        # Karnataka: 50% N at sowing, remaining 50% in two equal splits after 30 and
        # 50 days; P and K in the first dose at sowing. FYM 7-12 t/ha (7 used here).
        [Stage("At sowing", 0.5, 1, 1), Stage("30 days after sowing", 0.25, 0, 0),
         Stage("50 days after sowing", 0.25, 0, 0)],
        [("Farmyard manure (FYM), before sowing (7-12 t/ha)", 7, "t")],
        "TNAU Agritech - Ragi expert system (Karnataka)",
        "https://agritech.tnau.ac.in/expert_system/ragi/nutrientmanagement.html"),
    "maize": Crop(
        "Maize", "hybrid maize", (150, 75, 75),
        # 150:75:75 kg/ha for hybrid maize; a quarter of the N and full P2O5 and K2O
        # basally, half the N at 25 days and the last quarter at 45 days after sowing.
        [Stage("At sowing (basal)", 0.25, 1, 1), Stage("25 days after sowing", 0.5, 0, 0),
         Stage("45 days after sowing", 0.25, 0, 0)],
        [],
        "TNAU Agritech - Maize nutrient management", "https://agritech.tnau.ac.in/agriculture/agri_nutrientmgt_maize.html"),
    "onion": Crop(
        "Onion", "Bellary (big) onion", (100, 150, 75),
        # "Apply FYM 25 t/ha, Azospirillum 2 kg and Phosphobacteria 2 kg/ha, N 50 kg,
        #  P 150 kg and K 75 kg/ha as basal dose and N 50 kg/ha as top-dressing ...
        #  at 30 days after planting." Zinc sulphate 50 kg/ha at the last ploughing.
        [Stage("At planting (basal)", 0.5, 1, 1), Stage("30 days after planting", 0.5, 0, 0)],
        [("Farmyard manure (FYM), before planting", 25, "t"), ("Zinc sulphate, at last ploughing", 50, "kg")],
        "TNAU Agritech - Bellary onion", "https://agritech.tnau.ac.in/horticulture/horti_vegetables_bellaryonion.html"),
}

AREAS = [0.25, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 10]       # acres the touch screen offers


@dataclass
class Region:
    name: str
    n: str | None            # typical status of the district's farm soils; None = not settled by the survey
    p: str | None
    k: str | None
    source: str
    url: str
    verified: bool           # True: read in the paper itself; False: from a search excerpt of it


# Typical soil nutrient status by district, from published soil surveys, used
# ONLY for nutrients the farmer has no Soil Health Card value for. Categories
# follow the usual Indian soil-test limits (available N low < 280, medium
# 280-560 kg/ha; P2O5 medium ~23-56, high > 56; K2O medium 141-336 kg/ha). A
# district survey is an average: a soil test of the field is always better.
REGIONS: dict[str, Region] = {
    "bengaluru": Region(
        "Bengaluru", "medium", "high", "medium",
        "Avinash et al. 2026, Mysore J. Agric. Sci. 60(2): 11-23 (UAS-B, ICAR-NBSS&LUP). Agricultural land "
        "in the northern transect of Bengaluru: available N 384, P2O5 109, K2O 258 kg/ha",
        "https://www.uasbangalore.edu.in/wp-content/uploads/2026/06/2.-Avinash.pdf", True),
    "tumakuru": Region(
        "Tumakuru", "low", "medium", "medium",
        "Bhattacharya & Chikkaramappa 2023, Mysore J. Agric. Sci. 57(2): 327-339. Appanahalli sub-watershed, "
        "Gubbi taluk, 180 samples: mean available N 228, P2O5 33.8, K2O 211 kg/ha",
        "https://mail.uasbangalore.edu.in/images/2023-2nd-Issue/36.pdf", True),
    "kolar": Region(
        "Kolar", "low", "high", "high",
        "Nutrient index study of tomato-growing soils of Kolar: N 1.19 (low), P 2.65 (high), K 2.71 (high)",
        "https://krishi.icar.gov.in/jspui/bitstream/123456789/56296/1/Int.J%20plant%20%26%20Soil%20science-Tomato.pdf", False),
    "hassan": Region(
        "Hassan", "medium", "medium", "low",
        "Geo-referenced soil fertility study of Hassan district: N medium in 86 %, P medium in 92.8 %, "
        "K low in 67.2 % of samples",
        "https://www.researchgate.net/publication/319617809", False),
    "belagavi": Region(
        "Belagavi", "low", "medium", "high",
        "GIS soil fertility mapping, Belgaum district, 160 samples: N low in 79.4 %, P medium in 71.9 %, "
        "K high in 50 %",
        "https://www.researchgate.net/publication/280554499", False),
    "chikkaballapura": Region(
        "Chikkaballapura", None, "low", "low",
        "Nutrient index study of farmers' fields, Chikkaballapura district: P low in 50 %, K low in 86.1 % "
        "of samples (N not clearly settled)",
        "https://www.researchgate.net/publication/376993455", False),
    "other": Region("Other district", None, None, None, "No district survey used: general recommended dose", "", True),
}
DEFAULT_REGION = "other"


def _kg(x: float) -> float:
    return round(x) if x >= 10 else round(x * 2) / 2      # whole kg, or 0.5 kg for small amounts


def _fmt(x: float) -> str:
    return f"{x:g}"


def recommend(crop_id: str, area_acres: float, n: str = "unknown", p: str = "unknown", k: str = "unknown",
              sensor: dict | None = None, sensor_status: str = "no_data", region: str = DEFAULT_REGION) -> dict:
    """Soil Health Card ratings win; a nutrient without one takes the district's
    typical status (REGIONS); without either it gets the general dose."""
    crop = CROPS[crop_id]
    reg = REGIONS.get(region)
    if reg is None:
        raise ValueError(f"unknown region '{region}'")
    card = {"N": n, "P": p, "K": k}
    for r in card.values():
        if r not in RATING_FACTOR:
            raise ValueError(f"rating must be one of {', '.join(RATING_FACTOR)}")
    ratings, rating_from = {}, {}
    for x, regional in (("N", reg.n), ("P", reg.p), ("K", reg.k)):
        if card[x] != "unknown":
            ratings[x], rating_from[x] = card[x], "soil card"
        elif regional:
            ratings[x], rating_from[x] = regional, "district"
        else:
            ratings[x], rating_from[x] = "unknown", "general"
    ha = area_acres * ACRE_HA
    base = dict(zip("NPK", crop.npk))
    dose = {x: base[x] * RATING_FACTOR[ratings[x]] for x in "NPK"}          # kg/ha after the soil test rule

    # Per stage: P comes from DAP, whose N counts towards that stage's N; the
    # rest of the N is urea. If DAP brings more N than the stage needs, the
    # surplus is taken off the next N application.
    stages, carry = [], 0.0
    for st in crop.stages:
        p2o5 = dose["P"] * st.p * ha
        dap = p2o5 / DAP_P
        n_need = dose["N"] * st.n * ha - carry
        n_from_dap = dap * DAP_N
        urea_n = n_need - n_from_dap
        carry = max(0.0, -urea_n)
        urea = max(0.0, urea_n) / UREA_N
        mop = dose["K"] * st.k * ha / MOP_K
        stages.append({"when": st.when, "urea_kg": _kg(urea), "dap_kg": _kg(dap), "mop_kg": _kg(mop)})
    totals = {key: _kg(sum(s[key] for s in stages)) for key in ("urea_kg", "dap_kg", "mop_kg")}
    extras = [{"what": w, "amount": _kg(a * ha) if u == "kg" else round(a * ha, 1), "unit": u} for w, a, u in crop.extras]

    why = []
    for x, name in (("N", "nitrogen"), ("P", "phosphorus"), ("K", "potassium")):
        r, src = ratings[x], rating_from[x]
        who = "Soil card" if src == "soil card" else f"{reg.name} soil surveys (assumed)"
        if r == "low":
            why.append(f"{who}: {name} low, so {name} is 25% above the general dose.")
        elif r == "high":
            why.append(f"{who}: {name} high, so {name} is 25% below the general dose.")
        elif src == "district":
            why.append(f"{who}: {name} medium, so the general {name} dose.")
    if "district" in rating_from.values():
        why.append("District values are averages, not your field: a Soil Health Card test is better.")
    elif all(v == "general" for v in rating_from.values()):
        why.append("No soil card values or district data: this is the general dose. A soil test can lower your cost.")
    why.append("Nitrogen is split because it is easily lost; P and K are needed early by the roots.")

    field = conditions(sensor, sensor_status)
    return {
        "crop": crop_id, "name": crop.name, "note": crop.note, "area_acres": area_acres,
        "ratings": ratings, "rating_from": rating_from,
        "region": {"id": region, "name": reg.name, "source": reg.source, "url": reg.url, "verified": reg.verified},
        "base_kg_ha": base, "dose_kg_ha": {x: round(v, 1) for x, v in dose.items()},
        "dose_for_area_kg": {x: round(v * ha, 1) for x, v in dose.items()},
        "totals": totals, "stages": stages, "extras": extras, "why": why, "field": field,
        "source": {"crop": crop.source, "crop_url": crop.url, "soil_test": SOIL_TEST_SOURCE, "soil_test_url": SOIL_TEST_URL},
    }


def conditions(sensor: dict | None, status: str) -> list[str]:
    """Live readings -> what they mean for applying fertilizer today. Only
    statements the readings support; never a dose change."""
    if not sensor or status in ("no_data", "offline"):
        return ["Live sensor offline: check that the soil is moist (not dry, not waterlogged) before applying."]
    out = []
    if status == "stale":
        out.append("Sensor reading is old; check the field yourself.")
    t, h = sensor.get("temperature_c"), sensor.get("humidity_percent")
    if t is not None or h is not None:
        parts = ([f"{_fmt(t)} C"] if t is not None else []) + ([f"{_fmt(h)}% humidity"] if h is not None else [])
        out.append("Air now: " + ", ".join(parts) + ".")
    if sensor.get("soil_sensor_valid") and sensor.get("soil_moisture_percent") is not None:
        out.append(f"Soil moisture now: {_fmt(sensor['soil_moisture_percent'])}% (calibrated sensor).")
    else:
        out.append("Soil moisture unknown (sensor not calibrated): feel the soil at root depth first.")
    out.append("Apply to moist soil near the roots, not on leaves, and water lightly after.")
    return out


def screen_pages(rec: dict) -> tuple[str, list[list[tuple[str, str]]]]:
    """Title and pages of (style, text) lines for the kiosk's 320x240 TFT.
    Styles: H heading, V big value, T text, W warning, S small."""
    ar = rec["area_acres"]
    title = f"{rec['name']} - {_fmt(ar)} acre{'s' if ar != 1 else ''}"
    rt, rf = rec["ratings"], rec["rating_from"]
    short = {"low": "low", "medium": "med", "high": "high", "unknown": "?"}
    soil = "  ".join(f"{x}:{short[rt[x]]}{'*' if rf[x] == 'district' else ''}" for x in "NPK")
    t = rec["totals"]
    p1 = [("H", f"Total for the season   soil {soil}")]
    for label, key in (("Urea", "urea_kg"), ("DAP", "dap_kg"), ("MOP", "mop_kg")):
        p1.append(("V", f"{label}  {_fmt(t[key])} kg"))
    d = rec["dose_for_area_kg"]
    p1.append(("T", f"= N {_fmt(d['N'])}, P2O5 {_fmt(d['P'])}, K2O {_fmt(d['K'])} kg"))
    if "district" in rf.values():
        p1.append(("S", f"* assumed from {rec['region']['name']} district soil surveys"))
    p1.append(("S", f"{rec['note']}. Source: {rec['source']['crop']}"))
    p2 = [("H", "When to apply")]
    for s in rec["stages"]:
        parts = [f"{lbl} {_fmt(s[k])} kg" for lbl, k in (("Urea", "urea_kg"), ("DAP", "dap_kg"), ("MOP", "mop_kg")) if s[k]]
        p2.append(("W", s["when"]))
        p2.append(("T", "  " + (", ".join(parts) or "nothing")))
    p3 = [("H", "Field now (live sensors)")] + [("T", x) for x in rec["field"]]
    p4 = [("H", "Why")] + [("T", x) for x in rec["why"]]
    for e in rec["extras"]:
        p4.append(("T", f"Also: {e['what']} {_fmt(e['amount'])} {e['unit']}"))
    p4.append(("S", "Follow your Soil Health Card or local agriculture officer if they differ."))
    return title, [p1, p2, p3, p4]
