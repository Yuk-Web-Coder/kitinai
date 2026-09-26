# -*- coding: utf-8 -*-
"""
modules/line_server.py - LINE Messaging API Webhook Web Server
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import os
import threading
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent
)

from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from modules.notion_sync import NotionSync
from modules.ai_parser import AIParser

app = Flask(__name__)

# LINE SDK 設定
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def get_services():
    """Notion と AIParser を遅延初期化して返す"""
    global _notion, _ai_parser
    if _notion is None:
        _notion = NotionSync()
    if _ai_parser is None:
        _ai_parser = AIParser()
    return _notion, _ai_parser


@app.route("/callback", methods=['POST'])
def callback():
    """LINEからのWebhookリクエストを受信"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[LINE ERROR] 署名検証に失敗しました。Channel Secretを確認してください。")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    """テキストメッセージの受信処理"""
    user_text = event.message.text.strip()
    print(f"📩 [LINE 受信]: {user_text}")

    notion, ai_parser = get_services()


    # キーワード判定: 在庫一覧
    if user_text in ["在庫", "リスト", "在庫一覧", "中身"]:
        inventory = _notion.get_inventory()
        if not inventory:
            reply_text(event.reply_token, "📦 現在の冷蔵庫は空っぽです。")
            return
        lines = ["📦 【現在の在庫一覧】"]
        for item in inventory:
            exp = f" (賞味期限: {item['expiry']})" if item.get('expiry') else ""
            lines.append(f"・{item['name']}: {item['quantity']} [{item['location']}]{exp}")
        reply_text(event.reply_token, "\n".join(lines))
        return

    # キーワード判定: レシピ提案
    if user_text in ["レシピ", "おすすめ", "何作れる？", "今日のごはん"]:
        inventory = _notion.get_inventory()
        suggestion = _ai_parser.generate_recipe_suggestion(inventory)
        reply_text(event.reply_token, f"🍳 【AIレシピ提案】\n\n{suggestion}")
        return

    # キーワード判定: 買い物リスト
    if user_text in ["買い物", "買い物リスト", "買うもの", "必要なもの", "買いたいもの"]:
        shopping_list = _notion.get_shopping_list()
        if not shopping_list:
            reply_text(event.reply_token, "🛒 買い物リストは空です！全て揃っています。")
            return
        lines = ["🛒 【買い物リスト（要購入）】"]
        for item in shopping_list:
            qty_info = f" ({item['quantity']})" if item.get('quantity') else ""
            lines.append(f"・{item['name']}{qty_info}")
        lines.append("\n💡 買ってきたら「〇〇買った」と送信すると、自動で在庫に追加されます！")
        reply_text(event.reply_token, "\n".join(lines))
        return

    # 自然言語解析処理
    try:
        inventory = _notion.get_inventory()
        parse_res = _ai_parser.parse_user_input(user_text, inventory)
        action = parse_res.get("action", "unknown")
        items = parse_res.get("items", [])
        msg = parse_res.get("message", "")

        reply_msg = ""

        if action == "suggest_recipe":
            suggestion = _ai_parser.generate_recipe_suggestion(inventory)
            reply_msg = f"🍳 【AIレシピ提案】\n\n{suggestion}"

        elif action == "shopping_list":
            shopping_list = _notion.get_shopping_list()
            if not shopping_list:
                reply_msg = "🛒 買い物リストは空です！全て揃っています。"
            else:
                lines = ["🛒 【買い物リスト（要購入）】"]
                for item in shopping_list:
                    qty_info = f" ({item['quantity']})" if item.get('quantity') else ""
                    lines.append(f"・{item['name']}{qty_info}")
                lines.append("\n💡 買ってきたら「〇〇買った」と送信すると、自動で在庫に追加されます！")
                reply_msg = "\n".join(lines)

        elif action == "add_shopping_list":
            added_list = []
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                qty = item.get("quantity", "1個")
                _notion.add_to_shopping_list(name, qty)
                added_list.append(f"・{name} ({qty})")
            if added_list:
                reply_msg = "🛒 以下の食材を買い物リストに追加しました！\n" + "\n".join(added_list)
            else:
                reply_msg = "買い物リストに追加できませんでした。"

        elif action in ["add", "restock"]:
            added_names = []
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                qty = item.get("quantity", "1個")
                loc = item.get("location", "冷蔵室")
                exp = item.get("expiry", "")
                _notion.add_item(name=name, quantity=qty, location=loc, expiry=exp)
                added_names.append(f"・{name} ({qty})")
            
            if added_names:
                reply_msg = f"✅ 以下の食材を追加・補充しました！（買い物リストから自動削除）\n" + "\n".join(added_names)
            else:
                reply_msg = msg or "食材を追加できませんでした。"

        elif action == "consume":
            consumed_names = []
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                used_qty = item.get("quantity", "")
                res = _notion.consume_item(name=name, amount=used_qty)
                if res.get("action") == "finished":
                    consumed_names.append(f"・{name} (使い切ったため買い物リストへ追加されました)")
                else:
                    rem = res.get("remaining", "")
                    consumed_names.append(f"・{name} (残り {rem})")
            
            if consumed_names:
                reply_msg = f"🍽️ 以下の食材を使いました！\n" + "\n".join(consumed_names)
            else:
                reply_msg = msg or "対象の食材が見つかりませんでした。"

        elif action == "set_quantity":
            updated = []
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                new_qty = item.get("quantity", "1")
                res = _notion.set_quantity(name=name, new_quantity=new_qty)
                if res.get("success"):
                    updated.append(f"・{name} → {new_qty}")
            if updated:
                reply_msg = f"✏️ 数量を変更しました:\n" + "\n".join(updated)
            else:
                reply_msg = "対象の食材が見つかりませんでした。"

        else:
            reply_msg = msg or "すみません、よく理解できませんでした。「牛肉200g買った」「卵1個使った」「買い物リスト」など話しかけてみてください！"

        reply_text(event.reply_token, reply_msg)

    except Exception as e:
        print(f"❌ LINE メッセージ処理エラー: {e}")
        reply_text(event.reply_token, f"処理中にエラーが発生しました: {e}")


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event: MessageEvent):
    """画像（レシート）メッセージの受信処理"""
    print("📷 [LINE 受信]: 画像を受信しました。レシート解析を開始します...")

    notion, ai_parser = get_services()

    try:
        # LINE サーバーから画像バイナリを取得
        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            message_content = line_bot_blob_api.get_message_content(message_id=event.message.id)

        image_bytes = message_content

        # Gemini でレシート解析
        res = ai_parser.parse_receipt_image(image_bytes, mime_type="image/jpeg")
        items = res.get("items", [])

        if not items:
            reply_text(event.reply_token, "🧾 レシートから食品を検出できませんでした。別の画像でお試しください。")
            return

        added_list = []
        for item in items:
            name = item.get("name")
            if not name:
                continue
            qty = item.get("quantity", "1個")
            loc = item.get("location", "冷蔵室")
            exp = item.get("expiry", "")
            notion.add_item(name=name, quantity=qty, location=loc, expiry=exp)
            added_list.append(f"・{name} ({qty}) [{loc}]")

        if added_list:
            msg = f"🧾 レシートから{len(added_list)}点の食材を自動登録しました！\n\n" + "\n".join(added_list)
        else:
            msg = "食材の登録に失敗しました。"

        reply_text(event.reply_token, msg)

    except Exception as e:
        print(f"❌ レシート画像処理エラー: {e}")
        reply_text(event.reply_token, f"レシート画像の処理中にエラーが発生しました: {e}")


def reply_text(reply_token: str, text: str):
    """LINEへの返信ヘルパー"""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=text)]
                )
            )
    except Exception as e:
        print(f"❌ LINE 返信送信エラー: {e}")


def run_server(port: int = None):
    """Flask サーバーを起動"""
    if port is None:
        port = int(os.environ.get("PORT", 5000))
    print(f"🚀 LINE Webhook Web サーバーをポート {port} で起動します...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)



def start_line_server_thread(notion: NotionSync, ai_parser: AIParser, port: int = 5000):
    """バックグラウンドスレッドでLINE Webhook サーバーを開始"""
    init_services(notion, ai_parser)
    thread = threading.Thread(target=run_server, kwargs={"port": port}, daemon=True)
    thread.start()
    print(f"🌐 LINE Webhook スレッドを開始しました (Port: {port})")
    return thread


if __name__ == "__main__":
    from modules.notion_sync import NotionSync
    from modules.ai_parser import AIParser
    
    n = NotionSync()
    a = AIParser()
    init_services(n, a)
    run_server(5000)
