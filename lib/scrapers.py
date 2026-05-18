import json
import re
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


def download_image(url: str, dest_path: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=30, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(65536):
            f.write(chunk)
    return {
        "url": url,
        "http_status": resp.status_code,
        "domain": urllib.parse.urlparse(url).netloc,
        "response_headers": {
            "content-type": resp.headers.get("content-type"),
            "last-modified": resp.headers.get("last-modified"),
            "content-length": resp.headers.get("content-length"),
            "etag": resp.headers.get("etag"),
        },
    }


def scrape_page_metadata(page_url: str) -> dict:
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        return {"scrape_error": str(e)}

    meta = {}

    # OpenGraph tags
    og = {}
    for tag in soup.find_all("meta", property=re.compile(r"^og:")):
        og[tag.get("property")] = tag.get("content")
    if og:
        meta["opengraph"] = og

    # Schema.org JSON-LD
    jsonld = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            jsonld.append(data)
        except Exception:
            pass
    if jsonld:
        meta["schema_org"] = jsonld

    # <link rel="license">
    license_link = soup.find("link", rel="license")
    if license_link:
        meta["license_url"] = license_link.get("href")

    # <meta name="copyright">
    copyright_meta = soup.find("meta", attrs={"name": re.compile(r"copyright", re.I)})
    if copyright_meta:
        meta["copyright"] = copyright_meta.get("content")

    # <meta name="author">
    author_meta = soup.find("meta", attrs={"name": re.compile(r"^author$", re.I)})
    if author_meta:
        meta["author"] = author_meta.get("content")

    # Twitter card
    twitter = {}
    for tag in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
        twitter[tag.get("name")] = tag.get("content")
    if twitter:
        meta["twitter_card"] = twitter

    # Creative Commons license text anywhere in page
    cc_pattern = re.compile(
        r"creativecommons\.org/licenses/([a-z\-]+)/([0-9.]+)", re.I
    )
    cc_match = cc_pattern.search(resp.text)
    if cc_match:
        meta["cc_license"] = f"CC {cc_match.group(1).upper()} {cc_match.group(2)}"
        meta["cc_license_url"] = (
            f"https://creativecommons.org/licenses/"
            f"{cc_match.group(1)}/{cc_match.group(2)}/"
        )

    # Page title
    if soup.title:
        meta["page_title"] = soup.title.string

    return meta


def _civitai_image_api(image_id: str) -> dict:
    try:
        resp = requests.get(
            "https://civitai.com/api/v1/images",
            params={"imageId": image_id},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        return {"error": str(e)}
    return {}


def scrape_civitai(url: str) -> dict:
    result = {}
    page_match = re.search(r"civitai\.com/images/(\d+)", url)
    if page_match:
        result["image_id"] = page_match.group(1)
        result["api_data"] = _civitai_image_api(page_match.group(1))
    return result


def detect_platform(url: str) -> str:
    domain = urllib.parse.urlparse(url).netloc.lower()
    platforms = {
        "civitai": "civitai",
        "huggingface": "huggingface",
        "artstation": "artstation",
        "deviantart": "deviantart",
        "flickr": "flickr",
        "pixiv": "pixiv",
        "shutterstock": "shutterstock",
        "gettyimages": "getty_images",
        "istockphoto": "istock",
        "unsplash": "unsplash",
        "pexels": "pexels",
        "adobe": "adobe_stock",
        "googleuser": "google",
        "ggpht": "google",
        "gstatic": "google",
        "pinterest": "pinterest",
        "instagram": "instagram",
        "twitter": "twitter_x",
        "x.com": "twitter_x",
    }
    for key, platform in platforms.items():
        if key in domain:
            return platform
    return "unknown"
