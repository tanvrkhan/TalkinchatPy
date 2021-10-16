import os, sys, re
import string
import random
import requests
import urllib.request, urllib.error, urllib.parse

from urllib.parse import urlencode, urlunparse
from urllib.request import urlopen, Request

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36'
headers = { 'User-Agent': USER_AGENT }

class ImageUrl(object):
    def __init__(self):
            global key

    def get_image_urls(self, query_key):

        query = query_key
        url = urlunparse(("https", "www.bing.com", "/images/async", "", urlencode({"q": query}), ""))
        custom_user_agent = "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0"
        req = Request(url, headers={"User-Agent": custom_user_agent})
        page = urlopen(req)
        html = page.read().decode('utf8')
                                                                      
        links = re.findall('murl&quot;:&quot;(.*?)&quot;',html)
        return links
    
    
    def search_images_from_bing(self, query_key):
        url_list = self.get_image_urls(query_key)
        if len(url_list) == 0:
            pass
        else:
            img_url = url_list[random.randrange(len(url_list))]
                                                                                                                                                      # print(ur)
            return img_url

if __name__ == "__main__":
    ImageUrl()