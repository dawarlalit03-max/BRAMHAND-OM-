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

--- ⚙️ CONFIGURATION ---

warnings.filterwarnings("ignore")
IST = pytz.timezone("Asia/Kolkata")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_FILE = "brahmand_kavach_v31_6.db"
NSE500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

BASE_CAPITAL = 100000
RISK_PER_TRADE = 0.015    # 1.5% Risk
SCAN_INTERVAL = 1800      # 30 Mins
MAX_WORKERS = 2           # Safe for Render

LAST_GREETING_DATE = None
LAST_UPDATE_ID = 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

--- 💰 DYNAMIC LOGIC (LALIT'S SPECIAL) ---

def get_dynamic_config():
conn = sqlite3.connect(DB_FILE)
total_pnl = conn.execute("SELECT SUM(pnl) FROM trades WHERE status='CLOSED'").fetchone()[0] or 0
conn.close()
current_total_cap = BASE_CAPITAL + total_pnl
# हर 1 लाख बढ़ने पर 1 नया स्लॉट
max_slots = 5 + max(0, int(total_pnl // 100000))
return current_total_cap, max_slots

def get_available_capital():
total_cap, _ = get_dynamic_config()
conn = sqlite3.connect(DB_FILE)
rows = conn.execute("SELECT entry, qty FROM trades WHERE status='OPEN'").fetchall()
conn.close()
invested = sum(entry * qty for entry, qty in rows)
return max(0, total_cap - invested)

--- 📲 TELEGRAM CORE ---

def send_telegram(message):
if not BOT_TOKEN or not CHAT_ID: return
try:
url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
requests.post(url, data=payload, timeout=15)
except Exception as e: logging.error(f"Telegram Error: {e}")

--- 🗄️ DATABASE (WAL Mode Optimized) ---

def init_db():
conn = sqlite3.connect(DB_FILE)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("""CREATE TABLE IF NOT EXISTS trades (
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
pnl REAL DEFAULT 0)""")
conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_open_symbol ON trades(symbol) WHERE status='OPEN'")
conn.commit(); conn.close()

--- 🔍 LALIT'S V8 ANALYSIS ---

def analyze_stock(symbol):
try:
time.sleep(random.uniform(1.0, 2.0))
df = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=True, threads=False)

# सुरक्षा फिल्टर: खाली डेटा चेक  
    if df.empty or len(df) < 220: return None  
      
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]  
    ema50 = close.ewm(span=50).mean()  
    ema200 = close.ewm(span=200).mean()  
    rsi = ta.momentum.RSIIndicator(close, 14).rsi()  
    adx = ta.trend.ADXIndicator(high, low, close, 14).adx()  
    atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()  
    price = float(close.iloc[-1])  
      
    # V8 Strategy Logic  
    ema_slope = (ema50.iloc[-1] - ema50.iloc[-5]) / ema50.iloc[-5] * 100  
    vol_breakout = vol.iloc[-1] > vol.rolling(20).mean().iloc[-1] * 2.5  
    bullish = price > ema50.iloc[-1] > ema200.iloc[-1]  
    momentum = (50 < rsi.iloc[-1] < 66) and (adx.iloc[-1] > 25) and (ema_slope > 0.2)  
      
    if bullish and momentum and vol_breakout:  
        current_cap, max_slots = get_dynamic_config()  
        available_cap = get_available_capital()  
          
        # कैपिटल चेक  
        if available_cap < price: return None  
          
        sl = round(price - (2 * atr.iloc[-1]), 2)  
        target = round(price + (4 * atr.iloc[-1]), 2)  
          
        # स्मार्ट क्वांटिटी कैलकुलेशन  
        risk_qty = int((current_cap * RISK_PER_TRADE) / (price - sl))  
        capital_qty = int((available_cap / max_slots) / price)  
          
        qty = min(risk_qty, capital_qty)  
        if qty > 0: return {"symbol": symbol, "price": round(price, 2), "sl": sl, "target": target, "qty": qty}  
except: return None

--- 🔄 MONITORING (Persistent TSL Update) ---

def manage_exits():
conn = sqlite3.connect(DB_FILE)
conn.execute("PRAGMA journal_mode=WAL")
trades = conn.execute("SELECT id, symbol, entry, sl, target, qty, highest_price FROM trades WHERE status='OPEN'").fetchall()
for tid, sym, entry, current_sl, target, qty, high_price in trades:
try:
df = yf.download(sym, period="2d", interval="5m", progress=False, auto_adjust=True, threads=False)
if df.empty: continue
current = float(df["Close"].iloc[-1])

if current > high_price:  
            high_price = current  
            new_sl = max(current_sl, high_price * 0.97)  
            # डेटाबेस में पक्का अपडेट  
            conn.execute("UPDATE trades SET sl=?, highest_price=? WHERE id=?", (new_sl, high_price, tid))  
            current_sl = new_sl  
          
        if current <= current_sl or current >= target:  
            pnl = round((current - entry) * qty, 2)  
            conn.execute("UPDATE trades SET status='CLOSED', exit_time=?, pnl=? WHERE id=?", (datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), pnl, tid))  
            send_telegram(f"🔴 *EXIT:* `{sym}` | P&L: ₹{pnl:,.2f}")  
    except: continue  
conn.commit(); conn.close()

--- 🤖 TELEGRAM COMMANDS (Secure Filter) ---

def check_telegram_commands():
global LAST_UPDATE_ID
try:
url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
res = requests.get(url, params={"offset": LAST_UPDATE_ID, "timeout": 1}, timeout=5).json()
for up in res.get("result", []):
LAST_UPDATE_ID = up["update_id"] + 1
# सुरक्षा फिल्टर
if str(up.get("message", {}).get("chat", {}).get("id")) != str(CHAT_ID): continue

text = up.get("message", {}).get("text", "").strip()  
        if text == "#status":  
            cap, slots = get_dynamic_config()  
            avail = get_available_capital()  
            conn = sqlite3.connect(DB_FILE)  
            open_tr = conn.execute("SELECT symbol, sl FROM trades WHERE status='OPEN'").fetchall()  
            conn.close()  
            msg = f"📊 *ब्रह्मांड कवच v31.6 Status*\n💰 कैपिटल: ₹{cap:,.0f}\n💵 उपलब्ध: ₹{avail:,.0f}\n📦 स्लॉट्स: {slots}\n✅ ओपन: {len(open_tr)}"  
            send_telegram(msg)  
except: pass

--- 🌐 SERVER (Keep Alive) ---

class HealthHandler(BaseHTTPRequestHandler):
def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Live")
def log_message(self, format, *args): return

def market_open():
now = datetime.now(IST)
curr = now.hour * 60 + now.minute
return now.weekday() < 5 and 555 <= curr <= 930

--- 🚀 MAIN ENGINE ---

def run():
init_db()
port = int(os.environ.get("PORT", 10000))
server = HTTPServer(("0.0.0.0", port), HealthHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
send_telegram("🚀 ब्रह्मांड कवच v31.6 Final मास्टर लाइव\nललित जी, डायनामिक स्लॉट और सुरक्षा घेरे के साथ सिस्टम तैयार है!")

try: symbols = (pd.read_csv(NSE500_URL)["Symbol"] + ".NS").tolist()  
except: symbols = []  

while True:  
    try:  
        check_telegram_commands(); manage_exits()  
        if market_open():  
            current_cap, max_slots = get_dynamic_config()  
            conn = sqlite3.connect(DB_FILE)  
            current_open = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]  
              
            # स्लॉट फुल होने पर स्कैनिंग बंद  
            if current_open >= max_slots:  
                conn.close()  
            else:  
                conn.close()  
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:  
                    futures = {executor.submit(analyze_stock, s): s for s in symbols}  
                    for f in as_completed(futures):  
                        # लूप के अंदर दोबारा चेक (सेफ्टी के लिए)  
                        conn = sqlite3.connect(DB_FILE)  
                        now_open = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]  
                        if now_open >= max_slots:  
                            conn.close(); executor.shutdown(wait=False, cancel_futures=True); break  
                        conn.close()  
                          
                        res = f.result()  
                        if res:  
                            conn = sqlite3.connect(DB_FILE)  
                            try:  
                                conn.execute("INSERT INTO trades (symbol, entry, sl, target, qty, status, highest_price, entry_time) VALUES (?,?,?,?,?,?,?,?)", (res['symbol'], res['price'], res['sl'], res['target'], res['qty'], "OPEN", res['price'], datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")))  
                                conn.commit()  
                                send_telegram(f"🟢 *BUY:* `{res['symbol']}`\nPrice: ₹{res['price']}\nQty: {res['qty']}")  
                            except: pass  
                            finally: conn.close()  
        time.sleep(SCAN_INTERVAL)  
    except Exception as e: logging.error(f"Error: {e}"); time.sleep(30)

if name == "main":
run()
