import time
import re
import os
import urllib.request
import unicodedata
from datetime import datetime, timezone

# ─── CONFIG (READ FROM ENVIRONMENT - ZERO HARDCODED SECRETS) ──────────
PLAYLISTS_CONFIG = [
    {
        "env_var": "JSTAR_URL",
        "category": "JIO STAR"
    },
    {
        "env_var": "SONY_URL",
        "category": "SONYLIV"
    },
    {
        "env_var": "NONY_URL",
        "category": "SONYLIV - EVENTS"
    },
    {
        "env_var": "DIGITAL_TV_URL",
        "category": "Digital TV",
        "filter_category": "Digital", 
        "user_agent": "OTT Navigator"
    }
]

OUTPUT_FILE = "mixed_live.m3u"
RETRY_COUNT = 3
RETRY_DELAY = 5

OUTPUT_HEADER = os.environ.get("M3U_OUTPUT_HEADER", "#EXTM3U\n").strip() + "\n"

def fetch_url(url, user_agent="sktechtv", retries=RETRY_COUNT):
    if not url:
        return ""
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Cache-Control": "no-cache, no-store"
    }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    data = response.read().decode('utf-8').strip()
                    print(f"Fetched successfully on attempt {attempt}")
                    return data
                else:
                    print(f"Attempt {attempt}/{retries} failed: HTTP {response.status}")
        except Exception as e:
            print(f"Attempt {attempt}/{retries} failed: {e}")
        if attempt < retries:
            time.sleep(RETRY_DELAY)
    return ""

def process_playlist(raw_content, category, filter_category=None):
    lines = raw_content.splitlines()
    clean_lines = []
    keep_current = True
    
    for line in lines:
        s = line.strip()
        if not s: continue
        if s.upper().startswith("#EXTM3U"): continue
        if s.upper().startswith("##"): continue
        
        if s.upper().startswith("#EXTINF"):
            keep_current = True
            if filter_category:
                current_group_match = re.search(r'group-title="([^"]*)"', s, re.IGNORECASE)
                current_group = current_group_match.group(1) if current_group_match else ""
                norm_group = unicodedata.normalize('NFKD', current_group).lower()
                norm_filter = unicodedata.normalize('NFKD', filter_category).lower()
                if norm_filter not in norm_group:
                    keep_current = False
                    continue
            
            if 'group-title="' in s:
                s = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', s)
            else:
                s = re.sub(r',([^,]*)$', f' group-title="{category}",\\1', s)
            clean_lines.append(s)
        elif s.startswith("#"):
            if keep_current:
                clean_lines.append(s)
        else:
            if keep_current:
                clean_lines.append(s)
    return clean_lines

def write_plaintext(text):
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def main():
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"Run time: {current_time}")

    final_text = f"{OUTPUT_HEADER}\n# Last Auto-Updated: {current_time}\n\n"

    for pl in PLAYLISTS_CONFIG:
        url = os.environ.get(pl["env_var"], "").strip()
        if not url:
            print(f"No URL configured for {pl['category']} ({pl['env_var']}), skipping.")
            continue
        ua = pl.get("user_agent", "sktechtv")
        raw_content = fetch_url(url, user_agent=ua)
        if raw_content:
            filter_cat = pl.get("filter_category")
            processed_lines = process_playlist(raw_content, pl["category"], filter_cat)
            for line in processed_lines:
                final_text += line + "\n"
        else:
            print(f"Failed to fetch {pl['category']}, skipping.")

    write_plaintext(final_text)
    print(f"Successfully generated {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
