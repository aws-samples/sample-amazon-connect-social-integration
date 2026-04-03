## process X DM outbound messages from Amazon Connect
import json
import os
import decimal
import logging
import boto3
from config_service import get_secret_value
from table_service import TableService
from x_sender import send_x_text, send_x_attachment

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize table service
table_service = TableService()
credentials = get_secret_value(os.environ["SECRET_ARN"])
participant_client = boto3.client("connectparticipant")


def get_signed_url(connection_token, attachment_id):
    """Get a pre-signed URL for a Connect chat attachment."""
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
    """Get contact from DynamoDB by contactId."""
    response = table_service.table.query(
        KeyConditionExpression="contactId = :contactId",
        ExpressionAttributeValues={":contactId": contact_id},
    )
    if response.get("Items") and len(response["Items"]) > 0:
        return response["Items"][0]
    return None


def process_message(credentials, message_attributes, message):
    """Process an outbound MESSAGE event — send text DM to X user."""
    message_body = message["Content"]
    contactId = message["ContactId"]

    MessageVisibility = message_attributes["MessageVisibility"]["Value"]
    if MessageVisibility == "CUSTOMER" or MessageVisibility == "ALL":
        logger.info(f"contactId: {contactId}")
        contact = get_contact(table_service, contactId)

        if contact:
            userId = contact["userId"]
            send_x_text(credentials, message_body, userId)
        else:
            logger.warning(f"Contact not found for contactId: {contactId}")


def process_event(message_attributes, message):
    """Process an outbound EVENT — clean up session on disconnect/chat-ended."""
    message_type = message_attributes["ContentType"]["Value"]
    if (
        message_type == "application/vnd.amazonaws.connect.event.participant.left"
        or message_type == "application/vnd.amazonaws.connect.event.chat.ended"
    ):
        logger.info("participant left or chat ended")
        contactId = message["InitialContactId"]
        table_service.delete_item(key={"contactId": contactId})


def process_attachment(credentials, message_attributes, message):
    """Process an outbound ATTACHMENT event — send media DM to X user."""
    contactId = message["ContactId"]
    contact = get_contact(table_service, contactId)

    if contact:
        userId = contact["userId"]
        connectionToken = contact["connectionToken"]

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
                    send_x_attachment(
                        credentials=credentials,
                        attachment_url=signed_url,
                        mime_type=content_type,
                        recipient_id=userId,
                    )
                else:
                    logger.error(f"Failed to get signed URL for attachment {attachment_id}")
    else:
        logger.warning(f"Contact not found for attachment handling, contactId: {contactId}")


def process_record(credentials, record):
    """Process a single SNS record."""
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
        process_message(credentials, message_attributes, message)

    if message_type == "EVENT":
        process_event(message_attributes, message)

    if message_type == "ATTACHMENT":
        process_attachment(credentials, message_attributes, message)


def lambda_handler(event, context):
    logger.info(f"Event: {event}")
    records = event.get("Records", [])
    credentials = get_secret_value(os.environ["SECRET_ARN"])
    for record in records:
        process_record(credentials, record)
