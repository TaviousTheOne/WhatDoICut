from flask import Flask, render_template, request
from WhatDoICut import analyze_deck_from_url, explain_cut
import requests

app = Flask(__name__)

# ------------------------------------------------------------
# Fetch card image from Scryfall (handles MDFCs safely)
# ------------------------------------------------------------
def get_card_image(card_name):
    url = f"https://api.scryfall.com/cards/named?exact={card_name}"
    r = requests.get(url).json()

    # MDFC normalization
    if "image_uris" not in r and "card_faces" in r:
        for face in r["card_faces"]:
            if "image_uris" in face:
                r["image_uris"] = face["image_uris"]
                break

    if "image_uris" not in r:
        return None

    # Try preferred sizes in order
    for size in ["normal", "large", "png", "border_crop", "small"]:
        if size in r["image_uris"]:
            return r["image_uris"][size]

    return None


# ------------------------------------------------------------
# Web Route
# ------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    results = None

    if request.method == "POST":
        deck_url = request.form.get("deck_url")

        try:
            # Score deck (no images involved)
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
                c["reason"] = explain_cut(c, results["commander"])

        except Exception as e:
            results = {"error": str(e)}

    return render_template("index.html", results=results)


# ------------------------------------------------------------
# Run Flask App
# ------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=False)
