import requests
from bs4 import BeautifulSoup

class HoroScope(object):

    def __init__(self):
        '''
            Horoscope Class
        '''
        global key

    def horoscope(zodiac_sign: int, day: str) -> str:
        url = (
            "https://www.horoscope.com/us/horoscopes/general/"
            f"horoscope-general-daily-{day}.aspx?sign={zodiac_sign}"
        )

        soup = BeautifulSoup(requests.get(url).content, "html.parser")
    
        # print(soup.find("div", class_="main-horoscope").p.text)
        return soup.find("div", class_="main-horoscope").p.text


if __name__ == "__main__":
    #HoroScope()
    HoroScope()