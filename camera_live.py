from __future__ import annotations

import uuid
import streamlit as st
import streamlit.components.v1 as components


def create_camera_session(supabase):
    token = str(uuid.uuid4())
    result = supabase.rpc("create_camera_session", {"p_token": token}).execute()
    return token


def stop_camera_session(supabase, token):
    if not token:
        return
    try:
        supabase.rpc("stop_camera_session", {"p_token": token}).execute()
    except Exception:
        pass


def camera_sender(token: str, supabase_url: str, supabase_key: str, facing_mode: str = "environment"):
    """User side: captures BOTH camera and microphone and publishes them through WebRTC."""
    html = f"""
<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://unpkg.com/@supabase/supabase-js@2"></script>
<script src="https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js"></script>
<style>
body{{margin:0;background:#090909;color:white;font-family:Arial,sans-serif}}
.wrap{{padding:10px;text-align:center}} video{{width:100%;max-height:360px;background:#000;border-radius:12px;object-fit:cover}}
.badge{{display:inline-block;margin-top:8px;padding:7px 12px;border-radius:20px;background:#222;font-size:13px}}
.live{{background:#8b0000}} .small{{font-size:11px;color:#aaa;margin-top:5px}}
</style></head><body><div class="wrap">
<video id="preview" autoplay playsinline muted></video>
<div id="status" class="badge">Starting emergency camera + microphone…</div>
<div class="small">Camera and microphone are streamed live to the emergency contact.</div>
</div><script>
const TOKEN={token!r}, SUPABASE_URL={supabase_url!r}, SUPABASE_KEY={supabase_key!r}, FACING={facing_mode!r};
const sb=supabase.createClient(SUPABASE_URL,SUPABASE_KEY); let peer=null,stream=null;
function status(t,live=false){{const e=document.getElementById('status');e.textContent=t;e.className='badge'+(live?' live':'');}}
async function registerPeer(id){{const {{error}}=await sb.rpc('register_camera_peer',{{p_token:TOKEN,p_peer_id:id}});if(error)throw error;}}
async function start(){{
 try{{
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){{status('Camera/microphone not supported');return;}}
  stream=await navigator.mediaDevices.getUserMedia({{video:{{facingMode:FACING,width:{{ideal:1280}},height:{{ideal:720}}}},audio:{{echoCancellation:true,noiseSuppression:true,autoGainControl:true}}}});
  document.getElementById('preview').srcObject=stream;
  status('Camera + microphone ready — waiting for guardian',true);
  peer=new Peer(undefined,{{secure:true,debug:1}});
  peer.on('open',async id=>{{try{{await registerPeer(id);status('🔴 LIVE CAMERA + AUDIO — guardian can watch/listen now',true);}}catch(e){{status('Database registration failed');console.error(e);}}}});
  peer.on('call',call=>{{call.answer(stream);status('🔴 LIVE — guardian connected (video + audio)',true);}});
  peer.on('error',e=>{{status('Connection error: '+e.type);console.error(e);}});
 }}catch(e){{status('Permission/error: '+e.name);console.error(e);}}
}}
window.addEventListener('beforeunload',()=>{{try{{if(stream)stream.getTracks().forEach(t=>t.stop());if(peer)peer.destroy();}}catch(e){{}}}}); start();
</script></body></html>"""
    components.html(html, height=430, scrolling=False)


def camera_viewer(token: str, supabase_url: str, supabase_key: str):
    """Guardian side: receives the user's live camera AND microphone."""
    html = f"""
<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://unpkg.com/@supabase/supabase-js@2"></script>
<script src="https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js"></script>
<style>
body{{margin:0;background:#080808;color:white;font-family:Arial,sans-serif}}
.wrap{{padding:12px}} video{{width:100%;min-height:260px;max-height:70vh;background:#000;border-radius:12px;object-fit:contain}}
.status{{margin:10px 0;padding:10px;border-radius:9px;background:#222;text-align:center}} .live{{background:#650000}}
button{{width:100%;padding:13px;border:0;border-radius:9px;background:#b00020;color:white;font-weight:bold;font-size:15px;margin-top:10px}}
.note{{font-size:12px;color:#aaa;text-align:center;margin-top:8px}}
</style></head><body><div class="wrap">
<div id="status" class="status">Connecting to emergency camera…</div>
<video id="remote" autoplay playsinline></video>
<button id="sound" onclick="enableSound()">🔊 TAP TO ENABLE LIVE SOUND</button>
<div class="note">Live video and microphone audio are peer-to-peer. The stream is not recorded by this page.</div>
</div><script>
const TOKEN={token!r},SUPABASE_URL={supabase_url!r},SUPABASE_KEY={supabase_key!r};
const sb=supabase.createClient(SUPABASE_URL,SUPABASE_KEY);let peer=null,call=null,timer=null;
const remote=document.getElementById('remote');
function status(t,live=false){{const e=document.getElementById('status');e.textContent=t;e.className='status'+(live?' live':'');}}
function enableSound(){{remote.muted=false;remote.volume=1;remote.play().catch(()=>{{}});document.getElementById('sound').textContent='🔊 LIVE SOUND ENABLED';}}
async function getSession(){{const {{data,error}}=await sb.rpc('get_camera_session',{{p_token:TOKEN}});if(error)throw error;return data&&data.length?data[0]:null;}}
function dummy(){{const c=document.createElement('canvas');c.width=2;c.height=2;return c.captureStream(1);}}
async function connect(id){{if(!id)return;if(call)try{{call.close();}}catch(e){{}};call=peer.call(id,dummy());if(!call){{status('Could not create camera call');return;}}call.on('stream',s=>{{remote.srcObject=s;remote.muted=false;status('🔴 LIVE — video + audio connected',true);remote.play().catch(()=>{{status('🔴 LIVE — tap the sound button',true);}});}});call.on('close',()=>status('Camera connection ended'));call.on('error',e=>{{status('Camera connection error');console.error(e);}});}}
async function start(){{try{{peer=new Peer(undefined,{{secure:true,debug:1}});peer.on('open',async()=>{{status('Looking for the user camera…');const poll=async()=>{{try{{const s=await getSession();if(!s){{status('Camera session not found or expired');return;}}if(s.status!=='active'){{status('Emergency camera has ended');if(timer)clearInterval(timer);return;}}if(s.peer_id&&(!call||call.peer!==s.peer_id))await connect(s.peer_id);}}catch(e){{console.error(e);}}}};await poll();timer=setInterval(poll,2000);}});peer.on('error',e=>{{status('Viewer connection error: '+e.type);console.error(e);}});}}catch(e){{status('Unable to start viewer');console.error(e);}}}}
start();
</script></body></html>"""
    components.html(html, height=620, scrolling=False)
