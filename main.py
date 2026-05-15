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

BAZI_TIMES = ["10:00","11:30","13:00","14:30","16:00","17:30","19:00","20:30"]

def get_ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

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

def format_result(raw):
    """4565 -> 456-5, already formatted stays as is"""
    raw = raw.strip()
    if len(raw) == 4 and raw.isdigit():
        return f"{raw[:3]}-{raw[3]}"
    return raw

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": CHANNEL_ID,
            "text": message
        }, timeout=10)
        print(f"Telegram response: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Telegram error: {e}")

def parse_header_date(header):
    date_match = re.search(r'(\d{2}/\d{2}/\d{4})', header)
    if date_match:
        return date_match.group(1)

    today_match = re.search(r'\(?(\w+),?\s*(\d{1,2})\s+(\w+)\s+(\d{4})\)?', header)
    if today_match:
        day = today_match.group(2).zfill(2)
        month_str = today_match.group(3).upper()
        year = today_match.group(4)
        months = {
            "JANUARY":"01","FEBRUARY":"02","MARCH":"03","APRIL":"04",
            "MAY":"05","JUNE":"06","JULY":"07","AUGUST":"08",
            "SEPTEMBER":"09","OCTOBER":"10","NOVEMBER":"11","DECEMBER":"12"
        }
        month = months.get(month_str, "00")
        if month != "00":
            return f"{day}/{month}/{year}"
    return None

def extract_bazis(rows):
    cells = rows[1].find_all("td")
    bazis = []
    for cell in cells:
        text = cell.get_text(strip=True)
        digits = re.sub(r'[^0-9]', '', text)
        if len(digits) == 4:
            # Store in formatted form immediately
            bazis.append(f"{digits[:3]}-{digits[3]}")
    return bazis

def parse_tables(soup, data, sent, notify=False):
    today_key = get_ist_now().strftime("%d/%m/%Y")
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header = rows[0].get_text(strip=True)
        date_key = parse_header_date(header)
        if not date_key:
            continue

        bazis = extract_bazis(rows)
        if not bazis:
            continue

        sent_bazis = sent.get(date_key, [])

        if notify and date_key == today_key:
            for i, bazi in enumerate(bazis):
                if bazi not in sent_bazis:
                    bazi_time = BAZI_TIMES[i] if i < len(BAZI_TIMES) else "--:--"
                    msg = (
                        f"Kolkata FF Update\n"
                        f"Date: {date_key}\n"
                        f"Time: {bazi_time}\n"
                        f"Result: {bazi}"
                    )
                    send_telegram(msg)
                    sent_bazis.append(bazi)
                    print(f"Sent: {date_key} Bazi {i+1} = {bazi}")

        data[date_key] = bazis
        sent[date_key] = sent_bazis

def scrape_month(month_name, year, data, sent):
    try:
        url = f"https://kolkataff.tv/old-kolkata-ff-fatafat-result/monthly/index.php?month={month_name}&year={year}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        parse_tables(soup, data, sent, notify=False)
        print(f"Scraped history: {month_name} {year}")
    except Exception as e:
        print(f"Error: {month_name} {year}: {e}")

def scrape_history():
    data = load_data()
    sent = load_sent()

    month_names = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]

    today = get_ist_now()
    for i in range(3):
        d = today - timedelta(days=30*i)
        scrape_month(month_names[d.month - 1], d.year, data, sent)

    # Mark everything as sent — no spam on startup
    for date_key, bazis in data.items():
        sent[date_key] = bazis[:]

    save_data(data)
    save_sent(sent)
    print(f"History loaded — {len(data)} days stored")

def scrape():
    data = load_data()
    sent = load_sent()
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://kolkataff.tv/", headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        parse_tables(soup, data, sent, notify=True)
        save_data(data)
        save_sent(sent)
        print(f"[{get_ist_now().strftime('%d/%m/%Y %H:%M')} IST] OK — {len(data)} days")
    except Exception as e:
        print(f"Scrape error: {e}")

@app.route("/")
def index():
    return f"Kolkata FF Scraper — {get_ist_now().strftime('%d/%m/%Y %H:%M IST')}"

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
    today_key = get_ist_now().strftime("%d/%m/%Y")
    return jsonify({today_key: data.get(today_key, [])})

@app.route("/debug")
def debug():
    ist = get_ist_now()
    today_key = ist.strftime("%d/%m/%Y")
    data = load_data()
    sent = load_sent()
    return jsonify({
        "ist_time": ist.strftime("%d/%m/%Y %H:%M:%S"),
        "today_key": today_key,
        "today_results": data.get(today_key, []),
        "today_sent": sent.get(today_key, []),
        "total_days": len(data)
    })

@app.route("/reset-sent")
def reset_sent():
    data = load_data()
    sent = {}
    for date_key, bazis in data.items():
        sent[date_key] = bazis[:]
    save_sent(sent)
    return f"Done — {len(sent)} dates marked sent."

@app.route("/force-send-today")
def force_send_today():
    """Hit this to force resend today's results to Telegram"""
    data = load_data()
    sent = load_sent()
    today_key = get_ist_now().strftime("%d/%m/%Y")
    # Clear today from sent so it resends
    sent[today_key] = []
    save_sent(sent)
    scrape()
    return f"Forced resend for {today_key}"

if __name__ == "__main__":
    scrape_history()
    scrape()
    scheduler = BackgroundScheduler()
    scheduler.add_job(scrape, "interval", minutes=90)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
