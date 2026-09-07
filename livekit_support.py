import hashlib
import hmac
import html
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import streamlit.components.v1 as components
from livekit import api


LIVEKIT_JS = "https://cdn.jsdelivr.net/npm/livekit-client@2.22.2/dist/livekit-client.umd.min.js"


def create_livekit_token(api_key, api_secret, room_name, identity, publisher=False, ttl_hours=2):
    grants = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=publisher,
        can_subscribe=not publisher,
        can_publish_data=publisher,
        can_publish_sources=["camera", "microphone"] if publisher else None,
    )
    return (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_ttl(timedelta(hours=ttl_hours))
        .with_grants(grants)
        .to_jwt()
    )


def create_signed_live_link(app_url, live_view_secret, incident_id, expires_seconds=7200):
    expires = int(time.time()) + expires_seconds
    payload = f"{incident_id}:{expires}"
    sig = hmac.new(
        live_view_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    query = urlencode({"live_id": incident_id, "expires": expires, "sig": sig})
    return f"{app_url.rstrip('/')}/?{query}"


def validate_signed_live_link(live_view_secret, incident_id, expires, sig):
    try:
        expires = int(expires)
    except (TypeError, ValueError):
        return False
    if expires < int(time.time()):
        return False
    payload = f"{incident_id}:{expires}"
    expected = hmac.new(
        live_view_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, str(sig or ""))


def new_incident(supabase, app_url, live_view_secret, livekit_url, api_key, api_secret,
                 trigger_type, trigger_word="", lat=None, lon=None, accuracy=None):
    incident_id = uuid.uuid4().hex
    room_name = f"emg_{uuid.uuid4().hex}"
    publisher_identity = f"u_{uuid.uuid4().hex}"
    publisher_token = create_livekit_token(
        api_key, api_secret, room_name, publisher_identity, publisher=True
    )
    live_link = create_signed_live_link(app_url, live_view_secret, incident_id)

    row = {
        "incident_id": incident_id,
        "room_name": room_name,
        "status": "active",
        "trigger_type": trigger_type,
        "trigger_word": trigger_word or None,
        "lat": lat,
        "lon": lon,
        "accuracy": accuracy,
    }
    supabase.table("emergency_incidents").insert(row).execute()

    return {
        "incident_id": incident_id,
        "room_name": room_name,
        "publisher_identity": publisher_identity,
        "publisher_token": publisher_token,
        "live_link": live_link,
        "livekit_url": livekit_url,
    }


def end_incident(supabase, incident_id):
    if not incident_id:
        return
    supabase.table("emergency_incidents").update({
        "status": "ended",
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }).eq("incident_id", incident_id).execute()


def _js(value):
    return json.dumps(value)


def broadcaster_html(livekit_url, token, trigger_label, initial_lat=None, initial_lon=None):
    initial = {
        "lat": initial_lat,
        "lon": initial_lon,
    }
    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="{LIVEKIT_JS}"></script>
<style>
body {{ margin:0; font-family:Arial,sans-serif; background:#101114; color:#fff; }}
.wrap {{ padding:14px; }}
.badge {{ display:inline-block; padding:6px 10px; border-radius:999px; background:#b00020; font-weight:700; }}
.video-wrap {{ margin-top:12px; background:#000; border-radius:14px; overflow:hidden; min-height:240px; }}
video {{ width:100%; min-height:240px; max-height:520px; object-fit:cover; background:#000; }}
.row {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
button {{ border:0; border-radius:10px; padding:11px 14px; font-weight:700; cursor:pointer; }}
.primary {{ background:#fff; color:#111; }}
.danger {{ background:#b00020; color:#fff; }}
.card {{ margin-top:10px; padding:10px; border-radius:10px; background:#1b1d22; }}
.small {{ color:#b8bdc7; font-size:13px; }}
.ok {{ color:#73e09a; }}
.warn {{ color:#ffd166; }}
</style>
</head>
<body>
<div class="wrap">
  <span class="badge">🔴 LIVE EMERGENCY</span>
  <div class="small" style="margin-top:6px">{html.escape(trigger_label)}</div>
  <div class="video-wrap"><video id="preview" autoplay muted playsinline></video></div>
  <div class="row">
    <button id="switch" class="primary">🔄 Switch Camera</button>
    <button id="mic" class="primary">🎙️ Mute Mic</button>
    <button id="cam" class="primary">📷 Hide Camera</button>
  </div>
  <div class="card">
    <div id="status">Connecting live camera and microphone…</div>
    <div id="gps" class="small" style="margin-top:6px">Waiting for GPS…</div>
  </div>
</div>
<script>
(async () => {{
  const LK = window.LivekitClient;
  const room = new LK.Room({{ adaptiveStream: true, dynacast: true }});
  const status = document.getElementById('status');
  const gpsEl = document.getElementById('gps');
  const preview = document.getElementById('preview');
  let facing = 'environment';
  let micOn = true;
  let camOn = true;
  const initial = {_js(initial)};

  function showStatus(text, cls='') {{
    status.className = cls;
    status.textContent = text;
  }}

  async function publishGps(pos) {{
    try {{
      const payload = {{
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        timestamp: Date.now()
      }};
      gpsEl.textContent = `GPS: ${{payload.lat.toFixed(6)}}, ${{payload.lon.toFixed(6)}} ±${{Math.round(payload.accuracy || 0)}}m`;
      const data = new TextEncoder().encode(JSON.stringify(payload));
      await room.localParticipant.publishData(data, {{ reliable: false, topic: 'gps' }});
    }} catch (e) {{
      console.error('GPS publish failed', e);
    }}
  }}

  try {{
    await room.connect({_js(livekit_url)}, {_js(token)});
    showStatus('Connected. Requesting camera + microphone permission…', 'warn');

    const camPub = await room.localParticipant.setCameraEnabled(true, {{ facingMode: 'environment' }});
    await room.localParticipant.setMicrophoneEnabled(true);
    if (camPub && camPub.track) camPub.track.attach(preview);

    showStatus('🟢 Camera, microphone and live connection active', 'ok');

    if (navigator.geolocation) {{
      navigator.geolocation.getCurrentPosition(publishGps, () => {{}}, {{ enableHighAccuracy:true, timeout:10000, maximumAge:0 }});
      navigator.geolocation.watchPosition(
        publishGps,
        err => {{ gpsEl.textContent = 'GPS error: ' + err.message; }},
        {{ enableHighAccuracy:true, timeout:15000, maximumAge:0 }}
      );
    }} else if (initial.lat != null && initial.lon != null) {{
      gpsEl.textContent = `GPS: ${{Number(initial.lat).toFixed(6)}}, ${{Number(initial.lon).toFixed(6)}}`;
    }}

    document.getElementById('switch').onclick = async () => {{
      const pub = room.localParticipant.getTrackPublication(LK.Track.Source.Camera);
      if (!pub || !pub.track) return;
      facing = facing === 'environment' ? 'user' : 'environment';
      try {{
        await pub.track.restartTrack({{ facingMode: facing }});
      }} catch (e) {{
        alert('Camera switch was not supported by this device/browser.');
      }}
    }};

    document.getElementById('mic').onclick = async (ev) => {{
      micOn = !micOn;
      await room.localParticipant.setMicrophoneEnabled(micOn);
      ev.target.textContent = micOn ? '🎙️ Mute Mic' : '🎙️ Unmute Mic';
    }};

    document.getElementById('cam').onclick = async (ev) => {{
      camOn = !camOn;
      await room.localParticipant.setCameraEnabled(camOn, {{ facingMode: facing }});
      ev.target.textContent = camOn ? '📷 Hide Camera' : '📷 Show Camera';
      if (camOn) {{
        const pub = room.localParticipant.getTrackPublication(LK.Track.Source.Camera);
        if (pub && pub.track) pub.track.attach(preview);
      }}
    }};

    window.addEventListener('beforeunload', () => {{ try {{ room.disconnect(); }} catch(e) {{}} }});
  }} catch (e) {{
    console.error(e);
    showStatus('❌ Live media failed: ' + (e.message || e), 'warn');
  }}
}})();
</script>
</body>
</html>
"""


def viewer_html(livekit_url, token, trigger_label, initial_lat=None, initial_lon=None, status_value="active"):
    initial = {"lat": initial_lat, "lon": initial_lon}
    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="{LIVEKIT_JS}"></script>
<style>
body {{ margin:0; font-family:Arial,sans-serif; background:#0d0f12; color:#fff; }}
.wrap {{ padding:14px; }}
.header {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
.badge {{ padding:6px 10px; background:#b00020; border-radius:999px; font-weight:800; }}
.card {{ background:#181b20; border-radius:14px; padding:12px; margin-top:12px; }}
#media {{ background:#000; border-radius:14px; overflow:hidden; min-height:260px; display:flex; align-items:center; justify-content:center; }}
#media video {{ width:100%; min-height:260px; max-height:520px; object-fit:cover; }}
#media audio {{ display:none; }}
button, a.btn {{ border:0; border-radius:10px; padding:12px 14px; font-weight:800; cursor:pointer; text-decoration:none; display:inline-block; }}
button {{ background:#fff; color:#111; }}
a.btn {{ background:#0b6cff; color:#fff; }}
.small {{ color:#b8bdc7; font-size:13px; }}
.ok {{ color:#73e09a; }}
.warn {{ color:#ffd166; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div>
      <div class="badge">🔴 LIVE EMERGENCY</div>
      <div class="small" style="margin-top:6px">{html.escape(trigger_label)}</div>
    </div>
    <button id="sound">🔊 Enable Sound</button>
  </div>

  <div id="media" class="card"><div id="waiting">Waiting for user's live camera…</div></div>

  <div class="card">
    <div id="status">Connecting securely…</div>
    <div id="gps" style="margin-top:8px">Location waiting…</div>
    <div class="small" id="accuracy" style="margin-top:4px"></div>
    <div style="margin-top:10px"><a id="maps" class="btn" target="_blank">📍 Open Google Maps</a></div>
  </div>
</div>
<script>
(async () => {{
  const LK = window.LivekitClient;
  const room = new LK.Room({{ adaptiveStream: true }});
  const media = document.getElementById('media');
  const waiting = document.getElementById('waiting');
  const status = document.getElementById('status');
  const gps = document.getElementById('gps');
  const accuracy = document.getElementById('accuracy');
  const maps = document.getElementById('maps');
  const initial = {_js(initial)};

  function setGps(p) {{
    if (p.lat == null || p.lon == null) return;
    gps.textContent = `📍 ${{Number(p.lat).toFixed(6)}}, ${{Number(p.lon).toFixed(6)}}`;
    accuracy.textContent = p.accuracy ? `Accuracy: ±${{Math.round(p.accuracy)}}m` : '';
    maps.href = `https://maps.google.com/?q=${{p.lat}},${{p.lon}}`;
  }}
  setGps(initial);

  room.on(LK.RoomEvent.TrackSubscribed, (track) => {{
    if (waiting) waiting.style.display = 'none';
    const el = track.attach();
    if (track.kind === LK.Track.Kind.Video) {{
      el.autoplay = true; el.playsInline = true;
    }}
    if (track.kind === LK.Track.Kind.Audio) el.autoplay = true;
    media.appendChild(el);
  }});

  room.on(LK.RoomEvent.TrackUnsubscribed, (track) => track.detach());
  room.on(LK.RoomEvent.DataReceived, (payload, participant, kind, topic) => {{
    try {{
      if (topic && topic !== 'gps') return;
      const p = JSON.parse(new TextDecoder().decode(payload));
      if (typeof p.lat === 'number' && typeof p.lon === 'number') setGps(p);
    }} catch (e) {{}}
  }});
  room.on(LK.RoomEvent.ParticipantConnected, () => {{ status.textContent = '🟢 User connected'; status.className='ok'; }});
  room.on(LK.RoomEvent.ParticipantDisconnected, () => {{ status.textContent = '⚠️ User connection ended or temporarily lost'; status.className='warn'; }});

  document.getElementById('sound').onclick = async (ev) => {{
    try {{
      await room.startAudio();
      document.querySelectorAll('audio').forEach(a => a.play().catch(() => {{}}));
      ev.target.textContent = '🔊 Sound Enabled';
    }} catch (e) {{
      ev.target.textContent = 'Tap again for sound';
    }}
  }};

  try {{
    if ({_js(status_value)} !== 'active') {{
      status.textContent = 'Emergency session has ended.';
      status.className='warn';
    }}
    await room.connect({_js(livekit_url)}, {_js(token)});
    status.textContent = '🟢 Connected to secure live room';
    status.className='ok';
  }} catch (e) {{
    status.textContent = '❌ Could not connect: ' + (e.message || e);
    status.className='warn';
  }}
}})();
</script>
</body>
</html>
"""


def render_broadcaster(*args, height=640, **kwargs):
    components.html(broadcaster_html(*args, **kwargs), height=height, scrolling=True)


def render_viewer(*args, height=720, **kwargs):
    components.html(viewer_html(*args, **kwargs), height=height, scrolling=True)
