import os
import shutil
import json
from datetime import datetime

# Primary constants for standard backup
DATA_FILE = "data/orders.json"
BACKUP_DIR = "data/backups"
BACKUP_FILE = os.path.join(BACKUP_DIR, "latest_backup.json")

# Backwards-compatibility constants
SOURCE = DATA_FILE
BACKUP_FOLDER = "backups"


def perform_backup(source=SOURCE, backup_folder=BACKUP_FOLDER):
    """Creates a timestamped backup of the orders JSON file.

    Provided for backwards compatibility with legacy scripts and test suites.
    """
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

    # Only sync latest_backup.json when performing standard root backup
    if backup_folder == BACKUP_FOLDER:
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            shutil.copy2(source, BACKUP_FILE)
        except Exception:
            pass

    print("================================")
    print("BACKUP SUCCESSFUL")
    print("================================")
    print(f"Original file : {source}")
    print(f"Backup file   : {backup_file}")
    print("================================")
    return backup_file


def backup(data_file=DATA_FILE, backup_dir=BACKUP_DIR):
    """Creates latest backup and timestamped backup for disaster recovery."""
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(backup_dir, "latest_backup.json")

    if os.path.exists(data_file):
        shutil.copy(data_file, backup_file)
        print(f"[{datetime.now()}] Backup created successfully at {backup_file}")
        # Maintain timestamped backup in specified backup_dir
        perform_backup(source=data_file, backup_folder=backup_dir)
        if backup_dir == BACKUP_DIR and os.path.exists(BACKUP_FOLDER):
            perform_backup(source=data_file, backup_folder=BACKUP_FOLDER)
    else:
        # Create initial default backup if none exists
        sample_data = [{
            "name": "Seed Order",
            "mobile": "9999999999",
            "food": "Pizza",
            "quantity": "1",
            "date": str(datetime.now())
        }]
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f, indent=4)
        print(f"[{datetime.now()}] Initial seed backup created at {backup_file}")

    return backup_file


if __name__ == "__main__":
    backup()