from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
DATA_FILE = "/app/data/results.json"
SENT_FILE = "/app/data/sent.json"

TELEGRAM_TOKEN = "8462761178:AAFH3KWgqk4tgJfYM3yyQasS7i3co-JaErg"
CHANNEL_ID = "-1003757967990"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return json.load(f)
    return {}

def save_sent(data):
    os.makedirs(os.path.dirname(SENT_FILE), exist_ok=True)
    with open(SENT_FILE, "w") as f:
        json.dump(data, f)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": CHANNEL_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def parse_tables(soup, data, sent, notify=False):
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        header = rows[0].get_text(strip=True)

        date_match = re.search(r'(\d{2}/\d{2}/\d{4})', header)
        today_match = re.search(r'(\w+),\s*(\d+)\s*(\w+)\s*(\d{4})', header)

        if date_match:
            date_key = date_match.group(1)
        elif today_match:
            day = today_match.group(2).zfill(2)
            month_str = today_match.group(3).upper()
            year = today_match.group(4)
            months = {
                "JANUARY":"01","FEBRUARY":"02","MARCH":"03","APRIL":"04",
                "MAY":"05","JUNE":"06","JULY":"07","AUGUST":"08",
                "SEPTEMBER":"09","OCTOBER":"10","NOVEMBER":"11","DECEMBER":"12"
            }
            month = months.get(month_str, "00")
            date_key = f"{day}/{month}/{year}"
        else:
            continue

        if len(rows) < 2:
            continue

        cells = rows[1].find_all("td")
        bazis = []
        for cell in cells:
            text = cell.get_text(strip=True)
            text = re.sub(r'Tips', '', text).strip()
            if text and re.match(r'^[\d-]+$', text) and len(text) >= 3:
                bazis.append(text)

        if not bazis:
            continue

        sent_bazis = sent.get(date_key, [])

        if notify:
            for i, bazi in enumerate(bazis):
                if bazi not in sent_bazis:
                    msg = (
                        f"🎯 <b>Kolkata FF Update</b>\n"
                        f"📅 Date: {date_key}\n"
                        f"🕐 Bazi {i+1}\n"
                        f"🔢 Result: <b>{bazi}</b>"
                    )
                    send_telegram(msg)
                    sent_bazis.append(bazi)

        data[date_key] = bazis
        sent[date_key] = sent_bazis

def scrape_month(month_name, year, data, sent, notify=False):
    try:
        url = f"https://kolkataff.tv/old-kolkata-ff-fatafat-result/monthly/index.php?month={month_name}&year={year}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        parse_tables(soup, data, sent, notify=notify)
        print(f"Scraped {month_name} {year}")
    except Exception as e:
        print(f"Error scraping {month_name} {year}: {e}")

def scrape_homepage(data, sent, notify=True):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://kolkataff.tv/", headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        parse_tables(soup, data, sent, notify=notify)
        print(f"[{datetime.now()}] Homepage scraped")
    except Exception as e:
        print(f"Homepage error: {e}")

def scrape_history():
    """Run once on startup — scrapes last 3 months, no Telegram spam"""
    data = load_data()
    sent = load_sent()

    month_names = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]

    today = datetime.now()
    for i in range(3):
        d = today - timedelta(days=30*i)
        scrape_month(month_names[d.month - 1], d.year, data, sent, notify=False)

    save_data(data)
    save_sent(sent)
    print(f"History load done — {len(data)} days stored")

def scrape():
    """Runs every 90 mins — only homepage, sends Telegram for new results"""
    data = load_data()
    sent = load_sent()
    scrape_homepage(data, sent, notify=True)
    save_data(data)
    save_sent(sent)
    print(f"[{datetime.now()}] Scraped OK — {len(data)} days stored")

@app.route("/")
def index():
    return "Kolkata FF Scraper Running"

@app.route("/results")
def results():
    data = load_data()
    sorted_data = dict(
        sorted(data.items(),
               key=lambda x: datetime.strptime(x[0], "%d/%m/%Y"),
               reverse=True)
    )
    return jsonify(sorted_data)

@app.route("/today")
def today():
    data = load_data()
    today_key = datetime.now().strftime("%d/%m/%Y")
    return jsonify({today_key: data.get(today_key, [])})

if __name__ == "__main__":
    scrape_history()   # Load 3 months silently on startup
    scrape()           # Then scrape homepage + start Telegram
    scheduler = BackgroundScheduler()
    scheduler.add_job(scrape, "interval", minutes=90)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)