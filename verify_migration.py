import os
import sys
from source.database import DatabaseManager

# Setup correct path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

def verify_real_import():
    # Paths
    root = os.getcwd()
    db_path = os.path.join(root, "sugarcane.db")
    csv_path = os.path.join(root, "factory_code_list.csv")
    
    print(f"DB Path: {db_path}")
    print(f"CSV Path: {csv_path}")
    
    # Init DB
    mgr = DatabaseManager(db_path)
    
    # Seed
    mgr.seed_factories_from_csv(csv_path)
    
    # Verify S01 (should be Surin)
    name = mgr.get_thai_factory_name("S01")
    print(f"S01 Name from DB: {name}")
    
    if "สุรินทร์" in name:
        print("VERIFICATION SUCCESS: Thai name loaded correctly.")
    else:
        print("VERIFICATION FAILED: Name mismatch or bad encoding.")

if __name__ == "__main__":
    verify_real_import()
