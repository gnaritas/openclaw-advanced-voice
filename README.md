# @openclaw/advanced-voice

**Advanced voice calling plugin for OpenClaw with System 1/2 architecture.**

## Features

### 🏗️ System 1/2 Architecture
- **System 1 (OpenAI Realtime)**: Fast, conversational, handles real-time voice dialogue
- **System 2 (OpenClaw backend)**: Slow, deliberate, executes tools and provides deep reasoning
- Seamless integration via tool relay — voice handles interface, OpenClaw handles intelligence

### 🔒 Security Challenge
- Inbound calls start in TROLL MODE (defensive, evasive)
- Caller must provide passphrase: **"your-secret-passphrase"**
- Successful authentication unlocks full assistant capabilities
- Failed attempts result in playful trolling + eventual hangup

### 📝 Full Transcript Logging
- Every conversation logged to `~/clawd/memory/YYYY-MM-DD.md`
- Separate voice-calls.md for historical archive
- Includes timestamps, tool calls, and complete dialogue
- The assistant remembers past calls via memory system

### 📂 Externalized Prompts
- `prompts/inbound.txt` — Inbound call behavior
- `prompts/outbound.txt` — Outbound mission behavior
- Edit prompts without touching code
- Restart voice server to apply changes

### 🌉 Unified Mind Bridge
- Loads workspace context via `~/clawd/bin/narrative`
- System 2 (Voice) wakes with System 1 (Chat) context
- No duplicate explanations across modalities
- Seamless continuity between chat and voice

---

## Installation

### 1. Plugin Files
```bash
# Plugin is already scaffolded at:
~/.openclaw/extensions/advanced-voice/
```

### Deployment
- See `DEPLOYMENT.md` for the production deploy runbook (Linux -> Mac `clawd`).
- Canonical flow: push to GitHub, then pull on `mac` and restart gateway.

### 2. Configure in `openclaw.json`
Add to `plugins.entries`:

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
            "fromNumber": "+your-twilio-number"
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

### 3. Environment Variables
Set in your shell or `.env`:

```bash
export TWILIO_ACCOUNT_SID="ACxxxxxxxx"
export TWILIO_AUTH_TOKEN="your_twilio_auth_token"
export OPENAI_API_KEY="sk-proj-..."
export VOICE_API_KEY="your_voice_api_key"
```

### 4. Python Dependencies
```bash
cd ~/.openclaw/extensions/advanced-voice
pip install -r requirements.txt
```

---

## Usage

### Restart Gateway
```bash
openclaw gateway restart
```

The plugin will:
1. Load on Gateway startup
2. Start Python voice server on port 8001 (configurable)
3. Register `advanced_voice_call` tool for agent use

### Initiate Calls

#### Via Tool (Agent-Driven)
```javascript
// The agent can call this directly
{
  "tool": "advanced_voice_call",
  "to": "+14802203573",
  "message": "Hey Ramon, quick update on project X"
}
```

#### Via CLI Wrapper (Manual)
```bash
~/clawd/bin/call ramon "Test call"
```

#### Via HTTP API (Internal)
```bash
curl -X POST http://localhost:8001/call/number/+14802203573 \
  -H "X-Voice-Key: $VOICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Custom instructions here"}'
```

### Inbound Calls

**Setup Twilio webhook:**
- Point incoming call URL to: `https://your-public-url/incoming-call`
- Use ngrok, Cloudflare Tunnel, or Tailscale Funnel for public URL

**Flow:**
1. Call connects → Assistant in TROLL MODE
2. Assistant says: "Hello?"
3. Assistant asks: "Who is calling?"
4. Caller says: "your-secret-passphrase"
5. Assistant responds: "Awakening. Full system access granted."
6. FULL ASSISTANT MODE activated (all tools available)

---

## Architecture

### Call Flow
```
User Phone → Twilio → Voice Server (Python/FastAPI) → OpenAI Realtime API
                ↓
         System 1 (Voice Interface)
                ↓
         Tool Calls → jarvis_integration.py
                ↓
         System 2 (OpenClaw backend via Gateway HTTP API)
                ↓
         Execute Tools, Return Results
                ↓
         Relay to OpenAI → User Phone
```

### Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `index.js` | Plugin entry point, spawns voice server | Node.js |
| `server.py` | FastAPI voice server, handles Twilio Media Streams | Python/FastAPI |
| `jarvis_integration.py` | Tool execution relay to OpenClaw backend | Python/aiohttp |
| `prompts/` | Externalized prompt files | Plain text |
| `lib/` | Shared utilities (future) | Python |

### System 1 vs System 2

**System 1 (OpenAI Realtime):**
- ⚡ Fast response (< 500ms latency)
- 🎙️ Natural voice conversation
- 🔄 Interruption handling
- 📞 Call management

**System 2 (OpenClaw):**
- 🧠 Deep reasoning
- 🛠️ Tool execution (files, messages, web search)
- 🧠 Memory recall
- 📊 Strategic decisions

**Bridge:** `answer_user_query` and `execute_system_action` tools route to System 2 via HTTP.

---

## Configuration Reference

### Plugin Config Schema

```typescript
{
  enabled: boolean;              // Enable/disable plugin (default: true)
  port: number;                  // Voice server port (default: 8001)
  provider: 'twilio';            // Only Twilio supported currently
  twilio: {
    accountSid: string;          // Twilio Account SID
    authToken: string;           // Twilio Auth Token
    fromNumber: string;          // E.164 format: +1234567890
  };
  openai: {
    apiKey: string;              // OpenAI API key (Realtime API access)
  };
  security: {
    challenge: string;           // Passphrase (default: "your-secret-passphrase")
    apiKey: string;              // Internal API key for voice server endpoints
  };
  logging: {
    transcripts: boolean;        // Log full transcripts (default: true)
    memoryPath: string;          // Where to write transcripts (default: ~/clawd/memory)
  };
}
```

---

## Differences from Built-in `voice-call` Plugin

| Feature | Built-in Plugin | Advanced-Voice |
|---------|----------------|----------------|
| **Architecture** | Agent loop (STT → LLM → TTS) | OpenAI Realtime + OpenClaw System 2 |
| **Latency** | ~2-5 seconds per turn | ~500ms (Realtime API) |
| **Security** | Simple allowlist | Passphrase challenge/response |
| **Transcript Logging** | Optional call log store | Full markdown logs to memory/ |
| **Prompts** | Config-only | Externalized files (easy editing) |
| **Tool Execution** | During STT → TTS cycle | Real-time via System 2 bridge |
| **Context Bridge** | N/A | Unified Mind narrative loader |
| **Ports** | 3334 (default) | 8001 (default) |

**When to use built-in:**
- Multi-provider support (Telnyx, Plivo)
- Simple notify mode (one-way messages)
- Standard OpenClaw tooling

**When to use advanced-voice:**
- Need low-latency conversation
- Want security challenge for inbound
- Need full transcript logging
- Using System 1/2 architecture
- Customizing prompts frequently

---

## Troubleshooting

### Voice server won't start
```bash
# Check logs
journalctl -u openclaw-gateway -f | grep advanced-voice

# Check port availability
lsof -i :8001

# Test Python dependencies
cd ~/.openclaw/extensions/advanced-voice
python3 -c "import fastapi, aiohttp, twilio; print('OK')"
```

### Inbound calls not working
```bash
# Check Twilio webhook configuration
curl https://your-public-url/incoming-call

# Verify API key
echo $VOICE_API_KEY

# Check server logs
tail -f ~/.openclaw/extensions/advanced-voice/server.log
```

### Tool calls failing
```bash
# Check Gateway connectivity
curl http://127.0.0.1:18789/health

# Verify GATEWAY_TOKEN
openclaw config get gateway.token

# Check jarvis_integration.py logs
grep "Brain" ~/.openclaw/extensions/advanced-voice/server.log
```

---

## Testing Guide

### 1. Outbound Call Test
```bash
# From CLI
~/clawd/bin/call ramon "Test message"

# Should:
# - Connect to Ramon's phone
# - Start with "Hey Ramon, it's Jarvis..."
# - Respond to voice commands
# - Execute tools via System 2
# - Log transcript to memory/YYYY-MM-DD.md
```

### 2. Inbound Call Test
```bash
# Call your Twilio number from your phone
# Should:
# 1. Assistant says: "Hello?"
# 2. Assistant asks: "Who is calling?"
# 3. Say: "your-secret-passphrase"
# 4. Assistant says: "Awakening. Full system access granted."
# 5. Now you have full access to tools
```

### 3. Tool Execution Test
```bash
# During call, say:
# "What time is it?"
# "Check my calendar"
# "Search the web for latest AI news"
# "Send a message to Chris"

# Should:
# - Route to System 2 (OpenClaw)
# - Execute tool
# - Return result naturally
# - Log tool call in transcript
```

### 4. Transcript Logging Test
```bash
# After call ends, check:
ls -lh ~/clawd/memory/$(date +%Y-%m-%d).md

# Should contain:
# - Call start timestamp
# - Full conversation (user + assistant)
# - Tool calls and results
# - Call end + duration
```

---

## Running Both Plugins

You can run built-in `voice-call` and `advanced-voice` simultaneously:

**Port separation:**
- Built-in: Port 3334 (default)
- Advanced: Port 8001 (default)

**Use case separation:**
- Built-in: Simple outbound notify calls
- Advanced: Full conversation mode with System 2

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

---

## Future Enhancements

- [ ] Multi-provider support (Telnyx, Plivo)
- [ ] Configurable challenge password per user
- [ ] Voice biometric authentication
- [ ] Call recording archive
- [ ] Voice command shortcuts ("Jarvis, schedule a meeting")
- [ ] Emotion detection + response tuning
- [ ] Multi-language support
- [ ] Emergency mode (override troll for urgent calls)

---

## Development

### Edit Prompts
```bash
# Edit behavior
vim ~/.openclaw/extensions/advanced-voice/prompts/inbound.txt

# Restart to apply
openclaw gateway restart
```

### Add Custom Tools
Edit `server.py` → `TOOLS` array → Add OpenAI function schema

### Modify Integration Logic
Edit `jarvis_integration.py` → `execute_tool_via_jarvis()`

---

## Credits

**Author:** Ramon Leon  
**Based on:** Custom voice-server system (~/clawd/voice-server/)  
**Architecture:** System 1/2 pattern inspired by Kahneman's "Thinking, Fast and Slow"  
**Voice Engine:** OpenAI Realtime API  
**Telephony:** Twilio Programmable Voice + Media Streams  

---

## License

MIT
