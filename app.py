import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional

import database
import llm
from config import MAX_CONTENT_LENGTH, DEBUG_MODE, IS_SERVERLESS


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield
    await llm.close_http_client()


app = FastAPI(title="星空信匣 Starbox", lifespan=lifespan)


# --- Models ---

class SendRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_LENGTH)
    persona_id: Optional[str] = None


class OpenRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)


# --- Endpoints ---

@app.post("/api/letters/send")
async def send_letter(req: SendRequest):
    persona_map = llm.get_persona_map()
    pid = req.persona_id or "random"
    if pid != "random" and pid not in persona_map:
        raise HTTPException(status_code=400, detail={"error": "invalid_persona"})

    if not DEBUG_MODE and not database.check_rate_limit(req.device_id):
        resets_at = database.get_rate_limit_reset()
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "resets_at": resets_at.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
        )

    result = database.insert_letter(req.device_id, req.content, pid)
    letter_id = result["id"]

    # 立即调用 AI 回信
    try:
        llm_result = await llm.generate_reply(req.content, pid)
        replied_at = database.save_reply(
            letter_id, llm_result["reply"], llm_result["persona_name"],
            llm_result["persona_era"], llm_result["persona_id"]
        )
        return {
            "id": letter_id,
            "status": "replied",
            "reply": llm_result["reply"],
            "persona": {
                "name": llm_result["persona_name"],
                "era": llm_result["persona_era"],
            },
            "replied_at": replied_at,
        }
    except llm.LLMError:
        return {
            "id": letter_id,
            "status": "locked",
            "unlock_at": result["unlock_at"],
        }


@app.get("/api/letters")
async def get_letters(device_id: str):
    if not device_id or len(device_id) > 128:
        raise HTTPException(status_code=400, detail={"error": "invalid_device_id"})
    return database.get_letters_by_device(device_id)


@app.post("/api/letters/{letter_id}/open")
async def open_letter(letter_id: str, req: OpenRequest):
    result = database.open_letter(letter_id, req.device_id)

    if "error" in result:
        err = result["error"]
        if err == "letter_not_found":
            raise HTTPException(status_code=404, detail=result)
        elif err == "still_locked":
            raise HTTPException(status_code=403, detail=result)

    if "reply" in result:
        return result

    row = result["row"]
    try:
        llm_result = await llm.generate_reply(row["content"], row["target_frequency"])
    except llm.LLMError:
        raise HTTPException(status_code=502, detail={"error": "llm_unavailable", "retry": True})

    replied_at = database.save_reply(
        letter_id, llm_result["reply"], llm_result["persona_name"], llm_result["persona_era"],
        llm_result["persona_id"]
    )

    return {
        "id": letter_id,
        "reply": llm_result["reply"],
        "persona": {
            "name": llm_result["persona_name"],
            "era": llm_result["persona_era"],
        },
        "replied_at": replied_at,
    }


@app.get("/api/personas")
async def get_personas():
    personas = llm.load_personas()
    return {
        "random_available": len(personas) > 1,
        "characters": [
            {"id": p["id"], "name": p["name"], "era": p["era"]}
            for p in personas
        ]
    }


# --- Static files ---

if not IS_SERVERLESS:
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>index.html not found</h1>", status_code=404)
