# api/user.py
from fastapi import APIRouter, Request, HTTPException, Query, Body
from db.mongo import users_collection
from services.token import get_token
from datetime import datetime
import spotipy

router = APIRouter(tags=["user"])


@router.get("/me")
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


@router.get("/users")
def get_users():
    return list(
        users_collection.find(
            {}, {"_id": 0, "user_id": 1, "display_name": 1, "email": 1}
        )
    )


@router.post("/register")
def register_user(data: dict = Body(...)):
    user_id = data.get("user_id") or data.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    display_name = data.get("display_name")
    profile_picture = data.get("profile_picture")
    selected_playlists = data.get("selected_playlists", [])
    featured_ids = [p.get("id") for p in data.get("featured_playlists", [])]

    sp = spotipy.Spotify(auth=get_token(user_id))

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

    # Optional: trigger last_played and genre analysis (import locally)
    try:
        from services.music.wizard import genre_highest
        from api.genres import get_genres

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

    try:
        get_genres(user_id=user_id, refresh=True)
    except Exception as e:
        print("⚠️ Genre analysis failed during registration:", e)

    return {"status": "success", "message": "User registered and initialized"}