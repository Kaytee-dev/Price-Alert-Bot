# script to extract chatgpt conversation for exported data
import json

with open("part.json", "r") as file:
    loaded_data = json.load(file)
    chat_keys = loaded_data["mapping"].keys()
    
part_list = []

for key in chat_keys:
    value = loaded_data["mapping"][key]

    if value and isinstance(value, dict) and "message" in value:
        message = value["message"]
        if message and isinstance(message, dict) and "content" in message and "parts" in message["content"]:
            part = message["content"]["parts"]
    
            if part and "" not in part :
                #print(f"Checking part: {part[:50]}")
                part_list.append(part)

with open("output.json", "w") as file:
    json.dump(part_list, file, indent=4)

flat_list = [item for sublist in part_list for item in sublist]  # Flattens the nested lists
print(" ".join(flat_list)[:500])  # Prints the first 500 characters

