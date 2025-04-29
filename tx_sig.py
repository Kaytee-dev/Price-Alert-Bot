import requests
import json

def get_transfer_details(tx_signature):
    # JSON data for the request
    data = {
        "method": "getTransaction",
        "jsonrpc": "2.0",
        "id": "1",
        "params": [
            tx_signature,
            {"encoding": "jsonParsed", "commitment": "finalized"}
        ]
    }

    # Send the POST request
    response = requests.post(
        "https://api.mainnet-beta.solana.com",
        json=data,
        headers={"Content-Type": "application/json"}
    )

    # Process the response
    if response.status_code == 200:
        json_data = response.json()
        # if not json_data.get("result"):
        #     return {"receiver": None, "sender": None, "amount": None}
        
        # # Assuming the first instruction contains transfer details
        # instruction = json_data["result"]["transaction"]["message"]["instructions"]
        # info = instruction.get("parsed", {}).get("info", {})
        
        # return {
        #     "receiver": info.get("destination"),
        #     "sender": info.get("source"),
        #     "amount": info.get("lamports")
        #     }
        return json_data
    else:
        print(f"Error: Unable to fetch transaction details (Status Code: {response.status_code})")
        return None

def save_to_json(json_data, file_name):
    try:
        with open(file_name, 'w') as json_file:
            json.dump(json_data, json_file, indent=4)
        print(f"Data saved to {file_name}")
    except Exception as e:
        print(f"Error saving data: {e}")


if __name__ == "__main__":
    # Example transaction signature (replace with actual signature)
    transaction_signature = "LmHGHqWL8H8qwELkHSdCxP9FH8Sft5NKaYnzevvtNQtoRuZiMmtuXjKgZuDacz6dDbdbAaE3YedWGWs6cKt9wC4"
    
    # Get transfer details
    transfer_details = get_transfer_details(transaction_signature)
    #print(transfer_details)

    if transfer_details:
        # Save the fetched data to a JSON file
        save_to_json(transfer_details, "transaction_details.json")

