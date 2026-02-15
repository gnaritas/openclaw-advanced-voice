# Config Schema - @openclaw/advanced-voice

## openclaw.json Configuration

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
            "fromNumber": "+15551234567"
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
          },
          "prompts": {
            "inbound": "~/.openclaw/extensions/advanced-voice/prompts/inbound.txt",
            "outbound": "~/.openclaw/extensions/advanced-voice/prompts/outbound.txt"
          }
        }
      }
    }
  }
}
```

---

## Full Schema Reference

```typescript
interface AdvancedVoiceConfig {
  // Plugin enable/disable
  enabled: boolean;  // default: true

  // Voice server port
  port: number;  // default: 8001

  // Provider (only Twilio supported currently)
  provider: 'twilio';

  // Twilio configuration
  twilio: {
    accountSid: string;     // Twilio Account SID (ACxxxxxxxx)
    authToken: string;      // Twilio Auth Token
    fromNumber: string;     // E.164 format: +1234567890
  };

  // OpenAI Realtime API
  openai: {
    apiKey: string;         // OpenAI API key with Realtime access
  };

  // Security settings
  security: {
    challenge: string;      // Passphrase for inbound auth (default: "your-secret-passphrase")
    apiKey: string;         // Internal API key for voice server endpoints
  };

  // Transcript logging
  logging: {
    transcripts: boolean;   // Enable transcript logging (default: true)
    memoryPath: string;     // Where to write transcripts (default: ~/clawd/memory)
  };

  // Prompt file paths (optional)
  prompts?: {
    inbound: string;        // Path to inbound prompt file
    outbound: string;       // Path to outbound prompt file
  };
}
```

---

## Config Using CLI

```bash
# Enable plugin
openclaw config set plugins.entries.advanced-voice.enabled true

# Set port
openclaw config set plugins.entries.advanced-voice.config.port 8001

# Set Twilio credentials
openclaw config set plugins.entries.advanced-voice.config.twilio.accountSid "ACxxxxxxxx"
openclaw config set plugins.entries.advanced-voice.config.twilio.authToken "your_token"
openclaw config set plugins.entries.advanced-voice.config.twilio.fromNumber "+15551234567"

# Set OpenAI key
openclaw config set plugins.entries.advanced-voice.config.openai.apiKey "sk-proj-xxxxx"

# Set security challenge
openclaw config set plugins.entries.advanced-voice.config.security.challenge "your-secret-passphrase"
openclaw config set plugins.entries.advanced-voice.config.security.apiKey "your_api_key"

# Enable transcript logging
openclaw config set plugins.entries.advanced-voice.config.logging.transcripts true
openclaw config set plugins.entries.advanced-voice.config.logging.memoryPath "~/clawd/memory"
```

---

## Environment Variable Expansion

Config values starting with `${` will be expanded from environment:

```json
{
  "twilio": {
    "accountSid": "${TWILIO_ACCOUNT_SID}",
    "authToken": "${TWILIO_AUTH_TOKEN}"
  }
}
```

**Set in shell:**
```bash
export TWILIO_ACCOUNT_SID="ACxxxxxxxx"
export TWILIO_AUTH_TOKEN="your_token"
```

---

## Validation Rules

### Required Fields
- `twilio.accountSid` — Must start with "AC"
- `twilio.authToken` — Must not be empty
- `twilio.fromNumber` — Must match E.164 format (`^\+[1-9]\d{1,14}$`)
- `openai.apiKey` — Must not be empty

### Optional Fields
- `enabled` — Default: `true`
- `port` — Default: `8001`
- `provider` — Default: `twilio` (only option currently)
- `security.challenge` — Default: `"your-secret-passphrase"`
- `logging.transcripts` — Default: `true`
- `logging.memoryPath` — Default: `~/clawd/memory`

---

## Example Configs

### Minimal (Required Only)
```json
{
  "plugins": {
    "entries": {
      "advanced-voice": {
        "enabled": true,
        "config": {
          "twilio": {
            "accountSid": "ACxxxxxxxx",
            "authToken": "your_token",
            "fromNumber": "+15551234567"
          },
          "openai": {
            "apiKey": "sk-proj-xxxxx"
          }
        }
      }
    }
  }
}
```

### Full (All Options)
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
          },
          "prompts": {
            "inbound": "~/.openclaw/extensions/advanced-voice/prompts/inbound.txt",
            "outbound": "~/.openclaw/extensions/advanced-voice/prompts/outbound.txt"
          }
        }
      }
    }
  }
}
```

### Development (Disabled)
```json
{
  "plugins": {
    "entries": {
      "advanced-voice": {
        "enabled": false,
        "config": {
          "port": 8001,
          "twilio": {
            "accountSid": "test",
            "authToken": "test",
            "fromNumber": "+10000000000"
          },
          "openai": {
            "apiKey": "test"
          }
        }
      }
    }
  }
}
```

---

## Config Validation Errors

### Missing Required Fields
```
Error: advanced-voice config validation failed:
  - twilio.accountSid is required
  - twilio.authToken is required
  - twilio.fromNumber is required
  - openai.apiKey is required
```

### Invalid Phone Number
```
Error: advanced-voice config validation failed:
  - twilio.fromNumber must match E.164 format: +[country][number]
  Example: +14155551234
```

### Invalid Port
```
Error: advanced-voice config validation failed:
  - port must be a number between 1 and 65535
```

---

## Testing Config

```bash
# Validate config without starting Gateway
openclaw config validate

# Check parsed config
openclaw config get plugins.entries.advanced-voice

# Dry run (check what would load)
openclaw plugins list --json | jq '.plugins[] | select(.id == "advanced-voice")'
```

---

## Migration from Standalone voice-server

If migrating from `~/clawd/voice-server/`:

1. **Environment variables** — Same names, no changes needed
2. **Prompts** — Copy to plugin `prompts/` directory
3. **Config** — Port from `.env` to `openclaw.json`
4. **Watchdog** — No longer needed (Gateway manages lifecycle)
5. **Tunnel** — Can use same PUBLIC_URL

**Migration script:**
```bash
# Copy prompts
cp ~/clawd/voice-server/prompts/*.txt ~/.openclaw/extensions/advanced-voice/prompts/

# Copy .env values to shell exports
grep -E '^(TWILIO|OPENAI|VOICE)' ~/clawd/voice-server/.env >> ~/.zshrc

# Reload shell
source ~/.zshrc

# Configure plugin
openclaw config edit
# (Add advanced-voice config)

# Restart
openclaw gateway restart
```

---

## Next Steps

1. ✅ Config validated
2. 📝 Set environment variables
3. 🔧 Install Python dependencies
4. 🚀 Restart Gateway
5. 📞 Test calls

See [INSTALL.md](./INSTALL.md) for full setup guide.
