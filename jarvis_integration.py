"""
Jarvis Integration for Voice Server
Connects OpenAI Realtime voice calls to Jarvis (Clawdbot main session)

Tool execution:
- Simple tools (time, file ops, shell) execute directly
- Brain queries (ask_jarvis) route to Clawdbot Gateway HTTP API
- Transcripts logged to memory files so Jarvis remembers calls
- Narrative bridge awakens System 2 with workspace context
"""

import asyncio
import json
import os
import aiohttp
from typing import Dict, Any, Optional
from datetime import datetime

# Gateway API config
GATEWAY_URL = "http://127.0.0.1:18789/v1/chat/completions"
GATEWAY_TOKEN = "7e9917e5896de5d66fbdf8d418dd4a61b76cc8c4cf593dfd"
VOICE_API_KEY = "7e9917e5896de5d66fbdf8d418dd4a61b76cc8c4cf593dfd" # Shared secret for internal calls

# Narrative bridge
NARRATIVE_SCRIPT = os.path.expanduser("~/clawd/bin/narrative")


async def get_narrative_context() -> str:
    """
    Load workspace narrative context from bin/narrative script.
    This awakens System 2 with current tools, session state, and active plans.
    """
    try:
        if not os.path.exists(NARRATIVE_SCRIPT):
            print("[Narrative] Script not found, skipping context load")
            return ""
        
        result = await asyncio.create_subprocess_exec(
            NARRATIVE_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=10)
        
        if result.returncode == 0:
            narrative = stdout.decode().strip()
            print(f"[Narrative] Loaded {len(narrative)} bytes of context")
            return narrative
        else:
            print(f"[Narrative ERROR] Script failed: {stderr.decode()}")
            return ""
            
    except asyncio.TimeoutError:
        print("[Narrative ERROR] Script timed out")
        return ""
    except Exception as e:
        print(f"[Narrative ERROR] {e}")
        return ""


async def ask_brain(question: str, timeout: int = 45) -> Dict[str, Any]:
    """
    Ask System 2 (Clawdbot) a question via HTTP API.
    Use a stable session ID to maintain context and prevent zombie sessions.
    """
    sid = "agent:main:main"
    
    # Wrap question with voice system context
    # NOTE: Keep this natural - brackets/caps trigger paranoia in backend
    wrapped_question = f"""Voice call in progress with Ramon.

Question from Ramon: {question}

(System 1 is handling the conversation - you're System 2 providing the answer. Respond directly to his question.)"""
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GATEWAY_URL,
                headers={
                    "Authorization": f"Bearer {GATEWAY_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openclaw:main",
                    "messages": [{"role": "user", "content": wrapped_question}],
                    "user": sid
                },
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    answer = data["choices"][0]["message"]["content"]
                    print(f"[Brain] Success: {answer[:100]}...")
                    return {"success": True, "result": {"answer": answer.strip()}}
                else:
                    text = await response.text()
                    print(f"[Brain ERROR] HTTP {response.status}: {text}")
                    return {"success": False, "error": f"Gateway error: {response.status}"}
    except asyncio.TimeoutError:
        return {"success": False, "error": "Brain query timed out"}
    except Exception as e:
        print(f"[Brain ERROR] {e}")
        return {"success": False, "error": str(e)}


async def execute_tool_via_jarvis(
    tool_name: str,
    arguments: Dict[str, Any],
    call_id: str,
    session_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a tool by routing to the appropriate handler.
    
    Args:
        tool_name: Name of the tool
        arguments: Tool arguments
        call_id: Unique call ID
        session_context: Optional context
        
    Returns:
        Tool result dict with success/error status
    """
    
    print(f"[Tool] {tool_name}({json.dumps(arguments)})")
    
    try:
        if tool_name == "web_search":
            query = arguments.get("query", "")
            count = arguments.get("count", 3)
            
            command = f"openclaw web-search --query {json.dumps(query)} --count {count} --json"
            result = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=20)
            
            if result.returncode == 0:
                return {"success": True, "result": json.loads(stdout.decode())}
            else:
                return {"success": False, "error": stderr.decode().strip() or "Search failed"}
            
        elif tool_name == "ask_jarvis":
            question = arguments.get("task") or arguments.get("question", "")
            
            # Fast path for time requests
            if any(kw in question.lower() for kw in ["time", "what time", "current time"]):
                result = await asyncio.create_subprocess_shell(
                    "date",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(result.communicate(), timeout=5)
                return {"success": True, "result": {"answer": f"The current time is {stdout.decode().strip()}."}}
            
            # Route to brain (System 2)
            return await ask_brain(question)

        elif tool_name == "execute_command":
            command = arguments.get("command", "")
            
            result = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.expanduser("~")
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=10)
            
            return {
                "success": result.returncode == 0,
                "result": {
                    "stdout": stdout.decode().strip(),
                    "stderr": stderr.decode().strip(),
                    "returncode": result.returncode,
                    "command": command
                }
            }
            
        elif tool_name == "read_file":
            path = os.path.expanduser(arguments.get("path", ""))
            
            with open(path, 'r') as f:
                content = f.read()
                
            if len(content) > 1000:
                content = content[:1000] + f"\n... (truncated, {len(content)} bytes total)"
                
            return {"success": True, "result": {"path": path, "content": content, "size": len(content)}}
            
        elif tool_name == "write_file":
            path = os.path.expanduser(arguments.get("path", ""))
            content = arguments.get("content", "")
            
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write(content)
                
            return {"success": True, "result": {"path": path, "bytes_written": len(content)}}
            
        elif tool_name == "send_message":
            to = arguments.get("to", "")
            message = arguments.get("message", "")
            
            result = await asyncio.create_subprocess_exec(
                "/opt/homebrew/bin/imsg", "send", to, message,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=5)
            
            return {
                "success": result.returncode == 0,
                "result": {
                    "to": to,
                    "message": message,
                    "status": "sent" if result.returncode == 0 else "failed",
                    "output": stdout.decode().strip() or stderr.decode().strip()
                }
            }
                
        elif tool_name == "get_calendar":
            timeframe = arguments.get("timeframe", "today")
            
            command = f"icalBuddy -n -nc events{timeframe.capitalize()}"
            result = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(result.communicate(), timeout=10)
            
            return {"success": True, "result": {"timeframe": timeframe, "events": stdout.decode().strip() or "No events found."}}
            
        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
            
    except asyncio.TimeoutError:
        return {"success": False, "error": f"{tool_name} timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_transcript_to_jarvis(transcript: Dict[str, Any], call_sid: str):
    """
    Write conversation transcript to memory files after call ends.
    """
    
    call_summary = f"""## 📞 Voice Call - {transcript.get('start_time', 'unknown')}

**Call ID:** {call_sid}  
**Duration:** {transcript.get('duration_seconds', 0):.0f} seconds  

### Conversation:

"""
    
    events = transcript.get('events', [])
    user_messages = []
    assistant_messages = []
    tool_calls = []
    
    for event in events:
        event_type = event.get('type', '')
        
        if event_type == 'user_message':
            text = event.get('text', '').strip()
            if text:
                user_messages.append(text)
                call_summary += f"**Ramon:** {text}\n\n"
            
        elif event_type == 'assistant_message':
            text = event.get('text', '').strip()
            if text:
                assistant_messages.append(text)
                call_summary += f"**Jarvis:** {text}\n\n"
            
        elif event_type == 'tool_call':
            tool = event.get('tool', '')
            args = event.get('arguments', {})
            tool_calls.append(f"{tool}({args})")
            call_summary += f"*🔧 Tool: {tool}* `{json.dumps(args)}`\n\n"
            
        elif event_type == 'tool_result':
            result = event.get('result', {})
            if result.get('success'):
                call_summary += f"*✅ Result: Success*\n\n"
            else:
                call_summary += f"*❌ Result: {result.get('error', 'Failed')}*\n\n"
    
    if user_messages or assistant_messages:
        call_summary += f"\n**Summary:** {len(user_messages)} user messages, {len(assistant_messages)} assistant responses, {len(tool_calls)} tool calls\n"
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        memory_dir = os.path.expanduser("~/clawd/memory")
        memory_file = os.path.join(memory_dir, f"{today}.md")
        
        os.makedirs(memory_dir, exist_ok=True)
        
        file_exists = os.path.exists(memory_file)
        
        with open(memory_file, 'a') as f:
            if not file_exists:
                f.write(f"# Memory - {today}\n\n")
            f.write(f"{call_summary}\n---\n\n")
        
        print(f"[Transcript] Written to {memory_file}")
        
        voice_log = os.path.join(memory_dir, "voice-calls.md")
        with open(voice_log, 'a') as f:
            f.write(f"{call_summary}\n---\n\n")
        
    except Exception as e:
        print(f"[Transcript ERROR] {e}")
