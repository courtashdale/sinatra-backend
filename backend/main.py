# backend/main.py

# -- Imports
import os
import spotipy
import json
from spotipy.exceptions import SpotifyException
from pymongo.errors import ConnectionFailure
from datetime import datetime, timezone
from pydantic import BaseModel
from starlette.requests import Request
from pathlib import Path
from typing import List

# -- fastAPI
from fastapi import FastAPI, Depends, Query, HTTPException, Body, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Body

# -- backend
from backend.utils import get_spotify_oauth, get_artist_genres
from backend.db import users_collection, client
from backend.auth import get_token
from backend.music import genre_wizard
from backend.music.genre_wizard import META_GENRES, filter_sub_genres

app = FastAPI()

IS_DEV = os.getenv("NODE_ENV", "development").lower() == "development"
BASE_URL = os.getenv("DEV_BASE_URL") if IS_DEV else os.getenv("PRO_BASE_URL")

# -- website
origins = [
    "http://localhost:5173",  # local dev
    "https://sinatra.live",   # custom domain
    "https://sinatra.vercel.app",  # optional fallback
]

# -- middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sp_oauth = get_spotify_oauth()

# ---- Classes



class OnboardingPayload(BaseModel):
    user_id: str
    display_name: str
    profile_picture: str
    playlist_ids: List[str]

class PlaylistSummary(BaseModel):
    id: str
    name: str
    image: str
    tracks: int

class SaveAllPlaylistsRequest(BaseModel):
    user_id: str
    playlists: List[PlaylistSummary]


# --- FastAPI endpoints

@app.get("/login",tags=["routes"])
def login():
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)

@app.get("/user-playlists",tags=["user"])
def get_user_playlists(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user or "playlists.featured" not in user:
        return []

    public = []
    for pid in user["playlists.featured"]:
        match = users_collection.find_one(
            {"playlists.all.playlist_id": pid}, {"playlists.all.$": 1}
        )
        if match and "playlists.all" in match:
            public.append(match["playlists.all"][0])
    return public

@app.get("/all-playlists", tags=["user"])
def get_all_user_playlists(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id}, {"playlists.all": 1})
    if not user or "playlists.all" not in user:
        return []

    return user["playlists.all"]

from fastapi import Request

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
    print("🧪 NODE_ENV:", os.getenv("NODE_ENV"))
    print("🧪 IS_DEV:", IS_DEV)
    print("🧪 Redirecting to:", BASE_URL)
    user = users_collection.find_one({"user_id": user_id})
    frontend_base = "http://localhost:5173" if IS_DEV else BASE_URL
    if user and user.get("registered"):
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
        "playlists.featured": user.get("playlists.featured", []),
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

@app.post("/complete-onboarding", tags=["register"])
def complete_onboarding(data: OnboardingPayload):
    access_token = get_token(data.user_id)
    sp = spotipy.Spotify(auth=access_token)

    simplified_playlists = []

    for pid in data.playlist_ids:
        playlist = sp.playlist(pid)
        simplified_playlists.append(
            {
                "id": pid,
                "name": playlist["name"],
                "image": playlist["images"][0]["url"] if playlist["images"] else None,
                "track_count": playlist["tracks"]["total"],
                "external_url": playlist["external_urls"]["spotify"],
            }
        )

    users_collection.update_one(
        {"user_id": data.user_id},
        {
            "$set": {
                "display_name": data.display_name,
                "profile_picture": data.profile_picture,
                "onboarded": True,
                "playlists": {
                    "all": simplified_playlists,
                    "featured": [pl["id"] for pl in simplified_playlists if pl["id"] in data.playlist_ids]
                }
            }
        },
        upsert=True
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
        print("🎧 Raw flat_genres sample (before filtering):", flat_genres[:20])
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

    artist_genre_cache = {}
    flat_genres = []
    for track in top_tracks["items"]:
        genres = get_artist_genres(sp, track["artists"], artist_genre_cache)
        for g in genres:
            g_clean = g.strip().lower()
            flat_genres.append(g_clean)

    print("🎯 All raw genres (before filtering):", flat_genres[:20])

    # Let genre_wizard handle the filtering of meta-genres
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
    try:
        path = Path(__file__).resolve().parent / "music" / "genre-map.json"
        with open(path) as f:
            genre_map = json.load(f)
        return genre_map
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Genre map not found")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid genre map JSON")

@app.get("/public-playlist/{playlist_id}", tags=["playlists"])
def get_public_playlist(playlist_id: str):
    match = users_collection.find_one(
        {"playlists.all.playlist_id": playlist_id}, {"playlists.all.$": 1}
    )
    if not match or "playlists.all" not in match:
        raise HTTPException(status_code=404, detail="Playlist not found")

    return match["playlists.all"][0]


@app.get("/playlist-info", tags=["playlists"])
def get_playlist_info(user_id: str = Query(...), playlist_id: str = Query(...)):
    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)
    playlist = sp.playlist(playlist_id)

    return {
        "name": playlist["name"],
        "image": playlist["images"][0]["url"] if playlist["images"] else None,
    }


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
    users = users_collection.find({"playlists.all": {"$exists": True}})

    updated = 0

    for user in users:
        access_token = user.get("access_token")
        if not access_token:
            continue

        sp = spotipy.Spotify(auth=access_token)
        updated_playlists = []

        for pl in user.get("playlists.all", []):
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
            {"$set": {"playlists.all": updated_playlists}},
        )
        updated += 1

    return {"status": "ok", "users_updated": updated}

@app.get("/dashboard", tags=["user"])
def get_dashboard(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get genre analysis, playlists, playback
    genre_analysis = user.get("genre_analysis")
    last_played = user.get("last_played_track")
    all_playlists = user.get("playlists", {}).get("all", [])
    featured_playlists = user.get("playlists", {}).get("featured", [])

    # Load genre map
    try:
        with open(os.path.join("backend", "music", "genre-map.json")) as f:
            genre_map = json.load(f)
    except Exception as e:
        print("Failed to load genre map:", e)
        genre_map = {}

    return {
        "user": {
            "user_id": user["user_id"],
            "display_name": user.get("display_name"),
            "profile_picture": user.get("profile_picture", ""),
            "genre_analysis": genre_analysis or {},
        },
        "playlists": {
            "featured": [
                pl for pl in all_playlists
                if pl.get("id") in featured_playlists
            ],
            "all": all_playlists,
        },
        "played_track": last_played,
        "genre_map": genre_map,
    }

@app.get("/public-profile/{user_id}")
def public_profile(user_id: str):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    genre_analysis = user.get("genre_analysis")
    featured_ids = user.get("playlists.featured", [])
    all_playlists = user.get("playlists.all", [])
    featured = [pl for pl in all_playlists if pl.get("playlist_id") in featured_ids]

    return {
        "user_id": user["user_id"],
        "display_name": user.get("display_name"),
        "profile_picture": user.get("profile_picture"),
        "last_played_track": user.get("last_played_track"),
        "genres_data": genre_analysis,
        "featured_playlists": featured,
    }

@app.post("/add-playlists", tags=["user"])
def add_playlists(data: SaveAllPlaylistsRequest):
    result = users_collection.update_one(
        {"user_id": data.user_id},
        {
            "$addToSet": {
                "playlists.all": {"$each": [pl.dict() for pl in data.playlists]}
            }
        },
        upsert=True,
    )
    return {"status": "added", "modified_count": result.modified_count}

@app.post("/update-featured", tags=["user"])
def update_featured_playlists(data: dict):
    user_id = data.get("user_id")
    playlist_ids = data.get("playlist_ids")

    print(f"🔄 Incoming update-featured request for user: {user_id}")
    print(f"📦 Playlist IDs received: {playlist_ids}")

    if not user_id or not isinstance(playlist_ids, list):
        raise HTTPException(status_code=400, detail="Invalid input")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    all_playlists = user.get("playlists", {}).get("all", [])
    known_ids = {pl.get("id") for pl in all_playlists}  # 🔧 use 'id' not 'playlist_id'

    normalized_ids = [pid for pid in playlist_ids if pid in known_ids]

    print("✅ Normalized featured playlist_ids:", normalized_ids)

    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"playlists.featured": normalized_ids}}
    )

    print("💾 MongoDB update complete.\n")
    return {"status": "ok", "count": len(normalized_ids)}

@app.post("/delete-playlists", tags=["user"])
def delete_playlists(data: SaveAllPlaylistsRequest):
    playlist_ids = [pl.id for pl in data.playlists]
    print("🗑️ Deleting playlists:", playlist_ids, "for user:", data.user_id)

    result = users_collection.update_one(
        {"user_id": data.user_id},
        {
            "$pull": {
                "playlists.all": {
                    "playlist_id": {"$in": playlist_ids}
                }
            }
        }
    )

    return {"status": "deleted", "deleted_count": result.modified_count}

@app.post("/refresh_genres", tags=["user"])
def clear_genre_cache(user_id: str = Body(...)):
    result = users_collection.update_one(
        {"user_id": user_id},
        {"$unset": {"genre_analysis": "", "genre_last_updated": ""}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found or no genre data to clear.")
    return {"status": "ok", "message": "Genre cache cleared"}

@app.get("/spotify-me", tags=["spotify"])
def get_spotify_me(user_id: str = Query(...)):
    try:
        access_token = get_token(user_id)
        sp = spotipy.Spotify(auth=access_token)
        me = sp.current_user()
        return me
    except SpotifyException as e:
        print(f"⚠️ Spotify /me error for {user_id}: {e}")
        raise HTTPException(status_code=401, detail="Failed to fetch Spotify user profile.")
    
@app.post("/register", tags=["user"])
def register_user(data: dict = Body(...)):
    user_id = data.get("user_id") or data.get("id")  # Fallback
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    user_doc = {
        "user_id": user_id,
        "display_name": data.get("display_name"),
        "profile_picture": data.get("profile_picture"),
        "playlists": {
            "all": data.get("selected_playlists", []),
            "featured": data.get("featured_playlists", []),
        },
        "created_at": datetime.utcnow(),
        "registered": True
    }

    users_collection.update_one(
        {"user_id": user_id},
        {"$set": user_doc},
        upsert=True
    )

    return {"status": "success", "message": "User registered"}