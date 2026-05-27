import requests
import re

# ------------------------------------------------------------
# Scryfall Cache + Helpers
# ------------------------------------------------------------

_scryfall_cache = {}

def get_scryfall_card(name: str):
    """Fetch card from Scryfall with image normalization."""
    key = name.lower()
    if key in _scryfall_cache:
        return _scryfall_cache[key]

    url = f"https://api.scryfall.com/cards/named?exact={name}"
    r = requests.get(url).json()

    # Normalize image_uris so app.py's get_card_image() always works
    if "image_uris" not in r:
        if "card_faces" in r:
            try:
                r["image_uris"] = r["card_faces"][0]["image_uris"]
            except:
                pass

    _scryfall_cache[key] = r
    return r


def get_type_and_text(name: str):
    """Return (type_line, oracle_text) for any card, including MDFCs."""
    data = get_scryfall_card(name)
    type_line = data.get("type_line", "").lower()
    oracle_text = data.get("oracle_text", "").lower()

    # MDFCs store text on faces
    if not oracle_text and "card_faces" in data:
        oracle_text = " ".join(
            f.get("oracle_text", "").lower()
            for f in data["card_faces"]
        )

    return type_line, oracle_text


# ------------------------------------------------------------
# URL Detection
# ------------------------------------------------------------

def detect_platform(url: str):
    if "moxfield.com" in url:
        return "moxfield"
    if "archidekt.com" in url:
        return "archidekt"
    raise ValueError("URL is not from Archidekt or Moxfield")


# ------------------------------------------------------------
# Deck Fetchers
# ------------------------------------------------------------

def fetch_moxfield(url: str):
    deck_id = url.rstrip("/").split("/")[-1]
    api_url = f"https://api.moxfield.com/v2/decks/all/{deck_id}"
    data = requests.get(api_url).json()

    commander = []
    if "commanders" in data:
        for entry in data["commanders"].values():
            commander.append(entry["card"]["name"])

    if not commander and "partners" in data:
        for entry in data["partners"].values():
            commander.append(entry["card"]["name"])

    cards = []
    if "mainboard" in data:
        for entry in data["mainboard"].values():
            cards.append({
                "name": entry["card"]["name"],
                "qty": entry["quantity"]
            })

    return {"commander": commander, "cards": cards}


def fetch_archidekt(url: str):
    match = re.search(r"/decks/(\d+)", url)
    if not match:
        raise ValueError("Invalid Archidekt URL")

    deck_id = match.group(1)
    api_url = f"https://archidekt.com/api/decks/{deck_id}/"
    data = requests.get(api_url).json()

    commander = []
    cards = []

    for card in data["cards"]:
        if card["categories"] and "Commander" in card["categories"]:
            commander.append(card["card"]["oracleCard"]["name"])
        else:
            cards.append({
                "name": card["card"]["oracleCard"]["name"],
                "qty": card["quantity"]
            })

    return {"commander": commander, "cards": cards}


# ------------------------------------------------------------
# Commander Profile (tribal + tokens + triggers)
# ------------------------------------------------------------

def analyze_commander(commander_names):
    tribe = None
    makes_tokens = False
    cares_about_death = False
    cares_about_attack = False

    type_blob = ""
    oracle_blob = ""

    for name in commander_names:
        t, o = get_type_and_text(name)
        type_blob += " " + t
        oracle_blob += " " + o

    # Infer tribe from type line
    if "creature —" in type_blob:
        after = type_blob.split("creature —", 1)[1].strip()
        tribe = after.split()[0]

    # Common tribes fallback
    common_tribes = [
        "goblin", "elf", "zombie", "soldier", "wizard",
        "dragon", "angel", "vampire", "merfolk", "sliver",
        "human", "warrior", "cleric", "rogue"
    ]
    for t in common_tribes:
        if t in type_blob:
            tribe = tribe or t

    # Token engine?
    if "token" in oracle_blob or "create" in oracle_blob:
        makes_tokens = True

    # Death triggers?
    if "dies" in oracle_blob or "whenever another creature" in oracle_blob:
        cares_about_death = True

    # Attack triggers?
    if "attack" in oracle_blob or "attacks" in oracle_blob:
        cares_about_attack = True

    return {
        "tribe": tribe,
        "makes_tokens": makes_tokens,
        "cares_about_death": cares_about_death,
        "cares_about_attack": cares_about_attack,
        "names": commander_names,
    }


# ------------------------------------------------------------
# Card Scoring Engine (tribal + tokens + oracle)
# ------------------------------------------------------------

def score_card(card_name: str, commander_profile: dict):
    type_line, oracle_text = get_type_and_text(card_name)
    tribe = commander_profile["tribe"]

    score = 0.0

    # Tribal synergy
    if tribe:
        if tribe in type_line:
            score += 0.45
        if tribe in oracle_text:
            score += 0.25

    # Token synergy
    if commander_profile["makes_tokens"]:
        if "token" in oracle_text or "create" in oracle_text:
            score += 0.25
        if "1/1" in oracle_text:
            score += 0.10

    # Death synergy
    if commander_profile["cares_about_death"]:
        if "dies" in oracle_text:
            score += 0.20
        if "sacrifice" in oracle_text:
            score += 0.15

    # Attack synergy
    if commander_profile["cares_about_attack"]:
        if "attack" in oracle_text or "attacks" in oracle_text:
            score += 0.20

    # Generic roles (oracle-based)
    roles = {
        "ramp": ["add {", "treasure", "landfall"],
        "draw": ["draw a card", "draw two cards"],
        "removal": ["destroy target", "exile target", "damage to target"],
        "wincon": ["extra turn", "you win the game"],
    }
    for keywords in roles.values():
        if any(k in oracle_text for k in keywords):
            score += 0.20

    # Commander name synergy
    for cmd in commander_profile["names"]:
        if cmd.split()[0].lower() in oracle_text:
            score += 0.20

    # Efficiency (cheap cards slightly better)
    cmc = get_scryfall_card(card_name).get("cmc", 3)
    score += max(0.0, 0.25 - 0.03 * (cmc - 3))

    return min(max(score, 0.0), 1.0)


# ------------------------------------------------------------
# Explanation Engine
# ------------------------------------------------------------

def explain_cut(card, commander_names):
    name = card["name"]
    score = card["score"]
    type_line, oracle_text = get_type_and_text(name)
    commander_profile = analyze_commander(commander_names)

    tribe = commander_profile["tribe"]

    reasons = []

    # Score tiers
    if score < 0.10:
        reasons.append("Very low impact compared to other synergistic options")
    elif score < 0.20:
        reasons.append("Below-average synergy for what your commander is trying to do")

    # Tribal
    if tribe and tribe not in type_line and tribe not in oracle_text:
        reasons.append(f"Does not strongly support your {tribe} tribal game plan")

    # Token synergy
    if commander_profile["makes_tokens"]:
        if "token" not in oracle_text and "create" not in oracle_text:
            reasons.append("Provides little payoff or support for your token generation")

    # Death synergy
    if commander_profile["cares_about_death"]:
        if "dies" not in oracle_text and "sacrifice" not in oracle_text:
            reasons.append("Does not take advantage of your death/sacrifice synergies")

    # Attack synergy
    if commander_profile["cares_about_attack"]:
        if "attack" not in oracle_text and "attacks" not in oracle_text:
            reasons.append("Does not meaningfully reward your attacking game plan")

    # Generic utility
    if not any(k in oracle_text for k in ["draw a card", "destroy target", "exile target", "add {"]):
        reasons.append("Offers limited card advantage, removal, or mana acceleration")

    # Commander name synergy
    if not any(cmd.split()[0].lower() in oracle_text for cmd in commander_names):
        reasons.append("Lacks direct, text-level synergy with your commander")

    # Deduplicate
    seen = set()
    final = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            final.append(r)

    return " • ".join(final)


# ------------------------------------------------------------
# Deck Analysis
# ------------------------------------------------------------

def analyze_deck(deck):
    commander = deck["commander"]
    cards = deck["cards"]

    commander_profile = analyze_commander(commander)

    scored = []
    for c in cards:
        s = score_card(c["name"], commander_profile)
        scored.append({"name": c["name"], "qty": c["qty"], "score": s})

    scored.sort(key=lambda x: x["score"])
    return scored[:5]


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------

def analyze_deck_from_url(url: str):
    platform = detect_platform(url)

    if platform == "moxfield":
        deck = fetch_moxfield(url)
    else:
        deck = fetch_archidekt(url)

    return {
        "commander": deck["commander"],
        "cuts": analyze_deck(deck)
    }


# ------------------------------------------------------------
# CLI (optional)
# ------------------------------------------------------------

def main():
    print("=== What Do I Cut? ===")
    while True:
        url = input("\nPaste deck URL:\n> ").strip()
        try:
            result = analyze_deck_from_url(url)
            print("\nCommander:", ", ".join(result["commander"]))
            print("\nTop 5 Cuts:")
            for c in result["cuts"]:
                print(f"- {c['name']} ({c['score']:.3f})")
        except Exception as e:
            print("Error:", e)

        if input("\nAgain (y/n): ").lower() != "y":
            break


if __name__ == "__main__":
    main()
