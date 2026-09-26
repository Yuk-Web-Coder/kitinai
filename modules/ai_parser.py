"""
modules/ai_parser.py - Gemini 1.5 Flash による自然言語解析・レシピ生成

機能:
  - ユーザー発話を解析して action を分類 (add / consume / cook / suggest_recipe)
  - 賞味期限優先のレシピ提案
  - 503 エラー時に指数バックオフで最大3回再試行
"""
import json
import time
import re
from typing import Optional
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL


# ------------------------------------------------------------------
# アクション定義
# ------------------------------------------------------------------
ACTION_ADD = "add"
ACTION_RESTOCK = "restock"      # 買い足し（既存在庫に加算）
ACTION_CONSUME = "consume"
ACTION_COOK = "cook"
ACTION_SET_QTY = "set_quantity"  # 数量を指定値に直接変更
ACTION_SUGGEST = "suggest_recipe"
ACTION_SHOPPING_LIST = "shopping_list"          # 買い物リストの照会
ACTION_ADD_SHOPPING_LIST = "add_shopping_list"  # 買い物リストへ直追加
ACTION_UNKNOWN = "unknown"



class AIParser:
    """Gemini API を使った自然言語解析・レシピ提案クラス"""

    def __init__(self):
        self._client = genai.Client(api_key=GEMINI_API_KEY)
        print(f"🤖 Gemini 初期化完了 (モデル: {GEMINI_MODEL})")

    # ------------------------------------------------------------------
    # 内部: API 呼び出し（指数バックオフ再試行付き）
    # ------------------------------------------------------------------
    def _generate(self, prompt: str, max_retries: int = 3) -> str:
        """
        Gemini API を呼び出す。503エラー時は指数バックオフで再試行。
        Returns:
            生成テキスト
        """
        for attempt in range(max_retries):
            try:
                response = self._client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                )
                return response.text or ""
            except Exception as e:
                err_str = str(e).lower()
                if "503" in err_str or "unavailable" in err_str:
                    wait = 2 ** attempt  # 1, 2, 4 秒
                    print(f"⚠️  Gemini 503 エラー (試行 {attempt + 1}/{max_retries}) → {wait}秒後に再試行")
                    time.sleep(wait)
                else:
                    print(f"❌ Gemini エラー: {e}")
                    raise

        raise RuntimeError("Gemini API が応答しませんでした（最大再試行回数超過）")

    # ------------------------------------------------------------------
    # 内部: JSON 抽出ヘルパー
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        レスポンステキストから JSON ブロックを抽出してパースする。
        """
        # ```json ... ``` または ``` ... ``` ブロックを抽出
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            json_str = match.group(1).strip()
        else:
            # フォールバック: テキスト全体をそのまま試みる
            json_str = text.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------------
    # 公開: ユーザー発話解析
    # ------------------------------------------------------------------
    def parse_user_input(self, text: str, inventory: list[dict]) -> dict:
        """
        ユーザーの発話を解析し、アクションと対象アイテムを返す。

        Args:
            text: ユーザーの発話テキスト
            inventory: 現在の在庫リスト（Notionから取得済み）

        Returns:
            {
                "action": "add" | "consume" | "cook" | "suggest_recipe" | "unknown",
                "items": [{"name": str, "quantity": str, "location": str, "expiry": str}],
                "message": str  # ユーザーへの応答メッセージ
            }
        """
        inventory_summary = self._format_inventory_for_prompt(inventory)

        prompt = f"""あなたはキッチン在庫管理AIアシスタントです。
ユーザーの発話を解析し、以下のJSON形式で応答してください。

## 現在の在庫
{inventory_summary}

## ユーザーの発話
「{text}」

## 応答ルール
以下のactionのいずれかに分類し、JSON形式のみで応答してください（説明文不要）:

- **add**: 初めて買ってきた食材を新規追加する
  → items に追加アイテムリストを入れる
  → location は発話から推測（冷蔵室/冷凍室/棚/調味料）、不明な場合は"冷蔵室"
  → expiry は発話から推測できる場合 YYYY-MM-DD 形式、不明な場合は""
  → quantity は発話から推測、不明な場合は"1個"

- **restock**: すでに在庫にある食材を買い足した（数量を加算する）
  → 在庫リストに同名の食材がある場合は restock を選ぶ
  → items の quantity に「追加する量」を入れる

- **consume**: 食材を一部使った（数量を減らす）
  → items の quantity に「使った量」を必ず入れる（例: "2個", "100g"）
  → 「全部使った」「使い切った」の場合は quantity を "全量" にする

- **cook**: 料理を作った（料理名から食材と使用量を推測して消費）
  → items に使われた食材と推定使用量を入れる
  → message に「〇〇を作りました」と記載

- **set_quantity**: 数量を具体的な値に直接変更する（「〇〇を△個にして」等）
  → items の quantity に「変更後の数量」を入れる

- **suggest_recipe**: レシピを聞いている・何が作れるか聞いている
  → items は空リスト
  → message は "" (generate_recipe_suggestion で別途生成)

- **shopping_list**: 買い物リスト・必要なもの・何買えばいいか聞いている
  → items は空リスト

- **add_shopping_list**: 買いたいもの・買い物リストに〇〇を追加してと指示している
  → items に買いたい食材名を入れる

- **unknown**: どれにも該当しない
  → message にやさしく内容を記載

## 応答JSON形式
```json
{{
  "action": "add|restock|consume|cook|set_quantity|suggest_recipe|shopping_list|add_shopping_list|unknown",
  "items": [
    {{"name": "食材名", "quantity": "数量", "location": "保管場所", "expiry": "YYYY-MM-DD"}}
  ],
  "message": "ユーザーへの応答メッセージ（日本語）"
}}
```"""

        raw = self._generate(prompt)
        result = self._extract_json(raw)

        # バリデーション・デフォルト値補完
        if not result:
            return {
                "action": ACTION_UNKNOWN,
                "items": [],
                "message": "申し訳ありません、発話を理解できませんでした。もう一度お話しください。",
            }

        result.setdefault("action", ACTION_UNKNOWN)
        result.setdefault("items", [])
        result.setdefault("message", "")

        return result

    # ------------------------------------------------------------------
    # 公開: レシピ提案
    # ------------------------------------------------------------------
    def generate_recipe_suggestion(self, inventory_list: list[dict]) -> str:
        """
        現在庫から賞味期限優先のレシピを提案する。

        Args:
            inventory_list: 在庫リスト（賞味期限昇順でソート済みを期待）

        Returns:
            レシピ提案テキスト（日本語）
        """
        if not inventory_list:
            return "現在庫が空です。食材を追加してから再度お試しください。"

        inventory_summary = self._format_inventory_for_prompt(inventory_list)

        prompt = f"""あなたはプロの料理アドバイザーです。
以下の在庫から、賞味期限が近い食材を優先的に使ったレシピを2〜3品提案してください。

## 現在の在庫（賞味期限昇順）
{inventory_summary}

## 提案のルール
1. 賞味期限が最も近い食材を必ず使ったレシピを最優先にする
2. 在庫にある食材だけで作れるレシピを選ぶ（不足食材は最小限にする）
3. 1品目は「本日イチオシ」として詳しく、2〜3品目はシンプルに紹介する
4. 調理時間・難易度も添える
5. 親しみやすい日本語で、400字以内で簡潔に回答する

## 応答形式
【本日イチオシ】〇〇（調理時間: XX分 / 難易度: ★☆☆）
材料: ...
作り方のポイント: ...

【他のおすすめ】
・△△（調理時間: XX分）
・□□（調理時間: XX分）"""

        return self._generate(prompt)

    # ------------------------------------------------------------------
    # 公開: レシート画像解析 (マルチモーダル)
    # ------------------------------------------------------------------
    def parse_receipt_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
        """
        レシート画像をGeminiで解析し、購入した食材と数量を抽出する。
        """
        prompt = """あなたはスーパーや食料品店のレシートを解析するAIです。
画像に写っているレシートから、購入した【食品・食材・飲料】を抽出してください。
日用品や雑貨（ラップ、洗剤、ティッシュなど）は除外し、食品・食材のみを抽出してください。

以下のJSON形式のみで応答してください:
```json
{
  "items": [
    {"name": "食材名", "quantity": "数量（例: 1パック, 1個, 500gなど、レシート記載に合わせて）", "location": "推測した保管場所（冷蔵室/冷凍室/棚/調味料）", "expiry": ""}
  ],
  "message": "レシートから〇点の食材を読み取りました。"
}
```"""

        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, prompt],
            )
            raw = response.text or ""
            result = self._extract_json(raw)
            if not result or "items" not in result:
                return {
                    "items": [],
                    "message": "レシートから食材を検出できませんでした。"
                }
            return result
        except Exception as e:
            print(f"❌ レシート解析エラー: {e}")
            return {
                "items": [],
                "message": f"レシートの解析中にエラーが発生しました: {e}"
            }

    # ------------------------------------------------------------------
    # 内部: 在庫フォーマット
    # ------------------------------------------------------------------
    @staticmethod
    def _format_inventory_for_prompt(inventory: list[dict]) -> str:
        """在庫リストをプロンプト用の文字列に変換する"""
        if not inventory:
            return "（在庫なし）"

        lines = []
        for item in inventory:
            name = item.get("name", "不明")
            location = item.get("location", "")
            quantity = item.get("quantity", "")
            expiry = item.get("expiry", "")

            parts = [f"・{name}"]
            if quantity:
                parts.append(f"({quantity})")
            if location:
                parts.append(f"[{location}]")
            if expiry:
                parts.append(f"賞味期限: {expiry}")

            lines.append(" ".join(parts))

        return "\n".join(lines)


# ------------------------------------------------------------------
# 単体テスト
# ------------------------------------------------------------------
if __name__ == "__main__":
    from config import validate_config

    if not validate_config():
        exit(1)

    parser = AIParser()

    # テスト在庫
    test_inventory = [
        {"name": "牛乳", "quantity": "2本", "location": "冷蔵室", "expiry": "2026-09-27"},
        {"name": "卵", "quantity": "8個", "location": "冷蔵室", "expiry": "2026-10-05"},
        {"name": "玉ねぎ", "quantity": "3個", "location": "棚", "expiry": ""},
        {"name": "鶏もも肉", "quantity": "300g", "location": "冷凍室", "expiry": "2026-10-15"},
    ]

    tests = [
        ("牛乳1本買ってきたよ", "買い足し (restock)"),
        ("卵を3個使ったよ", "小数消費 (consume 数量あり)"),
        ("牛乳を今1本に変更して", "数量直接変更 (set_quantity)"),
        ("卵を全部使い切ったよ", "全量消費"),
        ("今日何作れる？", "レシピ提案"),
    ]

    for phrase, label in tests:
        print("\n" + "=" * 50)
        print(f"【{label}】「{phrase}」")
        result = parser.parse_user_input(phrase, test_inventory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
