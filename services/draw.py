#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Image generation: text on a canvas, text on an avatar, welcome cards.

Ported from the original TalkinchatPy bot. Returns a saved PNG path plus its
pixel size (width, height) which TalkinChat needs for image messages.
"""

import random
import tempfile
import textwrap
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

COLOR_LIST = [
    "#F0F8FF", "#7FFFD4", "#00FFFF", "#8A2BE2", "#A52A2A", "#DEB887", "#5F9EA0",
    "#7FFF00", "#D2691E", "#FF7F50", "#6495ED", "#DC143C", "#00CED1", "#FF1493",
    "#1E90FF", "#FFD700", "#DAA520", "#ADFF2F", "#FF69B4", "#CD5C5C", "#4B0082",
    "#F0E68C", "#7CFC00", "#ADD8E6", "#F08080", "#20B2AA", "#87CEFA", "#32CD32",
    "#FF00FF", "#FF8000", "#FFA500", "#FF4500", "#DA70D6", "#98FB98", "#DB7093",
    "#DDA0DD", "#B0E0E6", "#9B30FF", "#FF6347", "#40E0D0", "#EE82EE", "#F5DEB3",
]

_OUT = "pil_text.png"


def _font(size=60):
    return ImageFont.truetype(config.IMG_TXT_FONT, size)


def _text_size(draw, text, font):
    """Pillow-version-agnostic text measurement."""
    if hasattr(draw, "textbbox"):
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    return font.getsize(text)  # Pillow < 9.2 fallback


def _draw_wrapped(image, text, font, color, start_height, width=25):
    draw = ImageDraw.Draw(image)
    img_w, _ = image.size
    y = start_height
    for line in textwrap.wrap(text, width=width):
        line_w, line_h = _text_size(draw, line, font)
        draw.text(((img_w - line_w) / 2, y), line, font=font, fill=color)
        y += line_h + 6


def _resample():
    # Pillow 10 removed Image.ANTIALIAS.
    return getattr(Image, "Resampling", Image).LANCZOS


def _save_game_image(image, prefix):
    with tempfile.NamedTemporaryFile(prefix=f"talkinchat-{prefix}-", suffix=".png",
                                     delete=False) as output:
        image.save(output, "PNG")
        return output.name, image.size


def draw_tictactoe(board, player_x, player_o, status):
    image = Image.new("RGB", (900, 900), (22, 28, 36))
    canvas = ImageDraw.Draw(image)
    title = _font(44)
    body = _font(32)
    mark = _font(120)
    canvas.text((50, 35), "TIC-TAC-TOE", font=title, fill=(245, 198, 68))
    canvas.text((50, 100), f"X {player_x}   O {player_o}", font=body, fill="white")
    canvas.text((50, 815), status, font=body, fill=(135, 220, 190))
    left, top, size = 150, 170, 200
    for value in (1, 2):
        canvas.line((left + value * size, top, left + value * size, top + 3 * size),
                    fill=(108, 126, 145), width=12)
        canvas.line((left, top + value * size, left + 3 * size, top + value * size),
                    fill=(108, 126, 145), width=12)
    for index, value in enumerate(board):
        shown = str(value or "").replace("❌", "X").replace("⭕", "O")
        if not shown.strip():
            continue
        row, column = divmod(index, 3)
        color = (240, 92, 92) if shown.upper() == "X" else (72, 174, 235)
        width, height = _text_size(canvas, shown, mark)
        x = left + column * size + (size - width) / 2
        y = top + row * size + (size - height) / 2 - 15
        canvas.text((x, y), shown, font=mark, fill=color)
    return _save_game_image(image, "ttt")


def draw_hangman(masked_word, wrong_letters, wrong_count, status, riddle):
    image = Image.new("RGB", (1000, 700), (244, 241, 232))
    canvas = ImageDraw.Draw(image)
    ink = (32, 42, 52)
    canvas.text((50, 20), "HANGMAN", font=_font(48), fill=ink)
    _draw_wrapped(
        image, f"Riddle: {riddle}", _font(24), (76, 63, 47), 88, width=72
    )
    canvas.line((120, 620, 400, 620), fill=ink, width=12)
    canvas.line((250, 620, 250, 180), fill=ink, width=12)
    canvas.line((250, 180, 510, 180), fill=ink, width=12)
    canvas.line((510, 180, 510, 235), fill=ink, width=8)
    if wrong_count >= 1:
        canvas.ellipse((465, 235, 555, 325), outline=ink, width=8)
    if wrong_count >= 2:
        canvas.line((510, 325, 510, 460), fill=ink, width=8)
    if wrong_count >= 3:
        canvas.line((510, 360, 450, 415), fill=ink, width=8)
    if wrong_count >= 4:
        canvas.line((510, 360, 570, 415), fill=ink, width=8)
    if wrong_count >= 5:
        canvas.line((510, 460, 460, 550), fill=ink, width=8)
    if wrong_count >= 6:
        canvas.line((510, 460, 560, 550), fill=ink, width=8)
    canvas.text((600, 235), masked_word, font=_font(52), fill=(24, 105, 150))
    canvas.text((600, 335), "Wrong: " + " ".join(wrong_letters),
                font=_font(28), fill=(185, 66, 62))
    canvas.text((600, 405), status, font=_font(28), fill=ink)
    return _save_game_image(image, "hangman")


def _cricket_player(match, key):
    for team in match.get("teams", {}).values():
        for player in team.get("players", []):
            if player.get("key") == key:
                return str(player.get("user", "Player"))
    return "Player"


def _draw_cricket_ball(draw, center, radius, fill, seam):
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    draw.arc((x - radius * .65, y - radius, x + radius * .45, y + radius),
             285, 75, fill=seam, width=max(2, int(radius * .12)))
    draw.arc((x - radius * .45, y - radius, x + radius * .65, y + radius),
             105, 255, fill=seam, width=max(2, int(radius * .12)))


def _draw_cricket_stumps(draw, left, top, color, *, broken=False):
    for offset in (0, 28, 56):
        end_x = left + offset + (18 if broken and offset != 28 else 0)
        end_y = top + 112 - (20 if broken and offset == 56 else 0)
        draw.line((left + offset, top, end_x, end_y), fill=color, width=9)
    if broken:
        draw.line((left - 8, top - 18, left + 22, top - 30), fill=color, width=8)
        draw.line((left + 34, top - 34, left + 69, top - 18), fill=color, width=8)
    else:
        draw.line((left - 5, top - 8, left + 27, top - 8), fill=color, width=7)
        draw.line((left + 26, top - 8, left + 61, top - 8), fill=color, width=7)


def _draw_cricket_event(draw, bounds, match, events=()):
    left, top, right, bottom = bounds
    history = match.get("history", [])
    event = history[-1] if history else None
    phase = match.get("phase")
    cream, navy = "#FFF8E7", "#102E3A"
    event_kinds = {item.get("kind") for item in events if isinstance(item, dict)}

    if phase == "finished":
        kind, fill, accent, heading = "win", "#FFC857", "#102E3A", "MATCH WON"
    elif phase == "toss":
        kind, fill, accent, heading = "toss", "#44C7D8", "#102E3A", "TOSS"
    elif "super_over_started" in event_kinds:
        kind, fill, accent, heading = "waiting", "#F05D5E", cream, "SUPER OVER"
    elif "chase_started" in event_kinds:
        kind, fill, accent, heading = "waiting", "#FFC857", navy, "TARGET SET"
    elif not event:
        kind, fill, accent, heading = "waiting", "#173F4B", "#7FE0C3", "PLAY BALL"
    elif event.get("kind") == "wicket":
        kind, fill, accent, heading = "out", "#F05D5E", cream, "OUT!"
    else:
        runs = int(event.get("runs", 0))
        if runs == 6:
            kind, fill, accent, heading = "six", "#44C7D8", "#102E3A", "SIX!"
        elif runs == 4:
            kind, fill, accent, heading = "four", "#FFC857", "#102E3A", "FOUR!"
        elif runs == 0:
            kind, fill, accent, heading = "dot", "#4058A6", cream, "DOT BALL"
        else:
            kind, fill, accent = "runs", "#54D38A", "#102E3A"
            heading = f"{runs} RUN" if runs == 1 else f"{runs} RUNS"

    draw.rounded_rectangle(bounds, radius=8, fill=fill)
    heading_font = _fit_font(draw, heading, right - left - 34, 42, 26)
    heading = _short_text(draw, heading, heading_font, right - left - 34)
    width, _ = _text_size(draw, heading, heading_font)
    draw.text((left + (right - left - width) / 2, top + 18), heading,
              font=heading_font, fill=accent)

    cx, cy = (left + right) / 2, top + 174
    if kind == "out":
        _draw_cricket_stumps(draw, cx - 35, cy - 38, cream, broken=True)
        _draw_cricket_ball(draw, (cx + 75, cy - 42), 20, "#7A1825", cream)
    elif kind == "six":
        draw.arc((left + 35, top + 78, right - 35, bottom + 70), 198, 340,
                 fill=accent, width=7)
        _draw_cricket_ball(draw, (cx + 62, top + 105), 20, "#F05D5E", cream)
        for x, y in ((left + 54, top + 112), (right - 58, top + 150), (cx - 4, top + 92)):
            draw.line((x - 12, y, x + 12, y), fill=cream, width=4)
            draw.line((x, y - 12, x, y + 12), fill=cream, width=4)
    elif kind == "four":
        draw.line((left + 30, bottom - 45, right - 30, bottom - 45),
                  fill="#F05D5E", width=12)
        draw.line((left + 68, cy + 15, right - 72, cy - 18), fill=cream, width=7)
        _draw_cricket_ball(draw, (right - 72, cy - 18), 20, "#F05D5E", cream)
    elif kind == "dot":
        draw.polygon(((cx - 66, cy - 76), (cx + 66, cy - 76),
                      (cx + 48, cy + 50), (cx, cy + 88), (cx - 48, cy + 50)),
                     fill="#263873", outline=cream)
        _draw_cricket_stumps(draw, cx - 28, cy - 18, cream)
    elif kind == "runs":
        for shift in (-58, 58):
            x = cx + shift
            draw.ellipse((x - 17, cy - 72, x + 17, cy - 38), fill=accent)
            draw.line((x, cy - 36, x + shift * .18, cy + 20), fill=accent, width=9)
            draw.line((x, cy - 5, x - shift * .22, cy + 46), fill=accent, width=8)
            draw.line((x, cy - 5, x + shift * .34, cy + 40), fill=accent, width=8)
    elif kind == "win":
        draw.rectangle((cx - 45, cy - 52, cx + 45, cy + 38), fill=accent)
        draw.polygon(((cx - 72, cy - 52), (cx + 72, cy - 52),
                      (cx + 38, cy - 105), (cx - 38, cy - 105)), fill=accent)
        draw.rectangle((cx - 70, cy + 38, cx + 70, cy + 58), fill=accent)
    elif kind == "toss":
        draw.ellipse((cx - 72, cy - 76, cx + 72, cy + 68),
                     fill="#FFC857", outline=cream, width=6)
        draw.text((cx - 22, cy - 55), "C", font=_font(70), fill=accent)
    else:
        _draw_cricket_stumps(draw, cx - 28, cy - 22, accent)
        _draw_cricket_ball(draw, (cx + 74, cy - 38), 20, "#F05D5E", cream)


def draw_cricket_score(match, events=()):
    """Render a mobile-safe stadium board with a distinct scene per outcome."""
    image = Image.new("RGB", (1000, 700), "#092D2A")
    canvas = ImageDraw.Draw(image)
    cream, gold, mint = "#FFF8E7", "#FFC857", "#7FE0C3"
    muted, line = "#B7CEC7", "#35675D"
    teams = match.get("teams", {})
    team_a, team_b = teams.get("a", {}), teams.get("b", {})
    innings = match.get("innings") or {}
    phase = match.get("phase", "")

    canvas.text((40, 25), "HOWDIES CRICKET", font=_font(30), fill=gold)
    phase_label = ("TOSS" if phase == "toss" else "FINAL" if phase == "finished"
                   else f"INNINGS {match.get('innings_number', 1)}")
    pf = _font(20)
    pw, ph = _text_size(canvas, phase_label, pf)
    canvas.rounded_rectangle((940 - pw, 28, 960, 28 + ph + 18), radius=6,
                             fill="#173F4B")
    canvas.text((950 - pw, 34), phase_label, font=pf, fill=mint)

    versus = f"{team_a.get('room_name', 'Team A')}  vs  {team_b.get('room_name', 'Team B')}"
    versus_font = _fit_font(canvas, versus, 920, 34, 20)
    versus = _short_text(canvas, versus, versus_font, 920)
    canvas.text((40, 84), versus, font=versus_font, fill=cream)
    canvas.line((40, 132, 960, 132), fill=line, width=3)

    canvas.rounded_rectangle((40, 158, 610, 452), radius=8, fill="#113D38")
    if phase == "toss":
        winner = teams.get((match.get("toss") or {}).get("winner"), {})
        name = str(winner.get("room_name", "Team"))
        font = _fit_font(canvas, name, 510, 50, 28)
        canvas.text((70, 205), _short_text(canvas, name, font, 510), font=font, fill=cream)
        canvas.text((70, 285), "won the toss", font=_font(34), fill=mint)
        canvas.text((70, 350), "BAT OR BOWL?", font=_font(25), fill=gold)
    elif phase == "finished":
        winner = teams.get(match.get("winner"), {})
        name = str(winner.get("room_name", "No contest"))
        font = _fit_font(canvas, name, 510, 52, 28)
        canvas.text((70, 205), _short_text(canvas, name, font, 510), font=font, fill=cream)
        canvas.text((70, 286), "MATCH WINNER" if winner else "MATCH ENDED",
                    font=_font(31), fill=gold)
        if innings:
            canvas.text((70, 356),
                        f"Final score  {innings.get('runs', 0)} / {innings.get('wickets', 0)}",
                        font=_font(25), fill=muted)
    else:
        batting = teams.get(innings.get("batting"), {})
        team_name = str(batting.get("room_name", "Batting"))
        team_font = _fit_font(canvas, team_name, 500, 30, 20)
        canvas.text((70, 185), _short_text(canvas, team_name, team_font, 500),
                    font=team_font, fill=mint)
        score = f"{innings.get('runs', 0)} / {innings.get('wickets', 0)}"
        canvas.text((70, 232), score, font=_font(76), fill=cream)
        balls = int(innings.get("balls", 0))
        canvas.text((405, 273), f"{balls // 6}.{balls % 6} OV", font=_font(27), fill=muted)
        target = innings.get("target")
        if target:
            needed = max(0, int(target) - int(innings.get("runs", 0)))
            remaining = max(0, int(innings.get("max_balls", match.get("overs", 0) * 6)) - balls)
            canvas.text((70, 355), f"TARGET {target}", font=_font(25), fill=gold)
            canvas.text((310, 355), f"NEED {needed} FROM {remaining}",
                        font=_font(25), fill=cream)
        else:
            canvas.text((70, 355), f"{max(0, int(match.get('overs', 0)) * 6 - balls)} BALLS LEFT",
                        font=_font(25), fill=gold)

    _draw_cricket_event(canvas, (635, 158, 960, 452), match, events)

    if innings and phase not in {"toss", "finished"}:
        batter = _cricket_player(match, innings.get("striker"))
        bowler = _cricket_player(match, innings.get("bowler"))
        batter_font = _fit_font(canvas, batter, 360, 25, 18)
        bowler_font = _fit_font(canvas, bowler, 360, 25, 18)
        canvas.text((40, 480), "AT THE CREASE", font=_font(18), fill=muted)
        canvas.text((40, 512), _short_text(canvas, batter, batter_font, 360),
                    font=batter_font, fill=cream)
        canvas.text((425, 480), "WITH THE BALL", font=_font(18), fill=muted)
        canvas.text((425, 512), _short_text(canvas, bowler, bowler_font, 360),
                    font=bowler_font, fill=cream)
    else:
        canvas.text((40, 500), "MATCH CENTRE", font=_font(20), fill=muted)

    history = match.get("history", [])[-6:]
    canvas.text((40, 573), "LAST 6", font=_font(18), fill=muted)
    if history:
        for index, event in enumerate(history):
            label = "W" if event.get("kind") == "wicket" else str(event.get("runs", 0))
            color = "#F05D5E" if label == "W" else "#FFC857" if label in {"4", "6"} else mint
            left = 145 + index * 72
            canvas.ellipse((left, 565, left + 50, 615), fill="#173F4B", outline=color, width=3)
            font = _font(22)
            width, height = _text_size(canvas, label, font)
            canvas.text((left + (50 - width) / 2, 589 - height / 2),
                        label, font=font, fill=color)
    else:
        canvas.text((145, 571), "First ball waiting", font=_font(24), fill=cream)

    canvas.line((40, 640, 960, 640), fill=line, width=2)
    canvas.text((40, 656), "Send ,b1 through ,b6. Choices reveal together.",
                font=_font(19), fill=muted)
    return _save_game_image(image, "cricket")


def draw_blackjack(player_cards, dealer_cards, player_total, dealer_total, bet, status):
    image = Image.new("RGB", (1100, 700), (18, 93, 62))
    canvas = ImageDraw.Draw(image)
    canvas.text((45, 30), "BLACKJACK", font=_font(48), fill=(250, 215, 90))
    canvas.text((45, 105), f"Bet: {bet:,} XP", font=_font(28), fill="white")

    def cards(values, top, label, total):
        canvas.text((45, top), f"{label} · {total}", font=_font(30), fill="white")
        for index, value in enumerate(values):
            left = 300 + index * 135
            canvas.rounded_rectangle((left, top - 20, left + 105, top + 135), radius=8,
                                     fill=(250, 249, 244), outline=(28, 30, 35), width=4)
            canvas.text((left + 28, top + 22), str(value), font=_font(42), fill=(32, 35, 40))

    cards(dealer_cards, 210, "Dealer", dealer_total)
    cards(player_cards, 445, "You", player_total)
    canvas.text((45, 635), status, font=_font(28), fill=(250, 215, 90))
    return _save_game_image(image, "blackjack")


# ----------------------------------------------------------- card games -----
_CARD_TABLE_SIZE = (900, 1200)
_CARD_COLORS = {
    "clubs": "#263238",
    "spades": "#263238",
    "diamonds": "#C62828",
    "hearts": "#C62828",
    "red": "#D32F2F",
    "yellow": "#F9A825",
    "green": "#2E7D32",
    "blue": "#1565C0",
    "wild": "#37474F",
}
_CARD_LABELS = {
    "draw2": "DRAW 2",
    "reverse": "REVERSE",
    "skip": "SKIP",
    "wild": "WILD",
    "wild4": "WILD 4",
}


def _card_value(card, field, default=""):
    if isinstance(card, dict):
        return card.get(field, default)
    return getattr(card, field, default)


def _fit_font(draw, text, max_width, size, minimum=16):
    for candidate in range(size, minimum - 1, -2):
        font = _font(candidate)
        if _text_size(draw, text, font)[0] <= max_width:
            return font
    return _font(minimum)


def _short_text(draw, text, font, max_width):
    text = str(text)
    while _text_size(draw, text, font)[0] > max_width and len(text) > 3:
        text = text[:-4].rstrip() + "..."
    return text


def _draw_suit(draw, left, top, size, suit, color):
    """Draw a simple vector suit so standard cards remain legible in bundled fonts."""
    half = size / 2
    if suit == "diamonds":
        draw.polygon(
            [(left + half, top), (left + size, top + half),
             (left + half, top + size), (left, top + half)],
            fill=color,
        )
    elif suit == "hearts":
        draw.ellipse((left, top, left + half + 2, top + half + 4), fill=color)
        draw.ellipse((left + half - 2, top, left + size, top + half + 4), fill=color)
        draw.polygon(
            [(left, top + half - 2), (left + size, top + half - 2),
             (left + half, top + size)],
            fill=color,
        )
    elif suit == "clubs":
        radius = size * 0.34
        for center_x, center_y in (
            (left + half, top + radius),
            (left + radius, top + half + 2),
            (left + size - radius, top + half + 2),
        ):
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill=color,
            )
        draw.polygon(
            [(left + half - size * .12, top + half),
             (left + half + size * .12, top + half),
             (left + half + size * .22, top + size),
             (left + half - size * .22, top + size)],
            fill=color,
        )
    elif suit == "spades":
        draw.polygon(
            [(left + half, top), (left, top + size * .62),
             (left + half, top + size * .48), (left + size, top + size * .62)],
            fill=color,
        )
        draw.polygon(
            [(left + half - size * .12, top + half),
             (left + half + size * .12, top + half),
             (left + half + size * .22, top + size),
             (left + half - size * .22, top + size)],
            fill=color,
        )


def _draw_card_face(draw, bounds, card):
    """Render one public or private card without relying on external assets."""
    left, top, right, bottom = bounds
    suit = str(_card_value(card, "suit", "wild")).lower()
    rank = str(_card_value(card, "rank", "?")).upper()
    color = _CARD_COLORS.get(suit, "#37474F")
    width, height = right - left, bottom - top
    draw.rounded_rectangle(bounds, radius=12, fill="#FFFDF7", outline="#20313D", width=4)

    if suit in {"clubs", "diamonds", "hearts", "spades"}:
        rank_font = _fit_font(draw, rank, width - 28, 34, 18)
        draw.text((left + 13, top + 9), rank, font=rank_font, fill=color)
        _draw_suit(draw, left + 16, top + 55, min(30, width * .2), suit, color)
        _draw_suit(draw, right - min(44, width * .28), bottom - min(47, height * .22),
                   min(30, width * .2), suit, color)
        _draw_suit(draw, left + (width - min(54, width * .35)) / 2,
                   top + (height - min(54, height * .35)) / 2,
                   min(54, width * .35), suit, color)
        return

    draw.rounded_rectangle((left + 7, top + 7, right - 7, bottom - 7), radius=8,
                           fill=color)
    label = _CARD_LABELS.get(rank.lower(), rank)
    lines = textwrap.wrap(label, width=8) or [label]
    font = _fit_font(draw, max(lines, key=len), width - 30, 28, 14)
    line_height = _text_size(draw, "W", font)[1] + 3
    start = top + (height - line_height * len(lines)) / 2 - 3
    for index, line in enumerate(lines):
        line = _short_text(draw, line, font, width - 30)
        text_width, _ = _text_size(draw, line, font)
        draw.text((left + (width - text_width) / 2, start + index * line_height),
                  line, font=font, fill="#FFFFFF")


def _draw_seat(draw, bounds, player, count, is_turn):
    left, top, right, bottom = bounds
    fill = "#21465A" if is_turn else "#1C2C39"
    border = "#F7C948" if is_turn else "#486170"
    draw.rounded_rectangle(bounds, radius=10, fill=fill, outline=border, width=3)
    marker = "TURN" if is_turn else ""
    name_font = _fit_font(draw, str(player), right - left - 130, 28, 16)
    name = _short_text(draw, player, name_font, right - left - 130)
    draw.text((left + 16, top + 14), name, font=name_font, fill="#F7F8F3")
    count_text = f"{count} CARDS"
    count_font = _fit_font(draw, count_text, right - left - 32, 22, 14)
    draw.text((left + 16, bottom - 37), count_text, font=count_font, fill="#B9D5D9")
    if marker:
        marker_font = _font(18)
        marker_width, _ = _text_size(draw, marker, marker_font)
        draw.text((right - marker_width - 14, top + 16), marker, font=marker_font,
                  fill="#F7C948")


def _public_status_lines(view):
    game = str(view.get("game", "card game")).lower()
    if game == "thulla":
        status = [f"WASTE {view.get('waste_count', 0)}", "FIRST TRICK" if view.get("first_trick") else "FOLLOW SUIT"]
        if view.get("safe_players"):
            status.append("SAFE: " + ", ".join(map(str, view["safe_players"])))
        if view.get("loser"):
            status.append("LOSER: " + str(view["loser"]))
        return status
    if game == "rang":
        tricks = view.get("team_tricks", [0, 0])
        courts = view.get("courts", [0, 0])
        return [
            "TRUMP: " + str(view.get("trump") or "CHOOSING").upper(),
            f"TRICKS: {tricks[0] if tricks else 0} - {tricks[1] if len(tricks) > 1 else 0}",
            f"COURTS: {courts[0] if courts else 0} - {courts[1] if len(courts) > 1 else 0}",
            "DEAL " + str(view.get("deal_number", 1)),
        ]
    if game == "uno":
        direction = "CW" if view.get("direction", 1) == 1 else "CCW"
        status = [
            "ACTIVE: " + str(view.get("active_color") or "NONE").upper(),
            f"DRAW PILE: {view.get('draw_count', 0)} | {direction}",
            f"ROUND {view.get('round_number', 1)} / {view.get('target', 500)} XP",
        ]
        if view.get("pending_draw"):
            status.append(f"PENALTY: DRAW {view['pending_draw']}")
        if view.get("uno_catchable"):
            status.append("UNO: " + str(view["uno_catchable"]))
        return status
    return ["PUBLIC TABLE", "PHASE: " + str(view.get("phase", "waiting")).upper()]


def _draw_status(draw, lines, top):
    font = _font(22)
    y = top
    for line in lines[:5]:
        line = _short_text(draw, line, font, 820)
        draw.text((42, y), line, font=font, fill="#D5E7E5")
        y += 34


def _visible_table_cards(view):
    trick = view.get("trick") or []
    cards = []
    for entry in trick:
        if isinstance(entry, dict) and entry.get("card"):
            cards.append((str(entry.get("player", "")), entry["card"]))
    if not cards and view.get("discard"):
        cards.append(("DISCARD", view["discard"]))
    return cards[:4]


def draw_card_table(view, title):
    """Render a fixed-size room-safe table from a game public projection."""
    image = Image.new("RGB", _CARD_TABLE_SIZE, "#13232F")
    draw = ImageDraw.Draw(image)
    width, _ = image.size
    title = str(title)
    title_font = _fit_font(draw, title, width - 80, 42, 24)
    draw.text((40, 28), _short_text(draw, title, title_font, width - 80),
              font=title_font, fill="#F7C948")
    phase = "PHASE: " + str(view.get("phase", "waiting")).upper()
    phase_font = _font(20)
    phase_width, _ = _text_size(draw, phase, phase_font)
    draw.text((width - phase_width - 40, 40), phase, font=phase_font, fill="#B9D5D9")

    turn = view.get("current_player")
    turn_text = "TURN: " + (str(turn) if turn else "WAITING")
    turn_font = _fit_font(draw, turn_text, width - 80, 30, 18)
    draw.text((40, 91), _short_text(draw, turn_text, turn_font, width - 80),
              font=turn_font, fill="#F7F8F3")

    players = list(view.get("players") or [])[:8]
    counts = view.get("card_counts") or {}
    for index, player in enumerate(players):
        row, column = divmod(index, 2)
        left = 40 + column * 420
        top = 155 + row * 105
        _draw_seat(draw, (left, top, left + 400, top + 85), player,
                   counts.get(player, 0), player == turn)

    table_top = 600
    draw.rounded_rectangle((40, table_top, 860, 970), radius=12, fill="#0E1921",
                           outline="#486170", width=3)
    table_label = "TABLE" if view.get("trick") else "DISCARD"
    draw.text((65, table_top + 22), table_label, font=_font(24), fill="#B9D5D9")
    table_cards = _visible_table_cards(view)
    if table_cards:
        card_width, card_height = 150, 205
        gap = 32
        occupied = len(table_cards) * card_width + (len(table_cards) - 1) * gap
        start = (width - occupied) / 2
        for index, (player, card) in enumerate(table_cards):
            left = int(start + index * (card_width + gap))
            card_top = table_top + 55
            _draw_card_face(draw, (left, card_top, left + card_width, card_top + card_height), card)
            player_font = _fit_font(draw, player, card_width, 18, 12)
            player = _short_text(draw, player, player_font, card_width)
            player_width, _ = _text_size(draw, player, player_font)
            draw.text((left + (card_width - player_width) / 2, card_top + card_height + 7),
                      player, font=player_font, fill="#D5E7E5")
    else:
        draw.text((65, table_top + 138), "NO CARDS ON THE TABLE", font=_font(26),
                  fill="#7FA3AC")

    _draw_status(draw, _public_status_lines(view), 1010)
    return _save_game_image(image, "card-table")


def draw_private_hand(cards, title, page, pages):
    """Render one authenticated player's current hand page in a fixed mobile frame."""
    image = Image.new("RGB", _CARD_TABLE_SIZE, "#13232F")
    draw = ImageDraw.Draw(image)
    title = str(title)
    title_font = _fit_font(draw, title, 620, 38, 22)
    draw.text((40, 31), _short_text(draw, title, title_font, 620), font=title_font,
              fill="#F7C948")
    page = max(1, int(page))
    pages = max(1, int(pages))
    page_label = f"PAGE {min(page, pages)}/{pages}"
    page_font = _font(22)
    page_width, _ = _text_size(draw, page_label, page_font)
    draw.text((860 - page_width, 44), page_label, font=page_font, fill="#B9D5D9")
    draw.text((40, 96), "PRIVATE HAND", font=_font(21), fill="#D5E7E5")

    cards = list(cards or [])
    if len(cards) > 16:
        start = (min(page, pages) - 1) * 16
        cards = cards[start:start + 16]
    if not cards:
        draw.text((40, 210), "NO CARDS", font=_font(32), fill="#B9D5D9")
        return _save_game_image(image, "private-hand")

    card_width, card_height = 185, 210
    for index, card in enumerate(cards):
        row, column = divmod(index, 4)
        left = 48 + column * 212
        top = 155 + row * 245
        _draw_card_face(draw, (left, top, left + card_width, top + card_height), card)
    return _save_game_image(image, "private-hand")


def draw_on_canvas(text):
    bg = random.choice(COLOR_LIST)
    image = Image.new("RGB", (800, 600), color=bg)
    image = image.filter(ImageFilter.GaussianBlur(radius=2))
    _draw_wrapped(image, text, _font(60), random.choice(COLOR_LIST), 150)
    image.save(_OUT)
    return _OUT, image.size


def draw_on_avatar(text, avatar_url):
    resp = requests.get(avatar_url or config.DEFAULT_AVATAR, timeout=15)
    avatar = Image.open(BytesIO(resp.content)).convert("RGB")
    avatar = avatar.resize((800, 800), _resample())
    avatar = avatar.filter(ImageFilter.GaussianBlur(radius=12))
    _draw_wrapped(avatar, text, _font(60), random.choice(COLOR_LIST), 300)
    avatar.save(_OUT)
    return _OUT, avatar.size


def _load_avatar(url, size=260):
    """Fetch a circular avatar; fall back to a colored initial disc on failure."""
    try:
        resp = requests.get(url, timeout=12)
        img = Image.open(BytesIO(resp.content)).convert("RGB").resize((size, size), _resample())
    except Exception:  # noqa: BLE001 - avatar may be null/unreachable
        img = Image.new("RGB", (size, size), color=random.choice(COLOR_LIST))
    # circular mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def draw_slap_result(winner_name, winner_avatar, loser_name, loser_avatar,
                     winner_health=100, loser_health=100, damage=0,
                     critical=False, blocked=False):
    """Compose a 'winner slapped loser' card with both DPs. Returns (path, size)."""
    W, H = 800, 420
    bg = Image.new("RGB", (W, H), color=(20, 22, 30))
    draw = ImageDraw.Draw(bg)
    win = _load_avatar(winner_avatar)
    los = _load_avatar(loser_avatar)
    bg.paste(win, (90, 70), win)
    bg.paste(los, (450, 70), los)
    # big collision emoji-ish mark in the middle
    mid = _font(90)
    draw.text((W / 2 - 40, 150), "👊", font=mid, fill=(255, 90, 90))
    name_font = _font(34)
    for cx, name, tag, col in ((220, winner_name, "WINNER", (120, 230, 120)),
                               (580, loser_name, "SLAPPED", (240, 120, 120))):
        w, _ = _text_size(draw, name, name_font)
        draw.text((cx - w / 2, 345), name, font=name_font, fill=(255, 255, 255))
        tf = _font(22)
        tw, _ = _text_size(draw, tag, tf)
        draw.text((cx - tw / 2, 30), tag, font=tf, fill=col)
    for left, health_value, color in ((90, winner_health, (70, 205, 110)),
                                      (450, loser_health, (235, 80, 80))):
        draw.rounded_rectangle((left, 390, left + 260, 408), radius=7,
                               fill=(65, 68, 78))
        width = int(260 * max(0, min(100, health_value)) / 100)
        if width:
            draw.rounded_rectangle((left, 390, left + width, 408), radius=7, fill=color)
    state = "SHIELD BLOCKED" if blocked else ("CRITICAL" if critical else "HIT")
    damage_text = f"{state} · {damage} HP"
    state_font = _font(22)
    sw, _ = _text_size(draw, damage_text, state_font)
    draw.text(((W - sw) / 2, 5), damage_text, font=state_font, fill=(255, 210, 90))
    bg.save(_OUT)
    return _OUT, bg.size


def draw_welcome(username, room_name):
    bg = random.choice(COLOR_LIST)
    image = Image.new("RGB", (800, 600), color=bg)
    image = image.filter(ImageFilter.GaussianBlur(radius=3))
    text = f"Welcome to {room_name}\n{username}\nEnjoy your stay!"
    _draw_wrapped(image, text, _font(56), random.choice(COLOR_LIST), 150)
    image.save(_OUT)
    return _OUT, image.size


# ----------------------------------------------------------------- bingo -----
import os as _os
import tempfile as _tempfile

_BINGO_FONT = "fonts/Merienda-Bold.ttf"
# Classic B-I-N-G-O column header colors.
_BINGO_HEADER = ["#1E88E5", "#E53935", "#2E7D32", "#F57C00", "#6A1B9A"]
# marker emoji -> fill color for marked cells
_MARKER_COLORS = {
    "🔴": "#E53935", "🟠": "#FB8C00", "🟡": "#F9A825", "🟢": "#43A047",
    "🔵": "#1E88E5", "🟣": "#8E24AA", "🟤": "#6D4C41", "⚫": "#37474F",
    "⚪": "#9E9E9E",
}


def _bfont(size):
    try:
        return ImageFont.truetype(_BINGO_FONT, size)
    except OSError:
        return _font(size)


def draw_bingo_card(card, marked, title="Bingo Card", marker="🔴", subtitle=""):
    """Render a 5x5 Bingo card as a PNG (proper aligned grid, not chat text).

    card: 5x5 rows of ints with None at the free center. marked: set of numbers
    already called/marked. Returns (path, (w, h)); path is a unique temp file.
    """
    marked = set(marked)
    fill = _MARKER_COLORS.get(marker, "#E53935")
    cell, pad = 118, 24
    title_h, header_h = 76, 80
    grid = cell * 5
    sub_h = 52 if subtitle else 22
    W = grid + pad * 2
    H = title_h + header_h + grid + pad + sub_h
    img = Image.new("RGB", (W, H), "#FDFDFD")
    d = ImageDraw.Draw(img)

    hfont, nfont, sfont = _bfont(52), _bfont(46), _bfont(28)

    # Auto-fit the title (the player's name) so a long name never clips off the
    # edge — shrink the font, then truncate with an ellipsis only as a last resort.
    max_tw = W - 2 * pad
    tfont = _bfont(44)
    for size in range(44, 21, -2):
        tfont = _bfont(size)
        if _text_size(d, title, tfont)[0] <= max_tw:
            break
    disp = title
    while _text_size(d, disp, tfont)[0] > max_tw and len(disp) > 4:
        disp = disp[:-2]
    if disp != title:
        disp = disp.rstrip() + "…"
    tw, th = _text_size(d, disp, tfont)
    d.text(((W - tw) / 2, (title_h - th) / 2), disp, font=tfont, fill="#111111")

    top = title_h
    for i, ch in enumerate("BINGO"):
        x0 = pad + i * cell
        d.rectangle([x0, top, x0 + cell, top + header_h], fill=_BINGO_HEADER[i])
        cw, chh = _text_size(d, ch, hfont)
        d.text((x0 + (cell - cw) / 2, top + (header_h - chh) / 2 - 6), ch,
               font=hfont, fill="#FFFFFF")

    gy = top + header_h
    for r in range(5):
        for c in range(5):
            x0, y0 = pad + c * cell, gy + r * cell
            value = card[r][c]
            is_free = value is None
            is_marked = is_free or value in marked
            if is_free:
                bg, label, lcol = "#FFE082", "FREE", "#6D4C41"
            elif is_marked:
                bg, label, lcol = fill, str(value), "#FFFFFF"
            else:
                bg, label, lcol = "#FFFFFF", str(value), "#263238"
            d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=bg,
                        outline="#37474F", width=3)
            lfont = sfont if is_free else nfont
            lw, lh = _text_size(d, label, lfont)
            d.text((x0 + (cell - lw) / 2, y0 + (cell - lh) / 2 - 6), label,
                   font=lfont, fill=lcol)

    if subtitle:
        sw, shh = _text_size(d, subtitle, sfont)
        d.text(((W - sw) / 2, gy + grid + 12), subtitle, font=sfont, fill="#555555")

    out = _os.path.join(_tempfile.gettempdir(),
                        f"bingo_{_os.getpid()}_{random.randint(1, 999999)}.png")
    img.save(out)
    return out, img.size
