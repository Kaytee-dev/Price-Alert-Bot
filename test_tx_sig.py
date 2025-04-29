import aiohttp
import asyncio
from datetime import datetime

SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"
SOL_DECIMALS = 9

async def test_fetch_transaction(tx_sig):
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [tx_sig, {"encoding": "jsonParsed"}]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(SOLANA_MAINNET_RPC, headers=headers, json=payload) as resp:
            data = await resp.json()

    transaction = data.get("result")
    if not transaction:
        print("❌ Could not find transaction on-chain. Check your hash.")
        return

    print("✅ Transaction fetched successfully.")

    block_time = transaction.get("blockTime")
    if block_time:
        timestamp = datetime.fromtimestamp(block_time)
        print(f"⏱️ Block Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

    # Extract sender pubkey from accountKeys list
    message = transaction["transaction"]["message"]
    account_keys = message.get("accountKeys", [])
    sender_pubkey = next((acc.get("pubkey") for acc in account_keys if isinstance(acc, dict) and acc.get("signer")), "N/A")
    print(f"📤 Sender: {sender_pubkey}")

    print("--- Instructions ---")
    instructions = message["instructions"]
    for instr in instructions:
        parsed = instr.get("parsed", {})
        if parsed.get("type") == "transfer":
            info = parsed.get("info", {})
            dest = info.get("destination")
            lamports = int(info.get("lamports", 0))
            sol_amount = lamports / 10**SOL_DECIMALS

            print(f"Transfer to: {dest}, Amount: {sol_amount} SOL")

if __name__ == "__main__":
    test_sig = input("Enter a Solana transaction hash: ").strip()
    asyncio.run(test_fetch_transaction(test_sig))
