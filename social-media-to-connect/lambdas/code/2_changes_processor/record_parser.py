import logging
from boto3.dynamodb.types import TypeDeserializer

logger = logging.getLogger()
deserializer = TypeDeserializer()


def unmarshall_dynamodb_item(dynamodb_item):
    """
    Unmarshall a DynamoDB item from DynamoDB JSON format to Python dict.
    
    Args:
        dynamodb_item: DynamoDB item in DynamoDB JSON format
        
    Returns:
        dict: Unmarshalled Python dictionary
    """
    if not dynamodb_item:
        return {}
    
    return {key: deserializer.deserialize(value) for key, value in dynamodb_item.items()}


def parse_dynamodb_record(record):
    """
    Parse a DynamoDB stream record and unmarshall the data.
    
    Args:
        record: DynamoDB stream record
        
    Returns:
        dict: Unmarshalled record with all fields
    """
    # Extract event metadata
    event_name = record.get('eventName')
    event_source = record.get('eventSource')
    event_id = record.get('eventID')
    
    logger.info(f"Processing {event_name} event from {event_source}")
    
    # Parse DynamoDB data
    dynamodb_data = record.get('dynamodb', {})
    new_image = dynamodb_data.get('NewImage', {})
    
    if not new_image:
        logger.warning(f"No NewImage found in record {event_id}")
        return None
    
    # Unmarshall the DynamoDB item to regular Python dict
    unmarshalled_record = unmarshall_dynamodb_item(new_image)
    
    # Add event metadata
    unmarshalled_record['event_id'] = event_id
    unmarshalled_record['event_name'] = event_name
    
    return unmarshalled_record
    