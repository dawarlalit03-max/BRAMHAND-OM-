
import os
import time
import json
import pytz
import telebot
import yfinance as yf
import pandas as pd
import logging
from requests import Session
from flask import Flask
from threading import Thread
from datetime import datetime, time as dtime
from ta.trend import ADXIndicator

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

IST = pytz.timezone("Asia/Kolkata")
DATA_FILE = "v43_state.json"

CAPITAL = 100000
RISK_PER_TRADE = 0.01
MAX_POSITIONS = 4
MAX_SECTOR_POSITIONS = 2
DAILY_LOSS_LIMIT = -1500
ATR_SL_MULTIPLIER = 1.5
ATR_TARGET_MULTIPLIER = 4.0
BREAK_EVEN_TRIGGER = 0.02
PARTIAL_BOOK_TRIGGER = 0.06
PARTIAL_BOOK_QTY = 0.50
AUTO_EXIT_DAYS = 3
ADX_THRESHOLD = 25
SCAN_INTERVAL = 300
MONITOR_INTERVAL = 120
BATCH_SIZE = 50

# ================= LOGGING SETUP =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= YAHOO FINANCE FIX =================
session = Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

# ================= STORAGE & FLASK =================
app = Flask(__name__)
@app.route('/')
def home(): return "🚩 V43.5 BRAHMASTRA PRO LIVE 🚩"

def safe_save():
    """Atomic save - data corrupt nahi hoga"""
    try:
        data = {
            "positions": POSITIONS,
            "daily_pnl": DAILY_PNL,
            "wins": WINS,
            "losses": LOSSES,
            "date": str(datetime.now(IST).date())
        }
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.replace(temp_file, DATA_FILE)
        logging.info("Data saved successfully")
    except Exception as e:
        logging.error(f"SAVE ERROR: {e}")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == str(datetime.now(IST).date()):
                    logging.info("Loaded existing data for today")
                    return data.get("positions", {}), data.get("daily_pnl", 0), data.get("wins", 0), data.get("losses", 0)
        except Exception as e:
            logging.error(f"LOAD ERROR: {e}")
    logging.info("Starting fresh for today")
    return {}, 0, 0, 0

POSITIONS, DAILY_PNL, WINS, LOSSES = load_data()
TRADING_HALTED, SCAN_INDEX = False, 0

def send_msg(msg):
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"TG ERROR: {e}")

# ================= DATA FETCHING =================
def get_nifty250():
    try:
        df = pd.read_csv("https://archives.nseindia.com/content/indices/ind_nifty250list.csv")
        return [s + ".NS" for s in df["Symbol"].tolist()]
    except Exception as e:
        logging.error(f"Nifty250 fetch error: {e}")
        return ["RELIANCE.NS", "TATAMOTORS.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]

STOCKS = get_nifty250()
SECTOR_MAP = {'RELIANCE.NS': 'ENERGY', 'TATAMOTORS.NS': 'AUTO', 'TCS.NS': 'IT', 'INFY.NS': 'IT', 'SBIN.NS': 'BANK'}

# ================= LOGIC & MONITOR =================
def calculate_indicators(df):
    df = df.copy()
    df['EMA20'] = df['Close'].ewm(span=20).mean()
    df['EMA50'] = df['Close'].ewm(span=50).mean()
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain/loss)))
    adx = ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
    df['ADX'] = adx.adx()
    tr = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    return df.dropna()

def scan_and_trade():
    global SCAN_INDEX, TRADING_HALTED
    if TRADING_HALTED or len(POSITIONS) >= MAX_POSITIONS:
        return

    available = [s for s in STOCKS if s not in POSITIONS]
    scan_list = available[SCAN_INDEX:SCAN_INDEX + BATCH_SIZE]
    SCAN_INDEX = 0 if SCAN_INDEX + BATCH_SIZE >= len(available) else SCAN_INDEX + BATCH_SIZE

    try:
        data = yf.download(scan_list, period="100d", interval="1d", group_by='ticker', progress=False, session=session)
        for symbol in scan_list:
            df = data[symbol] if len(scan_list) > 1 else data
            if df.empty or len(df) < 50:
                continue
            df = calculate_indicators(df)
            last, prev = df.iloc[-1], df.iloc[-2]

            if last['ADX'] > ADX_THRESHOLD and 55 < last['RSI'] < 70 and last['Close'] > last['EMA50'] and last['Close'] > prev['High']:
                risk_amt = CAPITAL * RISK_PER_TRADE
                qty = int(risk_amt / (last['ATR'] * ATR_SL_MULTIPLIER))
                if qty > 0:
                    POSITIONS[symbol] = {
                        "buy": float(last['Close']),
                        "qty": qty,
                        "sl": float(last['Close'] - (last['ATR'] * ATR_SL_MULTIPLIER)),
                        "target": float(last['Close'] + (last['ATR'] * ATR_TARGET_MULTIPLIER)),
                        "time": datetime.now(IST).isoformat(),
                        "be_done": False,
                        "partial_done": False
                    }
                    safe_save()
                    send_msg(f"🚀 <b>BUY: {symbol}</b>\nPrice: {last['Close']:.2f}\nQty: {qty}\nTarget: {POSITIONS[symbol]['target']:.2f}")
                    logging.info(f"BUY signal for {symbol}")
    except Exception as e:
        logging.error(f"SCAN ERROR: {e}")

def monitor_positions():
    global DAILY_PNL, WINS, LOSSES
    if not POSITIONS:
        return
    try:
        data = yf.download(list(POSITIONS.keys()), period="1d", interval="1m", group_by='ticker', progress=False, session=session)
        for symbol, pos in list(POSITIONS.items()):
            df = data[symbol] if len(POSITIONS) > 1 else data
            curr = df['Close'].iloc[-1]

            if curr >= pos['target']:
                pnl = (curr - pos['buy']) * pos['qty']
                DAILY_PNL += pnl; WINS += 1
                send_msg(f"🎯 <b>TARGET HIT: {symbol}</b>\nP&L: ₹{pnl:.0f}")
                del POSITIONS[symbol]
            elif curr <= pos['sl']:
                pnl = (curr - pos['buy']) * pos['qty']
                DAILY_PNL += pnl; LOSSES += 1
                send_msg(f"🛑 <b>STOP LOSS: {symbol}</b>\nP&L: ₹{pnl:.0f}")
                del POSITIONS[symbol]
        safe_save()
    except Exception as e:
        logging.error(f"MONITOR ERROR: {e}")

# ================= COMMANDS =================
@bot.message_handler(commands=['start', 'status'])
def handle_status(message):
    total = WINS + LOSSES
    wr = (WINS/total*100) if total > 0 else 0
    text = f"🚩 <b>BRAHMASTRA V43.5 STATUS</b>\n\n💰 P&L: ₹{DAILY_PNL:.0f}\n📈 Positions: {len(POSITIONS)}/4\n✅ Wins: {WINS} | ❌ Loss: {LOSSES}\n🎯 WinRate: {wr:.1f}%"
    bot.reply_to(message, text, parse_mode="HTML")

# ================= LOOPS =================
def main_loop():
    logging.info("Bot started. Waiting for market open...")
    while True:
        now = datetime.now(IST)
        if dtime(9,20) <= now.time() <= dtime(15,30):
            # Har 5 min me scan karo
            if now.minute % 5 == 0 and now.second < 10:
                scan_and_trade()
            monitor_positions()
            time.sleep(10)
        else:
            time.sleep(60)

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    Thread(target=main_loop).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
