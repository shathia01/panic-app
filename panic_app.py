import streamlit as st
import requests
import math
import smtplib
import json
import time
import uuid
import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate, make_msgid
from streamlit_js_eval import streamlit_js_eval
from supabase import create_client

# ===================================================================
# ---------- SUPABASE CONFIG ----------
# ===================================================================
SUPABASE_URL = "YOUR_SUPABASE_URL"       # 🔁 Replace with your Supabase project URL
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY"  # 🔁 Replace with your Supabase anon/public key
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

APP_URL = "https://your-app.streamlit.app"  # 🔁 Replace with your deployed app URL

# ===================================================================
# ---------- AUDIO RECORDING JAVASCRIPT ----------
# ===================================================================
AUDIO_RECORD_JS = """
new Promise(async resolve => {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mediaRecorder = new MediaRecorder(stream);
        const audioChunks = [];
        mediaRecorder.addEventListener("dataavailable", e => audioChunks.push(e.data));
        mediaRecorder.addEventListener("stop", () => {
            const audioBlob = new Blob(audioChunks); // Uses browser's default format
            const reader = new FileReader();
            reader.readAsDataURL(audioBlob);
            reader.onloadend = () => {
                stream.getTracks().forEach(t => t.stop());
                resolve(reader.result);
            };
        });
        mediaRecorder.start();
        setTimeout(() => mediaRecorder.stop(), 10000); // 10 seconds recording
    } catch(e) { resolve("ERROR:" + e.message); }
})
"""

# ===================================================================
# ---------- GUARDIAN PAGE DETECTION ----------
# ===================================================================
track_id = st.query_params.get("track_id")

if track_id:
    st.set_page_config(page_title="Guardian Live Monitor", page_icon="🛡️", layout="centered")
    st.title("🛡️ Guardian Live Monitoring")
    st.caption(f"Tracking ID: `{track_id}`")

    status_box   = st.empty()
    map_box      = st.empty()
    details_box  = st.empty()
    refresh_box  = st.empty()

    try:
        response = supabase.table("live_tracking").select("*").eq("track_id", track_id).execute()
        data = response.data

        if not data:
            status_box.warning("⏳ Waiting for location data... The person may not have started yet or the journey has ended.")
        else:
            row = data[0]
            lat       = row["lat"]
            lon       = row["lon"]
            timestamp = row.get("timestamp", "Unknown")
            status    = row.get("status", "active")

            if status == "safe":
                status_box.success("✅ Journey completed — Person has reached safely!")
                details_box.info(f"Last known location: {lat:.5f}, {lon:.5f}\nTime: {timestamp}")
            else:
                status_box.error("🔴 LIVE — Location updating every 5 seconds")
                map_box.map([{"lat": lat, "lon": lon}])
                details_box.info(
                    f"📍 **Live Location**\n\n"
                    f"Latitude: `{lat:.6f}`\n\n"
                    f"Longitude: `{lon:.6f}`\n\n"
                    f"Last updated: `{timestamp}`\n\n"
                    f"[Open in Google Maps](https://maps.google.com/?q={lat},{lon})"
                )
                refresh_box.caption("Page auto-refreshes every 5 seconds.")
                time.sleep(5)
                st.rerun()

    except Exception as e:
        status_box.error(f"Error fetching location: {e}")

    st.stop()


# ===================================================================
# ---------- MAIN USER APP ----------
# ===================================================================
st.title("🚨 One-Click Emergency Panic Button")

# ---------- GMAIL CONFIG ----------
SENDER_EMAIL        = "shathia190304@gmail.com"
SENDER_APP_PASSWORD = "kvskirvfdhsscege"
SENDER_NAME         = "Emergency Alert"

DISTRESS_KEYWORDS = [
    "help", "please", "leave me", "stop", "let me go",
    "get away", "don't touch me", "call police", "save me",
    "emergency", "danger", "scared"
]

DEFAULT_CONTACTS = [
    {"name": "Admin", "email": "shathia190304@gmail.com"},
]

# ---------- SESSION STATE INIT ----------
for key, default in [
    ("extreme_active", False), ("update_count", 0), ("last_sent", None), ("tracking_locations", []),
    ("panic_requested", False), ("panic_key", 0),
    ("voice_active", False), ("voice_triggered", False), ("voice_trigger_word", ""), 
    ("voice_trigger_key", 0), ("voice_tracking_active", False), ("voice_update_count", 0),
    ("voice_tracking_locations", []), ("voice_last_sent", None),
    ("motion_monitoring", False), ("motion_triggered", False), ("motion_tracking_active", False),
    ("motion_update_count", 0), ("motion_tracking_locations", []), ("motion_last_sent", None),
    ("motion_listen_key", 0), ("guardian_active", False), ("guardian_id", None),
    ("guardian_update_count", 0), ("guardian_tracking_locations", []),
]:
    if key not in st.session_state: st.session_state[key] = default

raw = streamlit_js_eval(js_expressions="localStorage.getItem('emergency_my_contacts')", key="read_my_contacts")
my_contacts = []
if raw and raw != "null":
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict): my_contacts = [parsed]
        elif isinstance(parsed, list): my_contacts = parsed
    except Exception: my_contacts = []

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

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
        res = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=25).json()
        elements = res.get("elements", [])
        if not elements: return None
        best, best_dist = None, float("inf")
        for el in elements:
            plat = el.get("lat") or el.get("center", {}).get("lat")
            plon = el.get("lon") or el.get("center", {}).get("lon")
            if plat is None or plon is None: continue
            dist = haversine(lat, lon, plat, plon)
            if dist < best_dist:
                best_dist = dist
                name = el.get("tags", {}).get("name", "Police Station")
                best = (plat, plon, name, best_dist)
        return best
    except Exception: return None

# ---------- SEND EMAIL ----------
def send_email(recipient_name, recipient_email, lat, lon, update_num=None, accuracy=None,
               voice_triggered=False, trigger_word="", motion_triggered=False,
               guardian_link=None, safe_arrival=False, audio_data=None, audio_ext="webm"):
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_update = update_num is not None

    if safe_arrival:
        subject = "✅ Journey Completed Safely — Guardian Alert"
    elif guardian_link:
        subject = "🛡️ Guardian Live Monitoring Started — Live Tracking Link"
    elif motion_triggered:
        subject = "📳 MOTION ALERT - Shaking/Running Detected - Emergency"
    elif voice_triggered:
        subject = "🎙️ VOICE ALERT - Distress Word Detected - Emergency"
    elif is_update:
        subject = f"LIVE UPDATE #{update_num} - Emergency Alert - Urgent"
    else:
        subject = "Emergency Alert - Urgent Assistance Required"

    acc_text = f"+-{accuracy:.0f}m" if accuracy else "N/A"
    voice_note   = f'\n⚠️ Triggered by voice: "{trigger_word}"\n' if voice_triggered else ""
    motion_note  = "\n⚠️ Triggered by device motion/shaking — person may be in distress!\n" if motion_triggered else ""
    guardian_note = f"\n🛡️ Guardian Live Monitoring Link:\n{guardian_link}\n" if guardian_link else ""
    safe_note    = "\n✅ The person has SAFELY reached their destination. Live tracking has ended.\n" if safe_arrival else ""
    audio_note   = "\n🎧 AUDIO EVIDENCE ATTACHED: Please check the attached audio file recorded from the device's microphone.\n" if audio_data else ""

    plain = f"""{'✅ SAFE ARRIVAL NOTIFICATION' if safe_arrival else ('🛡️ GUARDIAN LIVE MONITORING STARTED' if guardian_link else ('📳 MOTION ALERT' if motion_triggered else ('🎙️ VOICE ALERT' if voice_triggered else ('LIVE TRACKING UPDATE #' + str(update_num) if is_update else 'EMERGENCY ALERT'))))}

Dear {recipient_name},

{'The person has safely reached their destination. Live tracking has ended.' if safe_arrival else ('Guardian Journey has started. Use the link below to monitor live location.' if guardian_link else ('MOTION DETECTED: Rapid shaking or running motion was automatically detected!' if motion_triggered else ('VOICE DISTRESS: The word "' + trigger_word + '" was detected!' if voice_triggered else ('This is a LIVE LOCATION UPDATE.' if is_update else 'Someone triggered the Emergency Panic Button.'))))}

Call emergency services (999) immediately.{voice_note}{motion_note}{guardian_note}{safe_note}{audio_note}
Location: {lat:.6f}, {lon:.6f}
Accuracy: {acc_text}
Google Maps: {maps_link}
Time: {timestamp}
"""

    if safe_arrival:
        color = "#1a7a1a"; header_text = "✅ Safe Arrival Confirmed"
        body_text = "The person has <b>safely reached their destination</b>. Live tracking has ended."
        extra_block = ""
    elif guardian_link:
        color = "#1a4a7a"; header_text = "🛡️ Guardian Live Monitoring Active"
        body_text = "A Guardian Journey has started. Click the button below to view their live location."
        extra_block = f"""<a href="{guardian_link}" style="display:block;text-align:center;background:#1a4a7a;color:white;padding:14px 20px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold;margin:15px 0;">🗺️ Open Live Guardian Map</a><p style="text-align:center;font-size:12px;color:#888;">Link: {guardian_link}</p>"""
    elif motion_triggered:
        color = "#7B3F00"; header_text = "📳 MOTION ALERT: Device Shaking Detected"
        body_text = "<b>⚠️ MOTION DISTRESS DETECTION ACTIVE</b><br>Rapid shaking or running motion was automatically detected. Immediate attention required!"
        extra_block = f"<p style='color:{color};font-weight:bold;'>{audio_note}</p>" if audio_data else ""
    elif voice_triggered:
        color = "#4a0080"; header_text = f'🎙️ VOICE ALERT: "{trigger_word}"'
        body_text = f'<b>⚠️ VOICE DISTRESS DETECTION ACTIVE</b><br>The word <b>"{trigger_word}"</b> was automatically detected. Immediate attention required!'
        extra_block = f"<p style='color:{color};font-weight:bold;'>{audio_note}</p>" if audio_data else ""
    elif is_update:
        color = "#8B0000"; header_text = f"LIVE UPDATE #{update_num}"
        body_text = "<b>LIVE TRACKING ACTIVE</b> — Person is moving. Latest position below."
        extra_block = ""
    else:
        color = "red"; header_text = "Emergency Alert"
        body_text = "Emergency Panic Button was activated."
        extra_block = ""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f8f8f8;padding:20px;">
    <div style="max-width:500px;margin:auto;background:white;border-radius:10px;border-top:6px solid {color};padding:30px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <h1 style="color:{color};text-align:center;">{header_text}</h1>
        <p>Dear <b>{recipient_name}</b>,</p>
        <p>{body_text}<br><br>{'Call emergency services (<b>999</b>) immediately.' if not safe_arrival and not guardian_link else ''}</p>
        {extra_block}
        <div style="background:#f0f8ff;border-left:4px solid {color};padding:15px;border-radius:5px;margin:20px 0;">
            <p style="margin:0;font-size:15px;">
                Location:<br>
                Lat: <code>{lat:.6f}</code><br>
                Lon: <code>{lon:.6f}</code><br>
                <small>GPS Accuracy: {acc_text}</small><br>
                <small>Sent: {timestamp}</small>
                {f'<br><small style="color:{color};font-weight:bold;">Update #{update_num} of ongoing tracking</small>' if is_update else ''}
            </p>
        </div>
        <a href="{maps_link}" style="display:block;text-align:center;background:{color};color:white;padding:14px 20px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold;margin-top:10px;">
            Open Location on Google Maps
        </a>
    </div></body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"]    = subject
        msg["From"]       = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"]         = recipient_email
        msg["Reply-To"]   = SENDER_EMAIL
        msg["Date"]       = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))
        
        # --- ATTACH AUDIO EVIDENCE ---
        if audio_data:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(audio_data)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="emergency_audio_{update_num or "alert"}.{audio_ext}"')
            msg.attach(part)
        # -----------------------------

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)

def send_to_all(lat, lon, contacts, update_num=None, accuracy=None,
                voice_triggered=False, trigger_word="", motion_triggered=False,
                guardian_link=None, safe_arrival=False, audio_data=None, audio_ext="webm"):
    results = []
    for c in contacts:
        success, error = send_email(
            c["name"], c["email"], lat, lon,
            update_num, accuracy, voice_triggered, trigger_word, motion_triggered,
            guardian_link, safe_arrival, audio_data, audio_ext
        )
        results.append({"name": c["name"], "email": c["email"], "success": success, "error": error})
    return results

all_contacts = list(DEFAULT_CONTACTS)
for c in my_contacts:
    if not any(x["email"].lower() == c["email"].lower() for x in all_contacts):
        all_contacts.append(c)

st.divider()
st.subheader("📋 My Emergency Contacts")
if my_contacts:
    st.success(f"{len(my_contacts)} personal contact(s) saved on this device.")
    for i, c in enumerate(my_contacts):
        col_name, col_email, col_del = st.columns([2, 3, 1])
        with col_name: st.write(f"**{c['name']}**")
        with col_email: st.write(c["email"])
        with col_del:
            if st.button("🗑️ Remove", key=f"remove_{i}"):
                updated = [x for j, x in enumerate(my_contacts) if j != i]
                escaped = json.dumps(updated).replace("'", "\\'")
                streamlit_js_eval(js_expressions=f"localStorage.setItem('emergency_my_contacts','{escaped}');true", key=f"del_contact_{i}")
                st.info("Removed. Refresh to confirm.")
else: st.info("No personal contacts saved yet. Add contacts below.")

st.markdown("##### ➕ Add a Contact")
with st.form("add_contact_form", clear_on_submit=True):
    col_n, col_e = st.columns(2)
    with col_n: reg_name = st.text_input("Name", placeholder="e.g. Sarah")
    with col_e: reg_email = st.text_input("Email", placeholder="e.g. sarah@gmail.com")
    if st.form_submit_button("Save Contact to This Device"):
        if reg_name and reg_email:
            if any(c["email"].lower() == reg_email.lower() for c in my_contacts):
                st.warning("A contact with that email already exists.")
            else:
                updated = my_contacts + [{"name": reg_name, "email": reg_email}]
                escaped = json.dumps(updated).replace("'", "\\'")
                streamlit_js_eval(js_expressions=f"localStorage.setItem('emergency_my_contacts','{escaped}');true", key="save_new_contact")
                st.success(f"Saved {reg_name}! Refresh to confirm.")
        else: st.warning("Please fill in both fields.")

# ===================================================================
# ---------- 🛡️ GUARDIAN LIVE MONITORING MODE ----------
# ===================================================================
st.divider()
st.subheader("🛡️ Guardian Live Monitoring")
st.caption("Start a monitored journey. Your guardians receive a live map link and track your location every 5 seconds. Press 'I Reached Safe' when you arrive.")

guard_col1, guard_col2 = st.columns([3, 1])
with guard_col1:
    if st.session_state.guardian_active:
        st.error(f"🛡️ GUARDIAN MODE ACTIVE — Tracking ID: `{st.session_state.guardian_id}`")
        tracking_link = f"{APP_URL}/?track_id={st.session_state.guardian_id}"
        st.markdown(f"**Guardian link:** [{tracking_link}]({tracking_link})")
    else: st.info("🔒 Guardian mode is OFF")

with guard_col2:
    if not st.session_state.guardian_active:
        if st.button("🛡️ Start Guardian Journey", use_container_width=True, type="primary"):
            st.session_state.guardian_id = str(uuid.uuid4())[:8]
            st.session_state.guardian_active = True
            st.session_state.guardian_update_count = 0
            st.session_state.guardian_tracking_locations = []
            st.rerun()
    else:
        if st.button("✅ I Reached Safe", use_container_width=True, type="primary"):
            try: supabase.table("live_tracking").update({"status": "safe"}).eq("track_id", st.session_state.guardian_id).execute()
            except Exception as e: st.warning(f"DB update error: {e}")
            last_locs = st.session_state.guardian_tracking_locations
            if last_locs: send_to_all(last_locs[-1]["lat"], last_locs[-1]["lon"], all_contacts, safe_arrival=True)
            total = st.session_state.guardian_update_count
            st.session_state.guardian_active = False
            st.session_state.guardian_id     = None
            st.session_state.guardian_update_count = 0
            st.session_state.guardian_tracking_locations = []
            st.success(f"✅ Guardians notified you reached safely! ({total} location updates sent)")
            st.rerun()

if st.session_state.guardian_active:
    g_loc_box = st.empty(); g_status_box = st.empty(); g_trail_box = st.empty(); g_count_box = st.empty()
    g_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
            );
        })""",
        key=f"guardian_loc_{st.session_state.guardian_update_count}"
    )

    if g_loc:
        g_lat = g_loc[0]; g_lon = g_loc[1]
        g_accuracy = g_loc[2] if len(g_loc) > 2 else None
        g_acc_str  = f"+-{g_accuracy:.0f}m" if g_accuracy else "unknown"
        g_count    = st.session_state.guardian_update_count + 1
        g_ts       = datetime.now().strftime("%H:%M:%S")
        g_tid      = st.session_state.guardian_id
        tracking_link = f"{APP_URL}/?track_id={g_tid}"

        try:
            supabase.table("live_tracking").upsert({"track_id": g_tid, "lat": g_lat, "lon": g_lon, "timestamp": datetime.now().isoformat(), "status": "active"}).execute()
        except Exception as e: g_status_box.warning(f"DB write error: {e}")

        if g_count == 1:
            with st.spinner("Sending live tracking link to guardians..."):
                results = send_to_all(g_lat, g_lon, all_contacts, guardian_link=tracking_link, accuracy=g_accuracy)
            for r in results:
                if r["success"]: g_status_box.success(f"✅ Guardian link sent to {r['name']}")
                else: g_status_box.error(f"❌ Failed to send to {r['name']}: {r['error']}")

        g_loc_box.info(f"🛡️ Update #{g_count} at {g_ts} | {g_lat:.6f}, {g_lon:.6f} | accuracy {g_acc_str}")
        st.session_state.guardian_tracking_locations.append({"update": g_count, "lat": g_lat, "lon": g_lon, "accuracy": g_acc_str, "time": g_ts})
        st.session_state.guardian_update_count = g_count

        with g_trail_box.expander(f"📍 Guardian location trail ({len(st.session_state.guardian_tracking_locations)} updates)", expanded=False):
            for entry in reversed(st.session_state.guardian_tracking_locations):
                st.markdown(f"**#{entry['update']}** at {entry['time']} — `{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) [Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})")

        for remaining in range(5, 0, -1):
            if not st.session_state.guardian_active:
                g_count_box.empty(); st.stop()
            g_count_box.caption(f"Next guardian update in {remaining}s...")
            time.sleep(1)
        g_count_box.empty()
        st.rerun()
    else:
        st.error("Could not get GPS location. Make sure location permission is granted.")
        for remaining in range(5, 0, -1):
            if not st.session_state.guardian_active: st.stop()
            time.sleep(1)
        if st.session_state.guardian_active: st.rerun()

# ===================================================================
# ---------- MOTION DETECTION SECTION ----------
# ===================================================================
st.divider()
st.subheader("📳 Motion Detection (Shake / Running)")
st.caption("Automatically detects rapid shaking or running motion. Once triggered, location and 10-sec audio evidence are sent to contacts.")

motion_threshold    = st.slider("Shake sensitivity (lower = more sensitive)", min_value=10, max_value=50, value=25, step=5)
motion_confirm_count = st.slider("Confirm shakes needed to trigger", min_value=2, max_value=8, value=3, step=1)

motion_col1, motion_col2, motion_col3 = st.columns([3, 1, 1])
with motion_col1:
    if st.session_state.motion_tracking_active: st.error("📳 MOTION ALERT ACTIVE — Live tracking ON")
    elif st.session_state.motion_monitoring: st.success("📳 Motion monitoring ACTIVE — watching accelerometer...")
    else: st.info("📴 Motion monitoring is OFF")

with motion_col2:
    if not st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
        if st.button("📳 Start Motion", use_container_width=True, type="primary"):
            st.session_state.motion_monitoring = True
            st.session_state.motion_triggered  = False
            st.session_state.motion_listen_key += 1
            st.rerun()
    elif st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
        if st.button("📴 Stop Motion", use_container_width=True):
            st.session_state.motion_monitoring = False
            streamlit_js_eval(js_expressions="window._motionListening = false; true", key="stop_motion_listener")
            st.rerun()

with motion_col3:
    if st.session_state.motion_tracking_active:
        if st.button("🛑 STOP TRACKING", use_container_width=True, type="primary"):
            st.session_state.motion_tracking_active = False
            st.session_state.motion_monitoring      = False
            st.session_state.motion_triggered       = False
            total = st.session_state.motion_update_count
            st.session_state.motion_update_count = 0
            st.session_state.motion_tracking_locations = []
            st.success(f"Motion tracking stopped after {total} update(s).")
            st.rerun()

if st.session_state.motion_monitoring and not st.session_state.motion_triggered and not st.session_state.motion_tracking_active:
    motion_result = streamlit_js_eval(
        js_expressions=f"""
        new Promise((resolve) => {{
            window._motionListening = true;
            if (!window.DeviceMotionEvent) {{ resolve({{ error: 'NOT_SUPPORTED' }}); return; }}
            const THRESHOLD   = {motion_threshold};
            const CONFIRM_REQ = {motion_confirm_count};
            let shakeCount = 0, lastAcc = null, resolved = false, listenTimeout = null;
            function onMotion(event) {{
                if (!window._motionListening || resolved) return;
                const acc = event.accelerationIncludingGravity;
                if (!acc) return;
                if (lastAcc) {{
                    const delta = Math.abs(acc.x - lastAcc.x) + Math.abs(acc.y - lastAcc.y) + Math.abs(acc.z - lastAcc.z);
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
                    }} else {{ if (shakeCount > 0) shakeCount = Math.max(0, shakeCount - 0.5); }}
                }}
                lastAcc = {{ x: acc.x, y: acc.y, z: acc.z }};
            }}
            if (typeof DeviceMotionEvent.requestPermission === 'function') {{
                DeviceMotionEvent.requestPermission()
                    .then(state => {{ if (state === 'granted') {{ window.addEventListener('devicemotion', onMotion); }} else {{ resolve({{ error: 'PERMISSION_DENIED' }}); }} }})
                    .catch(() => resolve({{ error: 'PERMISSION_ERROR' }}));
            }} else {{ window.addEventListener('devicemotion', onMotion); }}
            listenTimeout = setTimeout(() => {{ if (!resolved) {{ resolved = true; window.removeEventListener('devicemotion', onMotion); resolve({{ timeout: true }}); }} }}, 30000);
        }})
        """,
        key=f"motion_listen_{st.session_state.motion_listen_key}"
    )

    if motion_result is not None:
        if isinstance(motion_result, dict):
            if motion_result.get("detected"):
                st.session_state.motion_triggered       = True
                st.session_state.motion_tracking_active = True
                st.session_state.motion_monitoring      = False
                st.session_state.motion_update_count    = 0
                st.session_state.motion_tracking_locations = []
                st.session_state.motion_listen_key += 1
                st.rerun()
            elif motion_result.get("error") == "NOT_SUPPORTED":
                st.error("❌ Device/browser doesn't support motion detection.")
                st.session_state.motion_monitoring = False
            elif motion_result.get("error") == "PERMISSION_DENIED":
                st.error("❌ Motion permission denied.")
                st.session_state.motion_monitoring = False
            elif motion_result.get("error"):
                st.warning(f"Motion sensor error: {motion_result.get('error')}. Retrying...")
                st.session_state.motion_listen_key += 1
                time.sleep(1)
                st.rerun()
            elif motion_result.get("timeout"):
                st.session_state.motion_listen_key += 1
                st.rerun()

if st.session_state.motion_tracking_active:
    st.divider()
    st.error("📳 MOTION DISTRESS DETECTED — LIVE TRACKING ACTIVE")
    st.warning("Location is being sent every 30 seconds. Press 🛑 STOP TRACKING above to end.")

    m_location_box = st.empty(); m_result_box = st.empty(); m_trail_box = st.empty()

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
        m_lat = m_fresh_loc[0]; m_lon = m_fresh_loc[1]
        m_accuracy = m_fresh_loc[2] if len(m_fresh_loc) > 2 else None
        m_acc_str  = f"+-{m_accuracy:.0f}m" if m_accuracy else "unknown"
        m_count = st.session_state.motion_update_count + 1
        m_ts    = datetime.now().strftime("%H:%M:%S")

        m_location_box.info(f"📳 Motion Update #{m_count} at {m_ts} | {m_lat:.6f}, {m_lon:.6f} | accuracy {m_acc_str}")

        if m_count == 1:
            with st.spinner("Finding nearest police..."):
                police = find_police(m_lat, m_lon) or find_police(m_lat, m_lon, 15000)
            if police:
                plat, plon, pname, pdist = police
                st.success(f"🚔 {pname} — {pdist:.0f}m away")
                st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")

        # =========================================================
        # --- BACKGROUND AUDIO RECORDING (On trigger & every 10th email) ---
        # =========================================================
        audio_bytes = None
        audio_ext = "webm"
        if m_count == 1 or m_count % 10 == 0:
            audio_b64 = streamlit_js_eval(js_expressions=AUDIO_RECORD_JS, key=f"audio_motion_{m_count}")
            
            if audio_b64 is None:
                st.info("🎙️ Auto-Recording 10 seconds of background audio for evidence... Please hold.")
                st.stop()  # Wait securely for Javascript to resolve the 10-second promise

            if isinstance(audio_b64, str) and audio_b64.startswith("data:audio"):
                header = audio_b64.split(",")[0]
                if "mp4" in header: audio_ext = "m4a"
                elif "wav" in header: audio_ext = "wav"
                elif "ogg" in header: audio_ext = "ogg"
                
                b64_data = audio_b64.split(",")[1]
                audio_bytes = base64.b64decode(b64_data)
                st.success("🎤 Audio recorded successfully and attached to alert.")
            elif isinstance(audio_b64, str) and audio_b64.startswith("ERROR"):
                st.warning(f"Audio recording failed: {audio_b64}")
        # =========================================================

        with m_result_box.container():
            with st.spinner(f"Sending motion update #{m_count}..."):
                results = send_to_all(m_lat, m_lon, all_contacts, update_num=m_count, accuracy=m_accuracy, motion_triggered=True, audio_data=audio_bytes, audio_ext=audio_ext)
            for r in results:
                if r["success"]: st.success(f"✅ Motion Update #{m_count} sent to {r['name']}")
                else:            st.error(f"❌ Failed - {r['name']}: {r['error']}")

        st.session_state.motion_tracking_locations.append({"update": m_count, "lat": m_lat, "lon": m_lon, "accuracy": m_acc_str, "time": m_ts})
        st.session_state.motion_update_count = m_count
        st.session_state.motion_last_sent    = m_ts

        with m_trail_box.expander(f"📍 Motion trail ({len(st.session_state.motion_tracking_locations)} updates)", expanded=False):
            for entry in reversed(st.session_state.motion_tracking_locations):
                st.markdown(f"**#{entry['update']}** at {entry['time']} - `{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) [Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})")

        m_countdown = st.empty()
        for remaining in range(30, 0, -1):
            if not st.session_state.motion_tracking_active:
                m_countdown.empty(); st.stop()
            m_countdown.info(f"📳 Next motion update in {remaining}s... | Last sent: {m_ts}")
            time.sleep(1)
        m_countdown.empty()
        st.rerun()
    else:
        st.error("Could not get GPS location.")
        m_retry = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.motion_tracking_active:
                m_retry.empty(); st.stop()
            m_retry.warning(f"Retrying in {remaining} seconds...")
            time.sleep(1)
        m_retry.empty()
        if st.session_state.motion_tracking_active: st.rerun()


# ===================================================================
# ---------- VOICE RECOGNITION SECTION ----------
# ===================================================================
st.divider()
st.subheader("🎙️ Voice Distress Detection")
keywords_display = ", ".join([f'"{k}"' for k in DISTRESS_KEYWORDS])
st.caption(f"Listening for: {keywords_display}. Once triggered, location and 10-sec audio evidence are sent.")

voice_col1, voice_col2, voice_col3 = st.columns([3, 1, 1])
with voice_col1:
    if st.session_state.voice_tracking_active: st.error(f'🎙️ VOICE ALERT ACTIVE — Live tracking ON (triggered by: "{st.session_state.voice_trigger_word}")')
    elif st.session_state.voice_active: st.success("🎙️ Voice monitoring ACTIVE — listening for distress words...")
    else: st.info("🔇 Voice monitoring is OFF")

with voice_col2:
    if not st.session_state.voice_active and not st.session_state.voice_tracking_active:
        if st.button("🎙️ Start Listening", use_container_width=True, type="primary"):
            st.session_state.voice_active      = True
            st.session_state.voice_triggered   = False
            st.session_state.voice_trigger_word = ""
            st.session_state.voice_trigger_key += 1
            st.rerun()
    elif st.session_state.voice_active and not st.session_state.voice_tracking_active:
        if st.button("🔇 Stop Listening", use_container_width=True):
            st.session_state.voice_active = False
            streamlit_js_eval(js_expressions="window._emergencyRecognition && window._emergencyRecognition.stop(); true", key="stop_voice")
            st.rerun()

with voice_col3:
    if st.session_state.voice_tracking_active:
        if st.button("🛑 STOP TRACKING", use_container_width=True, type="primary"):
            st.session_state.voice_tracking_active = False
            st.session_state.voice_active          = False
            st.session_state.voice_triggered       = False
            total = st.session_state.voice_update_count
            st.session_state.voice_update_count = 0
            st.session_state.voice_tracking_locations = []
            st.success(f"Voice tracking stopped after {total} update(s).")
            st.rerun()

if st.session_state.voice_active and not st.session_state.voice_triggered and not st.session_state.voice_tracking_active:
    keywords_js = json.dumps(DISTRESS_KEYWORDS)
    voice_result = streamlit_js_eval(
        js_expressions=f"""
        new Promise((resolve) => {{
            if (window._emergencyRecognition) {{ window._emergencyRecognition.stop(); window._emergencyRecognition = null; }}
            const keywords = {keywords_js};
            if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {{ resolve({{ error: 'NOT_SUPPORTED' }}); return; }}
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            const recognition = new SpeechRecognition();
            window._emergencyRecognition = recognition;
            recognition.continuous = true; recognition.interimResults = true; recognition.lang = 'en-US'; recognition.maxAlternatives = 3;
            let resolved = false;
            recognition.onresult = (event) => {{
                for (let i = event.resultIndex; i < event.results.length; i++) {{
                    for (let a = 0; a < event.results[i].length; a++) {{
                        const transcript = event.results[i][a].transcript.toLowerCase().trim();
                        for (const kw of keywords) {{
                            if (transcript.includes(kw.toLowerCase())) {{
                                if (!resolved) {{ resolved = true; recognition.stop(); resolve({{ detected: true, word: kw, transcript: transcript }}); }}
                                return;
                            }}
                        }}
                    }}
                }}
            }};
            recognition.onerror = (event) => {{ if (!resolved) {{ resolved = true; resolve({{ error: event.error }}); }} }};
            recognition.onend   = () => {{ if (!resolved) {{ resolved = true; resolve({{ ended: true }}); }} }};
            recognition.start();
        }})
        """,
        key=f"voice_listen_{st.session_state.voice_trigger_key}"
    )

    if voice_result is not None:
        if isinstance(voice_result, dict):
            if voice_result.get("detected"):
                trigger_word = voice_result.get("word", "unknown")
                st.session_state.voice_triggered        = True
                st.session_state.voice_trigger_word     = trigger_word
                st.session_state.voice_tracking_active  = True
                st.session_state.voice_active           = False
                st.session_state.voice_update_count     = 0
                st.session_state.voice_tracking_locations = []
                st.session_state.voice_trigger_key += 1
                st.rerun()
            elif voice_result.get("error") == "NOT_SUPPORTED":
                st.error("❌ Browser doesn't support Speech Recognition. Use Chrome or Edge.")
                st.session_state.voice_active = False
            elif voice_result.get("error"):
                error_msg = voice_result.get("error", "")
                if error_msg not in ("aborted", "no-speech"): st.warning(f"Mic error: {error_msg}. Retrying...")
                st.session_state.voice_trigger_key += 1
                time.sleep(1)
                st.rerun()
            elif voice_result.get("ended"):
                st.session_state.voice_trigger_key += 1
                time.sleep(0.5)
                st.rerun()

if st.session_state.voice_tracking_active:
    st.divider()
    trigger_word = st.session_state.voice_trigger_word
    st.error(f'🎙️ VOICE DISTRESS DETECTED: "{trigger_word.upper()}" — LIVE TRACKING ACTIVE')
    st.warning("Location is being sent every 30 seconds. Press 🛑 STOP TRACKING above to end.")

    v_location_box = st.empty(); v_result_box = st.empty(); v_trail_box = st.empty()

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
        v_lat = v_fresh_loc[0]; v_lon = v_fresh_loc[1]
        v_accuracy = v_fresh_loc[2] if len(v_fresh_loc) > 2 else None
        v_acc_str  = f"+-{v_accuracy:.0f}m" if v_accuracy else "unknown"
        v_count = st.session_state.voice_update_count + 1
        v_ts    = datetime.now().strftime("%H:%M:%S")

        v_location_box.info(f"🎙️ Voice Update #{v_count} at {v_ts} | {v_lat:.6f}, {v_lon:.6f} | accuracy {v_acc_str}")

        if v_count == 1:
            with st.spinner("Finding nearest police..."):
                police = find_police(v_lat, v_lon) or find_police(v_lat, v_lon, 15000)
            if police:
                plat, plon, pname, pdist = police
                st.success(f"🚔 {pname} — {pdist:.0f}m away")
                st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")

        # =========================================================
        # --- BACKGROUND AUDIO RECORDING (On trigger & every 10th email) ---
        # =========================================================
        audio_bytes = None
        audio_ext = "webm"
        if v_count == 1 or v_count % 10 == 0:
            audio_b64 = streamlit_js_eval(js_expressions=AUDIO_RECORD_JS, key=f"audio_voice_{v_count}")
            
            if audio_b64 is None:
                st.info("🎙️ Auto-Recording 10 seconds of background audio for evidence... Please hold.")
                st.stop()  # Wait securely for Javascript to resolve

            if isinstance(audio_b64, str) and audio_b64.startswith("data:audio"):
                header = audio_b64.split(",")[0]
                if "mp4" in header: audio_ext = "m4a"
                elif "wav" in header: audio_ext = "wav"
                elif "ogg" in header: audio_ext = "ogg"

                b64_data = audio_b64.split(",")[1]
                audio_bytes = base64.b64decode(b64_data)
                st.success("🎤 Audio recorded successfully and attached to alert.")
            elif isinstance(audio_b64, str) and audio_b64.startswith("ERROR"):
                st.warning(f"Audio recording failed: {audio_b64}")
        # =========================================================

        with v_result_box.container():
            with st.spinner(f"Sending voice update #{v_count}..."):
                results = send_to_all(v_lat, v_lon, all_contacts, update_num=v_count, accuracy=v_accuracy, voice_triggered=True, trigger_word=trigger_word, audio_data=audio_bytes, audio_ext=audio_ext)
            for r in results:
                if r["success"]: st.success(f"✅ Voice Update #{v_count} sent to {r['name']}")
                else:            st.error(f"❌ Failed - {r['name']}: {r['error']}")

        st.session_state.voice_tracking_locations.append({"update": v_count, "lat": v_lat, "lon": v_lon, "accuracy": v_acc_str, "time": v_ts})
        st.session_state.voice_update_count = v_count
        st.session_state.voice_last_sent    = v_ts

        with v_trail_box.expander(f"📍 Voice trail ({len(st.session_state.voice_tracking_locations)} updates)", expanded=False):
            for entry in reversed(st.session_state.voice_tracking_locations):
                st.markdown(f"**#{entry['update']}** at {entry['time']} - `{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) [Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})")

        v_countdown = st.empty()
        for remaining in range(30, 0, -1):
            if not st.session_state.voice_tracking_active:
                v_countdown.empty(); st.stop()
            v_countdown.info(f"🎙️ Next voice update in {remaining}s... | Last sent: {v_ts}")
            time.sleep(1)
        v_countdown.empty()
        st.rerun()
    else:
        st.error("Could not get GPS location.")
        v_retry = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.voice_tracking_active:
                v_retry.empty(); st.stop()
            v_retry.warning(f"Retrying in {remaining} seconds...")
            time.sleep(1)
        v_retry.empty()
        if st.session_state.voice_tracking_active: st.rerun()


# ===================================================================
# ---------- PANIC BUTTONS ----------
# ===================================================================
st.divider()
st.caption(f"Alert will be sent to {len(all_contacts)} contact(s).")
col1, col2 = st.columns(2)

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
                if r["success"]: st.success(f"Sent to {r['name']}")
                else:            st.error(f"Failed - {r['name']}: {r['error']}")
            with st.spinner("Finding nearest police..."):
                police = find_police(lat, lon) or find_police(lat, lon, 15000)
            if police:
                plat, plon, name, dist = police
                st.success(f"{name} - {dist:.0f}m away")
                st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")
            else: st.error("No police station found nearby.")
            st.session_state.panic_requested = False

with col2:
    if not st.session_state.extreme_active:
        if st.button("EXTREME PANIC - Live Tracking", use_container_width=True):
            st.session_state.extreme_active = True
            st.session_state.update_count   = 0
            st.session_state.tracking_locations = []
            st.rerun()
    else:
        if st.button("STOP TRACKING", use_container_width=True, type="primary"):
            st.session_state.extreme_active = False
            st.success(f"Tracking stopped after {st.session_state.update_count} update(s).")
            st.rerun()

if st.session_state.extreme_active:
    st.divider()
    st.error("EXTREME PANIC ACTIVE - LIVE TRACKING ON")
    st.warning("Location sent every 30 seconds. Press STOP TRACKING above to end.")

    location_box = st.empty(); result_box = st.empty(); trail_box = st.empty()

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
        lat = fresh_loc[0]; lon = fresh_loc[1]
        accuracy = fresh_loc[2] if len(fresh_loc) > 2 else None
        acc_str  = f"+-{accuracy:.0f}m" if accuracy else "unknown"
        count = st.session_state.update_count + 1
        ts    = datetime.now().strftime("%H:%M:%S")

        location_box.info(f"Update #{count} at {ts} | {lat:.6f}, {lon:.6f} | accuracy {acc_str}")

        with result_box.container():
            with st.spinner(f"Sending update #{count}..."):
                results = send_to_all(lat, lon, all_contacts, update_num=count, accuracy=accuracy)
            for r in results:
                if r["success"]: st.success(f"Update #{count} sent to {r['name']}")
                else:            st.error(f"Failed - {r['name']}: {r['error']}")

        st.session_state.tracking_locations.append({"update": count, "lat": lat, "lon": lon, "accuracy": acc_str, "time": ts})
        st.session_state.update_count = count
        st.session_state.last_sent    = ts

        with trail_box.expander(f"Location trail ({len(st.session_state.tracking_locations)} updates)", expanded=False):
            for entry in reversed(st.session_state.tracking_locations):
                st.markdown(f"**#{entry['update']}** at {entry['time']} - `{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) [Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})")

        countdown = st.empty()
        for remaining in range(30, 0, -1):
            if not st.session_state.extreme_active:
                countdown.empty(); st.stop()
            countdown.info(f"Next update in {remaining} seconds... | Last sent: {ts}")
            time.sleep(1)
        countdown.empty()
        st.rerun()
    else:
        st.error("Could not get GPS location. Make sure location permission is granted.")
        retry_box = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.extreme_active:
                retry_box.empty(); st.stop()
            retry_box.warning(f"Retrying in {remaining} seconds...")
            time.sleep(1)
        retry_box.empty()
        if st.session_state.extreme_active: st.rerun()
