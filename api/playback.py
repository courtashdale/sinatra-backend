# api/playback.py
from fastapi import APIRouter, Query, Depends, HTTPException
import spotipy
from fastapi import Request

from db.mongo import users_collection
from services.token import get_token
from services.spotify_auth import get_artist_genres

router = APIRouter(tags=["playback"])


@router.get("/playback")
def get_playback_state(request: Request, access_token: str = Depends(get_token)):
    user_id = request.cookies.get("sinatra_user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing sinatra_user_id cookie")

    sp = spotipy.Spotify(auth=access_token)

    try:
        playback = sp.current_playback()

        if playback and playback.get("item"):
            # same as before...
            track_data = {...}
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_played_track": track_data}},
            )
            return {"playback": track_data}
        else:
            user = users_collection.find_one({"user_id": user_id})
            return {"playback": user.get("last_played_track", None)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recently-played")
def get_recently_played(request: Request, access_token: str = Depends(get_token), limit: int = 1):
    sp = spotipy.Spotify(auth=access_token)
    artist_genre_cache = {}

    try:
        recent = sp.current_user_recently_played(limit=limit)
        if not recent["items"]:
            return {"track": None}

        item = recent["items"][0]
        track = item["track"]
        artist = track["artists"][0]
        artist_data = sp.artist(artist["id"])
        genres = artist_data.get("genres", [])

        track_data = {
            "id": track["id"],
            "name": track["name"],
            "artist": artist["name"],
            "album": track["album"]["name"],
            "external_url": track["external_urls"]["spotify"],
            "album_art_url": (
                track["album"]["images"][0]["url"]
                if track["album"].get("images")
                else None
            ),
            "genres": genres,
        }

        return {"track": track_data}

    except Exception as e:
        print(f"⚠️ Recently played error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch recently played track")


@router.post("/play")
def start_playback(access_token: str = Depends(get_token)):
    sp = spotipy.Spotify(auth=access_token)
    sp.start_playback()
    return {"status": "playing"}


@router.post("/pause")
def pause_playback(access_token: str = Depends(get_token)):
    sp = spotipy.Spotify(auth=access_token)
    sp.pause_playback()
    return {"status": "paused"}