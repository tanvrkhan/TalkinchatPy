#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Music scraping: YouTube (yt-dlp) and JioSaavn.

Ported and modernized from the original TalkinchatPy bot (youtube_dl -> yt-dlp).
"""

import requests

import config
from song import Song

_YDL_OPTS = {"quiet": True, "noplaylist": True, "no_warnings": True}


def scrape_music_from_yt(search_query):
    """Search YouTube and return a Song with a direct audio URL (format 140)."""
    try:
        import yt_dlp as ydl_mod
    except ImportError:  # fall back to legacy name if that is what is installed
        import youtube_dl as ydl_mod

    with ydl_mod.YoutubeDL(_YDL_OPTS) as ydl:
        result = ydl.extract_info(f"ytsearch:{search_query}", download=False)
        entries = result.get("entries") or []
        if not entries:
            return None
        entry = entries[0]
        duration = entry.get("duration") or 0
        thumb = ""
        thumbs = entry.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[0]["url"].split("?")[0]

        # Prefer m4a audio (itag 140); otherwise take the best audio-only URL.
        chosen = None
        for fmt in entry.get("formats", []):
            if fmt.get("format_id") == "140" and fmt.get("url"):
                chosen = fmt["url"]
                break
        if not chosen:
            for fmt in entry.get("formats", []):
                if fmt.get("acodec") not in (None, "none") and \
                        fmt.get("vcodec") in (None, "none") and fmt.get("url"):
                    chosen = fmt["url"]
        if not chosen:
            return None
        return Song(title=entry.get("title", "Unknown"),
                    url=chosen, duration=duration, thumb_url=thumb)


def _get_song_urls(song_obj):
    """Fill a JioSaavn Song with its download + thumbnail URLs."""
    req = requests.get(
        headers=config.JIO_SAAVN_HEADERS,
        url=("https://www.jiosaavn.com/api.php?__call=song.getDetails"
             f"&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={song_obj.songid}"),
        timeout=15,
    )
    raw = req.json().get(song_obj.songid, {})
    if "media_preview_url" in raw:
        song_obj.url = (raw["media_preview_url"]
                        .replace("https://preview.saavncdn.com/", "https://aac.saavncdn.com/")
                        .replace("_96_p.mp4", "_320.mp4"))
        song_obj.thumb_url = raw.get("image", "").replace("-150x150.jpg", "-500x500.jpg")
        song_obj.duration = raw.get("duration", "")
        return song_obj
    return None


def jio_query(query_text, max_results=5):
    """Search JioSaavn and return a list of playable Songs."""
    req = requests.get(
        headers=config.JIO_SAAVN_HEADERS,
        url=("https://www.jiosaavn.com/api.php?p=1"
             f"&q={query_text.replace(' ', '+')}"
             "&_format=json&_marker=0&api_version=4&ctx=wap6dot0"
             f"&n={max_results}&__call=search.getResults"),
        timeout=15,
    )
    results = req.json().get("results", [])
    songs = []
    for raw in results:
        info = raw.get("more_info", {})
        artists = info.get("artistMap", {}).get("primary_artists", [])
        song = Song(
            songid=raw["id"],
            title=raw.get("title", "Unknown"),
            year=raw.get("year", "Unknown"),
            album=info.get("album", "Unknown"),
            copyright=info.get("copyright_text", "Unknown"),
            artist=artists[0]["name"] if artists else "Unknown",
        )
        filled = _get_song_urls(song)
        if filled:
            songs.append(filled)
    return songs
