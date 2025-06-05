# api/auth.py
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
import base64, json, os
import spotipy
from backend.utils import get_spotify_oauth
from db.mongo import users_collection

router = APIRouter(tags=["auth"])


def safe_b64decode(data: str):
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode()


@router.get("/login")
async def login(redirect_uri: str = Query(...)):
    state_payload = json.dumps({"redirect_uri": redirect_uri})
    encoded_state = base64.urlsafe_b64encode(state_payload.encode()).decode()

    sp_oauth = get_spotify_oauth(redirect_uri)
    auth_url = sp_oauth.get_authorize_url(state=encoded_state)
    return RedirectResponse(auth_url)


@router.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    try:
        decoded_state = safe_b64decode(state)
        redirect_uri = json.loads(decoded_state)["redirect_uri"]
        print(f"✅ Extracted redirect_uri from state: {redirect_uri}")
    except Exception as e:
        print(f"❌ Failed to decode state: {e}")
        raise HTTPException(status_code=400, detail=f"State decode error: {e}")

    try:
        sp_oauth = get_spotify_oauth(redirect_uri)
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        sp = spotipy.Spotify(auth=token_info["access_token"])
        profile = sp.current_user()
        user_id = profile.get("id")
    except Exception as e:
        print(f"❌ Token exchange or user fetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Internal callback error: {e}")

    if not user_id:
        raise HTTPException(status_code=400, detail="Spotify user ID missing.")

    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "access_token": token_info["access_token"],
                "refresh_token": token_info["refresh_token"],
                "expires_at": token_info["expires_at"],
            }
        },
        upsert=True,
    )

    frontend_base = os.getenv("DEV_BASE_URL") if os.getenv("NODE_ENV") == "development" else os.getenv("PRO_BASE_URL")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script>
            document.cookie = "sinatra_user_id={user_id}; path=/; domain=.sinatra.live; max-age=604800; SameSite=None; Secure";
            window.location.href = "{frontend_base}/home";
        </script>
    </head>
    <body></body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/refresh_token")
def refresh_token(refresh_token: str = Query(...)):
    sp_oauth = get_spotify_oauth()
    refreshed = sp_oauth.refresh_access_token(refresh_token)
    return {
        "access_token": refreshed["access_token"],
        "expires_in": refreshed["expires_in"],
    }

@router.get("/refresh-session", tags=["routes"])
def refresh_session(user_id: str = Query(...)):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token_info = {
        "access_token": user["access_token"],
        "refresh_token": user["refresh_token"],
        "expires_at": user["expires_at"],
    }
    sp_oauth = get_spotify_oauth()
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
        return {"status": "refreshed"}

    return {"status": "ok"}