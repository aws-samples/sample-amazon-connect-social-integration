import boto3
import os
import sys
import urllib.request
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ChatService:
    def __init__(
        self,
        instance_id=os.environ.get("INSTANCE_ID"),
        contact_flow_id=os.environ.get("CONTACT_FLOW_ID"),
        chat_duration_minutes=60,
        topic_arn=os.environ.get("TOPIC_ARN")
    ) -> None:
        self.participant = boto3.client("connectparticipant")
        self.connect = boto3.client("connect")
        self.contact_flow_id = contact_flow_id
        self.instance_id = instance_id
        self.chat_duration_minutes = chat_duration_minutes
        self.topic_arn = topic_arn

    def start_chat(self, message: str, userId: str, channel: str, userName: str = None, systemNumber: str = None):
        """
        Start a new Amazon Connect Chat session.
        
        Sets contact attributes:
        - Channel: "Messenger" (for Facebook Messenger integration)
        - customerId: sender PSID
        - customerName: sender display name
        """
        if userName is None:
            userName = userId

        attributes = {
            "Channel": channel,
            "customerId": userId,
            "customerName": userName,
        }

        if systemNumber is not None:
            attributes["systemNumber"] = systemNumber

        start_chat_response = self.connect.start_chat_contact(
            InstanceId=self.instance_id,
            ContactFlowId=self.contact_flow_id,
            Attributes=attributes,
            ParticipantDetails={"DisplayName": userName},
            InitialMessage={"ContentType": "text/plain", "Content": message},
            ChatDurationInMinutes=self.chat_duration_minutes,
            SupportedMessagingContentTypes=[
                "text/plain",
                "text/markdown",
                "application/json",
                "application/vnd.amazonaws.connect.message.interactive",
                "application/vnd.amazonaws.connect.message.interactive.response",
            ],
        )
        logger.info(start_chat_response)
        return start_chat_response

    def send_message_with_retry_connection(self, message: str, userId: str, channel: str, connectionToken: str, userName: str = None, systemNumber: str = None):
        """
        Send a message using existing connection token.
        If token is expired (AccessDeniedException), create a new session.
        
        Returns (contactId, participantToken, connectionToken) if new session created,
        or (None, None, None) if message sent successfully on existing connection.
        """
        if userName is None:
            userName = userId

        result = self.send_message(message, connectionToken)
        if result == "ACCESS_DENIED":
            contactId, participantToken, connectionToken = (
                self.start_chat_and_stream(
                    message=message or "New conversation with attachment",
                    userId=userId,
                    channel=channel,
                    userName=userName,
                    systemNumber=systemNumber,
                )
            )
            return contactId, participantToken, connectionToken
        return None, None, None

    def send_message(self, message, connectionToken):
        """
        Send a message to an existing Connect Chat session.
        
        Returns None on success, or error code string on failure.
        Handles AccessDeniedException for expired connection tokens.
        """
        try:
            self.participant.send_message(ContentType="text/plain", Content=message, ConnectionToken=connectionToken)
            return None
        except self.participant.exceptions.AccessDeniedException as e:
            logger.info(f"Access denied: {e}. Check your IAM permissions or connection token validity.")
            return "ACCESS_DENIED"
        except self.participant.exceptions.InternalServerException as e:
            logger.info(f"Internal server error: {e}. Please try again later.")
            return "SERVER_EXCEPTION"
        except self.participant.exceptions.ThrottlingException as e:
            logger.info(f"Request throttled: {e}. Reduce request frequency or implement backoff strategy.")
            return "THROTTLING"
        except self.participant.exceptions.ValidationException as e:
            logger.info(f"Validation error: {e}. Check your message content and connection token format.")
            return "VALIDATION_ERROR"
        except self.participant.exceptions.ServiceQuotaExceededException as e:
            logger.info(f"Service quota exceeded: {e}. Reduce message frequency or request quota increase.")
            return "QUOTA_ERROR"
        except Exception as e:
            logger.info(f"Unexpected error: {e}")
            return "UNEXPECTED_ERROR"

    def start_stream(self, ContactId):
        """
        Start contact streaming to SNS topic for agent message delivery.
        """
        if not self.topic_arn:
            logger.info("Missing Topic ARN for start streaming")
            return None

        start_stream_response = self.connect.start_contact_streaming(
            InstanceId=self.instance_id,
            ContactId=ContactId,
            ChatStreamingConfiguration={"StreamingEndpointArn": self.topic_arn})

        return start_stream_response

    def start_chat_and_stream(self, message: str, userId: str, channel: str, userName: str = None, systemNumber: str = None):
        """
        Create a new chat session, start streaming, and create participant connection.
        
        Returns (contactId, participantToken, connectionToken) tuple.
        """
        if userName is None:
            userName = userId

        start_chat_response = self.start_chat(
            message=message,
            userId=userId,
            channel=channel,
            userName=userName,
            systemNumber=systemNumber
        )

        participantToken = start_chat_response["ParticipantToken"]
        contactId = start_chat_response['ContactId']

        start_stream_response = self.start_stream(contactId)
        create_connection_response = self.create_connection(participantToken)
        connectionToken = create_connection_response['ConnectionCredentials']['ConnectionToken']

        return contactId, participantToken, connectionToken

    def create_connection(self, ParticipantToken):
        """
        Create a participant connection for sending messages.
        """
        create_connection_response = self.participant.create_participant_connection(
            Type=["CONNECTION_CREDENTIALS"],
            ParticipantToken=ParticipantToken,
            ConnectParticipant=True
        )
        return create_connection_response

    def get_signed_url(self, connectionToken, attachment):
        """
        Get a signed URL for downloading an attachment from Connect.
        """
        try:
            response = self.participant.get_attachment(
                AttachmentId=attachment, ConnectionToken=connectionToken
            )
        except ClientError as e:
            logger.info("Get attachment failed")
            logger.info(e.response["Error"]["Code"])
            return None
        else:
            return response["Url"]

    def attach_file(self, fileContents, fileName, fileType, ConnectionToken):
        """
        Upload an attachment to the Connect Chat session.
        
        Returns (attachmentId, error) tuple.
        - On success: (attachmentId, None)
        - On failure: (None, error_message)
        """
        fileSize = sys.getsizeof(fileContents) - 33  # Removing BYTES overhead
        logger.info("Size downloaded:" + str(fileSize))
        try:
            attachResponse = self.participant.start_attachment_upload(
                ContentType=fileType,
                AttachmentSizeInBytes=fileSize,
                AttachmentName=fileName,
                ConnectionToken=ConnectionToken
            )
        except ClientError as e:
            logger.info("Error while creating attachment")
            error_code = e.response['Error']['Code']
            if error_code in ('AccessDeniedException', 'ValidationException'):
                logger.info(e.response['Error'])
                return None, e.response['Error']['Message']
            raise
        else:
            try:
                upload_url = attachResponse['UploadMetadata']['Url']
                # Validate URL scheme to prevent file:// or other dangerous schemes
                if not upload_url or not upload_url.startswith("https://"):
                    logger.error("Invalid upload URL scheme, only HTTPS is allowed")
                    return None, "Invalid upload URL scheme"

                req = urllib.request.Request(
                    upload_url,
                    data=fileContents,
                    headers=attachResponse['UploadMetadata']['HeadersToInclude'],
                    method='PUT'
                )
                with urllib.request.urlopen(req) as filePostingResponse:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310
                    logger.info(filePostingResponse.status)
                    self.participant.complete_attachment_upload(
                        AttachmentIds=[attachResponse['AttachmentId']],
                        ConnectionToken=ConnectionToken)
                    logger.info("Attachment upload completed")
                    return attachResponse['AttachmentId'], None
            except Exception as e:
                logger.info("Error while uploading")
                logger.info(str(e))
                return None, str(e)
