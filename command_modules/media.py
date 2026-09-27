"""TalkinChat media commands routed through the transport adapter."""

import asyncio

from registry import command
from services import draw, images, music


@command("img", aliases=("image", "wlp"), help="Search an image", category="Images", needs_room=True)
async def image(bot, context):
    url = await asyncio.to_thread(images.search_image, context.args)
    if url:
        await bot.transport.send_image(context.room, url)
    else:
        await bot.reply(context, "No image found.")


@command("gif", help="Search a GIF", category="Images", needs_room=True)
async def gif(bot, context):
    url = await asyncio.to_thread(images.search_gif, context.args)
    if url:
        await bot.transport.send_image(context.room, url)
    else:
        await bot.reply(context, "No GIF found.")


@command("draw2", help="Draw text on a canvas", category="Images", needs_room=True)
async def draw_canvas(bot, context):
    path = await asyncio.to_thread(draw.draw_on_canvas, context.args)
    try:
        url = await bot.transport.upload(path, context.room, "image/png")
        await bot.transport.send_image(context.room, url)
    finally:
        try:
            __import__("os").remove(path)
        except OSError:
            pass


@command("play", aliases=("aud", "get"), help="Play a YouTube song", category="Music", needs_room=True)
async def play(bot, context):
    song = await asyncio.to_thread(music.scrape_music_from_yt, context.args)
    if not song:
        await bot.reply(context, "No playable song found.")
        return
    await bot.transport.send_audio(context.room, song.url, song.duration)


@command("jio", help="Play a JioSaavn song", category="Music", needs_room=True)
async def jio(bot, context):
    songs = await asyncio.to_thread(music.jio_query, context.args, 1)
    if not songs:
        await bot.reply(context, "No playable song found.")
        return
    await bot.transport.send_audio(context.room, songs[0].url, songs[0].duration)


@command("imagine", help="Generate AI art", category="Images", needs_room=True)
async def imagine(bot, context):
    await bot.reply(context, "AI image generation is unavailable until provider credentials are configured.")
