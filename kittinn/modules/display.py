"""
modules/display.py - E-ink ディスプレイ / PNG プレビュー出力

本番モード : Waveshare E-ink（SPI通信）で描画
モックモード: Pillow で display_preview.png を生成・保存
"""
import os
from datetime import datetime, date
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from config import MOCK_MODE, DISPLAY_PREVIEW_PATH, EXPIRY_WARNING_DAYS

# Waveshare ドライバの条件付きインポート
_epd_available = False
epd = None

if not MOCK_MODE:
    try:
        from waveshare_epd import epd7in5_V2 as _epd_module
        epd = _epd_module
        _epd_available = True
        print("🖥️  Waveshare E-ink ドライバ読み込み完了")
    except ImportError:
        print("⚠️  waveshare_epd が見つかりません → PNG プレビューにフォールバック")


# ------------------------------------------------------------------
# 定数
# ------------------------------------------------------------------
# E-ink 解像度（Waveshare 7.5inch V2）
EPD_WIDTH = 800
EPD_HEIGHT = 480

# カラーパレット（白黒 E-ink 向け）
COLOR_BLACK = 0
COLOR_WHITE = 255

# フォントサイズ
FONT_TITLE = 28
FONT_SECTION = 22
FONT_BODY = 18
FONT_SMALL = 14

# レイアウト
MARGIN = 20
DIVIDER_Y = 260  # 在庫 / レシピの境界 Y 座標


class DisplayManager:
    """ディスプレイ描画管理クラス"""

    def __init__(self):
        self._mock = MOCK_MODE or not _epd_available
        self._epd_instance = None

        if not self._mock:
            try:
                self._epd_instance = epd.EPD()
                self._epd_instance.init()
                self._epd_instance.Clear()
                print("✅ E-ink ディスプレイ初期化完了")
            except Exception as e:
                print(f"⚠️  E-ink 初期化失敗 ({e}) → PNG モードにフォールバック")
                self._mock = True
        else:
            print(f"🖥️  ディスプレイ: PNG プレビューモード ({DISPLAY_PREVIEW_PATH})")

    # ------------------------------------------------------------------
    # 公開: 画面更新
    # ------------------------------------------------------------------
    def update(self, inventory: list[dict], recipe: str = "", mode: str = "auto"):
        """
        用途に応じた全画面レイアウトで表示を更新する。

        Args:
            inventory: 在庫リスト [{"name", "quantity", "location", "expiry"}, ...]
            recipe   : レシピ提案テキスト
            mode     : "auto" | "inventory" | "recipe"
        """
        if mode == "auto":
            mode = "recipe" if recipe.strip() else "inventory"

        if mode == "recipe":
            img = self._render_recipe_page(recipe)
        else:
            img = self._render_inventory_page(inventory)

        if self._mock:
            img.save(DISPLAY_PREVIEW_PATH)
            print(f"🖼️  プレビュー保存: {os.path.abspath(DISPLAY_PREVIEW_PATH)} [モード: {mode}]")
        else:
            self._draw_epd(img)

    # ------------------------------------------------------------------
    # 内部: 在庫一覧 全画面描画
    # ------------------------------------------------------------------
    def _render_inventory_page(self, inventory: list[dict]) -> Image.Image:
        """在庫一覧を2列構成でゆったり描画する"""
        img = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), color=COLOR_WHITE)
        draw = ImageDraw.Draw(img)
        fonts = self._load_fonts()

        # ── ヘッダー ──────────────────────────────
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
        draw.rectangle([0, 0, EPD_WIDTH, 44], fill=COLOR_BLACK)
        draw.text(
            (MARGIN, 8),
            f"🍱 KitchenAI 在庫一覧  [{now_str}]",
            font=fonts["section"],
            fill=COLOR_WHITE,
        )

        # ── フッター ──────────────────────────────
        draw.rectangle([0, EPD_HEIGHT - 32, EPD_WIDTH, EPD_HEIGHT], fill=COLOR_BLACK)
        draw.text(
            (MARGIN, EPD_HEIGHT - 26),
            "💡 「今日何作れる？」と話しかけるとレシピ画面に切り替わります",
            font=fonts["small"],
            fill=COLOR_WHITE,
        )

        # ── メイン（2列レイアウト） ──────────────────
        if not inventory:
            draw.text((MARGIN, 100), "（在庫が登録されていません）", font=fonts["title"], fill=COLOR_BLACK)
            return img

        # 保管場所でグループ化
        grouped = {}
        for item in inventory:
            loc = item.get("location", "その他")
            grouped.setdefault(loc, []).append(item)

        # 左列: 冷蔵室, 冷凍室 / 右列: 棚, 調味料, その他
        col_left_locs = ["冷蔵室", "冷凍室"]
        col_right_locs = ["棚", "調味料", "その他"]

        # 左列の描画 (x: 20 -> 380)
        self._render_column_items(draw, grouped, col_left_locs, x_start=MARGIN, y_start=55, max_y=EPD_HEIGHT - 40, fonts=fonts)

        # 中央の縦区切り線
        draw.line([(395, 50), (395, EPD_HEIGHT - 38)], fill=COLOR_BLACK, width=1)

        # 右列の描画 (x: 410 -> 780)
        self._render_column_items(draw, grouped, col_right_locs, x_start=410, y_start=55, max_y=EPD_HEIGHT - 40, fonts=fonts)

        return img

    # ------------------------------------------------------------------
    # 内部: 列単位の在庫描画ヘルパー
    # ------------------------------------------------------------------
    def _render_column_items(self, draw: ImageDraw.ImageDraw, grouped: dict, locations: list[str], x_start: int, y_start: int, max_y: int, fonts: dict):
        y = y_start
        for loc in locations:
            if loc not in grouped:
                continue

            if y + 30 > max_y:
                break

            # カテゴリ見出し
            draw.rectangle([x_start, y, x_start + 360, y + 26], fill=COLOR_WHITE, outline=COLOR_BLACK, width=1)
            draw.text((x_start + 6, y + 2), f"▸ {loc}", font=fonts["section"], fill=COLOR_BLACK)
            y += 30

            for item in grouped[loc]:
                if y + 22 > max_y:
                    break

                name = item.get("name", "")
                qty = item.get("quantity", "")
                expiry = item.get("expiry", "")

                warn = ""
                if expiry:
                    try:
                        exp_date = date.fromisoformat(expiry)
                        days_left = (exp_date - date.today()).days
                        if days_left < 0:
                            warn = " [期限切れ!]"
                        elif days_left <= EXPIRY_WARNING_DAYS:
                            warn = f" [あと{days_left}日]"
                    except ValueError:
                        pass

                line = f"・{name}"
                if qty:
                    line += f" ({qty})"
                if warn:
                    line += warn
                elif expiry:
                    line += f" ({expiry[5:]})" # MM-DD 表示でコンパクトに

                draw.text((x_start + 10, y), line, font=fonts["body"], fill=COLOR_BLACK)
                y += 22
            y += 10

    # ------------------------------------------------------------------
    # 内部: レシピ提案 全画面描画
    # ------------------------------------------------------------------
    def _render_recipe_page(self, recipe: str) -> Image.Image:
        """本日のおすすめレシピを全画面で読みやすく描画する"""
        img = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), color=COLOR_WHITE)
        draw = ImageDraw.Draw(img)
        fonts = self._load_fonts()

        # ── ヘッダー ──────────────────────────────
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
        draw.rectangle([0, 0, EPD_WIDTH, 44], fill=COLOR_BLACK)
        draw.text(
            (MARGIN, 8),
            f"🍳 AIおすすめレシピ提案  [{now_str}]",
            font=fonts["section"],
            fill=COLOR_WHITE,
        )

        # ── フッター ──────────────────────────────
        draw.rectangle([0, EPD_HEIGHT - 32, EPD_WIDTH, EPD_HEIGHT], fill=COLOR_BLACK)
        draw.text(
            (MARGIN, EPD_HEIGHT - 26),
            "💡 食材の追加・消費などの操作を行うと在庫一覧画面に戻ります",
            font=fonts["small"],
            fill=COLOR_WHITE,
        )

        # ── 本文 ──────────────────────────────────
        y = 55
        lines = self._wrap_text(recipe, max_chars=42)
        for line in lines:
            if y > EPD_HEIGHT - 40:
                break
            
            # イチオシタイトルなどを強調
            if line.startswith("【") or line.startswith("■") or line.startswith("★"):
                draw.text((MARGIN, y), line, font=fonts["section"], fill=COLOR_BLACK)
                y += 28
            else:
                draw.text((MARGIN + 10, y), line, font=fonts["body"], fill=COLOR_BLACK)
                y += 24

        return img

    # ------------------------------------------------------------------
    # 内部: E-ink 描画
    # ------------------------------------------------------------------
    def _draw_epd(self, img: Image.Image):
        try:
            # E-ink は 1bit（白黒）に変換して送信
            bw_img = img.convert("1")
            self._epd_instance.display(self._epd_instance.getbuffer(bw_img))
            print("✅ E-ink 描画完了")
        except Exception as e:
            print(f"❌ E-ink 描画エラー: {e}")

    # ------------------------------------------------------------------
    # 内部: フォント読み込み
    # ------------------------------------------------------------------
    @staticmethod
    def _load_fonts() -> dict:
        """
        日本語対応フォントを読み込む。
        見つからない場合は Pillow デフォルトフォント使用。
        """
        # 日本語フォント候補（環境依存）
        jp_font_candidates = [
            "C:/Windows/Fonts/meiryo.ttc",          # Windows Meiryo
            "C:/Windows/Fonts/msgothic.ttc",         # Windows MS Gothic
            "/usr/share/fonts/truetype/takao-gothic/TakaoGothic.ttf",  # Linux
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",          # macOS
        ]

        font_path = None
        for candidate in jp_font_candidates:
            if os.path.exists(candidate):
                font_path = candidate
                break

        def load(size: int) -> ImageFont.ImageFont:
            if font_path:
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        return {
            "title": load(FONT_TITLE),
            "section": load(FONT_SECTION),
            "body": load(FONT_BODY),
            "small": load(FONT_SMALL),
        }

    # ------------------------------------------------------------------
    # 内部: テキスト折り返し
    # ------------------------------------------------------------------
    @staticmethod
    def _wrap_text(text: str, max_chars: int = 45) -> list[str]:
        """日本語テキストを指定文字数で折り返す"""
        lines = []
        for paragraph in text.split("\n"):
            if not paragraph.strip():
                lines.append("")
                continue
            while len(paragraph) > max_chars:
                lines.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            lines.append(paragraph)
        return lines

    # ------------------------------------------------------------------
    # 公開: クリーンアップ
    # ------------------------------------------------------------------
    def cleanup(self):
        """E-ink ディスプレイをクリアして省電力モードにする（本番のみ）"""
        if self._epd_instance:
            try:
                self._epd_instance.init()
                self._epd_instance.Clear()
                self._epd_instance.sleep()
                print("💤 E-ink スリープモード")
            except Exception as e:
                print(f"⚠️  E-ink クリーンアップエラー: {e}")


# ------------------------------------------------------------------
# 単体テスト
# ------------------------------------------------------------------
if __name__ == "__main__":
    display = DisplayManager()

    test_inventory = [
        {"name": "牛乳", "quantity": "1本", "location": "冷蔵室", "expiry": "2026-09-27"},
        {"name": "卵", "quantity": "8個", "location": "冷蔵室", "expiry": "2026-10-05"},
        {"name": "納豆", "quantity": "3パック", "location": "冷蔵室", "expiry": "2026-09-26"},
        {"name": "キャベツ", "quantity": "1個", "location": "冷蔵室", "expiry": "2026-10-01"},
        {"name": "玉ねぎ", "quantity": "3個", "location": "棚", "expiry": ""},
        {"name": "じゃがいも", "quantity": "4個", "location": "棚", "expiry": ""},
        {"name": "鶏もも肉", "quantity": "300g", "location": "冷凍室", "expiry": "2026-10-15"},
        {"name": "豚薄切り肉", "quantity": "200g", "location": "冷凍室", "expiry": "2026-10-10"},
        {"name": "醤油", "quantity": "1本", "location": "調味料", "expiry": ""},
        {"name": "みりん", "quantity": "1本", "location": "調味料", "expiry": ""},
    ]

    test_recipe = """【本日イチオシ】牛乳のクリームシチュー（調理時間: 30分 / 難易度: ★☆☆）
材料: 牛乳・鶏もも肉・玉ねぎ
作り方のポイント: 牛乳は最後に加えて沸騰させないのがコツ

【他のおすすめ】
・卵と玉ねぎの親子丼（調理時間: 15分）
・醤油チキンソテー（調理時間: 20分）"""

    print("1. 在庫画面テスト...")
    display.update(test_inventory, mode="inventory")

    print("2. レシピ画面テスト...")
    display.update(test_inventory, recipe=test_recipe, mode="recipe")

    print("テスト完了！display_preview.png を確認してください。")
