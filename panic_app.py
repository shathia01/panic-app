import json
import time
import uuid
from datetime import datetime

import streamlit as st
from streamlit_js_eval import streamlit_js_eval
from supabase import create_client

from emailer import send_to_all
from livekit_support import (
    create_livekit_token,
    end_incident,
    new_incident,
    render_broadcaster,
    render_viewer,
    validate_signed_live_link,
)
from utils import find_police


st.set_page_config(page_title="Shathia Emergency", page_icon="🚨", layout="centered")

# ===================================================================
# CONFIG
# ===================================================================
REQUIRED_SECRETS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SENDER_EMAIL",
    "SENDER_APP_PASSWORD",
    "APP_URL",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVE_VIEW_SECRET",
]
missing = [k for k in REQUIRED_SECRETS if not st.secrets.get(k)]
if missing:
    st.error("Missing Streamlit secrets: " + ", ".join(missing))
    st.info("Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and fill in the values.")
    st.stop()

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
SENDER_EMAIL = st.secrets["SENDER_EMAIL"]
SENDER_APP_PASSWORD = st.secrets["SENDER_APP_PASSWORD"]
SENDER_NAME = st.secrets.get("SENDER_NAME", "Shathia Emergency Alert")
APP_URL = st.secrets["APP_URL"].rstrip("/") + "/"
LIVEKIT_URL = st.secrets["LIVEKIT_URL"]
LIVEKIT_API_KEY = st.secrets["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = st.secrets["LIVEKIT_API_SECRET"]
LIVE_VIEW_SECRET = st.secrets["LIVE_VIEW_SECRET"]
DEFAULT_ADMIN_NAME = st.secrets.get("DEFAULT_ADMIN_NAME", "Admin")
DEFAULT_ADMIN_EMAIL = st.secrets.get("DEFAULT_ADMIN_EMAIL", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

DISTRESS_KEYWORDS = [
    "help", "please", "leave me", "stop", "let me go", "get away",
    "don't touch me", "call police", "save me", "emergency", "danger", "scared",
]

# ===================================================================
# QUERY ROUTES — SECURE LIVE VIEWER / GUARDIAN LOCATION VIEWER
# ===================================================================
live_id = st.query_params.get("live_id")
live_exp = st.query_params.get("expires")
live_sig = st.query_params.get("sig")
track_id = st.query_params.get("track_id")

if live_id:
    st.title("🚨 Shathia Live Emergency")
    if not validate_signed_live_link(LIVE_VIEW_SECRET, live_id, live_exp, live_sig):
        st.error("This emergency viewing link is invalid or has expired.")
        st.stop()

    try:
        result = supabase.table("emergency_incidents").select("*").eq("incident_id", live_id).execute()
        if not result.data:
            st.error("Emergency incident not found.")
            st.stop()

        incident = result.data[0]
        viewer_token = create_livekit_token(
            LIVEKIT_API_KEY,
            LIVEKIT_API_SECRET,
            incident["room_name"],
            f"g_{uuid.uuid4().hex}",
            publisher=False,
            can_publish_data=True,   # guardian may send camera-control data only
            can_subscribe=True,
        )
        trigger_type = incident.get("trigger_type") or "emergency"
        trigger_word = incident.get("trigger_word") or ""
        label = f"{trigger_type.upper()} DETECTED"
        if trigger_word:
            label += f' — "{trigger_word}"'

        if incident.get("status") != "active":
            st.warning("This emergency session has been marked as ended. Last known information is shown below.")

        render_viewer(
            LIVEKIT_URL,
            viewer_token,
            label,
            initial_lat=incident.get("lat"),
            initial_lon=incident.get("lon"),
            status_value=incident.get("status", "active"),
            height=730,
        )
        st.caption("For immediate danger in Malaysia, contact emergency services at 999.")
    except Exception as e:
        st.error(f"Could not open live emergency: {e}")
    st.stop()

if track_id:
    st.title("🛡️ Guardian Live Monitoring")
    st.caption(f"Tracking ID: `{track_id}`")
    status_box, map_box, details_box = st.empty(), st.empty(), st.empty()
    try:
        response = supabase.table("live_tracking").select("*").eq("track_id", track_id).execute()
        if not response.data:
            status_box.warning("Waiting for location data. The journey may not have started or may already be finished.")
        else:
            row = response.data[0]
            lat, lon = row["lat"], row["lon"]
            timestamp = row.get("timestamp", "Unknown")
            status = row.get("status", "active")
            if status == "safe":
                status_box.success("✅ Journey completed — person marked safe.")
            else:
                status_box.error("🔴 LIVE — Location updates every 5 seconds")
            map_box.map([{"lat": lat, "lon": lon}])
            details_box.info(
                f"📍 **Location**\n\nLatitude: `{lat:.6f}`\n\nLongitude: `{lon:.6f}`\n\n"
                f"Last updated: `{timestamp}`\n\n[Open in Google Maps](https://maps.google.com/?q={lat},{lon})"
            )
            if status != "safe":
                time.sleep(5)
                st.rerun()
    except Exception as e:
        st.error(f"Error fetching guardian location: {e}")
    st.stop()

# ===================================================================
# SESSION STATE
# ===================================================================
def init(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

for key, value in [
    ("motion_monitoring", False),
    ("motion_tracking_active", False),
    ("motion_trigger_word", ""),
    ("motion_listen_key", 0),
    ("voice_active", False),
    ("voice_tracking_active", False),
    ("voice_trigger_word", ""),
    ("voice_trigger_key", 0),
    ("manual_live_active", False),
    ("live_incident", None),
    ("live_initial_location", None),
    ("live_alert_sent", False),
    ("live_mode", None),
    ("guardian_active", False),
    ("guardian_id", None),
    ("guardian_update_count", 0),
    ("guardian_tracking_locations", []),
    ("panic_requested", False),
    ("panic_key", 0),
    ("extreme_active", False),
    ("update_count", 0),
    ("tracking_locations", []),
]:
    init(key, value)


def clear_live_session(mark_ended=True):
    incident = st.session_state.get("live_incident")
    if mark_ended and incident:
        try:
            end_incident(supabase, incident.get("incident_id"))
        except Exception:
            pass
    st.session_state.live_incident = None
    st.session_state.live_initial_location = None
    st.session_state.live_alert_sent = False
    st.session_state.live_mode = None


def stop_all_live_modes():
    st.session_state.motion_tracking_active = False
    st.session_state.motion_monitoring = False
    st.session_state.voice_tracking_active = False
    st.session_state.voice_active = False
    st.session_state.manual_live_active = False
    clear_live_session(mark_ended=True)


# ===================================================================
# CONTACTS
# ===================================================================
raw = streamlit_js_eval(
    js_expressions="localStorage.getItem('emergency_my_contacts')",
    key="read_my_contacts",
)
my_contacts = []
if raw and raw != "null":
    try:
        parsed = json.loads(raw)
        my_contacts = [parsed] if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
    except Exception:
        my_contacts = []

all_contacts = []
if DEFAULT_ADMIN_EMAIL:
    all_contacts.append({"name": DEFAULT_ADMIN_NAME, "email": DEFAULT_ADMIN_EMAIL})
for c in my_contacts:
    if c.get("email") and not any(x["email"].lower() == c["email"].lower() for x in all_contacts):
        all_contacts.append(c)


def email_all(lat, lon, **kwargs):
    return send_to_all(
        SENDER_EMAIL,
        SENDER_APP_PASSWORD,
        SENDER_NAME,
        all_contacts,
        lat,
        lon,
        **kwargs,
    )


# ===================================================================
# LIVE EMERGENCY ENGINE
# ===================================================================
def live_emergency_screen(mode, trigger_word=""):
    st.divider()
    label = f"{mode.upper()} EMERGENCY"
    if trigger_word:
        label += f' — "{trigger_word}"'
    st.error(f"🔴 {label} — LIVE CAMERA / AUDIO / GPS ACTIVE")
    st.warning("Keep this page open. The back camera starts first. Camera switching is controlled remotely by the guardian from the secure live link.")

    if not all_contacts:
        st.warning("No emergency email contacts are configured. Live streaming can still start, but no alert email can be sent.")

    if st.session_state.live_incident is None:
        loc = streamlit_js_eval(
            js_expressions="""
            new Promise(resolve => {
              if (!navigator.geolocation) { resolve({error:'NOT_SUPPORTED'}); return; }
              navigator.geolocation.getCurrentPosition(
                p => resolve({lat:p.coords.latitude, lon:p.coords.longitude, accuracy:p.coords.accuracy}),
                e => resolve({error:e.message || 'LOCATION_DENIED'}),
                {enableHighAccuracy:true, timeout:15000, maximumAge:0}
              );
            })
            """,
            key=f"live_initial_{mode}_{st.session_state.get('voice_trigger_key',0)}_{st.session_state.get('motion_listen_key',0)}",
        )
        if loc is None:
            st.info("Requesting your location before starting the secure emergency room…")
            st.stop()
        if not isinstance(loc, dict) or loc.get("error"):
            st.error(f"Location is required for the emergency alert. Error: {(loc or {}).get('error', 'unknown') if isinstance(loc, dict) else 'unknown'}")
            st.stop()

        try:
            incident = new_incident(
                supabase,
                APP_URL,
                LIVE_VIEW_SECRET,
                LIVEKIT_URL,
                LIVEKIT_API_KEY,
                LIVEKIT_API_SECRET,
                trigger_type=mode,
                trigger_word=trigger_word,
                lat=loc["lat"],
                lon=loc["lon"],
                accuracy=loc.get("accuracy"),
            )
            st.session_state.live_incident = incident
            st.session_state.live_initial_location = loc
            st.session_state.live_mode = mode
        except Exception as e:
            st.error(f"Could not create emergency live room. Run database/setup.sql first and check LiveKit/Supabase secrets. Details: {e}")
            st.stop()

    incident = st.session_state.live_incident
    loc = st.session_state.live_initial_location

    if not st.session_state.live_alert_sent:
        if all_contacts:
            with st.spinner("Sending secure live emergency link to saved contacts…"):
                results = email_all(
                    loc["lat"],
                    loc["lon"],
                    accuracy=loc.get("accuracy"),
                    voice_triggered=(mode == "voice"),
                    trigger_word=trigger_word,
                    motion_triggered=(mode == "motion"),
                    emergency_live_link=incident["live_link"],
                )
            for r in results:
                if r["success"]:
                    st.success(f"✅ Live emergency link sent to {r['name']}")
                else:
                    st.error(f"❌ Email failed for {r['name']}: {r['error']}")
        st.session_state.live_alert_sent = True

        with st.spinner("Finding nearest police station…"):
            police = find_police(loc["lat"], loc["lon"]) or find_police(loc["lat"], loc["lon"], 15000)
        if police:
            plat, plon, pname, pdist = police
            st.success(f"🚔 {pname} — approximately {pdist:.0f}m away")
            st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")

    st.caption(f"Initial location: {loc['lat']:.6f}, {loc['lon']:.6f} | Live link expires automatically.")
    render_broadcaster(
        LIVEKIT_URL,
        incident["publisher_token"],
        label,
        initial_lat=loc["lat"],
        initial_lon=loc["lon"],
        height=640,
    )
    st.info("The live media connection stays mounted without 30-second Streamlit reruns. GPS is sent through LiveKit continuously with movement updates plus a 5-second heartbeat, and the guardian can switch the user's front/back camera remotely.")
    st.stop()


# ===================================================================
# MAIN UI
# ===================================================================
st.title("🚨 Shathia Emergency Protection")
st.caption("Voice distress + motion detection + panic alerts + guardian journeys + secure live camera/audio/GPS.")

# Contacts
st.divider()
st.subheader("📋 My Emergency Contacts")
if my_contacts:
    for i, c in enumerate(my_contacts):
        c1, c2, c3 = st.columns([2, 3, 1])
        c1.write(f"**{c.get('name','Contact')}**")
        c2.write(c.get("email", ""))
        if c3.button("🗑️", key=f"delete_contact_{i}"):
            updated = [x for j, x in enumerate(my_contacts) if j != i]
            js_value = json.dumps(updated)
            streamlit_js_eval(
                js_expressions=f"localStorage.setItem('emergency_my_contacts', {json.dumps(js_value)}); true",
                key=f"delete_contact_js_{i}",
            )
            st.rerun()
else:
    st.info("No personal emergency contacts saved on this device.")

with st.form("add_contact", clear_on_submit=True):
    n1, n2 = st.columns(2)
    name = n1.text_input("Name", placeholder="e.g. Sarah")
    email = n2.text_input("Email", placeholder="e.g. sarah@gmail.com")
    if st.form_submit_button("➕ Save Contact"):
        if name.strip() and email.strip() and "@" in email:
            updated = my_contacts + [{"name": name.strip(), "email": email.strip()}]
            js_value = json.dumps(updated)
            streamlit_js_eval(
                js_expressions=f"localStorage.setItem('emergency_my_contacts', {json.dumps(js_value)}); true",
                key=f"save_contact_{uuid.uuid4().hex[:8]}",
            )
            st.success("Contact saved. Refresh once if it does not appear immediately.")
        else:
            st.warning("Enter a valid name and email address.")

st.caption(f"Alerts currently go to {len(all_contacts)} contact(s), including any configured default admin contact.")

# Guardian mode
st.divider()
st.subheader("🛡️ Guardian Live Monitoring")
st.caption("Share a live location journey with saved contacts. This mode is location-only and separate from emergency camera streaming.")
g1, g2 = st.columns([3, 1])
if st.session_state.guardian_active:
    g1.error(f"Guardian mode active — `{st.session_state.guardian_id}`")
    tracking_link = f"{APP_URL}?track_id={st.session_state.guardian_id}"
    g1.markdown(f"[Open guardian link]({tracking_link})")
    if g2.button("✅ I Reached Safe", use_container_width=True, type="primary"):
        try:
            supabase.table("live_tracking").update({"status": "safe"}).eq("track_id", st.session_state.guardian_id).execute()
            if st.session_state.guardian_tracking_locations and all_contacts:
                last = st.session_state.guardian_tracking_locations[-1]
                email_all(last["lat"], last["lon"], safe_arrival=True)
        except Exception as e:
            st.warning(f"Could not finalize guardian journey: {e}")
        st.session_state.guardian_active = False
        st.session_state.guardian_id = None
        st.session_state.guardian_update_count = 0
        st.session_state.guardian_tracking_locations = []
        st.rerun()
else:
    g1.info("Guardian mode is off")
    if g2.button("🛡️ Start Journey", use_container_width=True, type="primary"):
        st.session_state.guardian_id = uuid.uuid4().hex[:10]
        st.session_state.guardian_active = True
        st.session_state.guardian_update_count = 0
        st.session_state.guardian_tracking_locations = []
        st.rerun()

if st.session_state.guardian_active:
    gloc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => navigator.geolocation.getCurrentPosition(
          p => resolve([p.coords.latitude,p.coords.longitude,p.coords.accuracy]),
          () => resolve(null),
          {enableHighAccuracy:true,timeout:10000,maximumAge:0}
        ))
        """,
        key=f"guardian_loc_{st.session_state.guardian_update_count}",
    )
    if gloc:
        lat, lon = gloc[0], gloc[1]
        accuracy = gloc[2] if len(gloc) > 2 else None
        count = st.session_state.guardian_update_count + 1
        tracking_link = f"{APP_URL}?track_id={st.session_state.guardian_id}"
        supabase.table("live_tracking").upsert({
            "track_id": st.session_state.guardian_id,
            "lat": lat,
            "lon": lon,
            "timestamp": datetime.now().isoformat(),
            "status": "active",
        }).execute()
        if count == 1 and all_contacts:
            email_all(lat, lon, guardian_link=tracking_link, accuracy=accuracy)
        st.info(f"Guardian update #{count}: {lat:.6f}, {lon:.6f}")
        st.session_state.guardian_tracking_locations.append({"lat": lat, "lon": lon})
        st.session_state.guardian_update_count = count
        time.sleep(5)
        st.rerun()
    else:
        st.warning("Waiting for location permission…")
        st.stop()

# Developer test
st.divider()
with st.expander("🧪 Test Live Emergency (recommended before real use)"):
    st.write("Starts the same secure live camera + microphone + GPS workflow without waiting for voice or motion detection.")
    if not st.session_state.manual_live_active:
        if st.button("🔴 START TEST LIVE EMERGENCY", type="primary"):
            stop_all_live_modes()
            st.session_state.manual_live_active = True
            st.rerun()
    else:
        if st.button("🛑 STOP TEST"):
            stop_all_live_modes()
            st.rerun()
if st.session_state.manual_live_active:
    live_emergency_screen("test", "manual test")

# Motion
st.divider()
st.subheader("📳 Motion Detection")
st.caption("Detects repeated rapid motion. When triggered, it starts secure live camera + microphone + GPS and emails the viewing link.")
motion_threshold = st.slider("Shake sensitivity (lower = more sensitive)", 10, 50, 25, 5)
motion_confirm_count = st.slider("Confirm shakes needed", 2, 8, 3, 1)
mc1, mc2 = st.columns([3, 1])
if st.session_state.motion_tracking_active:
    mc1.error("🔴 Motion emergency live session active")
    if mc2.button("🛑 STOP MOTION", type="primary", use_container_width=True):
        stop_all_live_modes()
        st.rerun()
elif st.session_state.motion_monitoring:
    mc1.success("Motion monitoring active")
    if mc2.button("Stop Motion", use_container_width=True):
        st.session_state.motion_monitoring = False
        st.rerun()
else:
    mc1.info("Motion monitoring off")
    if mc2.button("📳 Start Motion", type="primary", use_container_width=True):
        stop_all_live_modes()
        st.session_state.motion_monitoring = True
        st.session_state.motion_listen_key += 1
        st.rerun()

if st.session_state.motion_monitoring and not st.session_state.motion_tracking_active:
    motion_result = streamlit_js_eval(
        js_expressions=f"""
        new Promise((resolve) => {{
          if (!window.DeviceMotionEvent) {{ resolve({{error:'NOT_SUPPORTED'}}); return; }}
          const THRESHOLD={motion_threshold}; const CONFIRM={motion_confirm_count};
          let count=0, last=null, done=false;
          function finish(v) {{ if(done) return; done=true; window.removeEventListener('devicemotion', onMotion); resolve(v); }}
          function onMotion(e) {{
            const a=e.accelerationIncludingGravity; if(!a) return;
            if(last) {{
              const delta=Math.abs(a.x-last.x)+Math.abs(a.y-last.y)+Math.abs(a.z-last.z);
              if(delta>THRESHOLD) count++; else count=Math.max(0,count-0.5);
              if(count>=CONFIRM) finish({{detected:true,delta:delta}});
            }}
            last={{x:a.x,y:a.y,z:a.z}};
          }}
          function listen() {{ window.addEventListener('devicemotion',onMotion); setTimeout(()=>finish({{timeout:true}}),30000); }}
          if(typeof DeviceMotionEvent.requestPermission==='function') {{
            DeviceMotionEvent.requestPermission().then(s=>s==='granted'?listen():finish({{error:'PERMISSION_DENIED'}})).catch(()=>finish({{error:'PERMISSION_ERROR'}}));
          }} else listen();
        }})
        """,
        key=f"motion_detect_{st.session_state.motion_listen_key}",
    )
    if isinstance(motion_result, dict):
        if motion_result.get("detected"):
            st.session_state.motion_monitoring = False
            st.session_state.motion_tracking_active = True
            clear_live_session(mark_ended=False)
            st.rerun()
        elif motion_result.get("error"):
            st.error(f"Motion sensor error: {motion_result['error']}")
            st.session_state.motion_monitoring = False
        elif motion_result.get("timeout"):
            st.session_state.motion_listen_key += 1
            st.rerun()

if st.session_state.motion_tracking_active:
    live_emergency_screen("motion")

# Voice
st.divider()
st.subheader("🎙️ Voice Distress Detection")
st.caption("Listening for: " + ", ".join(f'“{x}”' for x in DISTRESS_KEYWORDS))
vc1, vc2 = st.columns([3, 1])
if st.session_state.voice_tracking_active:
    vc1.error(f'🔴 Voice emergency active — "{st.session_state.voice_trigger_word}"')
    if vc2.button("🛑 STOP VOICE", type="primary", use_container_width=True):
        stop_all_live_modes()
        st.rerun()
elif st.session_state.voice_active:
    vc1.success("Voice monitoring active")
    if vc2.button("Stop Listening", use_container_width=True):
        st.session_state.voice_active = False
        st.rerun()
else:
    vc1.info("Voice monitoring off")
    if vc2.button("🎙️ Start Listening", type="primary", use_container_width=True):
        stop_all_live_modes()
        st.session_state.voice_active = True
        st.session_state.voice_trigger_key += 1
        st.rerun()

if st.session_state.voice_active and not st.session_state.voice_tracking_active:
    keywords_js = json.dumps(DISTRESS_KEYWORDS)
    voice_result = streamlit_js_eval(
        js_expressions=f"""
        new Promise((resolve) => {{
          const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
          if(!SR) {{ resolve({{error:'NOT_SUPPORTED'}}); return; }}
          const r=new SR(); r.continuous=true; r.interimResults=true; r.lang='en-US'; r.maxAlternatives=3;
          let done=false; const keywords={keywords_js};
          function finish(v) {{ if(done)return; done=true; try{{r.stop();}}catch(e){{}} resolve(v); }}
          r.onresult=(event)=>{{
            for(let i=event.resultIndex;i<event.results.length;i++) {{
              for(let a=0;a<event.results[i].length;a++) {{
                const text=event.results[i][a].transcript.toLowerCase().trim();
                for(const kw of keywords) if(text.includes(kw.toLowerCase())) {{ finish({{detected:true,word:kw,transcript:text}}); return; }}
              }}
            }}
          }};
          r.onerror=(e)=>finish({{error:e.error}}); r.onend=()=>finish({{ended:true}}); r.start();
        }})
        """,
        key=f"voice_detect_{st.session_state.voice_trigger_key}",
    )
    if isinstance(voice_result, dict):
        if voice_result.get("detected"):
            st.session_state.voice_trigger_word = voice_result.get("word", "unknown")
            st.session_state.voice_active = False
            st.session_state.voice_tracking_active = True
            clear_live_session(mark_ended=False)
            st.rerun()
        elif voice_result.get("error") == "NOT_SUPPORTED":
            st.error("Speech Recognition is not supported in this browser. Try current Chrome or Edge.")
            st.session_state.voice_active = False
        elif voice_result.get("error"):
            if voice_result.get("error") not in ("no-speech", "aborted"):
                st.warning(f"Voice recognition error: {voice_result.get('error')}")
            st.session_state.voice_trigger_key += 1
            st.rerun()
        elif voice_result.get("ended"):
            st.session_state.voice_trigger_key += 1
            st.rerun()

if st.session_state.voice_tracking_active:
    live_emergency_screen("voice", st.session_state.voice_trigger_word)

# Panic buttons
st.divider()
st.subheader("🚨 Manual Panic")
p1, p2 = st.columns(2)
if p1.button("PANIC", type="primary", use_container_width=True):
    st.session_state.panic_requested = True
    st.session_state.panic_key += 1

if st.session_state.panic_requested:
    loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => navigator.geolocation.getCurrentPosition(
          p=>resolve([p.coords.latitude,p.coords.longitude,p.coords.accuracy]),
          ()=>resolve('ERROR'), {enableHighAccuracy:true,timeout:15000,maximumAge:0}
        ))
        """,
        key=f"panic_{st.session_state.panic_key}",
    )
    if loc == "ERROR":
        st.error("Location unavailable. Allow location access and try again.")
        st.session_state.panic_requested = False
    elif loc:
        lat, lon = loc[0], loc[1]
        accuracy = loc[2] if len(loc) > 2 else None
        if all_contacts:
            for r in email_all(lat, lon, accuracy=accuracy):
                st.success(f"Sent to {r['name']}") if r["success"] else st.error(f"Failed for {r['name']}: {r['error']}")
        police = find_police(lat, lon) or find_police(lat, lon, 15000)
        if police:
            plat, plon, pname, pdist = police
            st.success(f"🚔 {pname} — {pdist:.0f}m away")
            st.link_button("GO TO POLICE NOW", f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}")
        st.session_state.panic_requested = False

if not st.session_state.extreme_active:
    if p2.button("EXTREME PANIC — Live Location", use_container_width=True):
        st.session_state.extreme_active = True
        st.session_state.update_count = 0
        st.session_state.tracking_locations = []
        st.rerun()
else:
    if p2.button("STOP EXTREME TRACKING", type="primary", use_container_width=True):
        st.session_state.extreme_active = False
        st.rerun()

if st.session_state.extreme_active:
    st.error("EXTREME PANIC LIVE LOCATION ACTIVE")
    loc = streamlit_js_eval(
        js_expressions="""
        new Promise(resolve => navigator.geolocation.getCurrentPosition(
          p=>resolve([p.coords.latitude,p.coords.longitude,p.coords.accuracy]),
          ()=>resolve(null), {enableHighAccuracy:true,timeout:15000,maximumAge:0}
        ))
        """,
        key=f"extreme_{st.session_state.update_count}",
    )
    if loc:
        lat, lon = loc[0], loc[1]
        accuracy = loc[2] if len(loc) > 2 else None
        count = st.session_state.update_count + 1
        if all_contacts:
            email_all(lat, lon, update_num=count, accuracy=accuracy)
        st.info(f"Update #{count}: {lat:.6f}, {lon:.6f}")
        st.session_state.update_count = count
        st.session_state.tracking_locations.append({"lat": lat, "lon": lon, "time": datetime.now().strftime("%H:%M:%S")})
        time.sleep(30)
        st.rerun()
    else:
        st.warning("Waiting for GPS…")
        st.stop()

st.divider()
st.caption("Important: web browsers cannot guarantee camera/microphone streaming after the browser is closed or the phone is locked. For production-level background emergency monitoring, use a native mobile app.")
