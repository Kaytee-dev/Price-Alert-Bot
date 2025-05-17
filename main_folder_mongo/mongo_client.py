from pymongo import AsyncMongoClient
from pymongo.server_api import ServerApi
import os
import logging

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "price_alert_bot")

client: AsyncMongoClient = None

# Exposed DB handle
db = None


async def connect():
    global client, db
    try:
        client = AsyncMongoClient(MONGO_URI, server_api=ServerApi("1"))
        db = client[MONGO_DB_NAME]
        logging.info("✅ Connected to MongoDB")
    except Exception as e:
        logging.error(f"❌ MongoDB connection failed: {e}")
        raise


async def disconnect():
    global client
    if client:
        await client.close()
        logging.info("🔌 MongoDB connection closed")
