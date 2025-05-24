# 📂 File: storage/rpcs.py

import logging
from typing import List
from util.utils import load_json, save_json
from config import RPC_LIST_FILE

logger = logging.getLogger(__name__)

RPC_LIST: List[str] = []
RPC_INDEX = 0

def load_rpc_list():
    global RPC_LIST, RPC_INDEX
    RPC_LIST = load_json(RPC_LIST_FILE, [], "RPC endpoints")
    RPC_INDEX = 0

def save_rpc_list():
    save_json(RPC_LIST_FILE, RPC_LIST, "RPC endpoints")

def get_next_rpc() -> str:
    """Returns the next RPC endpoint in rotation."""
    global RPC_INDEX
    if not RPC_LIST:
        raise ValueError("🚨 No RPC endpoints loaded!")
    rpc = RPC_LIST[RPC_INDEX % len(RPC_LIST)]
    RPC_INDEX += 1
    logger.debug(f"🔁 Rotating RPC: Using endpoint {rpc}")
    return rpc


def add_rpc(rpc: str) -> bool:
    """Adds a new RPC endpoint to the list if it's not already present."""
    if rpc not in RPC_LIST:
        RPC_LIST.append(rpc)
        save_rpc_list()
        return True
    return False

def remove_rpc(rpc: str) -> bool:
    """Removes an RPC endpoint from the list if it exists."""
    if rpc in RPC_LIST:
        RPC_LIST.remove(rpc)
        save_rpc_list()
        return True
    return False

