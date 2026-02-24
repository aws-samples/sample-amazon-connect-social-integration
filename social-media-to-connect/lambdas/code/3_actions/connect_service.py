import re
import logging
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()


def create_connect_task(
    record: Dict[str, Any],
    instance_id: str,
    contact_flow_id: str,
    connect_client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Create an Amazon Connect task from a social media post record.
    
    Optimized to dynamically process all attributes from the record,
    making it flexible for any post type and future field expansions.
    
    Args:
        record: DynamoDB record containing post data
        instance_id: Amazon Connect instance ID
        contact_flow_id: Contact flow ID for task routing
        connect_client: Optional boto3 Connect client (creates one if not provided)
        
    Returns:
        Dict containing the Connect API response
        
    Raises:
        Exception: If task creation fails
        
    Note:
        Queue routing is handled by the Contact Flow, not directly via the API.
    """
    if connect_client is None:
        connect_client = boto3.client('connect')
    
    # Extract essential fields
    post_id = record.get('id', 'unknown')
    post_type = record.get('type', 'unknown')
    
    # Get comment from llm_analysis.recommended_action or fallback to comment field
    llm_analysis = record.get('llm_analysis', {})
    comment = llm_analysis.get('recommended_action') or record.get('comment', '')
    
    # Create task name
    task_name = f"Social Media - {post_type.title()} - {post_id}"
    
    # Build task description
    description = _build_task_description(record, comment)
    
    # Build attributes and references
    attributes = _build_task_attributes(record)
    references = _build_task_references(record, comment)
    
    # Create the task
    try:
        task_params = {
            'InstanceId': instance_id,
            'ContactFlowId': contact_flow_id,
            'Name': task_name,
            'Description': description,
            'References': references,
            'Attributes': attributes
        }
        
        response = connect_client.start_task_contact(**task_params)
        logger.info(f"Created Connect task for post {post_id}: {response.get('ContactId')}")
        return response
        
    except ClientError as e:
        error_msg = f"Failed to create Connect task for post {post_id}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def _build_task_description(record: Dict[str, Any], comment: str) -> str:
    """Build dynamic task description from record fields."""
    lines = ["Social Media Post Analysis Required", ""]
    
    # Key fields to include in description
    field_mapping = {
        'id': 'Post ID',
        'type': 'Type',
        'external_fullname': 'Author',
        'external_name': 'Username',
        'created': 'Created',
        'sentiment': 'Sentiment',
        'language': 'Language',
        'location': 'Location',
        'status': 'Status',
        'is_pinned': 'Pinned'
    }
    
    for field, label in field_mapping.items():
        value = record.get(field)
        if value is not None and value != '':
            lines.append(_format_description_field(field, label, value))
    
    # Add LLM analysis if available
    llm_analysis = record.get('llm_analysis', {})
    if llm_analysis:
        lines.append("")
        lines.append("AI Analysis:")
        
        if 'message' in llm_analysis:
            lines.append(f"Summary: {llm_analysis['message']}")
        
        if 'priority' in llm_analysis:
            lines.append(f"Priority: {llm_analysis['priority']}")
        
        if 'requires_intervention' in llm_analysis:
            intervention = "Yes" if llm_analysis['requires_intervention'] else "No"
            lines.append(f"Requires Intervention: {intervention}")
    
    # Add comment/recommended action
    if comment:
        lines.extend(["", "Recommended Action:", comment])
    
    # Add permalink
    permalink = record.get('permalink') or record.get('post_link')
    if permalink:
        lines.extend(["", f"Permalink: {permalink}"])
    
    # Add Walls.io link
    wallsio_link = record.get('post_link_wallsio')
    if wallsio_link:
        lines.append(f"Walls.io Link: {wallsio_link}")
    
    lines.extend(["", "This task requires review and analysis of the social media post content."])
    
    return "\n".join(lines)


def _format_description_field(field: str, label: str, value: Any) -> str:
    """Format a field value for the description."""
    if field == 'type':
        return f"{label}: {str(value).title()}"
    elif field == 'status':
        return f"{label}: {'Active' if value else 'Inactive'}"
    elif field == 'is_pinned':
        return f"{label}: {'Yes' if value else 'No'}"
    else:
        return f"{label}: {value}"


def _build_task_attributes(record: Dict[str, Any]) -> Dict[str, str]:
    """Build dynamic attributes from record fields."""
    attributes = {'source': 'dynamodb_stream'}
    
    # Fields to exclude from attributes
    exclude_fields = {
        'processed', 'connect_task_created', 'connect_task_id',
        'ingestion_timestamp', 'source', 'llm_analysis'
    }
    
    # URL fields (added to references instead)
    url_fields = {
        'permalink', 'post_link', 'post_link_wallsio', 'userlink',
        'external_image', 'post_image', 'post_image_cdn',
        'post_video', 'post_video_cdn'
    }
    
    for field, value in record.items():
        # Skip excluded and URL fields
        if field in exclude_fields or field in url_fields:
            continue
        
        # Skip None values
        if value is None:
            continue
        
        # Handle source object
        if field == 'source' and isinstance(value, dict):
            _add_source_attributes(attributes, value)
            continue
        
        # Handle llm_analysis object
        if field == 'llm_analysis' and isinstance(value, dict):
            _add_llm_analysis_attributes(attributes, value)
            continue
        
        # Skip complex objects
        if isinstance(value, dict):
            continue
        
        # Handle lists
        if isinstance(value, list):
            if value and all(isinstance(item, (str, int, float, bool)) for item in value):
                attributes[field] = str(', '.join(str(item) for item in value))[:1024]
            continue
        
        # Handle long text fields by chunking
        str_value = str(value)
        if field == 'comment' and len(str_value) > 1024:
            _add_chunked_attribute(attributes, 'comment', str_value)
        else:
            # Truncate to 1024 chars (Connect attribute limit)
            attributes[field] = str_value[:1024]
    
    return attributes


def _add_source_attributes(attributes: Dict[str, str], source: Dict[str, Any]) -> None:
    """Extract key info from source object."""
    source_name = source.get('name') or source.get('username') or source.get('value')
    if source_name:
        attributes['source_name'] = str(source_name)[:1024]
    
    source_type = source.get('type')
    if source_type:
        attributes['source_type'] = str(source_type)[:1024]


def _add_llm_analysis_attributes(attributes: Dict[str, str], llm_analysis: Dict[str, Any]) -> None:
    """Extract key info from llm_analysis object."""
    if 'priority' in llm_analysis:
        attributes['llm_priority'] = str(llm_analysis['priority'])[:1024]
    
    if 'requires_intervention' in llm_analysis:
        attributes['llm_requires_intervention'] = str(llm_analysis['requires_intervention'])[:1024]
    
    if 'message' in llm_analysis:
        message = str(llm_analysis['message'])
        if len(message) > 1024:
            _add_chunked_attribute(attributes, 'llm_message', message)
        else:
            attributes['llm_message'] = message


def _add_chunked_attribute(attributes: Dict[str, str], field_name: str, value: str) -> None:
    """Add a long text field as chunked attributes."""
    chunk_size = 1000
    chunks = [value[i:i+chunk_size] for i in range(0, len(value), chunk_size)]
    
    for i, chunk in enumerate(chunks, 1):
        attributes[f'{field_name}_part_{i}'] = chunk
    
    attributes[f'{field_name}_parts_total'] = str(len(chunks))


def _build_task_references(record: Dict[str, Any], comment: str) -> Dict[str, Dict[str, str]]:
    """Build references for URLs and key identifiers."""
    post_id = record.get('id', 'unknown')
    post_type = record.get('type', 'unknown')
    
    references = {
        'post_id': {'Value': str(post_id), 'Type': 'STRING'},
        'post_type': {'Value': str(post_type), 'Type': 'STRING'}
    }
    
    # URL reference mapping
    url_mapping = {
        'permalink': 'permalink',
        'post_link': 'post_link',
        'post_link_wallsio': 'wallsio_link',
        'userlink': 'user_profile',
        'external_image': 'external_image',
        'post_image': 'post_image',
        'post_image_cdn': 'post_image_cdn',
        'post_video': 'post_video',
        'post_video_cdn': 'post_video_cdn'
    }
    
    for field, ref_name in url_mapping.items():
        value = record.get(field)
        if value and isinstance(value, str) and value.strip():
            if value.startswith(('http://', 'https://')):
                references[ref_name] = {'Value': value, 'Type': 'URL'}
    
    # Extract URLs from comment
    if comment:
        urls = re.findall(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            comment
        )
        if urls:
            references['comment_url'] = {'Value': urls[0], 'Type': 'URL'}
    
    return references
