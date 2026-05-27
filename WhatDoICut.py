import requests
import re

# ------------------------------------------------------------
# 1. URL DETECTION
# ------------------------------------------------------------

def detect_platform(url: str):
    if "moxfield.com" in url:
        return "moxfield"
    if "archidekt.com" in url:
        return "archidekt"
    raise ValueError("URL is not from Archidekt or Moxfield")


# ------------------------------------------------------------
# 2. FETCH DECK DATA
# ------------------------------------------------------------

def fetch_moxfield(url: str):
    deck_id = url.rstrip("/").split("/")[-1]
    api_url = f"https://api.moxfield.com/v2/decks/all/{deck_id}"
    data = requests.get(api_url).json()

    commander = []

    if "commanders" in data and isinstance(data["commanders"], dict):
        for entry in data["commanders"].values():
            commander.append(entry["card"]["name"])

    if not commander and "partners" in data and isinstance(data["partners"], dict):
        for entry in data["partners"].values():
            commander.append(entry["card"]["name"])

    cards = []
    if "mainboard" in data and isinstance(data["mainboard"], dict):
        for entry in data["mainboard"].values():
            cards.append({
                "name": entry["card"]["name"],
                "qty": entry["quantity"]
            })

    return {
        "commander": commander,
        "cards": cards
    }


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

    return {
        "commander": commander,
        "cards": cards
    }


# ------------------------------------------------------------
# 3. CARD SCORING ENGINE
# ------------------------------------------------------------

def score_card(card_name: str, commander_names: list):
    name = card_name.lower()

    synergy = 0
    for cmd in commander_names:
        if cmd.split()[0].lower() in name:
            synergy += 0.4

    roles = {
        "ramp": ["signet", "talisman", "sol ring", "cultivate", "kodama"],
        "draw": ["draw", "ponder", "opt", "study", "vision"],
        "removal": ["destroy", "exile", "counter", "path", "swords"],
        "wincon": ["overrun", "combo", "infinite", "extra turn"],
    }

    role_score = 0
    for keywords in roles.values():
        if any(k in name for k in keywords):
            role_score += 0.3

    efficiency = max(0, 0.3 - (len(name) * 0.005))

    redundancy = 0.1
    curve = 0.1

    final = (
        synergy * 0.45 +
        role_score * 0.25 +
        efficiency * 0.15 +
        redundancy * 0.10 +
        curve * 0.05
    )

    return final


# ------------------------------------------------------------
# 4. EXPLANATION ENGINE (IMPROVED)
# ------------------------------------------------------------

def explain_cut(card, commander_names):
    name = card["name"]
    score = card["score"]

    try:
        scry = requests.get(
            f"https://api.scryfall.com/cards/named?exact={name}"
        ).json()
        card_type = scry.get("type_line", "").lower()
    except:
        card_type = ""
    
    reasons = []

    if score < 0.10:
        reasons.append("Very low impact and contributes little to your overall game plan")
    elif score < 0.15:
        reasons.append("Weak synergy and limited strategic value")
    elif score < 0.20:
        reasons.append("Low contribution compared to other options in your colors")

    if "creature" in card_type:
        reasons.append("Creature provides minimal synergy with your commander’s strategy")
    if "artifact" in card_type:
        reasons.append("Artifact offers low utility relative to common Commander staples")
    if "enchantment" in card_type:
        reasons.append("Enchantment does not meaningfully support your deck’s core plan")
    if "instant" in card_type or "sorcery" in card_type:
        reasons.append("Spell is less efficient than similar effects available in your colors")
    if "land" in card_type:
        reasons.append("Land provides little functional value beyond basic mana production")

    name_lower = name.lower()
    roles = {
        "ramp": ["signet", "talisman", "sol ring", "cultivate", "kodama"],
        "draw": ["draw", "ponder", "opt", "study", "vision"],
        "removal": ["destroy", "exile", "counter", "path", "swords"],
        "wincon": ["overrun", "combo", "infinite", "extra turn"],
    }

    matched_role = None
    for role, keywords in roles.items():
        if any(k in name_lower for k in keywords):
            matched_role = role
            break

    if matched_role == "ramp":
        reasons.append("Ramp piece is redundant or less efficient than alternatives")
    elif matched_role == "draw":
        reasons.append("Card draw option is weaker than other available choices")
    elif matched_role == "removal":
        reasons.append("Removal spell is outclassed by more flexible or cheaper options")
    elif matched_role == "wincon":
        reasons.append("Win condition is slow or poorly aligned with your commander")

    if not any(cmd.lower().split()[0] in name_lower for cmd in commander_names):
        reasons.append("Does not meaningfully synergize with your commander")

    if not reasons:
        reasons.append("Lower synergy and efficiency compared to other options")

    return " • ".join(reasons)


# ------------------------------------------------------------
# 5. ANALYZE DECK
# ------------------------------------------------------------

def analyze_deck(deck):
    commander = deck["commander"]
    cards = deck["cards"]

    scored = []
    for c in cards:
        score = score_card(c["name"], commander)
        scored.append({
            "name": c["name"],
            "qty": c["qty"],
            "score": score
        })

    scored.sort(key=lambda x: x["score"])
    return scored[:5]


# ------------------------------------------------------------
# 6. PUBLIC API
# ------------------------------------------------------------

def analyze_deck_from_url(url: str):
    platform = detect_platform(url)

    if platform == "moxfield":
        deck = fetch_moxfield(url)
    else:
        deck = fetch_archidekt(url)

    bottom_five = analyze_deck(deck)

    return {
        "commander": deck["commander"],
        "cuts": bottom_five
    }


# ------------------------------------------------------------
# 7. CLI ENTRY POINT
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
