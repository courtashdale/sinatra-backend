# api/playback.py
from fastapi import APIRouter, Query, Depends, HTTPException
import spotipy

from db.mongo import users_collection
from services.token import get_token
from services.spotify_auth import get_artist_genres

router = APIRouter(tags=["playback"])


@router.get("/playback")
def get_playback_state(
    user_id: str = Query(...),
    access_token: str = Depends(get_token)
):
    sp = spotipy.Spotify(auth=access_token)

    try:
        playback = sp.current_playback()

        if playback and playback.get("item"):
            item = playback["item"]
            artist = item["artists"][0]
            artist_data = sp.artist(artist["id"])

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
                    "genres": artist_data.get("genres", []),
                }
            }

            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_played_track": track_data}},
            )

            return {"playback": track_data}
        else:
            return {"playback": None}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recently-played")
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