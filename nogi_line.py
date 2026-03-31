from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# import pandas as pd
import datetime

import re

# import time as tm
from linebot import LineBotApi
from linebot.models import TextSendMessage
import os

# import sys

import gspread
from google.oauth2.service_account import Credentials
import json


def get_settings_from_sheet():
    # GitHub Secret から JSON 鍵を取得
    service_account_info = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    client = gspread.authorize(creds)

    # スプレッドシートを開く（URLまたはタイトルで指定）
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    sheet = client.open_by_key(spreadsheet_id).worksheet("settings")

    # 全データを取得
    data = sheet.get_all_records()

    # 整理して返す
    settings = {
        "token": next(d["内容1"] for d in data if d["項目"] == "LINE_TOKEN"),
        # LINE_DEST の行から「内容1」をすべてリストで取る（複数対応）
        "dest_list": [d["内容1"] for d in data if d["項目"] == "LINE_DEST"],
        "members": {d["内容1"]: d["内容2"] for d in data if d["項目"] == "PUSH_MEMBER"},
    }
    return settings


# 1. ヘッドレスモード（画面を出さない設定）を作る
options = Options()
options.add_argument("--headless")  # 必須：画面なしで動かす
options.add_argument("--no-sandbox")  # 必須：セキュリティ制限を回避
options.add_argument("--disable-dev-shm-usage")  # 必須：メモリ不足エラーを回避
options.add_argument("--lang=ja-JP")

# 2. 「私は日本語のページを希望します」という情報をブラウザに持たせる
options.add_experimental_option("prefs", {"intl.accept_languages": "ja,ja-JP"})

# 3. ユーザーエージェント（ブラウザの種類）を日本のPCっぽく見せる
options.add_argument(
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

# 2. 設定を渡して起動する
driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()), options=options
)

today = datetime.date.today()
year = today.strftime("%Y")
month = today.strftime("%m")

# URLにクエリパラメータを正しく渡す
url = f"https://www.nogizaka46.com/s/n46/media/list?ima=1000&dy={year}{month}&lang=ja"
driver.get(url)

all_data = []

try:
    # スケジュール全体を包む要素（sc--day）が表示されるまで待機
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "sc--day"))
    )

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    # 日付ごとのブロックを取得（これで日付順が保証されます）
    days = soup.find_all("div", class_="sc--day")

    for d in days:
        day_text = d.find("p", class_="sc--day__d").get_text(strip=True)
        week_text = d.find("p", class_="sc--day__w").get_text(strip=True)

        # 「日付(曜日)」の形に整える
        full_date = f"{day_text}({week_text})"

        # その日の中にある各スケジュール項目を取得
        items = d.find_all("div", class_="m--scone")

        for item in items:
            # 時刻タグの取得
            time_tag = item.find("p", class_="m--scone__st")
            time = time_tag.get_text(strip=True) if time_tag else ""

            # 【追加】時刻がない（空文字）の場合は出力せずにスキップ
            # if not time:
            #    continue

            content = item.find("p", class_="m--scone__cat__name").get_text(strip=True)
            title = item.find("p", class_="m--scone__ttl").get_text(strip=True)
            link = item.find("a")["href"] if item.find("a") else ""

            # print(f"日付: {full_date})")
            # if time:
            #    print(f"時間: {time}")
            # print(f"ジャンル: {content}")
            # print(f"タイトル: {title}")
            # print("-" * 20)

            all_data.append(
                {
                    "日付": full_date,
                    "媒体": content,
                    "タイトル": title,
                    "時間": time,  # timeが空でも列として作成される
                    "リンク": link,
                }
            )
finally:
    driver.quit()

gcal_data = []
# --- Googleカレンダー用CSV出力 ---
if all_data:
    for item in all_data:
        # 日付の整形 (例: "15(月)" -> "2026/03/15")
        day_only = item["日付"].split("(")[0]
        start_date = f"{year}/{month}/{day_only}"

        subject = f"[{item['媒体']}] {item['タイトル']}"
        raw_time = item["時間"]  # 例: "19:00" または "19:00～20:00"

        start_time = ""
        end_time = ""
        all_day = "True"

        if raw_time:
            # 「数字:数字」のパターンをすべて抜き出す
            # これにより、記号が何であっても「19:00」と「20:00」をリストとして取得できる
            time_matches = re.findall(r"\d{1,2}:\d{2}", raw_time)

            if len(time_matches) >= 2:
                # 開始と終了が分かれた場合
                start_time = time_matches[0]
                end_time = time_matches[1]
                all_day = "False"
            elif len(time_matches) == 1:
                # 開始時間しかない場合
                start_time = time_matches[0]
                all_day = "False"
                try:
                    h, m = map(int, start_time.split(":"))
                    # 24時超えも考慮
                    end_dt = datetime.datetime(
                        2000, 1, 1, h % 24, m
                    ) + datetime.timedelta(hours=1)
                    end_time = end_dt.strftime("%H:%M")
                except:
                    end_time = start_time
        else:
            all_day = "True"
        gcal_data.append(
            {
                "Subject": subject,
                "Start Date": start_date,
                "Start Time": start_time,
                "End Date": start_date,
                "End Time": end_time,
                "All Day Event": all_day,
                "Description": item["媒体"],
                "Link": item["リンク"],
            }
        )

#     # CSV出力（以下は前回と同じ）
#     # --- Googleカレンダー用CSV出力 ---
#     df_gcal = pd.DataFrame(gcal_data)

#     # 1. ファイル名を固定にする（これで実行のたびに同じファイルが更新される）
#     filename_csv = "gcal_import_now.csv"

#     # 2. カラム順を整理
#     columns = ["Subject", "Start Date", "Start Time", "End Date", "End Time",
# "All Day Event", "Description"]

#     # mode='w' (writeモード) はデフォルトですが、明示的に上書きを指定
#     # encoding='utf-8-sig' はExcelで文字化けさせないため
#     df_gcal[columns].to_csv(filename_csv, index=False, encoding="utf-8-sig", mode='w')

#     print("-" * 20)
#     print(f"Googleカレンダー用CSVを更新しました: {filename_csv}")
#     print("このファイルをGoogleカレンダーにインポートしてください。")


# --- Googleカレンダー登録処理 ---


def register_to_google_calendar(service, gcal_data):
    # 【重要】ここに新しいカレンダーIDを貼り付けてください
    target_id = os.environ.get("GOOGLE_CALENDAR_ID_NOGI")
    # --- 1. 既存の予定をリストアップ ---
    # 過去7日から未来30日分を取得（深夜番組や日付変更のズレを確実にカバー）
    time_min = (
        datetime.datetime.utcnow() - datetime.timedelta(days=7)
    ).isoformat() + "Z"
    events_result = (
        service.events()
        .list(
            calendarId=target_id,
            timeMin=time_min,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    existing_events = events_result.get("items", [])

    # 既存予定の (タイトル, 開始時間) のリストを作成
    existing_list = []
    for ev in existing_events:
        summary = ev.get("summary", "")
        # 開始時刻を取得 (終日なら 'date', 通常なら 'dateTime')
        raw_start = ev["start"].get("dateTime", ev["start"].get("date", ""))
        # 比較用に分単位までの16文字 (YYYY-MM-DDTHH:MM) に整える
        clean_start = raw_start[:16].replace(" ", "T")
        existing_list.append({"summary": summary, "start": clean_start})

    print(
        f"現在、カレンダーには {len(existing_list)} 件の予定があります。チェック開始..."
    )

    # --- 2. 登録ループ ---
    for data in gcal_data:
        try:
            # 日付・時刻整形（25時対応）
            start_date = data["Start Date"].replace("/", "-")

            def get_iso_time(date_str, time_str):
                h, m = map(int, time_str.split(":"))
                days_to_add = h // 24
                actual_h = h % 24
                base_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                actual_date = base_date + datetime.timedelta(days=days_to_add)
                return f"{actual_date.strftime('%Y-%m-%d')}T{actual_h:02d}:{m:02d}:00"

            # 比較用の時間データ作成
            if data["All Day Event"] == "True":
                current_start_16 = start_date[:16]
            else:
                current_start_16 = get_iso_time(start_date, data["Start Time"])[:16]

            # --- 重複チェック判定 ---
            is_duplicate = False
            current_summary = data["Subject"].strip()

            for ex_ev in existing_list:
                # A. 開始時間が一致している
                # B. タイトルがどちらかを含んでいる（部分一致）
                if (current_start_16 == ex_ev["start"]) and (
                    current_summary in ex_ev["summary"]
                    or ex_ev["summary"] in current_summary
                ):
                    is_duplicate = True
                    break

            if is_duplicate:
                print(f"スキップ: {data['Subject']} (登録済み)")
                continue

            # --- 予定の作成と送信 ---
            event_body = {
                "summary": data["Subject"],
                "description": data["Description"],
                "start": (
                    {"date": start_date}
                    if data["All Day Event"] == "True"
                    else {
                        "dateTime": get_iso_time(start_date, data["Start Time"]),
                        "timeZone": "Asia/Tokyo",
                    }
                ),
                "end": (
                    {"date": start_date}
                    if data["All Day Event"] == "True"
                    else {
                        "dateTime": get_iso_time(start_date, data["End Time"]),
                        "timeZone": "Asia/Tokyo",
                    }
                ),
            }

            service.events().insert(calendarId=target_id, body=event_body).execute()
            print(f"◎ 新規登録完了: {data['Subject']}")

        except Exception as e:
            print(f"× エラー: {data['Subject']} - {e}")

    # 実行


# register_to_google_calendar(service, gcal_data)


def print_tomorrow_schedule(gcal_data):
    # 1. 明日の日付を取得 (YYYY-MM-DD 形式)
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"【明日 {tomorrow} の乃木坂46 スケジュール】")
    print("-" * 30)

    found_count = 0

    for data in gcal_data:
        # データの開始日（YYYY-MM-DD）を取得
        # ※gcal_data['Start Date'] が '2024-05-21' のような形式である前提
        event_date = data["Start Date"].replace("/", "-")

        if event_date == tomorrow:
            found_count += 1
            time_str = "終日" if data["All Day Event"] == "True" else data["Start Time"]
            print(f"・{time_str} 〜 : {data['Subject']}")
            # もし詳細（出演メンバーなど）も見たければ以下を追加
            # print(f"   (詳細: {data['Description']})")

    if found_count == 0:
        print("明日の予定は今のところありません。")

    print("-" * 30)
    print(f"合計 {found_count} 件")


# 実行
# print_tomorrow_schedule(gcal_data)


def send_line_message_api(gcal_data, settings):
    # --- 設定（LINE Developersから取得した値を入力） ---
    # token = settings["token"]
    # dest_list = settings["dest_list"]
    # push_members = settings["members"]

    token = settings.get("token")
    dest_list = settings.get("dest_list")
    push_members = settings.get("members", {})

    if not token or not dest_list:
        print("エラー: LINEトークンまたは宛先がスプレッドシートにありません。")
        return

    line_bot_api = LineBotApi(token)

    # 1. 明日の日付を取得
    tomorrow_dt = datetime.date.today() + datetime.timedelta(days=1)
    tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")

    # 2. メッセージ本文の作成
    msg_text = f"【明日 {tomorrow_dt.strftime('%m/%d')} の乃木坂46】\n"

    found_count = 0
    # send_line_message_api 関数の中をチェック

    for data in gcal_data:
        event_date = data["Start Date"].replace("/", "-")

        if event_date == tomorrow_str:
            found_count += 1
            time_str = "終日" if data["All Day Event"] == "True" else data["Start Time"]
            subject = data["Subject"]  # ← ここ！直接取り出せば日本語になります
            description = data["Description"]
            url = data["Link"]

            # 推しメン判定
            matched_emoji = ""
            # スプレッドシートから取得したメンバーリストを1人ずつチェック
            for name, emoji in push_members.items():
                # 名前（漢字）が含まれているかチェック
                if name in description or name in subject:
                    matched_emoji = emoji
                    break  # 1人見つかったらその人の絵文字を採用してループを抜ける

            # もし誰かに該当したらマークを付ける
            if matched_emoji:
                subject = f"{matched_emoji}【推し】{subject}"

            msg_text += f"\n・{time_str}〜\n  {subject}\n"
            if url:
                msg_text += f"\n  {url}"  # ← ここでURLを改行して追加
            msg_text += "\n"

    if found_count == 0:
        msg_text += "\n明日の予定はありません。"
    else:
        msg_text += f"\n計 {found_count} 件"

    for user_id in dest_list:
        try:
            line_bot_api.push_message(user_id, TextSendMessage(text=msg_text))
            print(f"送信完了: {user_id}")
        except Exception as e:
            print(f"送信失敗 ({user_id}): {e}")

    # 3. 送信実行


if __name__ == "__main__":
    try:
        # スプレッドシートから設定を取得
        app_settings = get_settings_from_sheet()

        # gcal_data（スクレイピング結果）がある場合のみ送信
        # ※スクレイピング部分のコードがこの前に必要です
        if "gcal_data" in locals() or "gcal_data" in globals():
            send_line_message_api(gcal_data, app_settings)
        else:
            print("エラー: gcal_data が定義されていません。")

    except Exception as e:
        print(f"システム実行エラー: {e}")
