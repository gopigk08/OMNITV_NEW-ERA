import urllib.request
import urllib.error
import ssl
import sys
import time
import os
from datetime import datetime, timezone

# ─── CONFIG (READ FROM ENVIRONMENT - ZERO HARDCODED SECRETS) ──────────
FRESH_JIO_URL = os.environ.get("CLOUDPLAY_JIO_URL", "").strip()
OUTPUT_FILE   = "gio.m3u"
RETRY_COUNT   = 5
RETRY_DELAY   = 10

OUTPUT_HEADER = os.environ.get("M3U_OUTPUT_HEADER", "#EXTM3U\n").strip() + "\n"

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def fetch_url(url, retries=RETRY_COUNT):
    if not url:
        print("No FRESH_JIO_URL provided.")
        return ""
    ctx = make_ssl_ctx()
    req = urllib.request.Request(url, headers={"User-Agent": "sktechtv", "Accept": "*/*"})
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

def write_plaintext(text):
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def main():
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"Run time: {current_time}")

    jio_content = fetch_url(FRESH_JIO_URL)

    if not jio_content:
        print("Fetch failed or no URL set. Writing keep-alive placeholder.")
        placeholder = f"{OUTPUT_HEADER}\n# Last Attempted: {current_time}\n# ERROR: Source unavailable. Will retry next run.\n"
        write_plaintext(placeholder)
        sys.exit(0)

    jio_lines = []
    skip_current_channel = False
    
    for line in jio_content.splitlines():
        line_s = line.strip()
        if not line_s or line_s.upper().startswith("#EXTM3U"):
            continue
            
        if line_s.upper().startswith("#EXTINF"):
            if "CloudPlay" in line_s and "Jtv|General" in line_s:
                skip_current_channel = True
            else:
                skip_current_channel = False
                
        if skip_current_channel:
            continue
            
        jio_lines.append(line_s)

    print(f"Total lines after filtering: {len(jio_lines)}")

    final_text = f"{OUTPUT_HEADER}\n# Last Auto-Updated: {current_time}\n\n"
    for line in jio_lines:
        final_text += line + "\n"

    write_plaintext(final_text)
    print(f"Successfully generated {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
