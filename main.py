import os
import time
import sqlite3
import threading
import logging
import warnings
import random
from datetime import datetime, timedelta
import pandas as pd
import requests
import yfinance as yf
import ta
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed

# फालतू चेतावनियों को रोकना
warnings.filterwarnings("ignore")

# --- ⚙️ CONFIGURATION ---
IST = pytz.timezone("Asia/Kolkata")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_FILE = "brahmand_kavach_v31.db"

INITIAL_CAPITAL = 100000
RISK_PER_TRADE = 0.015    
MAX_OPEN_TRADES = 5
SCAN_INTERVAL = 1800      
MAX_WORKERS = 2           # <--- एंटी-ब्लॉक के लिए कम किया गया

LAST_GREETING_DATE = None
LAST_REPORT_DATE = None
LAST_UPDATE_ID = 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- 📲 TELEGRAM CORE ---
def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, data=payload, timeout=15)
    except Exception as e: logging.error(f"Telegram Error: {e}")

# --- 📊 REPORTING & GREETINGS ---
def get_pnl_report(days=1):
    conn = sqlite3.connect(DB_FILE)
    since_date = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("SELECT symbol, pnl FROM trades WHERE status='CLOSED' AND exit_time >= ?", (since_date,)).fetchall()
    conn.close()
    if not rows: return "आज कोई ट्रेड क्लोज नहीं हुआ।"
    total_pnl = sum(r[1] for r in rows)
    detail = "\n".join([f"🔹 {r[0]}: ₹{r[1]:,.2f}" for r in rows])
    return f"{detail}\n\n💰 *Total P&L:* ₹{total_pnl:,.2f}"

def check_special_messages():
    global LAST_GREETING_DATE, LAST_REPORT_DATE
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    # सुबह 9:30 बजे जय श्री राम
    if now.hour == 9 and now.minute >= 30 and LAST_GREETING_DATE != today:
        send_telegram("🚩 *जय श्री राम, ललित जी!* \nमार्केट खुल गया है। आपका दिन मंगलमय और प्रॉफिटेबल हो। 🙏")
        LAST_GREETING_DATE = today
    # दोपहर 3:35 बजे क्लोजिंग रिपोर्ट
    if now.hour == 15 and now.minute >= 35 and LAST_REPORT_DATE != today:
        report = get_pnl_report(1)
        send_telegram(f"📉 *आज की क्लोजिंग रिपोर्ट:* \n\n{report}")
        LAST_REPORT_DATE = today

# --- 🗄️ DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, entry REAL NOT NULL, sl REAL NOT NULL, target REAL NOT NULL, qty INTEGER NOT NULL, status TEXT NOT NULL, highest_price REAL, entry_time TEXT, exit_time TEXT, pnl REAL DEFAULT 0)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_open_symbol ON trades(symbol) WHERE status='OPEN'")
    conn.commit(); conn.close()

# --- 🔍 ANALYSIS LOGIC ---
def analyze_stock(symbol):
    try:
        # एंटी-ब्लॉक डिले: याहू को लगेगा कि कोई इंसान चार्ट देख रहा है
        time.sleep(2.5 + random.random()) 
        
        df = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=True, threads=False)
        if df.empty or len(df) < 220: return None
        
        close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
        ema50 = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean()
        rsi = ta.momentum.RSIIndicator(close, 14).rsi()
        adx = ta.trend.ADXIndicator(high, low, close, 14).adx()
        atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()
        price = float(close.iloc[-1])
        
        # EMA Slope (Anti-Sideways)
        ema_slope = (ema50.iloc[-1] - ema50.iloc[-5]) / ema50.iloc[-5] * 100
        vol_breakout = vol.iloc[-1] > vol.rolling(20).mean().iloc[-1] * 2.5
        bullish_trend = price > ema50.iloc[-1] > ema200.iloc[-1]
        momentum_ok = (50 < rsi.iloc[-1] < 66) and (adx.iloc[-1] > 25) and (ema_slope > 0.2)
        
        if bullish_trend and momentum_ok and vol_breakout:
            sl = round(price - (2 * atr.iloc[-1]), 2)
            target = round(price + (4 * atr.iloc[-1]), 2)
            qty = min(int((INITIAL_CAPITAL * RISK_PER_TRADE) / (price - sl)), int((INITIAL_CAPITAL / MAX_OPEN_TRADES) / price))
            if qty > 0: return {"symbol": symbol, "price": round(price, 2), "sl": sl, "target": target, "qty": qty}
    except Exception as e:
        if "429" in str(e): time.sleep(60) # ब्लॉक होने पर 1 मिनट का ब्रेक
        return None

# --- 🔄 MONITORING ---
def manage_exits():
    conn = sqlite3.connect(DB_FILE)
    trades = conn.execute("SELECT id, symbol, entry, sl, target, qty, highest_price FROM trades WHERE status='OPEN'").fetchall()
    for tid, sym, entry, sl, target, qty, high_price in trades:
        time.sleep(1.5)
        try:
            df = yf.download(sym, period="2d", interval="5m", progress=False, auto_adjust=True, threads=False)
            current = float(df["Close"].iloc[-1])
            if current > high_price:
                high_price = current
                conn.execute("UPDATE trades SET highest_price=? WHERE id=?", (high_price, tid))
            trail_sl = max(sl, high_price * 0.97)
            reason = "Trailing SL 🛑" if current <= trail_sl else "Target 🎯" if current >= target else None
            if reason:
                pnl = round((current - entry) * qty, 2)
                conn.execute("UPDATE trades SET status='CLOSED', exit_time=?, pnl=? WHERE id=?", (datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), pnl, tid))
                send_telegram(f"🔴 *EXIT:* `{sym}` | {reason}\nPrice: ₹{current:.2f} | P&L: ₹{pnl:.2f}")
        except: continue
    conn.commit(); conn.close()

# --- 🤖 TELEGRAM COMMANDS ---
def check_telegram_commands():
    global LAST_UPDATE_ID
    if not BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        data = requests.get(url, params={"timeout": 2, "offset": LAST_UPDATE_ID}, timeout=5).json()
        for update in data.get("result", []):
            LAST_UPDATE_ID = update["update_id"] + 1
            text = update.get("message", {}).get("text", "").strip().lower()
            if text == "#status":
                conn = sqlite3.connect(DB_FILE)
                net_pnl = conn.execute("SELECT SUM(pnl) FROM trades WHERE status='CLOSED'").fetchone()[0] or 0
                month_pnl = conn.execute("SELECT SUM(pnl) FROM trades WHERE status='CLOSED' AND exit_time >= ?", ((datetime.now(IST) - timedelta(days=180)).strftime("%Y-%m-%d"),)).fetchone()[0] or 0
                open_trades = conn.execute("SELECT symbol, entry FROM trades WHERE status='OPEN'").fetchall()
                conn.close()
                msg = f"📊 *BRAHMAND KAVACH STATUS*\n\n💰 Total P&L: ₹{net_pnl:,.2f}\n📅 6 Month P&L: ₹{month_pnl:,.2f}\n\n📦 *Open Positions:* "
                msg += "\n".join([f"\n- {t[0]} @ ₹{t[1]}" for t in open_trades]) if open_trades else "None"
                send_telegram(msg)
    except: pass

# --- 🌐 HEALTH HANDLER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Active")
    def log_message(self, format, *args): return

def market_open():
    now = datetime.now(IST)
    current_minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and 555 <= current_minutes <= 930

# --- 🚀 RUNNER ENGINE ---
def run():
    init_db()
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    send_telegram("🚀 *BRAHMAND KAVACH v31.6 LIVE (SAFE MODE)*")
    
    try:
        df_nse = pd.read_csv(NSE500_URL)
        df_nse.to_csv("nifty500_backup.csv", index=False)
        symbols = (df_nse["Symbol"] + ".NS").tolist()
    except:
        try:
            symbols = (pd.read_csv("nifty500_backup.csv")["Symbol"] + ".NS").tolist()
        except: symbols = []

    while True:
        try:
            check_telegram_commands()
            check_special_messages()
            manage_exits()
            if market_open():
                conn = sqlite3.connect(DB_FILE)
                count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
                conn.close()
                if count < MAX_OPEN_TRADES:
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                        futures = {executor.submit(analyze_stock, s): s for s in symbols}
                        for future in as_completed(futures):
                            res = future.result()
                            if res:
                                conn = sqlite3.connect(DB_FILE)
                                try:
                                    conn.execute("INSERT INTO trades (symbol, entry, sl, target, qty, status, highest_price, entry_time) VALUES (?,?,?,?,?,?,?,?)", (res['symbol'], res['price'], res['sl'], res['target'], res['qty'], "OPEN", res['price'], datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")))
                                    conn.commit()
                                    send_telegram(f"🟢 *BUY:* `{res['symbol']}`\n━━━━━━━━━━━━━━━\n💰 Entry: ₹{res['price']:,.2f}\n🛑 SL: ₹{res['sl']:,.2f}\n🎯 Target: ₹{res['target']:,.2f}\n📦 Qty: {res['qty']}")
                                except: pass
                                finally: conn.close()
                time.sleep(SCAN_INTERVAL)
            else: time.sleep(20)
        except Exception as e: logging.error(f"Loop: {e}"); time.sleep(30)

if __name__ == "__main__": run()
