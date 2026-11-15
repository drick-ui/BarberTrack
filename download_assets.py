"""Download the front-end libraries (Bootstrap, icons, fonts) once, so the system works WITHOUT internet.

Run this once while you are online:   python download_assets.py
The files are saved in static/vendor/. When they exist, the pages use them instead of the CDN."""
import re
import sys
import urllib.request
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "static" / "vendor"
CDN = "https://cdn.jsdelivr.net/npm"
FILES = {
    "bootstrap/bootstrap.min.css": f"{CDN}/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    "bootstrap/bootstrap.bundle.min.js": f"{CDN}/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    "bootstrap-icons/bootstrap-icons.min.css": f"{CDN}/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    "bootstrap-icons/fonts/bootstrap-icons.woff2": f"{CDN}/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2",
    "bootstrap-icons/fonts/bootstrap-icons.woff": f"{CDN}/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff",
}
GOOGLE_FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
                "&family=Playfair+Display:wght@600;700&display=swap")
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def fetch(url, user_agent=BROWSER):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def save(relative_path, data):
    target = VENDOR / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def localize_font_css(css, download):
    """Replace every remote font URL in a Google Fonts stylesheet with a local file name.
    `download(url)` must return the file's bytes. Returns (new_css, {filename: bytes})."""
    files = {}

    def replace(match):
        url = match.group(1)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/")[-1])
        if name not in files:
            files[name] = download(url)
        return f"url({name})"

    return re.sub(r"url\((https://[^)]+)\)", replace, css), files


def main():
    failed = []
    for relative_path, url in FILES.items():
        try:
            save(relative_path, fetch(url))
            print(f"  ok      {relative_path}")
        except Exception as e:
            failed.append(relative_path)
            print(f"  FAILED  {relative_path}: {e}")
    try:  # the web fonts are optional: without them the system fonts are used
        css, font_files = localize_font_css(fetch(GOOGLE_FONTS).decode("utf-8"), fetch)
        for name, data in font_files.items():
            save(f"fonts/{name}", data)
        save("fonts/fonts.css", css.encode("utf-8"))
        print(f"  ok      fonts ({len(font_files)} files)")
    except Exception as e:
        print(f"  skipped fonts (optional): {e}")
    if failed:
        print("\nSome required files could not be downloaded. Check your internet and run this again.")
        sys.exit(1)
    print("\nDone. Restart the app. The system now works without internet.")


if __name__ == "__main__":
    main()
