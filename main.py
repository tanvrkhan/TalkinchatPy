#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# Created By  : DB (dbh4ck)
# Created Date: Sat, September 18 18:00:00 UTC 2021
# Author Email: dbh4ck@gmail.com

# For more info: https://dbh4ck.blogspot.com
# =============================================================================
"""A Simple Client Module to connect Talkinchat Server using websocket in Python"""
# =============================================================================
# Talkinchat username: docker
# =============================================================================

from __future__ import unicode_literals

import os
import websockets
import asyncio
import json
import urllib
import random
import requests
from urllib.parse import urlencode

from requests_toolbelt.multipart.encoder import MultipartEncoder
import ImageUrl
import pyaztro
import youtube_dl

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import textwrap
from io import BytesIO


# ===================================================================== AI CHAT BOT ===================================================================== 
''' 
    AI Chat Bot
'''
# import spacy
# spacy.load('en_core_web_sm')
# from chatterbot import ChatBot
# from chatterbot.trainers import ChatterBotCorpusTrainer

# my_bot = ChatBot(name='DB AI Bot', read_only=True,
#                 logic_adapters=['chatterbot.logic.MathematicalEvaluation',
#                                'chatterbot.logic.BestMatch'])

# corpus_trainer = ChatterBotCorpusTrainer(my_bot)
# corpus_trainer.train('chatterbot.corpus.english')
# ===================================================================== AI CHAT BOT ===================================================================== 


######### OTHERs ########
ID = "id"
NAME = "name"
USERNAME = "username"
PASSWORD = "password"
ROOM = "room"
TYPE = "type"
HANDLER = "handler"
ALLOWED_CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"
########## ------- ##########


########## SOCKET ########
SOCKET_URL = "wss://chatp.net:5333/server"
FILE_UPLOAD_URL = "https://cdn.talkinchat.com/post.php"
########## ------- ##########


######## MSGs #########
MSG_BODY = "body"
MSG_FROM = "from"
MSG_TO = "to"
MSG_TYPE_TXT = "text"
MSG_TYPE_IMG = "image"
MSG_TYPE_AUDIO = "audio"
MSG_URL = "url"
MSG_LENGTH = "length"
########## ------- ##########


######### Handlers #########
HANDLER_LOGIN = "login"
HANDLER_LOGIN_EVENT = "login_event"
HANDLER_ROOM_JOIN = "room_join"
HANDLER_ROOM_LEAVE = "room_leave"
HANDLER_ROOM_EVENT = "room_event"
HANDLER_ROOM_MESSAGE = "room_message"
HANDLER_CHAT_MESSAGE = "chat_message"
HANDLER_PROFILE_OTHER = "profile_other"
EVENT_TYPE_SUCCESS = "success"
########## ------- ##########


######### CREDENTIALS AND ROOM SETTINGS - CHANGE THIS #########
BOT_MASTER_ID = "docker"
GROUP_TO_INIT_JOIN = "london"
BOT_ID = "BOT_ID_XX"
BOT_PWD = "BOT_PWD_XX"
########## ------- ##########

IMG_TYPE_PNG = "image/png"
IMG_TYPE_JPG = "image/jpeg"
IMG_BG_COLOR = "black"
TEXT_FONT_COLOR = "black"
AUDIO_DURATION = 0
LAST_MUSIC_URL = ''
IMG_TXT_FONTS = r'fonts/Merienda-Regular.ttf'

ydl_opts = {
    'quiet': True,
    'noplaylist': True
}

TTS_LANG = "en" 
GOOGLE_TTS_HEADERS = {
        "Referer": "http://translate.google.com/",
        "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; WOW64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/47.0.2526.106 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
}

auto_reply_list = []

COLOR_LIST = ["#F0F8FF","#FAEBD7","#FFEFDB","#EEDFCC","#CDC0B0","#8B8378","#00FFFF","#7FFFD4","#76EEC6","#66CDAA","#458B74","#F0FFFF","#E0EEEE","#C1CDCD","#838B8B","#E3CF57","#F5F5DC","#FFE4C4","#EED5B7","#CDB79E","#8B7D6B","#000000","#FFEBCD","#0000FF","#0000EE","#0000CD","#00008B","#8A2BE2","#9C661F","#A52A2A","#FF4040","#EE3B3B","#CD3333","#8B2323","#DEB887","#FFD39B","#EEC591","#CDAA7D","#8B7355","#8A360F","#8A3324","#5F9EA0","#98F5FF","#8EE5EE","#7AC5CD","#53868B","#FF6103","#FF9912","#ED9121","#7FFF00","#76EE00","#66CD00","#458B00","#D2691E","#FF7F24","#EE7621","#CD661D","#8B4513","#3D59AB","#3D9140","#808A87","#FF7F50","#FF7256","#EE6A50","#CD5B45","#8B3E2F","#6495ED","#FFF8DC","#EEE8CD","#CDC8B1","#8B8878","#DC143C","#00EEEE","#00CDCD","#008B8B","#B8860B","#FFB90F","#EEAD0E","#CD950C","#8B6508","#A9A9A9","#006400","#BDB76B","#556B2F","#CAFF70","#BCEE68","#A2CD5A","#6E8B3D","#FF8C00","#FF7F00","#EE7600","#CD6600","#8B4500","#9932CC","#BF3EFF","#B23AEE","#9A32CD","#68228B","#E9967A","#8FBC8F","#C1FFC1","#B4EEB4","#9BCD9B","#698B69","#483D8B","#2F4F4F","#97FFFF","#8DEEEE","#79CDCD","#528B8B","#00CED1","#9400D3","#FF1493","#EE1289","#CD1076","#8B0A50","#00BFFF","#00B2EE","#009ACD","#00688B","#696969","#1E90FF","#1C86EE","#1874CD","#104E8B","#FCE6C9","#00C957","#B22222","#FF3030","#EE2C2C","#CD2626","#8B1A1A","#FF7D40","#FFFAF0","#228B22","#DCDCDC","#F8F8FF","#FFD700","#EEC900","#CDAD00","#8B7500","#DAA520","#FFC125","#EEB422","#CD9B1D","#8B6914","#808080","#030303","#1A1A1A","#1C1C1C","#1F1F1F","#212121","#242424","#262626","#292929","#2B2B2B","#2E2E2E","#303030","#050505","#333333","#363636","#383838","#3B3B3B","#3D3D3D","#404040","#424242","#454545","#474747","#4A4A4A","#080808","#4D4D4D","#4F4F4F","#525252","#545454","#575757","#595959","#5C5C5C","#5E5E5E","#616161","#636363","#0A0A0A","#666666","#6B6B6B","#6E6E6E","#707070","#737373","#757575","#787878","#7A7A7A","#7D7D7D","#0D0D0D","#7F7F7F","#828282","#858585","#878787","#8A8A8A","#8C8C8C","#8F8F8F","#919191","#949494","#969696","#0F0F0F","#999999","#9C9C9C","#9E9E9E","#A1A1A1","#A3A3A3","#A6A6A6","#A8A8A8","#ABABAB","#ADADAD","#B0B0B0","#121212","#B3B3B3","#B5B5B5","#B8B8B8","#BABABA","#BDBDBD","#BFBFBF","#C2C2C2","#C4C4C4","#C7C7C7","#C9C9C9","#141414","#CCCCCC","#CFCFCF","#D1D1D1","#D4D4D4","#D6D6D6","#D9D9D9","#DBDBDB","#DEDEDE","#E0E0E0","#E3E3E3","#171717","#E5E5E5","#E8E8E8","#EBEBEB","#EDEDED","#F0F0F0","#F2F2F2","#F7F7F7","#FAFAFA","#FCFCFC","#008000","#00FF00","#00EE00","#00CD00","#008B00","#ADFF2F","#F0FFF0","#E0EEE0","#C1CDC1","#838B83","#FF69B4","#FF6EB4","#EE6AA7","#CD6090","#8B3A62","#CD5C5C","#FF6A6A","#EE6363","#CD5555","#8B3A3A","#4B0082","#FFFFF0","#EEEEE0","#CDCDC1","#8B8B83","#292421","#F0E68C","#FFF68F","#EEE685","#CDC673","#8B864E","#E6E6FA","#FFF0F5","#EEE0E5","#CDC1C5","#8B8386","#7CFC00","#FFFACD","#EEE9BF","#CDC9A5","#8B8970","#ADD8E6","#BFEFFF","#B2DFEE","#9AC0CD","#68838B","#F08080","#E0FFFF","#D1EEEE","#B4CDCD","#7A8B8B","#FFEC8B","#EEDC82","#CDBE70","#8B814C","#FAFAD2","#D3D3D3","#FFB6C1","#FFAEB9","#EEA2AD","#CD8C95","#8B5F65","#FFA07A","#EE9572","#CD8162","#8B5742","#20B2AA","#87CEFA","#B0E2FF","#A4D3EE","#8DB6CD","#607B8B","#8470FF","#778899","#B0C4DE","#CAE1FF","#BCD2EE","#A2B5CD","#6E7B8B","#FFFFE0","#EEEED1","#CDCDB4","#8B8B7A","#32CD32","#FAF0E6","#FF00FF","#EE00EE","#CD00CD","#8B008B","#03A89E","#800000","#FF34B3","#EE30A7","#CD2990","#8B1C62","#BA55D3","#E066FF","#D15FEE","#B452CD","#7A378B","#9370DB","#AB82FF","#9F79EE","#8968CD","#5D478B","#3CB371","#7B68EE","#00FA9A","#48D1CC","#C71585","#E3A869","#191970","#BDFCC9","#F5FFFA","#FFE4E1","#EED5D2","#CDB7B5","#8B7D7B","#FFE4B5","#FFDEAD","#EECFA1","#CDB38B","#8B795E","#000080","#FDF5E6","#808000","#6B8E23","#C0FF3E","#B3EE3A","#9ACD32","#698B22","#FF8000","#FFA500","#EE9A00","#CD8500","#8B5A00","#FF4500","#EE4000","#CD3700","#8B2500","#DA70D6","#FF83FA","#EE7AE9","#CD69C9","#8B4789","#EEE8AA","#98FB98","#9AFF9A","#90EE90","#7CCD7C","#548B54","#BBFFFF","#AEEEEE","#96CDCD","#668B8B","#DB7093","#FF82AB","#EE799F","#CD6889","#8B475D","#FFEFD5","#FFDAB9","#EECBAD","#CDAF95","#8B7765","#33A1C9","#FFC0CB","#FFB5C5","#EEA9B8","#CD919E","#8B636C","#DDA0DD","#FFBBFF","#EEAEEE","#CD96CD","#8B668B","#B0E0E6","#800080","#9B30FF","#912CEE","#7D26CD","#551A8B","#872657","#C76114","#FF0000","#EE0000","#CD0000","#8B0000","#BC8F8F","#FFC1C1","#EEB4B4","#CD9B9B","#8B6969","#4169E1","#4876FF","#436EEE","#3A5FCD","#27408B","#FA8072","#FF8C69","#EE8262","#CD7054","#8B4C39","#F4A460","#308014","#54FF9F","#4EEE94","#43CD80","#2E8B57","#FFF5EE","#EEE5DE","#CDC5BF","#8B8682","#5E2612","#8E388E","#C5C1AA","#71C671","#555555","#1E1E1E","#282828","#515151","#5B5B5B","#848484","#8E8E8E","#B7B7B7","#C1C1C1","#EAEAEA","#F4F4F4","#7D9EC0","#AAAAAA","#8E8E38","#C67171","#7171C6","#388E8E","#A0522D","#FF8247","#EE7942","#CD6839","#8B4726","#C0C0C0","#87CEEB","#87CEFF","#7EC0EE","#6CA6CD","#4A708B","#6A5ACD","#836FFF","#7A67EE","#6959CD","#473C8B","#708090","#C6E2FF","#B9D3EE","#9FB6CD","#6C7B8B","#FFFAFA","#EEE9E9","#CDC9C9","#8B8989","#00FF7F","#00EE76","#00CD66","#008B45","#4682B4","#63B8FF","#5CACEE","#4F94CD","#36648B","#D2B48C","#FFA54F","#EE9A49","#CD853F","#8B5A2B","#008080","#D8BFD8","#FFE1FF","#EED2EE","#CDB5CD","#8B7B8B","#FF6347","#EE5C42","#CD4F39","#8B3626","#40E0D0","#00F5FF","#00E5EE","#00C5CD","#00868B","#00C78C","#EE82EE","#D02090","#FF3E96","#EE3A8C","#CD3278","#8B2252","#808069","#F5DEB3","#FFE7BA","#EED8AE","#CDBA96","#8B7E66","#FFFFFF","#F5F5F5","#FFFF00","#EEEE00","#CDCD00","#8B8B00"]

async def on_message(ws, data):
    global IMG_BG_COLOR
    global TEXT_FONT_COLO

    msg = data[MSG_BODY]
    frm = data[MSG_FROM]
    room = data[ROOM]
    user_avi = data['avatar_url']
    
    if frm == BOT_ID:
           return

    if user_avi is None:
        return

    if msg.startswith("!say "):
        raw_query = msg.split()
        txt = ' '.join(raw_query[2:])
        # query = msg[5:]
        
        res = requests.get(tts_url(txt, raw_query[1]), headers = GOOGLE_TTS_HEADERS)
        
        if res.url is not None:
            await send_group_msg_audio(ws, room, frm, res.url)
        else:
            await send_group_msg(ws, room, "Something went wrong!")

    # Music Bot, Scrape from youtube
    '''
        Scrape Data from youtube, extract mp3 and send it to the Group
        Songs, short clips, movies trailers, etc.
    '''

    if msg.startswith("!horo "):
        query = msg.split()

        zodiac_sign  = query[1].lower()
        ur_day = query[2].lower()

        if zodiac_sign is None or ur_day is None:
            await send_group_msg(ws, room, "Sign & Day Required!\n\n For eg., !horo scorpio today\n!horo aries yesterday\n!horo cancer tomorrow")
            return

        # params = (
        #         ('sign', 'aries'),
        #         ('day', 'today'),
        #         )

        # res = requests.post('https://aztro.sameerkumar.website/', params=params)
        # print(res.text)      
        dic = {'aries':'♈', 'taurus': '♉', 'gemini': '♊',
           'cancer': '♋', 'leo': '♌', 'virgo': '♍',
           'libra': '♎', 'scorpio': '♏', 'sagittarius': '♐',
           'capricorn': '♑', 'aquarius': '♒', 'pisces': '♓'}
        #print(dic[zodiac_sign])
        horoscope = pyaztro.Aztro(sign = zodiac_sign, day = ur_day)
        msgStr = f'''{frm} :  {dic[zodiac_sign]} Your horosope details:\n\n📆 Current Date: {horoscope.current_date}\n\n🈯 Description: {horoscope.description}\n\n🍭 Mood: {horoscope.mood}\n\n🎨 Color: {horoscope.color}\n\n🔢 Lucky No. : {horoscope.lucky_number}\n\n🕗 Lucky Time: {horoscope.lucky_time}'''

        await send_group_msg(ws, room, msgStr)
        # print(horoscope.description)
        # print(horoscope.mood)
        # print(horoscope.color)
        # print(horoscope.lucky_number)
        # print(horoscope.lucky_time)
        # print(horoscope.current_date)

        # horo = HoroScope.HoroScope()
        # print("im here  ")
        # dic = {'Aries': 1, 'Taurus': 2, 'Gemini': 3,
        #    'Cancer': 4, 'Leo': 5, 'Virgo': 6,
        #    'Libra': 7, 'Scorpio': 8, 'Sagittarius': 9,
        #    'Capricorn': 10, 'Aquarius': 11, 'Pisces': 12}

        # print('Choose your zodiac sign from below list : \n',
        #     '[Aries,Taurus,Gemini,Cancer,Leo,Virgo,Libra,\
        #     Scorpio,Sagittarius,Capricorn,Aquarius,Pisces]')
    
        # zodiac_sign = dic[input("Input your zodiac sign : ")]
        # print("On which day you want to know your horoscope ?\n",
        #     "Yesterday\n", "Today\n", "Tomorrow\n")
    
        # day = input("Input the day : ").lower()
        # horoscope_text = horo.horoscope(zodiac_sign, day)
        # print(horoscope_text)
        # payload = {
        #     "format": "json",
        #     "url": "https://soundcloud.com/forss/flickermood"
        # }
        # response = requests.post("https://soundcloud.com/oembed", data = payload, headers = {'Content-Type': 'application/x-www-form-urlencoded'})
        # print(response.text)

    

    if msg.startswith("!play "):
        global LAST_MUSIC_URL    
        search_music = msg[6:]
        music_url = scrape_music_from_yt(search_music)

        if music_url is not None and len(music_url) > 0:
            LAST_MUSIC_URL = music_url
            await send_group_msg_audio(ws, room, frm, music_url)
        else:
            await send_group_msg(ws, room, f"No song found for {search_music}!")

    
    if msg.startswith("!share "):
        target_id = msg[7:]

        if LAST_MUSIC_URL is not None and len(LAST_MUSIC_URL) > 0:
            if target_id is not None:
                await send_pvt_msg_audio(ws, room, frm, target_id, LAST_MUSIC_URL)
        else:
            await send_group_msg(ws, room, f"No song found for sharing!")


    # ===================================================================== AI CHAT BOT =====================================================================         
    '''
        AI ChatBot
    '''
    # if msg.startswith("!ar 1"):
    #     print("here")
    #     auto_reply_list.append(str(frm))


    # if msg.startswith("!ar 0"):
    #     print("here")
    #     auto_reply_list.remove(str(frm))

    # '''
    #     Uncomment below code to activate Auto-Reply Bot
    #     AI Bot Trained in English Corpuse
    #     For more info: chatterbot // Github
    # '''

    # if frm in auto_reply_list:
    #     resp = my_bot.get_response(msg)
    #     await send_group_msg(ws, room, frm + ": " + str(resp))
    # ===================================================================== AI CHAT BOT ===================================================================== 



    # image Scrape Using Bing Search
    '''
        Search Images from Bing Search &
        Sends the Images in groups
    '''

    if msg.startswith("!ud "):
        query = msg[4:]
        quoted_query = urllib.request.quote(query).replace("%20","")
        url = 'http://api.urbandictionary.com/v0/define?term=%s' % quoted_query
        response = urllib.request.urlopen(url)
        data = json.loads(response.read())

        if len(data['list']) == 0:
            await send_group_msg(ws, room, f"No result found for {query}")
        else:
            definition = data['list'][0]['definition']
            await send_group_msg(ws, room, f"Word: {query}\nDefinition: {definition}")

    if msg.startswith("!img "):
        keyword = msg[5:]
        imgParser = ImageUrl.ImageUrl()
        url = imgParser.search_images_from_bing(keyword)
        if url is None:
            await send_group_msg(ws, room, "No Image Found!")
        else:
            await send_group_msg_image(ws, room, url)
               
    # Leave Current Group
    if msg.startswith("!quit") and frm == BOT_MASTER_ID:
        await leave_group(ws, room)

    # Join Another Group
    if frm == BOT_MASTER_ID and msg.startswith("!join "):
        room = msg[6:]
        await join_group(ws, room)
        
    # Change Canvas Background Color    
    if frm == BOT_MASTER_ID and msg.startswith("!bgcolor "):
        IMG_BG_COLOR = msg[9:]

    # Change Fonts Color
    if frm == BOT_MASTER_ID and msg.startswith("!fc "):
        TEXT_FONT_COLOR = msg[4:]

    # Simple Text on Simple Canvas
    if(msg.startswith("!draw2 ")):
        #msg = msg[6:]
        #print(msg)
        img_color_rnd = COLOR_LIST[random.randrange(len(COLOR_LIST))]
        image = Image.new('RGB', (800, 600), color = img_color_rnd)
        image.filter(ImageFilter.GaussianBlur(radius = 25))
        font = ImageFont.truetype(IMG_TXT_FONTS, 60)
        text1 = msg[7:]
        color_txt_rnd = COLOR_LIST[random.randrange(len(COLOR_LIST))]
        text_start_height = 150
        draw_multiple_line_text(image, text1, font, color_txt_rnd, text_start_height)
        image.save('pil_text.png')
        
        link = upload_image_php("pil_text.png", "pil_text.png", room, IMG_TYPE_PNG)
        #print(link)
        if link is None:
            await send_group_msg(ws, room, "Error Sending File")
        else:
            await send_group_msg_image(ws, room, link)

    # Draw Text on Avatars
    if(msg.startswith("!draw ")):
        msg = msg[6:]
        font = ImageFont.truetype(IMG_TXT_FONTS, 60)
        text_color = (200, 200, 200)
        text_start_height = 300
        size = 800,800
        response = requests.get(user_avi)

        avatar = Image.open(BytesIO(response.content))
        avatar1 = avatar.resize(size, Image.ANTIALIAS)
        avatar2 = avatar1.filter(ImageFilter.GaussianBlur(radius = 15))
        color_txt_rnd = COLOR_LIST[random.randrange(len(COLOR_LIST))]
        draw_multiple_line_text(avatar2, msg, font, color_txt_rnd, text_start_height)
        avatar2.save('pil_text.png')
        link = upload_image_php("pil_text.png", "pil_text.png", room, IMG_TYPE_PNG)

        if link is None:
            await send_group_msg(ws, room, "Error Sending File")
        else:
            await send_group_msg_image(ws, room, link)


def tts_url(text, lang):
    return '?'.join([
        "https://translate.google.com/translate_tts",
        urlencode({
            "ie": "UTF-8",
            "q": text,  # quote_plus(text).replace('%20', '+')
            "tl": lang,
            "ttsspeed": "1",
            "total": "1",
            "idx": "0",
            "client": "tw-ob",
            "textlen": str(len(text))
        })
    ])

# Scrape Music
def scrape_music_from_yt(searchQuery):

    ydl = youtube_dl.YoutubeDL(ydl_opts)
    global AUDIO_DURATION

    with ydl:
            result = ydl.extract_info(
                f"ytsearch:{searchQuery}",
                download = False
            )

            AUDIO_DURATION = result['entries'][0]["duration"]
                
            formats = result['entries'][0]['formats']

            for data in formats:
                if data['format_id'] == '140':
                    if data['url'] is not None:
                        return data['url']
                    else:
                        return ''


# Upload Image to TalkinChat Server
def upload_image_php(fileName, filePath, roomName, imgType):
    # print("uploading image::::::")
    multipart_data = MultipartEncoder(
        fields = {
                'file': (fileName, open(filePath, 'rb'), imgType),
                'jid': BOT_ID,
                'is_private': 'no',
                'room': roomName,
                'device_id': gen_random_str(16)
               }
    )

    response = requests.post(FILE_UPLOAD_URL, data = multipart_data, headers = {'Content-Type': multipart_data.content_type})
    #print(response.text)
    return response.text


async def on_wc_draw(ws, data):
    # print(data[USERNAME])
    user = data[USERNAME]
    room = data[NAME]
    img_color_rnd = COLOR_LIST[random.randrange(len(COLOR_LIST))]
    image = Image.new('RGB', (800, 600), color = img_color_rnd)
    image.filter(ImageFilter.GaussianBlur(radius = 40))
    fontsize = 60  # starting font size
    font = ImageFont.truetype(IMG_TXT_FONTS, 60)
    text1 = f"Welcome  to  {room} \n {user} \n Enjoy your Stay!!!"

    text_color = COLOR_LIST[random.randrange(len(COLOR_LIST))]
    text_start_height = 150
    draw_multiple_line_text(image, text1, font, text_color, text_start_height)
    image.save('pil_text.png')

    link = upload_image_php("pil_text.png", "pil_text.png", room, IMG_TYPE_PNG)
    
    if link is None:
            await send_group_msg(ws, room, "Error Sending File")
    else:
            await send_group_msg_image(ws, room, link)

async def leave_group(ws, room):
    jsonbody = {HANDLER: HANDLER_ROOM_LEAVE, NAME: room, ID: gen_random_str(20)}
    await ws.send(json.dumps(jsonbody))


async def login(ws):
    jsonbody = {HANDLER: HANDLER_LOGIN, ID: gen_random_str(20), USERNAME: BOT_ID, PASSWORD: BOT_PWD}
    #print(jsonbody)
    await ws.send(json.dumps(jsonbody))


async def join_group(ws, group):
    jsonbody = {HANDLER: HANDLER_ROOM_JOIN, ID: gen_random_str(20), NAME: group}
    await ws.send(json.dumps(jsonbody))


async def send_group_msg(ws, room, msg):
    jsonbody = {HANDLER: HANDLER_ROOM_MESSAGE, ID: gen_random_str(20), ROOM: room, TYPE: MSG_TYPE_TXT, MSG_URL: "", MSG_BODY: msg, MSG_LENGTH: ""}
    await ws.send(json.dumps(jsonbody))

async def send_group_msg_image(ws, room, url):
    jsonbody = {HANDLER: HANDLER_ROOM_MESSAGE, ID: gen_random_str(20), ROOM: room, TYPE: MSG_TYPE_IMG, MSG_URL: url, MSG_BODY: "", MSG_LENGTH: ""}
    await ws.send(json.dumps(jsonbody))


async def send_group_msg_audio(ws, room, frm, url):    
    jsonbody = {HANDLER: HANDLER_ROOM_MESSAGE, ID: gen_random_str(20), ROOM: room, TYPE: MSG_TYPE_AUDIO, MSG_URL: url, MSG_BODY: "", MSG_LENGTH: f"{AUDIO_DURATION}"}
    if AUDIO_DURATION < 600:
        await ws.send(json.dumps(jsonbody))
    else:
        await send_group_msg(ws, room, f"{frm}: Song is longer than 10 minutes in duration!!!")


async def send_pvt_msg_audio(ws, room, frm, user, url):
    jsonbody = {HANDLER: HANDLER_CHAT_MESSAGE, ID: gen_random_str(20), MSG_TO: user, TYPE: MSG_TYPE_TXT, MSG_URL: "", MSG_BODY: f"{frm} sent you a song!!!", MSG_LENGTH: ""}
    jsonbody2 = {HANDLER: HANDLER_CHAT_MESSAGE, ID: gen_random_str(20), MSG_TO: user, TYPE: MSG_TYPE_AUDIO, MSG_URL: url, MSG_BODY: "", MSG_LENGTH: f"{AUDIO_DURATION}"}
    
    if AUDIO_DURATION < 600:
        await ws.send(json.dumps(jsonbody))
        await ws.send(json.dumps(jsonbody2))
        
        await send_group_msg(ws, room, f"Song has been sent to {user} by {frm}")
    else:
        await send_group_msg(ws, room, f"{frm}: Song is longer than 10 minutes in duration!!!")

    

def gen_random_str(length):
    return ''.join(random.choice(ALLOWED_CHARS) for i in range(length))


def draw_multiple_line_text(image, text, font, text_color, text_start_height):
    draw = ImageDraw.Draw(image)
    image_width, image_height = image.size
    y_text = text_start_height
    lines = textwrap.wrap(text, width=25)
    for line in lines:
        line_width, line_height = font.getsize(line)
        draw.text(((image_width - line_width) / 2, y_text), 
                  line, font=font, fill=text_color)
        y_text += line_height    
        
def add_corners(im, rad):
        circle = Image.new('L', (rad * 2, rad * 2), 0)
        draw = ImageDraw.Draw(circle)
        draw.ellipse((0, 0, rad * 2, rad * 2), fill=255)
        alpha = Image.new('L', im.size, 255)
        w, h = im.size
        alpha.paste(circle.crop((0, 0, rad, rad)), (0, 0))
        alpha.paste(circle.crop((0, rad, rad, rad * 2)), (0, h - rad))
        alpha.paste(circle.crop((rad, 0, rad * 2, rad)), (w - rad, 0))
        alpha.paste(circle.crop((rad, rad, rad * 2, rad * 2)), (w - rad, h - rad))
        im.putalpha(alpha)
        return im


async def start_bot():
    websocket = await websockets.connect(SOCKET_URL, ssl=True)
    await login(websocket)

    while True:
        if not websocket.open:
            try:
                print('Websocket is NOT connected. Reconnecting...')
                websocket = await websockets.connect(SOCKET_URL, ssl=True)
                await login(websocket)
            except:
                print('Unable to reconnect, trying again.')

        try:
            async for payload in websocket:
                if payload is not None:
                    data = json.loads(payload)
                    handler = data[HANDLER]

                    if handler == HANDLER_LOGIN_EVENT and data[TYPE] == EVENT_TYPE_SUCCESS:
                        print("Logged In SUCCESS")
                        await join_group(websocket, GROUP_TO_INIT_JOIN)

                
                    elif handler == HANDLER_ROOM_EVENT and data[TYPE] == MSG_TYPE_TXT:
                        await on_message(websocket, data)

                    elif handler == HANDLER_ROOM_EVENT and data[TYPE] == "user_joined":
                        await on_wc_draw(websocket, data)                            

        except:
            print('Error receiving message from websocket.')

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
    loop.run_forever()
