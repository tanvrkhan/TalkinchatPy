#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Image search (Bing) and GIF search (Giphy).

Images come from Bing (no key). GIFs come from Giphy's public API — its media
URLs re-host reliably, unlike Bing's hotlink-protected originals.
"""

import json
import random
import re
import urllib.parse
from urllib.request import Request, urlopen

import config

_UA = "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0"
_GIPHY_KEY = "Gc7131jiJuvI7IdN0HZ1D7nh0ow5BU6g"   # Giphy public API key


def _get_json(url, timeout=12):
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def search_image(query):
    """Random Bing image result (original URL)."""
    url = urllib.parse.urlunparse(
        ("https", "www.bing.com", "/images/async", "",
         urllib.parse.urlencode({"q": query}), ""))
    try:
        req = Request(url, headers={"User-Agent": _UA})
        html = urlopen(req, timeout=15).read().decode("utf8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    urls = re.findall(r"murl&quot;:&quot;(.*?)&quot;", html)
    return random.choice(urls) if urls else None


def search_gif(query):
    """Random Giphy GIF (a downloadable media.giphy.com URL)."""
    q = urllib.parse.quote(query)
    url = (f"https://api.giphy.com/v1/gifs/search?api_key={_GIPHY_KEY}"
           f"&q={q}&limit=30&rating=pg-13")
    try:
        data = _get_json(url)
    except Exception:  # noqa: BLE001
        return None
    items = data.get("data", [])
    if not items:
        return None
    imgs = random.choice(items).get("images", {})
    # prefer a smaller downloadable rendition, fall back to original
    for key in ("downsized_medium", "downsized", "original", "fixed_height"):
        u = imgs.get(key, {}).get("url")
        if u:
            return u.split("?")[0] if key in ("original", "fixed_height") else u
    return None
