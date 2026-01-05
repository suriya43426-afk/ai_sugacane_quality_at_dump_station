import boto3
import json
import os
from datetime import datetime

# ==============================================================================
# CONFIGURATION
# ==============================================================================
REGION = "ap-southeast-1"
BUCKET_NAME = "mitrphol-ai-sugarcane-data-lake"
TABLE_LOCATION = f"tables/sugarcane_monitoring_log"
IMAGE_FOLDER = "images"

def test_integration():
    print("="*60)
    print("PC Agent -> Data Lake Integration Test")
    print("="*60)

    # Use environment variables or default session
    # (Provided by CLI in this session)
    s3 = boto3.client('s3', region_name=REGION)
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    
    # 1. Prepare Mock Image (Dummy JPG)
    local_image_path = "mock_sugarcane.jpg"
    with open(local_image_path, "wb") as f:
        f.write(b"\xFF\xD8\xFF\xE0" + os.urandom(100) + b"\xFF\xD9") # Fake JPEG headers
    
    s3_image_key = f"{IMAGE_FOLDER}/MDC/{now.strftime('%Y-%m-%d')}/truck_88-8888_{timestamp_str}.jpg"
    
    # 2. Upload Image to S3
    print(f"[1] Uploading image to S3: {s3_image_key}")
    try:
        s3.upload_file(local_image_path, BUCKET_NAME, s3_image_key)
        image_url = f"s3://{BUCKET_NAME}/{s3_image_key}"
        print(f"    SUCCESS: Image uploaded.")
    except Exception as e:
        print(f"    ERROR: Image upload failed: {e}")
        return

    # 3. Create JSON Record (Matching Glue Table Schema)
    log_record = {
        "factory": "MDC",
        "process": "A",
        "dump_no": 1,
        "plate": "88-8888",
        "ai_result": 5,
        "captured_at": now.isoformat() + "Z",
        "image_s3_path": image_url,
        "agent_id": "M4-PRO-MAX-TEST"
    }
    
    # Save JSON locally first
    local_json_path = "log_entry.json"
    with open(local_json_path, "w") as f:
        json.dump(log_record, f)
    
    # 4. Upload JSON to Table Location
    # Each JSON file represents a record in our JSON SerDe table
    s3_json_key = f"{TABLE_LOCATION}/log_{timestamp_str}.json"
    print(f"[2] Uploading JSON record to: {s3_json_key}")
    try:
        s3.upload_file(local_json_path, BUCKET_NAME, s3_json_key)
        print(f"    SUCCESS: Data record created.")
    except Exception as e:
        print(f"    ERROR: JSON upload failed: {e}")
        return

    print("\n" + "="*60)
    print("INTEGRATION SUCCESSFUL!")
    print(f"Verify in S3: https://s3.console.aws.amazon.com/s3/buckets/{BUCKET_NAME}")
    print(f"Verify in Athena: SELECT * FROM sugarcane_monitoring_log")
    print("="*60)

    # Cleanup local files
    os.remove(local_image_path)
    os.remove(local_json_path)

if __name__ == "__main__":
    test_integration()