# api/public.py
from fastapi import APIRouter, HTTPException, Query
from db.mongo import users_collection
from services.music.track_utils import apply_meta_gradients

router = APIRouter(tags=["public"])

def _build_profile_response(user_id: str):
    """Return the public profile document for the given user."""
    doc = users_collection.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    
    playlists_data = doc.get("playlists", {})
    all_playlists = playlists_data.get("all", [])
    featured_ids = playlists_data.get("featured", [])

    playlist_lookup = {pl.get("id") or pl.get("playlist_id"): pl for pl in all_playlists}
    featured_playlists = [playlist_lookup.get(pid) for pid in featured_ids if pid in playlist_lookup]

    genres_data = doc.get("genres_analysis") or doc.get("genres")
    last_played = apply_meta_gradients(doc.get("last_played_track", {}))

    return {
        "user_id": doc.get("user_id"),
        "display_name": doc.get("display_name"),
        "profile_picture": doc.get("profile_image_url") or doc.get("profile_picture"),
        "playlists": {
            "all": all_playlists,
            "featured": featured_playlists,
        },
        "genres": doc.get("genre_analysis"),
        "last_played": last_played,
    }


@router.get("/public-profile/{user_id}")
def get_public_profile(user_id: str):
    """Fetch a user's public profile via path parameter."""
    return _build_profile_response(user_id)


@router.get("/public-profile")
def get_public_profile_query(user_id: str = Query(...)):
    """Fetch a user's public profile via query parameter."""
    return _build_profile_response(user_id)

@router.get("/public-track/{user_id}")
def get_public_track(user_id: str):
    doc = users_collection.find_one({"user_id": user_id}, {"last_played_track": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    track = doc.get("last_played_track")
    if not track:
        # Gracefully indicate missing track rather than returning 404
        return {"track": None}

    required_keys = {"id", "name", "artist", "album", "album_art_url"}
    if not isinstance(track, dict) or not required_keys.issubset(track.keys()):
        raise HTTPException(status_code=422, detail="Track data is malformed")

    return {"track": track}

@router.get("/public-genres/{user_id}")
def get_public_genres(user_id: str):
    doc = users_collection.find_one({"user_id": user_id})
    if not doc or "genre_analysis" not in doc:
        raise HTTPException(status_code=404, detail="No genre data found")
    return doc["genre_analysis"]