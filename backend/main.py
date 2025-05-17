# backend/main.py

# -- Imports
import os
import spotipy
from spotipy.exceptions import SpotifyException
from pymongo.errors import ConnectionFailure
from datetime import datetime, timezone
import csv
from pydantic import BaseModel

# -- fastAPI
from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# -- backend
from backend.utils import get_spotify_oauth, get_artist_genres
from backend.db import users_collection, client
from backend.auth import get_token
from backend.music import genre_wizard
from backend.music.genreColours import META_GENRE_COLORS

app = FastAPI()

IS_DEV = os.getenv("NODE_ENV", "development").lower() == "development"
BASE_URL = os.getenv("DEV_BASE_URL") if IS_DEV else os.getenv("PRO_BASE_URL")

class ThemeSettings(BaseModel):
    user_id: str
    theme: str
    background: str
    font: str
    text_color: str

sp_oauth = get_spotify_oauth()

if not IS_DEV:
    app.mount("/", StaticFiles(directory="backend/static", html=True), name="static")

tags_metadata = [
    {
        "name": "user",
        "description": "For queries about the user"
    }
]


@app.get("/", tags=["routes"])
def serve_react():
    if IS_DEV:
        return JSONResponse({"message": "Frontend not served in development. Run `npm run dev`."})
    return FileResponse("backend/static/index.html")


@app.get("/login",tags=["routes"])
def login():
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)


@app.get("/user-playlists",tags=["user"])
def get_user_playlists(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user or "important_playlists" not in user:
        return []

    public = []
    for pid in user["important_playlists"]:
        match = users_collection.find_one(
            {"public_playlists.playlist_id": pid}, {"public_playlists.$": 1}
        )
        if match and "public_playlists" in match:
            public.append(match["public_playlists"][0])
    return public

@app.get("/all-playlists", tags=["user"])
def get_all_user_playlists(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id}, {"public_playlists": 1})
    if not user or "public_playlists" not in user:
        return []

    return user["public_playlists"]


@app.get("/callback",tags=["routes"])
def callback(code: str):
    token_info = sp_oauth.get_access_token(code)
    access_token = token_info["access_token"]
    refresh_token = token_info["refresh_token"]
    expires_at = token_info["expires_at"]
    sp = spotipy.Spotify(auth=access_token)
    user_profile = sp.current_user()
    user_id = user_profile["id"]
    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "display_name": user_profile.get("display_name"),
                "profile_picture": (
                    user_profile["images"][0]["url"]
                    if user_profile.get("images") and len(user_profile["images"]) > 0
                    else "https://www.rollingstone.com/wp-content/uploads/2020/11/alex-trebek-obit.jpg?w=1600&h=900&crop=1"
                ),
            }
        },
        upsert=True,
    )
    user = users_collection.find_one({"user_id": user_id})
    frontend_base = "http://localhost:5173" if IS_DEV else BASE_URL
    if user and user.get("onboarded"):
        return RedirectResponse(f"{frontend_base}/home?user_id={user_id}")
    else:
        return RedirectResponse(f"{frontend_base}/onboard?user_id={user_id}")

@app.get("/recently-played", tags=["playback"])
def get_recently_played(access_token: str = Depends(get_token), limit: int = 1):
    sp = spotipy.Spotify(auth=access_token)
    artist_genre_cache = {}

    try:
        recent = sp.current_user_recently_played(limit=limit)
        simplified = []
        for item in recent["items"]:
            track = item["track"]
            genres = get_artist_genres(sp, track["artists"], artist_genre_cache)

            simplified.append(
                {
                    "played_at": item["played_at"],
                    "track": {
                        "name": track["name"],
                        "artists": [a["name"] for a in track["artists"]],
                        "album": track["album"]["name"],
                        "isrc": track.get("external_ids", {}).get("isrc"),
                        "external_url": track["external_urls"]["spotify"],
                        "genres": genres,
                    },
                }
            )

        return {"recently_played": simplified}

    except Exception as e:
        print(f"⚠️ Recently played error: {e}")
        return {"recently_played": False}

@app.get("/meta-genre-schema")
def get_meta_genre_schema():
    return JSONResponse(META_GENRE_COLORS)

@app.get("/playback", tags=["playback"])
def get_playback_state(
    user_id: str = Query(...), access_token: str = Depends(get_token)
):
    sp = spotipy.Spotify(auth=access_token)

    try:
        playback = sp.current_playback()

        if playback and playback.get("item"):
            item = playback["item"]
            track_data = {
                "is_playing": playback["is_playing"],
                "device": playback["device"]["name"],
                "volume_percent": playback["device"]["volume_percent"],
                "track": {
                    "name": item["name"],
                    "artist": item["artists"][0]["name"],
                    "album": item["album"]["name"],
                    "external_url": item["external_urls"]["spotify"],
                    "album_art_url": (
                        item["album"]["images"][0]["url"]
                        if item["album"].get("images")
                        else None
                    ),
                },
            }
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_played_track": track_data}},
            )

            return {"playback": track_data}

        user = users_collection.find_one({"user_id": user_id})
        return {"playback": user.get("last_played_track", False)}

    except Exception as e:
        print(f"⚠️ Playback error for {user_id}: {e}")
        user = users_collection.find_one({"user_id": user_id})
        return {"playback": user.get("last_played_track", False)}


@app.get("/refresh_token", tags=["auth"])
def refresh(refresh_token: str = Query(...)):
    refreshed = sp_oauth.refresh_access_token(refresh_token)
    return {
        "access_token": refreshed["access_token"],
        "expires_in": refreshed["expires_in"],
    }


@app.get("/me", tags=["user"])
def get_current_user(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user["user_id"],
        "display_name": user["display_name"],
        "email": user.get("email"),
        "profile_picture": user.get("profile_picture"),
        "important_playlists": user.get("important_playlists", []),
        "genre_analysis": user.get("genre_analysis"),
    }

@app.get("/playlists", tags=["user"])
def get_playlists(user_id: str = Query(...)):
    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)
    raw = sp.current_user_playlists()

    playlists = [
        {
            "id": p["id"],
            "name": p["name"],
            "image": p["images"][0]["url"] if p["images"] else None,
            "tracks": p["tracks"]["total"],
        }
        for p in raw["items"]
    ]

    return {"items": playlists}

@app.get("/users", tags=["user"])
def get_users():
    return list(
        users_collection.find(
            {}, {"_id": 0, "user_id": 1, "display_name": 1, "email": 1}
        )
    )

@app.get("/top-tracks", tags=["user"])
def get_top_tracks(
    access_token: str = Depends(get_token),
    limit: int = 10,
    time_range: str = "medium_term",
):
    sp = spotipy.Spotify(auth=access_token)
    top_tracks = sp.current_user_top_tracks(limit=limit, time_range=time_range)

    artist_genre_cache = {}
    simplified = []

    for track in top_tracks["items"]:
        genres = get_artist_genres(sp, track["artists"], artist_genre_cache)

        simplified.append(
            {
                "name": track["name"],
                "artists": [a["name"] for a in track["artists"]],
                "album": track["album"]["name"],
                "external_url": track["external_urls"]["spotify"],
                "isrc": track.get("external_ids", {}).get("isrc"),
                "genres": genres,
            }
        )

    return {"top_tracks": simplified}

@app.post("/save-theme", tags=["theme"])
def save_theme(settings: ThemeSettings):
    result = users_collection.update_one(
        {"user_id": settings.user_id},
        {"$set": {
            "theme_settings": {
                "theme": settings.theme,
                "background": settings.background,
                "font": settings.font,
                "text_color": settings.text_color,
            }
        }},
        upsert=True
    )
    return {"status": "ok", "modified": result.modified_count}


@app.post("/play", tags=["playback"])
def start_playback(access_token: str = Depends(get_token)):
    sp = spotipy.Spotify(auth=access_token)
    sp.start_playback()
    return {"status": "playing"}


@app.post("/pause", tags=["playback"])
def pause_playback(access_token: str = Depends(get_token)):
    sp = spotipy.Spotify(auth=access_token)
    sp.pause_playback()
    return {"status": "paused"}


@app.post("/complete-onboarding",tags=["register"])
def complete_onboarding(data: dict):
    if not all(
        k in data
        for k in ["user_id", "display_name", "profile_picture", "playlist_ids"]
    ):
        raise HTTPException(status_code=400, detail="Missing required fields")

    access_token = get_token(data["user_id"])
    sp = spotipy.Spotify(auth=access_token)

    full_playlists = []

    for pid in data["playlist_ids"]:
        playlist = sp.playlist(pid)
        tracks = []

        for item in playlist["tracks"]["items"]:
            track = item["track"]
            if track is None:
                continue
            tracks.append(
                {
                    "name": track["name"],
                    "artist": track["artists"][0]["name"],
                    "album": track["album"]["name"],
                    "album_art": (
                        track["album"]["images"][0]["url"]
                        if track.get("album") and track["album"].get("images")
                        else None
                    ),
                    "isrc": track.get("external_ids", {}).get("isrc"),
                    "track_id": track["id"],
                }
            )

        full_playlists.append(
            {
                "playlist_id": pid,
                "name": playlist["name"],
                "image": playlist["images"][0]["url"] if playlist["images"] else None,
                "tracks": tracks,
                "track_count": playlist["tracks"]["total"],
                "external_url": playlist["external_urls"]["spotify"],
            }
        )

    users_collection.update_one(
        {"user_id": data["user_id"]},
        {
            "$set": {
                "display_name": data["display_name"],
                "profile_picture": data["profile_picture"],
                "important_playlists": data["playlist_ids"],
                "onboarded": True,
            }
        },
    )

    for pl in full_playlists:
        users_collection.update_one(
            {"user_id": data["user_id"]},
            {
                "$addToSet": {"public_playlists": pl}
            },
            upsert=True,
        )

    return {"status": "ok"}

@app.get("/analyze-genres", tags=["user"])
def analyze_genres(user_id: str = Query(...)):
    try:
        access_token = get_token(user_id)
        sp = spotipy.Spotify(auth=access_token)

        top_artists = sp.current_user_top_artists(limit=50, time_range="short_term")

        flat_genres = []
        for artist in top_artists["items"]:
            flat_genres.extend([g.lower() for g in artist.get("genres", [])])
        print("🎧 Flattened genres from top artists:", flat_genres[:20])

        freq = genre_wizard.genre_frequency(flat_genres)
        sub_genres = genre_wizard.genre_frequency(flat_genres)
        raw_highest = genre_wizard.genre_highest(flat_genres)
        print("🎧 Raw highest genre counts:", raw_highest)
        total = sum(raw_highest.values()) or 1
        highest = {genre: round((count / total) * 100, 1) for genre, count in raw_highest.items()}
        summary = genre_wizard.generate_user_summary(raw_highest, total=total)

        result = {
            "input": flat_genres,
            "sub_genres": sub_genres,
            "frequency": freq,
            "highest": highest,
            "summary": summary
        }

        if genre_wizard.UNCATEGORIZED_GENRES:
            print("Unmapped genres found:")
            print(dict(genre_wizard.UNCATEGORIZED_GENRES))

        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "genre_analysis": result,
                    "genre_last_updated": datetime.now(timezone.utc)
                }
            },
            upsert=True,
        )

        return result

    except Exception as e:
        print(f"[ERROR] /analyze-genres failed for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Genre analysis failed.")

@app.get("/genres", tags=["user"])
def get_genres(user_id: str = Query(...), refresh: bool = False):
    user = users_collection.find_one({"user_id": user_id})
    if not refresh and user and "genre_analysis" in user:
        return user["genre_analysis"]

    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)
    top_tracks = sp.current_user_top_tracks(limit=50, time_range="short_term")
    flat_genres = []

    artist_genre_cache = {}
    for track in top_tracks["items"]:
        genres = get_artist_genres(sp, track["artists"], artist_genre_cache)
        flat_genres.extend([g.lower() for g in genres])

    sub_genres = genre_wizard.genre_frequency(flat_genres)
    raw_highest = genre_wizard.genre_highest(flat_genres)
    total = sum(raw_highest.values()) or 1
    summary = genre_wizard.generate_user_summary(raw_highest, total=total)
    highest = {genre: round((count / total) * 100, 1) for genre, count in raw_highest.items()}

    result = {
        "input": flat_genres,
        "sub_genres": sub_genres,
        "highest": highest,
        "summary": summary,
    }

    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "genre_analysis": result,
            "genre_last_updated": datetime.now(timezone.utc)
        }},
        upsert=True,
    )

    return result


@app.get("/genre-map", tags=["user"])
def get_genre_map():
    csv_path = os.path.join(os.path.dirname(__file__), "music", "genreSchema.csv")
    genre_map = {}

    with open(csv_path, newline='') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) >= 2:
                sub = row[0].strip().lower()
                parent = row[1].strip().lower()
                genre_map[sub] = parent

    return JSONResponse(content=genre_map)

@app.get("/public-playlist/{playlist_id}", tags=["playlists"])
def get_public_playlist(playlist_id: str):
    match = users_collection.find_one(
        {"public_playlists.playlist_id": playlist_id}, {"public_playlists.$": 1}
    )
    if not match or "public_playlists" not in match:
        raise HTTPException(status_code=404, detail="Playlist not found")

    return match["public_playlists"][0]


@app.get("/playlist-info", tags=["playlists"])
def get_playlist_info(user_id: str = Query(...), playlist_id: str = Query(...)):
    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)
    playlist = sp.playlist(playlist_id)

    return {
        "name": playlist["name"],
        "image": playlist["images"][0]["url"] if playlist["images"] else None,
    }

@app.get("/get-theme", tags=["theme"])
def get_theme(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    return user.get("theme_settings", {})


@app.delete("/delete-user",tags=["mongodb"])
def delete_user(user_id: str = Query(...)):
    result = users_collection.delete_one({"user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted"}


@app.get("/refresh-session",tags=["routes"])
def refresh_session(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token_info = {
        "access_token": user["access_token"],
        "refresh_token": user["refresh_token"],
        "expires_at": user["expires_at"],
    }
    if sp_oauth.is_token_expired(token_info):
        refreshed = sp_oauth.refresh_access_token(user["refresh_token"])
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "access_token": refreshed["access_token"],
                    "refresh_token": refreshed["refresh_token"],
                    "expires_at": refreshed["expires_at"],
                }
            },
        )
        return {"status": "refreshed"}

    return {"status": "ok"}

@app.get("/health", tags=["system"])
def health_check():
    try:
        client.admin.command("ping")
        return {"status": "ok", "db": "connected"}
    except ConnectionFailure:
        return {"status": "error", "db": "disconnected"}

@app.post("/admin/backfill-playlist-metadata", tags=["admin"])
def backfill_playlist_metadata():
    users = users_collection.find({"public_playlists": {"$exists": True}})

    updated = 0

    for user in users:
        access_token = user.get("access_token")
        if not access_token:
            continue

        sp = spotipy.Spotify(auth=access_token)
        updated_playlists = []

        for pl in user.get("public_playlists", []):
            try:
                playlist = sp.playlist(pl["playlist_id"])
                pl["track_count"] = playlist["tracks"]["total"]
                pl["external_url"] = playlist["external_urls"]["spotify"]
                updated_playlists.append(pl)
            except Exception as e:
                print(f"⚠️ Failed to update playlist {pl['playlist_id']}: {e}")
                continue

        users_collection.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"public_playlists": updated_playlists}},
        )
        updated += 1

    return {"status": "ok", "users_updated": updated}

@app.get("/dashboard", tags=["user"])
def get_dashboard(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    genre_analysis = user.get("genre_analysis")

    if genre_analysis and "sub_genres" not in genre_analysis:
        print(f"⚠️ Missing sub_genres for {user_id}, fetching fresh")
        genre_analysis = get_genres(user_id=user_id, refresh=True)

    all_playlists = user.get("public_playlists", [])
    featured_ids = user.get("important_playlists", [])
    featured_playlists = [pl for pl in all_playlists if pl["playlist_id"] in featured_ids]

    return {
        "user": {
            "user_id": user["user_id"],
            "display_name": user.get("display_name"),
            "profile_picture": user.get("profile_picture"),
            "genre_analysis": genre_analysis,
        },
        "playlists": {
            "featured": featured_playlists,
            "all": all_playlists,
        },
        "last_played_track": user.get("last_played_track", False),
    }

@app.get("/user-genres",tags=["user"])
def get_flat_user_genres(
    access_token: str = Depends(get_token),
    time_range: str = "short_term",
    limit: int = 50,
):
    sp = spotipy.Spotify(auth=access_token)
    top_tracks = sp.current_user_top_tracks(limit=limit, time_range=time_range)

    artist_genre_cache = {}
    flat_genres = []

    for track in top_tracks["items"]:
        genres = get_artist_genres(sp, track["artists"], artist_genre_cache)
        flat_genres.extend(genres)

    return {"genres": flat_genres}


@app.get("/{full_path:path}", include_in_schema=False)
def catch_all(full_path: str):
    if IS_DEV:
        return JSONResponse({"message": "No static files in dev. Use Vite on port 5173."})
    return FileResponse("frontend/dist/index.html")