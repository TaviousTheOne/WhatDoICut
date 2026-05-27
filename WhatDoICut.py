import requests
import re

# ------------------------------------------------------------
# Scryfall helper (NO caching, NO image data)
# ------------------------------------------------------------

def get_oracle_data(name: str):
    """Fetch only oracle_text and type_line from Scryfall. Never cache."""
    url = f"https://api.scryfall.com/cards/named?exact={name}"
    r = requests.get(url).json()

    # MDFC handling
    oracle = r.get("oracle_text", "")
    if not oracle and "card_faces" in r:
        oracle = " ".join(face.get("oracle_text", "") for face in r["card_faces"])

    type_line = r.get("type_line", "").lower()

    return type_line.lower(), oracle.lower()


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
# Commander Profile (oracle‑text based)
# ------------------------------------------------------------

def analyze_commander(commander_names):
    tribe = None
    makes_tokens = False
    cares_about_death = False
    cares_about_attack = False

    type_blob = ""
    oracle_blob = ""

    for name in commander_names:
        t, o = get_oracle_data(name)
        type_blob += " " + t
        oracle_blob += " " + o

    # Infer tribe from type line
    common_tribes = [
        "goblin", "elf", "zombie", "soldier", "wizard",
        "dragon", "angel", "vampire", "merfolk", "sliver",
        "human", "warrior", "cleric", "rogue"
    ]
    for t in common_tribes:
        if t in type_blob:
            tribe = t
            break

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
# Card Scoring Engine (oracle‑text synergy)
# ------------------------------------------------------------

def score_card(card_name: str, commander_profile: dict):
    type_line, oracle_text = get_oracle_data(card_name)
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

    # Generic roles
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

    return min(max(score, 0.0), 1.0)


# ------------------------------------------------------------
# Explanation Engine
# ------------------------------------------------------------

def explain_cut(card, commander_names):
    name = card["name"]
    score = card["score"]
    type_line, oracle_text = get_oracle_data(name)
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
# CLI Entry Point
# ------------------------------------------------------------

def main():
    print("=======================================")
    print("     MTG Commander – What Do I Cut")
    print("=======================================")

    while True:
        url = input("\nPaste an Archidekt or Moxfield deck link:\n> ").strip()

        try:
            result = analyze_deck_from_url(url)

            commander = result["commander"]
            cuts = result["cuts"]

            print(f"\nCommander: {', '.join(commander)}")
            print("\nThese are the top 5 cards that bring in the least value for what your deck is trying to do:\n")
            for entry in cuts:
                print(f"- {entry['name']} (score: {entry['score']:.3f})")

        except Exception as e:
            print(f"\nError: {e}")

        again = input("\nAnalyze another deck? (y/n): ").strip().lower()
        if again != "y":
            print("\nGood luck with your brewing, Tavious")
            break


if __name__ == "__main__":
    main()
