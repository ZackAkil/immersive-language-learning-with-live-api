# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import asyncio
import json
import os
import logging
import time
import uuid
import requests
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from server.recaptcha_validator import RecaptchaValidator
from server.gemini_live import GeminiLive
from server.fingerprint import generate_fingerprint
from server.simple_tracker import simpletrack
from server.config_utils import get_project_id


# Rate Limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import redis

# Load environment variables
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Configuration
PROJECT_ID = get_project_id()
LOCATION = os.getenv("LOCATION", "us-central1")
MODEL = os.getenv("MODEL", "gemini-live-2.5-flash-native-audio")
# Use a very long timeout for dev
SESSION_TIME_LIMIT = int(os.getenv("SESSION_TIME_LIMIT", "180"))
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY")
RECAPTCHA_SCORE_THRESHOLD = float(os.getenv("RECAPTCHA_SCORE_THRESHOLD", "0.5"))
REDIS_URL = os.getenv("REDIS_URL")
GLOBAL_RATE_LIMIT = os.getenv("GLOBAL_RATE_LIMIT", "1000 per hour")
PER_USER_RATE_LIMIT = os.getenv("PER_USER_RATE_LIMIT", "2 per minute")
DEV_MODE = os.getenv("DEV_MODE", "true") == "true"

# Initialize FastAPI
app = FastAPI()

# Initialize Recaptcha Validator
recaptcha_validator = RecaptchaValidator(
    project_id=PROJECT_ID,
    recaptcha_key=RECAPTCHA_SITE_KEY or "",
    score_threshold=RECAPTCHA_SCORE_THRESHOLD
)

def get_fingerprint_key(request: Request):
    return generate_fingerprint(request)

def get_global_key(request: Request):
    return "global"

# Initialize Rate Limiter
if DEV_MODE:
    logger.info("🔧 DEV_MODE enabled: Rate limiting disabled (using memory storage)")
    limiter = Limiter(key_func=get_global_key) # Defaults to memory
elif not REDIS_URL:
    logger.warning("⚠️ REDIS_URL not set: Using memory storage for rate limiting (not suitable for multi-instance)")
    limiter = Limiter(key_func=get_fingerprint_key)
else:
    limiter = Limiter(key_func=get_fingerprint_key, storage_uri=REDIS_URL)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.on_event("startup")
async def startup_event():
    """Test Redis connection on startup."""
    if REDIS_URL and not DEV_MODE:
        try:
            logger.info(f"Testing Redis connection to: {REDIS_URL.split('@')[-1] if '@' in REDIS_URL else REDIS_URL}")
            
            r = redis.from_url(REDIS_URL)
            r.ping()
            logger.info("✅ Redis connection successful")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            logger.error("Ensure Cloud Run is configured with a VPC Connector if using a private IP.")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
# app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Mount assets and other static directories from dist
if os.path.exists("dist/assets"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")
if os.path.exists("dist/audio-processors"):
    app.mount("/audio-processors", StaticFiles(directory="dist/audio-processors"), name="audio-processors")
# In-memory storage for valid session tokens (Token -> Timestamp)
valid_tokens: Dict[str, float] = {}
TOKEN_EXPIRY_SECONDS = 30

def cleanup_tokens():
    """Remove expired tokens."""
    current_time = time.time()
    expired = [token for token, ts in valid_tokens.items() if current_time - ts > TOKEN_EXPIRY_SECONDS]
    for token in expired:
        del valid_tokens[token]

@app.get("/api/status")
async def get_status():
    """Returns the current configuration mode (Simple vs Production)."""
    missing = []
    if not RECAPTCHA_SITE_KEY:
        missing.append("recaptcha")
    if not REDIS_URL:
        missing.append("redis")
    
    mode = "simple" if missing else "production"
    
    return {
        "mode": mode,
        "missing": missing
    }

@app.get("/{full_path:path}")
@simpletrack("page_view")
async def serve_spa(full_path: str):
    # Serve file from dist if it exists
    file_path = f"dist/{full_path}"
    if full_path and os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Fallback to index.html for SPA routing
    return FileResponse("dist/index.html")

@app.post("/api/auth")
@simpletrack("session_start")
@limiter.limit(GLOBAL_RATE_LIMIT, key_func=get_global_key)
@limiter.limit(PER_USER_RATE_LIMIT, key_func=get_fingerprint_key)
async def authenticate(request: Request):
    """
    Validates ReCAPTCHA and issues a temporary session token for WebSocket connection.
    """
    try:
        data = await request.json()
        recaptcha_token = data.get("recaptcha_token")
        
        # Check if ReCAPTCHA is configured
        if not RECAPTCHA_SITE_KEY:
             logger.warning("⚠️ RECAPTCHA_SITE_KEY not set: Skipping validation (Simple Mode)")
             # Proceed without validation
        else:
            if not recaptcha_token:
                raise HTTPException(status_code=400, detail="Missing ReCAPTCHA token")

            if DEV_MODE:
                logger.info("🔧 DEV_MODE enabled: Skipping ReCAPTCHA validation")
                validation_result = {'valid': True, 'passes_threshold': True}
            else:
                validation_result = recaptcha_validator.validate_token(
                    token=recaptcha_token,
                    recaptcha_action="LOGIN"
                )
            
            if not validation_result['valid']:
                logger.warning(f"ReCAPTCHA failed: {validation_result.get('error')}")
                raise HTTPException(status_code=403, detail="ReCAPTCHA validation failed")
                
            if not validation_result['passes_threshold']:
                logger.warning(f"ReCAPTCHA score too low: {validation_result.get('score')}")
                raise HTTPException(status_code=403, detail="ReCAPTCHA score too low")

        session_token = str(uuid.uuid4())
        cleanup_tokens()
        valid_tokens[session_token] = time.time()
        
        return {"session_token": session_token, "session_time_limit": SESSION_TIME_LIMIT}
        
    except Exception as e:
        logger.error(f"Auth error: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Internal server error")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """
    WebSocket endpoint for Gemini Live.
    Requires a valid session token generated via /api/auth.
    """
    await websocket.accept()
    
    # Validate Token
    if not token or token not in valid_tokens:
        logger.warning("Invalid or missing session token")
        await websocket.close(code=4003, reason="Unauthorized")
        return
        
    # Remove token (one-time use)
    del valid_tokens[token]
    
    logger.info("WebSocket connection accepted and authenticated")

    # Wait for initial setup message
    setup_config = None
    try:
        # We expect the first message to be the setup JSON
        message = await websocket.receive_text()
        initial_data = json.loads(message)
        if "setup" in initial_data:
            setup_config = initial_data["setup"]
            logger.info("Received setup configuration from client")
    except Exception as e:
        logger.warning(f"Error receiving setup config: {e}")

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()

    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        # The event queue handles the JSON message, but we might want to do something else here
        pass

    gemini_client = GeminiLive(
        project_id=PROJECT_ID,
        location=LOCATION,
        model=MODEL,
        input_sample_rate=16000
    )

    async def receive_from_client():
        try:
            while True:
                message = await websocket.receive()
                
                if "bytes" in message and message["bytes"]:
                    await audio_input_queue.put(message["bytes"])
                elif "text" in message and message["text"]:
                    text = message["text"]
                    try:
                        payload = json.loads(text)
                        if isinstance(payload, dict) and payload.get("type") == "image":
                            # Handle base64 image
                            image_data = base64.b64decode(payload["data"])
                            await video_input_queue.put(image_data)
                            continue
                        elif isinstance(payload, dict) and "realtime_input" in payload:
                             # Forward realtime input (audio/video chunks)
                             # The SDK JS sends 'realtime_input' for generic media chunks
                             # For now we handle simpler case or adapt GeminiLive class
                             pass
                    except json.JSONDecodeError:
                        pass
                    
                    await text_input_queue.put(text)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error receiving from client: {e}")

    receive_task = asyncio.create_task(receive_from_client())

    async def run_session():
        async for event in gemini_client.start_session(
            audio_input_queue=audio_input_queue,
            video_input_queue=video_input_queue,
            text_input_queue=text_input_queue,
            audio_output_callback=audio_output_callback,
            audio_interrupt_callback=audio_interrupt_callback,
            setup_config=setup_config
        ):
            if event:
                # Forward events (transcriptions, etc) to client
                await websocket.send_json(event)

    try:
        await asyncio.wait_for(run_session(), timeout=SESSION_TIME_LIMIT)
    except asyncio.TimeoutError:
        logger.info("Session time limit reached")
        await websocket.close(code=1000, reason="Session time limit reached")
    except Exception as e:
        logger.error(f"Error in Gemini session: {e}")
    finally:
        receive_task.cancel()
        # Ensure websocket is closed if not already
        try:
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
