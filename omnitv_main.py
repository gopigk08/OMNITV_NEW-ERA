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

# ---------------------------------------------------------
# 4. PREPARE CLOUDFLARE DISTRIBUTION DIRECTORY
# ---------------------------------------------------------
DIST_DIR = "cloudflare_dist"
if os.path.exists(DIST_DIR):
    # Clean previous build to prevent leftover unwanted files
    shutil.rmtree(DIST_DIR)
os.makedirs(DIST_DIR, exist_ok=True)

# ---------------------------------------------------------
# 5. PLAYLIST CONFIGURATION (CANONICAL OMNITV SERVERS S1 - S8)
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
# 6. PROCESS & ENCRYPT PLAYLISTS (EXACTLY 1 ENCRYPTED FILE PER SERVER)
# ---------------------------------------------------------
print("=" * 70)
print("              OmniTV Cloudflare Master Deployer")
print("=" * 70)
if EPG_URL:
    print("[EPG Engine] ✅ EPG Attached: [PROTECTED ENDPOINT]")
else:
    print("[EPG Engine] ⚠️ No EPG_URL secret provided. Default header applied.")

config_playlists = []
report_summary = []
priority_counter = 1

for pl in PLAYLISTS_TO_PROCESS:
    target_file = pl.get("local_file")
    fallback = pl.get("fallback_file")
    
    file_to_read = None
    if target_file and os.path.exists(target_file):
        file_to_read = target_file
    elif fallback and os.path.exists(fallback):
        file_to_read = fallback

    channel_count = 0
    status_str = ""

    if file_to_read:
        with open(file_to_read, "r", encoding="utf-8", errors="replace") as f:
            raw_content = f.read()

        if file_to_read.endswith(".enc"):
            raw_m3u = decrypt_with_master_key(raw_content)
        else:
            raw_m3u = raw_content

        channel_count = raw_m3u.count("#EXTINF:")

        lines = raw_m3u.splitlines()
        # Cleanly strip leading empty lines and any existing #EXTM3U
        while lines and (not lines[0].strip() or lines[0].strip().upper().startswith("#EXTM3U")):
            lines.pop(0)

        all_m3u = OUTPUT_HEADER + "\n".join(lines) + "\n"
        status_str = f"✅ OK ({channel_count:,} channels)" if channel_count > 0 else "❌ FAILED (0 channels - Empty)"
    else:
        status_str = f"❌ FAILED (File '{target_file}' not found)"
        all_m3u = OUTPUT_HEADER

    if channel_count == 0:
        # Fallback dummy placeholder to maintain valid M3U structure
        all_m3u += '#EXTINF:-1 tvg-id="" tvg-name="No Channels",No Channels Available\n#placeholder\n'

    # Output strictly as playlist_<id>.enc
    output_filename = f"playlist_{pl['id']}.enc"
    encrypted_data = encrypt_with_session_key(all_m3u)
    with open(os.path.join(DIST_DIR, output_filename), "w", encoding="utf-8") as f:
        f.write(encrypted_data)

    config_playlists.append({
        "id": pl["id"],
        "name": pl["name"],
        "url": output_filename,
        "priority": priority_counter
    })

    report_summary.append({
        "num": priority_counter,
        "name": pl["name"],
        "source": file_to_read or str(target_file),
        "output": output_filename,
        "channels": channel_count,
        "status": status_str
    })
    priority_counter += 1

# ---------------------------------------------------------
# 7. BUILD & ENCRYPT UNIFIED REMOTE CONFIG
# ---------------------------------------------------------
remote_config = {
    "playlists": config_playlists
}
if EPG_URL:
    remote_config["epgUrl"] = EPG_URL
    remote_config["epg_url"] = EPG_URL

with open(os.path.join(DIST_DIR, "remote_config.enc"), "w", encoding="utf-8") as f:
    f.write(encrypt_with_session_key(json.dumps(remote_config)))

# ---------------------------------------------------------
# 8. EXPORT ENCRYPTED SESSION TOKEN
# ---------------------------------------------------------
with open(os.path.join(DIST_DIR, "session_token.enc"), "w", encoding="utf-8") as f:
    f.write(encrypt_session_key())

# ---------------------------------------------------------
# 9. COPY index.html IF PRESENT
# ---------------------------------------------------------
if os.path.exists("index.html"):
    shutil.copy("index.html", os.path.join(DIST_DIR, "index.html"))

# ---------------------------------------------------------
# 10. GENERATE CLEAN REPORT & DIAGNOSTICS DASHBOARD
# ---------------------------------------------------------
print("\n" + "=" * 70)
print("                   OmniTV Deployment Summary")
print("=" * 70)
print(f"{'#':<3} {'Server Name':<23} {'Channels':<12} {'Status'}")
print("-" * 70)

has_failures = False
for item in report_summary:
    ch_text = f"{item['channels']:,}" if item['channels'] > 0 else "0"
    print(f"{item['num']:<3} {item['name']:<23} {ch_text:<12} {item['status']}")
    if item['channels'] == 0:
        has_failures = True

print("-" * 70)
if has_failures:
    print("⚠️  DIAGNOSTICS / ISSUES DETECTED:")
    for item in report_summary:
        if item['channels'] == 0:
            print(f"   -> [{item['name']}]: Source '{item['source']}' is empty or missing.")
            print(f"      Check if secret URL or syncer script failed for {item['name']}.")
print("-" * 70)

dist_files = sorted(os.listdir(DIST_DIR))
print(f"📦 Files Ready to Deploy to Cloudflare Pages ({len(dist_files)} total):")
for f in dist_files:
    size = os.path.getsize(os.path.join(DIST_DIR, f))
    print(f"   • {f:<25} ({size:,} bytes)")
print("=" * 70)
