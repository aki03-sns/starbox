from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

import database
import llm
from config import MAX_CONTENT_LENGTH, DEBUG_MODE


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


class FavoriteRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    persona_id: str = Field(..., min_length=1, max_length=64)


class LetterFavoriteRequest(BaseModel):
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
    return result


@app.get("/api/letters")
async def get_letters(device_id: str):
    if not device_id or len(device_id) > 128:
        raise HTTPException(status_code=400, detail={"error": "invalid_device_id"})
    return database.get_letters_by_device(device_id)


@app.post("/api/letters/{letter_id}/favorite")
async def toggle_letter_favorite(letter_id: str, req: LetterFavoriteRequest):
    result = database.toggle_letter_favorite(letter_id, req.device_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "letter_not_found"})
    return result


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


@app.post("/api/favorites")
async def add_favorite(req: FavoriteRequest):
    persona_map = llm.get_persona_map()
    if req.persona_id not in persona_map:
        raise HTTPException(status_code=400, detail={"error": "invalid_persona"})
    added = database.add_favorite(req.device_id, req.persona_id)
    if not added:
        return {"status": "already_exists", "persona_id": req.persona_id}
    return {"status": "added", "persona_id": req.persona_id}


@app.get("/api/favorites")
async def get_favorites(device_id: str):
    if not device_id or len(device_id) > 128:
        raise HTTPException(status_code=400, detail={"error": "invalid_device_id"})
    fav_ids = database.get_favorites(device_id)
    persona_map = llm.get_persona_map()
    return [
        {"id": pid, "name": persona_map[pid]["name"], "era": persona_map[pid]["era"]}
        for pid in fav_ids if pid in persona_map
    ]


# --- Static files ---

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")
