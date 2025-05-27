from pymongo import AsyncMongoClient
from pymongo.server_api import ServerApi
from pwd_loader.gcp_loader import get_secret
import os
import logging
from dotenv import load_dotenv

load_dotenv() 

#MONGO_URI = os.getenv("MONGO_URI")

# MONGO_URI = get_secret("mongo-uri")

# assert MONGO_URI, "Missing required secrets."

# if not MONGO_URI:
#     raise RuntimeError("❌ MONGO_URI environment variable is not set.")

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "price_alert_bot")

client: AsyncMongoClient = None

# Exposed DB handle
db = None
_collection_cache = {}

async def connect():
    global client, db

    MONGO_URI = get_secret("mongo-uri")
    try:
        client = AsyncMongoClient(MONGO_URI, server_api=ServerApi("1"))
        db = client[MONGO_DB_NAME]
        logging.info("✅ Connected to MongoDB")
    except Exception as e:
        logging.exception(f"❌ MongoDB connection failed:")
        raise


async def disconnect():
    global client
    if client:
        await client.close()
        logging.info("🔌 MongoDB connection closed")

def get_collection(collection_name: str):
    if db is None:
        raise RuntimeError("MongoDB not connected. Call connect() first.")
    if collection_name not in _collection_cache:
        _collection_cache[collection_name] = db[collection_name]
    return _collection_cache[collection_name]
