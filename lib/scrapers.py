import json
import re
import time
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

from lib.constants import IMAGE_EXTENSIONS

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
_ua_index = 0


def _headers() -> dict:
    global _ua_index
    ua = _USER_AGENTS[_ua_index % len(_USER_AGENTS)]
    _ua_index += 1
    return {"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"}


def _get_with_backoff(url: str, timeout: int = 15) -> Optional[requests.Response]:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_headers(), timeout=timeout)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            return resp
        except requests.RequestException:
            if attempt == 2:
                return None
            time.sleep(2 ** attempt)
    return None


def download_image(url: str, dest_path: str) -> dict:
    resp = requests.get(url, headers=_headers(), timeout=30, stream=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if not (content_type.startswith("image/") or content_type == "application/octet-stream"):
        raise ValueError(f"Unexpected content-type: {content_type}")
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(65536):
            f.write(chunk)
    return {
        "url": url,
        "http_status": resp.status_code,
        "domain": urllib.parse.urlparse(url).netloc,
        "response_headers": {
            "content-type": content_type,
            "last-modified": resp.headers.get("last-modified"),
            "content-length": resp.headers.get("content-length"),
            "etag": resp.headers.get("etag"),
            "tdm-reservation": resp.headers.get("tdm-reservation"),
        },
    }


def scrape_page_metadata(page_url: str) -> dict:
    resp = _get_with_backoff(page_url)
    if resp is None or not resp.ok:
        return {"scrape_error": f"HTTP {resp.status_code if resp else 'failed'}"}

    soup = BeautifulSoup(resp.text, "lxml")
    meta: dict = {}

    # OpenGraph
    og = {t.get("property"): t.get("content")
          for t in soup.find_all("meta", property=re.compile(r"^og:"))
          if t.get("content")}
    if og:
        meta["opengraph"] = og

    # Schema.org JSON-LD — flatten @graph arrays
    jsonld: list = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, dict) and "@graph" in data:
                jsonld.extend(data["@graph"])
            elif isinstance(data, list):
                jsonld.extend(data)
            else:
                jsonld.append(data)
        except (json.JSONDecodeError, TypeError):
            pass
    if jsonld:
        meta["schema_org"] = jsonld

    # <link rel="license"> — machine-readable license declaration
    link = soup.find("link", rel="license")
    if link and link.get("href"):
        meta["license_url"] = link["href"]

    # <meta name="copyright"> and <meta name="author">
    for name in ("copyright", "author"):
        tag = soup.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
        if tag and tag.get("content"):
            meta[name] = tag["content"]

    # Twitter card
    twitter = {t.get("name"): t.get("content")
               for t in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")})
               if t.get("content")}
    if twitter:
        meta["twitter_card"] = twitter

    # Creative Commons — only look in <a> hrefs and <link> hrefs, not raw text
    cc_pattern = re.compile(r"creativecommons\.org/licenses/([a-z\-]+)/([0-9.]+)", re.I)
    for tag in soup.find_all(["a", "link"], href=True):
        m = cc_pattern.search(tag["href"])
        if m:
            meta["cc_license"] = f"CC {m.group(1).upper()} {m.group(2)}"
            meta["cc_license_url"] = f"https://creativecommons.org/licenses/{m.group(1)}/{m.group(2)}/"
            break

    if soup.title and soup.title.string:
        meta["page_title"] = soup.title.string.strip()

    return meta


def _civitai_image_api(image_id: str) -> dict:
    resp = _get_with_backoff(
        f"https://civitai.com/api/v1/images?imageId={image_id}", timeout=10
    )
    if resp and resp.ok:
        try:
            return resp.json()
        except Exception:
            pass
    return {}


def scrape_civitai(url: str) -> dict:
    m = re.search(r"civitai\.com/images/(\d+)", url)
    if not m:
        return {}
    image_id = m.group(1)
    return {"image_id": image_id, "api_data": _civitai_image_api(image_id)}


def detect_platform(url: str) -> str:
    domain = urllib.parse.urlparse(url).netloc.lower()
    for key, name in [
        ("civitai", "civitai"), ("huggingface", "huggingface"),
        ("artstation", "artstation"),
        ("deviantart", "deviantart"), ("wixmp", "deviantart"),  # wixmp.com = DeviantArt CDN
        ("flickr", "flickr"), ("pixiv", "pixiv"),
        ("shutterstock", "shutterstock"), ("gettyimages", "getty_images"),
        ("istockphoto", "istock"), ("unsplash", "unsplash"),
        ("pexels", "pexels"), ("adobe", "adobe_stock"),
        ("googleuser", "google"), ("ggpht", "google"), ("gstatic", "google"),
        ("pinterest", "pinterest"), ("instagram", "instagram"),
        ("twitter", "twitter_x"), ("x.com", "twitter_x"),
        ("wikimedia", "wikimedia"), ("wikipedia", "wikimedia"),
    ]:
        if key in domain:
            return name
    return "unknown"
