# -*- coding: utf-8 -*-
"""
config.py - KitchenAI 設定・環境変数管理
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import os
from dotenv import load_dotenv

# .env ファイルを読み込む
load_dotenv()

# --- Notion ---
NOTION_TOKEN: str = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")

# --- Gemini ---
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# --- LINE Messaging API ---
LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")

# --- ハードウェア ---
DOOR_SENSOR_PIN: int = int(os.getenv("DOOR_SENSOR_PIN", "27"))

# --- モードフラグ ---
_mock_env = os.getenv("MOCK_MODE", "True").strip().lower()
MOCK_MODE: bool = _mock_env in ("true", "1", "yes")

# --- ディスプレイ ---
DISPLAY_PREVIEW_PATH: str = "display_preview.png"

# --- Gemini モデル ---
GEMINI_MODEL: str = "gemini-3.1-flash-lite"

# --- 賞味期限警告日数 ---
EXPIRY_WARNING_DAYS: int = 3


def validate_config() -> bool:
    """必須設定の検証"""
    errors = []

    if not NOTION_TOKEN:
        errors.append("NOTION_TOKEN が設定されていません")
    if not NOTION_DATABASE_ID:
        errors.append("NOTION_DATABASE_ID が設定されていません")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "<YOUR_GEMINI_API_KEY>":
        errors.append("GEMINI_API_KEY が設定されていません（.env ファイルを確認してください）")

    if errors:
        print("[ERROR] 設定エラー:")
        for e in errors:
            print(f"   - {e}")
        return False

    print("[OK] 設定読み込み完了")
    print(f"   モード: {'[PC] シミュレーション (MOCK)' if MOCK_MODE else '[Pi] Raspberry Pi 本番'}")
    print(f"   Notion DB: {NOTION_DATABASE_ID}")
    print(f"   Gemini モデル: {GEMINI_MODEL}")
    return True


if __name__ == "__main__":
    validate_config()
