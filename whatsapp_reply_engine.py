# -*- coding: utf-8 -*-
"""
Align and Glow Dental Clinic - Automated WhatsApp Reply Engine
Handles intent classification, clinical information retrieval,
interactive button reply generation, and optional Gemini AI fallback.

Strict Guidelines Enforced:
1. No personal doctor names ("dont add my name make it look proffesional").
2. Focus on aesthetic dentistry, clear aligners, smile designing, and evidence-based dental care.
3. Accurate clinic details:
   - Address: Sri Rama Arcade, 100 Feet Ring Road, Banashankari 3rd Stage (Opp. Kamakya Theatre)
   - Timings: Open Daily 9:00 AM – 9:00 PM
   - Phone / WhatsApp: +91 97402 75502
   - Maps: https://maps.google.com/?q=Align+and+Glow+Dental+Clinic+Banashankari+Bengaluru
   - Reviews: https://g.page/r/alignandglow/review
"""

import os
import re
import time
import json
import urllib.request
import urllib.error

# Clinic Constants
CLINIC_NAME = "Align and Glow Dental Clinic"
CLINIC_PHONE = "+91 97402 75502"
CLINIC_ADDRESS = (
    "No. 33, Sri Rama Arcade, 100 Feet Ring Road, Banashankari 3rd Stage, "
    "Bengaluru - 560085 (Opp. Kamakya Theatre, Kathriguppe Cross)"
)
CLINIC_HOURS = "Open Daily 9:00 AM – 9:00 PM (Monday – Sunday)"
GOOGLE_MAPS_LINK = "https://maps.google.com/?q=Align+and+Glow+Dental+Clinic+Banashankari+Bengaluru"
GOOGLE_REVIEW_LINK = "https://g.page/r/alignandglow/review"

STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "whatsapp_user_states.json"))


def load_user_states():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_user_states(states):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(states, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error saving user states: {e}")


def load_env():
    """Loads environment variables from os.environ, merged with .env file if present."""
    env = dict(os.environ)
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.path.exists(env_path):
        env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class ClinicReplyEngine:
    def __init__(self):
        self.env = load_env()
        self.gemini_key = self.env.get("GEMINI_API_KEY", "").strip()

    def set_user_state(self, sender_phone, state_name, meta=None):
        if not sender_phone:
            return
        states = load_user_states()
        states[str(sender_phone)] = {
            "state": state_name,
            "meta": meta or {},
            "updated_at": time.time()
        }
        save_user_states(states)

    def get_user_state(self, sender_phone):
        if not sender_phone:
            return None
        states = load_user_states()
        data = states.get(str(sender_phone))
        if data:
            # Expire state if older than 3 hours
            if time.time() - data.get("updated_at", 0) > 10800:
                self.clear_user_state(sender_phone)
                return None
            return data.get("state")
        return None

    def clear_user_state(self, sender_phone):
        if not sender_phone:
            return
        states = load_user_states()
        if str(sender_phone) in states:
            del states[str(sender_phone)]
            save_user_states(states)

    def is_booking_submission(self, text, user_state=None):
        """
        Determines whether a message is an appointment booking or time confirmation submission.
        """
        text_clean = (text or "").strip().lower()
        if not text_clean:
            return False

        # If user is in WAITING_FOR_BOOKING_DETAILS, any non-greeting text is booking data
        if user_state == "WAITING_FOR_BOOKING_DETAILS":
            if re.search(r"^(hi|hello|hey|namaste|start|menu|help)\b", text_clean):
                return False
            return True

        # If user is asking to reschedule or cancel without a specific time yet, route to reschedule flow
        if re.search(r"\b(reschedule|postpone|cancel)\b", text_clean) and not re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}\s*(?:am|pm))\b", text_clean):
            return False

        # Numbered list: 1 <name> 2 <time> 3 <concern>
        if re.search(r"(?:^|\s|\n)1[\.\:\-\)]?\s*.*?(?:2[\.\:\-\)]|\n2)", text_clean, re.DOTALL):
            return True

        # Specific time patterns: 5pm, 5:00 pm, 5.30pm, 10am, 11:30 am, 5 o'clock
        time_pat = r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\b\d{1,2}\s*(?:am|pm)\b|\b(?:at\s+)?\d{1,2}\s*o['\s]?clock)\b"
        has_time = bool(re.search(time_pat, text_clean))

        # Date/day words
        day_words = r"\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|afternoon|evening)\b"
        has_day = bool(re.search(day_words, text_clean))

        # Booking action words
        book_words = r"\b(book|appointment|slot|schedule|timing|visit|consultation|confirm|available|can i come|come at|reach at)\b"
        has_book_words = bool(re.search(book_words, text_clean))

        if has_time and (has_book_words or has_day or len(text_clean.split()) <= 4):
            return True

        if has_book_words and (has_time or has_day):
            return True

        return False

    def extract_booking_details(self, message_text, patient_name=None):
        """
        Intelligently extracts patient name, preferred time slot, and clinical concern.
        """
        full_text = (message_text or "").strip()
        raw_lines = [l.strip() for l in full_text.split("\n") if l.strip()]

        extracted_name = ""
        extracted_slot = ""
        extracted_concern = ""

        # 1. Numbered format: 1 <name> 2 <time> 3 <concern>
        num_match = re.search(
            r"1[\.\:\-\)]?\s*(?P<pname>[^2\n\r]+?)(?:\s*2[\.\:\-\)]|\n2[\.\:\-\)])\s*(?P<pslot>[^3\n\r]+?)(?:\s*3[\.\:\-\)]|\n3[\.\:\-\)])\s*(?P<pconcern>.+)",
            full_text,
            re.IGNORECASE | re.DOTALL
        )
        if num_match:
            extracted_name = num_match.group("pname").strip()
            extracted_slot = num_match.group("pslot").strip()
            extracted_concern = num_match.group("pconcern").strip()
        elif len(raw_lines) >= 3:
            extracted_name = re.sub(r"^[1-3][\.\:\-\)]?\s*", "", raw_lines[0]).strip()
            extracted_slot = re.sub(r"^[1-3][\.\:\-\)]?\s*", "", raw_lines[1]).strip()
            extracted_concern = re.sub(r"^[1-3][\.\:\-\)]?\s*", "", raw_lines[2]).strip()
        elif len(raw_lines) == 2:
            line0 = raw_lines[0]
            line1 = raw_lines[1]
            time_pat = r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\b\d{1,2}\s*(?:am|pm)\b|\b(?:today|tomorrow)\b)"
            if re.search(time_pat, line0, re.IGNORECASE):
                extracted_slot = line0
                extracted_concern = line1
            elif re.search(time_pat, line1, re.IGNORECASE):
                extracted_name = line0
                extracted_slot = line1
            else:
                extracted_name = line0
                extracted_concern = line1

        # 2. Refine slot from time regex if not found yet
        time_regex = r"\b((?:(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|afternoon|evening)\s*(?:at\s*)?)?\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\b\d{1,2}\s*(?:am|pm)\b|\b\d{1,2}(?::\d{2})\b|\b(?:morning|afternoon|evening)\b|\b(?:at\s+)?\d{1,2}\s*o['\s]?clock\b)"
        if not extracted_slot:
            time_match = re.search(time_regex, full_text, re.IGNORECASE)
            if time_match:
                extracted_slot = time_match.group(0).strip()

        # Clean / Normalize Slot
        if extracted_slot:
            extracted_slot = re.sub(r"^[^\w]+|[^\w\s\:\.]+$", "", extracted_slot).strip()
            extracted_slot = re.sub(r"(?i)(?<!:)\b(\d{1,2})\s*pm\b", r"\1:00 PM", extracted_slot)
            extracted_slot = re.sub(r"(?i)(?<!:)\b(\d{1,2})\s*am\b", r"\1:00 AM", extracted_slot)
            extracted_slot = re.sub(r"(?i):(\d{2})\s*pm\b", r":\1 PM", extracted_slot)
            extracted_slot = re.sub(r"(?i):(\d{2})\s*am\b", r":\1 AM", extracted_slot)
            extracted_slot = extracted_slot.title().replace("Pm", "PM").replace("Am", "AM")
        else:
            extracted_slot = "Today / Tomorrow (Preferred Slot)"

        # Refine Clinical Concern
        lower_text = full_text.lower()
        if not extracted_concern:
            if any(w in lower_text for w in ["pain", "toothache", "ache", "hurt", "swelling", "bleeding"]):
                extracted_concern = "Toothache / Pain Relief Care"
            elif any(w in lower_text for w in ["aligner", "invisalign", "braces"]):
                extracted_concern = "Clear Aligners / Invisible Braces"
            elif any(w in lower_text for w in ["smile design", "veneer", "bonding"]):
                extracted_concern = "Aesthetic Smile Design & Veneers"
            elif any(w in lower_text for w in ["whitening", "bleaching", "yellow"]):
                extracted_concern = "Cosmetic Teeth Whitening"
            elif any(w in lower_text for w in ["cleaning", "scaling"]):
                extracted_concern = "Scaling & Preventive Care"
            elif any(w in lower_text for w in ["implant", "replacement"]):
                extracted_concern = "Dental Implants"
            elif any(w in lower_text for w in ["rct", "root canal", "crown", "cap"]):
                extracted_concern = "Root Canal & Crown Evaluation"
            else:
                extracted_concern = "Dental & Aesthetic Consultation"
        else:
            extracted_concern = re.sub(r"^[^\w]+|[^\w\s]+$", "", extracted_concern).strip().capitalize()

        # Clean Patient Name
        if extracted_name:
            extracted_name = re.sub(r"[^\w\s]", "", extracted_name).strip().title()
        elif patient_name and patient_name.lower() not in ["patient", "valued patient", "dr anu", "align and glow"]:
            extracted_name = patient_name.strip()
        else:
            extracted_name = "Valued Patient"

        is_urgent = any(w in lower_text for w in ["pain", "toothache", "swelling", "bleeding", "severe", "urgent", "emergency", "hurt"])

        return {
            "name": extracted_name,
            "slot": extracted_slot,
            "concern": extracted_concern,
            "is_urgent": is_urgent
        }

    def generate_reply(self, message_text=None, button_id=None, patient_name=None, sender_phone=None, **kwargs):
        """
        Processes incoming message text or button click ID and generates
        a structured reply ready for WhatsApp Cloud API.
        """
        if message_text is None and "incoming_message" in kwargs:
            message_text = kwargs["incoming_message"]

        # 1. Handle Interactive Button Click if present
        if button_id:
            return self._handle_button_reply(button_id, patient_name, sender_phone)

        text_clean = (message_text or "").strip().lower()
        if not text_clean:
            return self._reply_greeting(patient_name)

        user_state = self.get_user_state(sender_phone)

        # 2. Check for Button / List Click text equivalents (e.g. user typed button or list label)
        if text_clean in ["book visit", "btn_book", "urgent visit", "book assessment", "book scan", "book whitening", "book consult"]:
            return self._handle_button_reply("btn_book", patient_name, sender_phone)
        if text_clean in ["clinic location", "btn_location", "get directions", "view location"]:
            return self._handle_button_reply("btn_location", patient_name, sender_phone)
        if text_clean in ["our services", "treatments", "btn_services", "explore services", "all services", "list_treatments"]:
            return self._handle_button_reply("btn_services", patient_name, sender_phone)
        if text_clean in ["photo assessment", "upload photo", "btn_photo", "btn_upload_photo", "virtual smile check", "smile check", "send photo", "send smile photo", "send tooth photo", "send teeth photo", "list_photo"]:
            return self._handle_button_reply("btn_photo", patient_name, sender_phone)
        if text_clean in ["list_smile_design", "smile design", "veneers"]:
            return self._reply_smile_design()
        if text_clean in ["list_aligners", "clear aligners", "aligners"]:
            return self._reply_aligners()
        if text_clean in ["list_whitening", "teeth whitening", "whitening"]:
            return self._reply_whitening()
        if text_clean in ["list_rct", "rct", "root canal"]:
            return self._reply_rct()
        if text_clean in ["list_implants", "dental implants", "implants"]:
            return self._reply_implants()
        if text_clean in ["list_cleaning", "scaling", "cleaning"]:
            return self._reply_cleaning()
        if text_clean in ["list_pediatric", "kids dentistry", "pediatric"]:
            return self._reply_pediatric()
        if text_clean in ["list_emergency", "urgent relief", "emergency"]:
            return self._reply_emergency()
        if text_clean in ["list_faqs", "faqs", "faq"]:
            return self._reply_faqs()
        if text_clean in ["btn_emi", "list_emi", "emi plans", "emi"]:
            return self._reply_payment_emi()
        if text_clean in ["btn_reschedule", "reschedule slot"]:
            return self._reply_reschedule()

        # 3. Check for User State: WAITING_FOR_BOOKING_DETAILS
        if user_state == "WAITING_FOR_BOOKING_DETAILS":
            # If user sent just a step number (e.g. "2" for time, "1" for name, "3" for concern)
            if text_clean in ["2", "2.", "option 2", "#2", "time", "slot"]:
                return self._reply_booking_time_prompt()
            if text_clean in ["1", "1.", "option 1", "#1", "name"]:
                return self._reply_booking_name_prompt()
            if text_clean in ["3", "3.", "option 3", "#3", "concern", "treatment"]:
                return self._reply_booking_concern_prompt()

            # If user sent an explicit greeting/reset
            if re.search(r"^(hi|hello|hey|namaste|start|menu|help)\b", text_clean):
                self.clear_user_state(sender_phone)
                return self._reply_greeting(patient_name)

            # This is their booking submission!
            booking_info = self.extract_booking_details(message_text, patient_name)
            self.set_user_state(sender_phone, "BOOKING_CONFIRMED", booking_info)
            return self._reply_booking_confirmed(booking_info)

        # 4. Check if message is a Booking / Time Confirmation Submission (even if state wasn't set)
        if self.is_booking_submission(text_clean, user_state):
            booking_info = self.extract_booking_details(message_text, patient_name)
            self.set_user_state(sender_phone, "BOOKING_CONFIRMED", booking_info)
            return self._reply_booking_confirmed(booking_info)

        # 5. Intent Detection via Keywords & Regex
        # A. Greeting / Menu
        if re.search(r"^(hi|hello|hey|namaste|vanakkam|good morning|good afternoon|good evening|start|menu|help|info)\b", text_clean):
            self.clear_user_state(sender_phone)
            return self._reply_greeting(patient_name)

        # B. Photo / Image Upload Guidance
        if re.search(r"\b(photo|image|picture|pic|upload|xray|x-ray|scan|smile photo|teeth photo|selfie|send photo)\b", text_clean):
            return self._reply_upload_photo_prompt()

        # C. Reschedule / Cancellation
        if re.search(r"\b(reschedule|postpone|cancel|change slot|change time|cant make it|cannot come|cant come)\b", text_clean):
            self.set_user_state(sender_phone, "WAITING_FOR_BOOKING_DETAILS")
            return self._reply_reschedule()

        # D. Post-Op Care / Home Guidance
        if re.search(r"\b(post[\s\-]?op|after extraction|extraction care|after rct|after whitening|bleeding|soft food|what can i eat)\b", text_clean):
            return self._reply_post_op_care()

        # E. Flexible EMI / Payment Options
        if re.search(r"\b(emi|installments?|payment options?|insurance|google pay|phonepe|paytm|upi|card|cards)\b", text_clean):
            return self._reply_payment_emi()

        # F. Specific Dental Clinical Treatments
        if re.search(r"\b(rct|root canal|crown|cap|caps)\b", text_clean):
            return self._reply_rct()
        if re.search(r"\b(implant|implants|missing tooth|tooth replacement|fixed tooth)\b", text_clean):
            return self._reply_implants()
        if re.search(r"\b(cleaning|scaling|tartar|plaque|polishing)\b", text_clean):
            return self._reply_cleaning()
        if re.search(r"\b(kids?|child|children|pediatric|baby teeth)\b", text_clean):
            return self._reply_pediatric()

        # G. Smile Design / Aesthetics / Veneers / Bonding
        if re.search(r"\b(smile design|veneers|veneer|composite bonding|bonding|gap|gaps|diastema|chipped|cosmetic|makeover|crooked)\b", text_clean):
            return self._reply_smile_design()

        # H. Clear Aligners / Invisible Braces
        if re.search(r"\b(aligner|aligners|invisalign|invisible braces|transparent braces|straightening|braces|clip)\b", text_clean):
            return self._reply_aligners()

        # I. Teeth Whitening
        if re.search(r"\b(whitening|bleaching|yellow|brighten|stains|clean and polish)\b", text_clean):
            return self._reply_whitening()

        # J. Emergency / Tooth Pain / Urgent
        if re.search(r"\b(pain|toothache|ache|swelling|bleeding|severe|emergency|broken tooth|hurt|urgent|accident)\b", text_clean):
            self.set_user_state(sender_phone, "WAITING_FOR_BOOKING_DETAILS")
            return self._reply_emergency()

        # K. Cost / Pricing / Fees
        if re.search(r"\b(cost|price|pricing|charges|fees|how much|rate|estimate|package)\b", text_clean):
            return self._reply_pricing()

        # L. Services / Menu / List
        if re.search(r"\b(services|treatments?|menu|procedures?|list|all treatments)\b", text_clean):
            return self._reply_services_list()

        # M. Location / Address / Directions
        if re.search(r"\b(where|location|address|directions|map|landmark|reach|kamakya|banashankari|kathriguppe)\b", text_clean):
            return self._reply_location()

        # N. Reviews / Ratings
        if re.search(r"\b(review|reviews|rating|ratings|google review|feedback)\b", text_clean):
            return self._reply_reviews()

        # O. Human Desk / Reception
        if re.search(r"\b(call|talk|doctor|receptionist|reception|human|agent|person|desk|contact)\b", text_clean):
            return self._reply_human_desk()

        # P. Appointment Booking General Prompt
        if re.search(r"\b(book|appointment|slot|schedule|timing|visit|consultation|available)\b", text_clean):
            self.set_user_state(sender_phone, "WAITING_FOR_BOOKING_DETAILS")
            return self._reply_booking(patient_name)

        # 6. Fallback: If Gemini API key is configured, use AI clinical response
        if self.gemini_key:
            ai_reply = self._generate_gemini_reply(message_text, patient_name)
            if ai_reply:
                return ai_reply

        # 7. Default Courteous Fallback with Quick Reply Buttons
        return self._reply_fallback(patient_name)

    def generate_image_reply(self, patient_name=None, caption=None, sender_phone=None):
        """Generates a structured reply when a patient sends a photo or document."""
        self.set_user_state(sender_phone, "PHOTO_RECEIVED", {"caption": caption})
        return self._reply_image_received(patient_name, caption)

    def generate_audio_reply(self, patient_name=None, sender_phone=None):
        """Generates a structured reply when a patient sends a voice note."""
        self.set_user_state(sender_phone, "VOICE_NOTE_RECEIVED")
        return {
            "type": "interactive_button",
            "header": "Voice Note Received",
            "body": (
                "🎙️ *Voice Note Received!* 🦷✨\n\n"
                "Thank you! Our clinical team and reception desk have received your audio message and are listening to your note right now.\n\n"
                "We will reply to you shortly. If this is an urgent toothache or you would like to reserve an appointment immediately, you can also tap below!"
            ),
            "footer": "Align and Glow • Dedicated Care",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_photo", "title": "📸 Send Photo"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "audio_received"
        }

    # -------------------------------------------------------------------------
    # Intent Response Builders
    # -------------------------------------------------------------------------
    def _handle_button_reply(self, button_id, patient_name=None, sender_phone=None):
        """Dispatches logic for interactive button taps and list item selections."""
        if button_id in ["btn_book", "btn_urgent"]:
            self.set_user_state(sender_phone, "WAITING_FOR_BOOKING_DETAILS")
            return self._reply_booking(patient_name)

        elif button_id in ["btn_photo", "btn_upload_photo", "list_photo"]:
            return self._reply_upload_photo_prompt()

        elif button_id == "btn_location":
            return self._reply_location()

        elif button_id in ["btn_services", "list_treatments", "explore_services"]:
            return self._reply_services_list()

        elif button_id in ["list_smile_design", "btn_smile_design"]:
            return self._reply_smile_design()

        elif button_id in ["list_aligners", "btn_aligners"]:
            return self._reply_aligners()

        elif button_id in ["list_whitening", "btn_whitening"]:
            return self._reply_whitening()

        elif button_id in ["list_rct", "btn_rct"]:
            return self._reply_rct()

        elif button_id in ["list_implants", "btn_implants"]:
            return self._reply_implants()

        elif button_id in ["list_cleaning", "btn_cleaning"]:
            return self._reply_cleaning()

        elif button_id in ["list_pediatric", "btn_pediatric"]:
            return self._reply_pediatric()

        elif button_id in ["list_emergency", "btn_emergency"]:
            self.set_user_state(sender_phone, "WAITING_FOR_BOOKING_DETAILS")
            return self._reply_emergency()

        elif button_id in ["list_faqs", "btn_faqs"]:
            return self._reply_faqs()

        elif button_id in ["btn_emi", "list_emi"]:
            return self._reply_payment_emi()

        elif button_id in ["btn_reschedule", "list_reschedule"]:
            self.set_user_state(sender_phone, "WAITING_FOR_BOOKING_DETAILS")
            return self._reply_reschedule()

        elif button_id == "btn_review":
            return self._reply_reviews()

        elif button_id == "btn_call":
            return self._reply_human_desk()

        return self._reply_greeting(patient_name)

    def _reply_greeting(self, patient_name=None):
        name_salutation = f" {patient_name}" if patient_name else ""
        return {
            "type": "interactive_button",
            "header": "Align and Glow Dental Clinic",
            "body": (
                f"Hello{name_salutation}! Welcome to *Align and Glow Dental Clinic* 🦷✨\n\n"
                "We provide advanced aesthetic dentistry, clear aligners, smile designing, and comprehensive dental care.\n\n"
                f"🕒 *Hours:* {CLINIC_HOURS}\n"
                "📍 *Location:* Opp. Kamakya Theatre, Banashankari 3rd Stage, Bengaluru\n\n"
                "How can we assist your smile today?"
            ),
            "footer": "Tap an option below for fast assistance",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_services", "title": "🦷 Our Services"}
            ],
            "intent": "greeting"
        }

    def _reply_emergency(self):
        return {
            "type": "interactive_button",
            "header": "Emergency Dental Assistance",
            "body": (
                "🚨 *Immediate Dental Relief Care*\n\n"
                "We understand that dental pain or swelling requires prompt clinical attention. We offer same-day relief appointments.\n\n"
                "💡 *Immediate Care Tips:*\n"
                "• Rinse gently with lukewarm salt water.\n"
                "• Do NOT place aspirin directly against your gums.\n"
                "• Avoid hot, cold, or hard foods on the painful area.\n\n"
                f"🕒 *Hours:* {CLINIC_HOURS}\n"
                f"📍 *Clinic:* {CLINIC_ADDRESS}\n"
                f"📞 *Direct Desk:* {CLINIC_PHONE}\n\n"
                "Please confirm your arrival or tap below to reserve an urgent slot."
            ),
            "footer": "Emergency Care • Daily 9 AM - 9 PM",
            "buttons": [
                {"id": "btn_book", "title": "📅 Urgent Visit"},
                {"id": "btn_photo", "title": "📸 Send Tooth Photo"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "emergency"
        }

    def _reply_smile_design(self):
        return {
            "type": "interactive_button",
            "header": "Aesthetic Smile Designing",
            "body": (
                "✨ *Modern Smile Design & Aesthetic Dentistry*\n\n"
                "At Align and Glow Dental Clinic, smile design is an architectural science customized to your facial symmetry and lip curvature:\n\n"
                "• *Minimal-Prep Porcelain Veneers:* Ultra-thin ceramic facings (0.3–0.5mm) that correct chipped, discolored, or uneven teeth while preserving natural enamel.\n"
                "• *Composite Artistry & Edge Bonding:* Single-sitting micro-contouring for gaps and minor chips with zero tooth reduction.\n"
                "• *Digital 3D Smile Planning:* Visualize your smile simulation before treatment begins.\n\n"
                "Would you like to schedule an assessment or send a photo of your smile?"
            ),
            "footer": "Evidence-Based Aesthetic Excellence",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Assessment"},
                {"id": "btn_photo", "title": "📸 Send Smile Photo"},
                {"id": "btn_location", "title": "📍 Clinic Location"}
            ],
            "intent": "smile_design"
        }

    def _reply_aligners(self):
        return {
            "type": "interactive_button",
            "header": "Clear Aligners & Orthodontics",
            "body": (
                "😁 *Clear Aligners (Invisible Braces)*\n\n"
                "Straighten your teeth comfortably without metal brackets or wires:\n\n"
                "• *Virtually Invisible:* Transparent medical-grade aligners that fit seamlessly over your teeth.\n"
                "• *Removable:* Enjoy your favorite foods and maintain normal brushing and flossing.\n"
                "• *Digitally Planned:* 3D scan maps every tooth movement from day one to your final smile.\n\n"
                "Would you like to check your aligner candidacy? You can send a smile photo or book a 3D scan!"
            ),
            "footer": "Align and Glow • Clear Orthodontics",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Aligner Scan"},
                {"id": "btn_photo", "title": "📸 Send Smile Photo"},
                {"id": "btn_location", "title": "📍 Clinic Location"}
            ],
            "intent": "clear_aligners"
        }

    def _reply_whitening(self):
        return {
            "type": "interactive_button",
            "header": "Cosmetic Teeth Whitening",
            "body": (
                "🌟 *Professional Teeth Whitening*\n\n"
                "Safely brighten your teeth without damaging enamel:\n\n"
                "• *In-Clinic Power Whitening:* Noticeable, radiant shade enhancement in a single 45-minute clinical session.\n"
                "• *Custom Home Kits:* Tailored precision trays made from digital impressions for gradual, lasting brightness.\n"
                "• *Enamel-Safe Formulation:* Eliminates deep tea, coffee, and tobacco stains safely.\n\n"
                "Would you like to send a photo of your teeth for shade evaluation or book a whitening session?"
            ),
            "footer": "Align and Glow • Radiant Smiles",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Whitening"},
                {"id": "btn_photo", "title": "📸 Send Teeth Photo"},
                {"id": "btn_location", "title": "📍 Clinic Location"}
            ],
            "intent": "teeth_whitening"
        }

    def _reply_pricing(self):
        return {
            "type": "interactive_button",
            "header": "Transparent Treatment Pricing",
            "body": (
                "💎 *Pricing & Consultation Transparency*\n\n"
                "At Align and Glow Dental Clinic, we believe in complete clinical transparency with zero hidden charges:\n\n"
                "• Every smile is unique — fees for procedures such as Clear Aligners, Smile Designing (Veneers/Bonding), Implants, or RCT depend on tooth anatomy, material choice, and clinical complexity.\n"
                "• During your initial consultation, we conduct a comprehensive evaluation and provide a transparent, written treatment plan before any work begins.\n"
                "• Convenient payment options and flexible EMI plans are available for comprehensive treatments.\n\n"
                "Would you like to schedule an initial consultation or send a smile photo for an estimate?"
            ),
            "footer": "Align and Glow • Complete Transparency",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Consult"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "pricing"
        }

    def _reply_booking(self, patient_name=None):
        name_salutation = f" {patient_name}" if patient_name else ""
        return {
            "type": "interactive_button",
            "header": "Align and Glow Dental Clinic",
            "body": (
                f"🗓 *Schedule Your Visit{name_salutation}*\n\n"
                f"We look forward to welcoming you to *Align and Glow Dental Clinic*! Our clinic is open *Daily from 9:00 AM to 9:00 PM*.\n\n"
                "Please reply with:\n"
                "1️⃣ *Patient Name*\n"
                "2️⃣ *Preferred Date & Time* (e.g., Tomorrow at 5:00 PM)\n"
                "3️⃣ *Concern / Treatment* (e.g., Smile Design, Aligners, Cleaning, Toothache)\n\n"
                "Our reception desk will confirm your appointment slot immediately! 🦷✨"
            ),
            "footer": "Align and Glow • Daily 9 AM - 9 PM",
            "buttons": [
                {"id": "btn_location", "title": "📍 View Location"},
                {"id": "btn_services", "title": "🦷 Our Services"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "booking"
        }

    def _reply_booking_confirmed(self, booking_info):
        name = booking_info.get("name", "Valued Patient")
        slot = booking_info.get("slot", "Requested Slot")
        concern = booking_info.get("concern", "Dental Consultation")
        is_urgent = booking_info.get("is_urgent", False)

        relief_block = ""
        if is_urgent:
            relief_block = (
                "🚨 *Priority Care Notice:*\n"
                "We have noted your discomfort and marked this booking with *Priority Attention* for prompt relief. "
                "Please rinse with lukewarm salt water and avoid cold or hard foods on the sensitive area.\n\n"
            )

        body = (
            f"✅ *Appointment Request Received!* 🦷✨\n\n"
            f"Thank you, *{name}*! We have registered your consultation request at *Align and Glow Dental Clinic*:\n\n"
            f"📅 *Preferred Slot:* {slot}\n"
            f"🩺 *Reason for Visit:* {concern}\n"
            f"📍 *Clinic:* {CLINIC_ADDRESS}\n"
            f"🕒 *Clinic Hours:* {CLINIC_HOURS}\n\n"
            f"{relief_block}"
            f"🔔 *What Happens Next:*\n"
            f"Our front desk reception has received an instant notification and is checking the chair schedule. "
            f"We will call or message you right away to confirm your exact appointment time!\n\n"
            f"Need urgent confirmation?\n"
            f"📞 *Direct Desk:* {CLINIC_PHONE}"
        )

        return {
            "type": "interactive_button",
            "header": "Align and Glow Dental Clinic",
            "body": body,
            "footer": "Align and Glow • Appointment Desk",
            "buttons": [
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"},
                {"id": "btn_services", "title": "🦷 Our Services"}
            ],
            "intent": "booking_confirmed",
            "booking_info": booking_info
        }

    def _reply_booking_time_prompt(self):
        return {
            "type": "interactive_button",
            "header": "Preferred Time Slot",
            "body": (
                "🗓 *Select Your Preferred Time*\n\n"
                "Align and Glow Dental Clinic is open *Daily from 9:00 AM to 9:00 PM*.\n\n"
                "Please reply with your preferred day and time:\n"
                "👉 e.g. *Today at 5:00 PM* or *Tomorrow 11:30 AM*\n\n"
                "You can also include your name and reason for visit (e.g., Toothache, Smile Design, Cleaning)!"
            ),
            "footer": "Align and Glow • Daily 9 AM - 9 PM",
            "buttons": [
                {"id": "btn_location", "title": "📍 View Location"},
                {"id": "btn_services", "title": "🦷 Our Services"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "booking_prompt_time"
        }

    def _reply_booking_name_prompt(self):
        return {
            "type": "interactive_button",
            "header": "Patient Name",
            "body": (
                "👤 *Patient Name for Appointment*\n\n"
                "Please reply with the patient's full name, preferred time slot (e.g. *Tomorrow at 5 PM*), and concern.\n\n"
                "Our front desk will confirm your appointment slot immediately!"
            ),
            "footer": "Align and Glow • Appointment Desk",
            "buttons": [
                {"id": "btn_location", "title": "📍 View Location"},
                {"id": "btn_services", "title": "🦷 Our Services"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "booking_prompt_name"
        }

    def _reply_booking_concern_prompt(self):
        return {
            "type": "interactive_button",
            "header": "Treatment of Interest",
            "body": (
                "🦷 *Reason for Consultation*\n\n"
                "Please reply with the dental care or aesthetic service you would like to consult on:\n\n"
                "• *Smile Design & Veneers*\n"
                "• *Clear Aligners (Invisible Braces)*\n"
                "• *Teeth Whitening*\n"
                "• *Toothache / Cavity / RCT*\n"
                "• *Cleaning & Scaling*\n\n"
                "Include your preferred time (e.g. *5:00 PM*) and we will confirm your visit!"
            ),
            "footer": "Align and Glow • Appointment Desk",
            "buttons": [
                {"id": "btn_services", "title": "🦷 View All Services"},
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "booking_prompt_concern"
        }

    def _reply_upload_photo_prompt(self):
        return {
            "type": "interactive_button",
            "header": "Virtual Smile & Dental Check",
            "body": (
                "📸 *Virtual Smile & Dental Photo Assessment* 🦷✨\n\n"
                "You can share a clear photo of your teeth or smile right here on WhatsApp!\n\n"
                "💡 *Tips for a Great Photo:*\n"
                "1️⃣ Ensure good, natural lighting on your teeth.\n"
                "2️⃣ Smile naturally showing your front teeth, or take a close-up of any specific tooth of concern (gap, chip, crowding, or pain area).\n"
                "3️⃣ Tap the 📎 (attachment) icon below, choose *Gallery* or *Camera*, and send it across!\n\n"
                "Our clinical team will review your photo for Aligner suitability, Smile Design options, or urgent relief care."
            ),
            "footer": "Align and Glow • Virtual Smile Check",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "photo_upload_prompt"
        }

    def _reply_image_received(self, patient_name=None, caption=None):
        name_salutation = f", *{patient_name}*" if patient_name and patient_name.lower() not in ["patient", "valued patient", "dr anu", "align and glow"] else ""
        caption_ack = f"\n💬 *Your note:* \"{caption}\"\n" if caption else "\n"
        return {
            "type": "interactive_button",
            "header": "Photo Received for Review",
            "body": (
                f"📸 *Smile & Dental Photo Received!* 🦷✨\n\n"
                f"Thank you{name_salutation}! We have securely received your image for clinical evaluation.{caption_ack}\n"
                "🔍 *Our Clinical Team is Reviewing For:*\n"
                "• Smile symmetry & Clear Aligner candidacy\n"
                "• Aesthetic options (Porcelain Veneers, Bonding, Whitening)\n"
                "• Any visible chipping, wear, discoloration, or areas needing care\n\n"
                "🔔 *Next Step:*\n"
                "Our reception team has been notified with your photo and will reply shortly. "
                "For a complete 3D digital diagnosis, we invite you to an in-clinic consultation!\n\n"
                f"📞 *Direct Clinic Desk:* {CLINIC_PHONE}"
            ),
            "footer": "Align and Glow • Smile Assessment",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "image_received"
        }

    def _reply_location(self):
        return {
            "type": "interactive_button",
            "header": "Clinic Location & Directions",
            "body": (
                "📍 *Align and Glow Dental Clinic*\n\n"
                f"🏢 *Address:* {CLINIC_ADDRESS}\n\n"
                "🏛 *Landmark:* Directly opposite Kamakya Theatre (Kathriguppe Cross)\n"
                f"🕒 *Timings:* {CLINIC_HOURS}\n"
                f"📞 *Phone / WhatsApp:* {CLINIC_PHONE}\n\n"
                f"🗺 *Google Maps Link:*\n{GOOGLE_MAPS_LINK}"
            ),
            "footer": "Banashankari 3rd Stage, Bengaluru",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_review", "title": "⭐ Google Reviews"}
            ],
            "intent": "location"
        }

    def _reply_reviews(self):
        return {
            "type": "interactive_button",
            "header": "Patient Reviews & Testimonials",
            "body": (
                "⭐ *Patient Reviews & Feedback*\n\n"
                "We take great pride in delivering gentle, evidence-based aesthetic dental care for families across Bengaluru.\n\n"
                "To read our 5-star verified patient reviews or share your feedback:\n\n"
                f"👉 *Google Reviews:* {GOOGLE_REVIEW_LINK}\n\n"
                "Thank you for trusting Align and Glow Dental Clinic!"
            ),
            "footer": "Align and Glow Dental Clinic",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_services", "title": "🦷 Our Services"}
            ],
            "intent": "reviews"
        }

    def _reply_human_desk(self):
        return {
            "type": "interactive_button",
            "header": "Clinic Front Desk Support",
            "body": (
                "📞 *Connect with Front Desk Reception*\n\n"
                "Our front desk reception team is available daily from 9:00 AM to 9:00 PM.\n\n"
                f"📱 *Direct Line / WhatsApp:* {CLINIC_PHONE}\n"
                f"📍 *Clinic:* {CLINIC_ADDRESS}\n\n"
                "A member of our clinic team has been notified and will reply to your message momentarily."
            ),
            "footer": "Align and Glow • Front Desk",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_services", "title": "🦷 Our Services"}
            ],
            "intent": "human_desk"
        }

    def _reply_fallback(self, patient_name=None):
        name_salutation = f" {patient_name}" if patient_name else ""
        return {
            "type": "interactive_button",
            "header": "Align and Glow Dental Clinic",
            "body": (
                f"Thank you for reaching out to *Align and Glow Dental Clinic*{name_salutation}! 🦷✨\n\n"
                "We provide advanced aesthetic smile design, clear aligners, precision restorations, and general dental care.\n\n"
                f"🕒 *Hours:* {CLINIC_HOURS}\n"
                "📍 *Location:* Opp. Kamakya Theatre, Banashankari 3rd Stage, Bengaluru\n\n"
                "Please choose an option below or type your query, and our team will be delighted to help."
            ),
            "footer": "Tap an option below",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_services", "title": "🦷 Our Services"}
            ],
            "intent": "fallback"
        }

    def _reply_services_list(self):
        return {
            "type": "interactive_list",
            "header": "Align and Glow Dental Clinic",
            "body": (
                "🦷 *Advanced Dental & Aesthetic Services*\n\n"
                "Welcome to *Align and Glow Dental Clinic*! We offer comprehensive, evidence-based aesthetic and restorative dental solutions.\n\n"
                "Tap below to browse our specialized treatments, smile simulations, and virtual assessment options:"
            ),
            "footer": "Open Daily 9:00 AM – 9:00 PM",
            "button_label": "Explore Services",
            "sections": [
                {
                    "title": "Aesthetic Dentistry",
                    "rows": [
                        {
                            "id": "list_smile_design",
                            "title": "Smile Design & Veneers",
                            "description": "Porcelain veneers, edge bonding & gap closure"
                        },
                        {
                            "id": "list_aligners",
                            "title": "Clear Aligners",
                            "description": "Custom invisible braces for teeth alignment"
                        },
                        {
                            "id": "list_whitening",
                            "title": "Teeth Whitening",
                            "description": "Instant 45-min enamel-safe shade brightening"
                        }
                    ]
                },
                {
                    "title": "Clinical Treatments",
                    "rows": [
                        {
                            "id": "list_rct",
                            "title": "Painless RCT & Crowns",
                            "description": "Single-sitting root canal & ceramic caps"
                        },
                        {
                            "id": "list_implants",
                            "title": "Dental Implants",
                            "description": "Permanent natural tooth replacement"
                        },
                        {
                            "id": "list_cleaning",
                            "title": "Scaling & Polishing",
                            "description": "Deep ultrasonic tartar & stain cleaning"
                        },
                        {
                            "id": "list_pediatric",
                            "title": "Kids Dentistry",
                            "description": "Gentle cavity prevention & pediatric care"
                        }
                    ]
                },
                {
                    "title": "Assessment & FAQs",
                    "rows": [
                        {
                            "id": "list_photo",
                            "title": "Photo Assessment",
                            "description": "Upload smile photo for preliminary review"
                        },
                        {
                            "id": "list_emergency",
                            "title": "Urgent Pain Relief",
                            "description": "Same-day priority slot for acute toothache"
                        },
                        {
                            "id": "list_faqs",
                            "title": "Post-Op & Clinic FAQs",
                            "description": "Recovery tips, 0% EMI plans & payment modes"
                        }
                    ]
                }
            ],
            "intent": "services_list"
        }

    def _reply_rct(self):
        return {
            "type": "interactive_button",
            "header": "Microscopic RCT & Crowns",
            "body": (
                "🔬 *Precision Root Canal Treatment & Ceramic Crowns*\n\n"
                "Save your natural infected tooth comfortably with advanced micro-endodontics:\n\n"
                "• *Painless Single-Sitting RCT:* Computer-controlled rotary instrumentation for maximum precision and rapid healing.\n"
                "• *Custom Zirconia / All-Ceramic Crowns:* Digitally milled caps designed for long-lasting chewing strength and lifelike appearance.\n"
                "• *Emergency Relief:* Immediate treatment for deep decay, severe throbbing pain, or dental trauma.\n\n"
                "Would you like to reserve a consultation or send a tooth photo/X-ray?"
            ),
            "footer": "Align and Glow • Micro-Endodontics",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book RCT Slot"},
                {"id": "btn_photo", "title": "📸 Send Tooth Photo"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "rct_treatment"
        }

    def _reply_implants(self):
        return {
            "type": "interactive_button",
            "header": "Permanent Dental Implants",
            "body": (
                "🔩 *Permanent Dental Implants & Tooth Replacement*\n\n"
                "Restore missing teeth with the gold-standard in modern restorative dentistry:\n\n"
                "• *Natural Look & Feel:* Medical-grade titanium roots that fuse seamlessly with the jawbone without trimming adjacent teeth.\n"
                "• *Full Chewing Power:* Eat all your favorite foods with zero slipping or discomfort.\n"
                "• *Bone Preservation:* Prevents premature facial aging and bone resorption.\n\n"
                "Would you like to check your implant candidacy or book an evaluation?"
            ),
            "footer": "Align and Glow • Dental Implants",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Assessment"},
                {"id": "btn_photo", "title": "📸 Send Smile Photo"},
                {"id": "btn_location", "title": "📍 Clinic Location"}
            ],
            "intent": "implants"
        }

    def _reply_cleaning(self):
        return {
            "type": "interactive_button",
            "header": "Preventive Care & Polishing",
            "body": (
                "🛡️ *Ultrasonic Scaling, Tartar Removal & Air Polishing*\n\n"
                "Maintain healthy gums, prevent bone loss, and eliminate stubborn food stains:\n\n"
                "• *Gentle Ultrasonic Scaling:* Effortlessly removes hard calculus without scraping tooth enamel.\n"
                "• *Air-Flow Stain Removal:* Erases tea, coffee, and nicotine discoloration for an instantly refreshed smile.\n"
                "• *Fresh Breath & Gum Health:* Prevents bleeding gums and gingivitis.\n\n"
                "Would you like to schedule a 30-minute cleaning session?"
            ),
            "footer": "Align and Glow • Preventive Care",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Cleaning"},
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "cleaning_scaling"
        }

    def _reply_pediatric(self):
        return {
            "type": "interactive_button",
            "header": "Pediatric Dental Care",
            "body": (
                "👶 *Gentle Pediatric & Kids Dental Care*\n\n"
                "Creating positive, fearless dental experiences for children:\n\n"
                "• *Painless Cavity Prevention:* Fluoride varnish application & protective pit/fissure sealants.\n"
                "• *Gentle Fillings & Pulp Therapy:* Designed specially for developing baby and permanent teeth.\n"
                "• *Habit Correction:* Preventive guidance for thumb-sucking, mouth breathing, and early spacing.\n\n"
                "Would you like to book a comfortable check-up for your child?"
            ),
            "footer": "Align and Glow • Gentle Kids Dentistry",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Kids Visit"},
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "pediatric_dentistry"
        }

    def _reply_post_op_care(self):
        return {
            "type": "interactive_button",
            "header": "Post-Procedure Home Care",
            "body": (
                "📋 *Clinical Post-Treatment Home Care Guidance*\n\n"
                "Please follow these instructions to ensure rapid, comfortable healing:\n\n"
                "1️⃣ *Gauze Pressure:* Keep the cotton gauze pad pressed firmly for 45 minutes. Swallow saliva normally — do NOT spit.\n"
                "2️⃣ *First 24 Hours:* Absolutely no spitting, vigorous rinsing, or drinking with a straw (to protect blood clot formation).\n"
                "3️⃣ *Diet:* Eat soft, cold foods (ice cream, yogurt, curd rice, smoothies). Avoid hot, hard, or spicy foods.\n"
                "4️⃣ *After 24 Hours:* Rinse gently with warm salt water (1/2 tsp salt in warm water) 3–4 times daily.\n"
                "5️⃣ *Medications:* Take all prescribed painkillers and antibiotics as advised.\n\n"
                "If you experience unusual swelling or prolonged bleeding, contact our desk immediately!"
            ),
            "footer": "Align and Glow • Patient Recovery Support",
            "buttons": [
                {"id": "btn_call", "title": "📞 Call Reception"},
                {"id": "btn_book", "title": "📅 Follow-Up Visit"},
                {"id": "btn_location", "title": "📍 Clinic Location"}
            ],
            "intent": "post_op_care"
        }

    def _reply_payment_emi(self):
        return {
            "type": "interactive_button",
            "header": "0% EMI & Payment Options",
            "body": (
                "💳 *Flexible Payment & 0% EMI Plans*\n\n"
                "We make world-class aesthetic and clinical dentistry accessible with transparent payment options:\n\n"
                "• *Accepted Modes:* UPI (Google Pay, PhonePe, Paytm), Debit/Credit Cards, Net Banking & Cash.\n"
                "• *0% Interest EMI:* Flexible 3, 6, 9 & 12-month installment plans available for Clear Aligners, Porcelain Veneers, Full Smile Design, and Dental Implants.\n"
                "• *Zero Hidden Costs:* You receive a written itemized estimate before any procedure begins.\n\n"
                "Would you like to book a consultation to discuss your personalized treatment plan?"
            ),
            "footer": "Align and Glow • Transparent Healthcare",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Consult"},
                {"id": "btn_photo", "title": "📸 Photo Assessment"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "payment_emi"
        }

    def _reply_reschedule(self):
        return {
            "type": "interactive_button",
            "header": "Reschedule Appointment",
            "body": (
                "🗓️ *Appointment Rescheduling Assistance*\n\n"
                "No worries at all! We completely understand schedules can change.\n\n"
                "Please reply with your updated preferred date & time:\n"
                "👉 Example: *\"Reschedule for Tomorrow at 6:00 PM\"*\n\n"
                "Our front desk will update your slot and send an immediate confirmation! 🦷✨"
            ),
            "footer": "Align and Glow • Open Daily 9 AM - 9 PM",
            "buttons": [
                {"id": "btn_book", "title": "📅 Confirm New Slot"},
                {"id": "btn_location", "title": "📍 Clinic Location"},
                {"id": "btn_call", "title": "📞 Call Desk"}
            ],
            "intent": "reschedule_request"
        }

    def _reply_faqs(self):
        return {
            "type": "interactive_button",
            "header": "Frequently Asked Questions",
            "body": (
                "💡 *Align and Glow Dental Clinic FAQs*\n\n"
                f"🕒 *Timings:* Open Daily 9:00 AM – 9:00 PM (Monday to Sunday).\n"
                f"📍 *Location:* {CLINIC_ADDRESS}\n"
                "🚗 *Parking:* Ample dedicated car & two-wheeler parking available.\n"
                "🛡️ *Sterilization:* 100% Class-B hospital-grade autoclave sterilization for utmost patient safety.\n"
                "💳 *Payments:* UPI, Cards, Cash & 0% EMI available on comprehensive treatments.\n\n"
                "How else may our team assist your smile today?"
            ),
            "footer": "Align and Glow Dental Clinic",
            "buttons": [
                {"id": "btn_book", "title": "📅 Book Visit"},
                {"id": "btn_emi", "title": "💳 View EMI Plans"},
                {"id": "btn_services", "title": "🦷 Our Services"}
            ],
            "intent": "faqs"
        }

    # -------------------------------------------------------------------------
    # Optional Gemini AI Assistant Integration
    # -------------------------------------------------------------------------
    def _generate_gemini_reply(self, user_prompt, patient_name=None):
        """
        Uses Gemini REST API to craft an intelligent clinical response
        strictly adhering to clinic rules and boundaries.
        """
        if not self.gemini_key:
            return None

        system_instruction = (
            "You are the virtual clinical receptionist for Align and Glow Dental Clinic, "
            "an advanced aesthetic and dental clinic located in Banashankari 3rd Stage, Bengaluru.\n"
            "STRICT GUIDELINES:\n"
            "1. NEVER mention any personal doctor names (no Dr. B Anuja or any specific doctor name). "
            "Refer to the clinic as 'Align and Glow Dental Clinic' or 'our clinical team'.\n"
            "2. Keep the tone professional, warm, empathetic, and evidence-based.\n"
            "3. Emphasize aesthetic dentistry, clear aligners, minimal-prep smile design, and gentle care.\n"
            "4. Provide helpful clinical information, but always advise that an in-person clinical examination "
            "is necessary for an accurate diagnosis and treatment plan.\n"
            "5. Clinic Hours: Open Daily 9:00 AM – 9:00 PM. Address: Opp. Kamakya Theatre, Banashankari 3rd Stage.\n"
            "6. Phone: +91 97402 75502.\n"
            "7. Keep responses concise, structured, and easy to read on WhatsApp (under 160 words). Use bullet points and WhatsApp bold (*text*)."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"
        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "parts": [{"text": f"Patient question: {user_prompt}"}]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 300
            }
        }

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if content:
                        return {
                            "type": "interactive_button",
                            "header": "Align and Glow Dental Clinic",
                            "body": content,
                            "footer": "Align and Glow • Daily 9 AM - 9 PM",
                            "buttons": [
                                {"id": "btn_book", "title": "📅 Book Visit"},
                                {"id": "btn_location", "title": "📍 Clinic Location"},
                                {"id": "btn_services", "title": "🦷 Our Services"}
                            ],
                            "intent": "gemini_ai"
                        }
        except Exception as e:
            # Fallback smoothly to rule-based engine if Gemini fails
            pass
        return None
