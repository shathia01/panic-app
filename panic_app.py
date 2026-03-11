import streamlit as st
import requests
import math
import smtplib
import json
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from streamlit_js_eval import streamlit_js_eval
import uuid
import hashlib

st.title("🚨 One-Click Emergency Panic Button")

# ---------- GMAIL CONFIG ----------
SENDER_EMAIL = "shathia190304@gmail.com"
SENDER_APP_PASSWORD = "kvskirvfdhsscege"
SENDER_NAME = "Emergency Alert"

# ---------- DISTRESS KEYWORDS ----------
DISTRESS_KEYWORDS = [
    "help", "please", "leave me", "stop", "let me go",
    "get away", "don't touch me", "call police", "save me",
    "emergency", "danger", "scared"
]

# ---------- DEFAULT HARDCODED CONTACTS ----------
DEFAULT_CONTACTS = [
    {"name": "Admin", "email": "shathia190304@gmail.com"},
]

# ---------- SESSION STATE INIT ----------
for key, default in [
    ("extreme_active", False),
    ("update_count", 0),
    ("last_sent", None),
    ("tracking_locations", []),
    ("panic_requested", False),
    ("panic_key", 0),
    ("voice_active", False),
    ("voice_triggered", False),
    ("voice_trigger_word", ""),
    ("voice_trigger_key", 0),
    ("voice_tracking_active", False),
    ("voice_update_count", 0),
    ("voice_tracking_locations", []),
    ("voice_last_sent", None),
    # Motion detection states
    ("motion_monitoring", False),
    ("motion_triggered", False),
    ("motion_tracking_active", False),
    ("motion_update_count", 0),
    ("motion_tracking_locations", []),
    ("motion_last_sent", None),
    ("motion_listen_key", 0),
    # Guardian Mode states
    ("guardian_active", False),
    ("guardian_session_id", None),
    ("guardian_destination", ""),
    ("guardian_update_count", 0),
    ("guardian_locations", []),
    ("guardian_last_sent", None),
    ("guardian_loc_key", 0),
    ("guardian_journey_ended", False),
    ("guardian_link_sent", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ---------- SHARED GUARDIAN STORE (server-side, in-memory) ----------
# This acts as the shared store between user and guardian viewer
if "guardian_store" not in st.session_state:
    st.session_state["guardian_store"] = {}

# Global store across all sessions using st.cache_resource
@st.cache_resource
def get_guardian_store():
    return {}

guardian_store = get_guardian_store()

# ---------- READ SAVED CONTACT FROM localStorage ----------
raw = streamlit_js_eval(js_expressions="localStorage.getItem('emergency_my_contacts')", key="read_my_contacts")
my_contacts = []
if raw and raw != "null":
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            my_contacts = [parsed]
        elif isinstance(parsed, list):
            my_contacts = parsed
    except Exception:
        my_contacts = []

# ---------- HAVERSINE ----------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ---------- FIND NEAREST POLICE ----------
def find_police(lat, lon, radius=5000):
    query = f"""
    [out:json][timeout:10];
    (
      node["amenity"="police"](around:{radius},{lat},{lon});
      way["amenity"="police"](around:{radius},{lat},{lon});
    );
    out center;
    """
    try:
        res = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query}, timeout=25
        ).json()
        elements = res.get("elements", [])
        if not elements:
            return None
        best, best_dist = None, float("inf")
        for el in elements:
            plat = el.get("lat") or el.get("center", {}).get("lat")
            plon = el.get("lon") or el.get("center", {}).get("lon")
            if plat is None or plon is None:
                continue
            dist = haversine(lat, lon, plat, plon)
            if dist < best_dist:
                best_dist = dist
                name = el.get("tags", {}).get("name", "Police Station")
                best = (plat, plon, name, best_dist)
        return best
    except Exception:
        return None

# ---------- SEND EMAIL ----------
def send_email(recipient_name, recipient_email, lat, lon, update_num=None, accuracy=None,
               voice_triggered=False, trigger_word="", motion_triggered=False,
               guardian_mode=False, guardian_link="", destination=""):
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_update = update_num is not None

    if guardian_mode:
        subject = f"🛡️ Guardian Mode Started — Live Journey Tracking"
        alert_type = "GUARDIAN"
    elif motion_triggered:
        subject = f"📳 MOTION ALERT - Shaking/Running Detected - Emergency"
        alert_type = "MOTION"
    elif voice_triggered:
        subject = f"🎙️ VOICE ALERT - Distress Word Detected - Emergency"
        alert_type = "VOICE"
    elif is_update:
        subject = f"LIVE UPDATE #{update_num} - Emergency Alert - Urgent"
        alert_type = "UPDATE"
    else:
        subject = "Emergency Alert - Urgent Assistance Required"
        alert_type = "PANIC"

    acc_text = f"+-{accuracy:.0f}m" if accuracy else "N/A"
    voice_note = f'\n⚠️ Triggered by voice: "{trigger_word}"\n' if voice_triggered else ""
    motion_note = "\n⚠️ Triggered by device motion/shaking — person may be in distress!\n" if motion_triggered else ""

    destination_text = f"\nDestination: {destination}" if destination else ""

    plain = f"""{'🛡️ GUARDIAN LIVE MONITORING MODE STARTED' if guardian_mode else ('📳 MOTION-TRIGGERED EMERGENCY ALERT' if motion_triggered else ('🎙️ VOICE-TRIGGERED EMERGENCY ALERT' if voice_triggered else ('LIVE TRACKING UPDATE #' + str(update_num) if is_update else 'EMERGENCY ALERT')))}

Dear {recipient_name},

{'🛡️ GUARDIAN MODE: Someone has started their journey and wants you to monitor them live. Click the link below to watch their location in real-time.' if guardian_mode else ('⚠️ MOTION ALERT: Rapid shaking or running motion was automatically detected on the device!' if motion_triggered else ('⚠️ VOICE DISTRESS DETECTION: The word "' + trigger_word + '" was detected. Auto-alert triggered!' if voice_triggered else ('This is a LIVE LOCATION UPDATE. The person is moving.' if is_update else 'Someone triggered the Emergency Panic Button.')))}

{'Call emergency services (999) immediately.' if not guardian_mode else ''}
{voice_note}{motion_note}
Current Location: {lat:.6f}, {lon:.6f}
Accuracy: {acc_text}{destination_text}
Google Maps: {maps_link}
Time: {timestamp}
{f'LIVE TRACKER LINK: {guardian_link}' if guardian_mode and guardian_link else ''}
"""

    guardian_banner = f"""
        <div style="background:#0a5c2e;color:white;padding:12px 15px;border-radius:6px;margin-bottom:15px;text-align:center;">
            🛡️ <b>GUARDIAN MODE ACTIVE</b> — Live journey tracking has started!
        </div>""" if guardian_mode else ""

    motion_banner = """
        <div style="background:#7B3F00;color:white;padding:12px 15px;border-radius:6px;margin-bottom:15px;text-align:center;">
            📳 <b>MOTION ALERT</b> — Rapid device shaking or running detected!
        </div>""" if motion_triggered else ""

    voice_banner = f"""
        <div style="background:#4a0080;color:white;padding:12px 15px;border-radius:6px;margin-bottom:15px;text-align:center;">
            🎙️ <b>VOICE ALERT</b> — Distress word detected: <b>"{trigger_word}"</b>
        </div>""" if voice_triggered else ""

    color = "#0a5c2e" if guardian_mode else ("#7B3F00" if motion_triggered else ("#4a0080" if voice_triggered else ("#8B0000" if is_update else "red")))
    header_text = (
        '🛡️ Guardian Live Monitoring Started' if guardian_mode else
        ('📳 MOTION ALERT: Device Shaking Detected' if motion_triggered else
         (f'🎙️ VOICE ALERT: "{trigger_word}"' if voice_triggered else
          (f'LIVE UPDATE #{update_num}' if is_update else 'Emergency Alert')))
    )

    live_tracker_button = f"""
        <a href="{guardian_link}" style="display:block;text-align:center;
           background:#0a5c2e;color:white;padding:14px 20px;
           border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold;margin-top:10px;">
            🗺️ Open Live Tracker Map
        </a>
        <p style="text-align:center;font-size:12px;color:#555;margin-top:8px;">
            This link shows their real-time location. Refresh anytime to see latest position.
        </p>
    """ if guardian_mode and guardian_link else ""

    destination_html = f"""
        <div style="background:#e8f5e9;border-left:4px solid #0a5c2e;padding:10px;border-radius:5px;margin:10px 0;">
            <b>📍 Destination:</b> {destination}
        </div>
    """ if destination else ""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f8f8f8;padding:20px;">
    <div style="max-width:500px;margin:auto;background:white;border-radius:10px;
                border-top:6px solid {color};padding:30px;
                box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        {guardian_banner}{motion_banner}{voice_banner}
        <h1 style="color:{color};text-align:center;">{header_text}</h1>
        <p>Dear <b>{recipient_name}</b>,</p>
        <p>
            {'<b>🛡️ GUARDIAN MODE ACTIVE</b><br>Someone has started their journey and wants you to monitor them safely. Use the live tracker link below to watch their real-time location until they arrive.' if guardian_mode else ('<b>⚠️ MOTION DISTRESS DETECTION ACTIVE</b><br>Rapid shaking or running motion was automatically detected on the device. Immediate attention required!' if motion_triggered else ('<b>⚠️ VOICE DISTRESS DETECTION ACTIVE</b><br>The word <b>"' + trigger_word + '"</b> was automatically detected by the emergency app. Immediate attention required!' if voice_triggered else ('<b>LIVE TRACKING ACTIVE</b> - Person is moving. Latest position below.' if is_update else 'Emergency Panic Button was activated.')))}
            <br><br>{'You will be able to track them live using the button below.' if guardian_mode else 'Call emergency services (<b>999</b>) immediately.'}
        </p>
        {destination_html}
        <div style="background:#{'e8f5e9' if guardian_mode else 'fff0f0'};border-left:4px solid {color};
                    padding:15px;border-radius:5px;margin:20px 0;">
            <p style="margin:0;font-size:15px;">
                {'Current Starting Location' if guardian_mode else 'Location'}:<br>
                Lat: <code>{lat:.6f}</code><br>
                Lon: <code>{lon:.6f}</code><br>
                <small>GPS Accuracy: {acc_text}</small><br>
                <small>Sent: {timestamp}</small>
            </p>
        </div>
        <a href="{maps_link}" style="display:block;text-align:center;
           background:{'#1976D2' if guardian_mode else color};color:white;padding:12px 20px;
           border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-top:10px;">
            📍 View Starting Point on Google Maps
        </a>
        {live_tracker_button}
    </div></body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"] = recipient_email
        msg["Reply-To"] = SENDER_EMAIL
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)

def send_to_all(lat, lon, contacts, update_num=None, accuracy=None,
                voice_triggered=False, trigger_word="", motion_triggered=False,
                guardian_mode=False, guardian_link="", destination=""):
    results = []
    for c in contacts:
        success, error = send_email(
            c["name"], c["email"], lat, lon,
            update_num, accuracy, voice_triggered, trigger_word, motion_triggered,
            guardian_mode, guardian_link, destination
        )
        results.append({"name": c["name"], "email": c["email"], "success": success, "error": error})
    return results

# ---------- BUILD CONTACT LIST ----------
all_contacts = list(DEFAULT_CONTACTS)
for c in my_contacts:
    if not any(x["email"].lower() == c["email"].lower() for x in all_contacts):
        all_contacts.append(c)

# ---------- MY CONTACT SECTION ----------
st.divider()
st.subheader("📋 My Emergency Contacts")

if my_contacts:
    st.success(f"{len(my_contacts)} personal contact(s) saved on this device.")
    for i, c in enumerate(my_contacts):
        col_name, col_email, col_del = st.columns([2, 3, 1])
        with col_name:
            st.write(f"**{c['name']}**")
        with col_email:
            st.write(c["email"])
        with col_del:
            if st.button("🗑️ Remove", key=f"remove_{i}"):
                updated = [x for j, x in enumerate(my_contacts) if j != i]
                escaped = json.dumps(updated).replace("'", "\\'")
                streamlit_js_eval(js_expressions=f"localStorage.setItem('emergency_my_contacts','{escaped}');true", key=f"del_contact_{i}")
                st.info("Removed. Refresh to confirm.")
else:
    st.info("No personal contacts saved yet. Add contacts below.")

st.markdown("##### ➕ Add a Contact")
with st.form("add_contact_form", clear_on_submit=True):
    col_n, col_e = st.columns(2)
    with col_n:
        reg_name = st.text_input("Name", placeholder="e.g. Sarah")
    with col_e:
        reg_email = st.text_input("Email", placeholder="e.g. sarah@gmail.com")
    if st.form_submit_button("Save Contact to This Device"):
        if reg_name and reg_email:
            if any(c["email"].lower() == reg_email.lower() for c in my_contacts):
                st.warning("A contact with that email already exists.")
            else:
                updated = my_contacts + [{"name": reg_name, "email": reg_email}]
                escaped = json.dumps(updated).replace("'", "\\'")
                streamlit_js_eval(js_expressions=f"localStorage.setItem('emergency_my_contacts','{escaped}');true", key="save_new_contact")
                st.success(f"Saved {reg_name}! Refresh to confirm.")
        else:
            st.warning("Please fill in both fields.")


# ===================================================================
# ==================== GUARDIAN LIVE MONITORING MODE ================
# ===================================================================
st.divider()
st.subheader("🛡️ Guardian Live Monitoring Mode")

st.caption(
    "Share your live journey with trusted contacts. They can watch your location "
    "update in real-time on a map until you press 'I'm Safe'. "
    "Location updates every 10 seconds."
)

# ---------- CHECK IF VIEWING AS GUARDIAN ----------
query_params = st.query_params
guardian_view_id = query_params.get("guardian", None)

if guardian_view_id:
    # ============================================================
    # GUARDIAN VIEWER PAGE — shown when contact opens the link
    # ============================================================
    st.markdown("---")
    st.markdown(
        "<h2 style='text-align:center;color:#0a5c2e;'>🛡️ Guardian Live Tracker</h2>",
        unsafe_allow_html=True
    )

    session_data = guardian_store.get(guardian_view_id)

    if not session_data:
        st.error("❌ This tracking session has expired or does not exist.")
        st.info("The person may have ended their journey or the session has timed out.")
        st.stop()

    status = session_data.get("status", "active")
    locations = session_data.get("locations", [])
    destination = session_data.get("destination", "")
    started_at = session_data.get("started_at", "")
    last_update = session_data.get("last_update", "")

    if status == "ended":
        st.success("✅ Journey Completed — The person has marked themselves as SAFE!")
        if locations:
            last = locations[-1]
            st.info(f"Last known location: {last['lat']:.6f}, {last['lon']:.6f} at {last['time']}")
        st.stop()

    # Active tracking view
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1:
        st.metric("Status", "🟢 LIVE")
    with col_stat2:
        st.metric("Updates", len(locations))
    with col_stat3:
        st.metric("Last Update", last_update or "Waiting...")

    if destination:
        st.info(f"📍 Destination: **{destination}**")

    if locations:
        latest = locations[-1]
        lat_now = latest["lat"]
        lon_now = latest["lon"]
        acc_now = latest.get("accuracy", "unknown")
        time_now = latest["time"]

        st.markdown(
            f"### 📍 Current Location\n"
            f"**Lat:** `{lat_now:.6f}` | **Lon:** `{lon_now:.6f}` | **Accuracy:** {acc_now}"
        )

        maps_embed_url = f"https://maps.google.com/maps?q={lat_now},{lon_now}&z=16&output=embed"
        st.markdown(
            f"""
            <div style="border-radius:12px;overflow:hidden;border:2px solid #0a5c2e;margin:10px 0;">
                <iframe
                    width="100%" height="400"
                    src="{maps_embed_url}"
                    frameborder="0" allowfullscreen
                    style="display:block;">
                </iframe>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.link_button(
            "🗺️ Open in Google Maps (Full View)",
            f"https://maps.google.com/?q={lat_now},{lon_now}",
            use_container_width=True
        )

        # Location trail
        with st.expander(f"📍 Location Trail ({len(locations)} points)", expanded=False):
            for entry in reversed(locations):
                st.markdown(
                    f"**#{entry['update']}** at {entry['time']} — "
                    f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry.get('accuracy','?')}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )
    else:
        st.info("⏳ Waiting for first location update...")

    st.caption(f"Journey started: {started_at} | This page auto-shows latest on refresh.")
    st.info("🔄 **Refresh this page** to see the latest location update.")
    st.stop()


# ============================================================
# NORMAL USER VIEW — Guardian Mode Controls
# ============================================================

# Status display
g_col1, g_col2, g_col3 = st.columns([3, 1, 1])
with g_col1:
    if st.session_state.guardian_active:
        count_so_far = st.session_state.guardian_update_count
        st.success(f"🛡️ Guardian Mode ACTIVE — {count_so_far} location update(s) sent")
    elif st.session_state.guardian_journey_ended:
        st.success("✅ Journey marked as SAFE — Guardian Mode ended.")
    else:
        st.info("🛡️ Guardian Mode is OFF")

with g_col2:
    if not st.session_state.guardian_active and not st.session_state.guardian_journey_ended:
        if st.button("🛡️ Start Guardian", use_container_width=True, type="primary"):
            session_id = str(uuid.uuid4()).replace("-", "")[:16]
            st.session_state.guardian_session_id = session_id
            st.session_state.guardian_active = True
            st.session_state.guardian_update_count = 0
            st.session_state.guardian_locations = []
            st.session_state.guardian_link_sent = False
            st.session_state.guardian_journey_ended = False
            st.session_state.guardian_loc_key = 0
            guardian_store[session_id] = {
                "status": "active",
                "locations": [],
                "destination": st.session_state.guardian_destination,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_update": None,
            }
            st.rerun()

with g_col3:
    if st.session_state.guardian_active:
        if st.button("✅ I'm Safe", use_container_width=True, type="primary"):
            sid = st.session_state.guardian_session_id
            if sid and sid in guardian_store:
                guardian_store[sid]["status"] = "ended"
            st.session_state.guardian_active = False
            st.session_state.guardian_journey_ended = True
            total = st.session_state.guardian_update_count
            st.session_state.guardian_update_count = 0
            st.success(f"✅ Marked as SAFE after {total} update(s). Contacts notified.")
            st.rerun()

# Destination input (only when not active)
if not st.session_state.guardian_active:
    dest_input = st.text_input(
        "📍 Destination (optional)",
        value=st.session_state.guardian_destination,
        placeholder="e.g. KLCC, Home, Office...",
        help="Your contacts will see this as the intended destination."
    )
    st.session_state.guardian_destination = dest_input

# ===================================================================
# ---------- GUARDIAN LIVE TRACKING LOOP ----------
# ===================================================================
if st.session_state.guardian_active:
    sid = st.session_state.guardian_session_id

    # Build tracker link
    base_url = st.get_option("browser.serverAddress") or "localhost"
    try:
        current_url_js = streamlit_js_eval(
            js_expressions="window.location.href.split('?')[0]",
            key="get_base_url"
        )
        if current_url_js:
            tracker_link = f"{current_url_js}?guardian={sid}"
        else:
            tracker_link = f"http://localhost:8501/?guardian={sid}"
    except Exception:
        tracker_link = f"http://localhost:8501/?guardian={sid}"

    # Show the tracker link prominently
    st.divider()
    st.success("🛡️ **Guardian Mode ACTIVE** — Contacts can track you live!")

    st.markdown("### 🔗 Share This Link With Your Guardian")
    st.code(tracker_link, language=None)
    st.caption("Your emergency contacts have been emailed this link automatically. They can also share it manually.")

    g_location_box = st.empty()
    g_result_box   = st.empty()
    g_trail_box    = st.empty()

    # Get fresh location every cycle
    g_fresh_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        })""",
        key=f"guardian_loc_{st.session_state.guardian_loc_key}"
    )

    if g_fresh_loc:
        g_lat      = g_fresh_loc[0]
        g_lon      = g_fresh_loc[1]
        g_accuracy = g_fresh_loc[2] if len(g_fresh_loc) > 2 else None
        g_acc_str  = f"+-{g_accuracy:.0f}m" if g_accuracy else "unknown"
        g_count    = st.session_state.guardian_update_count + 1
        g_ts       = datetime.now().strftime("%H:%M:%S")

        # Update shared store
        location_entry = {
            "update": g_count,
            "lat": g_lat,
            "lon": g_lon,
            "accuracy": g_acc_str,
            "time": g_ts
        }

        if sid in guardian_store:
            guardian_store[sid]["locations"].append(location_entry)
            guardian_store[sid]["last_update"] = g_ts
            guardian_store[sid]["destination"] = st.session_state.guardian_destination

        st.session_state.guardian_locations.append(location_entry)
        st.session_state.guardian_update_count = g_count
        st.session_state.guardian_last_sent = g_ts

        g_location_box.info(
            f"🛡️ Guardian Update #{g_count} at {g_ts} | "
            f"{g_lat:.6f}, {g_lon:.6f} | accuracy {g_acc_str}"
        )

        # Send email on first update only
        if g_count == 1 and not st.session_state.guardian_link_sent:
            with g_result_box.container():
                with st.spinner("Notifying your emergency contacts with tracker link..."):
                    dest = st.session_state.guardian_destination
                    results = send_to_all(
                        g_lat, g_lon, all_contacts,
                        guardian_mode=True,
                        guardian_link=tracker_link,
                        destination=dest
                    )
                for r in results:
                    if r["success"]:
                        st.success(f"✅ Guardian link sent to {r['name']} ({r['email']})")
                    else:
                        st.error(f"❌ Failed to notify {r['name']}: {r['error']}")
            st.session_state.guardian_link_sent = True

        # Show embedded map
        maps_embed = f"https://maps.google.com/maps?q={g_lat},{g_lon}&z=16&output=embed"
        st.markdown(
            f"""
            <div style="border-radius:12px;overflow:hidden;border:2px solid #0a5c2e;margin:10px 0;">
                <iframe width="100%" height="350"
                    src="{maps_embed}"
                    frameborder="0" allowfullscreen style="display:block;">
                </iframe>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.link_button(
            "🗺️ Open in Google Maps",
            f"https://maps.google.com/?q={g_lat},{g_lon}",
            use_container_width=True
        )

        with g_trail_box.expander(
            f"📍 Your location trail ({len(st.session_state.guardian_locations)} updates)",
            expanded=False
        ):
            for entry in reversed(st.session_state.guardian_locations):
                st.markdown(
                    f"**#{entry['update']}** at {entry['time']} — "
                    f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )

        g_countdown = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.guardian_active:
                g_countdown.empty()
                st.stop()
            g_countdown.info(
                f"🛡️ Guardian Mode ON — next update in {remaining}s | "
                f"Update #{g_count} | Last: {g_ts} | "
                f"Press '✅ I'm Safe' above when you arrive"
            )
            time.sleep(1)
        g_countdown.empty()
        st.session_state.guardian_loc_key += 1
        st.rerun()

    else:
        st.error("⚠️ Could not get GPS location. Please allow location access.")
        g_retry = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.guardian_active:
                g_retry.empty()
                st.stop()
            g_retry.warning(f"Retrying GPS in {remaining}s...")
            time.sleep(1)
        g_retry.empty()
        if st.session_state.guardian_active:
            st.session_state.guardian_loc_key += 1
            st.rerun()


# ===================================================================
# ---------- MOTION DETECTION SECTION ----------
# ===================================================================
st.divider()
st.subheader("📳 Motion Detection (Shake / Running)")

st.caption(
    "Automatically detects rapid shaking or running motion via the device accelerometer. "
    "Once triggered, location is sent every 30 seconds until you press STOP."
)

# Sensitivity slider
motion_threshold = st.slider(
    "Shake sensitivity (lower = more sensitive)",
    min_value=10, max_value=50, value=25, step=5,
    help="Acceleration threshold (m/s²) to trigger the alert. Lower values trigger on lighter movement."
)
motion_confirm_count = st.slider(
    "Confirm shakes needed to trigger",
    min_value=2, max_value=8, value=3, step=1,
    help="How many consecutive shakes above the threshold before alert fires."
)

motion_col1, motion_col2, motion_col3 = st.columns([3, 1, 1])
with motion_col1:
    if st.session_state.motion_tracking_active:
        st.error("📳 MOTION ALERT ACTIVE — Live tracking ON")
    elif st.session_state.motion_monitoring:
        st.success("📳 Motion monitoring ACTIVE — watching accelerometer...")
    else:
        st.info("📴 Motion monitoring is OFF")

with motion_col2:
    if not st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
        if st.button("📳 Start Motion", use_container_width=True, type="primary"):
            st.session_state.motion_monitoring = True
            st.session_state.motion_triggered = False
            st.session_state.motion_listen_key += 1
            st.rerun()
    elif st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
        if st.button("📴 Stop Motion", use_container_width=True):
            st.session_state.motion_monitoring = False
            streamlit_js_eval(
                js_expressions="window._motionListening = false; true",
                key="stop_motion_listener"
            )
            st.rerun()

with motion_col3:
    if st.session_state.motion_tracking_active:
        if st.button("🛑 STOP MOTION TRACKING", use_container_width=True, type="primary"):
            st.session_state.motion_tracking_active = False
            st.session_state.motion_monitoring = False
            st.session_state.motion_triggered = False
            total = st.session_state.motion_update_count
            st.session_state.motion_update_count = 0
            st.session_state.motion_tracking_locations = []
            st.success(f"Motion tracking stopped after {total} update(s).")
            st.rerun()

# ---------- INJECT MOTION DETECTION JS ----------
if st.session_state.motion_monitoring and not st.session_state.motion_triggered and not st.session_state.motion_tracking_active:
    motion_result = streamlit_js_eval(
        js_expressions=f"""
        new Promise((resolve) => {{
            window._motionListening = true;

            if (!window.DeviceMotionEvent) {{
                resolve({{ error: 'NOT_SUPPORTED' }});
                return;
            }}

            const THRESHOLD   = {motion_threshold};
            const CONFIRM_REQ = {motion_confirm_count};
            let shakeCount = 0;
            let lastAcc    = null;
            let resolved   = false;
            let listenTimeout = null;

            function onMotion(event) {{
                if (!window._motionListening || resolved) return;

                const acc = event.accelerationIncludingGravity;
                if (!acc) return;

                if (lastAcc) {{
                    const delta = Math.abs(acc.x - lastAcc.x)
                                + Math.abs(acc.y - lastAcc.y)
                                + Math.abs(acc.z - lastAcc.z);
                    if (delta > THRESHOLD) {{
                        shakeCount++;
                        if (shakeCount >= CONFIRM_REQ) {{
                            resolved = true;
                            window._motionListening = false;
                            window.removeEventListener('devicemotion', onMotion);
                            clearTimeout(listenTimeout);
                            resolve({{ detected: true, delta: delta }});
                            return;
                        }}
                    }} else {{
                        if (shakeCount > 0) shakeCount = Math.max(0, shakeCount - 0.5);
                    }}
                }}
                lastAcc = {{ x: acc.x, y: acc.y, z: acc.z }};
            }}

            if (typeof DeviceMotionEvent.requestPermission === 'function') {{
                DeviceMotionEvent.requestPermission()
                    .then(state => {{
                        if (state === 'granted') {{
                            window.addEventListener('devicemotion', onMotion);
                        }} else {{
                            resolve({{ error: 'PERMISSION_DENIED' }});
                        }}
                    }})
                    .catch(() => resolve({{ error: 'PERMISSION_ERROR' }}));
            }} else {{
                window.addEventListener('devicemotion', onMotion);
            }}

            listenTimeout = setTimeout(() => {{
                if (!resolved) {{
                    resolved = true;
                    window.removeEventListener('devicemotion', onMotion);
                    resolve({{ timeout: true }});
                }}
            }}, 30000);
        }})
        """,
        key=f"motion_listen_{st.session_state.motion_listen_key}"
    )

    if motion_result is not None:
        if isinstance(motion_result, dict):
            if motion_result.get("detected"):
                st.session_state.motion_triggered = True
                st.session_state.motion_tracking_active = True
                st.session_state.motion_monitoring = False
                st.session_state.motion_update_count = 0
                st.session_state.motion_tracking_locations = []
                st.session_state.motion_listen_key += 1
                st.rerun()
            elif motion_result.get("error") == "NOT_SUPPORTED":
                st.error("❌ Your device/browser doesn't support motion detection. Try Chrome on Android.")
                st.session_state.motion_monitoring = False
            elif motion_result.get("error") == "PERMISSION_DENIED":
                st.error("❌ Motion permission denied. On iPhone, go to Settings > Safari > Motion & Orientation Access.")
                st.session_state.motion_monitoring = False
            elif motion_result.get("error"):
                st.warning(f"Motion sensor error: {motion_result.get('error')}. Retrying...")
                st.session_state.motion_listen_key += 1
                time.sleep(1)
                st.rerun()
            elif motion_result.get("timeout"):
                st.session_state.motion_listen_key += 1
                st.rerun()

# ===================================================================
# ---------- MOTION LIVE TRACKING LOOP ----------
# ===================================================================
if st.session_state.motion_tracking_active:
    st.divider()
    st.error("📳 MOTION DISTRESS DETECTED — LIVE TRACKING ACTIVE")
    st.warning("Location is being sent every 30 seconds. Press 🛑 STOP MOTION TRACKING above to end.")

    m_location_box = st.empty()
    m_result_box   = st.empty()
    m_trail_box    = st.empty()

    m_fresh_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        })""",
        key=f"motion_xloc_{st.session_state.motion_update_count}"
    )

    if m_fresh_loc:
        m_lat      = m_fresh_loc[0]
        m_lon      = m_fresh_loc[1]
        m_accuracy = m_fresh_loc[2] if len(m_fresh_loc) > 2 else None
        m_acc_str  = f"+-{m_accuracy:.0f}m" if m_accuracy else "unknown"
        m_count    = st.session_state.motion_update_count + 1
        m_ts       = datetime.now().strftime("%H:%M:%S")

        m_location_box.info(
            f"📳 Motion Update #{m_count} at {m_ts} | "
            f"{m_lat:.6f}, {m_lon:.6f} | accuracy {m_acc_str}"
        )

        if m_count == 1:
            with st.spinner("Finding nearest police..."):
                police = find_police(m_lat, m_lon) or find_police(m_lat, m_lon, 15000)
            if police:
                plat, plon, pname, pdist = police
                st.success(f"🚔 {pname} — {pdist:.0f}m away")
                st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")

        with m_result_box.container():
            with st.spinner(f"Sending motion update #{m_count}..."):
                results = send_to_all(
                    m_lat, m_lon, all_contacts,
                    update_num=m_count,
                    accuracy=m_accuracy,
                    motion_triggered=True
                )
            for r in results:
                if r["success"]:
                    st.success(f"✅ Motion Update #{m_count} sent to {r['name']}")
                else:
                    st.error(f"❌ Failed - {r['name']}: {r['error']}")

        st.session_state.motion_tracking_locations.append({
            "update": m_count, "lat": m_lat, "lon": m_lon,
            "accuracy": m_acc_str, "time": m_ts
        })
        st.session_state.motion_update_count = m_count
        st.session_state.motion_last_sent    = m_ts

        with m_trail_box.expander(
            f"📍 Motion location trail ({len(st.session_state.motion_tracking_locations)} updates)",
            expanded=False
        ):
            for entry in reversed(st.session_state.motion_tracking_locations):
                st.markdown(
                    f"**#{entry['update']}** at {entry['time']} - "
                    f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )

        m_countdown = st.empty()
        for remaining in range(30, 0, -1):
            if not st.session_state.motion_tracking_active:
                m_countdown.empty()
                st.stop()
            m_countdown.info(f"📳 Next motion update in {remaining}s... | Last sent: {m_ts}")
            time.sleep(1)
        m_countdown.empty()
        st.rerun()

    else:
        st.error("Could not get GPS location. Make sure location permission is granted.")
        m_retry = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.motion_tracking_active:
                m_retry.empty()
                st.stop()
            m_retry.warning(f"Retrying in {remaining} seconds...")
            time.sleep(1)
        m_retry.empty()
        if st.session_state.motion_tracking_active:
            st.rerun()

# ===================================================================
# ---------- VOICE RECOGNITION SECTION ----------
# ===================================================================
st.divider()
st.subheader("🎙️ Voice Distress Detection")

keywords_display = ", ".join([f'"{k}"' for k in DISTRESS_KEYWORDS])
st.caption(f"Listening for: {keywords_display}")

voice_col1, voice_col2, voice_col3 = st.columns([3, 1, 1])
with voice_col1:
    if st.session_state.voice_tracking_active:
        st.error(f'🎙️ VOICE ALERT ACTIVE — Live tracking ON (triggered by: "{st.session_state.voice_trigger_word}")')
    elif st.session_state.voice_active:
        st.success("🎙️ Voice monitoring ACTIVE — listening for distress words...")
    else:
        st.info("🔇 Voice monitoring is OFF")

with voice_col2:
    if not st.session_state.voice_active and not st.session_state.voice_tracking_active:
        if st.button("🎙️ Start Listening", use_container_width=True, type="primary"):
            st.session_state.voice_active = True
            st.session_state.voice_triggered = False
            st.session_state.voice_trigger_word = ""
            st.session_state.voice_trigger_key += 1
            st.rerun()
    elif st.session_state.voice_active and not st.session_state.voice_tracking_active:
        if st.button("🔇 Stop Listening", use_container_width=True):
            st.session_state.voice_active = False
            streamlit_js_eval(
                js_expressions="window._emergencyRecognition && window._emergencyRecognition.stop(); true",
                key="stop_voice"
            )
            st.rerun()

with voice_col3:
    if st.session_state.voice_tracking_active:
        if st.button("🛑 STOP VOICE TRACKING", use_container_width=True, type="primary"):
            st.session_state.voice_tracking_active = False
            st.session_state.voice_active = False
            st.session_state.voice_triggered = False
            total = st.session_state.voice_update_count
            st.session_state.voice_update_count = 0
            st.session_state.voice_tracking_locations = []
            st.success(f"Voice tracking stopped after {total} update(s).")
            st.rerun()

# ---------- INJECT VOICE RECOGNITION JS ----------
if st.session_state.voice_active and not st.session_state.voice_triggered and not st.session_state.voice_tracking_active:
    keywords_js = json.dumps(DISTRESS_KEYWORDS)

    voice_result = streamlit_js_eval(
        js_expressions=f"""
        new Promise((resolve) => {{
            if (window._emergencyRecognition) {{
                window._emergencyRecognition.stop();
                window._emergencyRecognition = null;
            }}

            const keywords = {keywords_js};

            if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {{
                resolve({{ error: 'NOT_SUPPORTED' }});
                return;
            }}

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            const recognition = new SpeechRecognition();
            window._emergencyRecognition = recognition;

            recognition.continuous      = true;
            recognition.interimResults  = true;
            recognition.lang            = 'en-US';
            recognition.maxAlternatives = 3;

            let resolved = false;

            recognition.onresult = (event) => {{
                for (let i = event.resultIndex; i < event.results.length; i++) {{
                    for (let a = 0; a < event.results[i].length; a++) {{
                        const transcript = event.results[i][a].transcript.toLowerCase().trim();
                        for (const kw of keywords) {{
                            if (transcript.includes(kw.toLowerCase())) {{
                                if (!resolved) {{
                                    resolved = true;
                                    recognition.stop();
                                    resolve({{ detected: true, word: kw, transcript: transcript }});
                                }}
                                return;
                            }}
                        }}
                    }}
                }}
            }};

            recognition.onerror = (event) => {{
                if (!resolved) {{
                    resolved = true;
                    resolve({{ error: event.error }});
                }}
            }};

            recognition.onend = () => {{
                if (!resolved) {{
                    resolved = true;
                    resolve({{ ended: true }});
                }}
            }};

            recognition.start();
        }})
        """,
        key=f"voice_listen_{st.session_state.voice_trigger_key}"
    )

    if voice_result is not None:
        if isinstance(voice_result, dict):
            if voice_result.get("detected"):
                trigger_word = voice_result.get("word", "unknown")
                st.session_state.voice_triggered = True
                st.session_state.voice_trigger_word = trigger_word
                st.session_state.voice_tracking_active = True
                st.session_state.voice_active = False
                st.session_state.voice_update_count = 0
                st.session_state.voice_tracking_locations = []
                st.session_state.voice_trigger_key += 1
                st.rerun()
            elif voice_result.get("error") == "NOT_SUPPORTED":
                st.error("❌ Your browser doesn't support Speech Recognition. Please use Chrome or Edge.")
                st.session_state.voice_active = False
            elif voice_result.get("error"):
                error_msg = voice_result.get("error", "")
                if error_msg not in ("aborted", "no-speech"):
                    st.warning(f"Mic error: {error_msg}. Retrying...")
                st.session_state.voice_trigger_key += 1
                time.sleep(1)
                st.rerun()
            elif voice_result.get("ended"):
                st.session_state.voice_trigger_key += 1
                time.sleep(0.5)
                st.rerun()

# ===================================================================
# ---------- VOICE LIVE TRACKING LOOP ----------
# ===================================================================
if st.session_state.voice_tracking_active:
    st.divider()
    trigger_word = st.session_state.voice_trigger_word
    st.error(f'🎙️ VOICE DISTRESS DETECTED: "{trigger_word.upper()}" — LIVE TRACKING ACTIVE')
    st.warning("Location is being sent every 30 seconds. Press 🛑 STOP VOICE TRACKING above to end.")

    v_location_box = st.empty()
    v_result_box   = st.empty()
    v_trail_box    = st.empty()

    v_fresh_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        })""",
        key=f"voice_xloc_{st.session_state.voice_update_count}"
    )

    if v_fresh_loc:
        v_lat      = v_fresh_loc[0]
        v_lon      = v_fresh_loc[1]
        v_accuracy = v_fresh_loc[2] if len(v_fresh_loc) > 2 else None
        v_acc_str  = f"+-{v_accuracy:.0f}m" if v_accuracy else "unknown"
        v_count    = st.session_state.voice_update_count + 1
        v_ts       = datetime.now().strftime("%H:%M:%S")

        v_location_box.info(
            f"🎙️ Voice Update #{v_count} at {v_ts} | "
            f"{v_lat:.6f}, {v_lon:.6f} | accuracy {v_acc_str}"
        )

        if v_count == 1:
            with st.spinner("Finding nearest police..."):
                police = find_police(v_lat, v_lon) or find_police(v_lat, v_lon, 15000)
            if police:
                plat, plon, pname, pdist = police
                st.success(f"🚔 {pname} — {pdist:.0f}m away")
                st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")

        with v_result_box.container():
            with st.spinner(f"Sending voice update #{v_count}..."):
                results = send_to_all(
                    v_lat, v_lon, all_contacts,
                    update_num=v_count,
                    accuracy=v_accuracy,
                    voice_triggered=True,
                    trigger_word=trigger_word
                )
            for r in results:
                if r["success"]:
                    st.success(f"✅ Voice Update #{v_count} sent to {r['name']}")
                else:
                    st.error(f"❌ Failed - {r['name']}: {r['error']}")

        st.session_state.voice_tracking_locations.append({
            "update": v_count, "lat": v_lat, "lon": v_lon,
            "accuracy": v_acc_str, "time": v_ts
        })
        st.session_state.voice_update_count = v_count
        st.session_state.voice_last_sent    = v_ts

        with v_trail_box.expander(f"📍 Voice location trail ({len(st.session_state.voice_tracking_locations)} updates)", expanded=False):
            for entry in reversed(st.session_state.voice_tracking_locations):
                st.markdown(
                    f"**#{entry['update']}** at {entry['time']} - "
                    f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )

        v_countdown = st.empty()
        for remaining in range(30, 0, -1):
            if not st.session_state.voice_tracking_active:
                v_countdown.empty()
                st.stop()
            v_countdown.info(f"🎙️ Next voice update in {remaining}s... | Last sent: {v_ts}")
            time.sleep(1)
        v_countdown.empty()
        st.rerun()

    else:
        st.error("Could not get GPS location. Make sure location permission is granted.")
        v_retry = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.voice_tracking_active:
                v_retry.empty()
                st.stop()
            v_retry.warning(f"Retrying in {remaining} seconds...")
            time.sleep(1)
        v_retry.empty()
        if st.session_state.voice_tracking_active:
            st.rerun()

# ===================================================================
# ---------- PANIC BUTTONS ----------
# ===================================================================
st.divider()
st.caption(f"Alert will be sent to {len(all_contacts)} contact(s).")

col1, col2 = st.columns(2)

# ---- STANDARD PANIC ----
with col1:
    if st.button("PANIC", use_container_width=True, type="primary", disabled=st.session_state.extreme_active):
        st.session_state.panic_requested = True
        st.session_state.panic_key += 1

    if st.session_state.panic_requested:
        st.info("Locating... Please wait.")
        loc = streamlit_js_eval(
            js_expressions="""
            new Promise(resolve => {
                navigator.geolocation.getCurrentPosition(
                    p => resolve([p.coords.latitude, p.coords.longitude]),
                    () => resolve("ERROR")
                );
            })""",
            key=f"panic_location_{st.session_state.panic_key}"
        )

        if loc == "ERROR":
            st.error("Location unavailable - allow location access and refresh.")
            st.session_state.panic_requested = False
        elif loc is not None:
            lat, lon = loc
            st.success(f"Location: {lat:.5f}, {lon:.5f}")
            results = send_to_all(lat, lon, all_contacts)
            for r in results:
                if r["success"]:
                    st.success(f"Sent to {r['name']}")
                else:
                    st.error(f"Failed - {r['name']}: {r['error']}")
            with st.spinner("Finding nearest police..."):
                police = find_police(lat, lon) or find_police(lat, lon, 15000)
            if police:
                plat, plon, name, dist = police
                st.success(f"{name} - {dist:.0f}m away")
                st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")
            else:
                st.error("No police station found nearby.")

            st.session_state.panic_requested = False

# ---- EXTREME PANIC TOGGLE ----
with col2:
    if not st.session_state.extreme_active:
        if st.button("EXTREME PANIC - Live Tracking", use_container_width=True):
            st.session_state.extreme_active = True
            st.session_state.update_count = 0
            st.session_state.tracking_locations = []
            st.rerun()
    else:
        if st.button("STOP TRACKING", use_container_width=True, type="primary"):
            st.session_state.extreme_active = False
            st.success(f"Tracking stopped after {st.session_state.update_count} update(s).")
            st.rerun()

# ===================================================================
# ---------- EXTREME PANIC LIVE TRACKING ----------
# ===================================================================
if st.session_state.extreme_active:
    st.divider()
    st.error("EXTREME PANIC ACTIVE - LIVE TRACKING ON")
    st.warning("Location sent every 30 seconds. Press STOP TRACKING above to end.")

    location_box = st.empty()
    result_box   = st.empty()
    trail_box    = st.empty()

    fresh_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        })""",
        key=f"xloc_{st.session_state.update_count}"
    )

    if fresh_loc:
        lat      = fresh_loc[0]
        lon      = fresh_loc[1]
        accuracy = fresh_loc[2] if len(fresh_loc) > 2 else None
        acc_str  = f"+-{accuracy:.0f}m" if accuracy else "unknown"
        count    = st.session_state.update_count + 1
        ts       = datetime.now().strftime("%H:%M:%S")

        location_box.info(
            f"Update #{count} at {ts} | "
            f"{lat:.6f}, {lon:.6f} | accuracy {acc_str}"
        )

        with result_box.container():
            with st.spinner(f"Sending update #{count}..."):
                results = send_to_all(lat, lon, all_contacts, update_num=count, accuracy=accuracy)
            for r in results:
                if r["success"]:
                    st.success(f"Update #{count} sent to {r['name']}")
                else:
                    st.error(f"Failed - {r['name']}: {r['error']}")

        st.session_state.tracking_locations.append({
            "update": count, "lat": lat, "lon": lon,
            "accuracy": acc_str, "time": ts
        })
        st.session_state.update_count = count
        st.session_state.last_sent    = ts

        with trail_box.expander(f"Location trail ({len(st.session_state.tracking_locations)} updates)", expanded=False):
            for entry in reversed(st.session_state.tracking_locations):
                st.markdown(
                    f"**#{entry['update']}** at {entry['time']} - "
                    f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )

        countdown = st.empty()
        for remaining in range(30, 0, -1):
            if not st.session_state.extreme_active:
                countdown.empty()
                st.stop()
            countdown.info(f"Next update in {remaining} seconds... | Last sent: {ts}")
            time.sleep(1)
        countdown.empty()
        st.rerun()

    else:
        st.error("Could not get GPS location. Make sure location permission is granted.")
        retry_box = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.extreme_active:
                retry_box.empty()
                st.stop()
            retry_box.warning(f"Retrying in {remaining} seconds...")
            time.sleep(1)
        retry_box.empty()
        if st.session_state.extreme_active:
            st.rerun()
