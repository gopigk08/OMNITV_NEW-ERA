import urllib.request
import urllib.error
import ssl
import sys
import time
import os
from datetime import datetime, timezone

# ─── CONFIG (READ FROM ENVIRONMENT - ZERO HARDCODED SECRETS) ──────────
WISPY_URL     = os.environ.get("CLOUDPLAY_MBJTV_URL", "").strip()
OUTPUT_FILE   = "gioplus.m3u"
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
        print("No WISPY_URL provided.")
        return ""
    ctx = make_ssl_ctx()
    req = urllib.request.Request(url, headers={
        "User-Agent": "OTT Navigator",
        "Accept": "*/*"
    })
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

    content = fetch_url(WISPY_URL)

    if not content:
        print("Fetch failed or no URL set. Writing keep-alive placeholder.")
        placeholder = f"{OUTPUT_HEADER}\n# Last Attempted: {current_time}\n# ERROR: Source unavailable. Will retry next run.\n"
        write_plaintext(placeholder)
        sys.exit(0)

    if content.startswith("#EXTM3U"):
        content = content.replace("#EXTM3U", "", 1)
        
    final_text = f"{OUTPUT_HEADER}\n# Last Auto-Updated: {current_time}\n{content}"
    
    write_plaintext(final_text)
    print(f"Successfully generated {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
