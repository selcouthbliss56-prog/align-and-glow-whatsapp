# -*- coding: utf-8 -*-
"""
Align and Glow Dental Clinic - Meta WhatsApp Cloud API Client
Handles:
1. Connection & Credentials Verification
2. Sending Interactive Welcome Menus (with Quick-Reply Buttons)
3. Sending Direct Messages (Text, Clinic Location, Timings)
4. Sending Post-Treatment Google Review Link Requests
5. Sending Appointment Confirmations
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(ROOT_DIR, ".env")

CLINIC_NAME = "Align and Glow Dental Clinic"
CLINIC_PHONE = "+91 9740275502"
CLINIC_ADDRESS = "No. 33, Sri Rama Arcade, 100 Feet Ring Road, Banashankari 3rd Stage (Opp. Kamakya Theatre), Bengaluru - 560085"
GOOGLE_REVIEW_LINK = "https://g.page/r/CU2E1T5G0lO3EBM/review"
GOOGLE_MAPS_LINK = "https://maps.google.com/?q=Align+and+Glow+Dental+Clinic+Banashankari"


def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def format_phone_number(phone):
    """Formats phone number into international E.164 format without '+' or spaces."""
    cleaned = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(cleaned) == 10:
        cleaned = "91" + cleaned # Default to India country code
    return cleaned


class WhatsAppCloudAPI:
    def __init__(self):
        env = load_env()
        self.token = env.get("WHATSAPP_API_KEY", "").strip()
        self.phone_id = env.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.waba_id = env.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
        self.version = env.get("META_GRAPH_VERSION", "v20.0").strip()
        self.base_url = f"https://graph.facebook.com/{self.version}"

    def is_configured(self):
        return bool(self.token and self.phone_id)

    def test_connection(self):
        """Verifies WhatsApp credentials against Meta Graph API."""
        if not self.is_configured():
            print("\n[!] WHATSAPP API NOT YET CONFIGURED IN .env")
            print("Please ensure WHATSAPP_API_KEY and WHATSAPP_PHONE_NUMBER_ID are filled in d:/ALIGN AND GLOW/.env")
            return False

        url = f"{self.base_url}/{self.phone_id}?fields=verified_name,display_phone_number,status,quality_rating,code_verification_status"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print("\n" + "=" * 65)
                print(" SUCCESS: Meta WhatsApp Cloud API Connected!")
                print("=" * 65)
                print(f" Verified Display Name : {data.get('verified_name', 'N/A')}")
                print(f" Display Phone Number  : {data.get('display_phone_number', 'N/A')}")
                print(f" Quality Rating        : {data.get('quality_rating', 'N/A')}")
                print(f" Account Mode          : {data.get('code_verification_status', 'VERIFIED')}")
                print(f" Registration Status   : {data.get('status', 'PENDING')}")
                print("=" * 65 + "\n")
                return True
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            print(f"\n[X] Meta WhatsApp API Verification Failed ({e.code}):")
            print(f"    {err_msg}\n")
            return False
        except Exception as ex:
            print(f"\n[X] Connection Error: {ex}\n")
            return False

    def register_phone_number(self, pin="123456"):
        """Completes two-step verification registration for the phone number."""
        url = f"{self.base_url}/{self.phone_id}/register"
        payload = {
            "messaging_product": "whatsapp",
            "pin": str(pin)
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("success"):
                    print(f"[+] Phone number successfully registered with PIN! Status is now active.")
                    return True
                return False
        except urllib.error.HTTPError as e:
            print(f"[X] Registration failed ({e.code}): {e.read().decode('utf-8')}")
            return False
        except Exception as ex:
            print(f"[X] Registration error: {ex}")
            return False

    def send_raw_payload(self, payload):
        """Sends JSON payload to Meta messages endpoint."""
        if not self.is_configured():
            print("[X] WhatsApp API credentials missing.")
            return None

        url = f"{self.base_url}/{self.phone_id}/messages"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")
            print(f"[X] WhatsApp Send Error ({e.code}): {err}")
            return None
        except Exception as ex:
            print(f"[X] Request Error: {ex}")
            return None

    def send_text_message(self, to_phone, message_text):
        """Sends a standard text message."""
        recipient = format_phone_number(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message_text
            }
        }
        res = self.send_raw_payload(payload)
        if res and "messages" in res:
            print(f"[+] Sent text message to {recipient}. Msg ID: {res['messages'][0]['id']}")
            return True
        return False

    def send_interactive_menu(self, to_phone):
        """Sends an interactive message with Quick Reply buttons."""
        recipient = format_phone_number(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "text",
                    "text": "Align and Glow Dental Clinic"
                },
                "body": {
                    "text": (
                        "Welcome to Align and Glow Dental Clinic! 🦷✨\n\n"
                        "How can we assist you with your smile today?\n\n"
                        "🕒 Hours: 9:00 AM – 9:00 PM Daily\n"
                        "📍 Banashankari 3rd Stage, Bengaluru"
                    )
                },
                "footer": {
                    "text": "Tap an option below for quick assistance"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "btn_book",
                                "title": "📅 Book Visit"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "btn_location",
                                "title": "📍 Clinic Location"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "btn_services",
                                "title": "🦷 Our Services"
                            }
                        }
                    ]
                }
            }
        }
        res = self.send_raw_payload(payload)
        if res and "messages" in res:
            print(f"[+] Sent interactive menu to {recipient}.")
            return True
        return False

    def send_appointment_confirmation(self, to_phone, patient_name, appointment_datetime):
        """Sends a structured appointment confirmation."""
        recipient = format_phone_number(to_phone)
        msg = (
            f"Hello {patient_name}, your dental consultation at *Align and Glow Dental Clinic* is confirmed! 🦷✅\n\n"
            f"📅 *Date & Time:* {appointment_datetime}\n"
            f"📍 *Location:* {CLINIC_ADDRESS}\n"
            f"🗺 *Google Maps:* {GOOGLE_MAPS_LINK}\n\n"
            "• Please arrive 5–10 minutes early.\n"
            "• If you need to reschedule, reply directly to this message.\n\n"
            "We look forward to taking great care of your smile!"
        )
        return self.send_text_message(recipient, msg)

    def send_review_request(self, to_phone, patient_name="valued patient"):
        """Sends a polite Google Review request with direct link."""
        recipient = format_phone_number(to_phone)
        msg = (
            f"Hello {patient_name}, thank you for visiting *Align and Glow Dental Clinic* today! 🌟\n\n"
            "Your feedback helps our team maintain the highest clinical standards and helps others in Bengaluru find quality dental care.\n\n"
            "Could you take 30 seconds to share your experience on our official Google page?\n\n"
            f"⭐ *Leave a Review:* {GOOGLE_REVIEW_LINK}\n\n"
            "We appreciate your trust in us and look forward to your next visit!"
        )
        return self.send_text_message(recipient, msg)

    def send_button_message(self, to_phone, body_text, buttons, header_text="Align and Glow Dental", footer_text="Tap an option below"):
        """
        Sends an interactive message with up to 3 quick-reply buttons.
        buttons: list of dicts [{"id": "btn_1", "title": "Button Title"}]
        (titles must be 1-20 characters per Meta Graph API rules)
        """
        recipient = format_phone_number(to_phone)
        formatted_buttons = []
        for btn in buttons[:3]:
            title = btn.get("title", "")[:20]
            btn_id = btn.get("id", f"btn_{len(formatted_buttons)}")[:256]
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn_id,
                    "title": title
                }
            })

        interactive_dict = {
            "type": "button",
            "body": {
                "text": body_text
            },
            "action": {
                "buttons": formatted_buttons
            }
        }
        if header_text:
            interactive_dict["header"] = {
                "type": "text",
                "text": header_text[:60]
            }
        if footer_text:
            interactive_dict["footer"] = {
                "text": footer_text[:60]
            }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": interactive_dict
        }
        res = self.send_raw_payload(payload)
        if res and "messages" in res:
            print(f"[+] Sent button message to {recipient}. Msg ID: {res['messages'][0]['id']}")
            return True
    def send_list_message(self, to_phone, body_text, button_label="View Options", sections=None, header_text="Align and Glow Dental", footer_text="Select an option"):
        """
        Sends an interactive message with a menu dropdown (List Message).
        sections: list of dicts:
        [
            {
                "title": "Category Title",  # max 24 chars
                "rows": [
                    {
                        "id": "row_id",          # max 200 chars
                        "title": "Row Title",    # max 24 chars
                        "description": "Details" # max 72 chars
                    }
                ]
            }
        ]
        """
        recipient = format_phone_number(to_phone)
        formatted_sections = []
        for sec in (sections or []):
            sec_title = sec.get("title", "Services")[:24]
            formatted_rows = []
            for row in sec.get("rows", []):
                formatted_rows.append({
                    "id": row.get("id", f"row_{len(formatted_rows)}")[:200],
                    "title": row.get("title", "")[:24],
                    "description": row.get("description", "")[:72]
                })
            if formatted_rows:
                formatted_sections.append({
                    "title": sec_title,
                    "rows": formatted_rows
                })

        interactive_dict = {
            "type": "list",
            "body": {
                "text": body_text
            },
            "action": {
                "button": button_label[:20],
                "sections": formatted_sections
            }
        }
        if header_text:
            interactive_dict["header"] = {
                "type": "text",
                "text": header_text[:60]
            }
        if footer_text:
            interactive_dict["footer"] = {
                "text": footer_text[:60]
            }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": interactive_dict
        }
        res = self.send_raw_payload(payload)
        if res and "messages" in res:
            print(f"[+] Sent list message to {recipient}. Msg ID: {res['messages'][0]['id']}")
            return True
        return False

    def send_reply(self, to_phone, reply):
        """Dispatches reply generated by ClinicReplyEngine."""
        if not reply:
            return False
        
        reply_type = reply.get("type", "text")
        if reply_type == "interactive_button" and reply.get("buttons"):
            return self.send_button_message(
                to_phone=to_phone,
                body_text=reply.get("body", ""),
                buttons=reply.get("buttons", []),
                header_text=reply.get("header", "Align and Glow Dental"),
                footer_text=reply.get("footer", "Tap an option below")
            )
        elif reply_type == "interactive_list" and reply.get("sections"):
            return self.send_list_message(
                to_phone=to_phone,
                body_text=reply.get("body", ""),
                button_label=reply.get("button_label", "View Options"),
                sections=reply.get("sections", []),
                header_text=reply.get("header", "Align and Glow Dental"),
                footer_text=reply.get("footer", "Select an option")
            )
        else:
            return self.send_text_message(to_phone, reply.get("text", reply.get("body", "")))

    def get_media_url(self, media_id):
        """Fetches the temporary CDN download URL for a media ID from Meta Graph API."""
        if not self.is_configured():
            return None, None
        url = f"{self.base_url}/{media_id}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("url"), data.get("mime_type")
        except Exception as e:
            print(f"[!] Error getting media URL from Meta ({media_id}): {e}")
            return None, None

    def download_media(self, media_id, save_path):
        """Downloads patient media (e.g. smile photo) from Meta CDN and saves locally."""
        media_url, mime = self.get_media_url(media_id)
        if not media_url:
            return None
        req = urllib.request.Request(
            media_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "curl/7.68.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(data)
                print(f"[+] Downloaded patient media ({len(data)} bytes) to: {save_path}")
                return save_path
        except Exception as e:
            print(f"[!] Error downloading patient media: {e}")
            return None


if __name__ == "__main__":
    client = WhatsAppCloudAPI()
    print("Testing Meta WhatsApp Cloud API credentials...")
    client.test_connection()
