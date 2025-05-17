# backend/music/genre_wizard.py

from collections import defaultdict, Counter
import os
import csv
import logging

logging.basicConfig(level=logging.INFO)

## Genre summary appearing on home.html
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

GENRE_MAP = {}
csv_path = os.path.join(os.path.dirname(__file__), "genreSchema.csv")
with open(csv_path, newline='') as csvfile:
    reader = csv.reader(csvfile)
    for row in reader:
        if len(row) >= 2:
            sub, parent = row[0].strip().lower(), row[1].strip().lower()
            GENRE_MAP[sub] = parent
            # 🧠 Also map parent to itself so it doesn’t get dumped into "other"
            if parent not in GENRE_MAP:
                GENRE_MAP[parent] = parent

UNCATEGORIZED_GENRES = defaultdict(int)
def get_parent_genre(genre: str) -> str:
    genre_lc = genre.lower()
    if genre_lc in GENRE_MAP:
        return GENRE_MAP[genre_lc]
    else:
        # Track and log unknown genres
        UNCATEGORIZED_GENRES[genre_lc] += 1
        logging.info(f"Unmapped genre: '{genre_lc}'")
        return "other"

def genre_frequency(genre_inputs, limit=20):
    if not isinstance(genre_inputs, list):
        raise ValueError("Expected a list of genres.")
    frequency_counter = Counter(genre_inputs)
    top_genres = frequency_counter.most_common(limit)
    return dict(top_genres)

# Genre highest, sorts and finds highest genre
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

    # Log the genres that fell under "other"
    if OTHER_GENRES:
        logging.info("🚨 Genres categorized as 'other':")
        for g, c in sorted(OTHER_GENRES.items(), key=lambda x: -x[1]):
            logging.info(f"  '{g}' → other (x{c})")

    # ✅ Don't forget to return the sorted result
    return dict(sorted(result.items(), key=lambda item: item[1], reverse=True))