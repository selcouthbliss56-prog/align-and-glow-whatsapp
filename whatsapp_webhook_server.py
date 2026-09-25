# -*- coding: utf-8 -*-
"""
Align and Glow Dental Clinic - WhatsApp Cloud API Webhook Auto-Responder Server
Zero-dependency Python HTTP server that:
1. Verifies Meta Webhook challenge (GET /webhook).
2. Receives live incoming patient WhatsApp messages (POST /webhook).
3. Automatically generates and dispatches context-aware clinical replies with quick-action buttons.
4. Alerts the Doctor / Front Desk immediately on WhatsApp when a patient requests an appointment or inquires.
5. Auto-saves patient leads to an Excel-compatible CSV spreadsheet (patient_leads.csv).
6. Provides a Reception Inbox web dashboard (GET /inbox) with 1-click "Chat on WhatsApp" and "Call Patient" buttons.
7. Exports patient leads via GET /export-leads.csv.

Usage:
  python whatsapp_webhook_server.py
"""

import sys
import os
import csv
import json
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from whatsapp_reply_engine import ClinicReplyEngine, load_env
from whatsapp_cloud_api import WhatsAppCloudAPI

INBOX_FILE = os.path.join(SCRIPT_DIR, "whatsapp_inbox.json")
LEADS_CSV_FILE = os.path.join(SCRIPT_DIR, "patient_leads.csv")
UPLOADS_DIR = os.path.join(SCRIPT_DIR, "patient_uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


def load_inbox():
    if os.path.exists(INBOX_FILE):
        try:
            with open(INBOX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_inbox_message(entry):
    inbox = load_inbox()
    inbox.insert(0, entry)
    inbox = inbox[:500]
    with open(INBOX_FILE, "w", encoding="utf-8") as f:
        json.dump(inbox, f, indent=2, ensure_ascii=False)


def save_lead_to_csv(entry):
    """Saves lead to an Excel-friendly CSV file."""
    file_exists = os.path.exists(LEADS_CSV_FILE)
    try:
        with open(LEADS_CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "Timestamp",
                    "Patient Name",
                    "Phone Number",
                    "Intent Category",
                    "Preferred Slot",
                    "Concern",
                    "Patient Message",
                    "Direct WhatsApp Chat Link"
                ])
            sender = entry.get("sender_phone", "")
            wa_link = f"https://wa.me/{sender}" if sender else ""
            writer.writerow([
                entry.get("timestamp", ""),
                entry.get("patient_name", "Patient"),
                f"+{sender}",
                entry.get("intent", "general").upper(),
                entry.get("booking_slot", ""),
                entry.get("booking_concern", ""),
                entry.get("incoming_message", ""),
                wa_link
            ])
    except Exception as e:
        print(f"[!] Error writing to leads CSV: {e}")


class WhatsAppWebhookHandler(BaseHTTPRequestHandler):
    reply_engine = ClinicReplyEngine()
    whatsapp_api = WhatsAppCloudAPI()
    env = load_env()
    verify_token = env.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "align_and_glow_webhook_token_2026").strip()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Meta Webhook Verification endpoint
        if path == "/webhook":
            mode = query.get("hub.mode", [""])[0]
            token = query.get("hub.verify_token", [""])[0]
            challenge = query.get("hub.challenge", [""])[0]

            if mode == "subscribe" and token == self.verify_token:
                print(f"\n[+] Meta Webhook Verified Successfully! Challenge accepted.")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(challenge.encode("utf-8"))
            else:
                print(f"\n[!] Webhook Verification Mismatch: token received={token}")
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Verification token mismatch")
            return

        # 2. Reception Inbox Web UI
        elif path == "/inbox":
            self._render_inbox_html()
            return

        # 3. Serve Patient Uploaded Media (Photos, X-rays)
        elif path.startswith("/uploads/"):
            fname = os.path.basename(path)
            fpath = os.path.join(UPLOADS_DIR, fname)
            if os.path.exists(fpath):
                mime_type = "image/jpeg"
                if fname.lower().endswith(".png"):
                    mime_type = "image/png"
                elif fname.lower().endswith(".webp"):
                    mime_type = "image/webp"
                elif fname.lower().endswith(".pdf"):
                    mime_type = "application/pdf"
                elif fname.lower().endswith(".ogg"):
                    mime_type = "audio/ogg"
                elif fname.lower().endswith(".mp3"):
                    mime_type = "audio/mpeg"
                elif fname.lower().endswith(".m4a"):
                    mime_type = "audio/mp4"
                elif fname.lower().endswith(".wav"):
                    mime_type = "audio/wav"
                with open(fpath, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Media Not Found")
            return

        # 3. Export Leads to CSV
        elif path == "/export-leads.csv":
            if os.path.exists(LEADS_CSV_FILE):
                with open(LEADS_CSV_FILE, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="align_and_glow_patient_leads.csv"')
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"No patient leads recorded yet.")
            return

        # 4. Status Health Check
        elif path in ["/", "/status"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_data = {
                "clinic": "Align and Glow Dental Clinic",
                "phone": "+91 97402 75502",
                "status": "Online & Auto-Responder Active",
                "webhook_path": "/webhook",
                "inbox_dashboard": "/inbox",
                "export_leads": "/export-leads.csv",
                "total_messages": len(load_inbox())
            }
            self.wfile.write(json.dumps(status_data, indent=2).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len)

        # Immediate 200 OK acknowledgment to Meta
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')

        try:
            data = json.loads(post_body.decode("utf-8"))
            self._process_meta_payload(data)
        except Exception as e:
            print(f"[!] Error processing incoming webhook payload: {e}")

    def _process_meta_payload(self, data):
        """Extracts messages from Meta payload, auto-replies, alerts doctor, and logs lead."""
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                statuses = value.get("statuses", [])

                for st in statuses:
                    recip = st.get("recipient_id")
                    st_val = st.get("status")
                    errors = st.get("errors", [])
                    if errors:
                        print(f"[!] Meta Delivery Error for +{recip}: {errors}")
                    else:
                        print(f"[i] Delivery Status for +{recip}: {st_val.upper()}")

                contact_names = {}
                for c in contacts:
                    contact_names[c.get("wa_id")] = c.get("profile", {}).get("name", "Patient")

                for msg in messages:
                    sender_phone = msg.get("from")
                    msg_id = msg.get("id")
                    msg_type = msg.get("type")
                    patient_name = contact_names.get(sender_phone, "Valued Patient")

                    incoming_text = ""
                    button_id = None
                    image_filename = None
                    image_caption = None

                    if msg_type == "text":
                        incoming_text = msg.get("text", {}).get("body", "").strip()
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        if interactive.get("type") == "button_reply":
                            btn_reply = interactive.get("button_reply", {})
                            button_id = btn_reply.get("id")
                            incoming_text = f"[Tapped: {btn_reply.get('title')}]"
                        elif interactive.get("type") == "list_reply":
                            list_reply = interactive.get("list_reply", {})
                            button_id = list_reply.get("id")
                            incoming_text = f"[Selected: {list_reply.get('title')}]"
                    elif msg_type == "image":
                        img_data = msg.get("image", {})
                        media_id = img_data.get("id")
                        image_caption = img_data.get("caption", "").strip()
                        incoming_text = f"[Uploaded Smile Photo]{': ' + image_caption if image_caption else ''}"
                        if media_id and self.whatsapp_api.is_configured():
                            ext = "jpg"
                            mime = img_data.get("mime_type", "")
                            if "png" in mime:
                                ext = "png"
                            elif "webp" in mime:
                                ext = "webp"
                            clean_s = str(sender_phone).replace("+", "")
                            image_filename = f"{clean_s}_{int(datetime.now().timestamp())}_{media_id[:8]}.{ext}"
                            save_dest = os.path.join(UPLOADS_DIR, image_filename)
                            print(f"[+] Downloading patient image (id: {media_id}) to {image_filename}...")
                            self.whatsapp_api.download_media(media_id, save_dest)
                    elif msg_type in ["audio", "voice"]:
                        aud_data = msg.get("audio") or msg.get("voice", {})
                        media_id = aud_data.get("id")
                        incoming_text = "[Voice Note / Audio Inquiry]"
                        if media_id and self.whatsapp_api.is_configured():
                            clean_s = str(sender_phone).replace("+", "")
                            image_filename = f"{clean_s}_{int(datetime.now().timestamp())}_{media_id[:8]}.ogg"
                            save_dest = os.path.join(UPLOADS_DIR, image_filename)
                            print(f"[+] Downloading patient voice note (id: {media_id}) to {image_filename}...")
                            self.whatsapp_api.download_media(media_id, save_dest)
                    elif msg_type == "document":
                        doc_data = msg.get("document", {})
                        media_id = doc_data.get("id")
                        doc_filename = doc_data.get("filename", "dental_report.pdf")
                        image_caption = doc_data.get("caption", "").strip()
                        incoming_text = f"[Uploaded Document: {doc_filename}]{': ' + image_caption if image_caption else ''}"
                        if media_id and self.whatsapp_api.is_configured():
                            clean_s = str(sender_phone).replace("+", "")
                            image_filename = f"{clean_s}_{int(datetime.now().timestamp())}_{doc_filename}"
                            save_dest = os.path.join(UPLOADS_DIR, image_filename)
                            print(f"[+] Downloading patient document (id: {media_id}) to {image_filename}...")
                            self.whatsapp_api.download_media(media_id, save_dest)

                    if not incoming_text and not button_id and not image_filename:
                        continue

                    print("\n" + "=" * 65)
                    print(f"📩 RECEIVED WHATSAPP MESSAGE")
                    print(f"   From: {patient_name} (+{sender_phone})")
                    print(f"   Content: {incoming_text}")
                    if image_filename:
                        print(f"   Saved Media: {image_filename}")
                    print("=" * 65)

                    # 1. Generate Contextual Dental Reply
                    if msg_type in ["image", "document"]:
                        reply = self.reply_engine.generate_image_reply(
                            patient_name=patient_name,
                            caption=image_caption,
                            sender_phone=sender_phone
                        )
                    elif msg_type in ["audio", "voice"]:
                        reply = self.reply_engine.generate_audio_reply(
                            patient_name=patient_name,
                            sender_phone=sender_phone
                        )
                    else:
                        reply = self.reply_engine.generate_reply(
                            message_text=incoming_text,
                            button_id=button_id,
                            patient_name=patient_name,
                            sender_phone=sender_phone
                        )

                    print(f"🤖 GENERATED AUTO-REPLY (Intent: {reply.get('intent', 'unknown').upper()}):")
                    print(f"   {reply.get('body', '')[:120]}...")

                    # 2. Dispatch Reply via WhatsApp Cloud API
                    send_success = False
                    if self.whatsapp_api.is_configured():
                        send_success = self.whatsapp_api.send_reply(sender_phone, reply)
                        if send_success:
                            print(f"[+] Successfully sent reply to +{sender_phone}!")
                        else:
                            print(f"[X] Failed to send reply to +{sender_phone}.")

                    # 3. Log to Inbox JSON and Leads CSV
                    timestamp_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
                    b_info = reply.get("booking_info", {})
                    p_lead_name = b_info.get("name") or patient_name
                    log_entry = {
                        "timestamp": timestamp_str,
                        "sender_phone": sender_phone,
                        "patient_name": p_lead_name,
                        "incoming_message": incoming_text,
                        "intent": reply.get("intent", "general"),
                        "booking_slot": b_info.get("slot", ""),
                        "booking_concern": b_info.get("concern", ""),
                        "image_file": image_filename,
                        "reply_type": reply.get("type"),
                        "reply_body": reply.get("body"),
                        "buttons": [b.get("title") for b in reply.get("buttons", [])],
                        "sent_live": send_success
                    }
                    save_inbox_message(log_entry)
                    save_lead_to_csv(log_entry)

                    # 4. Instant WhatsApp Notification Alert to Doctor/Receptionist Phones
                    alert_raw = self.env.get("CLINIC_ADMIN_ALERT_PHONE", "").strip()
                    alert_phones = [p.strip().replace("+", "") for p in alert_raw.split(",") if p.strip()]
                    clean_sender = str(sender_phone).replace("+", "").strip()

                    for ap in alert_phones:
                        if clean_sender != ap and clean_sender != f"91{ap}":
                            if reply.get("intent") == "image_received":
                                caption_line = f"💬 *Patient Note:* \"{image_caption}\"\n" if image_caption else ""
                                photo_line = f"🖼 *Saved Photo:* {image_filename}\n" if image_filename else ""
                                alert_msg = (
                                    f"📸 *NEW PATIENT SMILE PHOTO RECEIVED!* 🦷✨\n\n"
                                    f"👤 *Patient Name:* {patient_name}\n"
                                    f"📱 *Phone:* +{clean_sender}\n"
                                    f"{caption_line}"
                                    f"{photo_line}\n"
                                    f"👉 *View Photo in Reception Inbox:*\nhttp://localhost:8000/inbox\n\n"
                                    f"👉 *Tap to Chat on WhatsApp:*\nhttps://wa.me/{clean_sender}\n\n"
                                    f"👉 *Tap to Call:* tel:+{clean_sender}"
                                )
                            elif reply.get("intent") == "audio_received":
                                audio_line = f"🎵 *Saved Audio File:* {image_filename}\n" if image_filename else ""
                                alert_msg = (
                                    f"🎙️ *NEW PATIENT VOICE NOTE RECEIVED!* 🦷✨\n\n"
                                    f"👤 *Patient Name:* {patient_name}\n"
                                    f"📱 *Phone:* +{clean_sender}\n"
                                    f"{audio_line}\n"
                                    f"👉 *Listen in Reception Inbox:*\nhttp://localhost:8000/inbox\n\n"
                                    f"👉 *Tap to Chat on WhatsApp:*\nhttps://wa.me/{clean_sender}\n\n"
                                    f"👉 *Tap to Call:* tel:+{clean_sender}"
                                )
                            elif reply.get("intent") == "booking_confirmed":
                                p_slot = b_info.get("slot", "Requested Slot")
                                p_concern = b_info.get("concern", "Consultation")
                                is_urg = b_info.get("is_urgent", False)
                                header_alert = "🚨 *URGENT SAME-DAY APPOINTMENT REQUEST!*" if is_urg else "📅 *NEW APPOINTMENT BOOKING CONFIRMED!*"

                                alert_msg = (
                                    f"{header_alert}\n\n"
                                    f"👤 *Patient Name:* {p_lead_name}\n"
                                    f"⏰ *Preferred Slot:* {p_slot}\n"
                                    f"🩺 *Concern:* {p_concern}\n"
                                    f"📱 *Phone:* +{clean_sender}\n"
                                    f"💬 *Patient Input:*\n\"{incoming_text}\"\n\n"
                                    f"👉 *Tap to Chat on WhatsApp:*\nhttps://wa.me/{clean_sender}\n\n"
                                    f"👉 *Tap to Call Patient:* tel:+{clean_sender}"
                                )
                            elif reply.get("intent") == "reschedule_request":
                                alert_msg = (
                                    f"🗓️ *PATIENT RESCHEDULE / CANCEL REQUEST*\n\n"
                                    f"👤 *Patient:* {patient_name}\n"
                                    f"📱 *Phone:* +{clean_sender}\n"
                                    f"💬 *Patient Message:* \"{incoming_text}\"\n\n"
                                    f"👉 *Tap to Chat on WhatsApp:*\nhttps://wa.me/{clean_sender}\n\n"
                                    f"👉 *Tap to Call:* tel:+{clean_sender}"
                                )
                            else:
                                alert_msg = (
                                    f"🚨 *NEW PATIENT INQUIRY!*\n\n"
                                    f"👤 *Patient:* {patient_name}\n"
                                    f"📱 *Phone:* +{clean_sender}\n"
                                    f"🎯 *Intent:* {reply.get('intent', 'general').upper()}\n"
                                    f"💬 *Patient Message:* \"{incoming_text}\"\n\n"
                                    f"👉 *Tap to Chat on WhatsApp:*\nhttps://wa.me/{clean_sender}\n\n"
                                    f"👉 *Tap to Call:* tel:+{clean_sender}"
                                )
                            print(f"[+] Forwarding instant alert to Doctor/Reception (+{ap})...")
                            self.whatsapp_api.send_text_message(ap, alert_msg)

    def _render_inbox_html(self):
        """Renders reception inbox UI with live stats, search, audio player, and 1-click connect actions."""
        inbox = load_inbox()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        total_leads = len(inbox)
        total_bookings = sum(1 for i in inbox if i.get("intent") == "booking_confirmed")
        total_photos = sum(1 for i in inbox if i.get("image_file") and any(i.get("image_file").lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]))
        total_audio = sum(1 for i in inbox if i.get("image_file") and any(i.get("image_file").lower().endswith(ext) for ext in [".ogg", ".mp3", ".m4a", ".wav"]))
        total_urgent = sum(1 for i in inbox if "urgent" in str(i.get("intent")).lower() or "pain" in str(i.get("incoming_message")).lower() or "emergency" in str(i.get("intent")).lower())

        cards_html = ""
        for item in inbox:
            sender = item.get("sender_phone", "")
            clean_s = str(sender).replace("+", "").strip()
            p_name = item.get("patient_name") or "Valued Patient"
            intent = item.get("intent", "inquiry")
            b_slot = item.get("booking_slot", "")
            buttons_html = "".join([f'<span class="badge">{b}</span>' for b in item.get("buttons", [])])
            img_file = item.get("image_file")
            
            media_type = "none"
            media_html = ""
            if img_file:
                lower_f = img_file.lower()
                if any(lower_f.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    media_type = "photo"
                    media_html = f"""
                    <div class="media-container photo-box">
                        <span class="media-label">📸 Attached Patient Photo:</span>
                        <a href="/uploads/{img_file}" target="_blank">
                            <img src="/uploads/{img_file}" alt="Patient Upload" class="patient-img">
                        </a>
                        <span class="media-subtext">🔍 Click photo to open high resolution</span>
                    </div>
                    """
                elif any(lower_f.endswith(ext) for ext in [".ogg", ".mp3", ".m4a", ".wav"]):
                    media_type = "audio"
                    media_html = f"""
                    <div class="media-container audio-box">
                        <span class="media-label">🎙️ Patient Voice Note / Audio Message:</span>
                        <audio controls class="patient-audio" src="/uploads/{img_file}"></audio>
                        <a href="/uploads/{img_file}" download class="media-download">⬇️ Download Audio</a>
                    </div>
                    """
                elif lower_f.endswith(".pdf"):
                    media_type = "document"
                    media_html = f"""
                    <div class="media-container doc-box">
                        <span class="media-label">📄 Attached Document / X-Ray:</span>
                        <a href="/uploads/{img_file}" target="_blank" class="doc-link">📄 Open Document ({img_file})</a>
                    </div>
                    """

            # Pre-filled WhatsApp URLs for 1-click receptionist responses
            confirm_msg = urllib.parse.quote(
                f"Hello {p_name}, your consultation request at *Align and Glow Dental Clinic* is confirmed! 🦷✨\n\n"
                f"📅 Slot: {b_slot or 'Reserved Appointment'}\n"
                f"📍 Clinic: Opp. Kamakya Theatre, Banashankari 3rd Stage, Bengaluru.\n\n"
                f"We look forward to taking great care of your smile! Let us know if you need any directions."
            )
            photo_req_msg = urllib.parse.quote(
                f"Hello {p_name}, thank you for contacting *Align and Glow Dental Clinic*! 🦷📸\n\n"
                f"Could you please share a well-lit, clear photo of your front teeth / smile right here? "
                f"Our clinical team will review it for clear aligners, veneers, or whitening."
            )
            wa_confirm_url = f"https://wa.me/{clean_s}?text={confirm_msg}"
            wa_photo_req_url = f"https://wa.me/{clean_s}?text={photo_req_msg}"

            # Intent categorization tag for filter pills
            filter_category = "inquiry"
            if intent == "booking_confirmed":
                filter_category = "booking"
            elif media_type == "photo":
                filter_category = "photo"
            elif media_type == "audio":
                filter_category = "audio"
            elif "urgent" in intent.lower() or "emergency" in intent.lower():
                filter_category = "urgent"

            intent_badge_class = "pill-inquiry"
            if intent == "booking_confirmed":
                intent_badge_class = "pill-booking"
            elif media_type in ["photo", "audio"]:
                intent_badge_class = "pill-media"
            elif "urgent" in intent.lower() or "emergency" in intent.lower():
                intent_badge_class = "pill-urgent"

            search_blob = f"{p_name} {clean_s} {item.get('incoming_message', '')} {intent} {b_slot}".lower()

            cards_html += f"""
            <div class="chat-card" data-category="{filter_category}" data-search="{search_blob}">
                <div class="chat-header">
                    <div>
                        <strong class="name">{p_name}</strong> 
                        <span class="phone">+{clean_s}</span>
                    </div>
                    <div class="header-right">
                        <span class="intent-pill {intent_badge_class}">{intent.upper().replace('_', ' ')}</span>
                        <span class="time">{item.get('timestamp')}</span>
                    </div>
                </div>

                <div class="msg patient-msg">
                    <span class="lbl">Patient Input:</span>
                    <div class="msg-text">{item.get('incoming_message')}</div>
                    {media_html}
                </div>

                <div class="msg reply-msg">
                    <span class="lbl">Bot Reply Sent:</span>
                    <pre>{item.get('reply_body')}</pre>
                    <div class="btn-group">{buttons_html}</div>
                </div>

                <div class="action-bar">
                    <a href="https://wa.me/{clean_s}" target="_blank" class="action-btn btn-wa">
                        💬 Open WhatsApp
                    </a>
                    <a href="tel:+{clean_s}" class="action-btn btn-call">
                        📞 Call Patient
                    </a>
                    <a href="{wa_confirm_url}" target="_blank" class="action-btn btn-secondary">
                        ✅ Confirm Slot (WA)
                    </a>
                    <a href="{wa_photo_req_url}" target="_blank" class="action-btn btn-secondary">
                        📸 Request Smile Photo
                    </a>
                </div>
            </div>
            """

        if not cards_html:
            cards_html = "<div class='empty'>No patient messages received yet. Send a test message or scan the clinic QR!</div>"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Align and Glow - WhatsApp Reception Desk & Patient Hub</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: #F8FAFC;
            color: #0F172A;
            margin: 0;
            padding: 24px 16px;
        }}
        .container {{
            max-width: 1040px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #0E253F 0%, #173B66 100%);
            color: white;
            padding: 28px 36px;
            border-radius: 20px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 14px 30px rgba(14,37,63,0.18);
            flex-wrap: wrap;
            gap: 16px;
        }}
        .header h1 {{ margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }}
        .header p {{ margin: 6px 0 0; color: #CBD5E1; font-size: 14.5px; }}
        .header-actions {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
        .badge-live {{
            background: #10B981;
            color: white;
            font-size: 12px;
            font-weight: 700;
            padding: 6px 14px;
            border-radius: 20px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .btn-export {{
            background: #D9A036;
            color: #0E253F;
            text-decoration: none;
            font-size: 13.5px;
            font-weight: 700;
            padding: 8px 18px;
            border-radius: 10px;
            transition: all 0.2s;
            box-shadow: 0 4px 12px rgba(217,160,54,0.3);
        }}
        .btn-export:hover {{ transform: translateY(-1px); opacity: 0.95; }}

        /* Stats Bar */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: white;
            padding: 18px 20px;
            border-radius: 14px;
            border: 1px solid #E2E8F0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.02);
            display: flex;
            align-items: center;
            gap: 14px;
        }}
        .stat-icon {{
            font-size: 26px;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 12px;
            background: #F1F5F9;
        }}
        .stat-num {{ font-size: 22px; font-weight: 800; color: #0E253F; margin: 0; line-height: 1.1; }}
        .stat-lbl {{ font-size: 12px; font-weight: 600; color: #64748B; margin: 2px 0 0; text-transform: uppercase; }}

        /* Filter & Search Bar */
        .controls-card {{
            background: white;
            padding: 16px 20px;
            border-radius: 16px;
            margin-bottom: 20px;
            border: 1px solid #E2E8F0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.02);
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}
        .search-box {{
            width: 100%;
            padding: 12px 18px;
            font-size: 15px;
            font-family: inherit;
            border: 1.5px solid #CBD5E1;
            border-radius: 10px;
            outline: none;
            transition: border-color 0.2s;
        }}
        .search-box:focus {{ border-color: #0E253F; }}
        .filter-row {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
        }}
        .filter-pills {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .filter-btn {{
            background: #F1F5F9;
            color: #475569;
            border: none;
            font-family: inherit;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .filter-btn:hover, .filter-btn.active {{
            background: #0E253F;
            color: white;
        }}
        .auto-refresh-box {{
            font-size: 13px;
            color: #64748B;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        /* Chat Cards */
        .chat-card {{
            background: white;
            border-radius: 16px;
            padding: 22px 26px;
            margin-bottom: 20px;
            border: 1px solid #E2E8F0;
            box-shadow: 0 4px 14px rgba(0,0,0,0.03);
            transition: all 0.2s;
        }}
        .chat-card:hover {{ box-shadow: 0 6px 20px rgba(0,0,0,0.05); border-color: #CBD5E1; }}
        .chat-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #F1F5F9;
            padding-bottom: 14px;
            margin-bottom: 14px;
        }}
        .name {{ font-size: 18px; color: #0E253F; font-weight: 700; }}
        .phone {{ color: #64748B; font-size: 14.5px; margin-left: 10px; font-weight: 600; }}
        .header-right {{ display: flex; gap: 10px; align-items: center; }}
        .intent-pill {{
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 6px;
            letter-spacing: 0.3px;
        }}
        .pill-booking {{ background: #D1FAE5; color: #065F46; }}
        .pill-media {{ background: #EDE9FE; color: #5B21B6; }}
        .pill-urgent {{ background: #FEE2E2; color: #991B1B; }}
        .pill-inquiry {{ background: #FEF3C7; color: #92400E; }}
        .time {{ color: #94A3B8; font-size: 12.5px; font-weight: 500; }}

        .msg {{ padding: 14px 18px; border-radius: 10px; margin-bottom: 12px; font-size: 14.5px; line-height: 1.5; }}
        .patient-msg {{ background: #F8FAFC; border-left: 4px solid #0E253F; }}
        .reply-msg {{ background: #ECFDF5; border-left: 4px solid #10B981; }}
        .lbl {{ font-weight: 700; font-size: 11px; text-transform: uppercase; display: block; margin-bottom: 4px; color: #64748B; letter-spacing: 0.5px; }}
        .msg-text {{ font-size: 15.5px; font-weight: 600; color: #0F172A; }}
        pre {{ margin: 0; font-family: inherit; white-space: pre-wrap; font-size: 13.5px; color: #0F172A; }}
        .btn-group {{ margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }}
        .badge {{ background: #D1FAE5; color: #065F46; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }}

        /* Media */
        .media-container {{
            margin-top: 12px;
            padding: 12px 16px;
            background: #F1F5F9;
            border-radius: 12px;
            border: 1px solid #E2E8F0;
        }}
        .media-label {{ font-size: 12px; font-weight: 700; color: #475569; display: block; margin-bottom: 8px; }}
        .patient-img {{
            max-width: 260px;
            max-height: 240px;
            border-radius: 10px;
            display: block;
            border: 1px solid #CBD5E1;
            box-shadow: 0 4px 10px rgba(0,0,0,0.06);
            transition: transform 0.2s;
        }}
        .patient-img:hover {{ transform: scale(1.02); }}
        .media-subtext {{ font-size: 11.5px; color: #64748B; margin-top: 6px; display: inline-block; font-weight: 500; }}
        .patient-audio {{ width: 100%; max-width: 380px; height: 38px; display: block; margin-bottom: 6px; }}
        .media-download, .doc-link {{
            font-size: 12px;
            font-weight: 600;
            color: #0E253F;
            text-decoration: underline;
        }}

        /* Action Buttons */
        .action-bar {{
            margin-top: 16px;
            padding-top: 14px;
            border-top: 1px dashed #E2E8F0;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .action-btn {{
            display: inline-flex;
            align-items: center;
            padding: 8px 16px;
            border-radius: 9px;
            font-size: 13.5px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .btn-wa {{
            background: #25D366;
            color: white;
            box-shadow: 0 2px 8px rgba(37,211,102,0.25);
        }}
        .btn-wa:hover {{ background: #1EBE5D; transform: translateY(-1px); }}
        .btn-call {{
            background: #0E253F;
            color: white;
        }}
        .btn-call:hover {{ background: #1B3B60; transform: translateY(-1px); }}
        .btn-secondary {{
            background: #F1F5F9;
            color: #334155;
            border: 1px solid #CBD5E1;
        }}
        .btn-secondary:hover {{ background: #E2E8F0; color: #0F172A; }}
        .empty {{ text-align: center; padding: 60px 24px; color: #64748B; background: white; border-radius: 16px; font-size: 16px; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div>
                <h1>Align and Glow Dental Clinic</h1>
                <p>Reception Desk & Smart Patient Hub • Line: +91 97402 75502</p>
            </div>
            <div class="header-actions">
                <a href="/export-leads.csv" class="btn-export">⬇️ Export Leads (CSV)</a>
                <span class="badge-live">● Bot Online 24/7</span>
            </div>
        </div>

        <!-- Summary Stats Grid -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon">👥</div>
                <div>
                    <div class="stat-num">{total_leads}</div>
                    <div class="stat-lbl">Total Leads</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">📅</div>
                <div>
                    <div class="stat-num">{total_bookings}</div>
                    <div class="stat-lbl">Bookings</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">📸</div>
                <div>
                    <div class="stat-num">{total_photos}</div>
                    <div class="stat-lbl">Smile Photos</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">🎙️</div>
                <div>
                    <div class="stat-num">{total_audio}</div>
                    <div class="stat-lbl">Voice Notes</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">🚨</div>
                <div>
                    <div class="stat-num">{total_urgent}</div>
                    <div class="stat-lbl">Urgent Care</div>
                </div>
            </div>
        </div>

        <!-- Search & Filter Controls -->
        <div class="controls-card">
            <input type="text" id="searchInput" class="search-box" placeholder="🔍 Search patient name, phone number, treatment, or message content..." onkeyup="filterCards()">
            <div class="filter-row">
                <div class="filter-pills">
                    <button class="filter-btn active" onclick="setFilter('all', this)">All Messages ({total_leads})</button>
                    <button class="filter-btn" onclick="setFilter('booking', this)">📅 Bookings ({total_bookings})</button>
                    <button class="filter-btn" onclick="setFilter('photo', this)">📸 Photos ({total_photos})</button>
                    <button class="filter-btn" onclick="setFilter('audio', this)">🎙️ Voice Notes ({total_audio})</button>
                    <button class="filter-btn" onclick="setFilter('urgent', this)">🚨 Urgent Care ({total_urgent})</button>
                </div>
                <div class="auto-refresh-box">
                    <input type="checkbox" id="autoRefreshToggle" checked>
                    <label for="autoRefreshToggle">Auto-refresh (15s)</label>
                </div>
            </div>
        </div>

        <!-- Chat Feed -->
        <div id="cardsList">
            {cards_html}
        </div>
    </div>

    <script>
        let currentFilter = 'all';

        function setFilter(category, btn) {{
            currentFilter = category;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            filterCards();
        }}

        function filterCards() {{
            const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
            const cards = document.querySelectorAll('.chat-card');
            cards.forEach(card => {{
                const cat = card.getAttribute('data-category') || '';
                const searchBlob = card.getAttribute('data-search') || '';
                
                const matchesFilter = (currentFilter === 'all') || (cat === currentFilter);
                const matchesSearch = !query || searchBlob.includes(query);

                if (matchesFilter && matchesSearch) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}

        // Auto Refresh every 15s if user is not actively typing
        setInterval(() => {{
            const toggle = document.getElementById('autoRefreshToggle');
            const searchInput = document.getElementById('searchInput');
            if (toggle && toggle.checked && (!searchInput || !searchInput.value)) {{
                window.location.reload();
            }}
        }}, 15000);
    </script>
</body>
</html>
"""
        self.wfile.write(html.encode("utf-8"))


def run_server(port=8000):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, WhatsAppWebhookHandler)
    env = load_env()
    token = env.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "align_and_glow_webhook_token_2026")
    print("\n" + "=" * 65)
    print(" ALIGN AND GLOW DENTAL CLINIC - WHATSAPP WEBHOOK AUTO-RESPONDER")
    print("=" * 65)
    print(f" Active Clinic Number : +91 97402 75502")
    print(f" Local Webhook URL    : http://localhost:{port}/webhook")
    print(f" Reception Inbox UI   : http://localhost:{port}/inbox")
    print(f" Leads Spreadsheet    : {LEADS_CSV_FILE}")
    print("=" * 65)
    print("\n[+] Server listening for Meta Webhook requests... Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping WhatsApp Webhook Server. Goodbye!")
        httpd.server_close()


if __name__ == "__main__":
    env = load_env()
    port = int(os.environ.get("PORT", env.get("WHATSAPP_WEBHOOK_PORT", 8000)))
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
