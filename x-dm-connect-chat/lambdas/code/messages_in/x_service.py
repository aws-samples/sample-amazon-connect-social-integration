import logging
import os
import time
from typing import List, Dict, Any, Optional
from table_service import TableService

logger = logging.getLogger()

USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME")
PROFILE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


class XMessage:
    """Represents a single X DM event"""

    def __init__(self, event_data: Dict[str, Any]):
        message_create = event_data.get('message_create', {})
        message_data = message_create.get('message_data', {})
        self.sender_id = message_create.get('sender_id')
        self.text = message_data.get('text')
        self.created_timestamp = event_data.get('created_timestamp')
        self.event_id = event_data.get('id')
        self.recipient_id = message_create.get('target', {}).get('recipient_id')

        # Parse attachment if present
        self.attachment = message_data.get('attachment')
        self.attachment_url = None
        self.attachment_type = None
        if self.attachment and self.attachment.get('type') == 'media':
            media = self.attachment.get('media', {})
            # For images: use media_url_https
            self.attachment_url = media.get('media_url_https') or media.get('media_url')
            self.attachment_type = media.get('type', 'photo')  # photo, animated_gif, video
            # For video/gif: prefer the video URL
            video_info = media.get('video_info', {})
            variants = video_info.get('variants', [])
            if variants:
                # Pick the mp4 variant (or first available)
                for v in variants:
                    if v.get('content_type') == 'video/mp4':
                        self.attachment_url = v['url']
                        break
                if not self.attachment_url and variants:
                    self.attachment_url = variants[0].get('url')

        # Determine message type
        if self.attachment_url:
            self.message_type = 'attachment'
        elif self.text:
            self.message_type = 'text'
        else:
            self.message_type = 'unknown'

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary"""
        return {
            'eventId': self.event_id,
            'senderId': self.sender_id,
            'recipientId': self.recipient_id,
            'createdTimestamp': self.created_timestamp,
            'text': self.text,
            'messageType': self.message_type
        }

    def __repr__(self):
        return f"XMessage(id={self.event_id}, sender={self.sender_id}, type={self.message_type})"


class XService:
    """Service to process X webhook events for Direct Messages"""

    def __init__(self, event_body: Dict[str, Any], x_account_id: Optional[str] = None,
                 credentials: Optional[Dict[str, str]] = None, get_profiles: bool = False):
        """
        Initialize X service with webhook event body.

        Args:
            event_body: The parsed JSON body from X webhook
            x_account_id: The business's own X account ID (for echo prevention)
            credentials: Dict with consumer_key, consumer_secret, access_token, access_token_secret
            get_profiles: If True, automatically fetch user profiles for all senders
        """
        self.event_body = event_body
        self.x_account_id = x_account_id
        self.credentials = credentials
        self.get_profiles = get_profiles
        self.messages: List[XMessage] = []
        self.user_profiles: Dict[str, Dict[str, Any]] = {}

        # Extract inline user profiles from the webhook payload (X includes them)
        self._extract_inline_profiles()

        # Parse direct_message_events
        self._parse_events()

        # Fetch any missing profiles if requested
        if self.get_profiles:
            self._fetch_all_profiles()

    def _extract_inline_profiles(self):
        """Extract user profiles from the inline 'users' dict in the webhook payload."""
        users = self.event_body.get('users', {})
        for user_id, user_data in users.items():
            profile = {
                'name': user_data.get('name'),
                'username': user_data.get('screen_name'),
                'profile_image_url': user_data.get('profile_image_url_https') or user_data.get('profile_image_url'),
            }
            self.user_profiles[user_id] = profile
        if users:
            logger.info(f"Extracted {len(users)} inline profiles from webhook payload")

    def _parse_events(self):
        """Parse direct_message_events and extract messages, filtering echoes."""
        events = self.event_body.get('direct_message_events', [])

        for event in events:
            message = XMessage(event)
            # Skip messages sent by our own account (echo prevention)
            if self.x_account_id and message.sender_id == self.x_account_id:
                logger.debug(f"Skipping message from own account: {message.sender_id}")
                continue
            self.messages.append(message)

        logger.info(f"Parsed {len(self.messages)} messages from {len(events)} events")

    def _fetch_all_profiles(self):
        """Fetch profiles for senders not already in the cache (from inline or DynamoDB)."""
        unique_sender_ids = set()

        for message in self.messages:
            if message.sender_id and message.sender_id not in self.user_profiles:
                unique_sender_ids.add(message.sender_id)

        if not unique_sender_ids:
            logger.info("All sender profiles already available from webhook payload")
            return

        logger.info(f"Fetching {len(unique_sender_ids)} missing profiles")

        for sender_id in unique_sender_ids:
            profile = self.get_user_profile(sender_id)
            if profile:
                self.user_profiles[sender_id] = profile

        logger.info(f"Total profiles available: {len(self.user_profiles)}")

    def get_messages(self) -> List[XMessage]:
        """Get all parsed messages"""
        return self.messages

    def get_text_messages(self) -> List[XMessage]:
        """Get only text messages"""
        return [msg for msg in self.messages if msg.message_type == 'text']

    def get_attachment_messages(self) -> List[XMessage]:
        """Get only attachment messages"""
        return [msg for msg in self.messages if msg.message_type == 'attachment']

    def get_message_count(self) -> int:
        """Get the total number of messages"""
        return len(self.messages)

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get X user profile information using Tweepy client.

        Checks in-memory cache first, then DynamoDB X Users table,
        then fetches from X API via Tweepy.

        Args:
            user_id: The X user ID

        Returns:
            Dictionary with user profile data or None if request fails
        """
        # Check in-memory cache first
        if user_id in self.user_profiles:
            logger.debug(f"Returning cached profile for user: {user_id}")
            return self.user_profiles[user_id]

        # Check DynamoDB users table
        if USERS_TABLE_NAME:
            try:
                users_table = TableService(table_name=USERS_TABLE_NAME)
                db_profile = users_table.get_item({"id": user_id})
                if db_profile:
                    db_profile.pop("id", None)
                    db_profile.pop("timestamp", None)
                    logger.info(f"Profile found in users table for: {user_id}")
                    self.user_profiles[user_id] = db_profile
                    return db_profile
            except Exception as e:
                logger.warning(f"Error reading users table, falling back to API: {e}")

        if not self.credentials:
            logger.warning("Credentials not provided. Cannot fetch user profile.")
            return None

        try:
            import tweepy

            client = tweepy.Client(
                consumer_key=self.credentials.get('consumer_key'),
                consumer_secret=self.credentials.get('consumer_secret'),
                access_token=self.credentials.get('access_token'),
                access_token_secret=self.credentials.get('access_token_secret')
            )

            logger.info(f"Fetching profile from X API for user: {user_id}")
            response = client.get_user(id=user_id, user_fields=['name', 'username', 'profile_image_url'])

            if response and response.data:
                profile_data = {
                    'name': response.data.name,
                    'username': response.data.username,
                    'profile_image_url': getattr(response.data, 'profile_image_url', None)
                }

                logger.info(f"Successfully retrieved profile for user: {profile_data.get('username', 'unknown')}")

                # Cache in memory
                self.user_profiles[user_id] = profile_data

                # Persist to DynamoDB users table
                if USERS_TABLE_NAME:
                    try:
                        users_table = TableService(table_name=USERS_TABLE_NAME)
                        item = {**profile_data, "id": user_id, "timestamp": int(time.time()) + PROFILE_TTL_SECONDS}
                        users_table.table.put_item(Item=item)
                        logger.info(f"Saved profile to users table for: {user_id}")
                    except Exception as e:
                        logger.warning(f"Failed to save profile to users table: {e}")

                return profile_data
            else:
                logger.warning(f"No data returned for user: {user_id}")
                return None

        except Exception as e:
            logger.error(f"Error fetching user profile: {e}")
            return None

    @staticmethod
    def get_display_name(profile: Optional[Dict[str, Any]], fallback: str) -> str:
        """
        Get display name from profile, falling back to provided fallback.

        Args:
            profile: User profile dict (may be None)
            fallback: Fallback string (typically the user ID)

        Returns:
            The profile's name if available, otherwise the fallback
        """
        if profile and profile.get('name'):
            return profile['name']
        return fallback
