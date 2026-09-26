# -*- coding: utf-8 -*-
"""
modules/notion_sync.py - Notion データベース連携

操作:
  - add_item         : 新規食材を「在庫あり」で追加
  - consume_item     : 数量を減算し、0になったら「使い切った」に更新
  - set_quantity     : 数量を指定値に直接セット
  - add_to_existing  : 既存在庫の数量に加算（買い足し）
  - get_inventory    : 「在庫あり」の食材を賞味期限昇順で取得
"""
import re
from datetime import datetime
from typing import Optional, Tuple
from notion_client import Client
from notion_client.errors import APIResponseError

from config import NOTION_TOKEN, NOTION_DATABASE_ID

# 賞味期限なしアイテムのソートキー（末尾扱い）
_NO_EXPIRY_SORT_KEY = "9999-99-99"


class NotionSync:
    """Notion DB 操作クラス"""

    def __init__(self):
        self._notion = Client(auth=NOTION_TOKEN)
        self._db_id = NOTION_DATABASE_ID
        print(f"📓 Notion 初期化完了 (DB: {self._db_id})")

    # ------------------------------------------------------------------
    # 公開: 食材追加
    # ------------------------------------------------------------------
    def add_item(
        self,
        name: str,
        quantity: str = "1個",
        location: str = "冷蔵室",
        expiry: str = "",
    ) -> bool:
        """
        食材を Notion DB に「在庫あり」で新規追加する。

        Args:
            name    : 食材名
            quantity: 数量（例: "2個", "1本"）
            location: 保管場所（"冷蔵室"|"冷凍室"|"棚"|"調味料"）
            expiry  : 賞味期限 YYYY-MM-DD 形式（省略可）

        Returns:
            成功 True / 失敗 False
        """
        # 保管場所バリデーション
        valid_locations = ["冷蔵室", "冷凍室", "棚", "調味料"]
        if location not in valid_locations:
            location = "冷蔵室"

        properties: dict = {
            "名前": {
                "title": [{"text": {"content": name}}]
            },
            "保管場所": {
                "select": {"name": location}
            },
            "ステータス": {
                "status": {"name": "在庫あり"}
            },
            "数量": {
                "rich_text": [{"text": {"content": quantity}}]
            },
            "賞味期限目安": {
                "rich_text": [{"text": {"content": expiry}}]
            },
        }

        try:
            page = self._notion.pages.create(
                parent={"database_id": self._db_id},
                properties=properties,
            )
            print(f"✅ 追加完了: {name} ({quantity}) [{location}] 期限:{expiry or '未設定'}")
            return True
        except APIResponseError as e:
            print(f"❌ Notion 追加エラー: {e}")
            return False

    # ------------------------------------------------------------------
    # 公開: 食材消費（数量減算 → 0になったら「使い切った」）
    # ------------------------------------------------------------------
    def consume_item(self, name: str, amount: str = "") -> dict:
        """
        食材名で検索し、数量を減算する。
        残量が0以下になった場合はステータスを「使い切った」に更新。

        Args:
            name  : 食材名
            amount: 消費量（例: "2個", "100g"）。空の場合は全量消費。

        Returns:
            {
                "success": bool,
                "action": "decreased" | "finished" | "not_found",
                "remaining": str,   # 残量文字列
                "message": str
            }
        """
        # 在庫を検索して現在の数量を取得
        item = self._find_item_full(name)
        if not item:
            print(f"[WARN] 見つかりません: {name}")
            return {"success": False, "action": "not_found",
                    "remaining": "", "message": f"{name}は在庫に見つかりませんでした"}

        page_id = item["page_id"]
        current_qty_str = item.get("quantity", "")

        # 全量消費（amountなし）または数量計算不能な場合
        if not amount:
            return self._mark_finished(page_id, name)

        # 数値・単位を抽出して計算
        current_val, unit = self._parse_quantity(current_qty_str)
        consume_val, _ = self._parse_quantity(amount)

        if current_val is None or consume_val is None:
            # 数値計算できない場合は全量消費扱い
            print(f"[INFO] 数量計算不可のため全量消費: {name} ({current_qty_str} - {amount})")
            return self._mark_finished(page_id, name)

        remaining_val = current_val - consume_val
        print(f"[INFO] 数量計算: {current_val}{unit} - {consume_val}{unit} = {remaining_val}{unit}")

        if remaining_val <= 0:
            return self._mark_finished(page_id, name)
        else:
            # 残量を更新
            remaining_str = self._format_quantity(remaining_val, unit)
            return self._update_quantity_str(page_id, name, remaining_str, action="decreased")

    # ------------------------------------------------------------------
    # 公開: 数量を直接セット（「卵を5個に変更して」）
    # ------------------------------------------------------------------
    def set_quantity(self, name: str, new_quantity: str) -> dict:
        """
        食材の数量を指定値に直接セットする。

        Args:
            name        : 食材名
            new_quantity: 新しい数量（例: "5個", "200g"）

        Returns:
            {"success": bool, "message": str}
        """
        item = self._find_item_full(name)
        if not item:
            return {"success": False, "message": f"{name}は在庫に見つかりませんでした"}

        result = self._update_quantity_str(item["page_id"], name, new_quantity, action="set")
        return result

    # ------------------------------------------------------------------
    # 公開: 既存在庫に数量を加算（買い足し）
    # ------------------------------------------------------------------
    def add_to_existing(self, name: str, amount: str) -> dict:
        """
        既存在庫の数量に追加分を加算する。
        在庫にない場合は False を返す（呼び出し元で add_item に切り替える）。

        Args:
            name  : 食材名
            amount: 追加量（例: "6個", "500ml"）

        Returns:
            {"success": bool, "found": bool, "new_quantity": str, "message": str}
        """
        item = self._find_item_full(name)
        if not item:
            return {"success": False, "found": False,
                    "new_quantity": "", "message": f"{name}は既存在庫にありません"}

        current_qty_str = item.get("quantity", "")
        current_val, unit = self._parse_quantity(current_qty_str)
        add_val, add_unit = self._parse_quantity(amount)

        if current_val is not None and add_val is not None:
            new_val = current_val + add_val
            effective_unit = unit or add_unit or ""
            new_qty_str = self._format_quantity(new_val, effective_unit)
        else:
            # 計算できない場合はそのまま上書き
            new_qty_str = amount

        result = self._update_quantity_str(item["page_id"], name, new_qty_str, action="added")
        result["found"] = True
        result["new_quantity"] = new_qty_str
        return result

    # ------------------------------------------------------------------
    # 内部: ステータスを「使い切った」にする
    # ------------------------------------------------------------------
    def _mark_finished(self, page_id: str, name: str) -> dict:
        try:
            self._notion.pages.update(
                page_id=page_id,
                properties={"ステータス": {"status": {"name": "使い切った"}}},
            )
            print(f"[OK] 使い切った: {name}")
            return {"success": True, "action": "finished",
                    "remaining": "0", "message": f"{name}を使い切りました"}
        except APIResponseError as e:
            print(f"[ERROR] Notion 更新エラー: {e}")
            return {"success": False, "action": "error",
                    "remaining": "", "message": str(e)}

    # ------------------------------------------------------------------
    # 内部: 数量文字列を Notion に書き込む
    # ------------------------------------------------------------------
    def _update_quantity_str(self, page_id: str, name: str,
                             new_qty: str, action: str) -> dict:
        try:
            self._notion.pages.update(
                page_id=page_id,
                properties={
                    "数量": {"rich_text": [{"text": {"content": new_qty}}]}
                },
            )
            print(f"[OK] 数量更新: {name} → {new_qty} ({action})")
            return {"success": True, "action": action,
                    "remaining": new_qty,
                    "message": f"{name}の数量を {new_qty} に更新しました"}
        except APIResponseError as e:
            print(f"[ERROR] Notion 数量更新エラー: {e}")
            return {"success": False, "action": "error",
                    "remaining": "", "message": str(e)}

    # ------------------------------------------------------------------
    # 内部: 食材を名前で検索して全情報を返す
    # ------------------------------------------------------------------
    def _find_item_full(self, name: str) -> Optional[dict]:
        """「在庫あり」の食材を名前で検索して dict を返す"""
        try:
            results = self._notion.search(
                query=name,
                filter={"property": "object", "value": "page"},
            )
            for page in results.get("results", []):
                try:
                    title = self._get_title(page)
                    status = (
                        page.get("properties", {})
                        .get("ステータス", {})
                        .get("status", {})
                        .get("name", "")
                    )
                    if title == name and status == "在庫あり":
                        return self._page_to_item(page)
                except Exception:
                    continue
            # 部分一致フォールバック
            for page in results.get("results", []):
                try:
                    status = (
                        page.get("properties", {})
                        .get("ステータス", {})
                        .get("status", {})
                        .get("name", "")
                    )
                    if status == "在庫あり":
                        return self._page_to_item(page)
                except Exception:
                    continue
            return None
        except APIResponseError:
            return None

    # ------------------------------------------------------------------
    # 内部: 数量文字列を (数値, 単位) に分解
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_quantity(qty_str: str) -> Tuple[Optional[float], str]:
        """
        "10個" → (10.0, "個")
        "200g" → (200.0, "g")
        "1.5kg" → (1.5, "kg")
        "3本" → (3.0, "本")
        数値が取れない場合は (None, "")
        """
        if not qty_str:
            return None, ""
        match = re.search(r"([\d.]+)\s*([^\d.\s]*)", qty_str.strip())
        if match:
            try:
                val = float(match.group(1))
                unit = match.group(2).strip()
                return val, unit
            except ValueError:
                pass
        return None, ""

    # ------------------------------------------------------------------
    # 内部: 数値+単位を文字列に戻す
    # ------------------------------------------------------------------
    @staticmethod
    def _format_quantity(val: float, unit: str) -> str:
        """10.0, "個" → "10個" / 1.5, "kg" → "1.5kg"""
        if val == int(val):
            return f"{int(val)}{unit}"
        return f"{val}{unit}"

    # ------------------------------------------------------------------
    # 公開: 在庫一覧取得（賞味期限昇順）
    # ------------------------------------------------------------------
    def get_inventory(self) -> list[dict]:
        """
        「在庫あり」の食材を賞味期限昇順で返す。
        """
        return self._get_items_by_status(["在庫あり"], sort_by_expiry=True)

    # ------------------------------------------------------------------
    # 公開: 買い物リスト取得（「使い切った」または「要購入」）
    # ------------------------------------------------------------------
    def get_shopping_list(self) -> list[dict]:
        """
        ステータスが「使い切った」または「要購入」の食材を一覧で返す。

        Returns:
            [{"name": str, "quantity": str, "location": str, "expiry": str}, ...]
        """
        return self._get_items_by_status(["使い切った", "要購入"], sort_by_expiry=False)

    # ------------------------------------------------------------------
    # 公開: 買い物リストへ手動追加（「要購入」ステータスで作成）
    # ------------------------------------------------------------------
    def add_to_shopping_list(self, name: str, quantity: str = "1個") -> bool:
        """
        指定した食材を「要購入」ステータスで Notion DB に登録する。
        """
        # 既に同じ名前のページがあればステータスを「要購入」にする
        item = self._find_item_any_status(name)
        if item:
            try:
                self._notion.pages.update(
                    page_id=item["page_id"],
                    properties={
                        "ステータス": {"status": {"name": "要購入"}},
                        "数量": {"rich_text": [{"text": {"content": quantity}}]}
                    }
                )
                print(f"✅ 買い物リスト更新: {name} ({quantity})")
                return True
            except APIResponseError as e:
                print(f"❌ 買い物リスト更新エラー: {e}")
                return False

        # 新規作成
        properties: dict = {
            "名前": {"title": [{"text": {"content": name}}]},
            "ステータス": {"status": {"name": "要購入"}},
            "数量": {"rich_text": [{"text": {"content": quantity}}]},
            "保管場所": {"select": {"name": "冷蔵室"}},
            "賞味期限目安": {"rich_text": [{"text": {"content": ""}}]}
        }
        try:
            self._notion.pages.create(parent={"database_id": self._db_id}, properties=properties)
            print(f"✅ 買い物リスト新規登録: {name} ({quantity})")
            return True
        except APIResponseError as e:
            print(f"❌ 買い物リスト追加エラー: {e}")
            return False

    # ------------------------------------------------------------------
    # 内部: 全ステータス検索
    # ------------------------------------------------------------------
    def _find_item_any_status(self, name: str) -> Optional[dict]:
        try:
            results = self._notion.search(query=name, filter={"property": "object", "value": "page"})
            for page in results.get("results", []):
                parent = page.get("parent", {})
                if parent.get("database_id", "").replace("-", "") != self._db_id.replace("-", ""):
                    continue
                if self._get_title(page) == name:
                    return self._page_to_item(page)
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 内部: 指定ステータスのアイテム取得ヘルパー
    # ------------------------------------------------------------------
    def _get_items_by_status(self, statuses: list[str], sort_by_expiry: bool = False) -> list[dict]:
        try:
            all_items = []
            start_cursor = None

            while True:
                kwargs = {
                    "filter": {"property": "object", "value": "page"},
                    "page_size": 100,
                }
                if start_cursor:
                    kwargs["start_cursor"] = start_cursor

                results = self._notion.search(**kwargs)
                pages = results.get("results", [])

                for page in pages:
                    parent = page.get("parent", {})
                    if parent.get("database_id", "").replace("-", "") != self._db_id.replace("-", ""):
                        continue

                    item = self._page_to_item(page)
                    status_prop = (
                        page.get("properties", {})
                        .get("ステータス", {})
                        .get("status", {})
                        .get("name", "")
                    )
                    if status_prop in statuses:
                        all_items.append(item)

                if results.get("has_more"):
                    start_cursor = results.get("next_cursor")
                else:
                    break

            if sort_by_expiry:
                all_items.sort(key=lambda x: x.get("expiry") or _NO_EXPIRY_SORT_KEY)
            return all_items

        except APIResponseError as e:
            print(f"[ERROR] Notion 取得エラー: {e}")
            return []


    # ------------------------------------------------------------------
    # 内部: ページ検索（名前ベース）
    # ------------------------------------------------------------------
    def _find_page_id(self, name: str) -> Optional[str]:
        """
        食材名で Notion を検索し、「在庫あり」の最初のページ ID を返す。
        URLエンコードエラーを避けるため search API を使用。
        """
        try:
            results = self._notion.search(
                query=name,
                filter={"property": "object", "value": "page"},
            )
            for page in results.get("results", []):
                # ステータスが「在庫あり」のものを優先
                try:
                    status = (
                        page.get("properties", {})
                        .get("ステータス", {})
                        .get("status", {})
                        .get("name", "")
                    )
                    title = self._get_title(page)
                    if title == name and status == "在庫あり":
                        return page["id"]
                except Exception:
                    continue

            # 厳密一致がなければ最初のヒットを返す
            pages = results.get("results", [])
            if pages:
                return pages[0]["id"]

            return None
        except APIResponseError as e:
            print(f"❌ Notion 検索エラー: {e}")
            return None

    # ------------------------------------------------------------------
    # 内部: ページ → dict 変換
    # ------------------------------------------------------------------
    @staticmethod
    def _page_to_item(page: dict) -> dict:
        """Notion ページオブジェクトを統一 dict 形式に変換する"""
        props = page.get("properties", {})

        # 名前
        name = ""
        title_prop = props.get("名前", {}).get("title", [])
        if title_prop:
            name = title_prop[0].get("text", {}).get("content", "")

        # 数量
        quantity = ""
        qty_prop = props.get("数量", {}).get("rich_text", [])
        if qty_prop:
            quantity = qty_prop[0].get("text", {}).get("content", "")

        # 保管場所
        location = ""
        loc_prop = props.get("保管場所", {}).get("select")
        if loc_prop:
            location = loc_prop.get("name", "")

        # 賞味期限目安
        expiry = ""
        exp_prop = props.get("賞味期限目安", {}).get("rich_text", [])
        if exp_prop:
            expiry = exp_prop[0].get("text", {}).get("content", "")

        return {
            "name": name,
            "quantity": quantity,
            "location": location,
            "expiry": expiry,
            "page_id": page.get("id", ""),
        }

    @staticmethod
    def _get_title(page: dict) -> str:
        """ページのタイトル（名前）を取得する"""
        props = page.get("properties", {})
        title_prop = props.get("名前", {}).get("title", [])
        if title_prop:
            return title_prop[0].get("text", {}).get("content", "")
        return ""


# ------------------------------------------------------------------
# 単体テスト
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    from config import NOTION_TOKEN, NOTION_DATABASE_ID
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("[ERROR] NOTION_TOKEN / NOTION_DATABASE_ID が設定されていません")
        exit(1)
    print("[OK] Notion 設定確認完了")

    notion = NotionSync()

    print("\n" + "=" * 50)
    print("【テスト1】食材追加")
    notion.add_item("テスト牛乳", "1本", "冷蔵室", "2026-09-30")
    notion.add_item("テスト卵", "10個", "冷蔵室", "2026-10-05")

    print("\n" + "=" * 50)
    print("【テスト2】在庫取得")
    inventory = notion.get_inventory()
    print(f"在庫数: {len(inventory)} 件")
    for item in inventory:
        print(f"  ・{item['name']} ({item['quantity']}) [{item['location']}] 期限:{item['expiry']}")

    print("\n" + "=" * 50)
    print("【テスト3】数量減算（卵2個使った）")
    r = notion.consume_item("テスト卵", "2個")
    print(r)

    print("\n" + "=" * 50)
    print("【テスト4】数量直接変更（テスト牛乳を3本に）")
    r = notion.set_quantity("テスト牛乳", "3本")
    print(r)

    print("\n" + "=" * 50)
    print("【テスト5】買い足し（テスト卵を6個追加）")
    r = notion.add_to_existing("テスト卵", "6個")
    print(r)

    print("\n" + "=" * 50)
    print("【テスト6】全量消費")
    r = notion.consume_item("テスト牛乳")
    print(r)

    print("\n" + "=" * 50)
    print("【テスト7】更新後の在庫取得")
    inventory = notion.get_inventory()
    print(f"在庫数: {len(inventory)} 件")
    for item in inventory:
        print(f"  ・{item['name']} ({item['quantity']}) [{item['location']}] 期限:{item['expiry']}")
