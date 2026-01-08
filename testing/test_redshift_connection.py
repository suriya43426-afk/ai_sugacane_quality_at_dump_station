import psycopg2
from datetime import datetime
import sys
import socket

# Configuration
HOST = "mitrphol-redshift-prod.cgffftialzgr.ap-southeast-1.redshift.amazonaws.com"
PORT = 5439 # Use integer for socket
DB_NAME = "mitrphol_prod"
USER = "cane_quality_user"
PASS = "CaneQuality@Mitr2026"

# Table Name - (Assuming a reasonable name, please update if widely different)
TABLE_NAME = "ai_sugarcane_log" 

def check_port(host, port, timeout=5):
    try:
        print(f"[DEBUG] Checking if port {port} is open on {host}...")
        with socket.create_connection((host, port), timeout=timeout):
            print(f"[DEBUG] Port {port} is OPEN.")
            return True
    except socket.timeout:
        print(f"[DEBUG] Port {port} check TIMED OUT (likely blocked or no route).")
        return False
    except Exception as e:
        print(f"[DEBUG] Port {port} check FAILED: {e}")
        return False

def test_connection():
    print("="*50)
    print("AWS Redshift Connection Test")
    print("="*50)
    
    # Pre-check port reachability
    if not check_port(HOST, PORT):
        print("\n[CRITICAL] Cannot reach Redshift server on port 5439.")
        print("Possible causes:")
        print("1. Your PC is not on the same network/VPN as Redshift.")
        print("2. Port 5439 is blocked by a Firewall (PC or Network).")
        print("3. The hostname resolved to a private IP (10.x.x.x) which is not reachable.")
        return

    conn = None
    try:
        print(f"[INFO] Connecting to {HOST} via psycopg2...")
        conn = psycopg2.connect(
            host=HOST,
            port=PORT,
            dbname=DB_NAME,
            user=USER,
            password=PASS
        )
        print("[SUCCESS] Connection established!")
        
        # Cursor for executing queries
        cur = conn.cursor()
        
        # Dummy Data
        now = datetime.now()
        data = {
            'Factory': 'MDC',
            'Milling_Process': 'A',
            'Dump_No': 1,
            'Plate': '88-8888',
            'ai_result': 5,
            'datetime': now.strftime("%Y-%m-%d %H:%M:%S"),
            'timestamp': now
        }
        
        print(f"[INFO] Preparing to insert data: {data}")
        
        # INSERT Query
        # Note: Adjust column names if they differ in the actual database
        query = f"""
            INSERT INTO {TABLE_NAME} (Factory, Milling_Process, Dump_No, Plate, ai_result, datetime, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        # Try to execute - catch table not found error specially
        try:
            cur.execute(query, (
                data['Factory'], 
                data['Milling_Process'], 
                data['Dump_No'], 
                data['Plate'], 
                data['ai_result'],
                data['datetime'],
                data['timestamp']
            ))
            
            # Commit the transaction
            conn.commit()
            print("[SUCCESS] Data inserted and committed successfully.")
            
        except psycopg2.errors.UndefinedTable:
            print(f"[ERROR] Table '{TABLE_NAME}' does not exist.")
            print("Please check the correct table name in the Redshift database.")
            conn.rollback() # Rollback the failed transaction
            
        except Exception as e:
            print(f"[ERROR] Insert failed: {e}")
            conn.rollback()
            
        # Optional: Verify by selecting back (if needed)
        # cur.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY created_at DESC LIMIT 1")
        # print("Latest row:", cur.fetchone())
        
        cur.close()
        
    except Exception as e:
        print(f"[CRITICAL] Connection failed: {e}")
    finally:
        if conn:
            conn.close()
            print("[INFO] Connection closed.")
            
if __name__ == "__main__":
    test_connection()
