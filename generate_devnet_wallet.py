from solana.keypair import Keypair
from base58 import b58encode
import qrcode
import json

# Generate new keypair
keypair = Keypair.generate()
public_key = str(keypair.public_key)
private_key = b58encode(keypair.seed).decode()
keypair_json = list(keypair.seed)

# Save keypair JSON (solana-keygen compatible)
with open("phantom_keypair.json", "w") as f:
    json.dump(keypair_json, f)

# Save public address
with open("phantom_address.txt", "w") as f:
    f.write(public_key)

# Save QR Code
img = qrcode.make(public_key)
img.save("phantom_address_qr.png")

print(f"✅ Public Key: {public_key}")
print(f"🔑 Private Key (base58): {private_key}")
