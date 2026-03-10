import streamlit as st
import requests
import math
import smtplib
import json
import time
import uuid
import os
import tempfile
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from streamlit_js_eval import streamlit_js_eval

# ===================================================================
# ---------- GUARDIAN LIVE VIEWER (contact's view via ?guardian=ID) -
# ===================================================================
query_params = st.query_params
guardian_view_id = query_params.get("guardian", None)

if guardian_view_id:
    loc_file = os.path.join(tempfile.gettempdir(), f"guardian_{guardian_view_id}.json")

    def load_guardian_data(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return None

    data = load_guardian_data(loc_file)

    if data is None:
        st.title("🛡️ Guardian Live Tracker")
        st.error("Session not found or has ended.")
        st.info("The journey may have finished, or the session is still starting. Try refreshing in a few seconds.")
        st.stop()

    dest        = data.get("destination", "Unknown")
    eta_str     = data.get("eta_str", "N/A")
    status      = data.get("status", "active")
    lat         = data.get("lat")
    lon         = data.get("lon")
    accuracy    = data.get("accuracy")
    last_updated = data.get("last_updated", "Unknown")
    trail       = data.get("trail", [])
    session_id  = data.get("session_id", guardian_view_id)

    if status == "arrived":
        st.title("✅ Safe Arrival Confirmed")
        st.success(f"The person has safely arrived at **{dest}**. Guardian session ended.")
        st.stop()

    if status == "overdue":
        st.title("⚠️ OVERDUE ALERT")
        st.error(f"Expected at **{dest}** by **{eta_str}** — arrival NOT confirmed!")
        st.warning("Please contact them immediately or call emergency services (999).")
    else:
        st.title(f"🛡️ Live Journey — {dest}")
        st.caption(f"Session `{session_id}` · ETA: {eta_str} · Last update: {last_updated}")

    if lat and lon:
        maps_url      = f"https://maps.google.com/?q={lat},{lon}"
        directions_url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"

        st.components.v1.html(
            f"""<div style="border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.15);margin-bottom:12px;">
                <iframe width="100%" height="420" frameborder="0" style="border:0;"
                    src="https://maps.google.com/maps?q={lat},{lon}&z=16&output=embed"
                    allowfullscreen></iframe></div>""",
            height=435,
        )

        ca, cb = st.columns(2)
        with ca:
            st.link_button("📍 Open in Google Maps", maps_url, use_container_width=True)
        with cb:
            st.link_button("🧭 Get Directions to Them", directions_url, use_container_width=True)

        acc_text = f"±{accuracy:.0f}m" if accuracy else "N/A"
        st.info(
            f"**Current position:** `{lat:.6f}, {lon:.6f}`  \n"
            f"**GPS accuracy:** {acc_text}  \n"
            f"**Last updated:** {last_updated}"
        )

        if trail:
            with st.expander(f"📍 Location history ({len(trail)} points)", expanded=False):
                for entry in reversed(trail[-30:]):
                    st.markdown(
                        f"🕐 {entry['time']} — `{entry['lat']:.5f}, {entry['lon']:.5f}` "
                        f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                    )
    else:
        st.warning("⏳ Waiting for first GPS fix...")

    # Auto-refresh every 5 seconds
    st.components.v1.html(
        """<script>setTimeout(function(){ window.location.reload(); }, 5000);</script>
        <p style="color:#888;font-size:12px;text-align:center;margin-top:4px;">
            🔄 Auto-refreshes every 5 seconds</p>""",
        height=35,
    )
    st.stop()


# ===================================================================
# ---------- MAIN APP -----------------------------------------------
# ===================================================================
st.title("🚨 One-Click Emergency Panic Button")

SENDER_EMAIL       = "shathia190304@gmail.com"
SENDER_APP_PASSWORD = "kvskirvfdhsscege"
SENDER_NAME        = "Emergency Alert"

DISTRESS_KEYWORDS = [
    "help", "please", "leave me", "stop", "let me go",
    "get away", "don't touch me", "call police", "save me",
    "emergency", "danger", "scared"
]

DEFAULT_CONTACTS = [
    {"name": "Admin", "email": "shathia190304@gmail.com"},
]

# Session state defaults
_defaults = {
    "extreme_active": False,       "update_count": 0,
    "last_sent": None,             "tracking_locations": [],
    "panic_requested": False,      "panic_key": 0,
    "voice_active": False,         "voice_triggered": False,
    "voice_trigger_word": "",      "voice_trigger_key": 0,
    "voice_tracking_active": False,"voice_update_count": 0,
    "voice_tracking_locations": [],"voice_last_sent": None,
    "motion_monitoring": False,    "motion_triggered": False,
    "motion_tracking_active": False,"motion_update_count": 0,
    "motion_tracking_locations": [],"motion_last_sent": None,
    "motion_listen_key": 0,
    # Guardian
    "guardian_active": False,      "guardian_session_id": "",
    "guardian_destination": "",    "guardian_eta_minutes": 30,
    "guardian_start_time": None,   "guardian_tracking_locations": [],
    "guardian_arrived": False,     "guardian_loc_key": 0,
    "guardian_overdue_alerted": False,
    "guardian_initial_email_sent": False,
    "_show_guardian_setup": False, "_guardian_send_arrival": False,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Read contacts from localStorage
raw = streamlit_js_eval(js_expressions="localStorage.getItem('emergency_my_contacts')", key="read_my_contacts")
my_contacts = []
if raw and raw != "null":
    try:
        parsed = json.loads(raw)
        my_contacts = [parsed] if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
    except Exception:
        pass

# ---------- Helpers ----------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_police(lat, lon, radius=5000):
    q = f'[out:json][timeout:10];(node["amenity"="police"](around:{radius},{lat},{lon});way["amenity"="police"](around:{radius},{lat},{lon}););out center;'
    try:
        res = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=25).json()
        best, bd = None, float("inf")
        for el in res.get("elements", []):
            plat = el.get("lat") or el.get("center", {}).get("lat")
            plon = el.get("lon") or el.get("center", {}).get("lon")
            if plat is None: continue
            d = haversine(lat, lon, plat, plon)
            if d < bd:
                bd = d; best = (plat, plon, el.get("tags", {}).get("name", "Police Station"), d)
        return best
    except Exception:
        return None

def get_base_url():
    try:
        host = st.context.headers.get("host", "localhost:8501")
        proto = "https" if ("streamlit.app" in host or "streamlitapp" in host) else "http"
        return f"{proto}://{host}"
    except Exception:
        return "http://localhost:8501"

def write_guardian_location(sid, lat, lon, accuracy, destination, eta_str, status="active", trail=None, start_time=None):
    path = os.path.join(tempfile.gettempdir(), f"guardian_{sid}.json")
    with open(path, "w") as f:
        json.dump({
            "session_id": sid, "lat": lat, "lon": lon, "accuracy": accuracy,
            "destination": destination, "eta_str": eta_str, "status": status,
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            "trail": (trail or [])[-100:], "start_time": start_time,
        }, f)

def delete_guardian_file(sid):
    try: os.remove(os.path.join(tempfile.gettempdir(), f"guardian_{sid}.json"))
    except Exception: pass

def compute_eta_str(start_iso, mins):
    try: return (datetime.fromisoformat(start_iso) + timedelta(minutes=mins)).strftime("%I:%M %p")
    except Exception: return "N/A"

def compute_eta_dt(start_iso, mins):
    try: return datetime.fromisoformat(start_iso) + timedelta(minutes=mins)
    except Exception: return None

# ---------- Email ----------
def send_email(rname, remail, lat, lon, update_num=None, accuracy=None,
               voice_triggered=False, trigger_word="", motion_triggered=False,
               guardian_triggered=False, guardian_info=None):
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    acc_text  = f"±{accuracy:.0f}m" if accuracy else "N/A"
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if guardian_triggered and guardian_info:
        g       = guardian_info
        action  = g.get("action", "start")
        dest    = g.get("destination", "Unknown")
        eta_s   = g.get("eta_str", "N/A")
        live_lk = g.get("live_link", maps_link)

        if action == "start":
            subj   = f"🛡️ Guardian Mode Started — Journey to {dest}"
            color  = "#1a5276"; hdr = "🛡️ Guardian Journey Started"
            body   = f"""<p>Dear <b>{rname}</b>,</p>
                <p>Someone has started a journey and asked you to be their guardian until they arrive safely.</p>
                <table style="width:100%;border-collapse:collapse;margin:16px 0;">
                    <tr><td style="color:#555;padding:5px 0;">📍 Destination</td><td><b>{dest}</b></td></tr>
                    <tr><td style="color:#555;padding:5px 0;">⏱️ ETA</td><td><b>{eta_s}</b></td></tr>
                    <tr><td style="color:#555;padding:5px 0;">🕐 Started</td><td>{ts}</td></tr>
                </table>
                <p>Click below to <b>watch their live location updating every 5 seconds</b>. No app needed — opens in any browser.</p>
                <a href="{live_lk}" style="display:block;text-align:center;background:#1a5276;color:white;
                   padding:16px;border-radius:8px;text-decoration:none;font-size:17px;font-weight:bold;margin:20px 0;">
                    🔴 WATCH LIVE JOURNEY</a>
                <p style="font-size:13px;color:#777;">You'll get a ✅ arrival email when they arrive safely,
                or a ⚠️ OVERDUE alert if they miss their ETA.</p>"""
            plain = f"Guardian started. Destination: {dest} | ETA: {eta_s}\nWatch live: {live_lk}"

        elif action == "arrived":
            subj   = f"✅ Safe Arrival Confirmed — {dest}"
            color  = "#1e8449"; hdr = "✅ Arrived Safely!"
            body   = f"<p>Dear <b>{rname}</b>,</p><p>🎉 Safe arrival at <b>{dest}</b> confirmed at {ts}.</p><p>Guardian monitoring has ended. No further action needed.</p>"
            plain  = f"Safe arrival confirmed at {dest} at {ts}."

        elif action == "overdue":
            subj   = f"⚠️ OVERDUE — Did NOT arrive at {dest} by {eta_s}"
            color  = "#c0392b"; hdr = "⚠️ OVERDUE — Missed ETA"
            body   = f"""<p>Dear <b>{rname}</b>,</p>
                <p><b>⚠️ ALERT:</b> Expected at <b>{dest}</b> by <b>{eta_s}</b> — arrival <b>NOT confirmed</b>.</p>
                <p>Please contact them immediately or call emergency services (<b>999</b>).</p>
                <div style="background:#fff0f0;border-left:4px solid #c0392b;padding:12px;border-radius:4px;margin:16px 0;">
                    Last known: <code>{lat:.6f}, {lon:.6f}</code> ({acc_text})</div>
                <a href="{maps_link}" style="display:block;text-align:center;background:#c0392b;color:white;
                   padding:14px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold;">
                    📍 Last Known Location</a>"""
            plain  = f"OVERDUE: Not arrived at {dest} by {eta_s}. Call 999. Last location: {maps_link}"
        else:
            return True, ""

        html = f"""<html><body style="font-family:Arial,sans-serif;background:#f0f4f8;padding:20px;">
            <div style="max-width:520px;margin:auto;background:white;border-radius:12px;
                        border-top:6px solid {color};padding:30px;box-shadow:0 2px 10px rgba(0,0,0,0.1);">
                <h1 style="color:{color};text-align:center;font-size:22px;">{hdr}</h1>{body}
            </div></body></html>"""
    else:
        # Panic / motion / voice
        is_upd = update_num is not None
        if motion_triggered:
            subj = f"📳 MOTION ALERT - Shaking/Running Detected"
        elif voice_triggered:
            subj = f"🎙️ VOICE ALERT - Distress Word Detected"
        elif is_upd:
            subj = f"LIVE UPDATE #{update_num} - Emergency Alert"
        else:
            subj = "Emergency Alert - Urgent Assistance Required"

        color = "#7B3F00" if motion_triggered else ("#4a0080" if voice_triggered else ("#8B0000" if is_upd else "red"))
        hdr   = ('📳 MOTION ALERT' if motion_triggered else
                 (f'🎙️ VOICE ALERT: "{trigger_word}"' if voice_triggered else
                  (f'LIVE UPDATE #{update_num}' if is_upd else 'Emergency Alert')))
        bd    = ('Rapid shaking/running detected.' if motion_triggered else
                 (f'Distress word "<b>{trigger_word}</b>" detected.' if voice_triggered else
                  ('Live location update.' if is_upd else 'Panic button activated.')))
        plain = f"{hdr}\nDear {rname},\n{bd}\nCall 999.\nLocation: {lat:.6f},{lon:.6f}\nMaps: {maps_link}\nTime: {ts}"
        html  = f"""<html><body style="font-family:Arial,sans-serif;background:#f8f8f8;padding:20px;">
            <div style="max-width:500px;margin:auto;background:white;border-radius:10px;
                        border-top:6px solid {color};padding:30px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
                <h1 style="color:{color};text-align:center;">{hdr}</h1>
                <p>Dear <b>{rname}</b>,</p><p>{bd}<br><br>Call emergency services (<b>999</b>) immediately.</p>
                <div style="background:#fff0f0;border-left:4px solid {color};padding:15px;border-radius:5px;margin:20px 0;">
                    <code>{lat:.6f}, {lon:.6f}</code><br><small>{acc_text} · {ts}</small></div>
                <a href="{maps_link}" style="display:block;text-align:center;background:{color};color:white;
                   padding:14px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold;">
                    Open on Google Maps</a>
            </div></body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subj
        msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"]      = remail
        msg["Reply-To"]= SENDER_EMAIL
        msg["Date"]    = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            s.sendmail(SENDER_EMAIL, remail, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)

def send_to_all(lat, lon, contacts, update_num=None, accuracy=None,
                voice_triggered=False, trigger_word="", motion_triggered=False,
                guardian_triggered=False, guardian_info=None):
    return [
        {"name": c["name"], "email": c["email"],
         **dict(zip(("success","error"), send_email(
             c["name"], c["email"], lat, lon, update_num, accuracy,
             voice_triggered, trigger_word, motion_triggered,
             guardian_triggered, guardian_info)))}
        for c in contacts
    ]

# Build full contact list
all_contacts = list(DEFAULT_CONTACTS)
for c in my_contacts:
    if not any(x["email"].lower() == c["email"].lower() for x in all_contacts):
        all_contacts.append(c)


# ===================================================================
# ---------- MY CONTACTS --------------------------------------------
# ===================================================================
st.divider()
st.subheader("📋 My Emergency Contacts")
if my_contacts:
    st.success(f"{len(my_contacts)} personal contact(s) saved.")
    for i, c in enumerate(my_contacts):
        cn, ce, cd = st.columns([2, 3, 1])
        with cn: st.write(f"**{c['name']}**")
        with ce: st.write(c["email"])
        with cd:
            if st.button("🗑️ Remove", key=f"remove_{i}"):
                updated = [x for j, x in enumerate(my_contacts) if j != i]
                streamlit_js_eval(js_expressions=f"localStorage.setItem('emergency_my_contacts','{json.dumps(updated).replace(chr(39),chr(92)+chr(39))}');true", key=f"del_{i}")
                st.info("Removed. Refresh to confirm.")
else:
    st.info("No personal contacts yet. Add one below.")

st.markdown("##### ➕ Add a Contact")
with st.form("add_contact_form", clear_on_submit=True):
    cn, ce = st.columns(2)
    with cn: reg_name  = st.text_input("Name",  placeholder="e.g. Sarah")
    with ce: reg_email = st.text_input("Email", placeholder="e.g. sarah@gmail.com")
    if st.form_submit_button("Save Contact"):
        if reg_name and reg_email:
            if any(c["email"].lower() == reg_email.lower() for c in my_contacts):
                st.warning("That email already exists.")
            else:
                updated = my_contacts + [{"name": reg_name, "email": reg_email}]
                streamlit_js_eval(js_expressions=f"localStorage.setItem('emergency_my_contacts','{json.dumps(updated).replace(chr(39),chr(92)+chr(39))}');true", key="save_contact")
                st.success(f"Saved {reg_name}! Refresh to confirm.")
        else:
            st.warning("Please fill in both fields.")


# ===================================================================
# =================== GUARDIAN LIVE MONITORING ======================
# ===================================================================
st.divider()
st.subheader("🛡️ Guardian Live Monitoring Mode")
st.caption(
    "Contacts receive a link that shows your real-time location on a live map — "
    "updating every 5 seconds, no app needed. They're notified when you arrive safely, "
    "or alerted automatically if you miss your ETA."
)

gc1, gc2, gc3 = st.columns([3, 1, 1])
with gc1:
    if st.session_state.guardian_active and not st.session_state.guardian_arrived:
        eta_s = compute_eta_str(st.session_state.guardian_start_time, st.session_state.guardian_eta_minutes)
        st.success(f"🛡️ **Guardian Active** — **{st.session_state.guardian_destination}** · ETA {eta_s}")
    elif st.session_state.guardian_arrived:
        st.success("✅ Safe arrival confirmed. Guardian Mode ended.")
    else:
        st.info("🛡️ Guardian Mode is OFF")

with gc2:
    if not st.session_state.guardian_active and not st.session_state.guardian_arrived:
        if st.button("🛡️ Start Guardian", use_container_width=True, type="primary"):
            st.session_state._show_guardian_setup = True
            st.rerun()

with gc3:
    if st.session_state.guardian_active and not st.session_state.guardian_arrived:
        if st.button("✅ Arrived Safely", use_container_width=True, type="primary"):
            st.session_state.guardian_arrived  = True
            st.session_state.guardian_active   = False
            st.session_state._guardian_send_arrival = True
            st.rerun()

if st.session_state.guardian_arrived:
    if st.button("🔄 Start New Journey", use_container_width=True):
        if st.session_state.guardian_session_id:
            delete_guardian_file(st.session_state.guardian_session_id)
        for k in ["guardian_active","guardian_arrived","guardian_session_id","guardian_destination",
                  "guardian_start_time","guardian_tracking_locations","guardian_overdue_alerted",
                  "guardian_initial_email_sent","_show_guardian_setup","_guardian_send_arrival"]:
            v = _defaults.get(k, False)
            st.session_state[k] = v
        st.session_state.guardian_eta_minutes = 30
        st.session_state.guardian_loc_key = 0
        st.rerun()

# Setup form
if st.session_state._show_guardian_setup and not st.session_state.guardian_active:
    with st.container(border=True):
        st.markdown("#### 🗺️ Journey Details")
        g_dest = st.text_input("📍 Destination", placeholder="e.g. Mid Valley Mall, KL")
        g_eta  = st.slider("⏱️ Estimated travel time (minutes)", 5, 180, 30, 5)
        st.markdown(f"**Guardians:** {len(all_contacts)} contact(s) will receive a live link")
        for c in all_contacts:
            st.caption(f"  • {c['name']} ({c['email']})")
        sb1, sb2 = st.columns(2)
        with sb1:
            if st.button("🚀 Begin Journey", use_container_width=True, type="primary"):
                if not g_dest.strip():
                    st.warning("Please enter a destination.")
                else:
                    sid = str(uuid.uuid4()).replace("-","")[:12].upper()
                    st.session_state.guardian_active               = True
                    st.session_state.guardian_session_id           = sid
                    st.session_state.guardian_destination          = g_dest.strip()
                    st.session_state.guardian_eta_minutes          = g_eta
                    st.session_state.guardian_start_time           = datetime.now().isoformat()
                    st.session_state.guardian_tracking_locations   = []
                    st.session_state.guardian_overdue_alerted      = False
                    st.session_state.guardian_arrived              = False
                    st.session_state.guardian_initial_email_sent   = False
                    st.session_state.guardian_loc_key              = 0
                    st.session_state._show_guardian_setup          = False
                    st.rerun()
        with sb2:
            if st.button("Cancel", use_container_width=True):
                st.session_state._show_guardian_setup = False
                st.rerun()


# ===================================================================
# ---------- GUARDIAN CONTINUOUS LOCATION BROADCAST ----------------
# ===================================================================
if st.session_state.guardian_active and not st.session_state.guardian_arrived:
    st.divider()
    sid   = st.session_state.guardian_session_id
    dest  = st.session_state.guardian_destination
    eta_s = compute_eta_str(st.session_state.guardian_start_time, st.session_state.guardian_eta_minutes)
    eta_dt = compute_eta_dt(st.session_state.guardian_start_time, st.session_state.guardian_eta_minutes)
    base_url  = get_base_url()
    live_link = f"{base_url}/?guardian={sid}"

    # Info panel
    with st.container(border=True):
        st.markdown("#### 🔴 Live Broadcasting")
        st.markdown(f"**Destination:** {dest} &nbsp;·&nbsp; **ETA:** {eta_s} &nbsp;·&nbsp; **Session:** `{sid}`")
        st.code(live_link, language=None)
        st.caption("👆 This link is emailed to your contacts automatically. They open it to watch you live.")

    # ETA progress bar
    if eta_dt:
        start_dt   = datetime.fromisoformat(st.session_state.guardian_start_time)
        total_s    = max(1, (eta_dt - start_dt).total_seconds())
        elapsed_s  = (datetime.now() - start_dt).total_seconds()
        pct        = min(1.0, max(0.0, elapsed_s / total_s))
        rem_mins   = max(0, int((eta_dt - datetime.now()).total_seconds() / 60))
        st.progress(pct, text=f"⏱️ {rem_mins} min remaining to {dest} · Press ✅ Arrived Safely when done")

    # Overdue check (fires once)
    if eta_dt and datetime.now() > eta_dt and not st.session_state.guardian_overdue_alerted:
        st.error(f"⚠️ Passed ETA ({eta_s})! Sending overdue alert to contacts...")
        st.session_state.guardian_overdue_alerted = True

    g_status = st.empty()
    g_trail  = st.empty()

    # ---------- Get fresh GPS location ----------
    g_loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                err => resolve(null),
                { enableHighAccuracy: true, timeout: 8000, maximumAge: 2000 }
            );
        })""",
        key=f"guardian_live_{st.session_state.guardian_loc_key}"
    )

    if g_loc:
        g_lat, g_lon = g_loc[0], g_loc[1]
        g_acc = g_loc[2] if len(g_loc) > 2 else None
        g_ts  = datetime.now().strftime("%H:%M:%S")

        trail = st.session_state.guardian_tracking_locations
        trail.append({"lat": g_lat, "lon": g_lon, "time": g_ts, "accuracy": g_acc})
        if len(trail) > 100:
            trail = trail[-100:]
        st.session_state.guardian_tracking_locations = trail

        # Determine status string
        gstatus = "overdue" if st.session_state.guardian_overdue_alerted else "active"

        # Write to server temp file — contacts' viewer page reads this
        write_guardian_location(sid, g_lat, g_lon, g_acc, dest, eta_s, gstatus, trail,
                                st.session_state.guardian_start_time)

        acc_disp = f"±{g_acc:.0f}m" if g_acc else "N/A"
        g_status.success(
            f"📡 **Broadcasting** · `{g_lat:.6f}, {g_lon:.6f}` · {acc_disp} · "
            f"{g_ts} · {len(trail)} point(s) recorded"
        )

        # Send initial email with live link (once)
        if not st.session_state.guardian_initial_email_sent:
            with st.spinner(f"Sending Guardian link to {len(all_contacts)} contact(s)..."):
                results = send_to_all(
                    g_lat, g_lon, all_contacts, accuracy=g_acc,
                    guardian_triggered=True,
                    guardian_info={"action":"start","destination":dest,"eta_str":eta_s,
                                   "session_id":sid,"live_link":live_link}
                )
            for r in results:
                if r["success"]:
                    st.success(f"📧 Live link sent to **{r['name']}** ({r['email']})")
                else:
                    st.error(f"❌ Failed → {r['name']}: {r['error']}")
            st.session_state.guardian_initial_email_sent = True

        # Send overdue email (once)
        if st.session_state.guardian_overdue_alerted:
            ov_key = f"_overdue_sent_{sid}"
            if not st.session_state.get(ov_key):
                with st.spinner("Sending overdue alert..."):
                    send_to_all(g_lat, g_lon, all_contacts, accuracy=g_acc,
                                guardian_triggered=True,
                                guardian_info={"action":"overdue","destination":dest,"eta_str":eta_s,
                                               "session_id":sid,"live_link":live_link})
                st.session_state[ov_key] = True
                st.warning("⚠️ Overdue alert sent to all contacts.")

        # Trail history
        with g_trail.expander(f"📍 Location history ({len(trail)} points)", expanded=False):
            for entry in reversed(trail[-20:]):
                ad = f"±{entry['accuracy']:.0f}m" if entry.get("accuracy") else "N/A"
                st.markdown(
                    f"🕐 {entry['time']} — `{entry['lat']:.5f}, {entry['lon']:.5f}` ({ad}) "
                    f"[Maps](https://maps.google.com/?q={entry['lat']},{entry['lon']})"
                )

        # Wait 5 s then re-poll location (non-stop loop)
        wait = st.empty()
        for i in range(5, 0, -1):
            if st.session_state.guardian_arrived or not st.session_state.guardian_active:
                wait.empty(); break
            wait.caption(f"📡 Next broadcast in {i}s…")
            time.sleep(1)
        wait.empty()
        st.session_state.guardian_loc_key += 1
        st.rerun()

    else:
        g_status.warning("⚠️ Waiting for GPS fix… (ensure location permission is granted)")
        time.sleep(3)
        st.session_state.guardian_loc_key += 1
        st.rerun()


# ===================================================================
# ---------- GUARDIAN ARRIVAL CONFIRMATION -------------------------
# ===================================================================
if st.session_state._guardian_send_arrival:
    st.divider()
    st.success("✅ Confirming safe arrival and notifying contacts…")
    arr_loc = streamlit_js_eval(
        js_expressions="""new Promise(resolve => {
            navigator.geolocation.getCurrentPosition(
                p => resolve([p.coords.latitude, p.coords.longitude, p.coords.accuracy]),
                () => resolve([0.0, 0.0, null]),
                { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }); })""",
        key="guardian_arrival_loc"
    )
    a_lat = arr_loc[0] if arr_loc else 0.0
    a_lon = arr_loc[1] if arr_loc else 0.0
    a_acc = arr_loc[2] if arr_loc and len(arr_loc) > 2 else None
    sid   = st.session_state.guardian_session_id
    dest  = st.session_state.guardian_destination
    eta_s = compute_eta_str(st.session_state.guardian_start_time, st.session_state.guardian_eta_minutes)

    write_guardian_location(sid, a_lat, a_lon, a_acc, dest, eta_s, "arrived",
                            st.session_state.guardian_tracking_locations,
                            st.session_state.guardian_start_time)
    with st.spinner("Sending arrival confirmation…"):
        results = send_to_all(a_lat, a_lon, all_contacts, guardian_triggered=True,
                              guardian_info={"action":"arrived","destination":dest,
                                             "eta_str":eta_s,"session_id":sid,"live_link":""})
    for r in results:
        st.success(f"✅ {r['name']} notified") if r["success"] else st.error(f"❌ {r['name']}: {r['error']}")

    st.session_state._guardian_send_arrival = False
    st.balloons()


# ===================================================================
# ---------- MOTION DETECTION --------------------------------------
# ===================================================================
st.divider()
st.subheader("📳 Motion Detection (Shake / Running)")
st.caption("Detects rapid shaking or running via accelerometer. Alerts sent every 30 seconds.")
motion_threshold    = st.slider("Shake sensitivity (lower = more sensitive)", 10, 50, 25, 5)
motion_confirm_count= st.slider("Confirm shakes needed", 2, 8, 3, 1)

mc1, mc2, mc3 = st.columns([3,1,1])
with mc1:
    if st.session_state.motion_tracking_active: st.error("📳 MOTION ALERT ACTIVE")
    elif st.session_state.motion_monitoring:    st.success("📳 Monitoring accelerometer…")
    else:                                        st.info("📴 Motion monitoring OFF")
with mc2:
    if not st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
        if st.button("📳 Start Motion", use_container_width=True, type="primary"):
            st.session_state.motion_monitoring = True
            st.session_state.motion_triggered  = False
            st.session_state.motion_listen_key += 1
            st.rerun()
    elif st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
        if st.button("📴 Stop", use_container_width=True):
            st.session_state.motion_monitoring = False
            streamlit_js_eval(js_expressions="window._motionListening=false;true", key="stop_motion")
            st.rerun()
with mc3:
    if st.session_state.motion_tracking_active:
        if st.button("🛑 STOP MOTION", use_container_width=True, type="primary"):
            total = st.session_state.motion_update_count
            st.session_state.motion_tracking_active   = False
            st.session_state.motion_monitoring        = False
            st.session_state.motion_triggered         = False
            st.session_state.motion_update_count      = 0
            st.session_state.motion_tracking_locations= []
            st.success(f"Stopped after {total} update(s)."); st.rerun()

if st.session_state.motion_monitoring and not st.session_state.motion_triggered and not st.session_state.motion_tracking_active:
    mr = streamlit_js_eval(js_expressions=f"""
        new Promise((resolve) => {{
            window._motionListening = true;
            if (!window.DeviceMotionEvent) {{ resolve({{error:'NOT_SUPPORTED'}}); return; }}
            const T={motion_threshold}, C={motion_confirm_count};
            let sc=0,la=null,res=false,lt=null;
            function om(e) {{
                if (!window._motionListening||res) return;
                const a=e.accelerationIncludingGravity; if(!a) return;
                if(la){{const d=Math.abs(a.x-la.x)+Math.abs(a.y-la.y)+Math.abs(a.z-la.z);
                    if(d>T){{sc++;if(sc>=C){{res=true;window._motionListening=false;
                        window.removeEventListener('devicemotion',om);clearTimeout(lt);
                        resolve({{detected:true,delta:d}});return;}}}}
                    else {{if(sc>0)sc=Math.max(0,sc-0.5);}}}}
                la={{x:a.x,y:a.y,z:a.z}};}}
            if(typeof DeviceMotionEvent.requestPermission==='function'){{
                DeviceMotionEvent.requestPermission().then(s=>{{
                    if(s==='granted') window.addEventListener('devicemotion',om);
                    else resolve({{error:'PERMISSION_DENIED'}});
                }}).catch(()=>resolve({{error:'PERMISSION_ERROR'}}));
            }} else window.addEventListener('devicemotion',om);
            lt=setTimeout(()=>{{if(!res){{res=true;window.removeEventListener('devicemotion',om);resolve({{timeout:true}});}}}},30000);
        }})""", key=f"motion_listen_{st.session_state.motion_listen_key}")
    if mr is not None and isinstance(mr, dict):
        if mr.get("detected"):
            st.session_state.motion_triggered        = True
            st.session_state.motion_tracking_active  = True
            st.session_state.motion_monitoring       = False
            st.session_state.motion_update_count     = 0
            st.session_state.motion_tracking_locations=[]
            st.session_state.motion_listen_key += 1; st.rerun()
        elif mr.get("error") == "NOT_SUPPORTED":
            st.error("❌ Motion not supported. Try Chrome on Android.")
            st.session_state.motion_monitoring = False
        elif mr.get("error") == "PERMISSION_DENIED":
            st.error("❌ Motion permission denied.")
            st.session_state.motion_monitoring = False
        elif mr.get("error"):
            st.session_state.motion_listen_key += 1; time.sleep(1); st.rerun()
        elif mr.get("timeout"):
            st.session_state.motion_listen_key += 1; st.rerun()

if st.session_state.motion_tracking_active:
    st.divider(); st.error("📳 MOTION DETECTED — LIVE TRACKING ACTIVE")
    mb, mr2, mt2 = st.empty(), st.empty(), st.empty()
    mloc = streamlit_js_eval(js_expressions="""new Promise(r=>{navigator.geolocation.getCurrentPosition(
        p=>r([p.coords.latitude,p.coords.longitude,p.coords.accuracy]),()=>r(null),
        {enableHighAccuracy:true,timeout:15000,maximumAge:0});})""",
        key=f"motion_xloc_{st.session_state.motion_update_count}")
    if mloc:
        ml,mlo,mac = mloc[0],mloc[1],(mloc[2] if len(mloc)>2 else None)
        mc = st.session_state.motion_update_count+1; mts = datetime.now().strftime("%H:%M:%S")
        mb.info(f"📳 #{mc} at {mts} | {ml:.6f},{mlo:.6f}" + (f" | ±{mac:.0f}m" if mac else ""))
        if mc==1:
            with st.spinner("Finding nearest police..."):
                p=find_police(ml,mlo) or find_police(ml,mlo,15000)
            if p: plat,plon,pn,pd=p; st.success(f"🚔 {pn} — {pd:.0f}m"); st.link_button("GO TO POLICE",f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")
        with mr2.container():
            with st.spinner(f"Sending #{mc}..."):
                res=send_to_all(ml,mlo,all_contacts,update_num=mc,accuracy=mac,motion_triggered=True)
            for r in res:
                st.success(f"✅ #{mc} → {r['name']}") if r["success"] else st.error(f"❌ {r['name']}: {r['error']}")
        st.session_state.motion_tracking_locations.append({"update":mc,"lat":ml,"lon":mlo,"time":mts})
        st.session_state.motion_update_count=mc
        cd=st.empty()
        for i in range(30,0,-1):
            if not st.session_state.motion_tracking_active: cd.empty(); st.stop()
            cd.info(f"📳 Next in {i}s…"); time.sleep(1)
        cd.empty(); st.rerun()
    else:
        st.error("GPS unavailable.")
        rb=st.empty()
        for i in range(10,0,-1):
            if not st.session_state.motion_tracking_active: rb.empty(); st.stop()
            rb.warning(f"Retrying in {i}s…"); time.sleep(1)
        rb.empty()
        if st.session_state.motion_tracking_active: st.rerun()


# ===================================================================
# ---------- VOICE RECOGNITION ------------------------------------
# ===================================================================
st.divider()
st.subheader("🎙️ Voice Distress Detection")
st.caption(f"Listening for: {', '.join(chr(34)+k+chr(34) for k in DISTRESS_KEYWORDS)}")

vc1,vc2,vc3 = st.columns([3,1,1])
with vc1:
    if st.session_state.voice_tracking_active: st.error(f'🎙️ VOICE ALERT — "{st.session_state.voice_trigger_word}"')
    elif st.session_state.voice_active:         st.success("🎙️ Listening for distress words…")
    else:                                        st.info("🔇 Voice monitoring OFF")
with vc2:
    if not st.session_state.voice_active and not st.session_state.voice_tracking_active:
        if st.button("🎙️ Start Listening", use_container_width=True, type="primary"):
            st.session_state.voice_active=True; st.session_state.voice_triggered=False
            st.session_state.voice_trigger_word=""; st.session_state.voice_trigger_key+=1; st.rerun()
    elif st.session_state.voice_active and not st.session_state.voice_tracking_active:
        if st.button("🔇 Stop", use_container_width=True):
            st.session_state.voice_active=False
            streamlit_js_eval(js_expressions="window._emergencyRecognition&&window._emergencyRecognition.stop();true",key="stop_voice")
            st.rerun()
with vc3:
    if st.session_state.voice_tracking_active:
        if st.button("🛑 STOP VOICE", use_container_width=True, type="primary"):
            total=st.session_state.voice_update_count
            st.session_state.voice_tracking_active=False; st.session_state.voice_active=False
            st.session_state.voice_triggered=False; st.session_state.voice_update_count=0
            st.session_state.voice_tracking_locations=[]
            st.success(f"Stopped after {total} update(s)."); st.rerun()

if st.session_state.voice_active and not st.session_state.voice_triggered and not st.session_state.voice_tracking_active:
    vr = streamlit_js_eval(js_expressions=f"""
        new Promise((resolve)=>{{
            if(window._emergencyRecognition){{window._emergencyRecognition.stop();window._emergencyRecognition=null;}}
            const kw={json.dumps(DISTRESS_KEYWORDS)};
            if(!('webkitSpeechRecognition'in window)&&!('SpeechRecognition'in window)){{resolve({{error:'NOT_SUPPORTED'}});return;}}
            const SR=window.SpeechRecognition||window.webkitSpeechRecognition,rec=new SR();
            window._emergencyRecognition=rec;
            rec.continuous=true;rec.interimResults=true;rec.lang='en-US';rec.maxAlternatives=3;
            let res=false;
            rec.onresult=e=>{{for(let i=e.resultIndex;i<e.results.length;i++)
                for(let a=0;a<e.results[i].length;a++){{
                    const t=e.results[i][a].transcript.toLowerCase().trim();
                    for(const k of kw)if(t.includes(k)){{if(!res){{res=true;rec.stop();resolve({{detected:true,word:k,transcript:t}});}}return;}}}}}};
            rec.onerror=e=>{{if(!res){{res=true;resolve({{error:e.error}})}}}};
            rec.onend=()=>{{if(!res){{res=true;resolve({{ended:true}})}}}};
            rec.start();}})""",
        key=f"voice_listen_{st.session_state.voice_trigger_key}")
    if vr is not None and isinstance(vr, dict):
        if vr.get("detected"):
            st.session_state.voice_triggered=True; st.session_state.voice_trigger_word=vr.get("word","unknown")
            st.session_state.voice_tracking_active=True; st.session_state.voice_active=False
            st.session_state.voice_update_count=0; st.session_state.voice_tracking_locations=[]
            st.session_state.voice_trigger_key+=1; st.rerun()
        elif vr.get("error")=="NOT_SUPPORTED":
            st.error("❌ Speech Recognition not supported. Use Chrome/Edge."); st.session_state.voice_active=False
        elif vr.get("error"):
            if vr.get("error") not in ("aborted","no-speech"): st.warning(f"Mic error: {vr.get('error')}. Retrying…")
            st.session_state.voice_trigger_key+=1; time.sleep(1); st.rerun()
        elif vr.get("ended"):
            st.session_state.voice_trigger_key+=1; time.sleep(0.5); st.rerun()

if st.session_state.voice_tracking_active:
    st.divider(); tw=st.session_state.voice_trigger_word
    st.error(f'🎙️ VOICE DISTRESS: "{tw.upper()}" — LIVE TRACKING ACTIVE')
    vb,vr2=st.empty(),st.empty()
    vloc=streamlit_js_eval(js_expressions="""new Promise(r=>{navigator.geolocation.getCurrentPosition(
        p=>r([p.coords.latitude,p.coords.longitude,p.coords.accuracy]),()=>r(null),
        {enableHighAccuracy:true,timeout:15000,maximumAge:0});})""",
        key=f"voice_xloc_{st.session_state.voice_update_count}")
    if vloc:
        vl,vlo,vac=vloc[0],vloc[1],(vloc[2] if len(vloc)>2 else None)
        vc=st.session_state.voice_update_count+1; vts=datetime.now().strftime("%H:%M:%S")
        vb.info(f"🎙️ #{vc} at {vts} | {vl:.6f},{vlo:.6f}")
        if vc==1:
            with st.spinner("Finding nearest police..."):
                p=find_police(vl,vlo) or find_police(vl,vlo,15000)
            if p: plat,plon,pn,pd=p; st.success(f"🚔 {pn} — {pd:.0f}m"); st.link_button("GO TO POLICE",f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")
        with vr2.container():
            with st.spinner(f"Sending #{vc}..."):
                res=send_to_all(vl,vlo,all_contacts,update_num=vc,accuracy=vac,voice_triggered=True,trigger_word=tw)
            for r in res:
                st.success(f"✅ #{vc} → {r['name']}") if r["success"] else st.error(f"❌ {r['name']}: {r['error']}")
        st.session_state.voice_tracking_locations.append({"update":vc,"lat":vl,"lon":vlo,"time":vts})
        st.session_state.voice_update_count=vc
        cd=st.empty()
        for i in range(30,0,-1):
            if not st.session_state.voice_tracking_active: cd.empty(); st.stop()
            cd.info(f"🎙️ Next in {i}s…"); time.sleep(1)
        cd.empty(); st.rerun()
    else:
        st.error("GPS unavailable.")
        rb=st.empty()
        for i in range(10,0,-1):
            if not st.session_state.voice_tracking_active: rb.empty(); st.stop()
            rb.warning(f"Retrying in {i}s…"); time.sleep(1)
        rb.empty()
        if st.session_state.voice_tracking_active: st.rerun()


# ===================================================================
# ---------- PANIC BUTTONS ----------------------------------------
# ===================================================================
st.divider()
st.caption(f"Alert will be sent to {len(all_contacts)} contact(s).")
p1,p2=st.columns(2)

with p1:
    if st.button("🚨 PANIC", use_container_width=True, type="primary", disabled=st.session_state.extreme_active):
        st.session_state.panic_requested=True; st.session_state.panic_key+=1
    if st.session_state.panic_requested:
        st.info("Locating…")
        loc=streamlit_js_eval(js_expressions="""new Promise(r=>{navigator.geolocation.getCurrentPosition(
            p=>r([p.coords.latitude,p.coords.longitude]),()=>r("ERROR"));})""",
            key=f"panic_location_{st.session_state.panic_key}")
        if loc=="ERROR":
            st.error("Location unavailable."); st.session_state.panic_requested=False
        elif loc is not None:
            lat,lon=loc; st.success(f"Location: {lat:.5f}, {lon:.5f}")
            res=send_to_all(lat,lon,all_contacts)
            for r in res:
                st.success(f"Sent to {r['name']}") if r["success"] else st.error(f"Failed - {r['name']}: {r['error']}")
            with st.spinner("Finding nearest police..."):
                p=find_police(lat,lon) or find_police(lat,lon,15000)
            if p: plat,plon,n,d=p; st.success(f"{n} - {d:.0f}m"); st.link_button("GO TO POLICE NOW",f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")
            else: st.error("No police found nearby.")
            st.session_state.panic_requested=False

with p2:
    if not st.session_state.extreme_active:
        if st.button("⚡ EXTREME PANIC - Live Tracking", use_container_width=True):
            st.session_state.extreme_active=True; st.session_state.update_count=0
            st.session_state.tracking_locations=[]; st.rerun()
    else:
        if st.button("🛑 STOP TRACKING", use_container_width=True, type="primary"):
            st.session_state.extreme_active=False
            st.success(f"Stopped after {st.session_state.update_count} update(s)."); st.rerun()

if st.session_state.extreme_active:
    st.divider(); st.error("⚡ EXTREME PANIC — LIVE TRACKING ON")
    lb,rb2,tb=st.empty(),st.empty(),st.empty()
    fl=streamlit_js_eval(js_expressions="""new Promise(r=>{navigator.geolocation.getCurrentPosition(
        p=>r([p.coords.latitude,p.coords.longitude,p.coords.accuracy]),()=>r(null),
        {enableHighAccuracy:true,timeout:15000,maximumAge:0});})""",
        key=f"xloc_{st.session_state.update_count}")
    if fl:
        lat,lon,acc=fl[0],fl[1],(fl[2] if len(fl)>2 else None)
        acc_s=f"±{acc:.0f}m" if acc else "unknown"
        cnt=st.session_state.update_count+1; ts=datetime.now().strftime("%H:%M:%S")
        lb.info(f"#{cnt} at {ts} | {lat:.6f},{lon:.6f} | {acc_s}")
        with rb2.container():
            with st.spinner(f"Sending #{cnt}..."):
                res=send_to_all(lat,lon,all_contacts,update_num=cnt,accuracy=acc)
            for r in res:
                st.success(f"#{cnt} → {r['name']}") if r["success"] else st.error(f"❌ {r['name']}: {r['error']}")
        st.session_state.tracking_locations.append({"update":cnt,"lat":lat,"lon":lon,"accuracy":acc_s,"time":ts})
        st.session_state.update_count=cnt
        with tb.expander(f"Trail ({cnt})",expanded=False):
            for e in reversed(st.session_state.tracking_locations):
                st.markdown(f"**#{e['update']}** {e['time']} `{e['lat']:.5f},{e['lon']:.5f}` [Maps](https://maps.google.com/?q={e['lat']},{e['lon']})")
        cd=st.empty()
        for i in range(30,0,-1):
            if not st.session_state.extreme_active: cd.empty(); st.stop()
            cd.info(f"Next in {i}s…"); time.sleep(1)
        cd.empty(); st.rerun()
    else:
        st.error("GPS unavailable.")
        rb3=st.empty()
        for i in range(10,0,-1):
            if not st.session_state.extreme_active: rb3.empty(); st.stop()
            rb3.warning(f"Retrying in {i}s…"); time.sleep(1)
        rb3.empty()
        if st.session_state.extreme_active: st.rerun()
