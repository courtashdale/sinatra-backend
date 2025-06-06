# api/system.py
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from db.mongo import users_collection, client
from pymongo.errors import ConnectionFailure
from datetime import datetime
import os, requests, logging


router = APIRouter(tags=["system"])

@router.delete("/delete-user")
def delete_user(user_id: str = Query(...)):
    result = users_collection.delete_one({"user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted"}


@router.get("/health")
def health_check():
    try:
        client.admin.command("ping")
        return {"status": "ok", "db": "connected"}
    except ConnectionFailure:
        return {"status": "error", "db": "disconnected"}


@router.get("/status")
def get_backend_status():
    try:
        client.admin.command("ping")
        db_status = "online"
    except Exception:
        db_status = "offline"

    return {
        "backend": "online",
        "mongo": db_status,
        "timestamp": datetime.utcnow().isoformat(),
    }