# models/shared.py
from pydantic import BaseModel
from typing import List


class CookiePayload(BaseModel):
    user_id: str


class UserIdPayload(BaseModel):
    user_id: str


class OnboardingPayload(BaseModel):
    user_id: str
    display_name: str
    profile_picture: str
    playlist_ids: List[str]