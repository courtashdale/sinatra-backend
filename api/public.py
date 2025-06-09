# api/public.py
from fastapi import APIRouter, HTTPException
from db.mongo import users_collection

router = APIRouter(tags=["public"])

@router.get("/public-profile/{user_id}")
def get_public_profile(user_id: str):
    doc = users_collection.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": doc.get("user_id"),
        "display_name": doc.get("display_name"),
        "profile_picture": doc.get("profile_image_url") or doc.get("profile_picture"),
        "genres_data": doc.get("genres"),
        "last_played_track": doc.get("last_played"),
        "featured_playlists": [
            pl for pl in doc.get("playlists", {}).get("all", [])
            if (pl.get("id") or pl.get("playlist_id")) in doc.get("playlists", {}).get("featured", [])
        ],
    }