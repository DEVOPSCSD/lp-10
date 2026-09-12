import os
import shutil
from datetime import datetime

SOURCE = "data/orders.json"
BACKUP_FOLDER = "backups"

os.makedirs(BACKUP_FOLDER, exist_ok=True)

if not os.path.exists(SOURCE):
    print("ERROR: orders.json not found.")
    print("Please place at least one test order first.")
else:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    backup_file = os.path.join(
        BACKUP_FOLDER,
        f"orders_backup_{timestamp}.json"
    )

    shutil.copy2(SOURCE, backup_file)

    print("================================")
    print("BACKUP SUCCESSFUL")
    print("================================")
    print(f"Original file : {SOURCE}")
    print(f"Backup file   : {backup_file}")
    print("================================")