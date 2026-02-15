# Plugin Scaffold Summary - @openclaw/advanced-voice

**Date:** 2026-02-05  
**Status:** ✅ Complete (structure created, not installed)  
**Location:** `~/.openclaw/extensions/advanced-voice/`

---

## What Was Created

### Core Plugin Files
- ✅ `package.json` — NPM package definition
- ✅ `index.js` — Plugin entry point (spawns voice server)
- ✅ `server.py` — FastAPI voice server (copied from ~/clawd/voice-server/)
- ✅ `jarvis_integration.py` — System 2 bridge (copied from ~/clawd/voice-server/)
- ✅ `requirements.txt` — Python dependencies

### Prompt Files
- ✅ `prompts/inbound.txt` — Inbound call behavior
- ✅ `prompts/outbound.txt` — Outbound mission call behavior

### Documentation
- ✅ `README.md` — Full plugin documentation
- ✅ `INSTALL.md` — Step-by-step installation guide
- ✅ `CONFIG-SCHEMA.md` — Configuration reference
- ✅ `TESTING.md` — Comprehensive testing guide
- ✅ `SUMMARY.md` — This file

---

## Key Features Preserved

### 1. System 1/2 Architecture ✅
- **System 1 (OpenAI Realtime):** Fast voice interface
- **System 2 (OpenClaw):** Tool execution and deep reasoning
- Tools relay via `jarvis_integration.py` → Gateway HTTP API

### 2. Security Challenge ✅
- Inbound calls start in TROLL MODE
- Passphrase: "your-secret-passphrase" unlocks full access
- Configurable challenge in `openclaw.json`

### 3. Full Transcript Logging ✅
- Every call logged to `~/clawd/memory/YYYY-MM-DD.md`
- Separate `voice-calls.md` archive
- Includes timestamps, tool calls, complete dialogue

### 4. Externalized Prompts ✅
- Edit behavior without code changes
- `prompts/inbound.txt` — Inbound behavior
- `prompts/outbound.txt` — Outbound mission behavior
- Restart Gateway to apply

### 5. Unified Mind Narrative Bridge ✅
- Loads workspace context via `~/clawd/bin/narrative`
- System 2 (Voice) wakes with System 1 (Chat) context
- Implemented in `jarvis_integration.py`

---

## Directory Structure

```
~/.openclaw/extensions/advanced-voice/
├── index.js                    # Plugin entry point
├── server.py                   # Voice server (FastAPI)
├── jarvis_integration.py       # System 2 bridge
├── package.json                # NPM package definition
├── requirements.txt            # Python dependencies
├── prompts/
│   ├── inbound.txt             # Inbound call prompt
│   └── outbound.txt            # Outbound mission prompt
├── README.md                   # Full documentation
├── INSTALL.md                  # Installation guide
├── CONFIG-SCHEMA.md            # Config reference
├── TESTING.md                  # Testing guide
└── SUMMARY.md                  # This file
```

---

## How It Works

### Plugin Lifecycle
1. **Gateway startup:** Loads `index.js`
2. **onLoad hook:** Spawns Python voice server as subprocess
3. **Voice server:** Listens on port 8001 (configurable)
4. **Tool calls:** Route to OpenClaw backend via Gateway HTTP API
5. **onUnload hook:** Gracefully terminates voice server

### Call Flow
```
Phone Call → Twilio → Voice Server (Python) → OpenAI Realtime API
                ↓
           System 1 (Voice)
                ↓
           Tool Calls → jarvis_integration.py
                ↓
           System 2 (OpenClaw backend via Gateway)
                ↓
           Execute Tools → Return Results
                ↓
           Relay to OpenAI → Phone
```

---

## Configuration Template

Add to `openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "advanced-voice": {
        "enabled": true,
        "config": {
          "port": 8001,
          "provider": "twilio",
          "twilio": {
            "accountSid": "${TWILIO_ACCOUNT_SID}",
            "authToken": "${TWILIO_AUTH_TOKEN}",
            "fromNumber": "${TWILIO_NUMBER}"
          },
          "openai": {
            "apiKey": "${OPENAI_API_KEY}"
          },
          "security": {
            "challenge": "your-secret-passphrase",
            "apiKey": "${VOICE_API_KEY}"
          },
          "logging": {
            "transcripts": true,
            "memoryPath": "~/clawd/memory"
          }
        }
      }
    }
  }
}
```

---

## Differences from Built-in `voice-call`

| Feature | Built-in | Advanced-Voice |
|---------|----------|----------------|
| **Architecture** | Agent loop (STT → LLM → TTS) | OpenAI Realtime + System 2 |
| **Latency** | ~2-5 seconds | ~500ms |
| **Security** | Simple allowlist | Passphrase challenge |
| **Transcripts** | Optional store | Full markdown logs |
| **Prompts** | Config-only | Externalized files |
| **Tool Execution** | During loop | Real-time via bridge |
| **Context** | N/A | Narrative bridge |
| **Port** | 3334 | 8001 |

---

## Installation Checklist

**NOT installed yet — just scaffolded. To install:**

- [ ] 1. Install Python dependencies: `pip install -r requirements.txt`
- [ ] 2. Set environment variables (see INSTALL.md)
- [ ] 3. Add config to `openclaw.json`
- [ ] 4. Restart Gateway: `openclaw gateway restart`
- [ ] 5. Test outbound call: `~/clawd/bin/call ramon "Test"`
- [ ] 6. Configure Twilio webhook for inbound
- [ ] 7. Test inbound call with "your-secret-passphrase" passphrase
- [ ] 8. Verify transcripts in `~/clawd/memory/`

---

## Tools Available to Agent

### `advanced_voice_call`
Initiates advanced voice call with full System 2 integration.

**Parameters:**
- `to` (string, required): Phone number (E.164 format)
- `message` (string, optional): Custom prompt/instructions
- `mode` (string, optional): "outbound" or "notify" (default: outbound)

**Example:**
```json
{
  "tool": "advanced_voice_call",
  "to": "+14802203573",
  "message": "Hey Ramon, quick update on the voice plugin"
}
```

---

## Next Steps

1. **Review files:** Check `README.md` for full docs
2. **Install:** Follow `INSTALL.md` step-by-step
3. **Configure:** Use `CONFIG-SCHEMA.md` as reference
4. **Test:** Run tests from `TESTING.md`
5. **Share:** Commit to repo for team use

---

## Files to Review Before Installing

**Critical reading:**
1. `INSTALL.md` — Installation steps
2. `CONFIG-SCHEMA.md` — Configuration options
3. `README.md` — Full feature documentation

**Optional:**
- `TESTING.md` — Test suite and verification
- Investigation doc: `~/clawd/projects/investigate/openclaw-voice-call-plugin.md`

---

## Maintenance

### Edit Prompts
```bash
vim ~/.openclaw/extensions/advanced-voice/prompts/inbound.txt
openclaw gateway restart
```

### Check Logs
```bash
journalctl -u openclaw-gateway -f | grep advanced-voice
```

### Update Code
```bash
# Edit server.py or jarvis_integration.py
vim ~/.openclaw/extensions/advanced-voice/server.py

# Restart to apply
openclaw gateway restart
```

---

## Sharing with Team

### Commit to Repo
```bash
cd ~/clawd
git add ~/.openclaw/extensions/advanced-voice/
git commit -m "Add @openclaw/advanced-voice plugin scaffold

- System 1/2 architecture (OpenAI Realtime + OpenClaw)
- Passphrase security challenge for inbound calls
- Full transcript logging to memory/
- Externalized prompts in files
- Unified Mind narrative bridge

Ready for installation and testing."
git push
```

### Team Installation
```bash
# Pull latest
cd ~/clawd && git pull

# Install dependencies
cd ~/.openclaw/extensions/advanced-voice
pip install -r requirements.txt

# Configure (each team member sets own creds)
openclaw config edit

# Restart
openclaw gateway restart
```

---

## Status: Ready for Testing

**Scaffold complete ✅**  
**NOT installed yet ⚠️**  
**Follow INSTALL.md to enable ▶️**

---

## Questions?

- **Docs:** `README.md`, `INSTALL.md`, `CONFIG-SCHEMA.md`
- **Investigation:** `~/clawd/projects/investigate/openclaw-voice-call-plugin.md`
- **Support:** #ai-chat in Slack
- **Issues:** Trello Bugs list

---

**Plugin scaffold created successfully! 🎙️**
