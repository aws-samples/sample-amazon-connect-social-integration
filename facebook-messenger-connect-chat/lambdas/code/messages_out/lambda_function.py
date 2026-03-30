## process Facebook Messenger outbound messages
import json
import os
import decimal
import logging
import boto3
from config_service import get_secret_value
from table_service import TableService
from messenger import send_messenger_text, send_messenger_attachment

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize table service
table_service = TableService()
access_token = get_secret_value(os.environ["SECRET_ARN"])
participant_client = boto3.client("connectparticipant")


def get_signed_url(connection_token, attachment_id):
    """Get a pre-signed URL for a Connect chat attachment.
    
    Args:
        connection_token: The connection token for the participant
        attachment_id: The ID of the attachment to retrieve
        
    Returns:
        The signed URL for the attachment, or None if retrieval fails
    """
    try:
        response = participant_client.get_attachment(
            AttachmentId=attachment_id,
            ConnectionToken=connection_token,
        )
        return response.get("Url")
    except Exception as e:
        logger.error(f"Failed to get signed URL for attachment {attachment_id}: {e}")
        return None


def get_contact(table_service, contact_id):
    """Get contact from DynamoDB by contactId.
    
    Args:
        table_service: The TableService instance
        contact_id: The Amazon Connect contact ID
        
    Returns:
        The contact record from ActiveConnections, or None if not found
    """
    response = table_service.table.query(
        KeyConditionExpression="contactId = :contactId",
        ExpressionAttributeValues={":contactId": contact_id},
    )
    if response.get("Items") and len(response["Items"]) > 0:
        return response["Items"][0]
    return None


def process_message(access_token, message_attributes, message):
    """Process MESSAGE type SNS records.
    
    For AGENT/SYSTEM messages with CUSTOMER/ALL visibility, sends the message
    to the customer via Messenger Send API.
    
    Args:
        access_token: The Page Access Token for Messenger API
        message_attributes: SNS message attributes containing MessageVisibility
        message: The parsed SNS message body
    """
    message_body = message["Content"]
    contactId = message["ContactId"]

    MessageVisibility = message_attributes["MessageVisibility"]["Value"]
    if MessageVisibility == "CUSTOMER" or MessageVisibility == "ALL":
        logger.info(f"contactId: {contactId}")
        contact = get_contact(table_service, contactId)

        if contact:
            userId = contact["userId"]
            pageId = contact["pageId"]
            send_messenger_text(
                access_token,
                message_body,
                userId,
            )
        else:
            logger.info("Contact not found")
    else:
        logger.info(f"Skipping message with visibility: {MessageVisibility}")


def process_event(message_attributes, message):
    """Process EVENT type SNS records.
    
    For participant.left or chat.ended events, deletes the session from
    ActiveConnections table.
    
    Args:
        message_attributes: SNS message attributes containing ContentType
        message: The parsed SNS message body
    """
    message_type = message_attributes["ContentType"]["Value"]
    if (
        message_type == "application/vnd.amazonaws.connect.event.participant.left"
        or message_type == "application/vnd.amazonaws.connect.event.chat.ended"
    ):
        logger.info("participant left or chat ended")
        contactId = message["InitialContactId"]
        table_service.delete_item(key={"contactId": contactId})


def process_attachment(access_token, message_attributes, message):
    """Process ATTACHMENT type SNS records.
    
    Retrieves the signed URL for each approved attachment and sends it
    to the customer via Messenger Send API.
    
    Args:
        access_token: The Page Access Token for Messenger API
        message_attributes: SNS message attributes
        message: The parsed SNS message body containing attachments
    """
    contactId = message["ContactId"]
    contact = get_contact(table_service, contactId)

    if contact:
        userId = contact["userId"]
        connectionToken = contact["connectionToken"]
        pageId = contact["pageId"]

        # Process attachments
        attachments = message.get("Attachments", [])
        for attachment in attachments:
            if attachment["Status"] == "APPROVED":
                attachment_id = attachment["AttachmentId"]
                attachment_name = attachment["AttachmentName"]
                content_type = attachment["ContentType"]

                # Get signed URL for the attachment from Connect
                signed_url = get_signed_url(connectionToken, attachment_id)

                if signed_url:
                    logger.info(f"Sending attachment {attachment_name} ({content_type}) to {userId}")
                    send_messenger_attachment(
                        access_token=access_token,
                        attachment_url=signed_url,
                        mime_type=content_type,
                        recipient_id=userId,
                    )
                else:
                    logger.error(f"Failed to get signed URL for attachment {attachment_id}")
    else:
        logger.info("Contact not found for attachment handling")


def process_record(access_token, record):
    """Process a single SNS record.
    
    Parses the SNS message and routes to the appropriate handler based on
    message type (MESSAGE, EVENT, or ATTACHMENT). Skips CUSTOMER role messages.
    
    Args:
        access_token: The Page Access Token for Messenger API
        record: The SNS record from the Lambda event
    """
    sns = record.get("Sns", {})
    sns_message_str = sns.get("Message", "{}")
    message_attributes = sns.get("MessageAttributes")
    message = json.loads(sns_message_str, parse_float=decimal.Decimal)

    logger.info(f"Message: {message}")
    message_type = message.get("Type")
    ParticipantRole = message.get("ParticipantRole")
    if ParticipantRole == "CUSTOMER":
        logger.info("ParticipantRole is CUSTOMER, ignoring")
        return

    if message_type == "MESSAGE":
        process_message(access_token, message_attributes, message)

    if message_type == "EVENT":
        process_event(message_attributes, message)

    if message_type == "ATTACHMENT":
        process_attachment(access_token, message_attributes, message)


def lambda_handler(event, context):
    """Lambda entry point for processing outbound messages.
    
    Processes SNS records containing Amazon Connect Chat streaming events
    and sends messages/attachments to customers via Messenger Send API.
    
    Args:
        event: Lambda event containing SNS records
        context: Lambda context
    """
    logger.info(f"Event: {event}")
    records = event.get("Records", [])
    access_token = get_secret_value(os.environ["SECRET_ARN"])
    for record in records:
        process_record(access_token, record)
