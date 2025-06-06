# api/genres.py
from fastapi import APIRouter, Query, HTTPException
from db.mongo import users_collection
from services.token import get_token
from services.spotify_auth import get_spotify_oauth
from services.music import wizard
from services.music import meta_gradients
from datetime import datetime, timezone
from services.music.wizard import get_gradient_for_genre


import os, json, traceback

router = APIRouter(tags=["genres"])


@router.get("/genres")
def get_genres(user_id: str = Query(...), refresh: bool = False):
    user = users_collection.find_one({"user_id": user_id})
    if not refresh and user and "genre_analysis" in user:
        return user["genre_analysis"]

    try:
        access_token = get_token(user_id)
        import spotipy
        sp = spotipy.Spotify(auth=access_token)

        # Fetch top 100 artists
        top_artists = []
        for offset in (0, 50):
            try:
                batch = sp.current_user_top_artists(
                    limit=50, offset=offset, time_range="short_term"
                )
                top_artists.extend(batch.get("items", []))
            except Exception as e:
                print(f"⚠️ Failed to fetch top artists at offset {offset}: {e}")

        # Extract genres
        flat_genres = []
        for artist in top_artists:
            flat_genres.extend([g.strip().lower() for g in artist.get("genres", [])])

        print("🎯 Combined raw genres from top 100 artists:", flat_genres[:20])

        raw_highest = wizard.genre_highest(flat_genres)
        sub_genres_raw = wizard.genre_frequency(flat_genres)

        total = sum(raw_highest.values()) or 1
        meta_genres = {
            genre: {
                "portion": round((count / total) * 100, 1),
                "gradient": get_gradient_for_genre(genre),
            }
            for genre, count in raw_highest.items()
        }

        try:
            with open("backend/genres/2d_genres.csv") as f:
                genre_map = {
                    line.split(",")[0].strip().lower(): line.split(",")[1].strip().lower()
                    for line in f.readlines()
                    if "," in line
                }
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to load genre map.")

        sub_genres = {}
        total_subgenre_count = sum(sub_genres_raw.values()) or 1
        for genre, count in sub_genres_raw.items():
            portion = round((count / total_subgenre_count) * 100, 1)
            parent = genre_map.get(genre.lower(), "other")
            sub_genres[genre] = {
                "portion": portion,
                "parent_genre": parent,
                "gradient": get_gradient_for_genre(parent),
            }

        sorted_subs = sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])
        top_sub = next(
            (g for g, _ in sorted_subs if genre_map.get(g.lower(), "") != g.lower()),
            None,
        )
        top_meta = genre_map.get(top_sub.lower(), "other") if top_sub else None

        result = {
            "sub_genres": dict(sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])[:10]),
            "meta_genres": dict(sorted(meta_genres.items(), key=lambda x: -x[1]["portion"])[:10]),
            "top_subgenre": {
                "sub_genre": top_sub,
                "parent_genre": top_meta,
                "gradient": get_gradient_for_genre(top_meta),
            },
        }

        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "genre_analysis": result,
                    "genre_last_updated": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

        return result

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Genre analysis failed: {str(e)}")


@router.post("/refresh_genres")
def refresh_genre_analysis(payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    users_collection.update_one(
        {"user_id": user_id},
        {"$unset": {"genre_analysis": "", "genre_last_updated": ""}},
    )

    return get_genres(user_id=user_id, refresh=True)