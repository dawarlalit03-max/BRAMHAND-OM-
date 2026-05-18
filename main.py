# 🚩🚩 JAI SHREE RAM - V44 BRAHMASTRA NSE250 ANTI-BAN FINAL 🚩🚩

import os
import time
import json
import pytz
import telebot
import yfinance as yf
import pandas as pd
import logging

from flask import Flask
from threading import Thread
from datetime import datetime, time as dtime
from ta.trend import ADXIndicator

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
IST = pytz.timezone("Asia/Kolkata")
DATA_FILE = "v44_nse250_state.json"

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
MONITOR_INTERVAL = 60
BATCH_SIZE = 15 # SAFE FOR ANTI-BAN

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ================= FLASK =================

app = Flask(__name__)

@app.route('/')
def home():
    return "🚩 V44 NSE250 BRAHMASTRA LIVE 🚩"

# ================= STORAGE =================

def safe_save():
    try:
        data = {
            "positions": POSITIONS,
            "daily_pnl": DAILY_PNL,
            "wins": WINS,
            "losses": LOSSES,
            "date": str(datetime.now(IST).date())
        }
        temp = DATA_FILE + ".tmp"
        with open(temp, "w") as f:
            json.dump(data, f)
        os.replace(temp, DATA_FILE)
    except Exception as e:
        logging.error(f"SAVE ERROR: {e}")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") == str(datetime.now(IST).date()):
                return (
                    data.get("positions", {}),
                    data.get("daily_pnl", 0),
                    data.get("wins", 0),
                    data.get("losses", 0)
                )
        except Exception as e:
            logging.error(f"LOAD ERROR: {e}")
    return {}, 0, 0, 0

POSITIONS, DAILY_PNL, WINS, LOSSES = load_data()
TRADING_HALTED = False
SCAN_INDEX = 0
MORNING_SENT = False
EVENING_SENT = False
CACHED_TREND = True
LAST_TREND_CHECK = None

# ================= TELEGRAM =================

def send_msg(msg):
    try:
        bot.send_message(CHAT_ID, f"🚩 जय श्री राम 🚩\n\n{msg}", parse_mode="HTML")
    except Exception as e:
        logging.error(f"TELEGRAM ERROR: {e}")

# ================= NSE250 SYMBOLS =================

def get_nse250_symbols():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty250list.csv"
        df = pd.read_csv(url)
        symbols = [str(x).strip() + ".NS" for x in df['Symbol'].tolist()]
        return symbols
    except Exception as e:
        logging.error(f"NSE250 LOAD ERROR: {e}")
        return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]

STOCKS = get_nse250_symbols()

SECTOR_MAP = {
    "RELIANCE.NS": "ENERGY", "ONGC.NS": "ENERGY",
    "TCS.NS": "IT", "INFY.NS": "IT",
    "HDFCBANK.NS": "BANK", "ICICIBANK.NS": "BANK", "SBIN.NS": "BANK",
    "LT.NS": "INFRA", "SUNPHARMA.NS": "PHARMA", "TATAMOTORS.NS": "AUTO"
}

# ================= MARKET TREND (ANTI-BAN UPDATED) =================

def market_trend():
    global CACHED_TREND, LAST_TREND_CHECK
    now = datetime.now(IST)
    
    # याहू को बार-बार हिट होने से बचाने के लिए ट्रेंड सिर्फ हर 30 मिनट में एक बार चेक होगा
    if LAST_TREND_CHECK is not None and (now - LAST_TREND_CHECK).seconds < 1800:
        return CACHED_TREND
        
    try:
        logging.info("Checking Market Trend...")
        nifty = yf.download("^NSEI", period="100d", interval="1d", progress=False, threads=False)
        if nifty.empty or len(nifty) < 50:
            LAST_TREND_CHECK = now
            return CACHED_TREND

        nifty['EMA50'] = nifty['Close'].ewm(span=50).mean()
        close = float(nifty['Close'].iloc[-1])
        ema50 = float(nifty['EMA50'].iloc[-1])

        CACHED_TREND = close > ema50
        LAST_TREND_CHECK = now
        return CACHED_TREND
    except Exception as e:
        logging.error(f"MARKET TREND ERROR (RATE LIMIT PASS): {e}")
        return CACHED_TREND # एरर आने पर पुराने ट्रेंड को ही सही मानकर बॉट रुकेगा नहीं

# ================= INDICATORS =================

def calculate_indicators(df):
    df = df.copy()
    df['EMA20'] = df['Close'].ewm(span=20).mean()
    df['EMA50'] = df['Close'].ewm(span=50).mean()

    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    adx = ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
    df['ADX'] = adx.adx()

    tr = pd.concat([
        df['High'] - df['Low'],
        abs(df['High'] - df['Close'].shift()),
        abs(df['Low'] - df['Close'].shift())
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    return df.dropna()

# ================= SCANNER =================

def scan_and_trade():
    global SCAN_INDEX, TRADING_HALTED
    try:
        if TRADING_HALTED:
            return

        if DAILY_PNL <= DAILY_LOSS_LIMIT:
            TRADING_HALTED = True
            send_msg(f"🛑 LOSS LIMIT HIT\n\nDaily P&L: ₹{DAILY_PNL:.0f}")
            return

        if len(POSITIONS) >= MAX_POSITIONS:
            return

        if not market_trend():
            return

        available = [s for s in STOCKS if s not in POSITIONS]
        if not available:
            return

        start = SCAN_INDEX
        end = start + BATCH_SIZE
        scan_list = available[start:end]
        SCAN_INDEX = 0 if end >= len(available) else end

        logging.info(f"Scanning {len(scan_list)} stocks safely...")

        candidates = []
        
        # एंटी-बैन सुधार: एक साथ ब्लास्ट करने के बजाय 4-4 के छोटे ग्रुप में आराम से डेटा उठाएगा
        for i in range(0, len(scan_list), 4):
            chunk = scan_list[i:i+4]
            try:
                data = yf.download(chunk, period="100d", interval="1d", group_by='ticker', progress=False, threads=True)
                time.sleep(1.5) # याहू के लिए छोटा सा स्पीड ब्रेकर
            except Exception as e:
                logging.error(f"Chunk Download Error: {e}")
                continue

            for symbol in chunk:
                try:
                    df = data[symbol].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
                    if df.empty or len(df) < 50:
                        continue

                    df = calculate_indicators(df)
                    if len(df) < 50:
                        continue

                    last = df.iloc[-1]
                    prev = df.iloc[-2]

                    adx = float(last['ADX'])
                    rsi = float(last['RSI'])
                    close = float(last['Close'])
                    ema20 = float(last['EMA20'])
                    ema50 = float(last['EMA50'])
                    prev_high = float(prev['High'])
                    atr = float(last['ATR'])
                    volume = float(last['Volume'])
                    avg_vol = float(df['Volume'].rolling(20).mean().iloc[-1])

                    if adx < ADX_THRESHOLD or not (55 < rsi < 70) or close < ema50:
                        continue

                    if not (close > prev_high and close > ema20):
                        continue

                    sector = SECTOR_MAP.get(symbol, "OTHER")
                    sector_count = sum(1 for s in POSITIONS if SECTOR_MAP.get(s) == sector)
                    if sector_count >= MAX_SECTOR_POSITIONS:
                        continue

                    score = 50
                    if volume > avg_vol * 1.5: score += 20
                    if rsi > 60: score += 10

                    candidates.append((symbol, score, close, atr))
                except Exception as e:
                    pass

        candidates.sort(key=lambda x: x[1], reverse=True)

        for symbol, score, price, atr in candidates:
            if len(POSITIONS) >= MAX_POSITIONS:
                break

            risk_amount = CAPITAL * RISK_PER_TRADE
            sl_distance = atr * ATR_SL_MULTIPLIER
            if sl_distance <= 0: continue

            qty = int(risk_amount / sl_distance)
            if qty <= 0 or (price * qty > CAPITAL * 0.20): continue

            sl = price - sl_distance
            target = price + (atr * ATR_TARGET_MULTIPLIER)

            POSITIONS[symbol] = {
                "buy": float(price), "qty": qty, "sl": float(sl), "target": float(target),
                "time": datetime.now(IST).isoformat(), "be_done": False, "partial_done": False
            }
            safe_save()

            send_msg(
                f"🚀 BUY SIGNAL\n\nStock: {symbol.replace('.NS','')}\nPrice: ₹{price:.2f}\n"
                f"Qty: {qty}\nSL: ₹{sl:.2f}\nTarget: ₹{target:.2f}\nScore: {score}"
            )
    except Exception as e:
        logging.error(f"SCAN ERROR: {e}")

# ================= MONITOR =================

def monitor_positions():
    global DAILY_PNL, WINS, LOSSES
    try:
        if not POSITIONS:
            return

        # मॉनिटरिंग के लिए भी सिंगल-थ्रेड और 1 मिनट का पूरा गैप रखेंगे
        data = yf.download(list(POSITIONS.keys()), period="1d", interval="1m", group_by='ticker', progress=False, threads=False)
        remove = []

        for symbol, pos in list(POSITIONS.items()):
            try:
                df = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
                if df.empty: continue

                curr = float(df['Close'].iloc[-1])

                if curr >= pos['buy'] * (1 + PARTIAL_BOOK_TRIGGER) and not pos['partial_done']:
                    partial_qty = int(pos['qty'] * PARTIAL_BOOK_QTY)
                    pnl = (curr - pos['buy']) * partial_qty
                    DAILY_PNL += pnl
                    pos['qty'] -= partial_qty
                    pos['partial_done'] = True
                    send_msg(f"💰 PARTIAL EXIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")

                if curr >= pos['buy'] * (1 + BREAK_EVEN_TRIGGER) and not pos['be_done']:
                    pos['sl'] = pos['buy']
                    pos['be_done'] = True
                    send_msg(f"🛡️ BREAK EVEN\n\n{symbol}")

                if curr >= pos['buy'] * 1.03:
                    new_sl = curr * 0.98
                    if new_sl > pos['sl']: pos['sl'] = new_sl

                entry_time = datetime.fromisoformat(pos['time'])
                if (datetime.now(IST) - entry_time).days >= AUTO_EXIT_DAYS:
                    pnl = (curr - pos['buy']) * pos['qty']
                    DAILY_PNL += pnl
                    if pnl >= 0: WINS += 1
                    else: LOSSES += 1
                    send_msg(f"⏰ AUTO EXIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")
                    remove.append(symbol)
                    continue

                if curr >= pos['target']:
                    pnl = (curr - pos['buy']) * pos['qty']
                    DAILY_PNL += pnl
                    WINS += 1
                    send_msg(f"🎯 TARGET HIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")
                    remove.append(symbol)
                elif curr <= pos['sl']:
                    pnl = (curr - pos['buy']) * pos['qty']
                    DAILY_PNL += pnl
                    LOSSES += 1
                    send_msg(f"🛑 STOPLOSS HIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")
                    remove.append(symbol)
            except Exception as e:
                logging.error(f"{symbol} MONITOR ERROR: {e}")

        for s in remove:
            if s in POSITIONS: del POSITIONS[s]
        safe_save()
    except Exception as e:
        logging.error(f"MONITOR ERROR: {e}")

# ================= STATUS =================

@bot.message_handler(commands=['start', 'status'])
def status(message):
    total = WINS + LOSSES
    winrate = ((WINS / total) * 100 if total > 0 else 0)

    tax_deducted = 0
    my_payout = 0
    reinvest_amount = DAILY_PNL

    if DAILY_PNL > 0:
        tax_deducted = DAILY_PNL * 0.15
        net_pnl = DAILY_PNL - tax_deducted
        my_payout = net_pnl * 0.20
        reinvest_amount = net_pnl * 0.80

    msg = (
        f"🚩 <b>V44 NSE250 BRAHMASTRA</b> 🚩\n\n"
        f"💰 Gross P&L: ₹{DAILY_PNL:.0f}\n"
        f"🏛️ Est. Tax (15%): ₹{tax_deducted:.0f}\n"
        f"💵 <b>आपका हिस्सा (20%): ₹{my_payout:.0f}</b>\n"
        f"📈 री-इन्वेस्टमेंट (80%): ₹{reinvest_amount:.0f}\n"
        f"-------------------------------\n"
        f"📊 Open Positions: {len(POSITIONS)}/{MAX_POSITIONS}\n"
        f"✅ Wins: {WINS}  |  ❌ Losses: {LOSSES}\n"
        f"🎯 WinRate: {winrate:.1f}%\n\n"
        f"🛡️ Anti-Ban System: RUNNING\n"
    )
    bot.reply_to(message, msg, parse_mode="HTML")

# ================= MAIN LOOP =================

def main_loop():
    global MORNING_SENT, EVENING_SENT
    logging.info("BOT STARTED")

    while True:
        try:
            now = datetime.now(IST)
            t = now.strftime("%H:%M")

            if t == "09:20" and not MORNING_SENT and now.weekday() < 5:
                send_msg("🚀 BOT ACTIVE\n\n✅ NSE250 Safe Scanner Enabled\n✅ Anti-Ban Active\n\nशुभ ट्रेडिंग 📈")
                MORNING_SENT = True
                EVENING_SENT = False

            if now.weekday() < 5 and dtime(9,20) <= now.time() <= dtime(15,30):
                if now.minute % 5 == 0 and now.second < 10:
                    scan_and_trade()
                monitor_positions()
                time.sleep(15)
            else:
                time.sleep(60)

            if t == "15:30" and not EVENING_SENT and now.weekday() < 5:
                tax_deducted = DAILY_PNL * 0.15 if DAILY_PNL > 0 else 0
                net_pnl = DAILY_PNL - tax_deducted if DAILY_PNL > 0 else DAILY_PNL
                my_payout = net_pnl * 0.20 if DAILY_PNL > 0 else 0
                
                send_msg(
                    f"📊 <b>DAILY FINAL REPORT (NSE250)</b>\n\n💰 सकल लाभ (Gross): ₹{DAILY_PNL:.0f}\n"
                    f"🏛️ टैक्स सुरक्षित किया: ₹{tax_deducted:.0f}\n💵 <b>ललित जी का शुद्ध पेआउट (20%): ₹{my_payout:.0f}</b>\n"
                    f"-------------------------------\n✅ Wins: {WINS}  |  ❌ Losses: {LOSSES}\n📈 Open Positions: {len(POSITIONS)}"
                )
                EVENING_SENT = True
                MORNING_SENT = False
        except Exception as e:
            logging.error(f"MAIN LOOP ERROR: {e}")
            time.sleep(15)

# ================= START =================

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

    send_msg("🚀 V44 NSE250 ANTI-BAN STARTED\n\n✅ 4-Stock Chunk Scanning Active\n✅ Cache Trend Enabled\n✅ Safe Rate Limit Active")

    Thread(target=main_loop, daemon=True).start()

    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=5)
        except Exception as e:
            time.sleep(15)
