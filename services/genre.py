# services/genre.py
import json, os
from collections import defaultdict
from services.music import wizard
from music.meta_gradients import get_gradient_for_genre


def load_genre_map():
    genre_map_path = os.path.join("backend", "genres", "2d_genres.csv")
    with open(genre_map_path) as f:
        return {
            line.split(",")[0].strip().lower(): line.split(",")[1].strip().lower()
            for line in f if "," in line
        }


def analyze_genres(flat_genres: list) -> dict:
    raw_highest = wizard.genre_highest(flat_genres)
    sub_genres_raw = wizard.genre_frequency(flat_genres)

    meta_total = sum(raw_highest.values()) or 1
    meta_genres = {
        genre: {
            "portion": round((count / meta_total) * 100, 1),
            "gradient": get_gradient_for_genre(genre),
        }
        for genre, count in raw_highest.items()
    }

    genre_map = load_genre_map()
    sub_total = sum(sub_genres_raw.values()) or 1
    sub_genres = {
        genre: {
            "portion": round((count / sub_total) * 100, 1),
            "parent_genre": genre_map.get(genre, "other"),
            "gradient": get_gradient_for_genre(genre_map.get(genre, "other")),
        }
        for genre, count in sub_genres_raw.items()
    }

    sorted_subs = sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])
    top_sub = next(
        (g for g, _ in sorted_subs if genre_map.get(g.lower(), "") != g.lower()), None
    )
    top_meta = genre_map.get(top_sub.lower(), "other") if top_sub else None

    return {
        "meta_genres": dict(sorted(meta_genres.items(), key=lambda x: -x[1]["portion"])[:10]),
        "sub_genres": dict(sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])[:10]),
        "top_subgenre": {
            "sub_genre": top_sub,
            "parent_genre": top_meta,
            "gradient": get_gradient_for_genre(top_meta),
        },
    }