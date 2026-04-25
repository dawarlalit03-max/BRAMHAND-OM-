# ============================================================
# 🏆 BRAHMAND KAVACH v31.2 PRODUCTION FINAL
# Lalit Edition | Render + Telegram + SQLite
# ============================================================

import os
import time
import sqlite3
import threading
import logging
import warnings
from io import StringIO
from datetime import datetime

import pandas as pd
import requests
import yfinance as yf
import ta
import pytz

from http.server import HTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

# ============================================================
# 🌏 TIMEZONE
# ============================================================
IST = pytz.timezone("Asia/Kolkata")

# ============================================================
# ⚙️ CONFIGURATION
# ============================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DB_FILE = "brahmand_kavach_v31.db"

INITIAL_CAPITAL = 100000
RISK_PER_TRADE = 0.02
MAX_OPEN_TRADES = 5
SCAN_INTERVAL = 900
MAX_WORKERS = 5

NSE500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
BACKUP_FILE = "nifty500_backup.csv"

# ============================================================
# 📝 LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ============================================================
# 🌐 KEEP ALIVE SERVER
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brahmand Kavach v31.2 Running")

    def log_message(self, format, *args):
        return


def start_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(
        target=server.serve_forever,
        daemon=True
    ).start()
    logging.info(f"Server started on port {port}")


# ============================================================
# 📲 TELEGRAM
# ============================================================
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("Telegram credentials missing.")
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            },
            timeout=15
        )

        if response.status_code != 200:
            logging.error(f"Telegram API Error: {response.text}")

    except Exception as e:
        logging.error(f"Telegram Exception: {e}")


# ============================================================
# 🗄️ DATABASE
# ============================================================
def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry REAL NOT NULL,
            sl REAL NOT NULL,
            target REAL NOT NULL,
            qty INTEGER NOT NULL,
            status TEXT NOT NULL,
            highest_price REAL,
            entry_time TEXT,
            exit_time TEXT,
            pnl REAL DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_open_symbol
        ON trades(symbol)
        WHERE status='OPEN'
    """)

    conn.commit()
    conn.close()


def get_open_count():
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE status='OPEN'"
    ).fetchone()[0]
    conn.close()
    return count


def trade_exists(symbol):
    conn = get_connection()
    exists = conn.execute(
        "SELECT 1 FROM trades WHERE symbol=? AND status='OPEN'",
        (symbol,)
    ).fetchone()
    conn.close()
    return exists is not None


# ============================================================
# 📊 NIFTY 500 LIST
# ============================================================
def get_nifty500_symbols():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(
            NSE500_URL,
            headers=headers,
            timeout=20
        )

        response.raise_for_status()

        df = pd.read_csv(StringIO(response.text))
        df.to_csv(BACKUP_FILE, index=False)

        logging.info("Downloaded latest NSE500 list.")

    except Exception as e:
        logging.warning(f"Using backup file: {e}")
        df = pd.read_csv(BACKUP_FILE)

    return (df["Symbol"] + ".NS").tolist()


# ============================================================
# 🔍 ANALYSIS
# ============================================================
def analyze_stock(symbol):
    try:
        df = yf.download(
            symbol,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False
        )

        if df.empty or len(df) < 220:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        ema50 = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean()

        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        adx = ta.trend.ADXIndicator(
            high, low, close, 14
        ).adx()

        atr = ta.volatility.AverageTrueRange(
            high, low, close, 14
        ).average_true_range()

        avg_vol = volume.rolling(20).mean()

        price = float(close.iloc[-1])

        valid = (
            price > ema50.iloc[-1] > ema200.iloc[-1]
            and 44 < rsi.iloc[-1] < 66
            and adx.iloc[-1] > 25
            and volume.iloc[-1] > avg_vol.iloc[-1] * 2.5
        )

        if not valid:
            return None

        sl = round(price - (2 * atr.iloc[-1]), 2)
        target = round(price + (4 * atr.iloc[-1]), 2)

        risk_amount = INITIAL_CAPITAL * RISK_PER_TRADE
        per_share_risk = price - sl

        if per_share_risk <= 0:
            return None

        qty = int(risk_amount / per_share_risk)

        capital_limit = int(
            (INITIAL_CAPITAL / MAX_OPEN_TRADES) / price
        )

        qty = min(qty, capital_limit)

        if qty <= 0:
            return None

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "sl": sl,
            "target": target,
            "qty": qty
        }

    except Exception as e:
        logging.debug(f"{symbol}: {e}")
        return None


# ============================================================
# 🛡️ EXIT MANAGEMENT
# ============================================================
def manage_exits():
    conn = get_connection()

    trades = conn.execute("""
        SELECT id, symbol, entry, sl,
               target, qty, highest_price
        FROM trades
        WHERE status='OPEN'
    """).fetchall()

    for trade in trades:
        tid, sym, entry, sl, target, qty, high_price = trade

        try:
            df = yf.download(
                sym,
                period="2d",
                interval="5m",
                progress=False,
                auto_adjust=True,
                threads=False
            )

            if df.empty:
                continue

            current = float(df["Close"].iloc[-1])

            if current > high_price:
                high_price = current
                conn.execute(
                    "UPDATE trades SET highest_price=? WHERE id=?",
                    (high_price, tid)
                )

            trail_sl = max(sl, high_price * 0.97)

            exit_reason = None

            if current <= trail_sl:
                exit_reason = "Trailing Stop Hit 🛑"

            elif current >= target:
                exit_reason = "Target Achieved 🎯"

            if exit_reason:
                pnl = round((current - entry) * qty, 2)

                conn.execute("""
                    UPDATE trades
                    SET status='CLOSED',
                        exit_time=?,
                        pnl=?
                    WHERE id=?
                """, (
                    datetime.now(IST).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    pnl,
                    tid
                ))

                send_telegram(
                    f"🔴 *EXIT SIGNAL*\n\n"
                    f"Stock: `{sym}`\n"
                    f"Reason: {exit_reason}\n"
                    f"Exit: ₹{current:.2f}\n"
                    f"P&L: ₹{pnl:.2f}"
                )

        except Exception as e:
            logging.error(f"Exit Error {sym}: {e}")

    conn.commit()
    conn.close()


# ============================================================
# 🟢 ENTRY EXECUTION
# ============================================================
def execute_trade(signal):
    if trade_exists(signal["symbol"]):
        return

    conn = get_connection()

    try:
        conn.execute("""
            INSERT INTO trades (
                symbol, entry, sl, target,
                qty, status, highest_price,
                entry_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal["symbol"],
            signal["price"],
            signal["sl"],
            signal["target"],
            signal["qty"],
            "OPEN",
            signal["price"],
            datetime.now(IST).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ))

        conn.commit()

        send_telegram(
            f"🟢 *BUY SIGNAL*\n\n"
            f"Stock: `{signal['symbol']}`\n"
            f"Entry: ₹{signal['price']}\n"
            f"SL: ₹{signal['sl']}\n"
            f"Target: ₹{signal['target']}\n"
            f"Qty: {signal['qty']}"
        )

        logging.info(f"Trade Opened: {signal['symbol']}")

    except sqlite3.IntegrityError:
        pass

    finally:
        conn.close()


# ============================================================
# ⏰ MARKET HOURS
# ============================================================
def market_open():
    now = datetime.now(IST)

    if now.weekday() >= 5:
        return False

    minutes = now.hour * 60 + now.minute
    return 555 <= minutes <= 930


# ============================================================
# 🚀 MAIN LOOP
# ============================================================
def run():
    init_db()
    start_server()

    send_telegram(
        "🚀 *BRAHMAND KAVACH v31.2 STARTED*\n"
        "RSI 44-66 | ADX 25+ | Volume 2.5x"
    )

    symbols = get_nifty500_symbols()

    while True:
        try:
            manage_exits()

            if market_open():
                open_trades = get_open_count()

                if open_trades < MAX_OPEN_TRADES:
                    logging.info("Scanning Market...")

                    with ThreadPoolExecutor(
                        max_workers=MAX_WORKERS
                    ) as executor:

                        futures = {
                            executor.submit(
                                analyze_stock, sym
                            ): sym
                            for sym in symbols
                        }

                        for future in as_completed(futures):
                            if get_open_count() >= MAX_OPEN_TRADES:
                                break

                            result = future.result()

                            if result:
                                execute_trade(result)

                time.sleep(SCAN_INTERVAL)

            else:
                time.sleep(60)

        except Exception as e:
            logging.exception(f"Main Loop Error: {e}")
            time.sleep(60)


# ============================================================
# 🎯 ENTRY POINT
# ============================================================
if __name__ == "__main__":
    run()
