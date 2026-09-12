import os
import shutil
from datetime import datetime

SOURCE = "data/orders.json"
BACKUP_FOLDER = "backups"


def perform_backup(source=SOURCE, backup_folder=BACKUP_FOLDER):
    """Creates a timestamped backup of the orders JSON file."""
    os.makedirs(backup_folder, exist_ok=True)

    if not os.path.exists(source):
        print("ERROR: orders.json not found.")
        print("Please place at least one test order first.")
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    backup_file = os.path.join(
        backup_folder,
        f"orders_backup_{timestamp}.json"
    )

    shutil.copy2(source, backup_file)

    print("================================")
    print("BACKUP SUCCESSFUL")
    print("================================")
    print(f"Original file : {source}")
    print(f"Backup file   : {backup_file}")
    print("================================")
    return backup_file


if __name__ == "__main__":
    perform_backup()