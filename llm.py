import json
import random
import os
import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL


PERSONAS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas.json")

# 缓存：只读一次文件
_personas_cache: list | None = None
_persona_map_cache: dict | None = None

# 复用 httpx 客户端（连接池）
_http_client: httpx.AsyncClient | None = None


class LLMError(Exception):
    def __init__(self, status_code=502):
        self.status_code = status_code


def load_personas() -> list:
    global _personas_cache
    if _personas_cache is None:
        with open(PERSONAS_PATH, "r", encoding="utf-8") as f:
            _personas_cache = json.load(f)
    return _personas_cache


def get_persona_map() -> dict:
    global _persona_map_cache
    if _persona_map_cache is None:
        _persona_map_cache = {p["id"]: p for p in load_personas()}
    return _persona_map_cache


def pick_persona(persona_id: str) -> dict:
    if persona_id is None or persona_id == "random":
        return random.choice(load_personas())
    return get_persona_map()[persona_id]


def build_system_prompt(persona: dict) -> str:
    base = persona["system_prompt"]
    name = persona["name"]
    era = persona["era"]

    left_q = "“"
    right_q = "”"
    dash = "—"

    return (
        f"{base}\n\n"
        f"【绝对执行指令 / OVERRIDE PROTOCOL】\n"
        f"- 格式锁定：绝对禁止输出任何{left_q}好的{right_q}、{left_q}收到{right_q}等前置确认文字。必须立刻直接输出正文。\n"
        f"- 行为红线：绝不共情！绝不分析发信人的心理！你必须保持极度符合设定的语气，"
        f"只需陈述你在当前时空看到的景象、你的自身经历，或对信件内容做出带有强烈偏见的简短评判。\n"
        f"- 固定落款：必须严格以\"\\n\\n{dash}{name}，{era}\"作为回复的最后一行。"
    )


def build_user_prompt(user_content: str) -> str:
    return f"[截获时空漂流信件]：\n\n{user_content}\n\n[信件结束]"


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=60)
    return _http_client


async def generate_reply(user_content: str, persona_id: str) -> dict:
    if not DEEPSEEK_API_KEY:
        raise LLMError(status_code=503)

    persona = pick_persona(persona_id)
    system_prompt = build_system_prompt(persona)
    user_prompt = build_user_prompt(user_content)

    client = _get_http_client()
    resp = await client.post(
        f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 1.2,
            "max_tokens": 1024,
        },
    )

    if resp.status_code != 200:
        raise LLMError()

    data = resp.json()
    reply_text = data["choices"][0]["message"]["content"]

    return {
        "reply": reply_text,
        "persona_id": persona["id"],
        "persona_name": persona["name"],
        "persona_era": persona["era"],
    }


async def close_http_client():
    """应用关闭时调用，释放连接池"""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
