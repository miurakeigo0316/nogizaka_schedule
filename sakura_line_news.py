import os
import datetime
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import gspread
import json
from google.oauth2.service_account import Credentials


# LINE v3 SDK
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)


# --- 設定 ---
def get_settings_from_sheet():
    # GitHub Secretに保存したJSON鍵を読み込み
    service_account_info = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    client = gspread.authorize(creds)

    # スプレッドシートを開く（IDを書き換えてください）
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    sheet = client.open_by_key(spreadsheet_id).worksheet("settings")

    data = sheet.get_all_records()

    # 各項目を整理して辞書にまとめる
    settings = {
        "token": next((d["内容1"] for d in data if d["項目"] == "LINE_TOKEN"), None),
        "dest_list": [d["内容1"] for d in data if d["項目"] == "LINE_DEST"],
        "members": {d["内容1"]: d["内容2"] for d in data if d["項目"] == "PUSH_MEMBER"},
    }
    return settings


settings = get_settings_from_sheet()
CHANNEL_ACCESS_TOKEN = settings.get("token")
USER_ID = settings.get("dest_list")
LAST_TITLE_FILE = "last_title_sakura.txt"

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

# 1週間前の日付境界
one_week_ago = datetime.datetime.now() - datetime.timedelta(days=7)

# 前回タイトル読み込み
last_title = ""
if os.path.exists(LAST_TITLE_FILE):
    with open(LAST_TITLE_FILE, "r", encoding="utf-8") as f:
        last_title = f.read().strip()

# ヘッドレスブラウザ起動
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
# ブラウザの言語を日本語に強制設定
options.add_argument("--lang=ja-JP")
options.add_experimental_option("prefs", {"intl.accept_languages": "ja"})

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()), options=options
)

try:
    driver.get("https://www.nogizaka46.com/s/n46/news/list?ima=1000")
    time.sleep(10)  # 読み込み待機
    soup = BeautifulSoup(driver.page_source, "html.parser")
    news_items = soup.find_all("li", {"class": "newsItem"})

    new_messages = []
    current_latest_title = ""

    for i, news in enumerate(news_items):
        title_element = news.find("div", {"class": "ttl"})
        if not title_element:
            continue
        title = title_element.text.strip()

        if i == 0:
            current_latest_title = title

        # 差分チェック
        if title == last_title:
            break

        # 日付チェック（1週間以内）
        date_str = news.find("p", {"class": "data"}).text.strip()
        try:
            news_date = datetime.datetime.strptime(date_str, "%Y.%m.%d")
            if news_date < one_week_ago:
                continue
        except:
            pass

        content = news.find("p", {"class": "cat_name"}).text.strip()
        link = news.find("a")["href"]

        new_messages.append(
            f"【乃木坂46 新着】\n\n📅 {date_str}\n🏷 {content}\n📢 {title}\n🔗 {link}"
        )

    if new_messages:
        # 最新の5件だけに絞る
        latest_5_posts = new_messages[:5]

        # LINEで読みやすいように「古い順」に並べて合体（一番下が最新になる）
        # もし一番上を最新にしたい場合は reversed() を外して latest_5_posts をそのまま使う
        combined_message = "【乃木坂46 新着まとめ (最新5件)】\n\n" + "\n\n---\n\n".join(
            reversed(latest_5_posts)
        )
        # # 古い順に並び替えて、区切り線で合体させる
        # combined_message = "【乃木坂46 新着まとめ】\n" + "\n\n---\n\n".join(
        #     reversed(new_messages)
        # )

        # 文字数オーバー対策（念のため）
        if len(combined_message) > 4500:
            combined_message = combined_message[:4400] + "\n...以下省略"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            # リスト（USER_ID）の中身を一人ずつループして送る
            for target_id in USER_ID:
                try:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=target_id,  # ここをループの変数に変える
                            messages=[TextMessage(text=combined_message)],
                        )
                    )
                    print(f"送信成功: {target_id}")
                except Exception as e:
                    print(f"送信失敗 ({target_id}): {e}")

    # 最新タイトルを保存して終了
    if current_latest_title:
        with open(LAST_TITLE_FILE, "w", encoding="utf-8") as f:
            f.write(current_latest_title)

finally:
    driver.quit()
