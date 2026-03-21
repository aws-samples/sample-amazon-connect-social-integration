import logging
import json
import os
import time
from urllib import request, parse, error
from typing import List, Dict, Any, Optional
from table_service import TableService

logger = logging.getLogger()

USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME")
PROFILE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


class MessengerMessage:
    """Represents a single Facebook Messenger message"""
    
    def __init__(self, messaging_data: Dict[str, Any]):
        self.sender_id = messaging_data.get('sender', {}).get('id')
        self.recipient_id = messaging_data.get('recipient', {}).get('id')
        self.timestamp = messaging_data.get('timestamp')
        
        message_data = messaging_data.get('message', {})
        self.message_id = message_data.get('mid')
        self.text = message_data.get('text')
        self.attachments = message_data.get('attachments', [])
        
        # Determine message type
        if self.text:
            self.message_type = 'text'
        elif len(self.attachments):
            self.message_type = 'attachment'
        else:
            self.message_type = 'unknown'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary"""
        return {
            'messageId': self.message_id,
            'senderId': self.sender_id,
            'recipientId': self.recipient_id,
            'timestamp': self.timestamp,
            'text': self.text,
            'messageType': self.message_type,
            'attachments': self.attachments
        }
    
    def __repr__(self):
        return f"MessengerMessage(id={self.message_id}, sender={self.sender_id}, type={self.message_type})"


class MessengerService:
    """Service to process Facebook Messenger webhook events"""
    
    GRAPH_API_VERSION = 'v24.0'
    GRAPH_API_BASE_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

    def __init__(self, event_body: Dict[str, Any], page_id: [str] = None, access_token: [str] = None, get_profiles: bool = False):
        """
        Initialize Messenger service with webhook event body
        
        Args:
            event_body: The parsed JSON body from Messenger webhook
            page_id: Facebook Page ID for echo prevention
            access_token: Facebook Page access token for API calls (optional)
            get_profiles: If True, automatically fetch user profiles for all senders (default: False)
        """
        self.event_body = event_body
        self.access_token = access_token
        self.get_profiles = get_profiles
        self.page_id = page_id
        self.messages: List[MessengerMessage] = []
        self.entries = []
        self.user_profiles: Dict[str, Dict[str, Any]] = {}  # Cache profiles by sender_id
        
        # Validate and parse the event - only process "page" object (not "instagram")
        if event_body.get('object') == 'page':
            self._parse_entries()
            
            # Fetch profiles if requested
            if self.get_profiles and self.access_token:
                self._fetch_all_profiles()
    
    def _parse_entries(self):
        """Parse all entries and extract messages"""
        entries = self.event_body.get('entry', [])
        
        for entry in entries:
            entry_data = {
                'id': entry.get('id'),
                'time': entry.get('time'),
                'messaging': []
            }
            
            messaging_list = entry.get('messaging', [])
            for messaging in messaging_list:
                message = MessengerMessage(messaging)
                # Skip messages sent by our own Page (echo prevention)
                if self.page_id and message.sender_id == self.page_id:
                    logger.debug(f"Skipping message from own Page: {message.sender_id}")
                    continue
                self.messages.append(message)
                entry_data['messaging'].append(message)
            
            self.entries.append(entry_data)
        
        logger.info(f"Parsed {len(self.messages)} messages from {len(self.entries)} entries")
    
    def _fetch_all_profiles(self):
        """Fetch profiles for all unique senders in messages"""
        unique_sender_ids = set()
        
        for message in self.messages:
            if message.sender_id:
                unique_sender_ids.add(message.sender_id)
        
        logger.info(f"Fetching profiles for {len(unique_sender_ids)} unique senders")
        
        for sender_id in unique_sender_ids:
            profile = self.get_user_profile(sender_id)
            if profile:
                self.user_profiles[sender_id] = profile
        
        logger.info(f"Successfully fetched {len(self.user_profiles)} profiles")
    
    def get_messages(self) -> List[MessengerMessage]:
        """Get all parsed messages"""
        return self.messages
    
    def get_text_messages(self) -> List[MessengerMessage]:
        """Get only text messages"""
        return [msg for msg in self.messages if msg.message_type == 'text']

    def get_attachment_messages(self) -> List[MessengerMessage]:
        """Get only attachment messages"""
        return [msg for msg in self.messages if msg.message_type == 'attachment']
    
    def get_entry_count(self) -> int:
        """Get the number of entries"""
        return len(self.entries)
    
    def get_message_count(self) -> int:
        """Get the total number of messages"""
        return len(self.messages)
    
    def get_user_profile(self, psid: str, fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Get Facebook Messenger user profile information using Graph API
        
        Args:
            psid: The Page-Scoped ID (PSID) of the user
            fields: List of fields to retrieve. Defaults to first_name, last_name, profile_pic.
        
        Returns:
            Dictionary with user profile data or None if request fails
            
        Example response:
            {
                "first_name": "Peter",
                "last_name": "Chang",
                "profile_pic": "https://fbcdn-profile-..."
            }
        """
        # Check in-memory cache first
        if psid in self.user_profiles:
            logger.debug(f"Returning cached profile for user: {psid}")
            return self.user_profiles[psid]

        # Check DynamoDB users table
        if USERS_TABLE_NAME:
            try:
                users_table = TableService(table_name=USERS_TABLE_NAME)
                db_profile = users_table.get_item({"id": psid})
                if db_profile:
                    # Remove internal fields before returning
                    db_profile.pop("id", None)
                    db_profile.pop("timestamp", None)
                    logger.info(f"Profile found in users table for: {psid}")
                    self.user_profiles[psid] = db_profile
                    return db_profile
            except Exception as e:
                logger.warning(f"Error reading users table, falling back to API: {e}")

        if not self.access_token:
            logger.warning("Access token not provided. Cannot fetch user profile.")
            return None

        # Validate PSID is numeric to prevent URL injection (e.g. file:// schemes)
        if not psid or not psid.isdigit():
            logger.error(f"Invalid PSID: must be numeric. Got: {psid!r}")
            return None

        logger.info(f"Profile NOT found in users table for: {psid}")
        
        # Default fields for Messenger - note: first_name and last_name are separate (unlike Instagram's single name field)
        if fields is None:
            fields = [
                'first_name',
                'last_name',
                'profile_pic'
            ]
        
        params = {
            'fields': ','.join(fields),
            'access_token': self.access_token
        }
        url = f"{self.GRAPH_API_BASE_URL}/{psid}?{parse.urlencode(params)}"
        
        # Defense-in-depth: ensure the URL uses HTTPS scheme only
        if not url.startswith("https://"):
            logger.error(f"Constructed URL does not use HTTPS scheme: {url}")
            return None
        
        try:
            logger.info(f"Fetching profile from Graph API for user: {psid}")
            
            req = request.Request(url, method='GET')
            with request.urlopen(req, timeout=10) as response:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310
                response_data = response.read()
                profile_data = json.loads(response_data.decode('utf-8'))
            
            logger.info(f"Successfully retrieved profile for user: {psid}")
            
            # Cache in memory
            self.user_profiles[psid] = profile_data

            # Persist to DynamoDB users table
            if USERS_TABLE_NAME:
                try:
                    users_table = TableService(table_name=USERS_TABLE_NAME)
                    item = {**profile_data, "id": psid, "timestamp": int(time.time()) + PROFILE_TTL_SECONDS}
                    users_table.table.put_item(Item=item)
                    logger.info(f"Saved profile to users table for: {psid}")
                except Exception as e:
                    logger.warning(f"Failed to save profile to users table: {e}")
            
            return profile_data
            
        except error.HTTPError as e:
            logger.error(f"HTTP error fetching user profile: {e.code} {e.reason}")
            try:
                error_body = e.read().decode('utf-8')
                logger.error(f"Response: {error_body}")
            except Exception as read_err:
                logger.warning(f"Could not read HTTP error response body: {read_err}")
            return None
        except error.URLError as e:
            logger.error(f"URL error fetching user profile: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching user profile: {e}")
            return None
    
    def get_display_name(self, profile: Optional[Dict[str, Any]], fallback: str) -> str:
        """
        Get display name from profile by concatenating first_name and last_name.
        
        Args:
            profile: User profile dictionary with first_name and last_name fields
            fallback: Fallback value to use if profile is None or missing name fields
            
        Returns:
            Display name as "first_name last_name" or fallback value
        """
        if not profile:
            return fallback
        
        first_name = profile.get('first_name', '')
        last_name = profile.get('last_name', '')
        
        if first_name or last_name:
            return f"{first_name} {last_name}".strip()
        
        return fallback
    
    def enrich_messages_with_profiles(self) -> List[Dict[str, Any]]:
        """
        Enrich all messages with sender profile information
        Uses cached profiles if available, otherwise fetches them
        
        Returns:
            List of dictionaries containing message data and sender profile
        """
        enriched_messages = []
        
        for message in self.messages:
            message_data = message.to_dict()
            
            # Get sender profile from cache or fetch it
            if message.sender_id:
                profile = self.user_profiles.get(message.sender_id)
                if not profile and self.access_token:
                    profile = self.get_user_profile(message.sender_id)
                
                if profile:
                    message_data['senderProfile'] = profile
            
            enriched_messages.append(message_data)
        
        return enriched_messages
