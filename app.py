from flask import Flask, render_template, request
from WhatDoICut import analyze_deck_from_url
import requests

app = Flask(__name__)

# ------------------------------------------------------------
# Fetch card image from Scryfall (handles double-faced cards)
# ------------------------------------------------------------
def get_card_image(card_name):
    url = f"https://api.scryfall.com/cards/named?exact={card_name}"
    r = requests.get(url).json()

    # Single-faced card
    if "image_uris" in r:
        return r["image_uris"].get("normal")

    # Double-faced card
    if "card_faces" in r:
        try:
            return r["card_faces"][0]["image_uris"]["normal"]
        except:
            pass

    return None


# ------------------------------------------------------------
# Explain WHY a card scored low
# ------------------------------------------------------------
def explain_cut(card):
    score = card["score"]
    name = card["name"].lower()

    reasons = []

    # Example heuristics — adjust based on your scoring engine
    if score < 0.2:
        reasons.append("Very low synergy with commander or deck theme")
    if "land" in name and score < 0.3:
        reasons.append("Land provides minimal utility compared to alternatives")
    if "artifact" in name and score < 0.3:
        reasons.append("Low-impact artifact with limited synergy")
    if "creature" in name and score < 0.3:
        reasons.append("Creature does not contribute meaningfully to strategy")
    if score < 0.1:
        reasons.append("Card is generally underpowered in Commander")

    # Fallback
    if not reasons:
        reasons.append("Lower synergy and efficiency compared to other options")

    return " • ".join(reasons)


# ------------------------------------------------------------
# Web Route
# ------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    results = None

    if request.method == "POST":
        deck_url = request.form.get("deck_url")

        try:
            results = analyze_deck_from_url(deck_url)

            # Commander images
            commander_images = []
            for cmd in results["commander"]:
                commander_images.append({
                    "name": cmd,
                    "image": get_card_image(cmd)
                })
            results["commander_images"] = commander_images

            # Add images + reasons to each cut
            for c in results["cuts"]:
                c["image"] = get_card_image(c["name"])
                c["reason"] = explain_cut(c)

        except Exception as e:
            results = {"error": str(e)}

    return render_template("index.html", results=results)


# ------------------------------------------------------------
# Run Flask App
# ------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=False)
