import sqlite3
import os
import sys
from datetime import datetime

def check_status():
    # Database is expected to be in the same directory or project root
    db_path = "sugarcane.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at: {os.path.abspath(db_path)}")
        return

    print(f"📂 Connected to Database: {os.path.abspath(db_path)}")
    print("-" * 50)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Overview Stats
        cursor.execute("SELECT COUNT(*) FROM processing_logs")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM processing_logs WHERE uploaded_at IS NOT NULL")
        uploaded = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM processing_logs WHERE uploaded_at IS NULL")
        pending = cursor.fetchone()[0]
        
        print(f"📊 Summary Statistics:")
        print(f"   Total Records:  {total}")
        print(f"   ✅ Uploaded:    {uploaded}")
        print(f"   ⏳ Pending:     {pending}")
        print("-" * 50)
        
        # 2. Latest Uploaded
        print("📨 Latest 5 Uploaded Items:")
        cursor.execute("""
            SELECT id, timestamp, factory_code, lane_number, plate_number, uploaded_at 
            FROM processing_logs 
            WHERE uploaded_at IS NOT NULL 
            ORDER BY uploaded_at DESC 
            LIMIT 5
        """)
        rows = cursor.fetchall()
        if rows:
            print(f"   {'ID':<5} | {'Timestamp':<20} | {'Lane':<4} | {'Plate':<10} | {'Uploaded At'}")
            for r in rows:
                print(f"   {r[0]:<5} | {r[1]:<20} | {r[3]:<4} | {r[4]:<10} | {r[5]}")
        else:
            print("   (No uploads yet)")
            
        print("-" * 50)

        # 3. Oldest Pending
        print("🚧 Oldest 5 Pending Items (Waiting Queue):")
        cursor.execute("""
            SELECT id, timestamp, factory_code, lane_number, plate_number 
            FROM processing_logs 
            WHERE uploaded_at IS NULL 
            ORDER BY timestamp ASC 
            LIMIT 5
        """)
        rows = cursor.fetchall()
        if rows:
            print(f"   {'ID':<5} | {'Timestamp':<20} | {'Lane':<4} | {'Plate':<10}")
            for r in rows:
                print(f"   {r[0]:<5} | {r[1]:<20} | {r[3]:<4} | {r[4]:<10}")
        else:
            print("   (Queue is empty - All synced!)")
            
        print("=" * 50)
        conn.close()

    except Exception as e:
        print(f"❌ Error querying database: {e}")

if __name__ == "__main__":
    check_status()
    input("\nPress Enter to exit...")
