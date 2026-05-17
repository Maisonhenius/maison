"""One-time seed: insert the 5 existing PRODUCTS into the products table.

Idempotent — uses ON CONFLICT (id) DO NOTHING so re-running is safe.

Usage:
    cd server && python migrations/002_seed_products.py
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env.local")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set in .env.local", file=sys.stderr)
    sys.exit(1)

# Snapshot of the PRODUCTS dict from app.py at the time of migration.
# Once seeded, the DB is the source of truth — this is a one-shot.
PRODUCTS = [
    {
        "slug": "out-of-control",
        "name": "Out of Control",
        "family": "Fruity-Floral",
        "price": 270,
        "mood": "Bold, daring, provocative",
        "character": "A scent for those who turn every moment into a declaration of freedom. Fresh and seductive, inspired by a modern Prince Charming.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Bold", "desc": "Unapologetically present in every room"},
            {"name": "Daring", "desc": "Lives for the unexpected, thrives in the night"},
            {"name": "Provocative", "desc": "Leaves an addictive, unforgettable trail"},
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Lemon - Nutmeg - Cool Spices", "desc": "The opening is bright and energizing with lemon, nutmeg and cool spices - a spark that cuts through the air.", "images": ["lemon", "nutmeg", "cool-spices"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Fig - Coconut - Freesia", "desc": "The heart reveals a creamy and slightly fruity facet built around fig, coconut and freesia - an unexpected softness.", "images": ["fig", "coconut", "freesia"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Patchouli - Fruity Musk - Sandalwood", "desc": "The base blends patchouli, sandalwood and fruity musk to create a sensual, elegant and addictive trail.", "images": ["patchouli", "sandalwood", "musk"]},
        },
        "card_image": "card-out-of-control.webp",
        "mood_image": "mood-out-of-control.webp",
        "explore_image": "card-out-of-control-square.webp",
        "bottle_image": "bottle-out-of-control.webp",
        "video": "1.mp4",
        "display_order": 1,
    },
    {
        "slug": "parisian",
        "name": "Parisian",
        "family": "Floral-Gourmand",
        "price": 270,
        "mood": "Sophisticated, romantic, timeless",
        "character": "A scent for those who embody elegance in every step, and savor life like a Parisian. This fragrance celebrates the French art of living, inspired by an elegant Parisian breakfast.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Sophisticated", "desc": "Effortlessly refined in taste and manner"},
            {"name": "Romantic", "desc": "Finds beauty in every small moment"},
            {"name": "Timeless", "desc": "Classic elegance that never fades"},
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Coffee with Cream - Grapefruit - Red Berries", "desc": "The opening combines the freshness of grapefruit and red berries with a gourmand coffee-with-cream facet.", "images": ["coffee-with-cream", "grapefruit", "red-berries"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Rose - Peony - Jasmine", "desc": "The heart reveals a refined floral bouquet composed of rose, peony and jasmine, bringing softness and romance.", "images": ["rose", "peony", "jasmine"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Croissant - Almond - Musk", "desc": "The base unfolds into a comforting gourmand accord of croissant, almond and musk, creating a soft and creamy signature.", "images": ["croissant", "almond", "musk"]},
        },
        "card_image": "card-parisian.webp",
        "mood_image": "mood-parisian.webp",
        "explore_image": "card-parisian-square.webp",
        "bottle_image": "bottle-parisian.webp",
        "video": "2.mp4",
        "display_order": 2,
    },
    {
        "slug": "velvet-waterfall",
        "name": "Velvet Waterfall",
        "family": "Floral-Woody",
        "price": 270,
        "mood": "Flowing, sensual, luminous",
        "character": "A scent for those who discover beauty in balance, and elegance in every motion. This fragrance is inspired by the camel, a symbol of calm, resilience and elegance within the vastness of the desert.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Flowing", "desc": "Moves with effortless grace through life"},
            {"name": "Sensual", "desc": "Embraces warmth and natural beauty"},
            {"name": "Luminous", "desc": "Radiates quiet, confident light"},
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Pepper - Saffron - Incense", "desc": "The opening reveals warm and spicy notes of pepper and saffron, enriched with animalic touches of civet and incense that evoke the mineral depth of desert landscapes.", "images": ["pepper", "saffron", "incense"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Rose - Violet - Lily of the Valley", "desc": "The floral heart combines rose, violet and lily of the valley, bringing a luminous and refined dimension to the composition.", "images": ["rose", "violet", "lily-of-the-valley"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Musk - Cedarwood - Vetiver", "desc": "The base settles on a woody and musky foundation composed of cedarwood, moss and vetiver, leaving a warm, elegant and enveloping trail.", "images": ["musk", "cedarwood", "vetiver"]},
        },
        "card_image": "card-velvet-waterfall.webp",
        "mood_image": "mood-velvet-waterfall.webp",
        "explore_image": "card-velvet-waterfall-square.webp",
        "bottle_image": "bottle-velvet-waterfall.webp",
        "video": "3.mp4",
        "display_order": 3,
    },
    {
        "slug": "oh-my-dear",
        "name": "Oh My Dear!",
        "family": "Woody-Amber",
        "price": 270,
        "mood": "Intimate, graceful, sentimental",
        "character": "A scent for those who treasure elegance in the everyday and carry their memories like jewels of the soul. This fragrance explores a soft and enveloping suede accord evoking the texture of skin.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Intimate", "desc": "Creates deep connections through presence"},
            {"name": "Graceful", "desc": "Carries elegance in the everyday"},
            {"name": "Sentimental", "desc": "Treasures memories like jewels of the soul"},
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Oud - Saffron - Aldehydes", "desc": "The opening blends the intensity of oud and saffron with luminous aldehydic notes that bring brightness to the composition.", "images": ["oud", "saffron", "aldehydes"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Rose - Leather - Cypriol", "desc": "The heart reveals a refined accord of rose and leather, structured by cypriol which reinforces the woody and elegant character of the fragrance.", "images": ["rose", "leather", "cypriol"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Amber - Vetiver - Vanilla", "desc": "The base combines amber, vetiver, cedarwood and vanilla to create a deep, warm and sophisticated trail.", "images": ["amber", "vetiver", "vanilla"]},
        },
        "card_image": "card-oh-my-dear.webp",
        "mood_image": "mood-oh-my-dear.webp",
        "explore_image": "card-oh-my-dear-square.webp",
        "bottle_image": "bottle-oh-my-dear.webp",
        "video": "1.mp4",
        "display_order": 4,
    },
    {
        "slug": "oud-passion",
        "name": "Oud Passion",
        "family": "Woody-Amber (Oud)",
        "price": 270,
        "mood": "Powerful, sophisticated, magnetic",
        "character": "A scent for those who wear confidence like a second skin. This fragrance is built around a balance between luminous freshness and woody depth.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Powerful", "desc": "Commands attention without saying a word"},
            {"name": "Sophisticated", "desc": "Knows the art of restraint and presence"},
            {"name": "Magnetic", "desc": "Draws people in with quiet intensity"},
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Grapefruit - Bergamot - Passion Fruit", "desc": "The opening draws inspiration from the freshness of citrus and exotic fruits: grapefruit, bergamot and passion fruit bring an immediate and modern dynamism.", "images": ["grapefruit", "bergamot", "passion-fruit"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Moldavian Rose - Patchouli - Vetiver", "desc": "The heart revolves around Moldavian rose absolute, combined with patchouli and vetiver, reinforcing the woody and earthy structure of the composition.", "images": ["moldavian-rose", "patchouli", "vetiver"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Sandalwood - Oud - Leather", "desc": "The base reveals a noble and long-lasting accord of sandalwood, oud, leather and Orcanox, leaving a warm, enveloping and elegant trail.", "images": ["sandalwood", "oud", "leather"]},
        },
        "card_image": "card-oud-passion.webp",
        "mood_image": "mood-oud-passion.webp",
        "explore_image": "card-oud-passion-square.webp",
        "bottle_image": "bottle-oud-passion.webp",
        "video": "2.mp4",
        "display_order": 5,
    },
]

INSERT_SQL = """
INSERT INTO products (
    id, slug, name, family, price, mood, "character", description,
    wearer, notes, card_image, mood_image, explore_image, bottle_image,
    video, display_order
) VALUES (
    %(slug)s, %(slug)s, %(name)s, %(family)s, %(price)s, %(mood)s, %(character)s, %(description)s,
    %(wearer)s, %(notes)s, %(card_image)s, %(mood_image)s, %(explore_image)s, %(bottle_image)s,
    %(video)s, %(display_order)s
)
ON CONFLICT (id) DO NOTHING;
"""

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
inserted = 0
try:
    with conn.cursor() as cur:
        for p in PRODUCTS:
            row = dict(p)
            row["wearer"] = json.dumps(row["wearer"])
            row["notes"] = json.dumps(row["notes"])
            cur.execute(INSERT_SQL, row)
            if cur.rowcount:
                inserted += 1
                print(f"  + {p['slug']}")
            else:
                print(f"  = {p['slug']} (already exists)")
        cur.execute("SELECT COUNT(*) FROM products;")
        total = cur.fetchone()[0]
    print(f"[seed] inserted {inserted} / total in table: {total}")
finally:
    conn.close()
