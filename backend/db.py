# backend/db.py

import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DB", "sinatra")]
users_collection = db.users
playlists_collection = db.playlists

try:
    client.admin.command("ping")
    print("✅ MongoDB connection successful ✅")
except ConnectionFailure:
    print("🟥 MongoDB connection failed 🟥")