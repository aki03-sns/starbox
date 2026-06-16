import sys
import os

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mangum import Mangum
from app import app

handler = Mangum(app)
