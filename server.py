#!/usr/bin/env python3
"""
Twilio Voice Server with OpenAI Realtime API
Handles outbound calls with AI agent capabilities

⚠️  STICKY NOTE FOR LLM:
    Prompts are now loaded from prompts/*.txt files at startup.
    If you modify prompt loading or add new prompts:
    - Make sure files exist before server starts
    - Test that passphrase templating works ({PASSPHRASE} → actual value)
    - Log prompt load success to stdout for debugging
    Run: python3 -c "from server import *" to test imports
"""

import os
import sys
import json
import base64
import asyncio
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
SECURITY_CHALLENGE = os.getenv("SECURITY_CHALLENGE")  # Required: security passphrase from config
if not SECURITY_CHALLENGE:
    raise ValueError("SECURITY_CHALLENGE environment variable is required")

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
    """Load system prompts from files. Falls back to defaults if files not found."""
    prompts_dir = os.path.join(os.path.dirname(__file__), 'prompts')

    # Load outbound prompt (used as default system message)
    outbound_prompt = "You are an AI assistant and digital butler."
    outbound_path = os.path.join(prompts_dir, 'jarvis-outbound.txt')
    if os.path.exists(outbound_path):
        try:
            with open(outbound_path, 'r') as f:
                outbound_prompt = f.read().strip()
            log_info(f"[Prompts] Loaded outbound prompt from {outbound_path}")
        except Exception as e:
            log_info(f"[Prompts] Warning: Could not load outbound prompt: {e}")

    # Load base prompt (used for inbound calls)
    base_prompt = ""
    base_path = os.path.join(prompts_dir, 'jarvis-base.txt')
    if os.path.exists(base_path):
        try:
            with open(base_path, 'r') as f:
                base_prompt = f.read().strip()
            log_info(f"[Prompts] Loaded base prompt from {base_path}")
        except Exception as e:
            log_info(f"[Prompts] Warning: Could not load base prompt: {e}")

    return outbound_prompt, base_prompt

# Initialize prompts at startup
JARVIS_SYSTEM_MESSAGE, BASE_INBOUND_PROMPT = load_prompts()

# Inbound call challenge (function to template in configurable passphrase)
def get_inbound_challenge(passphrase: str = SECURITY_CHALLENGE) -> str:
    """Inject the security passphrase into the base inbound prompt."""
    # Replace the placeholder in the prompt with the actual passphrase
    prompt = BASE_INBOUND_PROMPT.replace('{PASSPHRASE}', passphrase)
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
    }
]


# (Removed CALL_INSTRUCTIONS - no longer using separate bouncer)

@app.get("/")
async def root():
    return {"status": "Twilio Voice Server", "version": "1.0"}


@app.post("/call/id/{contact_id}")
async def initiate_call_by_id(contact_id: str, request: Request, _auth: str = Depends(verify_api_key)):
    """Initiate outbound call to a contact by ID"""
    data = await request.json()
    
    if contact_id not in CONTACTS:
        return {"error": f"Contact ID '{contact_id}' not found"}, 404
    
    to_number = CONTACTS[contact_id]
    message = data.get("message", JARVIS_SYSTEM_MESSAGE)
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
            url=f"{base_url}/twiml?message={base64.urlsafe_b64encode(message.encode()).decode()}&timezone={agent_timezone}",
            status_callback=f"{base_url}/call-status",
            status_callback_event=["initiated", "ringing", "answered", "completed"]
        )
        
        return {
            "success": True,
            "call_sid": call.sid,
            "to": to_number,
            "from": TWILIO_NUMBER,
            "status": call.status
        }
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/call/number/{phone_number}")
async def initiate_call_by_number(phone_number: str, request: Request, _auth: str = Depends(verify_api_key)):
    """Initiate outbound call to a phone number"""
    data = await request.json()
    
    # Ensure + prefix for E.164 format
    if not phone_number.startswith("+"):
        phone_number = f"+{phone_number}"
    
    message = data.get("message", JARVIS_SYSTEM_MESSAGE)
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
            url=f"{base_url}/twiml?message={base64.urlsafe_b64encode(message.encode()).decode()}&timezone={agent_timezone}",
            status_callback=f"{base_url}/call-status",
            status_callback_event=["initiated", "ringing", "answered", "completed"]
        )
        
        return {
            "success": True,
            "call_sid": call.sid,
            "to": phone_number,
            "from": TWILIO_NUMBER,
            "status": call.status
        }
    except Exception as e:
        return {"error": str(e)}, 500


@app.get("/incoming-call")
@app.post("/incoming-call")
async def incoming_call(request: Request):
    """Handle incoming calls - TwiML to connect to media stream with challenge"""
    form_data = await request.form()
    from_number = form_data.get("From", "Unknown")
    call_sid = form_data.get("CallSid", "unknown")
    
    # For incoming calls, The assistant handles the challenge directly
    # No separate bouncer - just flag it as inbound
    
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
    
    log_info(f"[Incoming Call] From {from_number} (CallSid: {call_sid}). Assistant will challenge.")
    
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
    """Generate TwiML to connect call to WebSocket (outbound calls)"""
    params = request.query_params
    message_encoded = params.get("message", "")
    timezone = params.get("timezone", "America/Los_Angeles")
    
    # Decode message to log/inspect
    try:
        message = base64.urlsafe_b64decode(message_encoded.encode()).decode()
    except:
        message = message_encoded
    
    # Get WebSocket URL - use the public-facing host
    host = request.headers.get("host", f"localhost:{PORT}")
    
    # Always use wss for cloudflare/ngrok/localtunnel tunnels
    protocol = "wss" if ("trycloudflare.com" in host or "ngrok" in host or "loca.lt" in host) else "ws"
    ws_url = f"{protocol}://{host}/media-stream?message={message_encoded}&timezone={timezone}&call_direction=outbound"
    log_info(f"[TwiML] Generated WebSocket URL: {ws_url}")
    
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=ws_url)
    response.append(connect)
    
    return Response(content=str(response), media_type="application/xml")


@app.post("/call-status")
async def call_status(request: Request):
    """Handle call status callbacks"""
    form = await request.form()
    call_sid = form.get("CallSid")
    status = form.get("CallStatus")
    
    log_info(f"[Call Status] {call_sid}: {status}")
    
    return {"status": "received"}


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
    
    # Get parameters
    params = dict(websocket.query_params)
    log_info(f"[WebSocket] Query params keys: {list(params.keys())}")
    
    call_sid_param = params.get("call_sid")
    message_override = params.get("message", "")
    timezone_default = params.get("timezone", "America/Los_Angeles")
    
    # Decode message override if present (outbound calls)
    decoded_override = ""
    if message_override:
        try:
            # Add padding if missing
            padding = 4 - (len(message_override) % 4)
            if padding < 4:
                message_override += "=" * padding
            decoded_override = base64.urlsafe_b64decode(message_override.encode()).decode()
            log_info(f"[WebSocket] Decoded message override (len: {len(decoded_override)})")
        except Exception as e:
            log_info(f"[WebSocket ERROR] Failed to decode message override: {e}")
            decoded_override = ""
    
    # Pre-load narrative context (same for all calls)
    narrative_context = await get_narrative_context()
    
    # Determine initial instructions
    # Note: For inbound calls, we'll update instructions after parsing customParameters from Twilio start event
    if decoded_override:
        # Outbound call with custom instructions
        base_instructions = decoded_override
        if narrative_context:
            final_instructions = f"{narrative_context}\n\n---\n\n{base_instructions}"
        else:
            final_instructions = base_instructions
        log_info("[WebSocket] Using custom outbound instructions")
        needs_inbound_update = False
    else:
        # Default to standard assistant - will be updated if inbound
        base_instructions = JARVIS_SYSTEM_MESSAGE
        if narrative_context:
            final_instructions = f"{narrative_context}\n\n---\n\n{base_instructions}"
        else:
            final_instructions = base_instructions
        log_info("[WebSocket] Using default assistant (will update if inbound)")
        needs_inbound_update = True  # Flag to check customParameters
    
    # Conversation tracking
    conversation_transcript: List[Dict[str, Any]] = []
    call_start_time = datetime.now()
    
    # OpenAI WebSocket connection
    openai_ws = None
    stream_sid = None
    call_sid = None
    timezone = timezone_default  # Initialize with default, updated from Twilio start event
    
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
                    nonlocal stream_sid, call_sid, timezone
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
                                
                                log_info(f"[Twilio] Stream started: {stream_sid} (call: {call_sid}, direction: {call_direction})")
                                
                                # Update session if inbound call detected
                                if needs_inbound_update and call_direction == "inbound":
                                    log_info("[WebSocket] Inbound call detected - updating session with challenge")
                                    inbound_instructions = JARVIS_SYSTEM_MESSAGE + get_inbound_challenge()
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
                                    log_info("[WebSocket] ✓ Session updated with inbound challenge")
                                    
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
                    nonlocal timezone
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
                session_context=session_context
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
