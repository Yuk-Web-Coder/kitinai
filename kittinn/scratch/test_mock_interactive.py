"""
test_mock_interactive.py - main.py のモック対話環境を自動テストするスクリプト
"""
import os
import subprocess
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def run_interactive_test():
    print("🚀 モック環境で main.py を起動し、ドア開閉と会話シミュレーションを実行します...\n")

    # シミュレートする一連の会話（Enterキー + 発話テキスト）
    # 空行 '\n' がドア開閉トリガー、直後のテキストが発話内容
    test_inputs = [
        "\n",                                # ドアを開ける
        "納豆1個と卵2個使ったよ\n",               # 食材消費
        "\n",                                # ドアを開ける
        "賞味期限が近いものでレシピ教えて\n",       # レシピ提案（画面切り替え）
        "\n",                                # ドアを開ける
        "キャベツ1個買ってきたよ\n",              # 食材追加（在庫画面へ復帰）
    ]
    
    input_str = "".join(test_inputs)

    # 環境変数に PYTHONIOENCODING=utf-8 を設定
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # subprocess で main.py を起動
    process = subprocess.Popen(
        [sys.executable, "main.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1
    )

    try:
        # 入力を送信して終了まで待機（Timeout付き）
        stdout, _ = process.communicate(input=input_str, timeout=35)
        print("--- 📋 main.py 実行ログ ---")
        print(stdout)
        print("---------------------------")
        print("\n✅ モック環境インタラクティブテスト成功！")
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, _ = process.communicate()
        print("--- 📋 実行ログ（タイムアウト） ---")
        print(stdout)
        print("-----------------------------------")

if __name__ == "__main__":
    run_interactive_test()
