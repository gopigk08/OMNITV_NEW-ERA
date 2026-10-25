# language: Python, file: omnitv_main.py
import os
import sys
import json
import base64
import urllib.request
import ssl
import re
import glob
import shutil
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
# 3. M3U HEADER & EPG SOURCES (READ STRICTLY FROM SECRETS)
# ---------------------------------------------------------
EPG_URL    = os.environ.get("EPG_URL", "").strip()
raw_header = os.environ.get("M3U_OUTPUT_HEADER", "").strip()

def build_m3u_header():
    if raw_header and ("x-tvg-url" in raw_header or "url-tvg" in raw_header):
        return raw_header.rstrip() + "\n"
    elif EPG_URL:
        return f'#EXTM3U x-tvg-url="{EPG_URL}" url-tvg="{EPG_URL}"\n'
    elif raw_header:
        return raw_header.rstrip() + "\n"
    else:
        return "#EXTM3U\n"

OUTPUT_HEADER = build_m3u_header()
if EPG_URL:
    print("[Master EPG Engine] EPG successfully detected from Secrets and attached to Header.")
else:
    print("[Master EPG Engine] No EPG_URL secret provided. Default header applied.")

# ---------------------------------------------------------
# 4. PREPARE CLOUDFLARE DISTRIBUTION DIRECTORY
# ---------------------------------------------------------
DIST_DIR = "cloudflare_dist"
os.makedirs(DIST_DIR, exist_ok=True)

# ---------------------------------------------------------
# 5. PLAYLIST CONFIGURATION
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
# 6. ENCRYPT ALL PLAYLISTS INTO .enc FILES
# ---------------------------------------------------------
config_playlists = []
priority_counter = 1
all_master_channels = []
processed_sources = set()

for pl in PLAYLISTS_TO_PROCESS:
    print(f"Processing Playlist: {pl['name']} ({pl['id']})")
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
        processed_sources.add(os.path.basename(file_to_read).lower())
        
        with open(file_to_read, "r", encoding="utf-8", errors="replace") as f:
            raw_content = f.read()

        if file_to_read.endswith(".enc"):
            raw_m3u = decrypt_with_master_key(raw_content)
        else:
            raw_m3u = raw_content

        lines = raw_m3u.splitlines()
        while lines and (not lines[0].strip() or lines[0].strip().upper().startswith("#EXTM3U")):
            lines.pop(0)
            
        all_m3u = OUTPUT_HEADER + "\n".join(lines) + "\n"
        if "#EXTINF" in raw_m3u:
            has_channels = True
            all_master_channels.extend(lines)
    else:
        print(f"  -> Source file not found: {target_file}")
        all_m3u = OUTPUT_HEADER
            
    if not has_channels:
        print(f"  -> No channels found for {pl['name']}. Fallback to dummy data.")
        all_m3u += '#EXTINF:-1,No Channels Available\n#placeholder\n'
        
    output_filename = f"playlist_{pl['id']}.enc"
    encrypted_data = encrypt_with_session_key(all_m3u)
    with open(os.path.join(DIST_DIR, output_filename), "w", encoding="utf-8") as f:
        f.write(encrypted_data)
    print(f"  -> [Cloudflare Output] Saved {output_filename}")
    
    # ALSO save with original base filename (e.g. helloworld.enc, gio.enc)
    if target_file:
        base_target = os.path.splitext(os.path.basename(target_file))[0]
        alt_enc_name = f"{base_target}.enc"
        if alt_enc_name != output_filename:
            with open(os.path.join(DIST_DIR, alt_enc_name), "w", encoding="utf-8") as f:
                f.write(encrypted_data)
            print(f"  -> [Cloudflare Output] Also saved {alt_enc_name}")

    config_playlists.append({
        "id": pl["id"],
        "name": pl["name"],
        "url": output_filename,
        "priority": priority_counter
    })
    priority_counter += 1

# ---------------------------------------------------------
# 7. ENCRYPT ANY REMAINING .m3u FILES INTO cloudflare_dist/*.enc
# ---------------------------------------------------------
for m3u_path in glob.glob("*.m3u"):
    m3u_base = os.path.basename(m3u_path)
    if m3u_base.lower() in processed_sources:
        continue
        
    print(f"Processing Additional Local File: {m3u_base}")
    try:
        with open(m3u_path, "r", encoding="utf-8", errors="replace") as f:
            raw_content = f.read()
            
        lines = raw_content.splitlines()
        while lines and (not lines[0].strip() or lines[0].strip().upper().startswith("#EXTM3U")):
            lines.pop(0)
            
        full_m3u = OUTPUT_HEADER + "\n".join(lines) + "\n"
        out_name = f"{os.path.splitext(m3u_base)[0]}.enc"
        encrypted_blob = encrypt_with_session_key(full_m3u)
        
        with open(os.path.join(DIST_DIR, out_name), "w", encoding="utf-8") as f:
            f.write(encrypted_blob)
        print(f"  -> [Cloudflare Output] Encrypted {m3u_base} -> {out_name}")
    except Exception as e:
        print(f"  -> Warning: failed to encrypt {m3u_base}: {e}")

# ---------------------------------------------------------
# 8. BUILD & ENCRYPT MASTER 'all.enc' (ALL CHANNELS UNIFIED)
# ---------------------------------------------------------
if all_master_channels:
    master_m3u = OUTPUT_HEADER + "\n".join(all_master_channels) + "\n"
    encrypted_master = encrypt_with_session_key(master_m3u)
    with open(os.path.join(DIST_DIR, "all.enc"), "w", encoding="utf-8") as f:
        f.write(encrypted_master)
    print("  -> [Cloudflare Output] Saved unified master 'all.enc'")

# ---------------------------------------------------------
# 9. BUILD & ENCRYPT UNIFIED REMOTE CONFIG
# ---------------------------------------------------------
remote_config = {
    "playlists": config_playlists
}
if EPG_URL:
    remote_config["epgUrl"] = EPG_URL
    remote_config["epg_url"] = EPG_URL

print("Encrypting unified remote_config.enc...")
with open(os.path.join(DIST_DIR, "remote_config.enc"), "w", encoding="utf-8") as f:
    f.write(encrypt_with_session_key(json.dumps(remote_config)))

print("Encrypting and exporting session_token.enc...")
with open(os.path.join(DIST_DIR, "session_token.enc"), "w", encoding="utf-8") as f:
    f.write(encrypt_session_key())

# ---------------------------------------------------------
# 10. COPY index.html & PURGE UNENCRYPTED .m3u FROM DIST
# ---------------------------------------------------------
if os.path.exists("index.html"):
    shutil.copy("index.html", os.path.join(DIST_DIR, "index.html"))

# STRICT SECURITY: Delete any raw .m3u files in dist so NO plaintext streams are exposed!
for raw_m3u in glob.glob(os.path.join(DIST_DIR, "*.m3u")):
    os.remove(raw_m3u)

print("\n" + "="*60)
print(f"SUCCESS! All files encrypted and placed in '{DIST_DIR}/'.")
print("Files ready to deploy to Cloudflare Pages (https://omnitv-live.pages.dev/):")
for f in sorted(os.listdir(DIST_DIR)):
    print(f"  - {f}")
print("="*60)
