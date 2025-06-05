# backend/main.py

# -- Imports
import os
import base64

from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

# -- fastAPI
from fastapi import (
    FastAPI,
    Query,
    HTTPException,
    HTTPException,
)

from fastapi import Body

from fastapi import HTTPException


# -- backend
from backend.utils import get_spotify_oauth
from backend.db import users_collection


app = FastAPI()

IS_DEV = os.getenv("NODE_ENV", "development").lower() == "development"
BASE_URL = os.getenv("DEV_BASE_URL") if IS_DEV else os.getenv("PRO_BASE_URL")

# ---- Classes


# --- FastAPI endpoints


def safe_b64decode(data: str):
    padding = '=' * (-len(data) % 4)  # Add missing padding if needed
    return base64.urlsafe_b64decode(data + padding).decode()