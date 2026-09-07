# Migration notes from the original Shathia code

## Changed for voice/motion emergencies

The old voice/motion flow recorded 15-second audio clips and then used a 30-second Streamlit sleep/rerun loop for GPS email updates.

The upgraded flow creates a single secure LiveKit incident and sends the emergency contact a signed **WATCH LIVE NOW** link. Camera, microphone and GPS then remain connected directly through LiveKit until the user stops the emergency session.

## Kept

- Saved contacts in browser localStorage
- Gmail alert delivery
- Guardian journey mode
- Voice distress keyword detection
- Motion/shake detection
- Manual panic button
- Extreme panic live-location mode
- Nearest-police lookup

## Added

- Secure live back-camera stream
- Live microphone audio
- Front/back camera switch
- Live GPS over LiveKit data packets
- Subscribe-only guardian tokens
- HMAC-signed viewer links with expiration
- Supabase emergency incident table
- Test-live-emergency mode
- Secrets moved out of source code
