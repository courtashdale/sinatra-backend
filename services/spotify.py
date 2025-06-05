# services/spotify.py
import spotipy
from backend.auth import get_token
from backend.utils import get_artist_genres


def get_spotify_client(user_id: str) -> spotipy.Spotify:
    access_token = get_token(user_id)
    return spotipy.Spotify(auth=access_token)


def enrich_playlist(sp: spotipy.Spotify, playlist_id: str) -> dict:
    playlist = sp.playlist(playlist_id)
    return {
        "id": playlist["id"],
        "name": playlist["name"],
        "image": playlist["images"][0]["url"] if playlist["images"] else None,
        "tracks": playlist["tracks"]["total"],
        "external_url": playlist["external_urls"]["spotify"],
    }


def simplify_track_with_genres(sp: spotipy.Spotify, track: dict, genre_cache: dict) -> dict:
    return {
        "name": track["name"],
        "artists": [a["name"] for a in track["artists"]],
        "album": track["album"]["name"],
        "external_url": track["external_urls"]["spotify"],
        "isrc": track.get("external_ids", {}).get("isrc"),
        "genres": get_artist_genres(sp, track["artists"], genre_cache),
    }