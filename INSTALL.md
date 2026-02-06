# Installation Guide - @openclaw/advanced-voice

## Prerequisites

1. **OpenClaw Gateway** running (v2026.2.2 or later)
2. **Twilio account** with Programmable Voice enabled
3. **OpenAI API key** with Realtime API access
4. **Python 3.10+** installed

---

## Step 1: Plugin Files

Plugin is already scaffolded at:
```
~/.openclaw/extensions/advanced-voice/
├── index.js               # Plugin entry point
├── server.py              # Voice server (FastAPI)
├── jarvis_integration.py  # System 2 bridge
├── prompts/               # Externalized prompts
│   ├── jarvis-base.txt    # Inbound (troll → Jarvis)
│   └── jarvis-outbound.txt # Outbound (friendly assistant)
├── package.json
├── requirements.txt       # Python deps
├── README.md
└── INSTALL.md (this file)
```

---

## Step 2: Install Python Dependencies

```bash
cd ~/.openclaw/extensions/advanced-voice
pip3 install -r requirements.txt
```

**Verify:**
```bash
python3 -c "import fastapi, aiohttp, twilio, dotenv, pytz; print('✓ All dependencies installed')"
```

---

## Step 3: Configure Environment Variables

Add to `~/.zshrc` (or `~/.bashrc`):

```bash
# Twilio credentials
export TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_AUTH_TOKEN="your_twilio_auth_token"
export TWILIO_NUMBER="+15551234567"  # Your Twilio phone number

# OpenAI Realtime API
export OPENAI_API_KEY="sk-proj-xxxxxxxxxxxxx"

# Voice server API key (internal security)
export VOICE_API_KEY="$(openssl rand -hex 32)"  # Generate once, save it

# OpenClaw Gateway token (for System 2 bridge)
export OPENCLAW_GATEWAY_TOKEN="$(openclaw config get gateway.token)"
```

**Apply changes:**
```bash
source ~/.zshrc
```

---

## Step 4: Configure in `openclaw.json`

Add to `plugins.entries` section:

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

**Edit config safely:**
```bash
openclaw config edit
# (Opens in your $EDITOR)
```

---

## Step 5: Public URL for Inbound Calls

### Option A: ngrok (Quick Testing)
```bash
ngrok http 8001
# Copy the HTTPS URL: https://abc123.ngrok.io
```

### Option B: Cloudflare Tunnel (Permanent)
```bash
cloudflared tunnel --url http://localhost:8001
# Copy the HTTPS URL
```

### Option C: Tailscale Funnel (Secure)
```bash
tailscale funnel 8001
# Copy the HTTPS URL
```

**Save your public URL:**
```bash
export PUBLIC_URL="https://your-tunnel-url.ngrok.io"
```

---

## Step 6: Configure Twilio Webhook

1. Go to [Twilio Console](https://console.twilio.com/)
2. Navigate to: **Phone Numbers → Manage → Active Numbers**
3. Click your phone number
4. Scroll to **Voice & Fax** section
5. Set **A CALL COMES IN** webhook:
   ```
   https://your-tunnel-url.ngrok.io/incoming-call
   ```
6. HTTP Method: **POST**
7. Click **Save**

---

## Step 7: Restart Gateway

```bash
openclaw gateway restart
```

**Check logs:**
```bash
journalctl -u openclaw-gateway -f | grep advanced-voice
```

**Expected output:**
```
[advanced-voice] Plugin loaded
[advanced-voice] Starting voice server on port 8001
[advanced-voice] Voice server started
```

---

## Step 8: Test Outbound Call

### Via CLI Wrapper
```bash
~/clawd/bin/call ramon "Test call from plugin"
```

### Via HTTP API
```bash
curl -X POST http://localhost:8001/call/number/+14802203573 \
  -H "X-Voice-Key: $VOICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Testing advanced voice plugin"}'
```

### Via Agent Tool
In OpenClaw chat:
```
Can you call me via the advanced voice system?
```

Agent will use `advanced_voice_call` tool.

---

## Step 9: Test Inbound Call

1. **Call your Twilio number** from your phone
2. **Assistant should say:** "Hello?"
3. **Assistant should ask:** "Who is calling?"
4. **Say:** "your-secret-passphrase"
5. **Assistant should respond:** "Awakening. Full system access granted."
6. **Now test tools:**
   - "What time is it?"
   - "Check my calendar"
   - "Search the web for latest AI news"

---

## Step 10: Verify Transcript Logging

After a call ends:

```bash
# Check today's memory file
cat ~/clawd/memory/$(date +%Y-%m-%d).md | tail -50

# Check voice calls archive
cat ~/clawd/memory/voice-calls.md | tail -50
```

**Expected format:**
```markdown
## 📞 Voice Call - 2026-02-05T16:30:00

**Call ID:** CAxxxxxxxxxxxx
**Duration:** 45 seconds

### Conversation:

**Ramon:** What time is it?

**Assistant:** The current time is 4:30 PM PST.

*🔧 Tool: get_time* `{"timezone": "America/Los_Angeles"}`

*✅ Result: Success*
```

---

## Troubleshooting

### Plugin won't load
```bash
# Check plugin list
openclaw plugins list --json | jq '.plugins[] | select(.id == "advanced-voice")'

# Check for errors
journalctl -u openclaw-gateway -f | grep -i error
```

### Voice server won't start
```bash
# Check port availability
lsof -i :8001

# Test Python directly
cd ~/.openclaw/extensions/advanced-voice
python3 server.py
```

### Inbound calls fail
```bash
# Test webhook endpoint
curl https://your-tunnel-url.ngrok.io/incoming-call

# Check Twilio webhook logs
# Go to: https://console.twilio.com/us1/monitor/logs/debugger
```

### Tool calls fail (System 2 bridge broken)
```bash
# Test Gateway connectivity
curl http://127.0.0.1:18789/health

# Check token
echo $OPENCLAW_GATEWAY_TOKEN

# Verify it matches config
openclaw config get gateway.token
```

---

## Uninstallation

```bash
# 1. Disable in config
openclaw config set plugins.entries.advanced-voice.enabled false

# 2. Restart Gateway
openclaw gateway restart

# 3. Remove plugin files (optional)
rm -rf ~/.openclaw/extensions/advanced-voice
```

---

## Running Alongside Built-in voice-call Plugin

Both plugins can coexist:

**Config:**
```json
{
  "plugins": {
    "entries": {
      "voice-call": {
        "enabled": true,
        "config": {
          "serve": { "port": 3334 }
        }
      },
      "advanced-voice": {
        "enabled": true,
        "config": {
          "port": 8001
        }
      }
    }
  }
}
```

**Use cases:**
- Built-in: Simple notify calls
- Advanced: Full conversations with System 2

---

## Next Steps

1. ✅ Plugin installed and working
2. 📝 Edit prompts in `prompts/` to customize behavior
3. 🔧 Add custom tools in `server.py` → `TOOLS` array
4. 📊 Monitor transcripts in `~/clawd/memory/`
5. 🚀 Share with team (commit plugin to repo)

---

## Support

- **Documentation:** [README.md](./README.md)
- **Issues:** Create ticket in Trello Bugs list
- **Discussion:** #ai-chat channel in Slack

---

**Plugin ready! 🎙️**
