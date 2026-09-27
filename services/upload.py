#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Upload a local file to Howdies' media endpoint.

    POST https://howdies.app:3001/api/upload   (multipart/form-data)
    fields: file, uploadType, UserID, token

Returns the hosted URL to use as chatroommessage.url, or None on failure.
See reference.md §8. UserID/token come from the login session; set them in
config (via env) once known, or they are learned from the login response.
"""

import mimetypes
import os
import random
import tempfile

import requests

import config


def rehost(url, kind="image", timeout=25):
    """Download an external file and re-host it on Howdies' CDN.

    External/oversized image or audio URLs sent straight to the chat make the
    server drop the connection, so media commands route through this. Returns
    the CDN URL or None.
    """
    if not (isinstance(url, str) and url.startswith("http")):
        return None
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True,
                         headers={"User-Agent": config.DEFAULT_UA,
                                  "Accept": "image/*,audio/*,*/*",
                                  "Referer": "https://www.google.com/"})
    except requests.RequestException as exc:
        print(f"[rehost] download failed: {exc}")
        return None
    if r.status_code != 200 or not r.content or len(r.content) > 20 * 1024 * 1024:
        print(f"[rehost] bad download: status={r.status_code} bytes={len(r.content or b'')}")
        return None
    ct = (r.headers.get("Content-Type") or "").lower()
    low = url.lower()
    if kind == "audio":
        ext = ".m4a" if ("mp4" in ct or ".m4a" in low or ".mp4" in low) else ".mp3"
    elif "gif" in ct or low.endswith(".gif"):
        ext = ".gif"
    elif "png" in ct or low.endswith(".png"):
        ext = ".png"
    else:
        ext = ".jpg"
    path = os.path.join(tempfile.gettempdir(),
                        f"howdies_dl_{os.getpid()}_{random.randint(1, 999999)}{ext}")
    try:
        with open(path, "wb") as fh:
            fh.write(r.content)
        return upload_file(path, kind)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def upload_from_url(url):
    return rehost(url, "image")


def upload_file(file_path, upload_type="image"):
    if not os.path.exists(file_path):
        return None
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    name = os.path.basename(file_path)
    with open(file_path, "rb") as fh:
        files = {"file": (name, fh, mime)}
        data = {
            "uploadType": upload_type,
            "UserID": config.USER_ID,
            "token": config.UPLOAD_TOKEN or config.CONNECT_TOKEN,
        }
        try:
            resp = requests.post(config.UPLOAD_URL, files=files, data=data,
                                 headers={"User-Agent": config.DEFAULT_UA},
                                 timeout=30)
        except requests.RequestException as exc:
            print(f"[upload] POST failed (UserID={config.USER_ID}): {exc}")
            return None

    url = _extract_url(resp)
    if not url:
        print(f"[upload] no URL in response (UserID={config.USER_ID}, "
              f"status={resp.status_code}): {(resp.text or '')[:200]}")
    return url


def _extract_url(resp):
    """The upload response shape is not fully confirmed; handle common cases."""
    text = (resp.text or "").strip()
    if not text:
        return None
    # JSON response: look for a url-ish field.
    try:
        j = resp.json()
        for key in ("url", "uploadedUrl", "fileUrl", "link", "data"):
            val = j.get(key) if isinstance(j, dict) else None
            if isinstance(val, str) and val.startswith("http"):
                return val
            if isinstance(val, dict):
                for k2 in ("url", "uploadedUrl", "link"):
                    if isinstance(val.get(k2), str) and val[k2].startswith("http"):
                        return val[k2]
    except ValueError:
        pass
    # Plain-text URL (like the old Talkinchat post.php).
    if text.startswith("http"):
        return text.split()[0]
    return None
