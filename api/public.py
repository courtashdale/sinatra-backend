# api/public.py
from fastapi import APIRouter, HTTPException, Query
from db.mongo import users_collection

router = APIRouter(tags=["public"])


async def _build_profile_response(user_id: str):
    """Return the public profile document for the given user."""
    doc = await users_collection.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": doc.get("user_id"),
        "display_name": doc.get("display_name"),
        "profile_picture": doc.get("profile_image_url") or doc.get("profile_picture"),
        "genres_data": doc.get("genres"),
        "last_played_track": doc.get("last_played_track"),
        "featured_playlists": [
            pl
            for pl in doc.get("playlists", {}).get("all", [])
            if (pl.get("id") or pl.get("playlist_id"))
            in doc.get("playlists", {}).get("featured", [])
        ],
    }


@router.get("/public-profile/{user_id}")
async def get_public_profile(user_id: str):
    return await _build_profile_response(user_id)

@router.get("/public-playlists/{user_id}")
async def get_public_playlists(user_id: str):
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.get("playlists", {}).get("all", [])

@router.get("/public-profile")
async def get_public_profile_query(user_id: str = Query(...)):
    return await _build_profile_response(user_id)

@router.get("/public-track/{user_id}")
async def get_public_track(user_id: str):
    doc = await users_collection.find_one({"user_id": user_id}, {"last_played_track": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    track = doc.get("last_played_track")
    if not track:
        return {"track": None}

    required_keys = {"id", "name", "artist", "album", "album_art_url"}
    if not isinstance(track, dict) or not required_keys.issubset(track.keys()):
        raise HTTPException(status_code=422, detail="Track data is malformed")

    return {"track": track}

@router.get("/public-genres/{user_id}")
async def get_public_genres(user_id: str):
    doc = await users_collection.find_one({"user_id": user_id})
    if not doc or "genre_analysis" not in doc:
        raise HTTPException(status_code=404, detail="No genre data found")
    return doc["genre_analysis"]