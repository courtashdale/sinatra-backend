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
from fastapi import Request
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

class FeaturedPayload(BaseModel):
    playlist_ids: List[str]

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

class RegisterPayload(BaseModel):
    display_name: str
    profile_picture: str
    selected_playlists: List[dict]
    featured_playlists: List[dict]


# --- FastAPI endpoints

@app.get("/login",tags=["routes"])
def login():
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)

@app.get("/user-playlists", tags=["user"])
def get_user_playlists(request: Request, user_id: str = Query(None)):
    # If no user_id is provided, fallback to cookie (for logged-in users)
    if not user_id:
        user_id = request.cookies.get("user_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user_id")

    doc = playlists_collection.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="No synced playlists found for user.")

    return {
        "user_id": doc["user_id"],
        "last_updated": doc.get("last_updated"),
        "playlists": doc.get("playlists", [])
    }

@app.get("/callback")
def callback(code: str):
    token_info = sp_oauth.get_access_token(code)
    access_token = token_info["access_token"]
    refresh_token = token_info["refresh_token"]
    expires_at = token_info["expires_at"]

    sp = spotipy.Spotify(auth=access_token)
    user_data = sp.current_user()
    user_id = user_data["id"]

    # Store tokens in DB
    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "display_name": user_data["display_name"],
                "images": user_data["images"],
            }
        },
        upsert=True,
    )

    # Redirect and set secure cookie
    response = RedirectResponse(url="/home")
    response.set_cookie(
        key="user_id",
        value=user_id,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=86400,
    )
    return response

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
def get_playback_state(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    access_token = get_token(request)
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
                    "album_art_url": item["album"]["images"][0]["url"] if item["album"].get("images") else None,
                    "genres": artist_data.get("genres", []),
                }
            }

            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_played_track": track_data}},
            )

            return {"playback": track_data}

        return {"playback": None}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/refresh_token", tags=["auth"])
def refresh(refresh_token: str = Query(...)):
    refreshed = sp_oauth.refresh_access_token(refresh_token)
    return {
        "access_token": refreshed["access_token"],
        "expires_in": refreshed["expires_in"],
    }


@app.get("/me")
def get_current_user(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    all_playlists = user.get("playlists", {}).get("all", [])
    featured_ids = user.get("playlists", {}).get("featured", [])

    # Match featured IDs to full playlist objects
    featured_playlists = [
        pl for pl in all_playlists if pl.get("id") in featured_ids
    ]

    return {
        "user_id": user["user_id"],
        "display_name": user.get("display_name"),
        "profile_picture": user.get("profile_picture", ""),
        "genre_analysis": user.get("genre_analysis", {}),
        "last_played_track": user.get("last_played_track"),
        "playlists": {
            "featured": featured_playlists,
            "all": all_playlists,
        }
    }

@app.get("/genres", tags=["user"])
def get_genres(request: Request, refresh: bool = False):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    user = users_collection.find_one({"user_id": user_id})
    if not refresh and user and "genre_analysis" in user:
        return user["genre_analysis"]

    try:
        access_token = get_token(request)
        sp = spotipy.Spotify(auth=access_token)

        top_artists = []
        for offset in (0, 50):
            try:
                batch = sp.current_user_top_artists(limit=50, offset=offset, time_range="short_term")
                top_artists.extend(batch.get("items", []))
            except Exception as e:
                print(f"⚠️ Failed to fetch top artists at offset {offset}: {e}")

        flat_genres = []
        for artist in top_artists:
            flat_genres.extend([g.strip().lower() for g in artist.get("genres", [])])

        raw_highest = genre_wizard.genre_highest(flat_genres)
        sub_genres_raw = genre_wizard.genre_frequency(flat_genres)

        total = sum(raw_highest.values()) or 1
        meta_genres = {
            genre: {
                "portion": round((count / total) * 100, 1),
                "gradient": get_gradient_for_genre(genre)
            }
            for genre, count in raw_highest.items()
        }

        try:
            genre_map_path = os.path.join("backend", "music", "genre-map.json")
            with open(genre_map_path) as f:
                genre_map = json.load(f)
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
                "gradient": get_gradient_for_genre(parent)
            }

        sorted_subs = sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])
        top_sub = next((g for g, _ in sorted_subs if genre_map.get(g.lower(), "") != g.lower()), None)
        top_meta = genre_map.get(top_sub.lower(), "other") if top_sub else None

        result = {
            "sub_genres": dict(sorted(sub_genres.items(), key=lambda x: -x[1]["portion"])[:10]),
            "meta_genres": dict(sorted(meta_genres.items(), key=lambda x: -x[1]["portion"])[:10]),
            "top_subgenre": {
                "sub_genre": top_sub,
                "parent_genre": top_meta,
                "gradient": get_gradient_for_genre(top_meta),
            }
        }

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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Genre analysis failed: {str(e)}")


@app.delete("/delete-user",tags=["mongodb"])
def delete_user(user_id: str = Query(...)):
    result = users_collection.delete_one({"user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted"}


@app.get("/refresh-session", tags=["routes"])
def refresh_session(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token_info = {
        "access_token": user.get("access_token"),
        "refresh_token": user.get("refresh_token"),
        "expires_at": user.get("expires_at"),
    }

    if not token_info["access_token"] or not token_info["refresh_token"]:
        raise HTTPException(status_code=403, detail="Missing token info")

    if sp_oauth.is_token_expired(token_info):
        refreshed = sp_oauth.refresh_access_token(token_info["refresh_token"])
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

@app.get("/dashboard", tags=["user"])
def get_dashboard(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    genre_analysis = user.get("genre_analysis")
    last_played = user.get("last_played_track")
    all_playlists = user.get("playlists", {}).get("all", [])
    featured_ids = user.get("playlists", {}).get("featured", [])

    featured_playlists = [
        pl for pl in all_playlists if pl.get("id") in featured_ids
    ]

    return {
        "user": {
            "user_id": user["user_id"],
            "display_name": user.get("display_name"),
            "profile_picture": user.get("profile_picture", ""),
            "genre_analysis": genre_analysis or {},
        },
        "playlists": {
            "featured": featured_playlists,
            "all": all_playlists,
        },
        "played_track": last_played,
    }

@app.get("/public-profile/{user_id}")
def public_profile(user_id: str):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    genre_analysis = user.get("genre_analysis")
    all_playlists = user.get("playlists", {}).get("all", [])
    featured_ids = user.get("playlists", {}).get("featured", [])

    featured_playlists = [
        pl for pl in all_playlists if pl.get("id") in featured_ids
    ]

    return {
        "user_id": user["user_id"],
        "display_name": user.get("display_name"),
        "profile_picture": user.get("profile_picture"),
        "last_played_track": user.get("last_played_track"),
        "genres_data": genre_analysis,
        "featured_playlists": featured_playlists,
    }

@app.post("/add-playlists", tags=["user"])
def add_playlists(request: Request, data: SaveAllPlaylistsRequest):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    access_token = get_token(request)
    sp = spotipy.Spotify(auth=access_token)

    enriched = []

    for pl in data.playlists:
        try:
            playlist = sp.playlist(pl.id)
            enriched.append({
                "id": pl.id,
                "name": playlist["name"],
                "image": playlist["images"][0]["url"] if playlist["images"] else None,
                "tracks": playlist["tracks"]["total"],
                "external_url": playlist["external_urls"]["spotify"]
            })
        except Exception as e:
            print(f"⚠️ Failed to fetch metadata for playlist {pl.id}: {e}")
            continue

    if not enriched:
        raise HTTPException(status_code=400, detail="No valid playlists to add")

    result = users_collection.update_one(
        {"user_id": user_id},
        {
            "$addToSet": {
                "playlists.all": {"$each": enriched}
            }
        },
        upsert=True,
    )

    return {"status": "added", "modified_count": result.modified_count}

@app.post("/update-featured", tags=["user"])
def update_featured_playlists(request: Request, data: FeaturedPayload):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    playlist_ids = data.playlist_ids
    if not isinstance(playlist_ids, list):
        raise HTTPException(status_code=400, detail="Invalid input")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    all_playlists = user.get("playlists", {}).get("all", [])
    known_ids = {pl.get("id") for pl in all_playlists}

    normalized_ids = [pid for pid in playlist_ids if pid in known_ids]

    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"playlists.featured": normalized_ids}}
    )

    return {"status": "ok", "count": len(normalized_ids)}

@app.post("/delete-playlists", tags=["user"])
def delete_playlists(request: Request, data: SaveAllPlaylistsRequest):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    playlist_ids = [pl.id for pl in data.playlists]

    result = users_collection.update_one(
        {"user_id": user_id},
        {
            "$pull": {
                "playlists.all": {
                    "id": {"$in": playlist_ids}
                }
            }
        }
    )

    return {"status": "deleted", "deleted_count": result.modified_count}


@app.post("/refresh_genres", tags=["user"])
def refresh_genre_analysis(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    users_collection.update_one(
        {"user_id": user_id},
        {"$unset": {"genre_analysis": "", "genre_last_updated": ""}}
    )

    # Trigger genre regeneration logic (same as GET /genres?refresh=true)
    return get_genres(request=request, refresh=True)

@app.get("/spotify-me", tags=["spotify"])
def get_spotify_me(request: Request):
    try:
        access_token = get_token(request)
        sp = spotipy.Spotify(auth=access_token)
        return sp.current_user()
    except SpotifyException as e:
        print(f"⚠️ Spotify /me error: {e}")
        raise HTTPException(status_code=401, detail="Failed to fetch Spotify user profile.")
    
@app.post("/register", tags=["user"])
def register_user(request: Request, data: RegisterPayload):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    display_name = data.display_name
    profile_picture = data.profile_picture
    selected_playlists = data.selected_playlists
    featured_ids = [p.get("id") for p in data.featured_playlists]

    sp = spotipy.Spotify(auth=get_token(request))

    enriched = []
    for pl in selected_playlists:
        try:
            playlist = sp.playlist(pl["id"])
            enriched.append({
                "id": pl["id"],
                "name": playlist["name"],
                "image": playlist["images"][0]["url"] if playlist["images"] else None,
                "tracks": playlist["tracks"]["total"],
                "external_url": playlist["external_urls"]["spotify"]
            })
        except Exception as e:
            print(f"⚠️ Failed to enrich playlist {pl['id']}: {e}")
            continue

    user_doc = {
        "user_id": user_id,
        "display_name": display_name,
        "profile_picture": profile_picture,
        "playlists": {
            "all": enriched,
            "featured": featured_ids,
        },
        "created_at": datetime.utcnow(),
        "registered": True
    }

    users_collection.update_one(
        {"user_id": user_id},
        {"$set": user_doc},
        upsert=True
    )

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
                    "album_art_url": playback["item"]["album"]["images"][0]["url"] if playback["item"]["album"]["images"] else None,
                    "genres": artist_data.get("genres", [])
                }
            }
            users_collection.update_one({"user_id": user_id}, {"$set": {"last_played_track": track_data}})
    except Exception as e:
        print("⚠️ Playback fetch failed:", e)

    try:
        get_genres(request, refresh=True)
    except Exception as e:
        print("⚠️ Genre analysis failed during registration:", e)

    return {"status": "success", "message": "User registered and initialized"}

@app.post("/admin/sync_playlists", tags=["admin"])
def sync_playlists(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    access_token = get_token(request)
    sp = spotipy.Spotify(auth=access_token)

    all_playlists = []
    offset = 0
    limit = 50
    total_fetched = 0

    try:
        user_profile = sp.current_user()
        spotify_user_id = user_profile["id"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Failed to fetch current user: {e}")

    while True:
        page = sp.current_user_playlists(limit=limit, offset=offset)
        items = page.get("items", [])
        if not items:
            break

        for p in items:
            if p["owner"]["id"] != spotify_user_id or p["tracks"]["total"] < 4:
                continue

            all_playlists.append({
                "id": p["id"],
                "name": p["name"],
                "tracks": p["tracks"]["total"],
                "owner_id": p["owner"]["id"],
                "image": p["images"][0]["url"] if p["images"] else None,
                "external_url": p["external_urls"]["spotify"]
            })

        offset += limit
        total_fetched += len(items)

    playlists_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "playlists": all_playlists,
                "last_updated": datetime.now(timezone.utc)
            }
        },
        upsert=True
    )

    return {
        "status": "ok",
        "user_id": user_id,
        "total_playlists_fetched": total_fetched,
        "total_playlists_saved": len(all_playlists)
    }