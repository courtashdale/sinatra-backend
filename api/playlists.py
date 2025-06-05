# api/playlists.py
from fastapi import APIRouter, Query, HTTPException, Body
from models.shared import CookiePayload, UserIdPayload, OnboardingPayload
from models.playlists import PlaylistSummary, PlaylistID, SaveAllPlaylistsRequest, FeaturedPlaylistsUpdateRequest
from typing import List
import spotipy

from db.mongo import users_collection, playlists_collection
from services.token import get_token

router = APIRouter(tags=["playlists"])

@router.get("/playlists")
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


@router.get("/all-playlists")
def get_all_user_playlists(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id}, {"playlists.all": 1})
    if not user or "playlists.all" not in user:
        return []

    return user["playlists.all"]


@router.post("/add-playlists")
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


@router.post("/delete-playlists")
def delete_playlists(data: SaveAllPlaylistsRequest):
    playlist_ids = [pl.id for pl in data.playlists]
    print("🗑️ Deleting playlists:", playlist_ids, "for user:", data.user_id)

    result = users_collection.update_one(
        {"user_id": data.user_id},
        {"$pull": {"playlists.all": {"id": {"$in": playlist_ids}}}},
    )

    return {"status": "deleted", "deleted_count": result.modified_count}


@router.post("/update-featured")
def update_featured_playlists(data: FeaturedPlaylistsUpdateRequest):
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
    known_ids = {pl.get("id") for pl in all_playlists}

    normalized_ids = [pid for pid in playlist_ids if pid in known_ids]

    users_collection.update_one(
        {"user_id": user_id}, {"$set": {"playlists.featured": normalized_ids}}
    )

    return {"status": "ok", "count": len(normalized_ids)}


@router.get("/public-playlist/{playlist_id}")
def get_public_playlist(playlist_id: str):
    match = users_collection.find_one(
        {"playlists.all.playlist_id": playlist_id}, {"playlists.all.$": 1}
    )
    if not match or "playlists.all" not in match:
        raise HTTPException(status_code=404, detail="Playlist not found")

    return match["playlists.all"][0]


@router.get("/playlist-info")
def get_playlist_info(user_id: str = Query(...), playlist_id: str = Query(...)):
    access_token = get_token(user_id)
    sp = spotipy.Spotify(auth=access_token)
    playlist = sp.playlist(playlist_id)

    return {
        "name": playlist["name"],
        "image": playlist["images"][0]["url"] if playlist["images"] else None,
    }


@router.get("/user-playlists")
def get_user_playlists(user_id: str = Query(...)):
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