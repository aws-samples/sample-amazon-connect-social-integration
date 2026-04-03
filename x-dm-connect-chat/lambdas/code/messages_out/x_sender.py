import logging
import tempfile
import os
import requests as http_requests
import tweepy

logger = logging.getLogger()


def _build_client(credentials):
    """Build a Tweepy Client using OAuth 2.0 User Context (v2 API)."""
    return tweepy.Client(
        consumer_key=credentials["consumer_key"],
        consumer_secret=credentials["consumer_secret"],
        access_token=credentials["access_token"],
        access_token_secret=credentials["access_token_secret"],
    )


def _build_api(credentials):
    """Build a Tweepy API instance using OAuth 1.0a (v1.1 API for media upload)."""
    auth = tweepy.OAuth1UserHandler(
        consumer_key=credentials["consumer_key"],
        consumer_secret=credentials["consumer_secret"],
        access_token=credentials["access_token"],
        access_token_secret=credentials["access_token_secret"],
    )
    return tweepy.API(auth)


def send_x_text(credentials, text, recipient_id):
    """
    Send a text DM to an X user via the v2 API.

    Args:
        credentials: Dict with consumer_key, consumer_secret, access_token, access_token_secret
        text: The text message to send
        recipient_id: X user ID of the recipient

    Returns:
        API response from create_direct_message
    """
    logger.info(f"Sending X text DM to {recipient_id}")
    client = _build_client(credentials)
    response = client.create_direct_message(
        participant_id=recipient_id,
        text=text,
    )
    logger.info(f"Text DM sent successfully to {recipient_id}")
    return response


def send_x_attachment(credentials, attachment_url, mime_type, recipient_id):
    """
    Send an attachment as a DM to an X user.

    Downloads the attachment from the signed URL, uploads it to X via the v1.1
    media_upload endpoint (OAuth 1.0a), then sends a DM with the media_id.

    If media upload fails, falls back to sending the signed URL as plain text.

    Args:
        credentials: Dict with consumer_key, consumer_secret, access_token, access_token_secret
        attachment_url: Pre-signed URL to download the attachment from
        mime_type: MIME type of the attachment (e.g. image/png)
        recipient_id: X user ID of the recipient

    Returns:
        API response from create_direct_message
    """
    logger.info(f"Sending X attachment DM to {recipient_id} ({mime_type})")

    # X only supports images and videos as DM media — PDFs, docs, etc. must be sent as links
    supported_media_types = (
        'image/jpeg', 'image/png', 'image/gif', 'image/webp',
        'video/mp4',
    )
    if mime_type not in supported_media_types:
        logger.info(f"Unsupported media type for X DM: {mime_type}. Sending as link.")
        return send_x_text(credentials, f"📎 {attachment_url}", recipient_id)

    try:
        # Download the attachment to a temp file
        suffix = _get_file_extension(mime_type)
        tmp_path = os.path.join(tempfile.gettempdir(), f"x_media_{os.getpid()}{suffix}")

        resp = http_requests.get(attachment_url, timeout=30)
        resp.raise_for_status()
        with open(tmp_path, 'wb') as f:
            f.write(resp.content)

        logger.info(f"Downloaded attachment to {tmp_path}")

        # Upload media via v1.1 API (OAuth 1.0a) with DM media category
        api = _build_api(credentials)
        media_category = _get_dm_media_category(mime_type)
        if media_category in ('dm_video', 'dm_gif'):
            media = api.chunked_upload(filename=tmp_path, media_category=media_category, wait_for_async_finalize=True)
        else:
            media = api.media_upload(filename=tmp_path, media_category=media_category)
        media_id = media.media_id
        logger.info(f"Media uploaded to X, media_id: {media_id}")

        # Clean up temp file
        os.unlink(tmp_path)

        # Send DM with media via v2 API
        client = _build_client(credentials)
        response = client.create_direct_message(
            participant_id=str(recipient_id),
            media_id=str(media_id),
        )
        logger.info(f"Attachment DM sent successfully to {recipient_id}")
        return response

    except Exception as e:
        # Clean up temp file if it exists
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)

        logger.error(f"Failed to upload media to X: {e}. Falling back to plain text URL.")
        # Fallback: send the signed URL as plain text
        return send_x_text(credentials, attachment_url, recipient_id)


def _get_file_extension(mime_type):
    """Map MIME type to a file extension for temp file creation."""
    mime_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "audio/mpeg": ".mp3",
        "application/pdf": ".pdf",
    }
    return mime_map.get(mime_type, ".bin")


def _get_dm_media_category(mime_type):
    """Map MIME type to X's DM media category for upload."""
    if mime_type == "image/gif":
        return "dm_gif"
    elif mime_type and mime_type.startswith("video/"):
        return "dm_video"
    else:
        return "dm_image"
