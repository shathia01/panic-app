import streamlit as st
import requests
import math
import smtplib
import json
import time
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from streamlit_js_eval import streamlit_js_eval

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
    # Guardian mode states
    ("guardian_active", False),
    ("guardian_session_id", None),
    ("guardian_destination", ""),
    ("guardian_update_count", 0),
    ("guardian_locations", []),
    ("guardian_last_sent", None),
    ("guardian_update_key", 0),
    ("guardian_safe_pressed", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

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

# ---------- READ GUARDIAN SESSION FROM URL PARAMS ----------
query_params = st.query_params
guardian_view_id = query_params.get("guardian", None)

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
               guardian_triggered=False, guardian_session_id=None, destination="",
               journey_safe=False, base_url=""):
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_update = update_num is not None

    if journey_safe:
        subject = "✅ SAFE - Journey Completed - Guardian Alert"
        alert_type = "SAFE"
    elif guardian_triggered:
        subject = f"👁️ GUARDIAN MODE - Live Journey Tracking Started"
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

    # Guardian live tracking link
    guardian_link = ""
    guardian_html_block = ""
    if guardian_triggered and guardian_session_id and base_url:
        guardian_link = f"{base_url}?guardian={guardian_session_id}"
        guardian_html_block = f"""
        <div style="background:#e8f5e9;border-left:4px solid #2e7d32;padding:15px;border-radius:5px;margin:15px 0;">
            <p style="margin:0;font-size:15px;"><b>🔴 LIVE TRACKING LINK</b><br>
            Open this link to watch their journey in real-time:<br>
            <a href="{guardian_link}" style="color:#1565c0;word-break:break-all;">{guardian_link}</a><br>
            <small>This link updates every 10 seconds with their live location.</small>
            </p>
        </div>"""

    safe_html_block = ""
    if journey_safe:
        safe_html_block = """
        <div style="background:#e8f5e9;border:2px solid #2e7d32;padding:15px;border-radius:8px;margin:15px 0;text-align:center;">
            <h2 style="color:#2e7d32;margin:0;">✅ THEY ARE SAFE</h2>
            <p style="margin:5px 0;">The user has confirmed they reached their destination safely.</p>
        </div>"""

    plain_guardian = f"\n🔴 LIVE TRACKING LINK: {guardian_link}\nOpen to watch their journey in real-time.\n" if guardian_link else ""
    plain_safe = "\n✅ THE USER HAS CONFIRMED THEY ARE SAFE AND REACHED THEIR DESTINATION.\n" if journey_safe else ""
    dest_text = f"\nDestination: {destination}" if destination else ""

    plain = f"""{'✅ SAFE ARRIVAL CONFIRMED' if journey_safe else ('👁️ GUARDIAN LIVE MONITORING STARTED' if guardian_triggered else ('📳 MOTION ALERT' if motion_triggered else ('🎙️ VOICE ALERT' if voice_triggered else ('LIVE UPDATE #' + str(update_num) if is_update else 'EMERGENCY ALERT'))))}

Dear {recipient_name},

{'The user has confirmed they reached their destination safely. Journey monitoring has ended.' if journey_safe else ('Guardian Live Monitoring has started. You can now track their journey in real-time.' if guardian_triggered else ('Rapid device shaking detected.' if motion_triggered else (f'Distress word "{trigger_word}" detected.' if voice_triggered else ('Live tracking update.' if is_update else 'Emergency Panic Button was activated.'))))}
{plain_safe}{plain_guardian}{dest_text}

Location: {lat:.6f}, {lon:.6f}
Accuracy: {acc_text}
Google Maps: {maps_link}
Time: {timestamp}
"""

    color = "#2e7d32" if journey_safe else ("#1a6b3c" if guardian_triggered else ("#7B3F00" if motion_triggered else ("#4a0080" if voice_triggered else ("#8B0000" if is_update else "red"))))
    header_text = (
        "✅ SAFE — Journey Completed" if journey_safe else
        ("👁️ Guardian Mode — Live Journey Started" if guardian_triggered else
         ("📳 MOTION ALERT" if motion_triggered else
          (f'🎙️ VOICE ALERT: "{trigger_word}"' if voice_triggered else
           (f"LIVE UPDATE #{update_num}" if is_update else "Emergency Alert"))))
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f8f8f8;padding:20px;">
    <div style="max-width:520px;margin:auto;background:white;border-radius:10px;
                border-top:6px solid {color};padding:30px;
                box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <h1 style="color:{color};text-align:center;">{header_text}</h1>
        <p>Dear <b>{recipient_name}</b>,</p>
        {safe_html_block}
        {guardian_html_block}
        <p>
            {'The user has confirmed they reached their destination safely. Journey monitoring has ended.' if journey_safe else
             ('Guardian Live Monitoring has been activated. Click the live tracking link above to follow their journey.' if guardian_triggered else
              ('Rapid shaking/running detected on device.' if motion_triggered else
               (f'Distress word <b>"{trigger_word}"</b> detected.' if voice_triggered else
                ('<b>LIVE TRACKING ACTIVE</b> — latest position below.' if is_update else 'Emergency Panic Button was activated.'))))}
        </p>
        {'<p style="color:#2e7d32;font-size:17px;"><b>Destination:</b> ' + destination + '</p>' if destination and not journey_safe else ''}
        <div style="background:#fff0f0;border-left:4px solid {color};
                    padding:15px;border-radius:5px;margin:20px 0;">
            <p style="margin:0;font-size:15px;">
                Location:<br>
                Lat: <code>{lat:.6f}</code><br>
                Lon: <code>{lon:.6f}</code><br>
                <small>GPS Accuracy: {acc_text}</small><br>
                <small>Sent: {timestamp}</small>
            </p>
        </div>
        <a href="{maps_link}" style="display:block;text-align:center;
           background:{color};color:white;padding:14px 20px;
           border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold;margin-top:10px;">
            Open Location on Google Maps
        </a>
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
                guardian_triggered=False, guardian_session_id=None, destination="",
                journey_safe=False, base_url=""):
    results = []
    for c in contacts:
        success, error = send_email(
            c["name"], c["email"], lat, lon,
            update_num, accuracy, voice_triggered, trigger_word, motion_triggered,
            guardian_triggered, guardian_session_id, destination, journey_safe, base_url
        )
        results.append({"name": c["name"], "email": c["email"], "success": success, "error": error})
    return results

# ---------- BUILD CONTACT LIST ----------
all_contacts = list(DEFAULT_CONTACTS)
for c in my_contacts:
    if not any(x["email"].lower() == c["email"].lower() for x in all_contacts):
        all_contacts.append(c)

# ===================================================================
# ---------- GUARDIAN VIEW MODE (when opened via link) ----------
# ===================================================================
if guardian_view_id:
    st.title("👁️ Guardian Live Monitoring")
    st.info(f"**Session ID:** `{guardian_view_id}`")
    st.caption("This page auto-refreshes every 10 seconds to show the latest location.")

    # Read guardian data from localStorage
    guardian_data_raw = streamlit_js_eval(
        js_expressions=f"localStorage.getItem('guardian_{guardian_view_id}')",
        key="guardian_view_read"
    )

    if guardian_data_raw and guardian_data_raw != "null":
        try:
            gdata = json.loads(guardian_data_raw)
            locations = gdata.get("locations", [])
            destination = gdata.get("destination", "")
            status = gdata.get("status", "active")
            started = gdata.get("started", "")

            if status == "safe":
                st.success("✅ JOURNEY COMPLETE — User has confirmed they are SAFE!")
            else:
                st.error("🔴 LIVE TRACKING ACTIVE")

            if destination:
                st.markdown(f"**📍 Destination:** {destination}")
            st.markdown(f"**⏱️ Journey started:** {started}")
            st.markdown(f"**📡 Total updates:** {len(locations)}")

            if locations:
                latest = locations[-1]
                lat = latest["lat"]
                lon = latest["lon"]
                ts = latest["time"]
                acc = latest.get("accuracy", "unknown")

                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("Latitude", f"{lat:.6f}")
                with col_b:
                    st.metric("Longitude", f"{lon:.6f}")

                st.markdown(f"**Last update:** {ts} | **Accuracy:** {acc}")

                maps_url = f"https://maps.google.com/?q={lat},{lon}"
                st.link_button("📍 Open Live Location on Google Maps", maps_url, use_container_width=True)

                # Show trail
                with st.expander(f"📍 Full location trail ({len(locations)} points)", expanded=False):
                    for entry in reversed(locations):
                        st.markdown(
                            f"**#{entry.get('update', '?')}** at {entry['time']} — "
                            f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry.get('accuracy','?')}) "
                            f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                        )

                # Embed map iframe
                st.markdown("### 🗺️ Live Map")
                st.components.v1.iframe(
                    f"https://maps.google.com/maps?q={lat},{lon}&z=16&output=embed",
                    height=400
                )

            else:
                st.warning("Waiting for first location update...")

        except Exception as e:
            st.error(f"Error reading tracking data: {e}")
    else:
        st.warning("No tracking data found yet. The user may not have started sharing, or the session has expired.")
        st.caption("This page will auto-refresh. Ask the user to start Guardian Mode and share the link.")

    # Auto-refresh every 10 seconds
    st.markdown("---")
    st.caption("🔄 Auto-refreshing every 10 seconds...")
    streamlit_js_eval(
        js_expressions="setTimeout(() => window.location.reload(), 10000); true",
        key="guardian_auto_refresh"
    )
    st.stop()


# ===================================================================
# ---------- MY CONTACT SECTION ----------
# ===================================================================
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
st.subheader("👁️ Guardian Live Monitoring Mode")

st.markdown("""
<div style="background:linear-gradient(135deg,#1a6b3c,#0d4a6b);color:white;padding:16px 20px;border-radius:10px;margin-bottom:10px;">
    <b>🛡️ Safe Journey Tracker</b><br>
    <small>Share a live tracking link with your emergency contacts. They can watch your journey in real-time 
    until you press <b>"I'm Safe"</b>. Location updates every 10 seconds, non-stop.</small>
</div>
""", unsafe_allow_html=True)

# Get base URL for shareable link
base_url_raw = streamlit_js_eval(
    js_expressions="window.location.origin + window.location.pathname",
    key="get_base_url"
)
base_url = base_url_raw if base_url_raw else ""

g_col1, g_col2 = st.columns([3, 1])

with g_col1:
    if st.session_state.guardian_active:
        st.error(f"🔴 GUARDIAN MODE ACTIVE — Tracking non-stop | Updates: {st.session_state.guardian_update_count}")
    else:
        st.info("🟢 Guardian Mode is OFF — Press Start to begin a monitored journey")

with g_col2:
    if not st.session_state.guardian_active:
        if st.button("🛡️ Start Guardian", use_container_width=True, type="primary"):
            new_id = str(uuid.uuid4())[:8].upper()
            st.session_state.guardian_session_id = new_id
            st.session_state.guardian_active = True
            st.session_state.guardian_update_count = 0
            st.session_state.guardian_locations = []
            st.session_state.guardian_update_key = 0
            st.session_state.guardian_safe_pressed = False
            st.rerun()
    else:
        if st.button("✅ I'm Safe!", use_container_width=True, type="primary"):
            st.session_state.guardian_safe_pressed = True
            st.rerun()

# ---------- GUARDIAN DESTINATION INPUT ----------
if not st.session_state.guardian_active:
    st.session_state.guardian_destination = st.text_input(
        "📍 Where are you going? (optional)",
        placeholder="e.g. KLCC, University, Home",
        value=st.session_state.guardian_destination
    )

# ===================================================================
# ---------- GUARDIAN ACTIVE LOOP ----------
# ===================================================================
if st.session_state.guardian_active:
    session_id = st.session_state.guardian_session_id
    destination = st.session_state.guardian_destination

    # Show shareable link prominently
    if base_url:
        share_link = f"{base_url}?guardian={session_id}"
        st.markdown("### 🔗 Share this link with your Guardian(s):")
        st.code(share_link, language=None)
        st.caption("Anyone with this link can watch your location update live every 10 seconds.")
        st.link_button("📲 Open Guardian View", share_link, use_container_width=False)

    if destination:
        st.info(f"📍 Destination: **{destination}**")

    # Handle "I'm Safe" confirmation
    if st.session_state.guardian_safe_pressed:
        st.success("✅ Sending SAFE confirmation to all contacts...")

        safe_loc = streamlit_js_eval(
            js_expressions="""
            new Promise(resolve => {
                navigator.geolocation.getCurrentPosition(
                    p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                    () => resolve(null),
                    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
                );
            })""",
            key="guardian_safe_loc"
        )

        safe_lat = safe_loc[0] if safe_loc else (st.session_state.guardian_locations[-1]["lat"] if st.session_state.guardian_locations else 0)
        safe_lon = safe_loc[1] if safe_loc else (st.session_state.guardian_locations[-1]["lon"] if st.session_state.guardian_locations else 0)

        # Mark session as safe in localStorage
        safe_payload = json.dumps({
            "locations": st.session_state.guardian_locations,
            "destination": destination,
            "status": "safe",
            "started": st.session_state.guardian_locations[0]["time"] if st.session_state.guardian_locations else datetime.now().strftime("%H:%M:%S"),
            "ended": datetime.now().strftime("%H:%M:%S")
        }).replace("'", "\\'")
        streamlit_js_eval(
            js_expressions=f"localStorage.setItem('guardian_{session_id}', '{safe_payload}'); true",
            key="guardian_mark_safe"
        )

        # Send safe email to all contacts
        with st.spinner("Notifying all contacts that you're safe..."):
            results = send_to_all(
                safe_lat, safe_lon, all_contacts,
                journey_safe=True,
                destination=destination,
                base_url=base_url
            )
        for r in results:
            if r["success"]:
                st.success(f"✅ Safe notification sent to {r['name']}")
            else:
                st.error(f"❌ Failed - {r['name']}: {r['error']}")

        total = st.session_state.guardian_update_count
        st.session_state.guardian_active = False
        st.session_state.guardian_safe_pressed = False
        st.session_state.guardian_update_count = 0
        st.session_state.guardian_locations = []
        st.balloons()
        st.success(f"🛡️ Guardian Mode ended safely after {total} location update(s). Stay safe!")
        st.stop()

    # ---------- GUARDIAN LOCATION UPDATE LOOP ----------
    g_location_box = st.empty()
    g_trail_box = st.empty()

    g_fresh_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve(null),
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        })""",
        key=f"guardian_loc_{st.session_state.guardian_update_key}"
    )

    if g_fresh_loc:
        g_lat = g_fresh_loc[0]
        g_lon = g_fresh_loc[1]
        g_accuracy = g_fresh_loc[2] if len(g_fresh_loc) > 2 else None
        g_acc_str = f"+-{g_accuracy:.0f}m" if g_accuracy else "unknown"
        g_count = st.session_state.guardian_update_count + 1
        g_ts = datetime.now().strftime("%H:%M:%S")

        # Store location entry
        new_entry = {
            "update": g_count,
            "lat": g_lat,
            "lon": g_lon,
            "accuracy": g_acc_str,
            "time": g_ts
        }
        st.session_state.guardian_locations.append(new_entry)
        st.session_state.guardian_update_count = g_count
        st.session_state.guardian_last_sent = g_ts

        # Save to localStorage so guardian view can read it
        payload = json.dumps({
            "locations": st.session_state.guardian_locations,
            "destination": destination,
            "status": "active",
            "started": st.session_state.guardian_locations[0]["time"] if st.session_state.guardian_locations else g_ts,
        }).replace("'", "\\'")
        streamlit_js_eval(
            js_expressions=f"localStorage.setItem('guardian_{session_id}', '{payload}'); true",
            key=f"guardian_save_{g_count}"
        )

        # On first update, send initial email with tracking link to all contacts
        if g_count == 1:
            with st.spinner("Sending Guardian alert with live link to all contacts..."):
                results = send_to_all(
                    g_lat, g_lon, all_contacts,
                    guardian_triggered=True,
                    guardian_session_id=session_id,
                    destination=destination,
                    base_url=base_url
                )
            for r in results:
                if r["success"]:
                    st.success(f"✅ Guardian link sent to {r['name']}")
                else:
                    st.error(f"❌ Failed - {r['name']}: {r['error']}")

        g_location_box.info(
            f"👁️ Guardian Update #{g_count} at {g_ts} | "
            f"{g_lat:.6f}, {g_lon:.6f} | Accuracy: {g_acc_str}"
        )

        with g_trail_box.expander(
            f"📍 Journey trail ({len(st.session_state.guardian_locations)} points)",
            expanded=False
        ):
            for entry in reversed(st.session_state.guardian_locations):
                st.markdown(
                    f"**#{entry['update']}** at {entry['time']} — "
                    f"`{entry['lat']:.5f}, {entry['lon']:.5f}` ({entry['accuracy']}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )

        # Countdown 10 seconds before next update
        g_countdown = st.empty()
        for remaining in range(10, 0, -1):
            if not st.session_state.guardian_active or st.session_state.guardian_safe_pressed:
                g_countdown.empty()
                st.rerun()
            g_countdown.caption(f"🔄 Next location update in {remaining}s... | Guardian tracking active")
            time.sleep(1)
        g_countdown.empty()

        st.session_state.guardian_update_key += 1
        st.rerun()

    else:
        st.warning("⚠️ Could not get GPS location. Retrying in 5 seconds...")
        time.sleep(5)
        st.session_state.guardian_update_key += 1
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
