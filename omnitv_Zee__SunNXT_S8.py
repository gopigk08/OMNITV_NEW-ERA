import urllib.request
import urllib.error
import ssl
import sys
import time
import os
import re
from datetime import datetime, timezone

# ─── CONFIG (READ FROM ENVIRONMENT - ZERO HARDCODED SECRETS) ──────────
PLAYLISTS = [
    {
        "url": os.environ.get("SUNNXT_URL", "").strip(),
        "category": "SUNNXT"
    },
    {
        "url": os.environ.get("ZEE_URL", "").strip(),
        "category": "ZEE5"
    }
]

OUTPUT_FILE = "zsun.m3u"
RETRY_COUNT = 3
RETRY_DELAY = 5

OUTPUT_HEADER = os.environ.get("M3U_OUTPUT_HEADER", "#EXTM3U\n").strip() + "\n"

def fetch_url(url, retries=RETRY_COUNT):
    if not url:
        return ""
    headers = {
        "User-Agent": "",
        "Accept": "*/*",
        "Cache-Control": "no-cache, no-store"
    }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    data = response.read().decode('utf-8', errors='replace').strip()
                    print(f"Fetched successfully on attempt {attempt}")
                    return data
        except Exception as e:
            print(f"Attempt {attempt}/{retries} failed: {e}")
        if attempt < retries:
            time.sleep(RETRY_DELAY)
    return ""

def process_playlist(raw_content, category):
    lines = raw_content.splitlines()
    clean_lines = []
    for line in lines:
        s = line.strip()
        if not s or s.upper().startswith("#EXTM3U") or s.upper().startswith("##"):
            continue
        if s.upper().startswith("#EXTINF"):
            if 'group-title="' in s:
                s = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', s)
            else:
                s = re.sub(r',([^,]*)$', f' group-title="{category}",\\1', s)
            clean_lines.append(s)
        else:
            clean_lines.append(s)
    return clean_lines

def write_plaintext(text):
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def main():
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"Run time: {current_time}")

    final_text = f"{OUTPUT_HEADER}\n# Last Auto-Updated: {current_time}\n\n"

    for pl in PLAYLISTS:
        url = pl["url"]
        if not url:
            print(f"No URL set for {pl['category']}, skipping.")
            continue
        raw_content = fetch_url(url)
        if raw_content:
            processed_lines = process_playlist(raw_content, pl["category"])
            for line in processed_lines:
                final_text += line + "\n"
        else:
            print(f"Failed to fetch {pl['category']}, skipping.")

    write_plaintext(final_text)
    print(f"Successfully saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
