import json
import urllib.request
import urllib.parse
import urllib.error
import os


META_API_VERSION = os.environ.get("META_API_VERSION", "v24.0")
GRAPH_API_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"


def get_attachment_type(mime_type):
    """Map MIME types to Messenger attachment types.
    
    Args:
        mime_type: MIME type string (e.g., "image/jpeg", "video/mp4")
        
    Returns:
        Messenger attachment type: "image", "video", "audio", or "file"
    """
    if mime_type.startswith("image/"):
        return "image"
    elif mime_type.startswith("video/"):
        return "video"
    elif mime_type.startswith("audio/"):
        return "audio"
    else:
        return "file"


def send_messenger_text(access_token, text_message, recipient_id):
    """
    Send a text message via Facebook Messenger Send API.

    Args:
        access_token: Page Access Token for authentication
        text_message: The text content to send
        recipient_id: Page-Scoped ID (PSID) of the recipient

    Returns:
        API response dict with recipient_id and message_id
        
    Raises:
        ValueError: If recipient_id is not numeric or URL scheme is invalid
        urllib.error.HTTPError: If the API request fails
    """
    print(f"Sending Messenger text message to {recipient_id}...")

    # Validate PSID is numeric to prevent URL injection
    if not str(recipient_id).isdigit():
        raise ValueError(f"Invalid recipient_id: must be numeric. Got: {recipient_id!r}")

    url = f"{GRAPH_API_BASE_URL}/me/messages"

    # Validate URL uses HTTPS scheme
    if not url.startswith("https://"):
        raise ValueError(f"Constructed URL does not use HTTPS scheme: {url}")

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message},
    }

    # Add access token as query parameter
    url_with_token = f"{url}?access_token={urllib.parse.quote(access_token)}"

    data = json.dumps(payload).encode("utf-8")

    print("payload:", payload)
    print(f"Request URL: {url}")

    req = urllib.request.Request(
        url_with_token, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req) as response:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310
            result = json.loads(response.read().decode("utf-8"))
            print(f"Message sent successfully: {result}")
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Error sending message: {e.code} - {error_body}")
        raise


def send_messenger_attachment(access_token, attachment_url, mime_type, recipient_id):
    """
    Send an attachment via Facebook Messenger Send API.

    Args:
        access_token: Page Access Token for authentication
        attachment_url: Public URL of the attachment (must be HTTPS)
        mime_type: MIME type of the attachment
        recipient_id: Page-Scoped ID (PSID) of the recipient

    Returns:
        API response dict with recipient_id and message_id
        
    Raises:
        ValueError: If recipient_id is not numeric, URL scheme is invalid, or attachment_url is not HTTPS
        urllib.error.HTTPError: If the API request fails
    """
    print(f"Sending Messenger attachment to {recipient_id}...")

    # Validate PSID is numeric to prevent URL injection
    if not str(recipient_id).isdigit():
        raise ValueError(f"Invalid recipient_id: must be numeric. Got: {recipient_id!r}")

    # Validate attachment URL uses HTTPS scheme
    if not attachment_url.startswith("https://"):
        raise ValueError(f"Attachment URL does not use HTTPS scheme: {attachment_url}")

    attachment_type = get_attachment_type(mime_type)

    url = f"{GRAPH_API_BASE_URL}/me/messages"

    # Validate constructed URL uses HTTPS scheme
    if not url.startswith("https://"):
        raise ValueError(f"Constructed URL does not use HTTPS scheme: {url}")

    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": attachment_type,
                "payload": {
                    "url": attachment_url,
                    "is_reusable": True
                }
            }
        },
    }

    # Add access token as query parameter
    url_with_token = f"{url}?access_token={urllib.parse.quote(access_token)}"

    data = json.dumps(payload).encode("utf-8")

    print("payload:", payload)
    print(f"Request URL: {url}")

    req = urllib.request.Request(
        url_with_token, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req) as response:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310
            result = json.loads(response.read().decode("utf-8"))
            print(f"Attachment sent successfully: {result}")
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Error sending attachment: {e.code} - {error_body}")
        raise
