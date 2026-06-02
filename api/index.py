"""
Vercel Serverless Function entry point.
Imports the FastAPI app from ../app.py
"""
import sys
import os

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402, F401
