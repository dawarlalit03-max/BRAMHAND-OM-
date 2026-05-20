# 🚩🚩 JAI SHREE RAM - V45 BRAHMASTRA NSE250 MASTER EDITION (ID FIXED) 🚩🚩

import os
import time
import json
import pytz
import telebot
import yfinance as yf
import pandas as pd
import logging
import requests
import sqlite3

from flask import Flask
from threading import Thread
from datetime import datetime, time as dtime
from ta.trend import ADXIndicator

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# 🔥 ललित जी, यहाँ आपकी सही आईडी को कोड के अंदर ही लॉक कर दिया गया है!
CHAT_ID = "8511514779" 

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
telebot.logger.setLevel(logging.CRITICAL) 

IST = pytz.timezone("Asia/Kolkata")
DB_FILE = "v45_trading.db"

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
BATCH_SIZE = 15 

# ⭐ 2026 की मुख्य NSE छुट्टियां
NSE_HOLIDAYS = [
    "2026-01-26", "2026-03-02", "2026-04-02", "2026-04-03", 
    "2026-04-14", "2026-05-01", "2026-10-02", "2026-10-22", 
    "2026-11-09", "2026-12-25"
]

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ================= FLASK (WEB SERVER) =================

app = Flask(__name__)

@app.route('/')
def home():
    return "🚩 V45 NSE250 BRAHMASTRA MASTER ENGINE LIVE 🚩"

# ================= SAFE DOWNLOAD (ANTIBAN SHIELD) =================

def safe_download(*args, **kwargs):
    try:
        time.sleep(1.5)
        return yf.download(*args, **kwargs)
    except Exception as e:
        logging.error(f"YF ERROR: {e}")
        return pd.DataFrame()

# ================= SQLITE DATABASE ENGINE =================

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                buy_price REAL,
                qty INTEGER,
                sl REAL,
                target REAL,
                entry_time TEXT,
                be_done INTEGER DEFAULT 0,
                partial_done INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_state (
                date TEXT PRIMARY KEY,
                daily_pnl REAL DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB INIT ERROR: {e}")

init_db()

def load_sqlite_state():
    positions_dict = {}
    daily_pnl, wins, losses = 0, 0, 0
    today_str = str(datetime.now(IST).date())
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute("SELECT symbol, buy_price, qty, sl, target, entry_time, be_done, partial_done FROM positions")
        rows = cursor.fetchall()
        for row in rows:
            positions_dict[row[0]] = {
                "buy": row[1], "qty": row[2], "sl": row[3], "target": row[4],
                "time": row[5], "be_done": bool(row[6]), "partial_done": bool(row[7])
            }
            
        cursor.execute("SELECT daily_pnl, wins, losses FROM daily_state WHERE date = ?", (today_str,))
        state = cursor.fetchone()
        if state:
            daily_pnl, wins, losses = state[0], state[1], state[2]
        else:
            cursor.execute("INSERT OR IGNORE INTO daily_state (date, daily_pnl, wins, losses) VALUES (?, 0, 0, 0)", (today_str,))
            conn.commit()
            
            cursor.execute("SELECT daily_pnl, wins, losses FROM daily_state ORDER BY date DESC LIMIT 1 OFFSET 1")
            last_state = cursor.fetchone()
            if last_state:
                daily_pnl, wins, losses = last_state[0], last_state[1], last_state[2]
            
        conn.close()
    except Exception as e:
        logging.error(f"DB LOAD ERROR: {e}")
        
    return positions_dict, daily_pnl, wins, losses

POSITIONS, DAILY_PNL, WINS, LOSSES = load_sqlite_state()
TRADING_HALTED = False
SCAN_INDEX = 0
MORNING_SENT = False
EVENING_SENT = False
CACHED_TREND = True
LAST_TREND_CHECK = None

def update_sqlite_position(symbol, pos_data, delete=False):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        cursor = conn.cursor()
        if delete:
            cursor.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO positions (symbol, buy_price, qty, sl, target, entry_time, be_done, partial_done)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, pos_data['buy'], pos_data['qty'], pos_data['sl'], pos_data['target'], 
                  pos_data['time'], int(pos_data['be_done']), int(pos_data['partial_done'])))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB POSITION UPDATE ERROR: {e}")

def save_sqlite_daily_state():
    try:
        today_str = str(datetime.now(IST).date())
        conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO daily_state (date, daily_pnl, wins, losses) 
            VALUES (?, ?, ?, ?)
        ''', (today_str, DAILY_PNL, WINS, LOSSES))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB DAILY STATE UPDATE ERROR: {e}")

# ================= TELEGRAM SEND FUNCTION =================

def send_msg(msg):
    try:
        # यहाँ सुरक्षा कवच को मॉडिफाई किया ताकि फिक्स आईडी पर रुकावट न आए
        if BOT_TOKEN and CHAT_ID in BOT_TOKEN:
            logging.error("सुरक्षा अलर्ट: टोकन और आईडी मिसमैच का अंदेशा।")
            return
        bot.send_message(CHAT_ID, f"🚩 जय श्री राम 🚩\n\n{msg}", parse_mode="HTML")
    except Exception as e:
        logging.error(f"TELEGRAM SEND ERROR: {e}")

# ================= NSE250 SYMBOLS FETCH =================

def get_nse250_symbols():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty250list.csv"
        df = pd.read_csv(url)
        symbols = [str(x).strip() + ".NS" for x in df['Symbol'].tolist()]
        return symbols
    except Exception as e:
        return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]

STOCKS = get_nse250_symbols()

SECTOR_MAP = {
    "RELIANCE.NS": "ENERGY", "ONGC.NS": "ENERGY",
    "TCS.NS": "IT", "INFY.NS": "IT",
    "HDFCBANK.NS": "BANK", "ICICIBANK.NS": "BANK", "SBIN.NS": "BANK",
    "LT.NS": "INFRA", "SUNPHARMA.NS": "PHARMA", "TATAMOTORS.NS": "AUTO"
}

# ================= MARKET TREND FILTER =================

def market_trend():
    global CACHED_TREND, LAST_TREND_CHECK
    now = datetime.now(IST)
    if LAST_TREND_CHECK is not None and (now - LAST_TREND_CHECK).seconds < 1800:
        return CACHED_TREND
        
    try:
        nifty = safe_download("^NSEI", period="100d", interval="1d", progress=False, threads=False)
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
        return CACHED_TREND

# ================= TECHNICAL INDICATORS =================

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

# ================= SAFE BATCH SCANNER =================

def scan_and_trade():
    global SCAN_INDEX, TRADING_HALTED
    try:
        if TRADING_HALTED: return
        if DAILY_PNL <= DAILY_LOSS_LIMIT:
            TRADING_HALTED = True
            send_msg(f"🛑 LOSS LIMIT HIT\n\nContinuous P&L: ₹{DAILY_PNL:.0f}")
            return

        if len(POSITIONS) >= MAX_POSITIONS or not market_trend(): return

        available = [s for s in STOCKS if s not in POSITIONS]
        if not available: return

        start = SCAN_INDEX
        end = start + BATCH_SIZE
        scan_list = available[start:end]
        SCAN_INDEX = 0 if end >= len(available) else end

        candidates = []
        for i in range(0, len(scan_list), 4):
            chunk = scan_list[i:i+4]
            data = safe_download(chunk, period="100d", interval="1d", group_by='ticker', progress=False, threads=True)

            for symbol in chunk:
                try:
                    df = data[symbol].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
                    if df.empty or len(df) < 50: continue

                    df = calculate_indicators(df)
                    if len(df) < 50: continue

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

                    if adx < ADX_THRESHOLD or not (55 < rsi < 70) or close < ema50: continue
                    if not (close > prev_high and close > ema20): continue

                    sector = SECTOR_MAP.get(symbol, "OTHER")
                    sector_count = sum(1 for s in POSITIONS if SECTOR_MAP.get(s) == sector)
                    if sector_count >= MAX_SECTOR_POSITIONS: continue

                    score = 50
                    if volume > avg_vol * 1.5: score += 20
                    if rsi > 60: score += 10

                    candidates.append((symbol, score, close, atr))
                except:
                    pass

        candidates.sort(key=lambda x: x[1], reverse=True)

        for symbol, score, price, atr in candidates:
            if len(POSITIONS) >= MAX_POSITIONS: break

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
            update_sqlite_position(symbol, POSITIONS[symbol])

            send_msg(
                f"🚀 BUY SIGNAL\n\nStock: {symbol.replace('.NS','')}\nPrice: ₹{price:.2f}\n"
                f"Qty: {qty}\nSL: ₹{sl:.2f}\nTarget: ₹{target:.2f}\nScore: {score}"
            )
    except Exception as e:
        logging.error(f"SCAN ERROR: {e}")

# ================= CONTINUOUS MONITORING =================

def monitor_positions():
    global DAILY_PNL, WINS, LOSSES
    try:
        if not POSITIONS: return
        data = safe_download(list(POSITIONS.keys()), period="1d", interval="1m", group_by='ticker', progress=False, threads=False)
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
                    update_sqlite_position(symbol, pos)
                    save_sqlite_daily_state()
                    send_msg(f"💰 PARTIAL EXIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")

                if curr >= pos['buy'] * (1 + BREAK_EVEN_TRIGGER) and not pos['be_done']:
                    pos['sl'] = pos['buy']
                    pos['be_done'] = True
                    update_sqlite_position(symbol, pos)
                    send_msg(f"🛡️ BREAK EVEN\n\n{symbol}")

                if curr >= pos['buy'] * 1.03:
                    new_sl = curr * 0.98
                    if new_sl > pos['sl']: 
                        pos['sl'] = new_sl
                        update_sqlite_position(symbol, pos)

                entry_time = datetime.fromisoformat(pos['time'])
                if (datetime.now(IST) - entry_time).days >= AUTO_EXIT_DAYS:
                    pnl = (curr - pos['buy']) * pos['qty']
                    DAILY_PNL += pnl
                    if pnl >= 0: WINS += 1
                    else: LOSSES += 1
                    remove.append(symbol)
                    update_sqlite_position(symbol, None, delete=True)
                    save_sqlite_daily_state()
                    send_msg(f"⏰ AUTO EXIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")
                    continue

                if curr >= pos['target']:
                    pnl = (curr - pos['buy']) * pos['qty']
                    DAILY_PNL += pnl
                    WINS += 1
                    remove.append(symbol)
                    update_sqlite_position(symbol, None, delete=True)
                    save_sqlite_daily_state()
                    send_msg(f"🎯 TARGET HIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")
                elif curr <= pos['sl']:
                    pnl = (curr - pos['buy']) * pos['qty']
                    DAILY_PNL += pnl
                    LOSSES += 1
                    remove.append(symbol)
                    update_sqlite_position(symbol, None, delete=True)
                    save_sqlite_daily_state()
                    send_msg(f"🛑 STOPLOSS HIT\n\n{symbol}\nP&L: ₹{pnl:.0f}")
            except Exception as e:
                logging.error(f"{symbol} MONITOR ERROR: {e}")

        for s in remove:
            if s in POSITIONS: del POSITIONS[s]
    except Exception as e:
        logging.error(f"MONITOR ERROR: {e}")

# ================= TELEGRAM COMMANDS =================

@bot.message_handler(commands=['start', 'status'])
def status(message):
    global POSITIONS, DAILY_PNL, WINS, LOSSES
    POSITIONS, DAILY_PNL, WINS, LOSSES = load_sqlite_state()
    
    total = WINS + LOSSES
    winrate = ((WINS / total) * 100 if total > 0 else 0)

    tax_deducted = DAILY_PNL * 0.15 if DAILY_PNL > 0 else 0
    net_pnl = DAILY_PNL - tax_deducted if DAILY_PNL > 0 else DAILY_PNL
    my_payout = net_pnl * 0.20 if DAILY_PNL > 0 else 0
    reinvest_amount = net_pnl * 0.80 if DAILY_PNL > 0 else DAILY_PNL

    msg = (
        f"🚩 <b>V45 NSE250 BRAHMASTRA (ID FIXED MASTER)</b> 🚩\n\n"
        f"💰 Total P&L: ₹{DAILY_PNL:.0f}\n"
        f"🏛️ Est. Tax (15%): ₹{tax_deducted:.0f}\n"
        f"💵 <b>आपका हिस्सा (20%): ₹{my_payout:.0f}</b>\n"
        f"📈 री-इन्वेस्टमेंट (80%): ₹{reinvest_amount:.0f}\n"
        f"-------------------------------\n"
        f"📊 Open Positions: {len(POSITIONS)}/{MAX_POSITIONS}\n"
        f"✅ Wins: {WINS}  |  ❌ Losses: {LOSSES}\n"
        f"🎯 WinRate: {winrate:.1f}%\n\n"
        f"🗄️ Database: SQLite Active (Continuous Tracking)\n"
    )
    bot.reply_to(message, msg, parse_mode="HTML")

# ================= CORE ENGINE LOOP =================

def main_loop():
    global MORNING_SENT, EVENING_SENT, POSITIONS, DAILY_PNL, WINS, LOSSES
    logging.info("BOT STARTED WITH SQLITE MASTER ENGINE (CONTINUOUS MODE)")

    while True:
        try:
            now = datetime.now(IST)
            t = now.strftime("%H:%M")
            today_str = str(now.date())

            if now.weekday() >= 5:
                time.sleep(3600)
                continue

            if today_str in NSE_HOLIDAYS:
                time.sleep(3600)
                continue

            if now.minute % 2 == 0 and now.second < 15:
                try: requests.get("http://localhost:10000/", timeout=5)
                except: pass

            if t == "09:20" and not MORNING_SENT:
                send_msg("🚀 BOT ACTIVE\n\n✅ SQLITE Fixed ID Active\n✅ Holiday Shield Active\n✅ Continuous Mode (No Reset)\n\nशुभ ट्रेडिंग 📈")
                MORNING_SENT = True
                EVENING_SENT = False

            if dtime(9,20) <= now.time() <= dtime(15,30):
                POSITIONS, DAILY_PNL, WINS, LOSSES = load_sqlite_state()
                if now.minute % 5 == 0 and now.second < 10:
                    scan_and_trade()
                monitor_positions()
                time.sleep(15)
            else:
                time.sleep(60)

            if t == "15:30" and not EVENING_SENT:
                POSITIONS, DAILY_PNL, WINS, LOSSES = load_sqlite_state()
                tax_deducted = DAILY_PNL * 0.15 if DAILY_PNL > 0 else 0
                net_pnl = DAILY_PNL - tax_deducted if DAILY_PNL > 0 else DAILY_PNL
                my_payout = net_pnl * 0.20 if DAILY_PNL > 0 else 0
                reinvest_amount = net_pnl * 0.80 if DAILY_PNL > 0 else DAILY_PNL
                
                send_msg(
                    f"📊 <b>DAILY FINAL REPORT (V45 MASTER)</b>\n\n"
                    f"💰 कुल संचयी लाभ (Gross Total): ₹{DAILY_PNL:.0f}\n"
                    f"🏛️ टैक्स सुरक्षित किया (15%): ₹{tax_deducted:.0f}\n"
                    f"💵 <b>ललित जी का शुद्ध पेआउट (20%): ₹{my_payout:.0f}</b>\n"
                    f"📈 पुनर्निवेश राशि (80%): ₹{reinvest_amount:.0f}\n"
                    f"-------------------------------\n"
                    f"✅ Wins: {WINS}  |  ❌ Losses: {LOSSES}\n"
                    f"📈 Open Positions: {len(POSITIONS)}"
                )
                EVENING_SENT = True
                MORNING_SENT = False
        except Exception as e:
            logging.error(f"MAIN LOOP EXCEPTION: {e}")
            time.sleep(15)

# ================= ENGINE START UP =================

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

    send_msg("🚀 V45 FIXED ID ENGINE DEPLOYED\n\n✅ Hardcoded Chat ID Setup\n✅ SQLite Continuous Ledger Live\n✅ Daily Reset REMOVED")

    Thread(target=main_loop, daemon=True).start()

    while True:
        try:
            logging.info("Telegram Polling Started...")
            bot.polling(none_stop=True, timeout=90, long_polling_timeout=30)
        except Exception as e:
            logging.error(f"TELEGRAM POLLING ERROR: {e}")
            time.sleep(15)
