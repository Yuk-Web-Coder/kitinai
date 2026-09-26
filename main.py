"""
main.py - KitchenAI メインループ

処理フロー:
  1. 初期化（設定検証 / Notion / AI / ディスプレイ / 音声 / センサー）
  2. 起動時に在庫をディスプレイへ反映
  3. ドア開閉 or Enterキー → 音声/テキスト入力 → Gemini解析 → Notion更新 → 応答
  4. Ctrl+C で安全に終了
"""
import sys
import time
import threading
import signal
from config import validate_config, MOCK_MODE, LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET

# --- 各モジュールのインポート ---
from modules.notion_sync import NotionSync
from modules.ai_parser import AIParser
from modules.display import DisplayManager
from modules.audio import AudioManager
from modules.sensor import DoorSensor
from modules.line_server import start_line_server_thread


# ===========================================================================
# KitchenAI メインクラス
# ===========================================================================
class KitchenAI:
    def __init__(self):
        print("\n" + "=" * 60)
        print("  🍳 KitchenAI 起動中...")
        print("=" * 60 + "\n")

        # 設定検証
        if not validate_config():
            print("\n⛔ 設定エラーのため起動できません。.env ファイルを確認してください。")
            sys.exit(1)

        # 各モジュール初期化
        print("\n📦 モジュール初期化中...\n")
        self.notion = NotionSync()
        self.ai = AIParser()
        self.display = DisplayManager()
        self.audio = AudioManager()

        # ドア開閉イベントのロック（多重処理防止）
        self._processing_lock = threading.Lock()
        self._running = True

        # センサー初期化（コールバック登録）
        self.sensor = DoorSensor(callback=self._on_door_event)

        # LINE Webhook サーバー起動（設定されている場合）
        if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
            try:
                start_line_server_thread(self.notion, self.ai, port=5000)
                print("📱 LINE Webhook サーバーをスレッド起動しました")
            except Exception as e:
                print(f"⚠️ LINE サーバー起動エラー: {e}")
        else:
            print("ℹ️  LINE_CHANNEL_ACCESS_TOKEN 未設定のため、LINE Webhook サーバーは起動しません")

        print("\n✅ 全モジュール初期化完了")

    # ------------------------------------------------------------------
    # 起動
    # ------------------------------------------------------------------
    def run(self):
        """メインループを起動する"""
        # 起動時に在庫をディスプレイへ反映
        self._refresh_display()

        # センサー監視開始
        self.sensor.start()

        print("\n" + "=" * 60)
        print("  🚀 KitchenAI 稼働中")
        if MOCK_MODE:
            print("  [Enter] キーでドア開閉をシミュレーション")
        print("  [Ctrl+C] で終了")
        print("=" * 60 + "\n")

        # メインスレッドは Ctrl+C を待つだけ
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    # ------------------------------------------------------------------
    # ドア開閉イベントハンドラ
    # ------------------------------------------------------------------
    def _on_door_event(self):
        """ドアが開いたときに呼ばれる。多重処理を防ぐためロックを使用"""
        if not self._processing_lock.acquire(blocking=False):
            print("⏳ 処理中です。しばらくお待ちください...")
            return

        try:
            self._handle_interaction()
        except Exception as e:
            print(f"❌ 処理中にエラーが発生しました: {e}")
            self.audio.speak("エラーが発生しました。もう一度お試しください。")
        finally:
            self._processing_lock.release()

    # ------------------------------------------------------------------
    # インタラクション処理
    # ------------------------------------------------------------------
    def _handle_interaction(self):
        """ドア開閉後の一連の処理を行う"""
        print("\n" + "-" * 40)
        print("🎤 音声入力受付中...")

        # 音声 / テキスト入力
        user_input = self.audio.listen()
        if not user_input:
            self.audio.speak("音声を認識できませんでした。もう一度話しかけてください。")
            return

        print(f"📝 受け取った内容: 「{user_input}」")

        # 現在の在庫を取得
        inventory = self.notion.get_inventory()

        # Gemini で解析
        print("🤖 Gemini で解析中...")
        result = self.ai.parse_user_input(user_input, inventory)
        action = result.get("action", "unknown")
        items = result.get("items", [])
        message = result.get("message", "")

        print(f"📊 解析結果: action={action}, items={len(items)}件")

        # アクションに応じた処理
        if action == "add":
            self._handle_add(items, message)
        elif action == "restock":
            self._handle_restock(items, message)
        elif action == "consume":
            self._handle_consume(items, message)
        elif action in ("cook",):
            self._handle_cook(items, message)
        elif action == "set_quantity":
            self._handle_set_quantity(items, message)
        elif action == "suggest_recipe":
            self._handle_recipe(inventory)
        else:
            # unknown / その他
            self.audio.speak(message or "申し訳ありません、理解できませんでした。")

        # ディスプレイを更新（レシピ提案以外の場合に在庫画面を更新）
        if action != "suggest_recipe":
            self._refresh_display(mode="inventory")

    # ------------------------------------------------------------------
    # アクション: 食材追加
    # ------------------------------------------------------------------
    def _handle_add(self, items: list[dict], message: str):
        """食材を Notion に追加し、結果を音声で案内する"""
        if not items:
            self.audio.speak(message or "追加する食材が分かりませんでした。")
            return

        added = []
        for item in items:
            name = item.get("name", "")
            quantity = item.get("quantity", "1個")
            location = item.get("location", "冷蔵室")
            expiry = item.get("expiry", "")

            if not name:
                continue

            success = self.notion.add_item(name, quantity, location, expiry)
            if success:
                added.append(name)

        if added:
            names = "、".join(added)
            response = f"{names}を在庫に追加しました。"
            if message:
                response = message
            self.audio.speak(response)
        else:
            self.audio.speak("食材の追加に失敗しました。")

    # ------------------------------------------------------------------
    # アクション: 買い足し（既存在庫への加算）
    # ------------------------------------------------------------------
    def _handle_restock(self, items: list[dict], message: str):
        """Notion の在庫数量に追加分を加算する"""
        if not items:
            self.audio.speak(message or "買い足しする食材が分かりませんでした。")
            return

        results = []
        for item in items:
            name = item.get("name", "")
            quantity = item.get("quantity", "1個")
            location = item.get("location", "冷蔵室")
            expiry = item.get("expiry", "")
            if not name:
                continue

            r = self.notion.add_to_existing(name, quantity)
            if r.get("found"):
                # 既存在庫への加算成功
                new_qty = r.get("new_quantity", "")
                results.append(f"{name}を{quantity}追加（計{new_qty}）")
            else:
                # 新規登録に切り替え
                self.notion.add_item(name, quantity, location, expiry)
                results.append(f"{name}を新規追加（{quantity}）")

        response = "。".join(results) + "。" if results else "処理できませんでした。"
        self.audio.speak(message or response)

    # ------------------------------------------------------------------
    # アクション: 食材消費（数量減算）
    # ------------------------------------------------------------------
    def _handle_consume(self, items: list[dict], message: str):
        """items の quantity 分だけ Notion の数量を減算する"""
        if not items:
            self.audio.speak(message or "消費する食材が分かりませんでした。")
            return

        responses = []
        for item in items:
            name = item.get("name", "")
            qty = item.get("quantity", "")
            if not name:
                continue

            # "全量" / "全部" / "空" の場合は全量消費
            is_all = qty in ("全量", "全部", "", "全て")
            result = self.notion.consume_item(name, "" if is_all else qty)

            if result["success"]:
                if result["action"] == "finished":
                    responses.append(f"{name}を使い切りました")
                else:
                    remaining = result.get("remaining", "")
                    responses.append(f"{name}を{qty}使いました（残り{remaining}）")
            else:
                responses.append(f"{name}は在庫に見つかりませんでした")

        response = "。".join(responses) + "。" if responses else "処理完了。"
        self.audio.speak(message or response)

    # ------------------------------------------------------------------
    # アクション: 料理を作った（消費量指定付き）
    # ------------------------------------------------------------------
    def _handle_cook(self, items: list[dict], message: str):
        """cook アクション: 食材と使用量を Gemini が推定して減算"""
        self._handle_consume(items, message)

    # ------------------------------------------------------------------
    # アクション: 数量を直接変更
    # ------------------------------------------------------------------
    def _handle_set_quantity(self, items: list[dict], message: str):
        """items の quantity に変更後数量を入れて直接更新"""
        if not items:
            self.audio.speak(message or "変更する食材が分かりませんでした。")
            return

        responses = []
        for item in items:
            name = item.get("name", "")
            new_qty = item.get("quantity", "")
            if not name or not new_qty:
                continue

            result = self.notion.set_quantity(name, new_qty)
            if result["success"]:
                responses.append(f"{name}を{new_qty}に変更しました")
            else:
                responses.append(f"{name}は在庫に見つかりませんでした")

        response = "。".join(responses) + "。" if responses else "処理完了。"
        self.audio.speak(message or response)

    # ------------------------------------------------------------------
    # アクション: レシピ提案
    # ------------------------------------------------------------------
    def _handle_recipe(self, inventory: list[dict]):
        """賞味期限優先のレシピを提案し、音声&ディスプレイで案内する"""
        print("📖 レシピ生成中...")
        recipe = self.ai.generate_recipe_suggestion(inventory)

        if recipe:
            self.audio.speak(recipe)
            # レシピを全画面モードでディスプレイ表示
            self._refresh_display(recipe=recipe, mode="recipe")
        else:
            self.audio.speak("レシピの提案に失敗しました。")

    # ------------------------------------------------------------------
    # ディスプレイ更新
    # ------------------------------------------------------------------
    def _refresh_display(self, recipe: str = "", mode: str = "auto"):
        """在庫をNotionから取得し、ディスプレイを更新する"""
        try:
            inventory = self.notion.get_inventory()
            self.display.update(inventory, recipe, mode=mode)
        except Exception as e:
            print(f"⚠️  ディスプレイ更新エラー: {e}")

    # ------------------------------------------------------------------
    # 終了処理
    # ------------------------------------------------------------------
    def _shutdown(self):
        print("\n\n🛑 KitchenAI をシャットダウンしています...")
        self._running = False
        self.sensor.stop()
        self.display.cleanup()
        print("👋 終了しました。")


# ===========================================================================
# エントリポイント
# ===========================================================================
def main():
    app = KitchenAI()
    app.run()


if __name__ == "__main__":
    main()
