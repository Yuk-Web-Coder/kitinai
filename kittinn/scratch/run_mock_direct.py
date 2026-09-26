"""
run_mock_direct.py - KitchenAI メイン処理を直接テストするスクリプト
"""
import sys
import time
from unittest.mock import patch

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from main import KitchenAI

def run_test():
    print("=" * 60)
    print("  🧪 KitchenAI モック対話テスト（直接実行）")
    print("=" * 60 + "\n")

    app = KitchenAI()

    # テストシナリオ (ドアオープン -> 発言テキスト)
    scenarios = [
        ("シナリオ1: 在庫消費", "納豆1個と卵2個使ったよ"),
        ("シナリオ2: 全画面レシピ提案", "賞味期限が近いものでレシピ教えて"),
        ("シナリオ3: 食材追加（在庫画面に自動復帰）", "キャベツ1個買ってきたよ"),
    ]

    for title, text_input in scenarios:
        print("\n" + "=" * 50)
        print(f"🚪 [MOCK] {title}")
        print(f"🗣️ 入力: 「{text_input}」")
        print("=" * 50)

        # audio.listen() が指定テキストを返すようにモック化して _on_door_event を呼び出す
        with patch.object(app.audio, 'listen', return_value=text_input):
            app._on_door_event()
        
        time.sleep(1)

    print("\n" + "=" * 60)
    print("  ✅ モック対話テスト全て正常完了！")
    print("  🖼️ display_preview.png の表示更新を確認してください。")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    run_test()
