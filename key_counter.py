import json

DATA_FILE = "token.json"


with open(DATA_FILE, "r", encoding="utf-8") as f:
    reader = json.load(f)

# counter = 0
# for key in reader.keys():
#     counter +=1

# print(counter)
addr_list = []
for data in reader:
    token_address = data.get("tokenAddress")
    addr_list.append(token_address)

with open ("token_output.json", "w") as f:
    json.dump(addr_list, f, indent=2)
print(len(addr_list))