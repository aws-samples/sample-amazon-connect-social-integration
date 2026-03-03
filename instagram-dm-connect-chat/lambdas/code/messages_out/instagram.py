import json
import urllib.request
import urllib.parse
import urllib.error
import os


META_API_VERSION = os.environ.get("META_API_VERSION", "v24.0")
GRAPH_API_BASE_URL = f"https://graph.instagram.com/{META_API_VERSION}"


def get_attachment_type(mime_type):
    """Map MIME types to Instagram attachment types"""
    if mime_type.startswith("image/"):
        return "image"
    elif mime_type.startswith("video/"):
        return "video"
    elif mime_type.startswith("audio/"):
        return "audio"
    elif mime_type == "application/pdf":
        return "file"
    else:
        return "file"


def send_instagram_text(access_token, text_message, recipient_id, instagram_account_id=None):
    """
    Send a text message via Instagram Messaging API

    Args:
        access_token: Page access token for authentication
        text_message: The text content to send
        recipient_id: Instagram-scoped ID (IGSID) of the recipient
        instagram_account_id:  Instagram account 

    Returns:
        API response dict with recipient_id and message_id
    """
    print(f"Sending Instagram text message to {recipient_id}...")

    # Get instagram_account_id from environment if not provided
    if not instagram_account_id:
        raise ValueError("instagram_account_id must be provided or set in environment variables")

    url = f"{GRAPH_API_BASE_URL}/{instagram_account_id}/messages"

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message},
        "access_token": access_token,
    }

    data = json.dumps(payload).encode("utf-8")

    print ("payload:", payload)

    print(f"Request URL: {url}")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            print(f"Message sent successfully: {result}")
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Error sending message: {e.code} - {error_body}")
        raise


def send_instagram_attachment(
    access_token, attachment_url, mime_type, recipient_id, instagram_account_id=None
):
    """
    Send an attachment via Instagram Messaging API

    Args:
        access_token: Page access token for authentication
        attachment_url: Public URL of the attachment
        mime_type: MIME type of the attachment
        recipient_id: Instagram-scoped ID (IGSID) of the recipient
        instagram_account_id: Instagram account ID (optional)

    Returns:
        API response dict with recipient_id and message_id
    """
    print(f"Sending Instagram attachment to {recipient_id}...")

    if not instagram_account_id:
        raise ValueError("instagram_account_id must be provided or set in environment variables")

    attachment_type = get_attachment_type(mime_type)

    url = f"{GRAPH_API_BASE_URL}/{instagram_account_id}/messages"

    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {"type": attachment_type, "payload": {"url": attachment_url}}
        },
        "access_token": access_token,
    }

    data = json.dumps(payload).encode("utf-8")

    print("payload:", payload)

    print(f"Request URL: {url}")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            print(f"Attachment sent successfully: {result}")
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Error sending attachment: {e.code} - {error_body}")
        raise
