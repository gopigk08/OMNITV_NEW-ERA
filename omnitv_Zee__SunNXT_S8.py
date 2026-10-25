import urllib.request
import urllib.error
import ssl
import sys
import time
import os
import re
from datetime import datetime, timezone

# â”€â”€â”€ CONFIG â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PLAYLISTS = [
    {
        "url": "https://raw.githubusercontent.com/alexandermail371/cricfytv/refs/heads/main/sunxt.m3u",
        "category": "SUNNXT"
    },
    {
        "url": "https://cloudplay-app-json.pages.dev/pro-raw-files/zee5.m3u",
        "category": "ZEE5"
    }
]

OUTPUT_FILE = "zsun.m3u"
RETRY_COUNT = 3
RETRY_DELAY = 5

OUTPUT_HEADER = os.environ.get("M3U_OUTPUT_HEADER", "#EXTM3U\n").strip() + "\n"
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def fetch_url(url, retries=RETRY_COUNT):
    print(f"Fetching: {url}")
    ctx = make_ssl_ctx()
    # ZEE5 usually requires sktechtv user-agent to bypass cloudflare/auth
    req = urllib.request.Request(url, headers={"User-Agent": "sktechtv", "Accept": "*/*"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                if data.strip():
                    print(f"âœ… Fetched successfully on attempt {attempt}")
                    return data
        except Exception as e:
            print(f"âš ï¸ Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)
    return ""

def process_playlist(raw_content, category):
    lines = raw_content.splitlines()
    clean_lines = []
    for line in lines:
        s = line.strip()
        if not s: continue
        if s.upper().startswith("#EXTM3U"): continue
        if s.upper().startswith("##"): continue
        
        # If it's an EXTINF line, overwrite or inject group-title
        if s.upper().startswith("#EXTINF"):
            if 'group-title="' in s:
                s = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', s)
            else:
                # Insert before the last comma
                s = re.sub(r',([^,]*)$', f' group-title="{category}",\\1', s)
        
        clean_lines.append(s)
    return clean_lines

def write_plaintext(text):
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def main():
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"ðŸ• Run time: {current_time}")

    final_text = f"{OUTPUT_HEADER}\n# Last Auto-Updated: {current_time}\n\n"

    for pl in PLAYLISTS:
        raw_content = fetch_url(pl["url"])
        if raw_content:
            processed_lines = process_playlist(raw_content, pl["category"])
            for line in processed_lines:
                final_text += line + "\n"
        else:
            print(f"âš ï¸ Failed to fetch {pl['category']}, skipping.")

    write_plaintext(final_text)
    print(f"âœ… Successfully extracted, modified categories, and saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
