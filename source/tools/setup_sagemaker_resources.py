import boto3
import time
import json

# ==============================================================================
# CONFIGURATION
# ==============================================================================
REGION = "ap-southeast-1"
BUCKET_NAME = "mitrphol-ai-sugarcane-data-lake"  # Must be globally unique
DB_NAME = "mitrphol_sagemaker_db"
TABLE_NAME = "sugarcane_monitoring_log"

# Schema Definition (Matches our API Spec + S3 Image Path)
COLUMNS = [
    {"Name": "factory", "Type": "string"},
    {"Name": "process", "Type": "string"},
    {"Name": "dump_no", "Type": "int"},
    {"Name": "plate", "Type": "string"},
    {"Name": "ai_result", "Type": "int"},
    {"Name": "captured_at", "Type": "string"}, # ISO 8601
    {"Name": "image_s3_path", "Type": "string"}, # Link to image in S3
    {"Name": "agent_id", "Type": "string"}
]

def setup_resources():
    print(f"--- Setting up Resources in {REGION} ---")
    
    try:
        session = boto3.Session(region_name=REGION)
        # Validate credentials exist
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        print(f"[INFO] Authenticated as: {identity['Arn']}")
    except Exception as e:
        print("\n[CRITICAL ERROR] AWS Credentials not found!")
        print("Please run the following command in your terminal:")
        print("    aws configure")
        print("Then enter your Access Key, Secret Key, and Region (ap-southeast-1).")
        print(f"Error Details: {e}")
        return

    s3 = session.client('s3')
    glue = session.client('glue')

    # 1. Create S3 Bucket (Data Lake Storage)
    print(f"\n[1] Checking/Creating S3 Bucket: {BUCKET_NAME}")
    try:
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={'LocationConstraint': REGION}
        )
        print(f"    SUCCESS: Bucket '{BUCKET_NAME}' created.")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"    INFO: Bucket '{BUCKET_NAME}' already exists (owned by you).")
    except Exception as e:
        print(f"    ERROR: Could not create bucket: {e}")
        # Continue to Glue even if S3 fails - maybe the bucket exists or user lacks S3 but has Glue perms

    # 2. Create Glue Database
    print(f"\n[2] Checking/Creating Glue Database: {DB_NAME}")
    try:
        glue.create_database(
            DatabaseInput={'Name': DB_NAME, 'Description': 'Database for Sugarcane AI Logs'}
        )
        print(f"    SUCCESS: Database '{DB_NAME}' created.")
    except glue.exceptions.AlreadyExistsException:
        print(f"    INFO: Database '{DB_NAME}' already exists.")

    # 3. Create Glue Table (Manual & Robust)
    print(f"\n[3] Creating Glue Table: {TABLE_NAME}")
    try:
        # Delete first to ensure fresh metadata
        try:
            glue.delete_table(DatabaseName=DB_NAME, Name=TABLE_NAME)
            print(f"    INFO: Existing table deleted for refresh.")
        except glue.exceptions.EntityNotFoundException:
            pass

        glue.create_table(
            DatabaseName=DB_NAME,
            TableInput={
                'Name': TABLE_NAME,
                'StorageDescriptor': {
                    'Columns': COLUMNS,
                    'Location': f"s3://{BUCKET_NAME}/tables/{TABLE_NAME}/",
                    'InputFormat': 'org.apache.hadoop.mapred.TextInputFormat',
                    'OutputFormat': 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat',
                    'SerdeInfo': {
                        'SerializationLibrary': 'org.openx.data.jsonserde.JsonSerDe',
                        'Parameters': {
                            'ignore.malformed.json': 'TRUE', 
                            'dots.in.keys': 'FALSE', 
                            'case.insensitive': 'TRUE',
                            'mapping': 'TRUE'
                        }
                    }
                },
                'TableType': 'EXTERNAL_TABLE',
                'Parameters': {'classification': 'json'}
            }
        )
        print(f"    SUCCESS: Table '{TABLE_NAME}' created with OpenX SerDe.")
        
    except Exception as e:
        print(f"    ERROR: Create Table failed: {e}")

    print("\n-----------------------------------------------------------")
    print("SETUP COMPLETE!")
    print(f"Query now: SELECT * FROM {TABLE_NAME}")
    print("-----------------------------------------------------------")

# Removed Manual Fallback function since we are using it directly
# Removed Crawler logic

if __name__ == "__main__":
    setup_resources()
