# backend/music/genreColours.py
import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "meta_genre_schema.json"

with open(SCHEMA_PATH, "r") as f:
    META_GENRE_COLORS = json.load(f)

META_GENRES = set(META_GENRE_COLORS.keys())