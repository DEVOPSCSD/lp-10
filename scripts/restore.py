import os
import sys

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from scripts.recover import restore_data
    has_recover = True
except ImportError:
    has_recover = False

if __name__ == "__main__":
    if has_recover:
        result = restore_data()
        if not result:
            sys.exit(1)
    else:
        import shutil
        import glob

        backup_files = (
            glob.glob("backups/orders_backup_*.json") +
            glob.glob("data/backups/latest_backup.json") +
            glob.glob("data/backups/orders_backup_*.json")
        )
        if not backup_files:
            print("NO BACKUP FOUND")
            sys.exit(1)

        latest_backup = max(backup_files, key=os.path.getmtime)
        original_file = "data/orders.json"
        os.makedirs(os.path.dirname(original_file), exist_ok=True)
        shutil.copy(latest_backup, original_file)

        print("================================")
        print("RESTORE SUCCESSFUL")
        print("================================")
        print("Backup file   :", latest_backup)
        print("Restored file :", original_file)
        print("================================")