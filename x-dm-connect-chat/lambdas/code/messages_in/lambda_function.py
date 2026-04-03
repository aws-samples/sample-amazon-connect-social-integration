## process X webhook messages
import json
import os
import logging
from config_service import get_secret_value, get_ssm_parameter
from table_service import TableService
from x_service import XService
from connect_chat_service import ChatService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from utils import build_response, compute_crc_response

CHANNEL_NAME = "X"


def download_attachment(url, credentials=None):
    """Download attachment content from X media URL.
    
    ton.twitter.com URLs require OAuth 1.0a authentication.
    pbs.twimg.com URLs are publicly accessible.
    """
    if not url or not url.startswith("https://"):
        logger.error(f"Invalid attachment URL scheme, only HTTPS is allowed: {url}")
        return None, None

    try:
        # ton.twitter.com requires OAuth — use Tweepy's API to make authenticated request
        if 'ton.twitter.com' in url and credentials:
            import tweepy
            import requests
            from requests_oauthlib import OAuth1

            logger.info(f"Downloading authenticated media from ton.twitter.com")
            oauth = OAuth1(
                credentials['consumer_key'],
                credentials['consumer_secret'],
                credentials['access_token'],
                credentials['access_token_secret'],
            )
            resp = requests.get(url, auth=oauth, timeout=15)
            resp.raise_for_status()
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            file_bytes = resp.content
            logger.info(f"Downloaded attachment: {len(file_bytes)} bytes, type: {content_type}")
            return file_bytes, content_type
        else:
            # Public URL (pbs.twimg.com, video.twimg.com, etc.)
            import urllib.request
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=15) as response:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310
                content_type = response.headers.get('Content-Type', 'application/octet-stream')
                file_bytes = response.read()
                logger.info(f"Downloaded attachment: {len(file_bytes)} bytes, type: {content_type}")
                return file_bytes, content_type
    except Exception as e:
        logger.error(f"Failed to download attachment: {e}")
        return None, None


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
        sender_profile: X profile data for the sender

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
                message=message.text or "New conversation",
                userId=message.sender_id,
                channel=CHANNEL_NAME,
                userName=user_name,
                systemNumber=None,
            )
        )
        return new_contact_id, new_participant_token, new_connection_token


def attachment_message_handler(message, connect_chat_service, table_service, user_name, sender_profile, credentials=None):
    """
    Handle attachment message: ensure a chat contact exists, download the media
    from X, and upload it to Connect as a file attachment.
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
        initial_text = f"[Sent {message.attachment_type or 'media'}]"
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

    att_url = message.attachment_url
    if not att_url:
        logger.warning("Attachment missing URL, skipping")
        return new_contact_id, new_participant_token, new_connection_token

    file_bytes, content_type = download_attachment(att_url, credentials=credentials)
    if file_bytes is None:
        logger.warning("Could not download attachment, sending URL as text")
        connect_chat_service.send_message(f"[{message.attachment_type} attachment]: {att_url}", connection_token)
        return new_contact_id, new_participant_token, new_connection_token

    # Generate filename
    ext_map = {'photo': 'jpg', 'animated_gif': 'gif', 'video': 'mp4'}
    ext = ext_map.get(message.attachment_type, 'bin')
    file_name = f"x_{message.attachment_type or 'media'}.{ext}"

    attachment_id, error = connect_chat_service.attach_file(
        fileContents=file_bytes,
        fileName=file_name,
        fileType=content_type,
        ConnectionToken=connection_token
    )

    if error:
        logger.error(f"Failed to upload attachment to Connect: {error}")
        connect_chat_service.send_message(f"[{message.attachment_type} attachment]: {att_url}", connection_token)
    else:
        logger.info(f"Attachment uploaded to Connect: {attachment_id}")

    return new_contact_id, new_participant_token, new_connection_token


def lambda_handler(event, context):
    logger.info(event)

    try:
        # Initialize config service
        config = get_ssm_parameter(os.environ["CONFIG_PARAM_NAME"])
        x_account_id = config.get("x_account_id")

        # Handle GET request (CRC webhook validation)
        if event['httpMethod'] == 'GET':
            query_params = event.get('queryStringParameters') or {}
            crc_token = query_params.get('crc_token')

            if not crc_token:
                return build_response(400, json.dumps({'error': 'Missing crc_token parameter'}))

            # Retrieve Consumer Secret from Secrets Manager
            credentials = get_secret_value(os.environ["SECRET_ARN"])
            consumer_secret = credentials.get('consumer_secret')

            # Compute CRC response
            crc_response = compute_crc_response(crc_token, consumer_secret)
            return build_response(200, json.dumps(crc_response))

        # Handle POST request (webhook message)
        if event.get("body") is None:
            return build_response(200, "bye bye")

        body = json.loads(event['body'])
        logger.info(f"Received webhook body: {json.dumps(body)}")

        # Check for direct_message_events key - if missing, this is an encrypted DM or non-DM event
        if 'direct_message_events' not in body:
            logger.info(f"Non-DM event received. Event keys: {list(body.keys())}")
            return build_response(200, json.dumps('OK'))

        # Get X API credentials
        credentials = get_secret_value(os.environ["SECRET_ARN"])

        # Initialize X service with get_profiles=True to automatically fetch profiles
        x_service = XService(body, credentials=credentials, x_account_id=x_account_id, get_profiles=True)

        logger.info(f"Parsed {x_service.get_message_count()} messages")

        # Initialize table service
        table_service = TableService()

        connect_chat_service = ChatService(
            instance_id=config.get("instance_id"),
            contact_flow_id=config.get("contact_flow_id"),
            topic_arn=os.environ.get("TOPIC_ARN")
        )

        # Process all messages
        for message in x_service.get_messages():
            logger.info(f"Processing {message.message_type} message from {message.sender_id}")
            user_name = message.sender_id

            # Get sender profile from cache (already fetched if get_profiles=True)
            sender_profile = x_service.user_profiles.get(message.sender_id)
            if sender_profile:
                logger.info(f"Sender profile: {sender_profile.get('username')} ({sender_profile.get('name')})")
                user_name = XService.get_display_name(sender_profile, message.sender_id)

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
                    sender_profile=sender_profile,
                    credentials=credentials
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
                        "xAccountId": x_account_id
                    }
                )

        return build_response(200, json.dumps('All good!'))

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return build_response(400, json.dumps({'error': str(e)}))
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}", exc_info=True)
        return build_response(500, json.dumps({'error': 'Internal server error'}))
