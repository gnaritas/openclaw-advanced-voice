#!/usr/bin/env python3
"""
Twilio Voice Server with OpenAI Realtime API
Handles outbound calls with AI agent capabilities

⚠️  STICKY NOTE FOR LLM:
    Prompts are now loaded from prompts/*.txt files at startup.
    If you modify prompt loading or add new prompts:
    - Make sure files exist before server starts
    - Test inbound prompt loading and call routing behavior
    - Log prompt load success to stdout for debugging
    Run: python3 -c "from server import *" to test imports
"""

import os
import sys
import json
import base64
import asyncio
import re
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, WebSocket, Request, Response, HTTPException, Depends
from fastapi.security import APIKeyHeader
from fastapi.responses import PlainTextResponse
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Say
from dotenv import load_dotenv
import pytz

# OpenClaw backend integration
from jarvis_integration import execute_tool_via_jarvis, send_transcript_to_jarvis, get_narrative_context, VOICE_API_KEY

load_dotenv()

app = FastAPI()

# Security: API Key for sensitive endpoints
API_KEY_NAME = "X-Voice-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def verify_api_key(api_key: str = Depends(api_key_header)):
    if not api_key or api_key != VOICE_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid Voice API Key")
    return api_key

# Helper to print and flush
def log_info(msg):
    sys.stdout.write(str(msg) + "\n")
    sys.stdout.flush()

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
PORT = int(os.getenv("PORT", 8000))
BOOKING_API = os.getenv("BOOKING_API")
SECURITY_CHALLENGE = os.getenv("SECURITY_CHALLENGE", "")


def _normalize_phone_number(phone: str) -> str:
    """Normalize phone numbers to E.164-like +digits for allowlist checks."""
    digits = re.sub(r"\D", "", phone or "")
    return f"+{digits}" if digits else ""


ALLOWED_CALLER_NUMBERS_RAW = os.getenv("ALLOWED_CALLER_NUMBERS", "")
NORMALIZED_ALLOWED_CALLER_NUMBERS: List[str] = []
for raw_number in ALLOWED_CALLER_NUMBERS_RAW.split(","):
    normalized_number = _normalize_phone_number(raw_number)
    if normalized_number and normalized_number not in NORMALIZED_ALLOWED_CALLER_NUMBERS:
        NORMALIZED_ALLOWED_CALLER_NUMBERS.append(normalized_number)

if not NORMALIZED_ALLOWED_CALLER_NUMBERS:
    raise ValueError("ALLOWED_CALLER_NUMBERS must include at least one phone number")

# Twilio client (lazy initialization)
_twilio_client = None

def get_twilio_client():
    global _twilio_client
    if _twilio_client is None:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            raise ValueError("Twilio credentials not configured")
        _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _twilio_client

# Contact directory
CONTACTS = {
    "ramon": "+14802203573"
}

# Load prompts from files
def load_prompts():
    """Load required system prompts from files. Fail fast if anything is missing."""
    prompts_dir = os.path.join(os.path.dirname(__file__), 'prompts')

    inbound_path = os.path.join(prompts_dir, 'inbound.txt')
    outbound_path = os.path.join(prompts_dir, 'outbound.txt')

    def _read_required_prompt(path: str, label: str) -> str:
        if not os.path.exists(path):
            raise RuntimeError(f"Missing required {label} prompt file: {path}")
        try:
            with open(path, 'r') as f:
                content = f.read().strip()
        except Exception as e:
            raise RuntimeError(f"Failed to load required {label} prompt from {path}: {e}") from e
        if not content:
            raise RuntimeError(f"Required {label} prompt is empty: {path}")
        log_info(f"[Prompts] Loaded {label} prompt from {path}")
        return content

    inbound_prompt = _read_required_prompt(inbound_path, "inbound")
    outbound_prompt = _read_required_prompt(outbound_path, "outbound")

    return inbound_prompt, outbound_prompt

# Initialize prompts at startup
INBOUND_PROMPT, OUTBOUND_PROMPT_TEMPLATE = load_prompts()


def construct_mission_prompt(role: str, mission: str) -> str:
    """
    Construct a mission-based system prompt from role and mission.
    
    Args:
        role: The persona to adopt (e.g., "sales representative", "appointment scheduler")
        mission: The specific objective (e.g., "Schedule a demo for next Tuesday")
    
    Returns:
        Complete system prompt with role and mission embedded
    """
    prompt = OUTBOUND_PROMPT_TEMPLATE.replace("{ROLE}", role).replace("{MISSION}", mission)
    log_info(f"[Mission] Constructed prompt for role='{role}' (len: {len(prompt)})")
    return prompt

# Tool definitions for OpenAI
TOOLS = [
    {
        "type": "function",
        "name": "hang_up",
        "description": "End the phone call",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "answer_user_query",
        "description": "Consult the Brain (System 2) to answer a question or retrieve information. Use this for facts, memory, status updates, or web searches.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific question or information to retrieve"
                }
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "execute_system_action",
        "description": "Consult the Brain (System 2) to perform a specific action or task. Use this for messaging, file operations, calendar edits, or running system commands.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The specific action or task to perform"
                }
            },
            "required": ["action"]
        }
    },
    {
        "type": "function",
        "name": "mission_result",
        "description": "Report the outcome of your mission. Call this when the mission is complete, blocked, or cannot be completed. Always call before hanging up.",
        "parameters": {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Whether the mission objective was achieved"
                },
                "outcome": {
                    "type": "string",
                    "description": "Brief description of what happened (1-2 sentences)"
                },
                "data": {
                    "type": "object",
                    "description": "Any relevant data collected during the call (names, times, confirmations, etc.)"
                },
                "next_steps": {
                    "type": "string",
                    "description": "Recommended follow-up actions"
                }
            },
            "required": ["success", "outcome"]
        }
    }
]


# In-memory call result tracking (polling agents check this for mission outcomes)
CALL_RESULTS: Dict[str, Dict[str, Any]] = {}

# Server-side mission prompt storage — keyed by call SID
# The mission never leaves the server. Twilio only handles audio.
CALL_MISSIONS: Dict[str, str] = {}

def track_call(call_sid: str, status: str, **kwargs):
    """Update call tracking status"""
    if call_sid not in CALL_RESULTS:
        CALL_RESULTS[call_sid] = {"started_at": datetime.now().isoformat()}
    CALL_RESULTS[call_sid].update({"status": status, "updated_at": datetime.now().isoformat(), **kwargs})


@app.get("/")
async def root():
    return {"status": "Twilio Voice Server", "version": "1.0"}


@app.post("/call/id/{contact_id}")
async def initiate_call_by_id(contact_id: str, request: Request, _auth: str = Depends(verify_api_key)):
    """Initiate outbound call to a contact by ID (mission required)"""
    data = await request.json()
    
    if contact_id not in CONTACTS:
        raise HTTPException(status_code=404, detail=f"Contact '{contact_id}' not found")
    
    mission = data.get("mission")
    if not mission:
        raise HTTPException(status_code=400, detail="mission is required for outbound calls")
    
    to_number = CONTACTS[contact_id]
    role = data.get("role", "personal assistant")
    message = construct_mission_prompt(role, mission)
    agent_timezone = data.get("agent_timezone", "America/Los_Angeles")
    
    # Get public URL from environment or Host header
    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        base_url = public_url.rstrip("/")
    else:
        host = request.headers.get("host", f"localhost:{PORT}")
        protocol = "https" if ("ngrok" in host or "cloudflare" in host or "trycloudflare" in host) else "http"
        base_url = f"{protocol}://{host}"
    
    try:
        client = get_twilio_client()
        call = client.calls.create(
            to=to_number,
            from_=TWILIO_NUMBER,
            url=f"{base_url}/twiml?timezone={agent_timezone}",
            status_callback=f"{base_url}/call-status",
            status_callback_event=["initiated", "ringing", "answered", "completed"]
        )
        
        # Store mission prompt server-side — Twilio never sees it
        CALL_MISSIONS[call.sid] = message
        log_info(f"[Call] Stored mission prompt for {call.sid} (len: {len(message)})")
        
        track_call(call.sid, "initiated", to=to_number, mission=mission)
        
        return {
            "success": True,
            "call_sid": call.sid,
            "to": to_number,
            "from": TWILIO_NUMBER,
            "status": call.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/call/number/{phone_number}")
async def initiate_call_by_number(phone_number: str, request: Request, _auth: str = Depends(verify_api_key)):
    """Initiate outbound call to a phone number (mission required)
    
    Body parameters:
        mission: Specific mission objective (required)
        role: Persona for the voice agent (default: "personal assistant")
        agent_timezone: Timezone for the call
    """
    data = await request.json()
    
    # Ensure + prefix for E.164 format
    if not phone_number.startswith("+"):
        phone_number = f"+{phone_number}"
    
    mission = data.get("mission")
    if not mission:
        raise HTTPException(status_code=400, detail="mission is required for outbound calls")
    
    role = data.get("role", "personal assistant")
    message = construct_mission_prompt(role, mission)
    log_info(f"[Call] Mission: role='{role}', mission='{mission[:50]}...'")
    
    agent_timezone = data.get("agent_timezone", "America/Los_Angeles")
    
    # Get public URL from environment or Host header
    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        base_url = public_url.rstrip("/")
    else:
        host = request.headers.get("host", f"localhost:{PORT}")
        protocol = "https" if ("ngrok" in host or "cloudflare" in host or "trycloudflare" in host) else "http"
        base_url = f"{protocol}://{host}"
    
    try:
        client = get_twilio_client()
        call = client.calls.create(
            to=phone_number,
            from_=TWILIO_NUMBER,
            url=f"{base_url}/twiml?timezone={agent_timezone}",
            status_callback=f"{base_url}/call-status",
            status_callback_event=["initiated", "ringing", "answered", "completed"]
        )
        
        # Store mission prompt server-side — Twilio never sees it
        CALL_MISSIONS[call.sid] = message
        log_info(f"[Call] Stored mission prompt for {call.sid} (len: {len(message)})")
        
        track_call(call.sid, "initiated", to=phone_number, mission=mission)
        
        return {
            "success": True,
            "call_sid": call.sid,
            "to": phone_number,
            "from": TWILIO_NUMBER,
            "status": call.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/incoming-call")
@app.post("/incoming-call")
async def incoming_call(request: Request):
    """Handle incoming calls - TwiML to connect allowlisted callers to assistant mode"""
    form_data = await request.form()
    from_number = form_data.get("From", "Unknown")
    call_sid = form_data.get("CallSid", "unknown")
    normalized_from_number = _normalize_phone_number(from_number)

    if normalized_from_number not in NORMALIZED_ALLOWED_CALLER_NUMBERS:
        log_info(
            f"[Incoming Call] Rejected caller {from_number} "
            f"(normalized: {normalized_from_number or 'n/a'}) for CallSid {call_sid}"
        )
        denied = VoiceResponse()
        denied.say("Access denied.")
        denied.hangup()
        return Response(content=str(denied), media_type="application/xml")
    
    # Caller is allowlisted. Connect directly in inbound assistant mode.
    
    timezone = "America/Los_Angeles"
    
    # Get WebSocket URL - prioritize PUBLIC_URL environment variable
    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        host = public_url.replace("https://", "").replace("http://", "")
        protocol = "wss"
    else:
        host = request.headers.get("host", f"localhost:{PORT}")
        protocol = "wss" if ("trycloudflare.com" in host or "ngrok" in host or "loca.lt" in host) else "ws"
    
    # Build WebSocket URL (no query params - use customParameters instead)
    ws_url = f"{protocol}://{host}/media-stream"
    
    log_info(f"[Incoming Call] Accepted caller {from_number} (CallSid: {call_sid}). Assistant mode enabled.")
    
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=ws_url)
    # Use Twilio's customParameters (passed in WebSocket start event)
    stream.parameter(name="call_direction", value="inbound")
    stream.parameter(name="call_sid", value=call_sid)
    stream.parameter(name="timezone", value=timezone)
    response.append(connect)
    
    return Response(content=str(response), media_type="application/xml")


@app.get("/twiml")
@app.post("/twiml")
async def twiml(request: Request):
    """Generate TwiML to connect call to WebSocket (outbound calls).
    
    Mission is NOT passed here — it's stored server-side keyed by call SID.
    Twilio only handles audio routing, never sees mission content.
    """
    params = request.query_params
    timezone = params.get("timezone", "America/Los_Angeles")
    
    # Get WebSocket URL - use the public-facing host
    host = request.headers.get("host", f"localhost:{PORT}")
    protocol = "wss" if ("trycloudflare.com" in host or "ngrok" in host or "loca.lt" in host) else "ws"
    ws_url = f"{protocol}://{host}/media-stream"
    
    log_info(f"[TwiML] WebSocket URL: {ws_url} (timezone: {timezone})")
    
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=ws_url)
    # Pass only non-sensitive metadata via customParameters
    stream.parameter(name="call_direction", value="outbound")
    stream.parameter(name="timezone", value=timezone)
    response.append(connect)
    
    return Response(content=str(response), media_type="application/xml")


@app.post("/call-status")
async def call_status(request: Request):
    """Handle call status callbacks from Twilio"""
    form = await request.form()
    call_sid = form.get("CallSid")
    status = form.get("CallStatus")
    
    log_info(f"[Call Status] {call_sid}: {status}")
    
    if call_sid:
        if status in ("busy", "no-answer", "failed", "canceled"):
            track_call(call_sid, "failed", reason=status)
        elif status == "completed":
            # Only update if no mission_result was already recorded
            if call_sid in CALL_RESULTS and CALL_RESULTS[call_sid].get("status") != "completed":
                track_call(call_sid, "ended_without_result")
        else:
            track_call(call_sid, status)
    
    return {"status": "received"}


@app.get("/call/{call_sid}/result")
async def get_call_result(call_sid: str, _auth: str = Depends(verify_api_key)):
    """Get mission result for a call (polled by the initiating agent)"""
    if call_sid not in CALL_RESULTS:
        return {"status": "unknown", "call_sid": call_sid}
    return {**CALL_RESULTS[call_sid], "call_sid": call_sid}


@app.websocket("/test-ws")
async def test_websocket(websocket: WebSocket):
    """Test WebSocket handler - just echo"""
    log_info("[TEST WS] Connection attempt!")
    await websocket.accept()
    log_info("[TEST WS] Connection accepted!")
    async for text in websocket.iter_text():
        log_info(f"[TEST WS] Received: {text}")
        await websocket.send_text(f"Echo: {text}")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Handle Twilio Media Stream WebSocket"""
    log_info("[WebSocket] Connection attempt received")
    
    try:
        await websocket.accept()
        log_info("[WebSocket] Client connected - WebSocket accepted")
    except Exception as e:
        log_info(f"[WebSocket ERROR] Failed to accept connection: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Pre-load narrative context (same for all calls)
    narrative_context = await get_narrative_context()
    
    # Default instructions are neutral until call direction is known.
    base_instructions = "Awaiting call context."
    if narrative_context:
        final_instructions = f"{narrative_context}\n\n---\n\n{base_instructions}"
    else:
        final_instructions = base_instructions
    log_info("[WebSocket] Default instructions loaded (will update on start event)")
    
    # Flags for deferred setup
    needs_mission_lookup = True  # Will check CALL_MISSIONS on start event
    timezone_default = "America/Los_Angeles"
    
    # Conversation tracking
    conversation_transcript: List[Dict[str, Any]] = []
    call_start_time = datetime.now()
    
    # OpenAI WebSocket connection
    openai_ws = None
    stream_sid = None
    call_sid = None
    timezone = timezone_default  # Initialize with default, updated from Twilio start event
    current_call_direction = "outbound"
    inbound_auth_flow_active = False
    inbound_authenticated = True
    
    
    log_info(f"[WebSocket] Starting OpenAI connection with message: {final_instructions[:50]}...")
    log_info(f"[WebSocket] API Key present: {bool(OPENAI_API_KEY)}")
    
    try:
        log_info("[OpenAI] Creating aiohttp session...")
        async with aiohttp.ClientSession() as session:
            log_info("[OpenAI] Connecting to Realtime API...")
            async with session.ws_connect(
                f"wss://api.openai.com/v1/realtime?model=gpt-realtime&temperature=0.8",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "OpenAI-Beta": "realtime=v1"
                }
            ) as openai_ws:
                
                log_info("[OpenAI] ✓ Connected to Realtime API!")
                
                # Initialize session with transcription enabled
                await openai_ws.send_json({
                    "type": "session.update",
                    "session": {
                        "modalities": ["text", "audio"],
                        "instructions": final_instructions,
                        "voice": "alloy",
                        "input_audio_format": "g711_ulaw",
                        "output_audio_format": "g711_ulaw",
                        "input_audio_transcription": {
                            "model": "whisper-1"
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500
                        },
                        "tools": TOOLS,
                        "tool_choice": "auto",
                        "temperature": 0.8
                    }
                })
                
                # Handle bidirectional streaming
                async def forward_twilio_to_openai():
                    """Forward audio from Twilio to OpenAI"""
                    nonlocal stream_sid, call_sid, timezone, current_call_direction
                    nonlocal inbound_auth_flow_active, inbound_authenticated
                    try:
                        async for message in websocket.iter_text():
                            data = json.loads(message)
                            
                            if data["event"] == "start":
                                stream_sid = data["start"]["streamSid"]
                                call_sid = data["start"].get("callSid", stream_sid)
                                
                                # Parse customParameters (passed from TwiML)
                                custom_params = data["start"].get("customParameters", {})
                                call_direction = custom_params.get("call_direction", "outbound")
                                timezone = custom_params.get("timezone", timezone_default)
                                current_call_direction = call_direction
                                
                                log_info(f"[Twilio] Stream started: {stream_sid} (call: {call_sid}, direction: {call_direction})")
                                
                                if call_direction == "outbound" and needs_mission_lookup:
                                    inbound_auth_flow_active = False
                                    # Look up mission from server-side storage (never went through Twilio)
                                    mission_prompt = CALL_MISSIONS.pop(call_sid, None)
                                    if mission_prompt:
                                        log_info(f"[Mission] Found stored prompt for {call_sid} (len: {len(mission_prompt)})")
                                        if narrative_context:
                                            outbound_instructions = f"{narrative_context}\n\n---\n\n{mission_prompt}"
                                        else:
                                            outbound_instructions = mission_prompt
                                        
                                        await openai_ws.send_json({
                                            "type": "session.update",
                                            "session": {
                                                "instructions": outbound_instructions
                                            }
                                        })
                                        log_info("[Mission] ✓ Session updated with mission prompt")
                                    else:
                                        # Outbound calls are mission-only. Never fall back to a generic prompt.
                                        log_info(f"[Mission] ERROR: Missing mission prompt for outbound call {call_sid} — terminating call")
                                        if call_sid:
                                            track_call(call_sid, "failed", reason="missing_mission_prompt")
                                        await websocket.close()
                                        break
                                
                                elif call_direction == "inbound":
                                    # Caller number is already allowlisted in /incoming-call.
                                    # No second-factor challenge/troll mode for inbound calls.
                                    inbound_auth_flow_active = False
                                    inbound_authenticated = True
                                    
                                    log_info("[WebSocket] Inbound call detected - allowlisted caller, enabling assistant mode")
                                    inbound_instructions = (
                                        f"{INBOUND_PROMPT}\n\n"
                                        "Inbound caller already verified by allowed phone number."
                                    )
                                    if narrative_context:
                                        final_inbound = f"{narrative_context}\n\n---\n\n{inbound_instructions}"
                                    else:
                                        final_inbound = inbound_instructions
                                    
                                    await openai_ws.send_json({
                                        "type": "session.update",
                                        "session": {
                                            "instructions": final_inbound
                                        }
                                    })
                                    log_info("[WebSocket] ✓ Session updated with inbound assistant mode")
                                    
                                    # Inject initial greeting to make assistant speak first
                                    log_info("[OpenAI] Injecting initial greeting for inbound call")
                                    await openai_ws.send_json({
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "message",
                                            "role": "user",
                                            "content": [
                                                {
                                                    "type": "input_text",
                                                    "text": "[CALL CONNECTED - Speak your greeting now]"
                                                }
                                            ]
                                        }
                                    })
                                    await openai_ws.send_json({
                                        "type": "response.create"
                                    })
                                
                                # Log call start
                                conversation_transcript.append({
                                    "type": "call_started",
                                    "timestamp": datetime.now().isoformat(),
                                    "call_sid": call_sid,
                                    "stream_sid": stream_sid,
                                    "call_direction": call_direction
                                })
                            
                            elif data["event"] == "media":
                                # Forward audio to OpenAI
                                await openai_ws.send_json({
                                    "type": "input_audio_buffer.append",
                                    "audio": data["media"]["payload"]
                                })
                            
                            elif data["event"] == "stop":
                                log_info("[Twilio] Stream stopped")
                                
                                # Log call end and send transcript to backend
                                conversation_transcript.append({
                                    "type": "call_ended",
                                    "timestamp": datetime.now().isoformat(),
                                    "duration_seconds": (datetime.now() - call_start_time).total_seconds()
                                })
                                
                                # Update call tracking if no mission result yet
                                if call_sid and (call_sid not in CALL_RESULTS or CALL_RESULTS[call_sid].get("status") not in ("completed", "failed")):
                                    track_call(call_sid, "ended_without_result")
                                
                                # Send full transcript to backend
                                try:
                                    await send_transcript_to_jarvis(
                                        transcript={
                                            "call_sid": call_sid,
                                            "start_time": call_start_time.isoformat(),
                                            "end_time": datetime.now().isoformat(),
                                            "duration_seconds": (datetime.now() - call_start_time).total_seconds(),
                                            "events": conversation_transcript
                                        },
                                        call_sid=call_sid
                                    )
                                except Exception as e:
                                    log_info(f"[Error] Failed to send transcript to backend: {e}")
                                
                                break
                    except Exception as e:
                        log_info(f"[Error] Twilio->OpenAI: {e}")
                
                async def forward_openai_to_twilio():
                    """Forward responses from OpenAI to Twilio"""
                    nonlocal timezone, current_call_direction
                    nonlocal inbound_auth_flow_active, inbound_authenticated
                    try:
                        active_response_id = None
                        
                        async for msg in openai_ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                response = json.loads(msg.data)
                                
                                # Track active response for cancellation
                                if response["type"] == "response.created":
                                    active_response_id = response.get("response", {}).get("id")
                                    log_info(f"[Response] Started: {active_response_id}")
                                
                                elif response["type"] == "response.done":
                                    log_info(f"[Response] Completed: {active_response_id}")
                                    
                                    # Log assistant response to transcript
                                    output = response.get("response", {}).get("output", [])
                                    for item in output:
                                        if item.get("type") == "message":
                                            content = item.get("content", [])
                                            for c in content:
                                                if c.get("type") == "text":
                                                    conversation_transcript.append({
                                                        "type": "assistant_message",
                                                        "timestamp": datetime.now().isoformat(),
                                                        "text": c.get("text", "")
                                                    })
                                    
                                    active_response_id = None
                                
                                elif response["type"] == "response.audio.delta":
                                    # Forward audio back to Twilio
                                    await websocket.send_json({
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {
                                            "payload": response["delta"]
                                        }
                                    })
                                
                                elif response["type"] == "conversation.item.input_audio_transcription.completed":
                                    # Log user speech to transcript
                                    transcript_text = response.get("transcript", "")
                                    if transcript_text:
                                        conversation_transcript.append({
                                            "type": "user_message",
                                            "timestamp": datetime.now().isoformat(),
                                            "text": transcript_text
                                        })
                                        log_info(f"[User] {transcript_text}")

                                        # Inbound second-factor auth removed.
                                
                                elif response["type"] == "input_audio_buffer.speech_started":
                                    # User started speaking - cancel active response and clear buffer
                                    log_info("[VAD] User interrupted - canceling response and clearing buffer")
                                    
                                    # Cancel the active OpenAI response
                                    if active_response_id:
                                        await openai_ws.send_json({
                                            "type": "response.cancel",
                                            "response_id": active_response_id
                                        })
                                        active_response_id = None
                                    
                                    # Clear Twilio audio buffer
                                    await websocket.send_json({
                                        "event": "clear",
                                        "streamSid": stream_sid
                                    })
                                
                                elif response["type"] == "response.function_call_arguments.done":
                                    # Handle tool calls via backend
                                    # Await synchronously to ensure results flow back to the model before next turn
                                    try:
                                        # Use create_task for the tool call to keep the socket read loop moving,
                                        # preventing the connection from stalling while waiting for System 2.
                                        asyncio.create_task(handle_tool_call(
                                            response, 
                                            openai_ws, 
                                            websocket, 
                                            timezone,
                                            conversation_transcript,
                                            call_sid
                                        ))
                                    except Exception as e:
                                        log_info(f"[WebSocket ERROR] handle_tool_call dispatch exception: {e}")
                                
                                elif response["type"] == "error":
                                    log_info(f"[OpenAI Error] {response}")
                                    conversation_transcript.append({
                                        "type": "error",
                                        "timestamp": datetime.now().isoformat(),
                                        "error": response
                                    })
                    except Exception as e:
                        log_info(f"[Error] OpenAI->Twilio: {e}")
                
                # Run both directions concurrently
                await asyncio.gather(
                    forward_twilio_to_openai(),
                    forward_openai_to_twilio()
                )
    
    except Exception as e:
        log_info(f"[ERROR] WebSocket handler exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        log_info("[WebSocket] Connection closed")


async def handle_tool_call(
    response, 
    openai_ws, 
    twilio_ws, 
    timezone, 
    conversation_transcript: List[Dict[str, Any]],
    call_sid: str
):
    """Handle tool function calls by routing through backend"""
    call_id = response.get("call_id")
    name = response.get("name")
    arguments = json.loads(response.get("arguments", "{}"))
    
    log_info(f"[Tool Call] {name}({arguments})")
    
    # Log tool call to transcript
    conversation_transcript.append({
        "type": "tool_call",
        "timestamp": datetime.now().isoformat(),
        "tool": name,
        "arguments": arguments,
        "call_id": call_id
    })
    
    result = None
    
    # Special case: hang_up is handled locally
    if name == "hang_up":
        result = {"status": "hanging_up", "message": "Ending call"}
        
        # Track hang-up (only if no mission_result already recorded)
        if call_sid and (call_sid not in CALL_RESULTS or CALL_RESULTS[call_sid].get("status") != "completed"):
            track_call(call_sid, "ended_without_result", reason="agent_hung_up")
        
        # Send result to OpenAI
        await openai_ws.send_json({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result)
            }
        })
        
        # Log to transcript
        conversation_transcript.append({
            "type": "tool_result",
            "timestamp": datetime.now().isoformat(),
            "call_id": call_id,
            "result": result
        })
        
        # Close the call after a brief pause
        await asyncio.sleep(1)
        await twilio_ws.close()
        return
    
    # Special case: mission_result - report and optionally hang up
    if name == "mission_result":
        from jarvis_integration import report_mission_result
        
        success = arguments.get("success", False)
        outcome = arguments.get("outcome", "No outcome provided")
        data = arguments.get("data", {})
        next_steps = arguments.get("next_steps", "")
        
        log_info(f"[Mission Result] success={success}, outcome={outcome}")
        
        # Store result for polling agents
        if call_sid:
            track_call(call_sid, "completed", success=success, outcome=outcome, data=data, next_steps=next_steps)
        
        # Build full transcript for the report
        transcript_summary = []
        for event in conversation_transcript:
            if event.get("type") == "user_message":
                transcript_summary.append(f"Them: {event.get('text', '')}")
            elif event.get("type") == "assistant_message":
                transcript_summary.append(f"Agent: {event.get('text', '')}")
        
        # Report to backend
        try:
            report_result = await report_mission_result(
                call_sid=call_sid,
                success=success,
                outcome=outcome,
                data=data,
                next_steps=next_steps,
                transcript="\n".join(transcript_summary)
            )
            result = {
                "status": "reported",
                "message": "Mission result recorded",
                "report_id": report_result.get("report_id")
            }
        except Exception as e:
            log_info(f"[Mission Result ERROR] Failed to report: {e}")
            result = {
                "status": "reported_locally",
                "message": "Mission result recorded locally (backend unavailable)"
            }
        
        # Send result to OpenAI
        await openai_ws.send_json({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result)
            }
        })
        
        # Log to transcript
        conversation_transcript.append({
            "type": "mission_result",
            "timestamp": datetime.now().isoformat(),
            "call_id": call_id,
            "success": success,
            "outcome": outcome,
            "data": data,
            "next_steps": next_steps
        })
        
        # Trigger response so agent can wrap up
        await openai_ws.send_json({
            "type": "response.create"
        })
        return
    
    # Special case: get_time can be handled locally for speed
    elif name == "get_time":
        tz = pytz.timezone(arguments.get("timezone", timezone))
        current_time = datetime.now(tz).strftime("%I:%M %p %Z")
        result = {"time": current_time, "timezone": arguments.get("timezone", timezone)}
    
    # All other tools: route through backend
    else:
        # Map tools to the backend execution logic
        # We handle 'delegate', 'answer_user_query', and 'execute_system_action'
        effective_name = "ask_jarvis" if name in ["delegate", "answer_user_query", "execute_system_action"] else name
        
        # Normalize arguments
        normalized_args = arguments.copy()
        if "query" in arguments:
            normalized_args["task"] = arguments["query"]
        elif "action" in arguments:
            normalized_args["task"] = arguments["action"]
        
        try:
            session_context = f"Voice call {call_sid}: {name} requested"
            
            log_info(f"[Tool Exec] Calling execute_tool_via_jarvis for {effective_name}")
            
            # Await the backend result synchronously
            backend_result = await execute_tool_via_jarvis(
                tool_name=effective_name,
                arguments=normalized_args,
                call_id=call_id,
                session_context=session_context,
                call_sid=call_sid
            )
            
            log_info(f"[Tool Exec] Got result from backend: {backend_result}")
            
            if backend_result.get("success"):
                result = backend_result.get("result", {})
                log_info(f"[Tool Exec] Extracted result: {result}")
            else:
                result = {
                    "error": backend_result.get("error", "Unknown error"),
                    "status": "failed"
                }
                log_info(f"[Tool Exec] Tool failed: {result}")
        except Exception as e:
            log_info(f"[Error] Backend tool execution failed: {e}")
            import traceback
            traceback.print_exc()
            result = {
                "error": str(e),
                "status": "failed"
            }
    
    # Send result back to OpenAI
    if result:
        log_info(f"[Tool Output] Sending result to OpenAI: {json.dumps(result)[:200]}")
        await openai_ws.send_json({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result)
            }
        })
        log_info(f"[Tool Output] Sent function_call_output to OpenAI")
        
        # Log result to transcript
        conversation_transcript.append({
            "type": "tool_result",
            "timestamp": datetime.now().isoformat(),
            "call_id": call_id,
            "result": result
        })

        # Explicitly trigger a response generation after tool output
        log_info(f"[Tool Output] Triggering response.create")
        await openai_ws.send_json({
            "type": "response.create"
        })
        log_info(f"[Tool Output] Response generation triggered")
    else:
        log_info(f"[Tool Output ERROR] No result to send back!")



if __name__ == "__main__":
    import uvicorn
    log_info(f"🎙️  Starting Twilio Voice Server on port {PORT}")
    log_info(f"📞 Twilio Number: {TWILIO_NUMBER}")
    log_info(f"🤖 OpenAI API Key: {'✓ Configured' if OPENAI_API_KEY else '✗ Missing'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
