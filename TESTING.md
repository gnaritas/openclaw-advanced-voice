# Testing Guide - @openclaw/advanced-voice

## Pre-Flight Checklist

Before testing, verify:

```bash
# 1. Plugin loaded
openclaw plugins list --json | jq '.plugins[] | select(.id == "advanced-voice") | .status'
# Expected: "loaded"

# 2. Voice server running
lsof -i :8001 | grep LISTEN
# Expected: python process listening on port 8001

# 3. Environment variables set
echo $TWILIO_ACCOUNT_SID $OPENAI_API_KEY $VOICE_API_KEY | wc -w
# Expected: 3 (all three set)

# 4. Gateway health
curl -s http://127.0.0.1:18789/health | jq
# Expected: {"status": "ok"}
```

---

## Test Suite

### Test 1: Server Health Check

```bash
curl -s http://localhost:8001/ | jq
```

**Expected output:**
```json
{
  "status": "Twilio Voice Server",
  "version": "1.0"
}
```

**If fails:** Voice server not running. Check Gateway logs.

---

### Test 2: Outbound Call (CLI)

```bash
~/clawd/bin/call ramon "This is a test call from the advanced voice plugin"
```

**Expected behavior:**
1. Phone rings within 5 seconds
2. Assistant says: "Hey Ramon, it's your assistant. I'm calling because..."
3. Natural conversation flow
4. Tool calls execute (if requested)
5. Call ends gracefully

**Verification:**
```bash
# Check transcript was logged
cat ~/clawd/memory/$(date +%Y-%m-%d).md | grep -A 20 "Voice Call"

# Check voice-calls archive
tail -50 ~/clawd/memory/voice-calls.md
```

---

### Test 3: Outbound Call (HTTP API)

```bash
curl -X POST http://localhost:8001/call/number/+14802203573 \
  -H "X-Voice-Key: $VOICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Testing advanced voice plugin via HTTP API",
    "agent_timezone": "America/Los_Angeles"
  }' | jq
```

**Expected output:**
```json
{
  "success": true,
  "call_sid": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "to": "+14802203573",
  "from": "+your-twilio-number",
  "status": "queued"
}
```

---

### Test 4: Inbound Call - Troll Mode

**Steps:**
1. Call your Twilio number from your phone
2. Wait for the assistant to speak first

**Expected flow:**
```
Assistant: "Hello?"
You: "Hi, I need help"
Assistant: [Mocking/unhelpful response - TROLL MODE]
You: "Can you assist me?"
Assistant: [Continues trolling]
```

**Success criteria:**
- Assistant speaks first
- Assistant is evasive/unhelpful
- No tool access granted
- Eventually hangs up if no passphrase

---

### Test 5: Inbound Call - Authentication

**Steps:**
1. Call your Twilio number
2. Wait for assistant greeting
3. Say the passphrase: **"your-secret-passphrase"**

**Expected flow:**
```
Assistant: "Hello?"
You: "Hi"
Assistant: "Who is calling?"
You: "your-secret-passphrase"
Assistant: "Awakening. Full system access granted."
```

**Success criteria:**
- Assistant transforms from troll to helpful
- Full tool access now available
- Can execute commands

---

### Test 6: Tool Execution - Time Query

**During authenticated call:**
```
You: "What time is it?"
```

**Expected:**
- Jarvis pauses briefly (System 2 call)
- Assistant responds: "The current time is [time] [timezone]"
- No errors or "I don't know"

**Verification:**
```bash
# Check transcript for tool call
cat ~/clawd/memory/$(date +%Y-%m-%d).md | grep -A 5 "get_time"
```

---

### Test 7: Tool Execution - Web Search

**During authenticated call:**
```
You: "Search the web for latest AI news"
```

**Expected:**
- Longer pause (web search takes time)
- Jarvis summarizes results naturally
- No "I can't do that"

**Verification:**
```bash
# Check transcript for web_search tool call
cat ~/clawd/memory/$(date +%Y-%m-%d).md | grep -A 10 "web_search"
```

---

### Test 8: Tool Execution - File Operations

**During authenticated call:**
```
You: "What files are in my home directory?"
```

**Expected:**
- Jarvis routes to System 2
- Executes command
- Reads back results

**Verification:**
```bash
# Check transcript for execute_command tool call
cat ~/clawd/memory/$(date +%Y-%m-%d).md | grep -A 10 "execute_command"
```

---

### Test 9: Transcript Completeness

**After any call:**

```bash
# Check today's memory file
TRANSCRIPT=$(cat ~/clawd/memory/$(date +%Y-%m-%d).md)

# Verify required elements
echo "$TRANSCRIPT" | grep -q "Voice Call" && echo "✓ Call header present"
echo "$TRANSCRIPT" | grep -q "Call ID:" && echo "✓ Call ID logged"
echo "$TRANSCRIPT" | grep -q "Duration:" && echo "✓ Duration logged"
echo "$TRANSCRIPT" | grep -q "Ramon:" && echo "✓ User messages logged"
echo "$TRANSCRIPT" | grep -q "Assistant:" && echo "✓ Assistant responses logged"
```

**Expected:** All checks pass (✓)

---

### Test 10: Prompt Customization

**Steps:**
1. Edit prompt file:
   ```bash
   vim ~/.openclaw/extensions/advanced-voice/prompts/outbound.txt
   # Change greeting to: "Greetings Ramon, Jarvis here."
   ```

2. Restart Gateway:
   ```bash
   openclaw gateway restart
   ```

3. Make outbound call:
   ```bash
   ~/clawd/bin/call ramon "Test custom greeting"
   ```

**Expected:**
- Jarvis uses new greeting
- No code changes needed
- Prompt loaded on startup

---

### Test 11: Concurrent Calls (Stress Test)

**Only if you have multiple Twilio numbers:**

```bash
# Start 3 calls simultaneously
~/clawd/bin/call ramon "Test 1" &
~/clawd/bin/call ramon "Test 2" &
~/clawd/bin/call ramon "Test 3" &
wait
```

**Expected:**
- All calls succeed
- No crashes
- All transcripts logged correctly

---

### Test 12: Error Handling - Invalid API Key

```bash
curl -X POST http://localhost:8001/call/number/+14802203573 \
  -H "X-Voice-Key: WRONG_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test"}' 
```

**Expected output:**
```json
{
  "detail": "Forbidden: Invalid Jarvis API Key"
}
```

**HTTP status:** 403

---

### Test 13: Error Handling - Missing Credentials

**Steps:**
1. Temporarily unset Twilio credentials:
   ```bash
   unset TWILIO_ACCOUNT_SID
   ```

2. Restart Gateway:
   ```bash
   openclaw gateway restart
   ```

3. Attempt call:
   ```bash
   ~/clawd/bin/call ramon "Test"
   ```

**Expected:**
- Call fails gracefully
- Error logged to Gateway logs
- No crash

**Restore:**
```bash
export TWILIO_ACCOUNT_SID="ACxxxxxxxx"
openclaw gateway restart
```

---

### Test 14: Narrative Context Bridge

**Steps:**
1. Write something to today's memory:
   ```bash
   echo "## Important Note\n\nRamon prefers morning calls before 10 AM." >> ~/clawd/memory/$(date +%Y-%m-%d).md
   ```

2. Make a call:
   ```bash
   ~/clawd/bin/call ramon "Quick check-in"
   ```

3. Ask Assistant:
   ```
   You: "When do I prefer calls?"
   ```

**Expected:**
- Jarvis has access to today's context
- Responds: "You prefer morning calls before 10 AM"
- Narrative bridge is working

---

### Test 15: Coexistence with Built-in Plugin

**If both plugins enabled:**

```bash
# Check both are running
lsof -i :3334  # Built-in voice-call
lsof -i :8001  # Advanced-voice

# Make call via built-in
openclaw voicecall notify --to "+14802203573" --message "Test from built-in"

# Make call via advanced
~/clawd/bin/call ramon "Test from advanced"
```

**Expected:**
- Both plugins work independently
- No port conflicts
- No interference

---

## Performance Benchmarks

### Latency Targets

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **First response** | < 1s | Time from "Hello?" to Jarvis speaking |
| **Tool call (local)** | < 3s | Time from question to answer (e.g., "What time is it?") |
| **Tool call (web)** | < 8s | Time from question to answer (e.g., "Search the web...") |
| **Transcription delay** | < 500ms | User finishes speaking → OpenAI recognizes end |

**Measure manually:**
1. Record call audio
2. Use stopwatch or video analysis
3. Document in `~/clawd/memory/voice-performance.md`

---

## Regression Tests

Run after any code changes:

```bash
cd ~/.openclaw/extensions/advanced-voice

# Run all tests
bash -c '
  echo "=== Test 1: Health Check ==="
  curl -s http://localhost:8001/ | jq

  echo -e "\n=== Test 2: Outbound Call ==="
  ~/clawd/bin/call ramon "Regression test" 

  echo -e "\n=== Test 3: Transcript Logged ==="
  grep -q "Voice Call" ~/clawd/memory/$(date +%Y-%m-%d).md && echo "✓ Pass" || echo "✗ Fail"

  echo -e "\n=== Test 4: Config Valid ==="
  openclaw config validate && echo "✓ Pass" || echo "✗ Fail"
'
```

---

## Debugging Failures

### Call doesn't connect
```bash
# Check Twilio logs
curl -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Calls.json?PageSize=1"

# Check voice server logs
journalctl -u openclaw-gateway -f | grep advanced-voice

# Check local server log
tail -f ~/.openclaw/extensions/advanced-voice/server.log
```

### Tool calls fail
```bash
# Test Gateway connectivity
curl http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw:main",
    "messages": [{"role": "user", "content": "Test"}]
  }'

# Check jarvis_integration.py logs
grep "Brain" ~/.openclaw/extensions/advanced-voice/server.log | tail -20
```

### Transcripts not logging
```bash
# Check memory directory exists
ls -ld ~/clawd/memory/

# Check permissions
touch ~/clawd/memory/test.md && rm ~/clawd/memory/test.md

# Check plugin config
openclaw config get plugins.entries.advanced-voice.config.logging
```

---

## Test Coverage Matrix

| Feature | Test # | Status |
|---------|--------|--------|
| Server health | 1 | ✅ |
| Outbound call (CLI) | 2 | ✅ |
| Outbound call (API) | 3 | ✅ |
| Inbound troll mode | 4 | ✅ |
| Inbound auth | 5 | ✅ |
| Tool: time query | 6 | ✅ |
| Tool: web search | 7 | ✅ |
| Tool: file ops | 8 | ✅ |
| Transcript logging | 9 | ✅ |
| Prompt customization | 10 | ✅ |
| Concurrent calls | 11 | ✅ |
| Error: invalid key | 12 | ✅ |
| Error: missing creds | 13 | ✅ |
| Narrative bridge | 14 | ✅ |
| Coexistence | 15 | ✅ |

---

## Next Steps

1. ✅ All tests passing
2. 📝 Document any failures in Trello Bugs
3. 🚀 Share results with team
4. 🔄 Run regression suite weekly
5. 📊 Monitor performance metrics

---

**Testing complete! 🧪**
