# backend/utils.py
import os
from spotipy.oauth2 import SpotifyOAuth

# Only load .env locally — Railway will have NODE_ENV set
if os.getenv("NODE_ENV", "").strip().lower() != "production":
    from dotenv import load_dotenv
    load_dotenv()

NODE_ENV = os.getenv("NODE_ENV", "").strip().lower()
IS_DEV = NODE_ENV == "development"

# Decide which callback is required
CALLBACK_KEY = "DEV_CALLBACK" if IS_DEV else "PRO_CALLBACK"

# Required env vars
required_env_vars = [
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "MONGODB_URI",
    "NODE_ENV",
    CALLBACK_KEY,
]

# Debugging output
print("🧪 NODE_ENV:", NODE_ENV)
print("🧪 IS_DEV:", IS_DEV)
print("🧪 Checking for:", CALLBACK_KEY)

for var in required_env_vars:
    if not os.getenv(var):
        raise Exception(f"Missing environment variable: {var}")

CALLBACK_URL = os.getenv(CALLBACK_KEY)

def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=CALLBACK_URL,
        scope="user-read-private user-read-email user-read-playback-state user-modify-playback-state playlist-read-private user-top-read user-read-recently-played",
    )

def get_artist_genres(sp, artists, cache):
    genres = set()
    for artist in artists:
        artist_id = artist["id"]
        if artist_id not in cache:
            artist_info = sp.artist(artist_id)
            cache[artist_id] = artist_info.get("genres", [])
        genres.update(cache[artist_id])
    return list(genres)