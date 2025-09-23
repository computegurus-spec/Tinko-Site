import os, requests
from dotenv import load_dotenv

load_dotenv()

GUPSHUP_API_KEY = os.getenv("GUPSHUP_API_KEY")
GUPSHUP_APP_NAME = os.getenv("GUPSHUP_APP_NAME")
GUPSHUP_API_ENDPOINT = "https://api.gupshup.io/sm/api/v1/msg"

def send_whatsapp_message(phone_number, template_id, template_params):
    if not GUPSHUP_API_KEY or not GUPSHUP_APP_NAME:
        print("Gupshup API Key or App Name not configured. Skipping message.")
        return False

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": GUPSHUP_API_KEY,
    }
    payload = {
        "channel": "whatsapp",
        "source": GUPSHUP_APP_NAME,
        "destination": phone_number,
        "message": f'{{"type":"template","id":"{template_id}","params":{template_params}}}',
        "src.name": GUPSHUP_APP_NAME,
    }
    try:
        resp = requests.post(GUPSHUP_API_ENDPOINT, headers=headers, data=payload)
        resp.raise_for_status()
        print(f"WhatsApp message OK → {phone_number}: {resp.text}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"WhatsApp send failed ({phone_number}): {e}")
        return False
