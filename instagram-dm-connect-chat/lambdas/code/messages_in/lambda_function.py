## process Instagram webhook messages
import json
import os
import logging
from config_service import get_secret_value, get_ssm_parameter
from table_service import TableService
from instagram_service import InstagramService
from connect_chat_service import ChatService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from utils import build_response, validate_healthcheck

CHANNEL_NAME = "Instagram"


def get_contact(table_service, user_id):
    """Get contact from DynamoDB by user_id"""
    response = table_service.table.query(
        IndexName='byUser',
        KeyConditionExpression='userId = :userId',
        ExpressionAttributeValues={':userId': user_id}
    )
    if response.get("Items") and len(response['Items']) > 0:
        return response['Items'][0]
    return None


def text_message_handler(message, connect_chat_service, table_service, user_name, sender_profile):
    """
    Handle text message processing: look for existing contact and send message,
    or generate a new chat if contact doesn't exist.
    
    Args:
        message: Message object with sender_id, text, and message_type
        connect_chat_service: ChatService instance for AWS Connect operations
        table_service: TableService instance for DynamoDB operations
        user_name: Display name for the user
        sender_profile: Instagram profile data for the sender
        
    Returns:
        tuple: (contact_id, participant_token, connection_token) if successful, (None, None, None) otherwise
    """
    contact = get_contact(table_service, message.sender_id)
    
    if contact:
        logger.info(f"Found existing contact: {contact}")
        new_contact_id, new_participant_token, new_connection_token = (
            connect_chat_service.send_message_with_retry_connection(
                message=message.text,
                userId=message.sender_id,
                channel=CHANNEL_NAME,
                userName=user_name,
                connectionToken=contact["connectionToken"],
                systemNumber=None
            )
        )
        # Delete old contact if new one was created (connection retry)
        if new_contact_id:
            table_service.delete_item(key={"contactId": contact["contactId"]})
            return new_contact_id, new_participant_token, new_connection_token
        return None, None, None
    else:
        logger.info(f"New contact from: {message.sender_id}")
        logger.info(f"Text message: {message.text}")
        new_contact_id, new_participant_token, new_connection_token = (
            connect_chat_service.start_chat_and_stream(
                message=message.text or "New conversation with attachment",
                userId=message.sender_id,
                channel=CHANNEL_NAME,
                userName=user_name,
                systemNumber=None,
            )
        )
        return new_contact_id, new_participant_token, new_connection_token
def download_attachment(url):
    """Download attachment content from Instagram CDN URL.

    Args:
        url: The Instagram CDN URL for the attachment

    Returns:
        tuple: (file_bytes, content_type) or (None, None) on failure
    """
    # Validate URL scheme to prevent file:// or other dangerous schemes
    if not url or not url.startswith("https://"):
        logger.error(f"Invalid attachment URL scheme, only HTTPS is allowed: {url}")
        return None, None

    try:
        import urllib.request
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=15) as response:  # nosec: URL scheme validated above
            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            file_bytes = response.read()
            logger.info(f"Downloaded attachment: {len(file_bytes)} bytes, type: {content_type}")
            return file_bytes, content_type
    except Exception as e:
        logger.error(f"Failed to download attachment: {e}")
        return None, None


def get_attachment_filename(attachment):
    """Generate a filename based on attachment type.

    Args:
        attachment: Instagram attachment dict with 'type' and 'payload'

    Returns:
        str: Generated filename
    """
    att_type = attachment.get('type', 'file')
    extension_map = {
        'image': 'jpg',
        'video': 'mp4',
        'audio': 'mp3',
        'file': 'bin'
    }
    ext = extension_map.get(att_type, 'bin')
    return f"instagram_{att_type}.{ext}"


def attachment_message_handler(message, connect_chat_service, table_service, user_name, sender_profile):
    """
    Handle attachment message processing: ensure a chat contact exists,
    then upload each attachment to Connect.

    Args:
        message: InstagramMessage with attachments
        connect_chat_service: ChatService instance
        table_service: TableService instance
        user_name: Display name for the user
        sender_profile: Instagram profile data

    Returns:
        tuple: (contact_id, participant_token, connection_token)
    """
    contact = get_contact(table_service, message.sender_id)
    new_contact_id = None
    new_participant_token = None
    new_connection_token = None
    connection_token = None

    if contact:
        logger.info(f"Found existing contact for attachment: {contact['contactId']}")
        connection_token = contact["connectionToken"]
    else:
        # Start a new chat with a placeholder message describing the attachment
        att_types = [att.get('type', 'file') for att in message.attachments]
        initial_text = f"[Sent {', '.join(att_types)}]"
        logger.info(f"New contact from attachment: {message.sender_id}")

        new_contact_id, new_participant_token, new_connection_token = (
            connect_chat_service.start_chat_and_stream(
                message=initial_text,
                userId=message.sender_id,
                channel=CHANNEL_NAME,
                userName=user_name,
                systemNumber=None,
            )
        )
        connection_token = new_connection_token

    if not connection_token:
        logger.error("No connection token available for attachment upload")
        return new_contact_id, new_participant_token, new_connection_token

    # Upload each attachment to Connect
    for attachment in message.attachments:
        att_url = attachment.get('payload', {}).get('url')
        if not att_url:
            logger.warning(f"Attachment missing URL, skipping")
            continue

        file_bytes, content_type = download_attachment(att_url)
        if file_bytes is None:
            # Fallback: send the URL as a text message
            logger.warning("Could not download attachment, sending URL as text")
            connect_chat_service.send_message(
                f"[{attachment.get('type', 'file')} attachment]: {att_url}",
                connection_token
            )
            continue

        file_name = get_attachment_filename(attachment)
        att_type = attachment.get('type', 'file')

        # Use content_type from download, but override for known types if needed
        if att_type == 'image' and not content_type.startswith('image/'):
            content_type = 'image/jpeg'
        elif att_type == 'video' and not content_type.startswith('video/'):
            content_type = 'video/mp4'
        elif att_type == 'audio' and not content_type.startswith('audio/'):
            content_type = 'audio/mpeg'

        attachment_id, error = connect_chat_service.attach_file(
            fileContents=file_bytes,
            fileName=file_name,
            fileType=content_type,
            ConnectionToken=connection_token
        )

        if error:
            logger.error(f"Failed to upload attachment to Connect: {error}")
            # Fallback: send URL as text
            connect_chat_service.send_message(
                f"[{att_type} attachment]: {att_url}",
                connection_token
            )
        else:
            logger.info(f"Attachment uploaded to Connect: {attachment_id}")

    return new_contact_id, new_participant_token, new_connection_token


def lambda_handler(event, context):
    logger.info(event)
    
    try:
        # Initialize config service
        config = get_ssm_parameter(os.environ["CONFIG_PARAM_NAME"])
        instagram_account_id = config.get("instagram_account_id")

        # Handle GET request (webhook verification)
        if event['httpMethod'] == 'GET':
            return build_response(200, validate_healthcheck(event, config['INSTAGRAM_VERIFICATION_TOKEN']))
        
        # Handle POST request (webhook message)
        if event.get("body") is None:
            return build_response(200, "bye bye")
        
        body = json.loads(event['body'])
        logger.info(f"Received webhook body: {json.dumps(body)}")
        
        # Get Instagram access token
        access_token = get_secret_value(os.environ["SECRET_ARN"])
        
        # Initialize Instagram service with get_profiles=True to automatically fetch profiles
        instagram = InstagramService(body, access_token=access_token, get_profiles=True, instagram_account_id=instagram_account_id)
        
        logger.info(f"Parsed {instagram.get_message_count()} messages")
        
        # Initialize table service
        table_service = TableService()

        connect_chat_service = ChatService(
            instance_id=config.get("instance_id"), 
            contact_flow_id=config.get("contact_flow_id"),
            topic_arn=os.environ.get("TOPIC_ARN")
        )
        
        # Process all messages (text and attachments)
        for message in instagram.get_messages():
            logger.info(f"Processing {message.message_type} message from {message.sender_id}")
            user_name = message.sender_id
            
            # Get sender profile from cache (already fetched if get_profiles=True)
            sender_profile = instagram.user_profiles.get(message.sender_id)
            if sender_profile:
                logger.info(f"Sender profile: {sender_profile.get('username')} ({sender_profile.get('name')})")
                user_name = sender_profile.get('name')
            
            new_contact_id = None
            new_participant_token = None
            new_connection_token = None

            if message.message_type == "text":
                new_contact_id, new_participant_token, new_connection_token = text_message_handler(
                    message=message,
                    connect_chat_service=connect_chat_service,
                    table_service=table_service,
                    user_name=user_name,
                    sender_profile=sender_profile
                )
            elif message.message_type == "attachment":
                new_contact_id, new_participant_token, new_connection_token = attachment_message_handler(
                    message=message,
                    connect_chat_service=connect_chat_service,
                    table_service=table_service,
                    user_name=user_name,
                    sender_profile=sender_profile
                )
            else:
                logger.warning(f"Unknown message type: {message.message_type}, skipping")
                continue
                
            # Update DynamoDB with new contact details
            if new_contact_id:
                table_service.update(
                    key={"contactId": new_contact_id},
                    details={
                        "userId": message.sender_id,
                        "participantToken": new_participant_token,
                        "connectionToken": new_connection_token,
                        "userName": user_name,
                        "senderProfile": sender_profile,
                        "instagramAccountId": instagram_account_id
                    }
                )
        
        return build_response(200, json.dumps('All good!'))
    
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return build_response(400, json.dumps({'error': str(e)}))
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}", exc_info=True)
        return build_response(500, json.dumps({'error': 'Internal server error'}))







