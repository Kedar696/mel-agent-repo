"""Hindi / English vocabulary for assets and shared UI strings. Owner: P5.
TODO(P5): native-speaker review of every Hindi string; add gender agreement for asset nouns."""

ASSET_HI = {
    "wheat": "गेहूँ", "mustard": "सरसों", "potato": "आलू", "lentil": "मसूर", "gram": "चना",
    "pea": "मटर", "maize": "मक्का", "onion": "प्याज़", "cauliflower": "फूलगोभी", "cabbage": "पत्तागोभी",
    "tomato": "टमाटर", "cow": "गाय", "buffalo": "भैंस", "goat": "बकरी", "chickpea": "चना",
}
GENERIC = {"en-IN": {"crop": "crop", "livestock": "animal", None: "crop"},
           "hi-IN": {"crop": "फसल", "livestock": "पशु", None: "फसल"}}


def asset_word(insight: dict, lang: str) -> str:
    a = insight.get("asset") or {}
    name = a.get("name")
    if name:
        return ASSET_HI.get(name, name) if lang == "hi-IN" else name
    return GENERIC[lang].get(a.get("category"), GENERIC[lang][None])
