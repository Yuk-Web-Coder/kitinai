"""
test_flow.py - 全画面切り替え動作の自動テストスクリプト
"""
import os
import sys
from modules.notion_sync import NotionSync
from modules.ai_parser import AIParser
from modules.display import DisplayManager

def run_test():
    print("\n🧪 --- KitchenAI 動作テスト開始 ---\n")
    
    notion = NotionSync()
    ai = AIParser()
    display = DisplayManager()
    
    # 1. 現在の在庫を取得して在庫画面を表示
    print("1️⃣ 在庫を取得して [在庫一覧画面] を生成...")
    inventory = notion.get_inventory()
    display.update(inventory, mode="inventory")
    print("   -> 在庫画面 プレビュー保存完了")
    
    # 2. レシピ提案の解析 & 全画面切り替え
    print("\n2️⃣ レシピ提案テスト...")
    user_input = "賞味期限が近いもので何かレシピ教えて"
    parsed = ai.parse_user_input(user_input, inventory)
    print(f"   解析結果: action={parsed.get('action')}")
    
    if parsed.get("action") == "suggest_recipe":
        recipe = ai.generate_recipe_suggestion(inventory)
        print(f"   生成レシピ:\n{recipe[:100]}...\n")
        display.update(inventory, recipe=recipe, mode="recipe")
        print("   -> [レシピ画面] プレビュー保存完了")
    
    # 3. 消費アクション後の自動復帰テスト
    print("\n3️⃣ 食材消費テスト（在庫画面へ復帰）...")
    user_input2 = "卵1個使ったよ"
    parsed2 = ai.parse_user_input(user_input2, inventory)
    print(f"   解析結果: action={parsed2.get('action')}, items={parsed2.get('items')}")
    
    if parsed2.get("action") == "consume":
        for item in parsed2.get("items", []):
            name = item.get("name")
            qty = item.get("quantity")
            if name and qty:
                res = notion.consume_item(name, qty)
                print(f"   Notion更新結果: {res}")
        
        # 最新の在庫を取得して在庫画面に戻る
        updated_inv = notion.get_inventory()
        display.update(updated_inv, mode="inventory")
        print("   -> [在庫一覧画面] へ復帰・プレビュー更新完了")

    print("\n✅ 全テスト完了！")

if __name__ == "__main__":
    run_test()
