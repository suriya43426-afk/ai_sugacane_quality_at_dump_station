import boto3
import time

def test_query():
    client = boto3.client('athena', region_name='ap-southeast-1')
    
    query = 'SELECT * FROM "mitrphol_sagemaker_db"."sugarcane_monitoring_log" LIMIT 10;'
    print(f"Running Query: {query}")
    
    # Start Query
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': 'mitrphol_sagemaker_db'},
        ResultConfiguration={'OutputLocation': 's3://mitrphol-ai-sugarcane-data-lake/athena-results/'}
    )
    query_execution_id = response['QueryExecutionId']
    print(f"Execution ID: {query_execution_id}")
    
    # Wait for result
    while True:
        stats = client.get_query_execution(QueryExecutionId=query_execution_id)
        status = stats['QueryExecution']['Status']['State']
        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
            break
        time.sleep(1)
    
    if status == 'SUCCEEDED':
        results = client.get_query_results(QueryExecutionId=query_execution_id)
        print("Query Succeeded!")
        # Print columns
        cols = [col['Label'] for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo']]
        print(f"Columns: {cols}")
        # Print rows
        for row in results['ResultSet']['Rows'][1:]: # Skip header
            data = [d.get('VarCharValue', 'NULL') for d in row['Data']]
            print(data)
    else:
        print(f"Query Failed: {stats['QueryExecution']['Status']['StateChangeReason']}")

if __name__ == "__main__":
    test_query()
