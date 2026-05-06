import requests
import time
import threading
import json
import os
import re

# --- কনফিগারেশন ---
TELEGRAM_TOKEN = '6288193781:AAGrBx3qgv1H_Bz3FL-BgW19gpXbgVL-M-Y'  # @BotFather থেকে পাওয়া টোকেন
DB_FILE = "users.json"
UPBIT_NOTICE_API = "https://api-manager.upbit.com/api/v1/notices?page=1&per_page=5"
UPBIT_MARKET_API = "https://api.upbit.com/v1/market/all"

# ইউজার ডাটাবেজ
if os.path.exists(DB_FILE):
    with open(DB_FILE, "r") as f:
        user_ids = set(json.load(f))
else:
    user_ids = set()

# গ্লোবাল ভেরিয়েবল
tracked_notices = {} 
old_markets = set()
last_update_id = 0

def save_users():
    with open(DB_FILE, "w") as f:
        json.dump(list(user_ids), f)

def send_broadcast(message):
    for chat_id in list(user_ids):
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
        except: pass

def convert_to_bd_time(kst_time_str):
    if not kst_time_str: return None
    try:
        kst_hour = int(kst_time_str.split(':')[0])
        minute = kst_time_str.split(':')[1]
        # KST (Korea) থেকে ৩ ঘণ্টা বিয়োগ করলে BD টাইম পাওয়া যায়
        bd_hour = (kst_hour - 3) % 24
        ampm = "PM" if bd_hour >= 12 else "AM"
        display_hour = bd_hour if bd_hour <= 12 else bd_hour - 12
        if display_hour == 0: display_hour = 12
        return f"{display_hour}:{minute} {ampm} (BD)"
    except: return None

# --- ১. নোটিশ মনিটর ও টাইম আপডেট ডিটেক্টর (সবচেয়ে শক্তিশালী অংশ) ---
def notice_monitor():
    global tracked_notices
    print("🚀 নোটিশ ও টাইম আপডেট মনিটর চালু হয়েছে...")
    
    # শুরুতে বর্তমান নোটিশগুলো একবার চেক করে নেওয়া যাতে পুরনো খবর না আসে
    try:
        init_res = requests.get(UPBIT_NOTICE_API, timeout=10).json()
        if init_res.get('success'):
            for n in init_res['data']['list']:
                tracked_notices[n['id']] = None 
    except: pass

    while True:
        try:
            response = requests.get(UPBIT_NOTICE_API, timeout=10).json()
            if response.get('success'):
                notices = response['data']['list']
                
                for notice in notices:
                    n_id = notice['id']
                    n_title = notice['title']
                    
                    # শুধু লিস্টিং ফিল্টার (কোরিয়ান ও ইংরেজি কি-ওয়ার্ড)
                    if any(word in n_title.lower() for word in ["listing", "added", "market", "거래", "상장"]):
                        
                        # প্রতিবার নোটিশের ভেতর ঢুকে চেক করবে সময় আপডেট হয়েছে কি না
                        detail_res = requests.get(f"https://api-manager.upbit.com/api/v1/notices/{n_id}", timeout=10).json()
                        body = detail_res['data']['body']
                        
                        # সময় (HH:MM) খুঁজে বের করা
                        time_match = re.search(r'(\d{2}:\d{2})', body)
                        found_time = time_match.group(1) if time_match else None

                        # কেস ১: একদম নতুন নোটিশ আসলে
                        if n_id not in tracked_notices:
                            tracked_notices[n_id] = found_time
                            bd_time = convert_to_bd_time(found_time)
                            time_info = f"<b>{bd_time}</b>" if bd_time else "<i>এখনো ঘোষণা হয়নি (বট নজর রাখছে)</i>"
                            
                            msg = (
                                f"📢 <b>নতুন লিস্টিং ঘোষণা!</b>\n\n"
                                f"📌 {n_title}\n"
                                f"⏰ ট্রেড শুরু: {time_info}\n"
                                f"🔗 <a href='https://upbit.com/service_center/notice?id={n_id}'>বিস্তারিত দেখুন</a>"
                            )
                            send_broadcast(msg)

                        # কেস ২: পুরনো নোটিশে সময় আপডেট হলে (আগে সময় ছিল না, এখন আছে)
                        elif found_time and (tracked_notices.get(n_id) is None):
                            tracked_notices[n_id] = found_time
                            bd_time = convert_to_bd_time(found_time)
                            
                            msg = (
                                f"🔄 <b>টাইম আপডেট এলার্ট!</b>\n\n"
                                f"📌 {n_title}\n"
                                f"⏰ <b>ট্রেড শুরুর সময় পাওয়া গেছে: {bd_time}</b>\n"
                                f"🔗 <a href='https://upbit.com/service_center/notice?id={n_id}'>অফিসিয়াল লিঙ্ক</a>"
                            )
                            send_broadcast(msg)
                            
        except Exception as e:
            print(f"Notice Monitor Error: {e}")
        time.sleep(10) # ১০ সেকেন্ড পর পর চেক

# --- ২. লাইভ লিস্টিং ডিটেক্টর (স্পট মার্কেটে আসা মাত্রই) ---
def live_listing_detector():
    global old_markets
    print("⚡ লাইভ মার্কেট ডিটেক্টর চালু হয়েছে...")
    try:
        res = requests.get(UPBIT_MARKET_API, timeout=10).json()
        old_markets = {item['market'] for item in res}
    except: pass

    while True:
        try:
            res = requests.get(UPBIT_MARKET_API, timeout=10).json()
            current_markets = {item['market'] for item in res}
            new_listings = current_markets - old_markets

            if new_listings:
                for market in new_listings:
                    msg = (
                        f"🔥 <b>TOKEN LISTED ON SPOT!</b>\n\n"
                        f"💰 <b>Pair:</b> {market}\n"
                        f"✅ এই টোকেনটি এখন ট্রেড করার জন্য এভেইলেবল!"
                    )
                    send_broadcast(msg)
                old_markets = current_markets
        except: pass
        time.sleep(3) # প্রতি ৩ সেকেন্ডে মার্কেট স্ক্যান

# --- ৩. টেলিগ্রাম ইউজার হ্যান্ডলার ---
def telegram_listener():
    global last_update_id
    print("💬 টেলিগ্রাম কমান্ড লিসেনার চালু হয়েছে...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=20"
            res = requests.get(url, timeout=25).json()
            if res.get('result'):
                for update in res['result']:
                    last_update_id = update['update_id']
                    if 'message' in update and 'text' in update['message']:
                        chat_id = update['message']['chat']['id']
                        if update['message']['text'] == "/start":
                            if chat_id not in user_ids:
                                user_ids.add(chat_id)
                                save_users()
                            msg = "✅ <b>সাবস্ক্রাইব সফল!</b>\nএখন থেকে Upbit-এর লিস্টিং ঘোষণা এবং সময়ের সব আপডেট এখানে পাবেন।"
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                          json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})
        except: pass
        time.sleep(2)

# --- থ্রেডগুলো রান করা ---
t1 = threading.Thread(target=notice_monitor, daemon=True)
t2 = threading.Thread(target=live_listing_detector, daemon=True)
t3 = threading.Thread(target=telegram_listener, daemon=True)

t1.start()
t2.start()
t3.start()

print("🤖 বট পুরোপুরি অ্যাক্টিভ। বন্ধ করতে Ctrl+C চাপুন।")
while True:
    time.sleep(1)
