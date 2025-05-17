import aiohttp
import asyncio

SOLANA_DEVNET = "https://api.devnet.solana.com"

async def airdrop_sol(address: str, amount: int = 1):
    """Request an airdrop to the specified devnet wallet."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "requestAirdrop",
        "params": [address, amount * 10**9]  # lamports
    }

    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(SOLANA_DEVNET, headers=headers, json=payload) as resp:
            result = await resp.json()
            print("✅ Airdrop Result:", result)

if __name__ == "__main__":
    wallet = input("Enter your devnet wallet address: ").strip()
    asyncio.run(airdrop_sol(wallet, amount=2))
