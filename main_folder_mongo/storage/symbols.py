from util.utils import load_json, save_json
from config import SYMBOLS_FILE
from typing import Dict

ADDRESS_TO_SYMBOL: Dict[str, str] = {}

def load_symbols_from_file():
    global ADDRESS_TO_SYMBOL
    ADDRESS_TO_SYMBOL = load_json(SYMBOLS_FILE, {}, "symbols")

def save_symbols_to_file():
    save_json(SYMBOLS_FILE, ADDRESS_TO_SYMBOL, "symbols")
