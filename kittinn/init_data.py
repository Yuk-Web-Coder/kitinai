from modules.notion_sync import NotionSync

n = NotionSync()

items = [
    ("牛乳",       "1本",   "冷蔵室", "2026-09-28"),
    ("卵",         "10個",  "冷蔵室", "2026-10-03"),
    ("豚バラ肉",   "200g",  "冷凍室", "2026-10-10"),
    ("玉ねぎ",     "3個",   "棚",     ""),
    ("醤油",       "1本",   "調味料", "2027-03-01"),
    ("にんじん",   "2本",   "冷蔵室", "2026-10-01"),
    ("ほうれん草", "1袋",   "冷蔵室", "2026-09-27"),
    ("カレールー", "1箱",   "棚",     "2027-06-01"),
    ("豆腐",       "1丁",   "冷蔵室", "2026-09-29"),
    ("鶏もも肉",   "300g",  "冷凍室", "2026-11-01"),
]

print("データ追加中...")
for name, qty, loc, exp in items:
    n.add_item(name, qty, loc, exp)

print()
print("=== 追加後の在庫（賞味期限順） ===")
inv = n.get_inventory()
for item in inv:
    expiry = item["expiry"]
    exp_str = f" 期限:{expiry}" if expiry else ""
    print(f"  {item['name']} ({item['quantity']}) [{item['location']}]{exp_str}")
print(f"\n合計 {len(inv)} 件")
