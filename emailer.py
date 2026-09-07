import base64
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid


def send_email(sender_email, sender_password, sender_name, recipient_name, recipient_email,
               lat, lon, update_num=None, accuracy=None, voice_triggered=False,
               trigger_word="", motion_triggered=False, guardian_link=None,
               safe_arrival=False, emergency_live_link=None,
               audio_b64=None, audio_mime="audio/webm"):
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_update = update_num is not None

    if safe_arrival:
        subject = "✅ Journey Completed Safely — Guardian Alert"
    elif emergency_live_link and motion_triggered:
        subject = "🔴 LIVE MOTION EMERGENCY — Camera, Audio & Location Available"
    elif emergency_live_link and voice_triggered:
        subject = f'🔴 LIVE VOICE EMERGENCY — "{trigger_word}" Detected'
    elif guardian_link:
        subject = "🛡️ Guardian Live Monitoring Started — Live Tracking Link"
    elif motion_triggered:
        subject = "📳 MOTION ALERT — Emergency"
    elif voice_triggered:
        subject = "🎙️ VOICE ALERT — Emergency"
    elif is_update:
        subject = f"LIVE UPDATE #{update_num} — Emergency Alert"
    else:
        subject = "Emergency Alert — Urgent Assistance Required"

    acc_text = f"±{accuracy:.0f}m" if accuracy else "N/A"
    trigger_desc = ""
    if voice_triggered:
        trigger_desc = f'Voice distress word detected: "{trigger_word}".'
    elif motion_triggered:
        trigger_desc = "Rapid motion/shaking was detected."

    live_plain = ""
    if emergency_live_link:
        live_plain = (
            "\n🔴 LIVE EMERGENCY VIEW:\n"
            f"{emergency_live_link}\n"
            "Open this secure link to watch the live camera, hear live audio, and see live GPS.\n"
        )

    guardian_plain = f"\nGuardian tracking link:\n{guardian_link}\n" if guardian_link else ""
    safe_plain = "\nThe person marked the journey as safely completed.\n" if safe_arrival else ""

    plain = f"""Emergency notification

Dear {recipient_name},

{trigger_desc or ('Guardian journey started.' if guardian_link else ('The person marked safe.' if safe_arrival else 'Emergency alert activated.'))}
{live_plain}{guardian_plain}{safe_plain}
Location: {lat:.6f}, {lon:.6f}
Accuracy: {acc_text}
Google Maps: {maps_link}
Time: {timestamp}

If there is immediate danger, contact emergency services (999 in Malaysia).
"""

    color = "#b00020" if not safe_arrival else "#167c34"
    live_block = ""
    if emergency_live_link:
        live_block = f"""
        <div style="background:#fff0f2;border:2px solid #b00020;padding:16px;border-radius:10px;margin:18px 0;text-align:center;">
          <h2 style="color:#b00020;margin-top:0;">🔴 LIVE EMERGENCY</h2>
          <p>Watch the user's live camera, hear live audio and follow live location.</p>
          <a href="{emergency_live_link}" style="display:block;background:#b00020;color:#fff;padding:15px;border-radius:8px;text-decoration:none;font-size:18px;font-weight:bold;">WATCH LIVE NOW</a>
          <p style="font-size:12px;color:#666;">This secure link expires automatically.</p>
        </div>
        """

    guardian_block = ""
    if guardian_link:
        guardian_block = f"""
        <a href="{guardian_link}" style="display:block;text-align:center;background:#174a7e;color:#fff;padding:14px;border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0;">Open Guardian Live Map</a>
        """

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f3f4f6;padding:20px;">
      <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;border-top:6px solid {color};padding:28px;">
        <h1 style="color:{color};text-align:center;">{'✅ Safe Arrival' if safe_arrival else '🚨 Emergency Alert'}</h1>
        <p>Dear <b>{recipient_name}</b>,</p>
        <p>{trigger_desc or ('Guardian journey has started.' if guardian_link else ('The user marked the journey safe.' if safe_arrival else 'An emergency alert was activated.'))}</p>
        {live_block}
        {guardian_block}
        <div style="background:#eef6ff;padding:14px;border-radius:8px;">
          <b>Location</b><br>
          {lat:.6f}, {lon:.6f}<br>
          Accuracy: {acc_text}<br>
          Time: {timestamp}
        </div>
        <a href="{maps_link}" style="display:block;text-align:center;background:#0b6cff;color:white;padding:13px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:14px;">Open in Google Maps</a>
        {'<p style="margin-top:18px"><b>If there is immediate danger, contact emergency services (999 in Malaysia).</b></p>' if not safe_arrival else ''}
      </div>
    </body></html>
    """

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = recipient_email
        msg["Reply-To"] = sender_email
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(plain, "plain"))
        alt.attach(MIMEText(html, "html"))
        msg.attach(alt)

        if audio_b64:
            try:
                audio_bytes = base64.b64decode(audio_b64)
                ext = "ogg" if "ogg" in audio_mime else "webm"
                part = MIMEBase("audio", ext)
                part.set_payload(audio_bytes)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=f"evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}",
                )
                msg.attach(part)
            except Exception:
                pass

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_to_all(sender_email, sender_password, sender_name, contacts, lat, lon, **kwargs):
    results = []
    for c in contacts:
        success, error = send_email(
            sender_email, sender_password, sender_name,
            c["name"], c["email"], lat, lon, **kwargs
        )
        results.append({"name": c["name"], "email": c["email"], "success": success, "error": error})
    return results
