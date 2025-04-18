# utils.py
import json
import logging

def load_json(file_path: str, fallback, log_label: str = ""):
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            logging.info(f"📂 Loaded {log_label or file_path}.")
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info(f"📂 No valid {log_label or file_path} found. Starting fresh.")
        return fallback.copy() if isinstance(fallback, dict) else list(fallback)

def save_json(file_path: str, data, log_label: str = ""):
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        logging.info(f"💾 Saved {log_label or file_path}.")
    except Exception as e:
        logging.error(f"❌ Failed to save {log_label or file_path}: {e}")



# # --- Generic JSON Utilities ---
# def load_json(file_path: str, fallback, log_label: str = ""):
#     try:
#         with open(file_path, "r") as f:
#             data = json.load(f)
#             logging.info(f"📂 Loaded {log_label or file_path}.")
#             return data
#     except (FileNotFoundError, json.JSONDecodeError):
#         logging.info(f"📂 No valid {log_label or file_path} found. Starting fresh.")
#         return fallback.copy() if isinstance(fallback, dict) else list(fallback)

# def save_json(file_path: str, data, log_label: str = ""):
#     try:
#         with open(file_path, "w") as f:
#             json.dump(data, f, indent=2)
#         logging.info(f"💾 Saved {log_label or file_path}.")
#     except Exception as e:
#         logging.error(f"❌ Failed to save {log_label or file_path}: {e}")
