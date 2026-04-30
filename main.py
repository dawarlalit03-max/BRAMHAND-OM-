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

# --- CONFIGURATION ---
IST = pytz.timezone("Asia/Kolkata")
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

LAST_GREETING_DATE = None
LAST_WEEKLY_REPORT = None
LAST_UPDATE_ID = 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- CORE FUNCTIONS ---
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e: logging.error(f"Telegram Error: {e}")

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, 
        entry REAL NOT NULL, sl REAL NOT NULL, target REAL NOT NULL, 
        qty INTEGER NOT NULL, status TEXT NOT NULL, highest_price REAL, 
        entry_time TEXT, exit_time TEXT, pnl REAL DEFAULT 0)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_open_symbol ON trades(symbol) WHERE status='OPEN'")
    conn.commit()
    conn.close()

# --- TELEGRAM COMMAND CENTER ---
def send_morning_greeting():
    global LAST_GREETING_DATE
    now = datetime.now(IST)
    if now.hour == 9 and now.minute == 0:
        today = now.date()
        if LAST_GREETING_DATE != today:
            send_telegram("🌞 *Good Morning Lalit Ji!*\n\n📈 Brahmand Kavach Active\n🕘 Market Opening\n🔥 Ready for Trading")
            LAST_GREETING_DATE = today

def send_open_trades():
    conn = get_connection()
    rows = conn.execute("SELECT symbol, entry, qty, target, sl FROM trades WHERE status='OPEN' ORDER BY entry_time ASC").fetchall()
    conn.close()
    if not rows:
        send_telegram("📦 *OPEN TRADES*\n\nNo active positions."); return
    msg = "📦 *OPEN TRADES*\n\n"
    total_val = 0
    for sym, entry, qty, target, sl in rows:
        val = entry * qty; total_val += val
        msg += f"📌 `{sym}`\nQty: {qty} | Entry: ₹{entry:.2f}\nSL: ₹{sl:.2f} | Tgt: ₹{target:.2f}\nValue: ₹{val:,.0f}\n\n"
    msg += f"💰 Total Exposure: ₹{total_val:,.0f}"
    send_telegram(msg)

def send_portfolio_status():
    conn = get_connection()
    open_trades = conn.execute("SELECT entry, qty FROM trades WHERE status='OPEN'").fetchall()
    pnl_row = conn.execute("SELECT SUM(pnl) FROM trades WHERE status='CLOSED'").fetchone()
    conn.close()
    invested = sum(r[0] * r[1] for r in open_trades)
    msg = f"📊 *PORTFOLIO STATUS*\n\n💰 Invested: ₹{invested:,.0f}\n📈 P&L: ₹{pnl_row[0] or 0:,.2f}\n📦 Positions: {len(open_trades)}"
    send_telegram(msg)

def send_weekly_report(force=False):
    global LAST_WEEKLY_REPORT
    now = datetime.now(IST)
    if not force:
        if now.weekday() != 5 or now.hour != 18: return
        week_id = now.strftime("%Y-%W")
        if LAST_WEEKLY_REPORT == week_id: return
    else: week_id = now.strftime("%Y-%W")
    
    conn = get_connection()
    stats = conn.execute("SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END), SUM(CASE WHEN pnl<=0 THEN 1 ELSE 0 END), ROUND(SUM(pnl),2) FROM trades WHERE status='CLOSED' AND date(exit_time) >= date('now','-7 days')").fetchone()
    conn.close()
    total, wins, losses, net = stats
    win_rate = (wins/total*100) if total else 0
    send_telegram(f"📊 *WEEKLY REPORT*\n\nTotal: {total}\nWins: {wins}\nLoss: {losses}\nWin Rate: {win_rate:.1f}%\nPNL: ₹{net or 0}")
    LAST_WEEKLY_REPORT = week_id

def check_telegram_commands():
    global LAST_UPDATE_ID
    if not BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        data = requests.get(url, params={"timeout": 2, "offset": LAST_UPDATE_ID}, timeout=5).json()
        for update in data.get("result", []):
            LAST_UPDATE_ID = update["update_id"] + 1
            text = update.get("message", {}).get("text", "").strip().lower()
            if text == "#status": send_portfolio_status()
            elif text == "#open": send_open_trades()
            elif text == "#pnl": 
                conn = get_connection()
                pnl = conn.execute("SELECT SUM(pnl) FROM trades WHERE status='CLOSED'").fetchone()[0]
                conn.close()
                send_telegram(f"📈 Total P&L: ₹{pnl or 0:,.2f}")
            elif text == "#weekly": send_weekly_report(force=True)
            elif text == "#help": send_telegram("🤖 *COMMANDS*\n#status | #open | #pnl | #weekly | #help")
    except: pass

# --- ANALYSIS & EXITS ---
def analyze_stock(symbol):
    try:
        df = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 220: return None
        close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
        ema50, ema200 = close.ewm(span=50).mean(), close.ewm(span=200).mean()
        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        adx = ta.trend.ADXIndicator(high, low, close, 14).adx()
        atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        price = float(close.iloc[-1])
        if price > ema50.iloc[-1] > ema200.iloc[-1] and 44 < rsi.iloc[-1] < 66 and adx.iloc[-1] > 25 and vol.iloc[-1] > vol.rolling(20).mean().iloc[-1] * 2.5:
            sl = round(price - (2 * atr.iloc[-1]), 2)
            target = round(price + (4 * atr.iloc[-1]), 2)
            qty = min(int((INITIAL_CAPITAL * RISK_PER_TRADE) / (price - sl)), int((INITIAL_CAPITAL/MAX_OPEN_TRADES)/price))
            return {"symbol": symbol, "price": round(price, 2), "sl": sl, "target": target, "qty": qty} if qty > 0 else None
    except: return None

def manage_exits():
    conn = get_connection()
    trades = conn.execute("SELECT id, symbol, entry, sl, target, qty, highest_price FROM trades WHERE status='OPEN'").fetchall()
    for tid, sym, entry, sl, target, qty, high_price in trades:
        try:
            df = yf.download(sym, period="2d", interval="5m", progress=False, auto_adjust=True)
            current = float(df["Close"].iloc[-1])
            if current > high_price:
                high_price = current
                conn.execute("UPDATE trades SET highest_price=? WHERE id=?", (high_price, tid))
            trail_sl = max(sl, high_price * 0.97)
            reason = "Trailing SL 🛑" if current <= trail_sl else "Target 🎯" if current >= target else None
            if reason:
                pnl = round((current - entry) * qty, 2)
                conn.execute("UPDATE trades SET status='CLOSED', exit_time=?, pnl=? WHERE id=?", (datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), pnl, tid))
                send_telegram(f"🔴 *EXIT SIGNAL*\n`{sym}` | {reason}\nExit: ₹{current:.2f} | PNL: ₹{pnl:.2f}")
        except: continue
    conn.commit(); conn.close()

def market_open():
    now = datetime.now(IST)
    return now.weekday() < 5 and (555 <= now.hour * 60 + now.minute <= 930)

# --- SERVER & RUNNER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Active")
    def log_message(self, format, *args): return

def run():
    init_db(); port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    send_telegram("🚀 *BRAHMAND KAVACH v31.2 ULTIMATE LIVE*")
    try: symbols = (pd.read_csv(NSE500_URL)["Symbol"] + ".NS").tolist()
    except: symbols = []

    while True:
        try:
            send_morning_greeting(); send_weekly_report(); check_telegram_commands(); manage_exits()
            if market_open():
                conn = get_connection()
                open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
                conn.close()
                if open_count < MAX_OPEN_TRADES:
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                        futures = {executor.submit(analyze_stock, s): s for s in symbols}
                        for future in as_completed(futures):
                            res = future.result()
                            if res:
                                conn = get_connection()
                                try:
                                    if not conn.execute("SELECT 1 FROM trades WHERE symbol=? AND status='OPEN'", (res['symbol'],)).fetchone() and conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0] < MAX_OPEN_TRADES:
                                        conn.execute("INSERT INTO trades (symbol, entry, sl, target, qty, status, highest_price, entry_time) VALUES (?,?,?,?,?,?,?,?)", (res['symbol'], res['price'], res['sl'], res['target'], res['qty'], "OPEN", res['price'], datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")))
                                        conn.commit()
                                        send_telegram(f"🟢 *BUY SIGNAL*\nStock: `{res['symbol']}`\nEntry: ₹{res['price']:.2f}\nSL: ₹{res['sl']:.2f} | Tgt: ₹{res['target']:.2f}")
                                except: pass
                                finally: conn.close()
                time.sleep(SCAN_INTERVAL)
            else: time.sleep(10)
        except Exception as e: logging.error(f"Loop Error: {e}"); time.sleep(30)

if __name__ == "__main__": run()
