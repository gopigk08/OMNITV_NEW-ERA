import urllib.request
import urllib.error
import re
import ssl
import sys
import time
import os
import unicodedata
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

# ─── CONFIG (READ FROM ENVIRONMENT - ZERO HARDCODED SECRETS) ──────────
CLOUDPLAY_URL = os.environ.get("CLOUDPLAY_JIO_URL", "").strip()
ZEE_URL       = os.environ.get("ZEE_URL", "").strip()
TVTELUGU_URL  = os.environ.get("TVTELUGU_MADHU_URL", "").strip()

TEMP_ENC_FILE = "template.enc"
TEMP_M3U_FILE = "template.m3u"
LOCAL_FILE    = "Tel_Local.enc"
OUTPUT_FILE   = "helloworld.m3u"

RETRY_COUNT   = 5
RETRY_DELAY   = 10

OUTPUT_HEADER = os.environ.get("M3U_OUTPUT_HEADER", "#EXTM3U\n").strip() + "\n"
ZEE_CHANNELS_TO_SKIP = {"zee telugu hd", "zee cinemalu hd", "zee telugu", "zee cinemalu"}

def get_master_crypto():
    hex_key = os.environ.get("OMNI_MASTER_KEY", "").strip()
    if not hex_key:
        return None, None
    try:
        key = bytes.fromhex(hex_key)
        iv = b'Tv#9_X2bL4pM1kF7'
        return key, iv
    except Exception:
        return None, None

def decrypt_payload(b64_str):
    key, iv = get_master_crypto()
    if not key:
        return ""
    try:
        raw_ct = base64.b64decode(b64_str.strip())
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        padded = cipher.decryptor().update(raw_ct) + cipher.decryptor().finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Decryption error: {e}")
        return ""

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def fetch_url(url, retries=RETRY_COUNT):
    if not url:
        return ""
    ctx = make_ssl_ctx()
    ua = "OTT Navigator IPTV/1.6.7.4 (Linux; Android 11)" if "tvtelugu" in url else "sktechtv"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                if data.strip():
                    print(f"Fetched successfully on attempt {attempt}")
                    return data
        except Exception as e:
            print(f"Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)
    return ""

def is_any_url(line):
    s = line.strip()
    if s.startswith("http") or s.startswith("rtmp"): return True
    if s.startswith("#http") or s.startswith("#rtmp"): return True
    if s.startswith("# backup: http"): return True
    return False

def parse_source_into_blocks(content):
    lines = [l.rstrip() for l in content.splitlines()]
    blocks = []
    url_indices = [i for i, line in enumerate(lines) if is_any_url(line)]
    last_claimed_idx = -1
    for idx in url_indices:
        url_line = lines[idx].strip()
        if url_line.startswith("# backup: "):
            url_line = url_line.replace("# backup: ", "", 1)
        elif url_line.startswith("#http") or url_line.startswith("#rtmp"):
            url_line = url_line[1:]
            
        ua_line = None
        if "|" in url_line:
            parts = url_line.split("|")
            url_line = parts[0]
            for param in parts[1:]:
                if param.startswith("User-Agent="):
                    ua = param.split("=", 1)[1]
                    ua_line = f"#EXTVLCOPT:http-user-agent={ua}"
            
        block_lines = [url_line]
        if ua_line:
            block_lines.insert(0, ua_line)
            
        extinf_found = False
        for j in range(idx - 1, last_claimed_idx, -1):
            line = lines[j]
            if not line.strip(): continue
            if line.upper().startswith("#EXTM3U"): continue
            if line.upper().startswith("#EXTINF"):
                if extinf_found:
                    break
                extinf_found = True
            block_lines.insert(0, line)
            
        if extinf_found:
            blocks.append(block_lines)
        last_claimed_idx = idx
        
    return blocks

def normalize_text(text):
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower().strip()

def get_channel_name(extinf_line):
    parts = extinf_line.split(",")
    return parts[-1].strip() if len(parts) > 1 else ""

def set_group_title_telugu(extinf_line):
    line = re.sub(r'group-title="[^"]*"', '', extinf_line).strip()
    line = re.sub(r'\s+', ' ', line)
    line = re.sub(r',([^,]*)$', r' group-title="Telugu",\1', line)
    return line

def parse_temp_order():
    content = ""
    if os.path.exists(TEMP_ENC_FILE):
        print(f"Reading template from {TEMP_ENC_FILE}...")
        with open(TEMP_ENC_FILE, "r", encoding="utf-8") as f:
            content = decrypt_payload(f.read())
    elif os.path.exists(TEMP_M3U_FILE):
        print(f"Reading template from {TEMP_M3U_FILE}...")
        with open(TEMP_M3U_FILE, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    else:
        print("Template file not found.")
        return []

    names = []
    for line in content.splitlines():
        if re.match(r'#\s*EXTINF', line.strip(), re.IGNORECASE):
            name = get_channel_name(line)
            if name:
                names.append(normalize_text(name))
    return names

def build_dict(blocks):
    d = {}
    for b in blocks:
        extinf = next((l for l in b if l.upper().startswith("#EXTINF")), "")
        name = normalize_text(get_channel_name(extinf))
        if name and name not in d:
            d[name] = b
    return d

def main():
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"Run time: {current_time}")

    temp_order = parse_temp_order()
    print(f"Found {len(temp_order)} channels in template for ordering")

    cloudplay_content = fetch_url(CLOUDPLAY_URL)
    zee_content = fetch_url(ZEE_URL)
    tvtelugu_content = fetch_url(TVTELUGU_URL)

    cloudplay_blocks = parse_source_into_blocks(cloudplay_content) if cloudplay_content else []
    zee_blocks = parse_source_into_blocks(zee_content) if zee_content else []
    tvtelugu_blocks = parse_source_into_blocks(tvtelugu_content) if tvtelugu_content else []

    cp_dict = build_dict(cloudplay_blocks)
    zee_dict = build_dict(zee_blocks)
    tt_dict = build_dict(tvtelugu_blocks)

    extracted_channels = {}
    found_count = 0

    for name in temp_order:
        selected_block = None
        if name in ZEE_CHANNELS_TO_SKIP:
            if name in zee_dict:
                selected_block = zee_dict[name]
            elif name in tt_dict:
                selected_block = tt_dict[name]
        else:
            if name in cp_dict:
                selected_block = cp_dict[name]
            elif name in tt_dict:
                selected_block = tt_dict[name]

        if selected_block:
            new_block = []
            for line in selected_block:
                if line.upper().startswith("#EXTINF"):
                    new_block.append(set_group_title_telugu(line))
                else:
                    new_block.append(line)
            extracted_channels[name] = new_block
            found_count += 1

    print(f"Extracted {found_count} channels out of {len(temp_order)} from template.")

    gk_content = ""
    try:
        local_src = LOCAL_FILE if os.path.exists(LOCAL_FILE) else "Tel_Local.enc"
        if os.path.exists(local_src):
            with open(local_src, 'r', encoding='utf-8') as f:
                raw_gk = f.read()
            if local_src.endswith(".enc"):
                gk_content = decrypt_payload(raw_gk)
            else:
                gk_content = raw_gk
            print(f"Successfully read local GK source from {local_src}.")
    except Exception as e:
        print(f"Could not read local GK source: {e}")

    gk_blocks = parse_source_into_blocks(gk_content) if gk_content else []
    print(f"Local source: {len(gk_blocks)} blocks found")

    if not extracted_channels and not gk_blocks:
        print("All sources failed! Writing keep-alive placeholder.")
        final_text = f"{OUTPUT_HEADER}\n# Last Attempted: {current_time}\n# ERROR: Sources unavailable. Will retry next run.\n"
    else:
        final_text = f"{OUTPUT_HEADER}\n# Last Auto-Updated: {current_time}\n\n"
        for name in temp_order:
            if name in extracted_channels:
                for line in extracted_channels[name]:
                    final_text += line + "\n"
        for block in gk_blocks:
            for line in block:
                final_text += line + "\n"

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
            f.write(final_text)
        print(f"Successfully generated {OUTPUT_FILE}")
    except Exception as e:
        print(f"Error writing output file: {e}")

if __name__ == "__main__":
    main()
