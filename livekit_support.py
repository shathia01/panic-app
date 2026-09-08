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


# Keep the browser SDK pinned so behaviour is repeatable in Streamlit Cloud.
LIVEKIT_JS = "https://cdn.jsdelivr.net/npm/livekit-client@2.22.3/dist/livekit-client.umd.min.js"


def create_livekit_token(
    api_key,
    api_secret,
    room_name,
    identity,
    publisher=False,
    ttl_hours=2,
    can_publish_data=None,
    can_subscribe=None,
):
    """
    Create a LiveKit room token.

    Broadcaster:
      - camera/microphone publishing allowed
      - realtime GPS/data publishing allowed
      - data reception allowed so guardian can send camera-control commands

    Guardian:
      - camera/microphone publishing NOT allowed
      - media subscription allowed
      - data publishing can be enabled for remote camera-control commands
    """
    if can_publish_data is None:
        can_publish_data = publisher
    if can_subscribe is None:
        can_subscribe = True

    grants = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=publisher,
        can_subscribe=can_subscribe,
        can_publish_data=can_publish_data,
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


def new_incident(
    supabase,
    app_url,
    live_view_secret,
    livekit_url,
    api_key,
    api_secret,
    trigger_type,
    trigger_word="",
    lat=None,
    lon=None,
    accuracy=None,
):
    incident_id = uuid.uuid4().hex
    room_name = f"emg_{uuid.uuid4().hex}"
    publisher_identity = f"u_{uuid.uuid4().hex}"

    # The user's phone publishes media + GPS, and can receive guardian data commands.
    publisher_token = create_livekit_token(
        api_key,
        api_secret,
        room_name,
        publisher_identity,
        publisher=True,
        can_publish_data=True,
        can_subscribe=True,
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
    initial = {"lat": initial_lat, "lon": initial_lon}

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
.card {{ margin-top:10px; padding:12px; border-radius:10px; background:#1b1d22; }}
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
  <div class="card">
    <div id="status">Connecting live camera and microphone…</div>
    <div id="camera" class="small" style="margin-top:6px">Camera: back</div>
    <div id="control" class="small" style="margin-top:4px">Camera switching is controlled by the guardian.</div>
    <div id="gps" class="small" style="margin-top:6px">Waiting for GPS…</div>
  </div>
</div>
<script>
(async () => {{
  const LK = window.LivekitClient;
  const room = new LK.Room({{ adaptiveStream: true, dynacast: true }});
  const status = document.getElementById('status');
  const cameraEl = document.getElementById('camera');
  const controlEl = document.getElementById('control');
  const gpsEl = document.getElementById('gps');
  const preview = document.getElementById('preview');
  const initial = {_js(initial)};

  let facing = 'environment';
  let latestGps = null;
  let gpsWatchId = null;
  let gpsHeartbeatId = null;
  let gpsSequence = 0;

  function showStatus(text, cls='') {{
    status.className = cls;
    status.textContent = text;
  }}

  function cameraName() {{
    return facing === 'user' ? 'front' : 'back';
  }}

  async function sendCameraStatus(success=true, message='') {{
    try {{
      const payload = {{
        type: 'camera_status',
        facing: facing,
        camera: cameraName(),
        success: success,
        message: message,
        timestamp: Date.now()
      }};
      const data = new TextEncoder().encode(JSON.stringify(payload));
      await room.localParticipant.publishData(data, {{ reliable: true, topic: 'camera-status' }});
    }} catch (e) {{
      console.error('Could not publish camera status', e);
    }}
  }}

  async function changeCamera(action) {{
    const pub = room.localParticipant.getTrackPublication(LK.Track.Source.Camera);
    if (!pub || !pub.track) {{
      await sendCameraStatus(false, 'Camera track is not available.');
      return;
    }}

    let target = facing;
    if (action === 'front') target = 'user';
    else if (action === 'back') target = 'environment';
    else if (action === 'switch') target = facing === 'environment' ? 'user' : 'environment';
    else return;

    controlEl.textContent = 'Guardian requested ' + (target === 'user' ? 'front' : 'back') + ' camera…';

    try {{
      await pub.track.restartTrack({{ facingMode: target }});
      facing = target;
      cameraEl.textContent = 'Camera: ' + cameraName();
      controlEl.textContent = 'Camera changed remotely by guardian.';
      await sendCameraStatus(true, 'Camera changed successfully.');
    }} catch (e) {{
      console.error('Camera switch failed', e);
      controlEl.textContent = 'Camera switch failed on this device/browser.';
      await sendCameraStatus(false, e.message || 'Camera switch failed.');
    }}
  }}

  async function publishGpsPayload(payload) {{
    if (!payload || typeof payload.lat !== 'number' || typeof payload.lon !== 'number') return;
    try {{
      gpsSequence += 1;
      const outgoing = {{
        ...payload,
        timestamp: Date.now(),
        sequence: gpsSequence,
      }};
      gpsEl.textContent = `GPS #${{gpsSequence}}: ${{outgoing.lat.toFixed(6)}}, ${{outgoing.lon.toFixed(6)}} ±${{Math.round(outgoing.accuracy || 0)}}m`;
      const data = new TextEncoder().encode(JSON.stringify(outgoing));
      // GPS is intentionally lossy/low-latency. A 5-second heartbeat sends the latest value again.
      await room.localParticipant.publishData(data, {{ reliable: false, topic: 'gps' }});
    }} catch (e) {{
      console.error('GPS publish failed', e);
    }}
  }}

  async function onGpsPosition(pos) {{
    latestGps = {{
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy: pos.coords.accuracy,
    }};
    await publishGpsPayload(latestGps);
  }}

  function gpsError(err) {{
    console.warn('GPS error', err);
    if (latestGps) {{
      gpsEl.textContent = `GPS temporarily unavailable — keeping last location ${{latestGps.lat.toFixed(6)}}, ${{latestGps.lon.toFixed(6)}}`;
    }} else {{
      gpsEl.textContent = 'GPS error: ' + (err && err.message ? err.message : 'unknown');
    }}
  }}

  function startContinuousGps() {{
    if (!navigator.geolocation) {{
      if (initial.lat != null && initial.lon != null) {{
        latestGps = {{ lat:Number(initial.lat), lon:Number(initial.lon), accuracy:null }};
        publishGpsPayload(latestGps);
      }} else {{
        gpsEl.textContent = 'Geolocation is not supported by this browser.';
      }}
      return;
    }}

    if (initial.lat != null && initial.lon != null) {{
      latestGps = {{ lat:Number(initial.lat), lon:Number(initial.lon), accuracy:null }};
    }}

    // Immediate fresh sample.
    navigator.geolocation.getCurrentPosition(
      onGpsPosition,
      gpsError,
      {{ enableHighAccuracy:true, timeout:12000, maximumAge:0 }}
    );

    // Movement-driven updates.
    gpsWatchId = navigator.geolocation.watchPosition(
      onGpsPosition,
      gpsError,
      {{ enableHighAccuracy:true, timeout:15000, maximumAge:0 }}
    );

    // Heartbeat: guarantees the guardian receives a GPS packet at least every ~5 seconds,
    // even when the phone is stationary and watchPosition does not emit a new callback.
    gpsHeartbeatId = setInterval(() => {{
      if (latestGps) publishGpsPayload(latestGps);

      // Also ask for a fresh high-accuracy sample. If a browser chooses not to produce one,
      // the heartbeat above still keeps the guardian updated with the last known position.
      navigator.geolocation.getCurrentPosition(
        onGpsPosition,
        () => {{}},
        {{ enableHighAccuracy:true, timeout:4500, maximumAge:0 }}
      );
    }}, 5000);
  }}

  try {{
    await room.connect({_js(livekit_url)}, {_js(token)});
    showStatus('Connected. Requesting camera + microphone permission…', 'warn');

    const camPub = await room.localParticipant.setCameraEnabled(true, {{ facingMode: 'environment' }});
    await room.localParticipant.setMicrophoneEnabled(true);
    if (camPub && camPub.track) camPub.track.attach(preview);

    facing = 'environment';
    cameraEl.textContent = 'Camera: back';
    showStatus('🟢 Camera, microphone and live connection active', 'ok');

    startContinuousGps();

    // Receive guardian-only data commands. Guardian identities are generated with g_ prefix.
    room.on(LK.RoomEvent.DataReceived, async (payload, participant, kind, topic) => {{
      if (topic !== 'camera-control') return;
      if (!participant || !participant.identity || !participant.identity.startsWith('g_')) return;

      try {{
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg && msg.type === 'camera_control') {{
          await changeCamera(msg.action);
        }}
      }} catch (e) {{
        console.error('Invalid camera control message', e);
      }}
    }});

    room.on(LK.RoomEvent.ParticipantConnected, async (participant) => {{
      if (participant && participant.identity && participant.identity.startsWith('g_')) {{
        await sendCameraStatus(true, 'Guardian connected.');
        if (latestGps) await publishGpsPayload(latestGps);
      }}
    }});

    window.addEventListener('beforeunload', () => {{
      try {{ if (gpsWatchId !== null) navigator.geolocation.clearWatch(gpsWatchId); }} catch(e) {{}}
      try {{ if (gpsHeartbeatId !== null) clearInterval(gpsHeartbeatId); }} catch(e) {{}}
      try {{ room.disconnect(); }} catch(e) {{}}
    }});
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
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
button, a.btn {{ border:0; border-radius:10px; padding:12px 14px; font-weight:800; cursor:pointer; text-decoration:none; display:inline-block; }}
button {{ background:#fff; color:#111; }}
button:disabled {{ opacity:.45; cursor:not-allowed; }}
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
    <b>📷 Guardian Camera Control</b>
    <div class="controls">
      <button id="backCam">⬅️ Back Camera</button>
      <button id="frontCam">🤳 Front Camera</button>
      <button id="switchCam">🔄 Switch Camera</button>
    </div>
    <div id="cameraStatus" class="small" style="margin-top:8px">Waiting for user's phone…</div>
  </div>

  <div class="card">
    <div id="status">Connecting securely…</div>
    <div id="gps" style="margin-top:8px">Location waiting…</div>
    <div class="small" id="accuracy" style="margin-top:4px"></div>
    <div class="small" id="gpsMeta" style="margin-top:4px"></div>
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
  const gpsMeta = document.getElementById('gpsMeta');
  const maps = document.getElementById('maps');
  const cameraStatus = document.getElementById('cameraStatus');
  const backCam = document.getElementById('backCam');
  const frontCam = document.getElementById('frontCam');
  const switchCam = document.getElementById('switchCam');
  const initial = {_js(initial)};

  let gpsCount = 0;
  let userConnected = false;

  function setControlEnabled(enabled) {{
    backCam.disabled = !enabled;
    frontCam.disabled = !enabled;
    switchCam.disabled = !enabled;
  }}
  setControlEnabled(false);

  function hasUserParticipant() {{
    for (const p of room.remoteParticipants.values()) {{
      if (p.identity && p.identity.startsWith('u_')) return true;
    }}
    return false;
  }}

  function setGps(p) {{
    if (p.lat == null || p.lon == null) return;
    gpsCount += 1;
    gps.textContent = `📍 ${{Number(p.lat).toFixed(6)}}, ${{Number(p.lon).toFixed(6)}}`;
    accuracy.textContent = p.accuracy ? `Accuracy: ±${{Math.round(p.accuracy)}}m` : 'Accuracy: unavailable';
    maps.href = `https://maps.google.com/?q=${{p.lat}},${{p.lon}}`;

    const ts = p.timestamp ? new Date(Number(p.timestamp)) : new Date();
    gpsMeta.textContent = `Live update #${{gpsCount}} • ${{ts.toLocaleTimeString()}}`;
  }}
  setGps(initial);

  async function sendCameraCommand(action) {{
    if (!userConnected && !hasUserParticipant()) {{
      cameraStatus.textContent = 'User phone is not connected yet.';
      cameraStatus.className = 'small warn';
      return;
    }}

    try {{
      cameraStatus.textContent = 'Sending camera command…';
      cameraStatus.className = 'small warn';
      const payload = {{
        type: 'camera_control',
        action: action,
        timestamp: Date.now(),
      }};
      const data = new TextEncoder().encode(JSON.stringify(payload));
      await room.localParticipant.publishData(data, {{ reliable: true, topic: 'camera-control' }});
    }} catch (e) {{
      cameraStatus.textContent = 'Camera command failed: ' + (e.message || e);
      cameraStatus.className = 'small warn';
    }}
  }}

  backCam.onclick = () => sendCameraCommand('back');
  frontCam.onclick = () => sendCameraCommand('front');
  switchCam.onclick = () => sendCameraCommand('switch');

  room.on(LK.RoomEvent.TrackSubscribed, (track) => {{
    if (waiting) waiting.style.display = 'none';
    const el = track.attach();
    if (track.kind === LK.Track.Kind.Video) {{
      el.autoplay = true;
      el.playsInline = true;
    }}
    if (track.kind === LK.Track.Kind.Audio) el.autoplay = true;
    media.appendChild(el);
  }});

  room.on(LK.RoomEvent.TrackUnsubscribed, (track) => track.detach());

  room.on(LK.RoomEvent.DataReceived, (payload, participant, kind, topic) => {{
    try {{
      const p = JSON.parse(new TextDecoder().decode(payload));

      if (topic === 'gps') {{
        if (typeof p.lat === 'number' && typeof p.lon === 'number') setGps(p);
        return;
      }}

      if (topic === 'camera-status' && p && p.type === 'camera_status') {{
        if (p.success) {{
          cameraStatus.textContent = `✅ User camera is now ${{p.camera || (p.facing === 'user' ? 'front' : 'back')}}.`;
          cameraStatus.className = 'small ok';
        }} else {{
          cameraStatus.textContent = '⚠️ Camera change failed: ' + (p.message || 'unsupported by device/browser');
          cameraStatus.className = 'small warn';
        }}
      }}
    }} catch (e) {{}}
  }});

  room.on(LK.RoomEvent.ParticipantConnected, (participant) => {{
    if (participant && participant.identity && participant.identity.startsWith('u_')) {{
      userConnected = true;
      status.textContent = '🟢 User connected';
      status.className = 'ok';
      cameraStatus.textContent = 'Guardian camera controls ready.';
      cameraStatus.className = 'small ok';
      setControlEnabled(true);
    }}
  }});

  room.on(LK.RoomEvent.ParticipantDisconnected, (participant) => {{
    if (participant && participant.identity && participant.identity.startsWith('u_')) {{
      userConnected = false;
      status.textContent = '⚠️ User connection ended or temporarily lost';
      status.className = 'warn';
      cameraStatus.textContent = 'Waiting for user phone to reconnect…';
      cameraStatus.className = 'small warn';
      setControlEnabled(false);
    }}
  }});

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
      status.className = 'warn';
    }}

    await room.connect({_js(livekit_url)}, {_js(token)});
    status.textContent = '🟢 Connected to secure live room';
    status.className = 'ok';

    userConnected = hasUserParticipant();
    if (userConnected) {{
      setControlEnabled(true);
      cameraStatus.textContent = 'Guardian camera controls ready.';
      cameraStatus.className = 'small ok';
    }}
  }} catch (e) {{
    status.textContent = '❌ Could not connect: ' + (e.message || e);
    status.className = 'warn';
    setControlEnabled(false);
  }}
}})();
</script>
</body>
</html>
"""


def render_broadcaster(*args, height=640, **kwargs):
    components.html(broadcaster_html(*args, **kwargs), height=height, scrolling=True)


def render_viewer(*args, height=760, **kwargs):
    components.html(viewer_html(*args, **kwargs), height=height, scrolling=True)
