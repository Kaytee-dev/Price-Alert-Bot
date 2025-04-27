import json

DATA_FILE = "main_folder/storage/data/active_tokens.json"

with open(DATA_FILE, "r") as f:
    reader = json.load(f)

counter = 0
for key in reader.keys():
    counter +=1

print(counter)
