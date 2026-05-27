import requests
import re

# Simple in-memory cache to avoid hammering Scryfall
_scryfall_cache = {}


# ------------------------------------------------------------
# 0. SCRYFALL HELPERS
# ------------------------------------------------------------

def get_scryfall_card(name: str):
    key = name.lower()
    if key in _scryfall_cache:
        return _scryfall_cache[key]

    url = f"https://api.scryfall.com/cards/named?exact={name}"
    r = requests.get(url).json()
    _scryfall_cache[key] = r
    return r


def get_type_and_text(name: str):
    data = get_scryfall_card(name)
    type_line = data.get("type_line", "").lower()
    oracle_text = data.get("oracle_text", "").lower()
    # Double-faced cards sometimes store text on faces
    if not oracle_text and "card_faces" in data:
        faces = data["card_faces"]
        oracle_text = " ".join(
            f.get("oracle_text", "").lower() for f in faces
        )
    return type_line, oracle_text


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
# 3. COMMANDER PROFILE (TRIBAL + TOKENS)
# ------------------------------------------------------------

def analyze_commander(commander_names):
    """
    Build a profile of what the commander is doing:
    - primary tribe (if any)
    - whether it makes tokens
    - whether it cares about attacking / dying
    """
    tribe = None
    makes_tokens = False
    cares_about_death = False
    cares_about_attack = False

    oracle_blob = ""
    type_blob = ""

    for name in commander_names:
        type_line, oracle_text = get_type_and_text(name)
        type_blob += " " + type_line
        oracle_blob += " " + oracle_text

    # Try to infer tribe from type line (first creature type after "—")
    # e.g. "legendary creature — goblin warrior"
    tribe_candidates = []
    if "creature —" in type_blob:
        after_dash = type_blob.split("creature —", 1)[1].strip()
        # take first word as primary tribe
        first_word = after_dash.split()[0]
        tribe_candidates.append(first_word)

    # Also look for common tribes in type line
    common_tribes = [
        "goblin", "elf", "zombie", "soldier", "wizard",
        "dragon", "angel", "vampire", "merfolk", "sliver",
        "human", "warrior", "cleric", "rogue"
    ]
    for t in common_tribes:
        if t in type_blob:
            tribe_candidates.append(t)

    tribe = tribe_candidates[0] if tribe_candidates else None

    text = oracle_blob

    if "token" in text or "create" in text:
        makes_tokens = True
    if "dies" in text or "whenever another creature" in text:
        cares_about_death = True
    if "attack" in text or "attacks" in text:
        cares_about_attack = True

    return {
        "tribe": tribe,
        "makes_tokens": makes_tokens,
        "cares_about_death": cares_about_death,
        "cares_about_attack": cares_about_attack,
        "oracle_text": oracle_blob,
        "type_line": type_blob,
        "names": commander_names,
    }


# ------------------------------------------------------------
# 4. CARD SCORING ENGINE (TRIBAL + TOKENS + ORACLE)
# ------------------------------------------------------------

def score_card(card_name: str, commander_profile: dict):
    type_line, oracle_text = get_type_and_text(card_name)
    name_lower = card_name.lower()

    tribe = commander_profile["tribe"]
    makes_tokens_cmd = commander_profile["makes_tokens"]
    cares_about_death_cmd = commander_profile["cares_about_death"]
    cares_about_attack_cmd = commander_profile["cares_about_attack"]

    score = 0.0

    # --- Tribal synergy ---
    if tribe:
        if tribe in type_line:
            score += 0.45  # same creature type as commander (e.g. Goblin)
        if tribe in oracle_text:
            score += 0.25  # references tribe in rules text

    # --- Token synergy ---
    if makes_tokens_cmd:
        if "token" in oracle_text or "create" in oracle_text:
            score += 0.25
        if "1/1" in oracle_text:
            score += 0.10

    # --- Death / sacrifice synergy ---
    if cares_about_death_cmd:
        if "dies" in oracle_text or "whenever another creature" in oracle_text:
            score += 0.20
        if "sacrifice" in oracle_text:
            score += 0.15

    # --- Attack synergy ---
    if cares_about_attack_cmd:
        if "attack" in oracle_text or "attacks" in oracle_text:
            score += 0.20

    # --- Generic roles (from oracle text, not name) ---
    roles = {
        "ramp": ["add {", "treasure", "landfall"],
        "draw": ["draw a card", "draw two cards", "card for each"],
        "removal": ["destroy target", "exile target", "damage to target"],
        "wincon": ["extra turn", "you win the game", "cannot lose the game"],
    }

    role_score = 0.0
    for keywords in roles.values():
        if any(k in oracle_text for k in keywords):
            role_score += 0.20

    score += role_score

    # --- Commander name / direct synergy ---
    for cmd in commander_profile["names"]:
        cmd_first = cmd.split()[0].lower()
        if cmd_first in oracle_text:
            score += 0.20

    # --- Small efficiency heuristic: cheaper cards slightly better ---
    cmc = get_scryfall_card(card_name).get("cmc", 3)
    efficiency = max(0.0, 0.25 - 0.03 * (cmc - 3))
    score += efficiency

    # Clamp
    if score < 0:
        score = 0.0
    if score > 1:
        score = 1.0

    return score


# ------------------------------------------------------------
# 5. EXPLANATION ENGINE (USES SAME PROFILE)
# ------------------------------------------------------------

def explain_cut(card, commander_names):
    name = card["name"]
    score = card["score"]

    commander_profile = analyze_commander(commander_names)
    tribe = commander_profile["tribe"]
    makes_tokens_cmd = commander_profile["makes_tokens"]
    cares_about_death_cmd = commander_profile["cares_about_death"]
    cares_about_attack_cmd = commander_profile["cares_about_attack"]

    type_line, oracle_text = get_type_and_text(name)

    reasons = []

    # Score tiers
    if score < 0.10:
        reasons.append("Very low impact compared to other synergistic options")
    elif score < 0.20:
        reasons.append("Below-average synergy for what your commander is trying to do")

    # Tribal explanation
    if tribe:
        if tribe not in type_line and tribe not in oracle_text:
            reasons.append(f"Does not strongly support your {tribe} tribal game plan")

    # Token explanation
    if makes_tokens_cmd:
        if "token" not in oracle_text and "create" not in oracle_text:
            reasons.append("Provides little payoff or support for your token generation")
    
    # Death / sacrifice explanation
    if cares_about_death_cmd and ("dies" not in oracle_text and "sacrifice" not in oracle_text):
        reasons.append("Does not take advantage of your death/sacrifice synergies")

    # Attack explanation
    if cares_about_attack_cmd and ("attack" not in oracle_text and "attacks" not in oracle_text):
        reasons.append("Does not meaningfully reward your attacking game plan")

    # Generic role explanation
    if "draw a card" not in oracle_text and "destroy target" not in oracle_text \
       and "exile target" not in oracle_text and "add {" not in oracle_text:
        reasons.append("Offers limited card advantage, removal, or mana acceleration")

    # Commander name synergy
    name_lower = name.lower()
    if not any(cmd.split()[0].lower() in oracle_text for cmd in commander_names):
        reasons.append("Lacks direct, text-level synergy with your commander")

    if not reasons:
        reasons.append("Lower overall synergy and utility than other available options")

    # Make it compact
    # Remove duplicates while preserving order
    seen = set()
    unique_reasons = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique_reasons.append(r)

    return " • ".join(unique_reasons)


# ------------------------------------------------------------
# 6. ANALYZE DECK
# ------------------------------------------------------------

def analyze_deck(deck):
    commander = deck["commander"]
    cards = deck["cards"]

    commander_profile = analyze_commander(commander)

    scored = []
    for c in cards:
        score = score_card(c["name"], commander_profile)
        scored.append({
            "name": c["name"],
            "qty": c["qty"],
            "score": score
        })

    scored.sort(key=lambda x: x["score"])
    return scored[:5]


# ------------------------------------------------------------
# 7. PUBLIC API
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
# 8. CLI ENTRY POINT
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
