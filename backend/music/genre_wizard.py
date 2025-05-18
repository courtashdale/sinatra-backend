import os
import json
import logging
from collections import defaultdict, Counter

logging.basicConfig(level=logging.INFO)

# 🔁 Load genre-map.json
genre_map_path = os.path.join(os.path.dirname(__file__), "genre-map.json")
with open(genre_map_path) as f:
    raw_map = json.load(f)

# 🔁 Normalize keys and values
GENRE_MAP = {
    k.strip().lower(): v.strip().lower()
    for k, v in raw_map.items()
}

# 🧠 Ensure all parent genres are mapped to themselves
for parent in set(GENRE_MAP.values()):
    if parent not in GENRE_MAP:
        GENRE_MAP[parent] = parent

# Optional: Load meta-genres.json for is_meta_genre()
meta_genre_path = os.path.join(os.path.dirname(__file__), "meta-genres.json")
if os.path.exists(meta_genre_path):
    with open(meta_genre_path) as f:
        META_GENRES = set(g.lower() for g in json.load(f))
else:
    META_GENRES = set()

UNCATEGORIZED_GENRES = defaultdict(int)

def get_parent_genre(genre: str) -> str:
    genre_lc = genre.strip().lower()
    if genre_lc in GENRE_MAP:
        return GENRE_MAP[genre_lc]
    else:
        UNCATEGORIZED_GENRES[genre_lc] += 1
        logging.info(f"Unmapped genre: '{genre_lc}'")
        return "other"

def is_meta_genre(name: str) -> bool:
    return name.lower() in META_GENRES

def genre_frequency(genre_inputs, limit=20):
    if not isinstance(genre_inputs, list):
        raise ValueError("Expected a list of genres.")
    frequency_counter = Counter(genre_inputs)
    top_genres = frequency_counter.most_common(limit)
    return dict(top_genres)

def genre_highest(genre_inputs):
    if isinstance(genre_inputs, dict):
        inputs = genre_inputs
    elif isinstance(genre_inputs, list):
        inputs = Counter(genre_inputs)
    else:
        raise ValueError("genre_inputs must be a list or a dict.")

    result = defaultdict(int)
    OTHER_GENRES = defaultdict(int)

    for genre, count in inputs.items():
        parent = get_parent_genre(genre)
        result[parent] += count
        if parent == "other":
            OTHER_GENRES[genre] += count

    if OTHER_GENRES:
        logging.info("🚨 Genres categorized as 'other':")
        for g, c in sorted(OTHER_GENRES.items(), key=lambda x: -x[1]):
            logging.info(f"  '{g}' → other (x{c})")

    return dict(sorted(result.items(), key=lambda item: item[1], reverse=True))

def generate_user_summary(highest_genres: dict, total: int = None):
    if not highest_genres:
        return "We couldn’t find enough genre data to summarize your taste 😢"

    if total is None:
        total = sum(highest_genres.values())

    top = sorted(highest_genres.items(), key=lambda x: x[1], reverse=True)
    primary = top[0][0]
    primary_pct = round(top[0][1] / total * 100)

    if len(top) > 1:
        secondary = top[1][0]
        secondary_pct = round(top[1][1] / total * 100)
        detail = f"You also listen to a lot of {secondary} ({secondary_pct}%)."
    else:
        detail = ""

    return f"🎧 You mostly listen to {primary} music ({primary_pct}%). {detail}"