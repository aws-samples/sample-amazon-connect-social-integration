import os
import logging
import json
import boto3
from record_parser import parse_dynamodb_record
from agent_class import create_agent_service_from_config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')


def save_to_dynamodb(table_name: str, record: dict):
    """
    Save processed record to DynamoDB table.
    
    Args:
        table_name: Name of the DynamoDB table
        record: Processed record to save
    """
    try:
        table = dynamodb.Table(table_name) # type: ignore
        table.put_item(Item=record)
        logger.info(f"Successfully saved record {record.get('id')} to {table_name}")
    except Exception as e:
        logger.error(f"Failed to save record {record.get('id')} to DynamoDB: {str(e)}")
        raise


def lambda_handler(event, context):
    logger.info(f"Received event with {len(event.get('Records', []))} records")
    
    # Get environment variables
    table_name = os.environ.get('TABLE_NAME')
    if not table_name:
        logger.error("TABLE_NAME environment variable not set")
        raise ValueError("TABLE_NAME environment variable is required")
    
    # Initialize agent service from config
    agent_service = create_agent_service_from_config()
    
    processed_count = 0
    failed_count = 0
    
    for record in event.get('Records', []):
        try:
            # Only process INSERT events
            if record.get('eventName') != 'INSERT':
                logger.info(f"Skipping {record.get('eventName')} event for record {record.get('eventID')}")
                continue
                
            # Parse DynamoDB stream record
            parsed_record = parse_dynamodb_record(record)
            
            if not parsed_record:
                logger.warning(f"Skipping record {record.get('eventID')} - no data to process")
                continue
            
            # Get comment for LLM analysis
            comment = parsed_record.get('comment')
            
            # Perform LLM analysis if agent service is available and comment exists
            if agent_service and comment:
                try:
                    logger.info(f"Analyzing comment for record {parsed_record['id']}")
                    result = agent_service.invoke(comment)
                    result_json = json.loads(result.model_dump_json())
                    parsed_record['llm_analysis'] = result_json
                    logger.info(f"LLM analysis completed for record {parsed_record['id']}")
                except Exception as e:
                    logger.error(f"LLM analysis failed for record {parsed_record['id']}: {str(e)}")
                    # Continue processing without LLM analysis
                    parsed_record['llm_analysis'] = None
            else:
                if not agent_service:
                    logger.info("Agent service not available - skipping LLM analysis")
                if not comment:
                    logger.info(f"No comment found for record {parsed_record['id']} - skipping LLM analysis")
                parsed_record['llm_analysis'] = None
            
            # Save to DynamoDB
            save_to_dynamodb(table_name, parsed_record)
            processed_count += 1
            logger.info(f"Successfully processed record: {parsed_record['id']}")
            
        except Exception as e:
            logger.error(f"Error processing record {record.get('eventID')}: {str(e)}")
            failed_count += 1
            continue
    
    logger.info(f"Processing complete - Success: {processed_count}, Failed: {failed_count}")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed_count': processed_count,
            'failed_count': failed_count,
            'total_records': len(event.get('Records', []))
        })
    }
