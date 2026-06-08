import os

# === 测试模式开关 ===
# True  → 锁定倒计时缩短为 5 秒，便于快速走完全流程审核大模型回信质量
# False → 正式模式，锁定 8 小时
DEBUG_MODE = False

# === 锁定时长 ===
if DEBUG_MODE:
    LOCK_DURATION_SECONDS = 5
else:
    LOCK_DURATION_SECONDS = 8 * 60 * 60  # 8 hours

# === 限流 ===
MAX_LETTERS_PER_DAY = 2

# === 信件内容限制 ===
MAX_CONTENT_LENGTH = 2000

# === 数据库 ===
DATABASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_PATH = os.path.join(DATABASE_DIR, "starbox.db")

# === DeepSeek API ===
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    import sys
    print("⚠️  警告: 未设置环境变量 DEEPSEEK_API_KEY，LLM 回信功能将不可用", file=sys.stderr)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# === 人设目录 ===
PERSONAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas")
