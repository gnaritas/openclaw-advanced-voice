#!/usr/bin/env python3
"""
Advanced Voice Watchdog - Monitors tunnel and voice server

Based on the original voice-server watchdog.py but adapted for the
OpenClaw advanced-voice plugin architecture.

Responsibilities:
1. Start/restart cloudflared tunnel on port 8001
2. Parse the dynamic tunnel URL from output
3. Update Twilio webhook configuration
4. Start/restart voice server with PUBLIC_URL
5. Monitor public endpoint for end-to-end health
"""

import os
import re
import sys
import json
import time
import signal
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional

# Configuration
LOCAL_PORT = 8001
LOCAL_URL = f"http://localhost:{LOCAL_PORT}"
PLUGIN_DIR = Path(__file__).parent
TUNNEL_LOG = PLUGIN_DIR / "tunnel.log"
SERVER_LOG = PLUGIN_DIR / "server.log"
WATCHDOG_LOG = PLUGIN_DIR / "watchdog.log"
HEALTH_CHECK_INTERVAL = 30  # seconds
TUNNEL_STARTUP_WAIT = 10
MAX_CONSECUTIVE_FAILURES = 3


def _load_openclaw_config():
    """Load advanced-voice config from OpenClaw's openclaw.json"""
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path) as f:
            data = json.load(f)
        return data.get("plugins", {}).get("entries", {}).get("advanced-voice", {}).get("config", {})
    except Exception:
        return {}


_oc_cfg = _load_openclaw_config()
_twilio_cfg = _oc_cfg.get("twilio", {})
_openai_cfg = _oc_cfg.get("openai", {})
_security_cfg = _oc_cfg.get("security", {})

# Twilio config (env vars first, then OpenClaw config fallback)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID") or _twilio_cfg.get("accountSid")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN") or _twilio_cfg.get("authToken")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER") or _twilio_cfg.get("fromNumber")

# Server environment (pass through from parent process env, with OpenClaw config fallback)
SERVER_ENV = {
    "PORT": os.getenv("PORT", "8001"),
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID or "",
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN or "",
    "TWILIO_NUMBER": TWILIO_NUMBER or "",
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY") or _openai_cfg.get("apiKey", ""),
    "VOICE_API_KEY": os.getenv("VOICE_API_KEY") or _security_cfg.get("apiKey", ""),
    "GATEWAY_URL": os.getenv("GATEWAY_URL", "http://127.0.0.1:18789/v1/chat/completions"),
    "GATEWAY_TOKEN": os.getenv("GATEWAY_TOKEN", ""),
    "SECURITY_CHALLENGE": os.getenv("SECURITY_CHALLENGE") or _security_cfg.get("challenge", ""),
}

# Process handles
tunnel_process = None
server_process = None
current_public_url = None


def log(msg: str):
    """Log with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{timestamp}] {msg}\n"
    print(message, end='')
    sys.stdout.flush()
    
    # Also log to file
    with open(WATCHDOG_LOG, 'a') as f:
        f.write(message)


def parse_tunnel_url(log_path: Path, timeout: int = TUNNEL_STARTUP_WAIT) -> Optional[str]:
    """Parse cloudflare tunnel URL from log output"""
    start = time.time()
    url_pattern = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
    
    while time.time() - start < timeout:
        if log_path.exists():
            content = log_path.read_text()
            match = url_pattern.search(content)
            if match:
                return match.group(0)
        time.sleep(1)
    
    return None


def start_tunnel() -> Optional[str]:
    """Start cloudflared tunnel and return the public URL"""
    global tunnel_process
    
    # Kill any existing tunnel
    stop_tunnel()
    
    # Clear old log
    if TUNNEL_LOG.exists():
        TUNNEL_LOG.unlink()
    
    log("Starting cloudflared tunnel...")
    
    # Start tunnel with output to log file
    with open(TUNNEL_LOG, 'w') as log_file:
        tunnel_process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", LOCAL_URL],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
    
    log(f"Tunnel process started (PID: {tunnel_process.pid})")
    
    # Wait for and parse the URL
    url = parse_tunnel_url(TUNNEL_LOG, timeout=TUNNEL_STARTUP_WAIT)
    
    if url:
        log(f"Tunnel URL: {url}")
        return url
    else:
        log("ERROR: Failed to get tunnel URL from cloudflared output")
        return None


def stop_tunnel():
    """Stop the cloudflared tunnel"""
    global tunnel_process
    
    if tunnel_process:
        log(f"Stopping tunnel (PID: {tunnel_process.pid})")
        try:
            tunnel_process.terminate()
            tunnel_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel_process.kill()
        tunnel_process = None
    
    # Kill any orphaned cloudflared processes
    subprocess.run(["pkill", "-f", "cloudflared tunnel"], capture_output=True)


def start_server(public_url: str):
    """Start the voice server with the correct PUBLIC_URL"""
    global server_process
    
    # Kill any existing server
    stop_server()
    
    log(f"Starting voice server with PUBLIC_URL={public_url}")
    
    env = os.environ.copy()
    env.update(SERVER_ENV)
    env["PUBLIC_URL"] = public_url
    
    with open(SERVER_LOG, 'w') as log_file:
        server_process = subprocess.Popen(
            [sys.executable, "-u", "server.py"],
            cwd=PLUGIN_DIR,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
    
    log(f"Server process started (PID: {server_process.pid})")
    
    # Wait for server to be ready
    for _ in range(10):
        try:
            resp = requests.get(LOCAL_URL, timeout=2)
            if resp.status_code == 200:
                log("Server is ready")
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    
    log("WARNING: Server may not be ready")
    return False


def stop_server():
    """Stop the voice server"""
    global server_process
    
    if server_process:
        log(f"Stopping server (PID: {server_process.pid})")
        try:
            server_process.terminate()
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
        server_process = None
    
    # Kill any orphaned server processes
    subprocess.run(["pkill", "-f", "python3.*server.py"], capture_output=True)


def update_twilio_webhook(public_url: str) -> bool:
    """Update Twilio phone number webhook"""
    try:
        from twilio.rest import Client
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        numbers = client.incoming_phone_numbers.list(phone_number=TWILIO_NUMBER)
        
        if not numbers:
            log(f"ERROR: Phone number {TWILIO_NUMBER} not found")
            return False
        
        number = numbers[0]
        webhook_url = f"{public_url}/incoming-call"
        
        number.update(
            voice_url=webhook_url,
            voice_method="POST"
        )
        
        log(f"Updated Twilio webhook: {webhook_url}")
        return True
        
    except Exception as e:
        log(f"ERROR updating Twilio webhook: {e}")
        return False


def check_public_health(public_url: str) -> bool:
    """Check if the public URL is healthy (end-to-end)"""
    try:
        resp = requests.get(public_url, timeout=10)
        return resp.status_code == 200
    except requests.RequestException as e:
        log(f"Health check failed: {e}")
        return False


def check_local_health() -> bool:
    """Check if the local server is responding"""
    try:
        resp = requests.get(LOCAL_URL, timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def full_restart() -> bool:
    """Full restart: tunnel + server + Twilio config"""
    global current_public_url
    
    log("=== FULL RESTART ===")
    
    # Start tunnel and get URL
    public_url = start_tunnel()
    if not public_url:
        log("Failed to start tunnel")
        return False
    
    current_public_url = public_url
    
    # Start server with the URL
    if not start_server(public_url):
        log("Server may have issues")
    
    # Update Twilio webhook
    update_twilio_webhook(public_url)
    
    # Verify public health
    time.sleep(2)
    if check_public_health(public_url):
        log("=== SYSTEM HEALTHY ===")
        return True
    else:
        log("WARNING: Public health check failed after restart")
        return False


def signal_handler(signum, frame):
    """Handle shutdown gracefully"""
    log("Received shutdown signal")
    stop_server()
    stop_tunnel()
    sys.exit(0)


def main():
    global current_public_url
    
    log("=" * 60)
    log("Advanced Voice Watchdog Starting")
    log("=" * 60)
    log(f"Local URL: {LOCAL_URL}")
    log(f"Health check interval: {HEALTH_CHECK_INTERVAL}s")
    log(f"Twilio number: {TWILIO_NUMBER}")
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Initial startup
    if not full_restart():
        log("Initial startup failed, will retry...")
    
    consecutive_failures = 0
    
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        
        # Check public URL health
        if current_public_url and check_public_health(current_public_url):
            consecutive_failures = 0
            # Log health every ~5 minutes
            if int(time.time()) % 300 < HEALTH_CHECK_INTERVAL:
                log(f"Health OK: {current_public_url}")
        else:
            consecutive_failures += 1
            log(f"Public health check FAILED ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})")
            
            # Check if local server is still up
            if not check_local_health():
                log("Local server also down - full restart needed")
                full_restart()
                consecutive_failures = 0
            elif consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log("Max failures reached - restarting tunnel")
                # Just restart the tunnel, server is fine
                public_url = start_tunnel()
                if public_url:
                    current_public_url = public_url
                    update_twilio_webhook(public_url)
                    # Restart server with new PUBLIC_URL
                    start_server(public_url)
                consecutive_failures = 0


if __name__ == "__main__":
    main()
