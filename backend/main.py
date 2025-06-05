# backend/main.py

# -- Imports
import os
import spotipy
import json
import requests
from starlette.middleware.cors import CORSMiddleware
import logging

from spotipy.exceptions import SpotifyException
from pymongo.errors import ConnectionFailure
from datetime import datetime, timezone
from pydantic import BaseModel
from starlette.requests import Request
from fastapi import Request
from pathlib import Path
from typing import List

# -- fastAPI
from fastapi import (
    FastAPI,
    Depends,
    Query,
    HTTPException,
    Body,
    HTTPException,
    APIRouter,
)
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi import Response
import secrets
from fastapi.staticfiles import StaticFiles
from fastapi import Body
from spotipy.oauth2 import SpotifyOAuth
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse


# -- backend
from backend.utils import get_spotify_oauth, get_artist_genres
from backend.db import users_collection, client, playlists_collection
from backend.auth import get_token
from backend.music import genre_wizard
from backend.music.genre_wizard import META_GENRES, filter_sub_genres
from backend.music.meta_gradients import get_gradient_for_genre


app = FastAPI()

IS_DEV = os.getenv("NODE_ENV", "development").lower() == "development"
BASE_URL = os.getenv("DEV_BASE_URL") if IS_DEV else os.getenv("PRO_BASE_URL")

# -- website
origins = [
    "http://localhost:5173",  # local dev
    "https://sinatra.live",  # custom domain
    "https://sinatra.vercel.app",  # optional fallback
]

# -- middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["set-cookie"],
)

# ---- Classes

class CookiePayload(BaseModel):
    user_id: str


class UserIdPayload(BaseModel):
    user_id: str


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


class PlaylistID(BaseModel):
    id: str


class SaveAllPlaylistsRequest(BaseModel):
    user_id: str
    playlists: List[PlaylistID]


# --- FastAPI endpoints


@app.get("/login")
async def login(request: Request, redirect_uri: str = Query(...)):
    state = secrets.token_urlsafe(16)
    sp_oauth = get_spotify_oauth(redirect_uri)
    auth_url = sp_oauth.get_authorize_url(state=state)
    return RedirectResponse(auth_url)


@app.get("/user-playlists", tags=["user"])
def get_user_playlists(user_id: str = Query(...)):
    from backend.db import playlists_collection

    doc = playlists_collection.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(
            status_code=404, detail="No synced playlists found for user."
        )

    return {
        "user_id": doc["user_id"],
        "last_updated": doc.get("last_updated"),
        "playlists": doc.get("playlists", []),
    }


@app.get("/all-playlists", tags=["user"])
def get_all_user_playlists(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id}, {"playlists.all": 1})
    if not user or "playlists.all" not in user:
        return []

    return user["playlists.all"]


@app.get("/callback")
async def callback(request: Request, redirect_uri: str = Query(...)):
    frontend_base = os.getenv("DEV_BASE_URL") if IS_DEV else os.getenv("PRO_BASE_URL")
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    print(f"🌀 Received code: {code}")
    print(f"🌀 Received state: {state}")
    print(f"🔒 Using redirect_uri: {redirect_uri}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    sp_oauth = get_spotify_oauth(redirect_uri)

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
    except Exception as e:
        print(f"❌ Token exchange failed: {e}")
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    sp = spotipy.Spotify(auth=token_info["access_token"])
    profile = sp.current_user()
    user_id = profile.get("id")

    if not user_id:
        raise HTTPException(status_code=400, detail="Spotify user ID missing.")

    # Save tokens
    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "access_token": token_info["access_token"],
                "refresh_token": token_info["refresh_token"],
                "expires_at": token_info["expires_at"],
            }
        },
        upsert=True,
    )

    # Return HTML that sets the cookie
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script>
            document.cookie = "sinatra_user_id={user_id}; path=/; domain=.sinatra.live; max-age=604800; SameSite=None; Secure";
            window.location.href = "{frontend_base}/home";
        </script>
    </head>
    <body></body>
    </html>
    """
    return HTMLResponse(content=html)

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
            artist = item["artists"][0]
            artist_data = sp.artist(artist["id"])  # 🔍 fetch artist info

            track_data = {
                "track": {
                    "id": item["id"],
                    "name": item["name"],
                    "artist": artist["name"],
                    "album": item["album"]["name"],
                    "external_url": item["external_urls"]["spotify"],
                    "album_art_url": (
                        item["album"]["images"][0]["url"]
                        if item["album"].get("images")
                        else None
                    ),
                    "genres": artist_data.get("genres", []),  # ✅ add genres here
                },
            }

            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_played_track": track_data}},
            )

            return {"playback": track_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/refresh_token", tags=["auth"])
def refresh(refresh_token: str = Query(...)):
    sp_oauth = get_spotify_oauth()  # ← fix here
    refreshed = sp_oauth.refresh_access_token(refresh_token)
    return {
        "access_token": refreshed["access_token"],
        "expires_in": refreshed["expires_in"],
    }


@app.get("/me", tags=["user"])
def get_current_user(request: Request):
    user_id = request.cookies.get("sinatra_user_id")
    print(f"🍪 /me cookie received: sinatra_user_id = {user_id}")

    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        print(f"❌ /me user not found for user_id: {user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    print(f"✅ /me success for user_id: {user_id}")
    return {
        "user_id": user["user_id"],
        "display_name": user["display_name"],
        "email": user.get("email"),
        "profile_picture": user.get("profile_picture"),
        "playlists.featured": user.get("playlists.featured", []),
        "genre_analysis": user.get("genre_analysis"),
        "registered": user.get("registered", False),
    }


@app.get("/playlists", tags=["user"])
def get_playlists(
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)
    raw = sp.current_user_playlists(limit=limit, offset=offset)

    playlists = [
        {
            "id": p["id"],
            "name": p["name"],
            "owner": p["owner"]["id"],
            "tracks": p["tracks"]["total"],
            "image": p["images"][0]["url"] if p["images"] else None,
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


@app.get("/genres", tags=["user"])
def get_genres(user_id: str = Query(...), refresh: bool = False):
    user = users_collection.find_one({"user_id": user_id})
    if not refresh and user and "genre_analysis" in user:
        return user["genre_analysis"]

    try:
        access_token = get_token(user_id)
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

        # Extract genres from top artists only
        flat_genres = []
        for artist in top_artists:
            flat_genres.extend([g.strip().lower() for g in artist.get("genres", [])])

        print("🎯 Combined raw genres from top 100 artists:", flat_genres[:20])

        # Analyze genres
        raw_highest = genre_wizard.genre_highest(flat_genres)
        sub_genres_raw = genre_wizard.genre_frequency(flat_genres)

        total = sum(raw_highest.values()) or 1
        meta_genres = {
            genre: {
                "portion": round((count / total) * 100, 1),
                "gradient": get_gradient_for_genre(genre),
            }
            for genre, count in raw_highest.items()
        }

        # Load genre map
        try:
            genre_map_path = os.path.join("backend", "music", "genre-map.json")
            with open(genre_map_path) as f:
                genre_map = json.load(f)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to load genre map.")

        # Sub-genres with gradients from their parent meta-genre
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

        # Top sub-genre (ignore if it's the same as its meta-genre)
        sorted_subs = sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])
        top_sub = next(
            (g for g, _ in sorted_subs if genre_map.get(g.lower(), "") != g.lower()),
            None,
        )
        top_meta = genre_map.get(top_sub.lower(), "other") if top_sub else None

        result = {
            "sub_genres": dict(
                sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])[:10]
            ),
            "meta_genres": dict(
                sorted(meta_genres.items(), key=lambda x: -x[1]["portion"])[:10]
            ),
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
        import traceback

        traceback.print_exc()  # 👈 This shows the exact error in your terminal
        raise HTTPException(status_code=500, detail=f"Genre analysis failed: {str(e)}")


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


@app.delete("/delete-user", tags=["mongodb"])
def delete_user(user_id: str = Query(...)):
    result = users_collection.delete_one({"user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted"}


@app.get("/refresh-session", tags=["routes"])
def refresh_session(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token_info = {
        "access_token": user["access_token"],
        "refresh_token": user["refresh_token"],
        "expires_at": user["expires_at"],
    }
    sp_oauth = get_spotify_oauth()
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


@app.get("/dashboard")
async def get_dashboard(request: Request):
    user_id = request.cookies.get("sinatra_user_id")
    print(f"🍪 /dashboard cookie received: sinatra_user_id = {user_id}")

    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    doc = users_collection.find_one({"user_id": user_id})  # 🛠️ Fix: was {"id": user_id}
    if not doc:
        print(f"❌ /dashboard: user not found in DB for user_id = {user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    print(f"✅ /dashboard success for user_id = {user_id}")
    return {
        "id": user_id,
        "display_name": doc.get("display_name"),
        "profile_picture": doc.get("profile_picture"),
        "playlists": doc.get("playlists", {}),
        "genres": doc.get("genres", {}),
        "last_played": doc.get("last_played", {}),
    }


@app.get("/public-profile/{user_id}")
def public_profile(user_id: str):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    genre_analysis = user.get("genre_analysis")
    playlists = user.get("playlists", {})
    featured_ids = playlists.get("featured", [])
    all_playlists = playlists.get("all", [])
    featured = [
        pl
        for pl in all_playlists
        if pl.get("id") in featured_ids or pl.get("playlist_id") in featured_ids
    ]

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
    access_token = get_token(data.user_id)
    sp = spotipy.Spotify(auth=access_token)

    enriched = []

    for pl in data.playlists:
        try:
            playlist = sp.playlist(pl.id)
            enriched.append(
                {
                    "id": pl.id,
                    "name": playlist["name"],
                    "image": (
                        playlist["images"][0]["url"] if playlist["images"] else None
                    ),
                    "tracks": playlist["tracks"]["total"],
                    "external_url": playlist["external_urls"]["spotify"],
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to fetch metadata for playlist {pl.id}: {e}")
            continue

    if not enriched:
        raise HTTPException(status_code=400, detail="No valid playlists to add")

    result = users_collection.update_one(
        {"user_id": data.user_id},
        {"$addToSet": {"playlists.all": {"$each": enriched}}},
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
        {"user_id": user_id}, {"$set": {"playlists.featured": normalized_ids}}
    )

    print("💾 MongoDB update complete.\n")
    return {"status": "ok", "count": len(normalized_ids)}


@app.post("/delete-playlists", tags=["user"])
def delete_playlists(data: SaveAllPlaylistsRequest):
    playlist_ids = [pl.id for pl in data.playlists]
    print("🗑️ Deleting playlists:", playlist_ids, "for user:", data.user_id)

    result = users_collection.update_one(
        {"user_id": data.user_id},
        {"$pull": {"playlists.all": {"id": {"$in": playlist_ids}}}},  # <-- Fix is here
    )

    return {"status": "deleted", "deleted_count": result.modified_count}


@app.post("/refresh_genres", tags=["user"])
def refresh_genre_analysis(payload: UserIdPayload):
    user_id = payload.user_id

    # Clear cached genre data
    users_collection.update_one(
        {"user_id": user_id},
        {"$unset": {"genre_analysis": "", "genre_last_updated": ""}},
    )

    # Trigger genre regeneration logic (equivalent to calling /genres?refresh=true)
    return get_genres(user_id=user_id, refresh=True)


@app.get("/spotify-me", tags=["spotify"])
def get_spotify_me(user_id: str = Query(...)):
    try:
        access_token = get_token(user_id)
        sp = spotipy.Spotify(auth=access_token)
        me = sp.current_user()
        return me
    except SpotifyException as e:
        print(f"⚠️ Spotify /me error for {user_id}: {e}")
        raise HTTPException(
            status_code=401, detail="Failed to fetch Spotify user profile."
        )


@app.post("/register", tags=["user"])
def register_user(data: dict = Body(...)):
    user_id = data.get("user_id") or data.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    display_name = data.get("display_name")
    profile_picture = data.get("profile_picture")
    selected_playlists = data.get("selected_playlists", [])
    featured_ids = [p.get("id") for p in data.get("featured_playlists", [])]

    sp = spotipy.Spotify(auth=get_token(user_id))

    # Enrich playlist metadata
    enriched = []
    for pl in selected_playlists:
        try:
            playlist = sp.playlist(pl["id"])
            enriched.append(
                {
                    "id": pl["id"],
                    "name": playlist["name"],
                    "image": (
                        playlist["images"][0]["url"] if playlist["images"] else None
                    ),
                    "tracks": playlist["tracks"]["total"],
                    "external_url": playlist["external_urls"]["spotify"],
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to enrich playlist {pl['id']}: {e}")
            continue

    # Save to Mongo
    user_doc = {
        "user_id": user_id,
        "display_name": display_name,
        "profile_picture": profile_picture,
        "playlists": {
            "all": enriched,
            "featured": featured_ids,
        },
        "created_at": datetime.utcnow(),
        "registered": True,
    }

    users_collection.update_one({"user_id": user_id}, {"$set": user_doc}, upsert=True)

    # 🔁 Trigger playback analysis
    try:
        playback = sp.current_playback()
        if playback and playback.get("item"):
            artist = playback["item"]["artists"][0]
            artist_data = sp.artist(artist["id"])
            track_data = {
                "track": {
                    "id": playback["item"]["id"],
                    "name": playback["item"]["name"],
                    "artist": artist["name"],
                    "album": playback["item"]["album"]["name"],
                    "external_url": playback["item"]["external_urls"]["spotify"],
                    "album_art_url": (
                        playback["item"]["album"]["images"][0]["url"]
                        if playback["item"]["album"]["images"]
                        else None
                    ),
                    "genres": artist_data.get("genres", []),
                }
            }
            users_collection.update_one(
                {"user_id": user_id}, {"$set": {"last_played_track": track_data}}
            )
    except Exception as e:
        print("⚠️ Playback fetch failed:", e)

    # 🎯 Trigger genre analysis
    try:
        get_genres(user_id=user_id, refresh=True)
    except Exception as e:
        print("⚠️ Genre analysis failed during registration:", e)

    return {"status": "success", "message": "User registered and initialized"}


@app.post("/admin/sync_playlists", tags=["admin"])
def sync_playlists(user_id: str = Query(...)):
    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)

    all_playlists = []
    offset = 0
    limit = 50
    total_fetched = 0

    # Get current user's Spotify ID
    user_profile = sp.current_user()
    spotify_user_id = user_profile["id"]

    while True:
        page = sp.current_user_playlists(limit=limit, offset=offset)
        items = page.get("items", [])

        if not items:
            break

        for p in items:
            # Filter out playlists not owned by user or with fewer than 4 tracks
            if p["owner"]["id"] != spotify_user_id or p["tracks"]["total"] < 4:
                continue

            all_playlists.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "tracks": p["tracks"]["total"],
                    "owner_id": p["owner"]["id"],
                    "image": p["images"][0]["url"] if p["images"] else None,
                    "external_url": p["external_urls"]["spotify"],
                }
            )

        offset += limit
        total_fetched += len(items)

    playlists_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "playlists": all_playlists,
                "last_updated": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    return {
        "status": "ok",
        "user_id": user_id,
        "total_playlists_fetched": total_fetched,
        "total_playlists_saved": len(all_playlists),
    }


@app.get("/status", tags=["status"])
def get_backend_status():
    try:
        # Quick check on MongoDB connection
        client.admin.command("ping")
        db_status = "online"
    except Exception:
        db_status = "offline"

    return {
        "backend": "online",
        "mongo": db_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")
VERCEL_PROJECT = os.getenv("VERCEL_PROJECT")
VERCEL_TEAM = os.getenv("VERCEL_TEAM")


@app.get("/vercel-status")
def get_vercel_status():
    base_url = "https://api.vercel.com"
    headers = {"Authorization": f"Bearer {VERCEL_TOKEN}"}

    try:
        # Step 1: Get most recent deployment
        deployments_url = f"{base_url}/v6/deployments?projectId={VERCEL_PROJECT}&teamId={VERCEL_TEAM}&limit=1"
        deployments_res = requests.get(deployments_url, headers=headers)
        deployments_res.raise_for_status()
        deployments_data = deployments_res.json()

        if not deployments_data.get("deployments"):
            return {"vercel": "no deployments"}

        latest = deployments_data["deployments"][0]
        deployment_id = latest["uid"]
        deployment_url = latest["url"]
        short_state = latest["state"]

        # Step 2: Get detailed deployment info
        deployment_detail_url = f"{base_url}/v13/deployments/{deployment_id}?teamId={VERCEL_TEAM}"
        detail_res = requests.get(deployment_detail_url, headers=headers)
        detail_res.raise_for_status()
        detail_data = detail_res.json()
        long_state = detail_data.get("readyState")

        # Step 3: Optionally fetch logs (comment out if not needed)
        logs_url = f"{base_url}/v2/deployments/{deployment_id}/events?teamId={VERCEL_TEAM}&limit=5"
        logs_res = requests.get(logs_url, headers=headers)
        logs = logs_res.json().get("events", [])

        return {
            "vercel": long_state,
            "deploymentUrl": f"https://{deployment_url}",
            "shortState": short_state,
            "logs": logs,
        }

    except Exception as e:
        logging.exception("❌ Error fetching Vercel deployment status")
        return {
            "vercel": "error",
            "detail": str(e),
        }
    

@app.post("/set-cookie")
def set_cookie_route(data: CookiePayload):
    response = JSONResponse({"message": "cookie set"})
    response.set_cookie(
        key="sinatra_user_id",
        value=data.user_id,
        httponly=True,
        secure=True,
        samesite="None",
        path="/",
        max_age=3600 * 24 * 7,
    )
    return response