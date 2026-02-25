import streamlit as st
import requests
import math
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from streamlit_js_eval import streamlit_js_eval

st.title("🚨 One-Click Emergency Panic Button")

# ---------- GMAIL CONFIG ----------
SENDER_EMAIL = "SENDER_EMAIL"       # your Gmail address
SENDER_APP_PASSWORD = "SENDER_APP_PASSWORD"   # 16-char app password (no spaces)

# ---------- DEFAULT HARDCODED CONTACTS ----------
DEFAULT_CONTACTS = [
    {"name": "Mum", "email": "mum@example.com"},
    {"name": "Dad", "email": "dad@example.com"},
]

# ---------- GET LOCATION ----------
location = streamlit_js_eval(
    js_expressions="""
    new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(
            pos => resolve([pos.coords.latitude, pos.coords.longitude]),
            err => resolve(null)
        );
    })
    """,
    key="get_location"
)

# ---------- HAVERSINE ----------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
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
            data={"data": query},
            timeout=25
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
    except Exception as e:
        st.error(f"Overpass error: {e}")
        return None

# ---------- SEND EMAIL ----------
def send_email(recipient_name, recipient_email, lat, lon):
    maps_link = f"https://maps.google.com/?q={lat},{lon}"

    # --- HTML email body ---
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f8f8f8; padding: 20px;">
        <div style="max-width: 500px; margin: auto; background: white; border-radius: 10px;
                    border-top: 6px solid red; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">

            <h1 style="color: red; text-align: center;">🚨 EMERGENCY ALERT</h1>

            <p style="font-size: 16px;">Dear <b>{recipient_name}</b>,</p>

            <p style="font-size: 16px;">
                This is an automated emergency alert.<br><br>
                <b>I need help immediately!</b><br>
                Please contact me or call <b>999</b> right away.
            </p>

            <div style="background-color: #fff3f3; border-left: 4px solid red;
                        padding: 15px; border-radius: 5px; margin: 20px 0;">
                <p style="margin: 0; font-size: 15px;">
                    📍 <b>My Live Location:</b><br>
                    Latitude: <code>{lat:.6f}</code><br>
                    Longitude: <code>{lon:.6f}</code>
                </p>
            </div>

            <a href="{maps_link}" style="display: block; text-align: center;
               background-color: red; color: white; padding: 14px 20px;
               border-radius: 8px; text-decoration: none; font-size: 16px;
               font-weight: bold; margin-top: 10px;">
               📍 OPEN MY LOCATION IN GOOGLE MAPS
            </a>

            <p style="font-size: 12px; color: #999; text-align: center; margin-top: 20px;">
                This alert was sent automatically via Emergency Panic Button App.
            </p>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🚨 EMERGENCY ALERT — I Need Help Now!"
        msg["From"] = SENDER_EMAIL
        msg["To"] = recipient_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())

        return True, ""
    except Exception as e:
        return False, str(e)

def send_email_to_all(lat, lon, contacts):
    results = []
    for contact in contacts:
        success, error = send_email(contact["name"], contact["email"], lat, lon)
        results.append({
            "name": contact["name"],
            "email": contact["email"],
            "success": success,
            "error": error
        })
    return results

# ---------- SIDEBAR: MANAGE CONTACTS ----------
st.sidebar.header("📋 Emergency Contacts")
st.sidebar.caption("Default contacts:")
for c in DEFAULT_CONTACTS:
    st.sidebar.write(f"✅ {c['name']} — {c['email']}")

st.sidebar.divider()
st.sidebar.caption("Add extra contacts for this session:")

if "extra_contacts" not in st.session_state:
    st.session_state.extra_contacts = []

with st.sidebar.form("add_contact_form", clear_on_submit=True):
    new_name = st.text_input("Name", placeholder="e.g. Sister")
    new_email = st.text_input("Email", placeholder="e.g. sister@gmail.com")
    add_btn = st.form_submit_button("➕ Add Contact")
    if add_btn:
        if new_name and new_email:
            st.session_state.extra_contacts.append({
                "name": new_name,
                "email": new_email
            })
            st.success(f"{new_name} added!")
        else:
            st.warning("Please fill in both fields.")

if st.session_state.extra_contacts:
    st.sidebar.caption("Added this session:")
    for i, c in enumerate(st.session_state.extra_contacts):
        col1, col2 = st.sidebar.columns([3, 1])
        col1.write(f"➕ {c['name']} — {c['email']}")
        if col2.button("🗑️", key=f"del_{i}"):
            st.session_state.extra_contacts.pop(i)
            st.rerun()

# ---------- PANIC BUTTON ----------
st.divider()
all_contacts = DEFAULT_CONTACTS + st.session_state.extra_contacts
st.caption(f"📧 Alert email will be sent to {len(all_contacts)} contact(s) when PANIC is pressed.")

if st.button("🚨 PANIC", use_container_width=True, type="primary"):
    if location:
        lat, lon = location
        st.success(f"📍 Location detected: {lat:.5f}, {lon:.5f}")

        # --- Send Emails ---
        st.info("📤 Sending emergency emails...")
        results = send_email_to_all(lat, lon, all_contacts)

        for r in results:
            if r["success"]:
                st.success(f"✅ Email sent to {r['name']} ({r['email']})")
            else:
                st.error(f"❌ Failed to send to {r['name']} — {r['error']}")

        # --- Find Police ---
        with st.spinner("🔍 Locating nearest police station..."):
            police = find_police(lat, lon, radius=5000)

        if not police:
            st.warning("Widening search to 15km...")
            police = find_police(lat, lon, radius=15000)

        if police:
            plat, plon, name, dist = police
            st.success(f"🚔 Nearest Police Station: **{name}** ({dist:.0f}m away)")
            nav = f"https://www.google.com/maps/dir/?api=1&destination={plat},{plon}"
            st.link_button("🚓 GO TO POLICE NOW", nav)
        else:
            st.error("No police station found in the area.")

    else:
        st.error("⚠️ Location not available — refresh the page and allow location permission.")

