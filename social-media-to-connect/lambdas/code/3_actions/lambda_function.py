import os
import logging
import json
import boto3
from typing import Dict, Any

from config_service import get_ssm_parameter
from record_parser import parse_dynamodb_record
from connect_service import create_connect_task
from table_service import TableService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
connect_client = boto3.client('connect')


def lambda_handler(event, context):
    """
    Process DynamoDB stream records and create Amazon Connect tasks
    for posts that require intervention.
    """
    logger.info(f"Processing {len(event.get('Records', []))} records")
    
    # Get Connect configuration
    connect_config_param = os.environ.get('CONNECT_CONFIG_PARAM_NAME')
    if not connect_config_param:
        raise ValueError("CONNECT_CONFIG_PARAM_NAME environment variable not set")
    
    try:
        config = get_ssm_parameter(connect_config_param)
        connect_config = config.get('connect_config', {})
        instance_id = connect_config.get('instance_id')
        contact_flow_id = connect_config.get('contact_flow_id')
        
        if not instance_id or not contact_flow_id:
            raise ValueError("Missing instance_id or contact_flow_id in configuration")
        
        logger.info(f"Using Connect instance: {instance_id}")
        
    except Exception as e:
        logger.error(f"Failed to load Connect configuration: {str(e)}")
        raise
    
    # Get table name for updates
    table_service = None
    if os.environ.get('TABLE_NAME'):
        table_service = TableService()
        logger.info(f"Initialized TableService for table: {os.environ.get('TABLE_NAME')}")
    else:
        logger.warning("TABLE_NAME not set, task status updates will be skipped")
    
    # Process each record
    results = {
        'processed': 0,
        'skipped': 0,
        'created': 0,
        'failed': 0,
        'errors': []
    }
    
    for record in event.get('Records', []):
        try:
            # Parse the DynamoDB record
            if record.get('eventName') != 'INSERT':
                logger.info(f"Skipping {record.get('eventName')} event for record {record.get('eventID')}")
                continue
            parsed_record = parse_dynamodb_record(record)
            
            if not parsed_record:
                logger.warning("Skipping record with no NewImage")
                results['skipped'] += 1
                continue
            
            post_id = parsed_record.get('id', 'unknown')
            results['processed'] += 1
            
            # Check if intervention is required
            if not should_create_task(parsed_record):
                logger.info(f"Post {post_id} does not require intervention, skipping")
                results['skipped'] += 1
                continue
            
            # Create Connect task
            logger.info(f"Creating Connect task for post {post_id}")
            response = create_connect_task(
                record=parsed_record,
                instance_id=instance_id,
                contact_flow_id=contact_flow_id,
                connect_client=connect_client
            )
            
            contact_id = response.get('ContactId')
            results['created'] += 1
            
            # Update DynamoDB with task info
            if table_service:
                try:
                    key = {
                        'id': post_id,
                        'created_timestamp': parsed_record.get('created_timestamp')
                    }
                    details = {
                        'connect_task_created': True,
                        'connect_task_id': contact_id
                    }
                    table_service.update(key, details)
                    logger.info(f"Updated task status for post {post_id}")
                except Exception as e:
                    logger.error(f"Failed to update task status for post {post_id}: {str(e)}")
            
        except Exception as e:
            error_msg = f"Failed to process record: {str(e)}"
            logger.error(error_msg)
            results['failed'] += 1
            results['errors'].append(error_msg)
    
    logger.info(f"Processing complete: {json.dumps(results)}")
    
    return {"batchItemFailures": []}

def should_create_task(record: Dict[str, Any]) -> bool:
    """
    Determine if a Connect task should be created for this record.
    
    Logic:
    - If llm_analysis exists, check requires_intervention
    - If llm_analysis doesn't exist, process the record (create task)
    
    Args:
        record: Parsed DynamoDB record
        
    Returns:
        bool: True if task should be created, False otherwise
    """
    llm_analysis = record.get('llm_analysis')
    
    # If no llm_analysis, process the record
    if not llm_analysis:
        logger.info("No llm_analysis found, creating task")
        return True
    
    # If llm_analysis exists, check requires_intervention
    requires_intervention = llm_analysis.get('requires_intervention', False)
    
    if requires_intervention:
        logger.info("llm_analysis indicates intervention required")
        return True
    else:
        logger.info("llm_analysis indicates no intervention required")
        return False
