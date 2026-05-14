# 🚩 जय श्री राम - V43.5 BRAHMASTRA PRO FINAL 🚩

import os
import time
import json
import pytz
import telebot
import yfinance as yf
import pandas as pd

from flask import Flask
from threading import Thread
from datetime import datetime
from ta.trend import ADXIndicator

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN)

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

# ===== UPDATED =====
SCAN_INTERVAL = 300
MONITOR_INTERVAL = 120
BATCH_SIZE = 50

# ================= FLASK =================

app = Flask(__name__)

@app.route('/')
def home():
    return "🚩 V43.5 BRAHMASTRA PRO LIVE 🚩"

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

        temp_file = DATA_FILE + ".tmp"

        with open(temp_file, "w") as f:
            json.dump(data, f)

        os.replace(temp_file, DATA_FILE)

    except Exception as e:
        print(f"SAVE ERROR: {e}")

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

        except:
            pass

    return {}, 0, 0, 0

POSITIONS, DAILY_PNL, WINS, LOSSES = load_data()

TRADING_HALTED = False

LAST_SCAN = ""
LAST_MONITOR = 0

MORNING_SENT = False
EVENING_SENT = False

SCAN_INDEX = 0

# ================= TELEGRAM =================

def send_msg(msg):

    try:

        bot.send_message(
            CHAT_ID,
            msg,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"TG ERROR: {e}")

# ================= NIFTY 250 =================

NIFTY_250_URL = "https://archives.nseindia.com/content/indices/ind_nifty250list.csv"

def get_nifty250():

    try:

        df = pd.read_csv(NIFTY_250_URL)

        symbols = [
            s + ".NS"
            for s in df["Symbol"].tolist()
        ]

        return list(set(symbols))

    except Exception as e:

        print(f"NIFTY250 ERROR: {e}")

        return [
            "RELIANCE.NS",
            "TCS.NS",
            "INFY.NS",
            "HDFCBANK.NS",
            "ICICIBANK.NS"
        ]

STOCKS = get_nifty250()

# ================= SECTOR MAP =================

SECTOR_MAP = {

    'RELIANCE.NS': 'ENERGY',
    'ONGC.NS': 'ENERGY',
    'IOC.NS': 'ENERGY',
    'BPCL.NS': 'ENERGY',

    'TCS.NS': 'IT',
    'INFY.NS': 'IT',
    'WIPRO.NS': 'IT',
    'HCLTECH.NS': 'IT',

    'HDFCBANK.NS': 'BANK',
    'ICICIBANK.NS': 'BANK',
    'SBIN.NS': 'BANK',
    'AXISBANK.NS': 'BANK',

    'TATASTEEL.NS': 'METAL',
    'JSWSTEEL.NS': 'METAL',
    'HINDALCO.NS': 'METAL',

    'SUNPHARMA.NS': 'PHARMA',
    'CIPLA.NS': 'PHARMA',
    'DIVISLAB.NS': 'PHARMA',

    'LT.NS': 'INFRA',
    'ULTRACEMCO.NS': 'INFRA',
    'SIEMENS.NS': 'INFRA',

    'MARUTI.NS': 'AUTO',
    'TATAMOTORS.NS': 'AUTO',
    'M&M.NS': 'AUTO'
}

# ================= MARKET TREND =================

def market_trend():

    try:

        df = yf.download(
            "^NSEI",
            period="250d",
            interval="1d",
            progress=False
        )

        if len(df) < 200:
            return True

        df['EMA20'] = df['Close'].ewm(span=20).mean()
        df['EMA50'] = df['Close'].ewm(span=50).mean()
        df['EMA200'] = df['Close'].ewm(span=200).mean()

        last = df.iloc[-1]

        return (
            last['EMA20'] >
            last['EMA50'] >
            last['EMA200']
        )

    except:
        return True

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

    adx = ADXIndicator(
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        window=14
    )

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

    global TRADING_HALTED
    global SCAN_INDEX

    if TRADING_HALTED:
        return

    if DAILY_PNL <= DAILY_LOSS_LIMIT:

        TRADING_HALTED = True

        send_msg(
            f"🛑 *LOSS LIMIT HIT*\n"
            f"Daily P&L: ₹{DAILY_PNL:.0f}\n"
            f"Trading Halted"
        )

        return

    if len(POSITIONS) >= MAX_POSITIONS:
        return

    if not market_trend():
        return

    available = [
        s for s in STOCKS
        if s not in POSITIONS
    ]

    if not available:
        return

    start = SCAN_INDEX
    end = start + BATCH_SIZE

    scan_list = available[start:end]

    SCAN_INDEX = end

    if SCAN_INDEX >= len(available):
        SCAN_INDEX = 0

    try:

        data = yf.download(
            scan_list,
            period="90d",
            interval="1d",
            group_by='ticker',
            progress=False,
            threads=True
        )

    except Exception as e:

        print(f"SCAN ERROR: {e}")
        return

    candidates = []

    for symbol in scan_list:

        try:

            df = data[symbol].copy()

            df = calculate_indicators(df)

            if len(df) < 50:
                continue

            last = df.iloc[-1]
            prev = df.iloc[-2]

            if last['ADX'] < ADX_THRESHOLD:
                continue

            if last['Close'] < last['EMA50']:
                continue

            if not (55 < last['RSI'] < 70):
                continue

            breakout = (
                last['Close'] > prev['High']
                and last['Close'] > last['EMA20']
            )

            if not breakout:
                continue

            sector = SECTOR_MAP.get(symbol, "OTHER")

            sector_count = sum(
                1 for s in POSITIONS
                if SECTOR_MAP.get(s) == sector
            )

            if sector_count >= MAX_SECTOR_POSITIONS:
                continue

            avg_vol = df['Volume'].rolling(20).mean().iloc[-1]

            score = 50

            if last['Volume'] > avg_vol * 1.5:
                score += 20

            if last['RSI'] > 60:
                score += 10

            candidates.append((
                symbol,
                score,
                last['Close'],
                last['ATR']
            ))

        except Exception as e:
            print(f"{symbol} ERROR: {e}")

    candidates = sorted(
        candidates,
        key=lambda x: x[1],
        reverse=True
    )

    for symbol, score, price, atr in candidates:

        if len(POSITIONS) >= MAX_POSITIONS:
            break

        risk_amount = CAPITAL * RISK_PER_TRADE

        sl_distance = atr * ATR_SL_MULTIPLIER

        qty = int(risk_amount / sl_distance)

        if qty <= 0:
            continue

        if price * qty > CAPITAL * 0.25:
            continue

        sl = price - sl_distance

        target = (
            price +
            (atr * ATR_TARGET_MULTIPLIER)
        )

        POSITIONS[symbol] = {

            "buy": float(price),
            "qty": qty,
            "sl": float(sl),
            "target": float(target),
            "time": datetime.now(IST).isoformat(),
            "be_done": False,
            "partial_done": False
        }

        safe_save()

        send_msg(
            f"🚀 *BUY SIGNAL*\n\n"
            f"*{symbol.replace('.NS','')}*\n"
            f"Price: ₹{price:.2f}\n"
            f"Qty: {qty}\n"
            f"SL: ₹{sl:.2f}\n"
            f"Target: ₹{target:.2f}\n"
            f"Score: {score}"
        )

# ================= MONITOR =================

def monitor_positions():

    global DAILY_PNL
    global WINS
    global LOSSES

    if not POSITIONS:
        return

    try:

        data = yf.download(
            list(POSITIONS.keys()),
            period="1d",
            interval="1m",
            group_by='ticker',
            progress=False,
            threads=True
        )

    except Exception as e:
        print(f"MONITOR ERROR: {e}")
        return

    remove = []

    for symbol, pos in POSITIONS.items():

        try:

            df = data[symbol]

            curr = df['Close'].iloc[-1]

            # ===== PARTIAL =====

            if (
                curr >= pos['buy'] * (1 + PARTIAL_BOOK_TRIGGER)
                and not pos['partial_done']
            ):

                partial_qty = int(
                    pos['qty'] * PARTIAL_BOOK_QTY
                )

                pnl = (
                    (curr - pos['buy']) *
                    partial_qty
                )

                DAILY_PNL += pnl

                pos['qty'] -= partial_qty

                pos['partial_done'] = True

                send_msg(
                    f"💰 *PARTIAL EXIT*\n"
                    f"{symbol.replace('.NS','')}\n"
                    f"P&L: ₹{pnl:.0f}"
                )

            # ===== BREAK EVEN =====

            if (
                curr >= pos['buy'] * (1 + BREAK_EVEN_TRIGGER)
                and not pos['be_done']
            ):

                pos['sl'] = pos['buy']

                pos['be_done'] = True

                send_msg(
                    f"🛡️ *BREAK EVEN*\n"
                    f"{symbol.replace('.NS','')}"
                )

            # ===== TRAILING =====

            if curr >= pos['buy'] * 1.03:

                new_sl = curr * 0.98

                if new_sl > pos['sl']:
                    pos['sl'] = new_sl

            # ===== AUTO EXIT =====

            entry_time = datetime.fromisoformat(
                pos['time']
            )

            if (
                datetime.now(IST) - entry_time
            ).days >= AUTO_EXIT_DAYS:

                pnl = (
                    (curr - pos['buy']) *
                    pos['qty']
                )

                DAILY_PNL += pnl

                if pnl >= 0:
                    WINS += 1
                else:
                    LOSSES += 1

                send_msg(
                    f"⏰ *AUTO EXIT*\n"
                    f"{symbol.replace('.NS','')}\n"
                    f"P&L: ₹{pnl:.0f}"
                )

                remove.append(symbol)

                continue

            # ===== TARGET =====

            if curr >= pos['target']:

                pnl = (
                    (curr - pos['buy']) *
                    pos['qty']
                )

                DAILY_PNL += pnl

                WINS += 1

                send_msg(
                    f"🎯 *TARGET HIT*\n"
                    f"{symbol.replace('.NS','')}\n"
                    f"P&L: ₹{pnl:.0f}"
                )

                remove.append(symbol)

            # ===== STOP LOSS =====

            elif curr <= pos['sl']:

                pnl = (
                    (curr - pos['buy']) *
                    pos['qty']
                )

                DAILY_PNL += pnl

                LOSSES += 1

                send_msg(
                    f"🛑 *STOP LOSS*\n"
                    f"{symbol.replace('.NS','')}\n"
                    f"P&L: ₹{pnl:.0f}"
                )

                remove.append(symbol)

        except Exception as e:
            print(f"{symbol} MONITOR ERROR: {e}")

    for s in remove:

        if s in POSITIONS:
            del POSITIONS[s]

    safe_save()

# ================= TELEGRAM COMMANDS =================

@bot.message_handler(commands=['start', 'status'])

def status(message):

    total = WINS + LOSSES

    winrate = (
        (WINS / total) * 100
        if total > 0 else 0
    )

    msg = (
        f"🚩 *V43.5 BRAHMASTRA PRO*\n\n"
        f"💰 Daily P&L: ₹{DAILY_PNL:.0f}\n"
        f"📈 Positions: {len(POSITIONS)}/{MAX_POSITIONS}\n"
        f"✅ Wins: {WINS}\n"
        f"❌ Losses: {LOSSES}\n"
        f"🎯 WinRate: {winrate:.1f}%\n\n"
    )

    if POSITIONS:

        for s, p in POSITIONS.items():

            msg += (
                f"• {s.replace('.NS','')}\n"
                f"Buy: ₹{p['buy']:.2f}\n"
                f"SL: ₹{p['sl']:.2f}\n"
                f"Qty: {p['qty']}\n\n"
            )

    else:
        msg += "No Active Positions"

    bot.reply_to(
        message,
        msg,
        parse_mode="Markdown"
    )

# ================= MAIN LOOP =================

def main_loop():

    global LAST_SCAN
    global LAST_MONITOR
    global MORNING_SENT
    global EVENING_SENT
    global DAILY_PNL
    global TRADING_HALTED
    global WINS
    global LOSSES

    while True:

        try:

            now = datetime.now(IST)

            current_time = now.strftime("%H:%M")

            # ===== MORNING MESSAGE =====

            if (
                current_time == "09:20"
                and not MORNING_SENT
                and now.weekday() < 5
            ):

                send_msg(
                    "🚩 *जय श्री राम* 🚩\n"
                    "V43.5 BRAHMASTRA ACTIVE ✅\n"
                    "⚡ 5-Minute Rotational Scanner ON"
                )

                MORNING_SENT = True
                EVENING_SENT = False

            # ===== MARKET HOURS =====

            if (
                now.weekday() < 5
                and "09:20" <= current_time <= "15:20"
            ):

                # ===== 5 MINUTE SCANNER =====

                if (
                    now.minute % 5 == 0
                    and LAST_SCAN != current_time
                ):

                    LAST_SCAN = current_time

                    scan_and_trade()

                # ===== MONITOR =====

                if (
                    time.time() - LAST_MONITOR
                ) > MONITOR_INTERVAL:

                    LAST_MONITOR = time.time()

                    monitor_positions()

            # ===== EVENING REPORT =====

            if (
                current_time == "15:30"
                and not EVENING_SENT
                and now.weekday() < 5
            ):

                total = WINS + LOSSES

                winrate = (
                    (WINS / total) * 100
                    if total > 0 else 0
                )

                msg = (
                    f"📊 *DAILY REPORT*\n\n"
                    f"💰 P&L: ₹{DAILY_PNL:.0f}\n"
                    f"✅ Wins: {WINS}\n"
                    f"❌ Losses: {LOSSES}\n"
                    f"🎯 WinRate: {winrate:.1f}%\n"
                    f"📈 Open Positions: {len(POSITIONS)}"
                )

                send_msg(msg)

                DAILY_PNL = 0
                WINS = 0
                LOSSES = 0

                TRADING_HALTED = False

                safe_save()

                EVENING_SENT = True
                MORNING_SENT = False

            time.sleep(5)

        except Exception as e:

            print(f"MAIN LOOP ERROR: {e}")

            time.sleep(10)

# ================= START =================

if __name__ == "__main__":

    Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=10000
        ),
        daemon=True
    ).start()

    send_msg(
        "🚀 *V43.5 BRAHMASTRA PRO STARTED* 🚀\n"
        "⚡ 5-Minute Rotational Scanner ACTIVE"
    )

    Thread(
        target=main_loop,
        daemon=True
    ).start()

    while True:

        try:

            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60
            )

        except Exception as e:

            print(f"POLL ERROR: {e}")

            time.sleep(15)
