import os
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════
#  CLIENT CONFIG — Royal Darbar
# ══════════════════════════════════════════════════════════════════
CLIENT = {
    "type":             "restaurant",
    "name":             "Royal Darbar",
    "fonnte_token":     os.environ.get("FONNTE_TOKEN", ""),
    "admin_phone":      os.environ.get("ADMIN_PHONE",  "916205131181"),
    "website":          os.environ.get("WEBSITE",      "https://royal-darbar.netlify.app"),
    "timing_start":     os.environ.get("TIMING_START", "10:00"),
    "timing_end":       os.environ.get("TIMING_END",   "23:00"),
    "firebase_project": os.environ.get("FB_PROJECT",   "royal-darbar-1"),
    "location":         "Matiara Tok, Sarai, Bihar",
}

# ══════════════════════════════════════════════════════════════════
#  SESSION (10 min timeout) — same as master_bot
# ══════════════════════════════════════════════════════════════════
sessions = {}

def get_session(phone):
    now = time.time()
    if phone in sessions:
        if now - sessions[phone].get("t", 0) > 600:
            del sessions[phone]
            return {}
        return sessions[phone]
    return {}

def set_session(phone, data):
    sessions[phone] = {**data, "t": time.time()}

# ══════════════════════════════════════════════════════════════════
#  CACHE — same as master_bot
# ══════════════════════════════════════════════════════════════════
_cache = {}

def cached(key, fetcher, ttl=300):
    now = time.time()
    if key in _cache and (now - _cache[key][1]) < ttl:
        return _cache[key][0]
    data = fetcher()
    _cache[key] = (data, now)
    return data

# ══════════════════════════════════════════════════════════════════
#  FIREBASE HELPERS — same as master_bot
# ══════════════════════════════════════════════════════════════════
def fb_base():
    proj = CLIENT["firebase_project"]
    return f"https://firestore.googleapis.com/v1/projects/{proj}/databases/(default)/documents"

def fb_val(field):
    if not field: return None
    for t in ["stringValue","booleanValue","integerValue","doubleValue"]:
        if t in field: return field[t]
    return None

def fb_get_settings():
    try:
        res = requests.get(f"{fb_base()}/settings/bot", timeout=5)
        fields = res.json().get("fields", {})
        return {
            "botEnabled": fb_val(fields.get("botEnabled")) if fields.get("botEnabled") else True,
            "autoReply":  fb_val(fields.get("autoReply"))  if fields.get("autoReply")  else True,
        }
    except:
        return {"botEnabled": True, "autoReply": True}

def fb_get_menu():
    try:
        res  = requests.get(f"{fb_base()}/menu", timeout=8)
        docs = res.json().get("documents", [])
        items = []
        for doc in docs:
            f = doc.get("fields", {})
            if fb_val(f.get("available")) is False: continue
            items.append({
                "name":     fb_val(f.get("name"))     or "",
                "price":    fb_val(f.get("price"))    or 0,
                "category": fb_val(f.get("category")) or "Other",
                "emoji":    fb_val(f.get("emoji"))    or "•",
                "veg":      fb_val(f.get("veg")),
            })
        return items
    except Exception as e:
        print(f"[MENU ERROR] {e}")
        return []

def fb_add(collection, data):
    try:
        fields = {}
        for k, v in data.items():
            if   isinstance(v, bool):        fields[k] = {"booleanValue": v}
            elif isinstance(v, (int,float)): fields[k] = {"doubleValue": float(v)}
            else:                            fields[k] = {"stringValue": str(v)}
        fields["createdAt"] = {"timestampValue": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        requests.post(f"{fb_base()}/{collection}", json={"fields": fields}, timeout=5)
    except Exception as e:
        print(f"[FB ADD ERROR] {e}")

def fb_get_announcement():
    try:
        res    = requests.get(f"{fb_base()}/config/announcement", timeout=5)
        fields = res.json().get("fields", {})
        if fb_val(fields.get("active")):
            return fb_val(fields.get("text")) or ""
        return ""
    except:
        return ""

def fb_find_order(order_id):
    try:
        query = {
            "structuredQuery": {
                "from":  [{"collectionId": "orders"}],
                "where": {"fieldFilter": {
                    "field": {"fieldPath": "numId"},
                    "op":    "EQUAL",
                    "value": {"integerValue": int(order_id)}
                }},
                "limit": 1
            }
        }
        proj = CLIENT["firebase_project"]
        res  = requests.post(
            f"https://firestore.googleapis.com/v1/projects/{proj}/databases/(default)/documents:runQuery",
            json=query, timeout=8
        )
        results = res.json()
        if results and isinstance(results, list) and results[0].get("document"):
            f = results[0]["document"].get("fields", {})
            return {
                "name":   fb_val(f.get("name"))   or "",
                "status": fb_val(f.get("status")) or "new",
                "items":  fb_val(f.get("items"))  or "",
                "total":  fb_val(f.get("total"))  or "",
            }
        return None
    except Exception as e:
        print(f"[TRACK ERROR] {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  WORKING HOURS — same as master_bot
# ══════════════════════════════════════════════════════════════════
def is_open():
    try:
        sh, sm = map(int, CLIENT["timing_start"].split(":"))
        eh, em = map(int, CLIENT["timing_end"].split(":"))
        now    = datetime.now()
        return now.replace(hour=sh,minute=sm,second=0) <= now <= now.replace(hour=eh,minute=em,second=0)
    except:
        return True

# ══════════════════════════════════════════════════════════════════
#  SEND MESSAGE — same as master_bot
# ══════════════════════════════════════════════════════════════════
def send_msg(to, message):
    try:
        resp = requests.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": CLIENT["fonnte_token"], "Content-Type": "application/json"},
            json={"target": to, "message": message, "countryCode": "91"},
            timeout=10
        )
        print(f"[SENT → {to}] {resp.status_code}")
    except Exception as e:
        print(f"[SEND ERROR] {e}")

def notify_admin(msg):
    send_msg(CLIENT["admin_phone"], msg)

# ══════════════════════════════════════════════════════════════════
#  MESSAGE BUILDERS
# ══════════════════════════════════════════════════════════════════
GREETINGS = ["hi","hello","hlo","hii","hey","namaskar","namaste","hy",
             "start","help","0","back","wapas","reset"]

def welcome():
    ann = cached("ann", fb_get_announcement, ttl=120)
    ann_line = f"\n\n📢 *{ann}*" if ann else ""
    return (
        f"🏰 *Royal Darbar*\n"
        f"Namaskar! Swagat hai aapka 🙏{ann_line}\n\n"
        f"Aap kya karna chahte hain?\n\n"
        f"*1️⃣* 🛒 Order karna hai\n"
        f"*2️⃣* 📋 Menu dekhna hai\n"
        f"*3️⃣* 🪑 Table Book karna hai\n"
        f"*4️⃣* 🎉 Event / Party Booking\n"
        f"*5️⃣* 📦 Order Track karna hai\n"
        f"*6️⃣* 📍 Location & Timing\n"
        f"*7️⃣* 📞 Humse baat karein\n\n"
        f"Number ya seedha batayein 😊"
    )

def order_reply():
    url = CLIENT["website"]
    return (
        f"🛒 *ONLINE ORDER*\n\n"
        f"Kaise order karna chahte hain?\n\n"
        f"*1* 🚴 Home Delivery\n"
        f"*2* 🏃 Self Pickup\n"
        f"*3* 🍽️ Dine-in\n\n"
        f"Ya seedha website se order karein:\n"
        f"👉 *{url}*\n\nWapas ke liye *0* bhejein"
    )

def order_type_reply(otype):
    url = CLIENT["website"]
    ts, te = CLIENT["timing_start"], CLIENT["timing_end"]
    msgs = {
        "1": (f"🚴 *HOME DELIVERY*\n\n👉 *{url}*\n\n"
              f"✅ Menu choose karo → Cart → Checkout\n"
              f"✅ WhatsApp pe confirm aayega!\n"
              f"⏰ ~40-50 min delivery\n\nWapas ke liye *0* bhejein"),
        "2": (f"🏃 *SELF PICKUP*\n\n👉 *{url}*\n\n"
              f"✅ Pickup select karo → Order karo\n"
              f"✅ Ready hone pe WhatsApp aayega!\n"
              f"📍 Matiara Tok, Sarai, Bihar\n"
              f"⏰ {ts} – {te}\n\nWapas ke liye *0* bhejein"),
        "3": (f"🍽️ *DINE-IN*\n\n"
              f"📍 Matiara Tok, Sarai, Bihar\n"
              f"⏰ {ts} – {te} (Daily)\n\n"
              f"Table booking ke liye *3* bhejein 🪑\n"
              f"Ya website pe pre-order: 👉 *{url}*\n\nWapas ke liye *0* bhejein"),
    }
    return msgs.get(otype, order_reply())

def menu_reply():
    url   = CLIENT["website"]
    items = cached("menu", fb_get_menu, ttl=300)
    if not items:
        return f"📋 *ROYAL DARBAR MENU*\n\nPoora menu website pe dekho:\n👉 *{url}*\n\n🥡 Chinese | 🍛 North Indian\n\nWapas ke liye *0* bhejein"

    cat_order  = ["Starters","Main Course","Rice & Biryani","Chinese","Breads","Desserts","Beverages","Special"]
    cat_emojis = {"Starters":"🥗","Main Course":"🍛","Rice & Biryani":"🍚",
                  "Chinese":"🥡","Breads":"🫓","Desserts":"🍮","Beverages":"🥤","Special":"⭐"}
    cats = {}
    for item in items:
        cats.setdefault(item.get("category","Other"), []).append(item)

    msg = "📋 *ROYAL DARBAR MENU*\n"
    shown = set()
    for cat in cat_order:
        if cat not in cats: continue
        shown.add(cat)
        msg += f"\n*{cat_emojis.get(cat,'🍽️')} {cat}*\n"
        for it in cats[cat]:
            dot = "🟢" if it.get("veg") is True else "🔴" if it.get("veg") is False else "•"
            msg += f"{dot} {it.get('emoji','')} {it['name']} — ₹{it['price']}\n"
    for cat, its in cats.items():
        if cat in shown: continue
        msg += f"\n*🍽️ {cat}*\n"
        for it in its:
            msg += f"• {it.get('emoji','')} {it['name']} — ₹{it['price']}\n"

    msg += f"\n👉 Order: *{url}*\n\nWapas ke liye *0* bhejein"
    return msg

def location_reply():
    ts, te = CLIENT["timing_start"], CLIENT["timing_end"]
    status = "🟢 Abhi OPEN hai!" if is_open() else f"🔴 Abhi band hai (opens {ts})"
    return (
        f"📍 *Royal Darbar Restaurant & Resort*\n\n"
        f"📍 Matiara Tok, Sarai, Bihar\n"
        f"⏰ *Timing:* {ts} – {te} (Daily)\n"
        f"{status}\n\n"
        f"🗺️ Google Maps: *'Royal Darbar Sarai'* search karein\n"
        f"🌐 Website: {CLIENT['website']}\n\nWapas ke liye *0* bhejein"
    )

def contact_reply():
    phone = CLIENT["admin_phone"][-10:]
    ts, te = CLIENT["timing_start"], CLIENT["timing_end"]
    return (
        f"📞 *CONTACT — Royal Darbar*\n\n"
        f"📱 WhatsApp / Call: *+91 {phone}*\n"
        f"🌐 Website: {CLIENT['website']}\n"
        f"📍 Matiara Tok, Sarai, Bihar\n"
        f"⏰ Available: {ts} – {te}\n\n"
        f"Hum hamesha madad ke liye taiyaar hain! 🙏\n\nWapas ke liye *0* bhejein"
    )

def unknown_reply():
    return (
        f"Maafi chahte hain 😅\n\nKripya batayein:\n"
        f"*1* — 🛒 Order\n*2* — 📋 Menu\n*3* — 🪑 Table Book\n"
        f"*4* — 🎉 Event Booking\n*5* — 📦 Order Track\n"
        f"*6* — 📍 Location\n*7* — 📞 Contact\n*0* — 🔄 Main Menu"
    )

# ══════════════════════════════════════════════════════════════════
#  INTENT DETECTION
#  Numbers aur Keywords DONO alag-alag hain — dono saath bhi kaam
#  karte hain (e.g. "1", "order", "1 order karna hai" — sab chalega)
# ══════════════════════════════════════════════════════════════════

# Number shortcuts — sirf main menu mein kaam karte hain
NUM_MAP = {
    "1": "order",
    "2": "menu",
    "3": "booking",
    "4": "event",
    "5": "track",
    "6": "location",
    "7": "contact",
}

# Keywords — natural language, koi bhi flow mein kaam karte hain
ORDER_KW   = ["order","khaana","food","delivery","pickup","dine","khana","mangana","chahiye","lena"]
MENU_KW    = ["menu","list","kya hai","kya milta","item","dishes","available","kya h","kya kya"]
BOOK_KW    = ["table","book","reservation","seat","jagah","buk","reserve","dining"]
EVENT_KW   = ["event","party","shaadi","wedding","birthday","function","banquet","reception","shadi"]
TRACK_KW   = ["track","status","mera order","kahan hai","kitna time","deliver","kitni der","order no"]
LOC_KW     = ["location","address","kahan","kaha","timing","time","open","sarai","matiara","shop","dur","direction"]
CONTACT_KW = ["contact","call","baat","phone","number","support","staff","helpline","manager","owner"]

def detect_intent(msg):
    """
    Pehle number check karo, phir keywords.
    Dono match ho toh bhi kaam karta hai — e.g. "1 order karna hai"
    pehle "1" se hi pakad lega.
    """
    m = msg.strip().lower()

    # Number match — exact ya message mein hai (e.g. "1", "option 1", "no 1")
    for num, intent in NUM_MAP.items():
        # Pure number ya number ke saath kuch extra
        if m == num or m.startswith(num + " ") or m.endswith(" " + num):
            return intent

    # Keyword match
    for kw in ORDER_KW:
        if kw in m: return "order"
    for kw in MENU_KW:
        if kw in m: return "menu"
    for kw in BOOK_KW:
        if kw in m: return "booking"
    for kw in EVENT_KW:
        if kw in m: return "event"
    for kw in TRACK_KW:
        if kw in m: return "track"
    for kw in LOC_KW:
        if kw in m: return "location"
    for kw in CONTACT_KW:
        if kw in m: return "contact"

    return None

# ══════════════════════════════════════════════════════════════════
#  BOOKING FLOW HELPERS
# ══════════════════════════════════════════════════════════════════
EVENT_TYPES = {"1":"💍 Shaadi/Wedding","2":"🎂 Birthday Party","3":"🏢 Corporate Event","4":"🎊 Other"}

def handle_booking_flow(phone, msg, session):
    step = session.get("step")
    ts, te = CLIENT["timing_start"], CLIENT["timing_end"]

    if step == "bk_name":
        set_session(phone, {**session, "step":"bk_phone", "bk_name": msg})
        return "📱 Aapka *phone number* bhejein:\n_(Example: 9876543210)_\n\nWapas ke liye *0* bhejein"

    if step == "bk_phone":
        set_session(phone, {**session, "step":"bk_date", "bk_phone": msg})
        return "📅 Kaunsi *date* ko aana hai?\n_(Example: 30 April)_\n\nWapas ke liye *0* bhejein"

    if step == "bk_date":
        set_session(phone, {**session, "step":"bk_time", "bk_date": msg})
        return f"⏰ Kaunsa *time* chahiye?\n_(Example: 7:30 PM)_\nHumari timing: {ts} – {te}\n\nWapas ke liye *0* bhejein"

    if step == "bk_time":
        set_session(phone, {**session, "step":"bk_guests", "bk_time": msg})
        return "👥 Kitne *log* aayenge?\n_(Example: 4)_\n\nWapas ke liye *0* bhejein"

    if step == "bk_guests":
        s = {**session, "bk_guests": msg}
        set_session(phone, {**s, "step":"bk_confirm"})
        return (
            f"✅ *CONFIRM KAREIN*\n\n"
            f"👤 {s.get('bk_name')}\n📱 {s.get('bk_phone')}\n"
            f"📅 {s.get('bk_date')} | ⏰ {s.get('bk_time')}\n👥 {msg} guests\n\n"
            f"*1* ✅ Confirm\n*2* ✏️ Dobara bharo\n*0* ❌ Cancel"
        )

    if step == "bk_confirm":
        if msg == "1":
            fb_add("bookings", {
                "btype":"dinein", "source":"whatsapp", "status":"pending",
                "name":session.get("bk_name",""), "phone":session.get("bk_phone", phone),
                "date":session.get("bk_date",""), "time":session.get("bk_time",""),
                "guests":session.get("bk_guests",""),
            })
            notify_admin(
                f"🪑 *NEW TABLE BOOKING (WhatsApp)*\n"
                f"👤 {session.get('bk_name')} | 📱 {session.get('bk_phone', phone)}\n"
                f"📅 {session.get('bk_date')} ⏰ {session.get('bk_time')}\n"
                f"👥 {session.get('bk_guests')} guests"
            )
            set_session(phone, {"step":"main"})
            return (
                f"✅ *Booking Confirmed!*\n\n"
                f"Royal Darbar mein aapka swagat hoga 🏰\n"
                f"📅 {session.get('bk_date')} | ⏰ {session.get('bk_time')}\n\n"
                f"Hamara team jald confirm karega 📞\n\nWapas ke liye *0* bhejein"
            )
        if msg == "2":
            set_session(phone, {"step":"bk_name"})
            return "Theek hai, dobara bharte hain 😊\n\nApna *naam* bhejein:"
        set_session(phone, {"step":"main"})
        return welcome()
    return None

def handle_event_flow(phone, msg, session):
    step = session.get("step")

    if step == "ev_type":
        etype = EVENT_TYPES.get(msg)
        if not etype:
            return (f"Kaunsa event hai?\n\n*1* 💍 Shaadi\n*2* 🎂 Birthday\n"
                    f"*3* 🏢 Corporate\n*4* 🎊 Other\n\nWapas ke liye *0* bhejein")
        set_session(phone, {**session, "step":"ev_name", "ev_type": etype})
        return f"*{etype}*\n\nAapka *naam* bhejein:\n\nWapas ke liye *0* bhejein"

    if step == "ev_name":
        set_session(phone, {**session, "step":"ev_date", "ev_name": msg})
        return "📅 Event ki *date* kya hai?\n_(Example: 15 May 2026)_\n\nWapas ke liye *0* bhejein"

    if step == "ev_date":
        set_session(phone, {**session, "step":"ev_guests", "ev_date": msg})
        return "👥 Kitne *guests* aayenge?\n_(Example: 150)_\n\nWapas ke liye *0* bhejein"

    if step == "ev_guests":
        set_session(phone, {**session, "step":"ev_budget", "ev_guests": msg})
        return "💰 Approximate *budget* batayein:\n_(Example: 50000 ya 1 lakh)_\n\nWapas ke liye *0* bhejein"

    if step == "ev_budget":
        fb_add("bookings", {
            "btype":"event", "source":"whatsapp", "status":"pending",
            "eventType":session.get("ev_type",""), "name":session.get("ev_name",""),
            "phone":phone, "date":session.get("ev_date",""),
            "eventGuests":session.get("ev_guests",""), "budget":msg,
        })
        notify_admin(
            f"🎉 *NEW EVENT INQUIRY (WhatsApp)*\n"
            f"🎊 {session.get('ev_type')} | 👤 {session.get('ev_name')}\n"
            f"📱 {phone} | 📅 {session.get('ev_date')}\n"
            f"👥 {session.get('ev_guests')} guests | 💰 {msg}"
        )
        set_session(phone, {"step":"main"})
        return (
            f"✅ *Event Inquiry Received!*\n\n"
            f"🎉 {session.get('ev_type')}\n"
            f"📅 {session.get('ev_date')} | 👥 {session.get('ev_guests')} guests\n\n"
            f"Hamara team 24 ghante mein contact karega 📞\n\nWapas ke liye *0* bhejein"
        )
    return None

# ══════════════════════════════════════════════════════════════════
#  PROCESS MESSAGE
# ══════════════════════════════════════════════════════════════════
def process(phone, message):
    msg  = message.strip()
    ml   = msg.lower()

    # Bot on/off from admin panel
    settings = cached("settings", fb_get_settings, ttl=60)
    if not settings.get("botEnabled", True): return None
    if not settings.get("autoReply",  True): return None

    session = get_session(phone)
    step    = session.get("step", "main")

    # Greeting / reset
    if not session or ml in GREETINGS:
        set_session(phone, {"step":"main"})
        return welcome()

    # Active flows — booking
    if step.startswith("bk_"):
        if ml in ["0","back","wapas"]:
            set_session(phone, {"step":"main"})
            return welcome()
        return handle_booking_flow(phone, msg, session)

    # Active flows — event
    if step.startswith("ev_"):
        if ml in ["0","back","wapas"]:
            set_session(phone, {"step":"main"})
            return welcome()
        return handle_event_flow(phone, msg, session)

    # Active flow — order type select
    if step == "order_type":
        if ml in ["0","back","wapas"]:
            set_session(phone, {"step":"main"})
            return welcome()
        if msg in ["1","2","3"]:
            set_session(phone, {"step":"main"})
            return order_type_reply(msg)
        return order_reply()

    # Active flow — track order
    if step == "track_wait":
        if ml in ["0","back","wapas"]:
            set_session(phone, {"step":"main"})
            return welcome()
        oid = ''.join(filter(str.isdigit, msg))
        if not oid:
            return "❌ Sahi Order ID bhejein (jaise: 47)\n\nWapas ke liye *0* bhejein"
        order = fb_find_order(oid)
        set_session(phone, {"step":"main"})
        if order:
            STATUS = {
                "new":"🟠 Received","accepted":"✅ Accepted",
                "preparing":"🔵 Preparing","ready":"🟡 Ready — Pickup/Delivery taiyaar!",
                "delivered":"✅ Delivered — Enjoy! 🍛","rejected":"❌ Rejected"
            }
            return (f"📦 *ORDER #{oid}*\n\n"
                    f"👤 {order['name']}\n🍽️ {order['items']}\n💰 ₹{order['total']}\n\n"
                    f"📊 {STATUS.get(order['status'], order['status'])}\n\nWapas ke liye *0* bhejein")
        return f"❌ Order #{oid} nahi mila.\n\nSahi ID check karein ya *7* pe contact karein.\n\nWapas ke liye *0* bhejein"

    # Intent detection
    intent = detect_intent(msg)

    if intent == "order":
        set_session(phone, {"step":"order_type"})
        return order_reply()

    if intent == "menu":
        set_session(phone, {"step":"main"})
        return menu_reply()

    if intent == "booking":
        set_session(phone, {"step":"bk_name"})
        return "🪑 *TABLE BOOKING*\n\nApna *naam* bhejein:\n_(Example: Rahul Kumar)_\n\nWapas ke liye *0* bhejein"

    if intent == "event":
        set_session(phone, {"step":"ev_type"})
        return (f"🎉 *EVENT BOOKING*\n\nKaunsa event hai?\n\n"
                f"*1* 💍 Shaadi\n*2* 🎂 Birthday\n*3* 🏢 Corporate\n*4* 🎊 Other\n\nWapas ke liye *0* bhejein")

    if intent == "track":
        set_session(phone, {"step":"track_wait"})
        return "📦 *ORDER TRACK*\n\nApna *Order ID* bhejein:\n_(Website pe order ke baad ID milti hai)_\n\nWapas ke liye *0* bhejein"

    if intent == "location":
        set_session(phone, {"step":"main"})
        return location_reply()

    if intent == "contact":
        set_session(phone, {"step":"main"})
        return contact_reply()

    set_session(phone, {"step":"main"})
    return unknown_reply()

# ══════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ══════════════════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data    = request.json or {}
        sender  = data.get("sender") or data.get("from", "")
        message = data.get("message") or data.get("text", "")
        if not sender or not message:
            return jsonify({"status":"ignored"}), 200
        # Skip admin's own messages
        admin = CLIENT["admin_phone"].replace("+","").replace(" ","")
        if sender.replace("+","").replace(" ","") == admin:
            return jsonify({"status":"self"}), 200
        reply = process(sender, message)
        if reply:
            time.sleep(0.5)
            send_msg(sender, reply)
        return jsonify({"status":"ok"}), 200
    except Exception as e:
        print(f"[ERROR /webhook] {e}")
        return jsonify({"status":"error","msg":str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return (f"<h2>🏰 Royal Darbar — WhatsApp Bot</h2>"
            f"<p>Status: Running ✅</p>"
            f"<p>Webhook URL: <code>POST /webhook</code></p>"
            f"<p>Active sessions: {len(sessions)}</p>")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"running","sessions":len(sessions),"project":CLIENT["firebase_project"]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
