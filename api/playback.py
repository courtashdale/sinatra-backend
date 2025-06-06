# api/playback.py
from fastapi import APIRouter, Query, Depends, HTTPException, Request
import spotipy
from db.mongo import users_collection
from services.token import get_token

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
            track = playback["item"]
            artist = track["artists"][0]
            track_data = {
                "id": track["id"],
                "name": track["name"],
                "artist": artist["name"],
                "album": track["album"]["name"],
                "external_url": track["external_urls"]["spotify"],
                "album_art_url": track["album"]["images"][0]["url"] if track["album"].get("images") else None,
            }

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
            "album_art_url": track["album"]["images"][0]["url"] if track["album"].get("images") else None,
            "genres": genres,
        }

        return {"track": track_data}

    except Exception as e:
        print(f"⚠️ Recently played error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch recently played track")


@router.get("/now-playing")
def now_playing(request: Request, access_token: str = Depends(get_token)):
    sp = spotipy.Spotify(auth=access_token)

    try:
        current = sp.current_playback()
        if not current or not current.get("item"):
            return {"track": None}

        track = current["item"]
        artist = track["artists"][0]
        artist_data = sp.artist(artist["id"])
        genres = artist_data.get("genres", [])

        track_data = {
            "id": track["id"],
            "name": track["name"],
            "artist": artist["name"],
            "album": track["album"]["name"],
            "external_url": track["external_urls"]["spotify"],
            "album_art_url": track["album"]["images"][0]["url"] if track["album"].get("images") else None,
            "genres": genres,
        }

        return {"track": track_data}

    except Exception as e:
        print(f"⚠️ Now playing error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch now playing track")


@router.post("/update-playing")
def update_playing(request: Request, access_token: str = Depends(get_token)):
    user_id = request.cookies.get("sinatra_user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing sinatra_user_id cookie")

    sp = spotipy.Spotify(auth=access_token)

    try:
        current = sp.current_playback()
        if not current or not current.get("item"):
            raise HTTPException(status_code=404, detail="Nothing is currently playing")

        track = current["item"]
        artist = track["artists"][0]
        artist_data = sp.artist(artist["id"])
        genres = artist_data.get("genres", [])

        track_data = {
            "id": track["id"],
            "name": track["name"],
            "artist": artist["name"],
            "album": track["album"]["name"],
            "external_url": track["external_urls"]["spotify"],
            "album_art_url": track["album"]["images"][0]["url"] if track["album"].get("images") else None,
            "genres": genres,
        }

        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"last_played_track": {"track": track_data}}}
        )

        return {"status": "updated", "track": track_data}

    except Exception as e:
        print(f"⚠️ Update playing error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update last played track")


@router.get("/check-recent")
def check_recent_track(request: Request):
    user_id = request.cookies.get("sinatra_user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing sinatra_user_id cookie")

    user = users_collection.find_one({"user_id": user_id})
    last_track = user.get("last_played_track", {})
    return {"track": last_track.get("track") or last_track}