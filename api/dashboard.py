# api/dashboard.py
from fastapi import APIRouter, Request, HTTPException
from db.mongo import users_collection

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(request: Request):
    user_id = request.cookies.get("sinatra_user_id")
    print(f"🍪 /dashboard cookie received: sinatra_user_id = {user_id}")

    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    doc = users_collection.find_one({"user_id": user_id})
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


@router.get("/public-profile/{user_id}")
def public_profile(user_id: str):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    genre_analysis = user.get("genre_analysis")
    playlists = user.get("playlists", {})
    featured_ids = playlists.get("featured", [])
    all_playlists = playlists.get("all", [])
    featured = [
        pl for pl in all_playlists
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