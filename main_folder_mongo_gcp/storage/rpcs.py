# 📂 rpc.py

import logging
from typing import List
from mongo_client import get_collection

logger = logging.getLogger(__name__)

RPC_LIST: List[str] = []
RPC_INDEX = 0

def get_rpc_collection():
    return get_collection("rpcs")


async def load_rpc_list():
    """
    Load the RPC endpoints from MongoDB and reset rotation index.
    """
    global RPC_LIST, RPC_INDEX
    collection = get_rpc_collection()
    doc = await collection.find_one({"_id": "rpc_list"})
    RPC_LIST = doc.get("endpoints", []) if doc else []
    RPC_INDEX = 0
    logger.info("✅ RPCs loaded from rpcs collection")


async def save_rpc_list():
    """
    Save the current in-memory RPC list to MongoDB.
    """
    collection = get_rpc_collection()
    await collection.update_one(
        {"_id": "rpc_list"},
        {"$set": {"endpoints": RPC_LIST}},
        upsert=True
    )


def get_next_rpc() -> str:
    """
    Returns the next RPC endpoint in round-robin fashion.
    """
    global RPC_INDEX
    if not RPC_LIST:
        raise ValueError("🚨 No RPC endpoints loaded!")
    rpc = RPC_LIST[RPC_INDEX % len(RPC_LIST)]
    RPC_INDEX += 1
    logger.debug(f"🔁 Rotating RPC: Using endpoint {rpc}")
    return rpc


async def add_rpcs_bulk(rpcs: List[str]) -> List[str]:
    """
    Add multiple RPC endpoints. Returns list of newly added RPCs.
    """
    global RPC_LIST
    await load_rpc_list()

    new_rpcs = [rpc for rpc in rpcs if rpc not in RPC_LIST]
    if not new_rpcs:
        return []

    RPC_LIST.extend(new_rpcs)

    collection = get_rpc_collection()
    await collection.update_one(
        {"_id": "rpc_list"},
        {"$addToSet": {"endpoints": {"$each": new_rpcs}}},
        upsert=True
    )

    return new_rpcs


async def remove_rpcs_bulk(rpcs: List[str]) -> List[str]:
    """
    Remove multiple RPC endpoints. Returns list of successfully removed RPCs.
    """
    global RPC_LIST
    await load_rpc_list()

    to_remove = [rpc for rpc in rpcs if rpc in RPC_LIST]
    if not to_remove:
        return []

    RPC_LIST = [rpc for rpc in RPC_LIST if rpc not in to_remove]

    collection = get_rpc_collection()
    await collection.update_one(
        {"_id": "rpc_list"},
        {"$pull": {"endpoints": {"$in": to_remove}}}
    )

    return to_remove
