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
    html = f"""
<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://unpkg.com/@supabase/supabase-js@2"></script>
<script src="https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js"></script>
<style>
body{{margin:0;background:#090909;color:white;font-family:Arial,sans-serif}}
.wrap{{padding:10px;text-align:center}}
video{{width:100%;max-height:360px;background:#000;border-radius:12px;object-fit:cover}}
.badge{{display:inline-block;margin-top:8px;padding:7px 12px;border-radius:20px;background:#222;font-size:13px}}
.live{{background:#8b0000}}
.small{{font-size:11px;color:#aaa;margin-top:5px;word-break:break-all}}
</style></head>
<body>
<div class="wrap">
  <video id="preview" autoplay playsinline muted></video>
  <div id="status" class="badge">Starting emergency camera…</div>
  <div id="peer" class="small"></div>
</div>
<script>
const TOKEN = {token!r};
const SUPABASE_URL = {supabase_url!r};
const SUPABASE_KEY = {supabase_key!r};
const FACING = {facing_mode!r};
const sb = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
let peer = null;
let stream = null;

function status(text, live=false) {{
  const el=document.getElementById('status');
  el.textContent=text;
  el.className='badge'+(live?' live':'');
}}

async function registerPeer(id) {{
  const {{error}} = await sb.rpc('register_camera_peer', {{p_token:TOKEN,p_peer_id:id}});
  if(error) throw error;
}}

async function start() {{
  try {{
    stream = await navigator.mediaDevices.getUserMedia({{
      video: {{ facingMode: FACING, width: {{ideal:1280}}, height: {{ideal:720}} }},
      audio: false
    }});
    document.getElementById('preview').srcObject=stream;
    status('Camera ready — waiting for guardian', true);

    peer = new Peer(undefined, {{secure:true, debug:1}});
    peer.on('open', async id => {{
      document.getElementById('peer').textContent='Camera connection ready';
      try {{
        await registerPeer(id);
        status('🔴 LIVE CAMERA — guardian can watch now', true);
      }} catch(e) {{
        status('Database registration failed');
        console.error(e);
      }}
    }});

    peer.on('call', call => {{
      call.answer(stream);
      status('🔴 LIVE CAMERA — guardian connected', true);
    }});
    peer.on('error', e => {{ status('Camera connection error: '+e.type); console.error(e); }});
  }} catch(e) {{
    status('Camera permission/error: '+e.name);
    console.error(e);
  }}
}}

window.addEventListener('beforeunload', () => {{
  try {{ if(stream) stream.getTracks().forEach(t=>t.stop()); if(peer) peer.destroy(); }} catch(e){{}}
}});
start();
</script></body></html>
"""
    components.html(html, height=430, scrolling=False)


def camera_viewer(token: str, supabase_url: str, supabase_key: str):
    html = f"""
<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://unpkg.com/@supabase/supabase-js@2"></script>
<script src="https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js"></script>
<style>
body{{margin:0;background:#080808;color:white;font-family:Arial,sans-serif}}
.wrap{{padding:12px}}
video{{width:100%;min-height:260px;max-height:70vh;background:#000;border-radius:12px;object-fit:contain}}
.status{{margin:10px 0;padding:10px;border-radius:9px;background:#222;text-align:center}}
.live{{background:#650000}}
.note{{font-size:12px;color:#aaa;text-align:center}}
</style></head>
<body>
<div class="wrap">
  <div id="status" class="status">Connecting to emergency camera…</div>
  <video id="remote" autoplay playsinline controls></video>
  <div class="note">The video is peer-to-peer. This page does not record the camera stream.</div>
</div>
<script>
const TOKEN = {token!r};
const SUPABASE_URL = {supabase_url!r};
const SUPABASE_KEY = {supabase_key!r};
const sb = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
let peer=null, call=null, timer=null;

function status(text,live=false) {{
  const el=document.getElementById('status'); el.textContent=text;
  el.className='status'+(live?' live':'');
}}

async function getSession() {{
  const {{data,error}}=await sb.rpc('get_camera_session',{{p_token:TOKEN}});
  if(error) throw error;
  if(!data || !data.length) return null;
  return data[0];
}}

function makeDummyStream() {{
  const c=document.createElement('canvas'); c.width=2; c.height=2;
  const ctx=c.getContext('2d'); ctx.fillStyle='black'; ctx.fillRect(0,0,2,2);
  return c.captureStream(1);
}}

async function connectToPeer(peerId) {{
  if(!peerId) return;
  if(call) try{{call.close();}}catch(e){{}}
  const dummy=makeDummyStream();
  call=peer.call(peerId,dummy);
  if(!call) {{ status('Could not create camera call'); return; }}
  call.on('stream', remoteStream => {{
    document.getElementById('remote').srcObject=remoteStream;
    status('🔴 LIVE — Guardian is watching',true);
  }});
  call.on('close',()=>{{ status('Camera connection ended'); }});
  call.on('error',e=>{{ status('Camera connection error'); console.error(e); }});
}}

async function start() {{
  try {{
    peer=new Peer(undefined,{{secure:true,debug:1}});
    peer.on('open',async()=>{{
      status('Looking for the user camera…');
      timer=setInterval(async()=>{{
        try {{
          const s=await getSession();
          if(!s) {{status('Emergency camera session not found or expired');return;}}
          if(s.status!=='active') {{status('Emergency camera has ended'); clearInterval(timer); return;}}
          if(s.peer_id && (!call || call.peer!==s.peer_id)) await connectToPeer(s.peer_id);
        }} catch(e) {{console.error(e);}}
      }},2000);
      const s=await getSession();
      if(s && s.peer_id) await connectToPeer(s.peer_id);
    }});
    peer.on('error',e=>{{status('Viewer connection error: '+e.type);console.error(e);}});
  }} catch(e) {{status('Unable to start viewer');console.error(e);}}
}}
start();
</script></body></html>
"""
    components.html(html, height=560, scrolling=False)
