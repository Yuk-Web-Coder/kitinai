import time
print("Notion インデックス反映待機中 (8秒)...")
time.sleep(8)
from modules.notion_sync import NotionSync
n = NotionSync()
inv = n.get_inventory()
print(f"在庫確認: {len(inv)} 件")
for item in inv:
    expiry = item["expiry"]
    exp_str = f" 期限:{expiry}" if expiry else ""
    name = item["name"]
    qty = item["quantity"]
    loc = item["location"]
    print(f"  {name} ({qty}) [{loc}]{exp_str}")
