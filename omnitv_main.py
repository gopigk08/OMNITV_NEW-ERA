import os
import sys
import json
import base64
import urllib.request
import ssl
import re
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

# ---------------------------------------------------------
# 1. READ MASTER KEY & IV FROM SECRETS (NO EXPOSED BYTES)
# ---------------------------------------------------------
MASTER_KEY_HEX = os.environ.get('OMNI_MASTER_KEY')
MASTER_IV_HEX  = os.environ.get('OMNI_MASTER_IV')

if not MASTER_KEY_HEX:
    raise ValueError("CRITICAL: OMNI_MASTER_KEY environment variable is not set!")
if not MASTER_IV_HEX:
    raise ValueError("CRITICAL: OMNI_MASTER_IV environment variable is not set!")

MASTER_KEY = bytes.fromhex(MASTER_KEY_HEX.strip())
MASTER_IV  = bytes.fromhex(MASTER_IV_HEX.strip())

def decrypt_with_master_key(encrypted_b64):
    """Decrypts local repository .enc files using the Master Key."""
    try:
        raw_ct = base64.b64decode(encrypted_b64.strip())
        cipher = Cipher(algorithms.AES(MASTER_KEY), modes.CBC(MASTER_IV), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(raw_ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Error decrypting local enc file: {e}")
        return ""

# ---------------------------------------------------------
# 2. GENERATE ROTATING SESSION KEY (Changes every run)
# ---------------------------------------------------------
SESSION_KEY = os.urandom(32)
SESSION_IV = os.urandom(16)

def encrypt_with_session_key(data_string):
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data_string.encode('utf-8')) + padder.finalize()
    cipher = Cipher(algorithms.AES(SESSION_KEY), modes.CBC(SESSION_IV), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(SESSION_IV + ct).decode('utf-8')

def encrypt_session_key():
    payload = base64.b64encode(SESSION_KEY + SESSION_IV).decode('utf-8')
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(payload.encode('utf-8')) + padder.finalize()
    cipher = Cipher(algorithms.AES(MASTER_KEY), modes.CBC(MASTER_IV), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(ct).decode('utf-8')

# ---------------------------------------------------------
# 3. M3U HEADER & EPG SOURCES
# ---------------------------------------------------------
OUTPUT_HEADER = os.environ.get("M3U_OUTPUT_HEADER", "#EXTM3U\n").strip() + "\n"

# ---------------------------------------------------------
# 4. PLAYLIST CONFIGURATION
# ---------------------------------------------------------
PLAYLISTS_TO_PROCESS = [
    {
        "id": "main",
        "name": "S1-JIO TV",
        "local_file": "gio.m3u"
    },
    {
        "id": "backup",
        "name": "S2-JIO TV+",
        "local_file": "gioplus.m3u"
    },
    {
        "id": "only_4K",
        "name": "S3-STAR SHARE",
        "local_file": "star_share.enc",
        "fallback_file": "star_share.m3u"
    },
    {
        "id": "server4",
        "name": "S4-ONLY-TELUGU",
        "local_file": "helloworld.m3u"
    },
    {
        "id": "server5",
        "name": "S5-ALL MIX",
        "local_file": "All_Mix_S5.enc",
        "fallback_file": "All_Mix_S5.enc"
    },
    {
        "id": "server6",
        "name": "S6-FANCODE LIVE",
        "local_file": "fcliv.m3u"
    },
    {
        "id": "server7",
        "name": "S7-JIOSTAR - SONYLIV",
        "local_file": "mixed_live.m3u"
    },
    {
        "id": "server8",
        "name": "S8-SUNNXT - ZEE5",
        "local_file": "zsun.m3u"
    }
]

# ---------------------------------------------------------
# 5. FETCH, PARSE, ENCRYPT, & ASSEMBLE
# ---------------------------------------------------------
os.makedirs("cloudflare_dist", exist_ok=True)
config_playlists = []
priority_counter = 1

for pl in PLAYLISTS_TO_PROCESS:
    print(f"Processing Playlist: {pl['name']} ({pl['id']})")
    all_m3u = OUTPUT_HEADER
    has_channels = False
    
    target_file = pl.get("local_file")
    fallback = pl.get("fallback_file")
    
    file_to_read = None
    if target_file and os.path.exists(target_file):
        file_to_read = target_file
    elif fallback and os.path.exists(fallback):
        file_to_read = fallback

    if file_to_read:
        print(f"  -> Reading source from: {file_to_read}")
        with open(file_to_read, "r", encoding="utf-8", errors="replace") as f:
            raw_content = f.read()

        if file_to_read.endswith(".enc"):
            raw_m3u = decrypt_with_master_key(raw_content)
        else:
            raw_m3u = raw_content

        lines = raw_m3u.splitlines()
        if lines and lines[0].strip().upper().startswith("#EXTM3U"):
            lines = lines[1:]
            
        all_m3u += "\n".join(lines) + "\n"
        if "#EXTINF" in raw_m3u:
            has_channels = True
    else:
        print(f"  -> Source file not found: {target_file}")
            
    if not has_channels:
        print(f" -> No channels found for {pl['name']}. Fallback to dummy data.")
        all_m3u += '#EXTINF:-1,No Channels Available\n#placeholder\n'
        
    output_filename = f"playlist_{pl['id']}.enc"
    print(f" -> Encrypting with Session Key -> {output_filename}")
    
    encrypted_data = encrypt_with_session_key(all_m3u)
    with open(os.path.join("cloudflare_dist", output_filename), "w", encoding="utf-8") as f:
        f.write(encrypted_data)
        
    config_playlists.append({
        "id": pl["id"],
        "name": pl["name"],
        "url": output_filename,
        "priority": priority_counter
    })
    priority_counter += 1

# ---------------------------------------------------------
# 6. BUILD & ENCRYPT UNIFIED REMOTE CONFIG
# ---------------------------------------------------------
remote_config = {
    "playlists": config_playlists
}

print("Encrypting unified config...")
with open("cloudflare_dist/remote_config.enc", "w", encoding="utf-8") as f:
    f.write(encrypt_with_session_key(json.dumps(remote_config)))

print("Encrypting and exporting Session Token...")
with open("cloudflare_dist/session_token.enc", "w", encoding="utf-8") as f:
    f.write(encrypt_session_key())

print("SUCCESS! All files generated in 'cloudflare_dist/'.")
print(f"Total playlists processed: {len(config_playlists)}")
