# 🚩 JAI SHREE RAM - V44 BRAHMASTRA AI PRO INDIA FINAL 🚩

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

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

IST = pytz.timezone("Asia/Kolkata")

DATA_FILE = "v44_state.json"

# =========================================================
# CAPITAL SETTINGS
# =========================================================

CAPITAL = 100000

RISK_PER_TRADE = 0.01

MAX_POSITIONS = 4
MAX_SECTOR_POSITIONS = 2

MAX_CAPITAL_PER_TRADE = 0.20

DAILY_LOSS_LIMIT = -1500

# =========================================================
# STRATEGY SETTINGS
# =========================================================

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

# =========================================================
# INDIA MARKET FILTERS
# =========================================================

VIX_LIMIT = 20

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

@app.route('/')
def home():
    return "🚩 V44 BRAHMASTRA AI PRO LIVE 🚩"

# =========================================================
# STORAGE
# =========================================================

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

        logging.error(f"SAVE ERROR: {e}")

def load_data():

    if os.path.exists(DATA_FILE):

        try:

            with open(DATA_FILE, "r") as f:
                data = json.load(f)

            if data.get("date") == str(datetime.now(IST).date()):

                logging.info("Previous State Loaded")

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

# =========================================================
# TELEGRAM
# =========================================================

def send_msg(msg):

    try:

        bot.send_message(
            CHAT_ID,
            msg,
            parse_mode="HTML"
        )

    except Exception as e:

        logging.error(f"TG ERROR: {e}")

# =========================================================
# NIFTY 250
# =========================================================

def get_nifty250():

    try:

        df = pd.read_csv(
            "https://archives.nseindia.com/content/indices/ind_nifty250list.csv"
        )

        return [
            s + ".NS"
            for s in df["Symbol"].tolist()
        ]

    except Exception as e:

        logging.error(f"NIFTY250 ERROR: {e}")

        return [
            "RELIANCE.NS",
            "TCS.NS",
            "INFY.NS",
            "SBIN.NS",
            "TATAMOTORS.NS"
        ]

STOCKS = get_nifty250()

# =========================================================
# SECTOR MAP
# =========================================================

SECTOR_MAP = {

    "RELIANCE.NS": "ENERGY",
    "ONGC.NS": "ENERGY",

    "TCS.NS": "IT",
    "INFY.NS": "IT",
    "HCLTECH.NS": "IT",

    "SBIN.NS": "BANK",
    "HDFCBANK.NS": "BANK",
    "ICICIBANK.NS": "BANK",

    "TATAMOTORS.NS": "AUTO",
    "MARUTI.NS": "AUTO",

    "SUNPHARMA.NS": "PHARMA",

    "LT.NS": "INFRA"
}

# =========================================================
# INDIA VIX FILTER
# =========================================================

def check_vix():

    try:

        vix = yf.download(
            "^INDIAVIX",
            period="5d",
            interval="1d",
            progress=False
        )

        if vix.empty:
            return True

        current_vix = float(vix['Close'].iloc[-1])

        logging.info(f"INDIA VIX: {current_vix}")

        return current_vix < VIX_LIMIT

    except Exception as e:

        logging.error(f"VIX ERROR: {e}")

        return True

# =========================================================
# MARKET TREND
# =========================================================

def market_trend():

    try:

        df = yf.download(
            "^NSEI",
            period="200d",
            interval="1d",
            progress=False
        )

        if len(df) < 50:
            return True

        df['EMA50'] = df['Close'].ewm(span=50).mean()

        bullish = (
            df['Close'].iloc[-1]
            >
            df['EMA50'].iloc[-1]
        )

        return bullish

    except Exception as e:

        logging.error(f"MARKET TREND ERROR: {e}")

        return True

# =========================================================
# INDICATORS
# =========================================================

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

# =========================================================
# SCANNER
# =========================================================

def scan_and_trade():

    global SCAN_INDEX
    global TRADING_HALTED

    try:

        # =========================
        # RISK STOP
        # =========================

        if TRADING_HALTED:
            return

        if DAILY_PNL <= DAILY_LOSS_LIMIT:

            TRADING_HALTED = True

            send_msg(
                f"🛑 <b>DAILY LOSS LIMIT HIT</b>\n"
                f"P&L: ₹{DAILY_PNL:.0f}"
            )

            return

        # =========================
        # POSITION LIMIT
        # =========================

        if len(POSITIONS) >= MAX_POSITIONS:
            return

        # =========================
        # MARKET FILTER
        # =========================

        if not market_trend():

            logging.info("Market Weak")

            return

        # =========================
        # VIX FILTER
        # =========================

        if not check_vix():

            logging.info("High VIX - No Trade")

            return

        # =========================
        # ROTATIONAL SCAN
        # =========================

        available = [
            s for s in STOCKS
            if s not in POSITIONS
        ]

        if not available:
            return

        start = SCAN_INDEX
        end = start + BATCH_SIZE

        scan_list = available[start:end]

        SCAN_INDEX = (
            0 if end >= len(available)
            else end
        )

        logging.info(f"Scanning {len(scan_list)} Stocks")

        data = yf.download(
            scan_list,
            period="100d",
            interval="1d",
            group_by='ticker',
            progress=False,
            threads=False
        )

        candidates = []

        # =========================
        # STOCK ANALYSIS
        # =========================

        for symbol in scan_list:

            try:

                df = (
                    data[symbol].copy()
                    if isinstance(data.columns, pd.MultiIndex)
                    else data.copy()
                )

                if df.empty:
                    continue

                df = calculate_indicators(df)

                if len(df) < 50:
                    continue

                last = df.iloc[-1]
                prev = df.iloc[-2]

                # =========================
                # CONDITIONS
                # =========================

                if last['ADX'] < ADX_THRESHOLD:
                    continue

                if not (55 < last['RSI'] < 70):
                    continue

                if last['Close'] < last['EMA50']:
                    continue

                breakout = (
                    last['Close'] > prev['High']
                    and
                    last['Close'] > last['EMA20']
                )

                if not breakout:
                    continue

                # =========================
                # SECTOR CONTROL
                # =========================

                sector = SECTOR_MAP.get(
                    symbol,
                    "OTHER"
                )

                sector_count = sum(
                    1 for s in POSITIONS
                    if SECTOR_MAP.get(s) == sector
                )

                if sector_count >= MAX_SECTOR_POSITIONS:
                    continue

                # =========================
                # AI SCORE
                # =========================

                score = 50

                avg_vol = (
                    df['Volume']
                    .rolling(20)
                    .mean()
                    .iloc[-1]
                )

                if last['Volume'] > avg_vol * 1.5:
                    score += 20

                if last['RSI'] > 60:
                    score += 10

                if last['ADX'] > 30:
                    score += 10

                candidates.append((
                    symbol,
                    score,
                    last['Close'],
                    last['ATR']
                ))

            except Exception as e:

                logging.error(f"{symbol} ERROR: {e}")

        # =========================
        # BEST STOCKS
        # =========================

        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        # =========================
        # BUY
        # =========================

        for symbol, score, price, atr in candidates:

            if len(POSITIONS) >= MAX_POSITIONS:
                break

            risk_amount = CAPITAL * RISK_PER_TRADE

            sl_distance = atr * ATR_SL_MULTIPLIER

            if sl_distance <= 0:
                continue

            qty = int(
                risk_amount / sl_distance
            )

            if qty <= 0:
                continue

            capital_used = price * qty

            if capital_used > CAPITAL * MAX_CAPITAL_PER_TRADE:
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
                f"🚀 <b>BUY SIGNAL</b>\n\n"
                f"<b>{symbol}</b>\n"
                f"Price: ₹{price:.2f}\n"
                f"Qty: {qty}\n"
                f"SL: ₹{sl:.2f}\n"
                f"Target: ₹{target:.2f}\n"
                f"AI Score: {score}"
            )

            logging.info(f"BUY: {symbol}")

    except Exception as e:

        logging.error(f"SCAN ERROR: {e}")

# =========================================================
# POSITION MONITOR
# =========================================================

def monitor_positions():

    global DAILY_PNL
    global WINS
    global LOSSES

    try:

        if not POSITIONS:
            return

        data = yf.download(
            list(POSITIONS.keys()),
            period="1d",
            interval="1m",
            group_by='ticker',
            progress=False,
            threads=False
        )

        remove = []

        for symbol, pos in list(POSITIONS.items()):

            try:

                df = (
                    data[symbol]
                    if isinstance(data.columns, pd.MultiIndex)
                    else data
                )

                if df.empty:
                    continue

                curr = df['Close'].iloc[-1]

                # =========================
                # PARTIAL EXIT
                # =========================

                if (
                    curr >= pos['buy'] * (1 + PARTIAL_BOOK_TRIGGER)
                    and not pos['partial_done']
                ):

                    partial_qty = int(
                        pos['qty'] * PARTIAL_BOOK_QTY
                    )

                    pnl = (
                        (curr - pos['buy'])
                        * partial_qty
                    )

                    DAILY_PNL += pnl

                    pos['qty'] -= partial_qty

                    pos['partial_done'] = True

                    send_msg(
                        f"💰 <b>PARTIAL EXIT</b>\n"
                        f"{symbol}\n"
                        f"P&L: ₹{pnl:.0f}"
                    )

                # =========================
                # BREAK EVEN
                # =========================

                if (
                    curr >= pos['buy'] * (1 + BREAK_EVEN_TRIGGER)
                    and not pos['be_done']
                ):

                    pos['sl'] = pos['buy']

                    pos['be_done'] = True

                    send_msg(
                        f"🛡️ <b>BREAK EVEN</b>\n"
                        f"{symbol}"
                    )

                # =========================
                # TRAILING SL
                # =========================

                if curr >= pos['buy'] * 1.03:

                    new_sl = curr * 0.98

                    if new_sl > pos['sl']:

                        pos['sl'] = new_sl

                # =========================
                # AUTO EXIT
                # =========================

                entry_time = datetime.fromisoformat(
                    pos['time']
                )

                if (
                    datetime.now(IST) - entry_time
                ).days >= AUTO_EXIT_DAYS:

                    pnl = (
                        (curr - pos['buy'])
                        * pos['qty']
                    )

                    DAILY_PNL += pnl

                    if pnl >= 0:
                        WINS += 1
                    else:
                        LOSSES += 1

                    send_msg(
                        f"⏰ <b>AUTO EXIT</b>\n"
                        f"{symbol}\n"
                        f"P&L: ₹{pnl:.0f}"
                    )

                    remove.append(symbol)

                    continue

                # =========================
                # TARGET
                # =========================

                if curr >= pos['target']:

                    pnl = (
                        (curr - pos['buy'])
                        * pos['qty']
                    )

                    DAILY_PNL += pnl

                    WINS += 1

                    send_msg(
                        f"🎯 <b>TARGET HIT</b>\n"
                        f"{symbol}\n"
                        f"P&L: ₹{pnl:.0f}"
                    )

                    remove.append(symbol)

                # =========================
                # STOPLOSS
                # =========================

                elif curr <= pos['sl']:

                    pnl = (
                        (curr - pos['buy'])
                        * pos['qty']
                    )

                    DAILY_PNL += pnl

                    LOSSES += 1

                    send_msg(
                        f"🛑 <b>STOP LOSS</b>\n"
                        f"{symbol}\n"
                        f"P&L: ₹{pnl:.0f}"
                    )

                    remove.append(symbol)

            except Exception as e:

                logging.error(f"{symbol} MONITOR ERROR: {e}")

        # =========================
        # REMOVE CLOSED
        # =========================

        for s in remove:

            if s in POSITIONS:
                del POSITIONS[s]

        safe_save()

    except Exception as e:

        logging.error(f"MONITOR ERROR: {e}")

# =========================================================
# TELEGRAM STATUS
# =========================================================

@bot.message_handler(commands=['start', 'status'])

def status(message):

    total = WINS + LOSSES

    winrate = (
        (WINS / total) * 100
        if total > 0 else 0
    )

    msg = (
        f"🚩 <b>V44 BRAHMASTRA AI PRO</b>\n\n"
        f"💰 Daily P&L: ₹{DAILY_PNL:.0f}\n"
        f"📈 Positions: {len(POSITIONS)}/{MAX_POSITIONS}\n"
        f"✅ Wins: {WINS}\n"
        f"❌ Losses: {LOSSES}\n"
        f"🎯 WinRate: {winrate:.1f}%\n\n"
    )

    if POSITIONS:

        for s, p in POSITIONS.items():

            msg += (
                f"• {s}\n"
                f"Buy: ₹{p['buy']:.2f}\n"
                f"SL: ₹{p['sl']:.2f}\n"
                f"Qty: {p['qty']}\n\n"
            )

    else:

        msg += "No Active Positions"

    bot.reply_to(
        message,
        msg,
        parse_mode="HTML"
    )

# =========================================================
# MAIN LOOP
# =========================================================

def main_loop():

    logging.info("BRAHMASTRA Started")

    while True:

        try:

            now = datetime.now(IST)

            if (
                now.weekday() < 5
                and
                dtime(9,20) <= now.time() <= dtime(15,30)
            ):

                # =========================
                # 5 MINUTE SCAN
                # =========================

                if (
                    now.minute % 5 == 0
                    and now.second < 10
                ):

                    scan_and_trade()

                # =========================
                # POSITION MONITOR
                # =========================

                monitor_positions()

                time.sleep(15)

            else:

                time.sleep(60)

        except Exception as e:

            logging.error(f"MAIN LOOP ERROR: {e}")

            time.sleep(15)

# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=10000
        ),
        daemon=True
    ).start()

    send_msg(
        "🚀 <b>V44 BRAHMASTRA AI PRO STARTED</b>\n"
        "🇮🇳 India Market AI Scanner ACTIVE\n"
        "⚡ VIX Protection ENABLED\n"
        "⚡ Smart Risk Management ENABLED"
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

            logging.error(f"POLL ERROR: {e}")

            time.sleep(15)
