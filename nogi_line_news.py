import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from linebot import LineBotApi
from linebot.models import TextSendMessage

# --- 設定 ---
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
USER_ID = os.environ["LINE_USER_ID"]
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

# 前回保存したタイトルを読み込む
LAST_TITLE_FILE = "last_title.txt"
last_title = ""
if os.path.exists(LAST_TITLE_FILE):
    with open(LAST_TITLE_FILE, "r", encoding="utf-8") as f:
        last_title = f.read().strip()

# ヘッドレスブラウザ設定
options = Options()
options.add_argument("--headless")
driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()), options=options
)

try:
    driver.get("https://www.nogizaka46.com/s/n46/news/list?ima=1000")
    soup = BeautifulSoup(driver.page_source, "html.parser")
    news_items = soup.find_all("li", {"class": "newsItem"})

    new_messages = []
    current_latest_title = ""

    for i, news in enumerate(news_items):
        title = news.find("div", {"class": "ttl"}).text.strip()

        # 1件目のタイトルを記録（次回の比較用）
        if i == 0:
            current_latest_title = title

        # 前回送ったタイトルと同じものを見つけたら、それ以降は古い記事なのでストップ
        if title == last_title:
            break

        # 差分（新着）情報を組み立て
        date = news.find("p", {"class": "data"}).text.strip()
        content = news.find("p", {"class": "cat_name"}).text.strip()
        link = "https://www.nogizaka46.com" + news.find("a")["href"]
        new_messages.append(
            f"【乃木坂46 新着】\n\n📅 {date}\n🏷 {content}\n📢 {title}\n🔗 {link}"
        )

    # 新着があればLINE送信（古い順に送るため逆順にする）
    for msg in reversed(new_messages):
        line_bot_api.push_message(USER_ID, TextSendMessage(text=msg))

    # 最新のタイトルをファイルに保存
    if current_latest_title:
        with open(LAST_TITLE_FILE, "w", encoding="utf-8") as f:
            f.write(current_latest_title)

finally:
    driver.quit()
