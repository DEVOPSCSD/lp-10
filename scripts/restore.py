import os
import shutil
import glob

backup_files = glob.glob("backups/orders_backup_*.json")

if not backup_files:
    print("NO BACKUP FOUND")
    exit()

latest_backup = max(backup_files, key=os.path.getmtime)

original_file = "data/orders.json"

shutil.copy(latest_backup, original_file)

print("================================")
print("RESTORE SUCCESSFUL")
print("================================")
print("Backup file   :", latest_backup)
print("Restored file :", original_file)
print("================================")