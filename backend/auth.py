# backend/auth.py

from fastapi import Query, HTTPException, Request
from backend.db import users_collection
from backend.utils import get_spotify_oauth

sp_oauth = get_spotify_oauth()

def get_token(request: Request) -> str:
    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user session")

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found in database")

    token_info = {
        "access_token": user.get("access_token"),
        "refresh_token": user.get("refresh_token"),
        "expires_at": user.get("expires_at"),
    }

    if not all(token_info.values()):
        raise HTTPException(status_code=400, detail="User token info incomplete")

    if sp_oauth.is_token_expired(token_info):
        refreshed = sp_oauth.refresh_access_token(user["refresh_token"])
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
        return refreshed["access_token"]

    return token_info["access_token"]