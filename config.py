import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

DYNAMIC_WEBAPP_URL = None

BOT_TOKEN = os.getenv("BOT_TOKEN", "8951033399:AAEmzv4WdpbhuO8IM4mkE3dCxhvWMq3YiJI")

# Parse admin user IDs
admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
if admin_ids_raw:
    for item in admin_ids_raw.split(","):
        item = item.strip()
        if item.isdigit():
            ADMIN_IDS.append(int(item))
        elif item.startswith("-") and item[1:].isdigit():
            ADMIN_IDS.append(int(item))

# Parse admin group ID
admin_group_id_raw = os.getenv("ADMIN_GROUP_ID", "")
ADMIN_GROUP_ID = None
if admin_group_id_raw:
    try:
        ADMIN_GROUP_ID = int(admin_group_id_raw.strip())
    except ValueError:
        ADMIN_GROUP_ID = None

def get_admin_ids():
    load_dotenv()
    ids_raw = os.getenv("ADMIN_IDS", "")
    ids = []
    if ids_raw:
        for item in ids_raw.split(","):
            item = item.strip()
            if item.isdigit() or (item.startswith("-") and item[1:].isdigit()):
                ids.append(int(item))
    return ids

def get_admin_group_id():
    load_dotenv()
    group_raw = os.getenv("ADMIN_GROUP_ID", "")
    if group_raw:
        try:
            return int(group_raw.strip())
        except ValueError:
            return None
    return None

def get_webapp_url():
    if DYNAMIC_WEBAPP_URL:
        return DYNAMIC_WEBAPP_URL
        
    load_dotenv()
    url = os.getenv("WEBAPP_URL", "")
    if not url:
        return "https://t.me"
        
    # Telegram API rejects loopback hosts like localhost or 127.0.0.1
    if "localhost" in url or "127.0.0.1" in url:
        print("\n" + "!"*70)
        print("WARNING: Telegram rejects 'localhost' or '127.0.0.1' addresses!")
        print("Bot falls back to 'https://t.me' to prevent startup failure.")
        print("To test the Web App locally, please use an HTTPS tunnel (e.g., ngrok or serveo).")
        print("!"*70 + "\n")
        return "https://t.me"
        
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    elif not url.startswith("https://"):
        url = f"https://{url}"
    return url
