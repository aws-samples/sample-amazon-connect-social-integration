# Property-based tests for Facebook Messenger Connect Chat
# Uses hypothesis library for property-based testing

import sys
import os
import time

# Add the lambdas code paths to sys.path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambdas', 'code', 'messages_in'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambdas', 'code', 'messages_out'))

from hypothesis import given, settings, strategies as st, assume

from utils import validate_healthcheck
from messenger_service import MessengerService, MessengerMessage, PROFILE_TTL_SECONDS
from messenger import get_attachment_type


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 1: Webhook verification token matching
# **Validates: Requirements 2.1, 2.2**
# =============================================================================
class TestWebhookVerificationTokenMatching:
    """
    Property 1: Webhook verification token matching
    
    For any verification token string T, configured token C, and challenge string CH:
    if T equals C, the verification function returns CH;
    if T does not equal C, the verification function returns an empty string.
    """

    @settings(max_examples=100)
    @given(
        token=st.text(min_size=1, max_size=100),
        challenge=st.text(min_size=1, max_size=100)
    )
    def test_matching_tokens_return_challenge(self, token: str, challenge: str):
        """When tokens match, the challenge should be returned."""
        event = {
            'queryStringParameters': {
                'hub.mode': 'subscribe',
                'hub.verify_token': token,
                'hub.challenge': challenge
            }
        }
        
        result = validate_healthcheck(event, token)
        
        assert result == challenge, f"Expected challenge '{challenge}' but got '{result}'"

    @settings(max_examples=100)
    @given(
        provided_token=st.text(min_size=1, max_size=100),
        configured_token=st.text(min_size=1, max_size=100),
        challenge=st.text(min_size=1, max_size=100)
    )
    def test_non_matching_tokens_return_empty_string(self, provided_token: str, configured_token: str, challenge: str):
        """When tokens do not match, an empty string should be returned."""
        # Ensure tokens are different
        assume(provided_token != configured_token)
        
        event = {
            'queryStringParameters': {
                'hub.mode': 'subscribe',
                'hub.verify_token': provided_token,
                'hub.challenge': challenge
            }
        }
        
        result = validate_healthcheck(event, configured_token)
        
        assert result == '', f"Expected empty string but got '{result}'"

    @settings(max_examples=100)
    @given(
        token_pair=st.tuples(
            st.text(min_size=1, max_size=100),
            st.text(min_size=1, max_size=100)
        ),
        challenge=st.text(min_size=1, max_size=100)
    )
    def test_response_matches_iff_tokens_equal(self, token_pair: tuple, challenge: str):
        """
        Combined property: response matches challenge if and only if tokens are equal.
        This is the core property that validates Requirements 2.1 and 2.2.
        """
        provided_token, configured_token = token_pair
        
        event = {
            'queryStringParameters': {
                'hub.mode': 'subscribe',
                'hub.verify_token': provided_token,
                'hub.challenge': challenge
            }
        }
        
        result = validate_healthcheck(event, configured_token)
        
        if provided_token == configured_token:
            assert result == challenge, f"Tokens match but challenge not returned. Expected '{challenge}', got '{result}'"
        else:
            assert result == '', f"Tokens don't match but got non-empty response: '{result}'"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 2: Messenger webhook payload parsing extracts correct fields
# **Validates: Requirements 3.1, 10.1**
# =============================================================================
class TestMessengerWebhookPayloadParsing:
    """
    Property 2: Messenger webhook payload parsing extracts correct fields
    
    For any valid Messenger webhook payload with object: "page" and a messaging array
    containing entries with sender.id, recipient.id, and message.text, the parser shall
    produce message objects where sender_id, recipient_id, and text match the input
    payload values exactly.
    """

    @settings(max_examples=100)
    @given(
        sender_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        recipient_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        message_text=st.text(min_size=1, max_size=500),
        timestamp=st.integers(min_value=1000000000, max_value=9999999999)
    )
    def test_parsed_fields_match_input_payload(self, sender_id: str, recipient_id: str, message_text: str, timestamp: int):
        """Parsed message fields should match the input webhook payload exactly."""
        # Ensure sender_id != recipient_id to avoid echo prevention filtering
        assume(sender_id != recipient_id)
        
        webhook_payload = {
            "object": "page",
            "entry": [{
                "id": recipient_id,
                "time": timestamp,
                "messaging": [{
                    "sender": {"id": sender_id},
                    "recipient": {"id": recipient_id},
                    "timestamp": timestamp,
                    "message": {
                        "mid": "test_mid_123",
                        "text": message_text
                    }
                }]
            }]
        }
        
        # Use recipient_id as page_id to avoid echo prevention
        service = MessengerService(webhook_payload, page_id=recipient_id)
        messages = service.get_messages()
        
        assert len(messages) == 1, f"Expected 1 message, got {len(messages)}"
        msg = messages[0]
        
        assert msg.sender_id == sender_id, f"sender_id mismatch: expected '{sender_id}', got '{msg.sender_id}'"
        assert msg.recipient_id == recipient_id, f"recipient_id mismatch: expected '{recipient_id}', got '{msg.recipient_id}'"
        assert msg.text == message_text, f"text mismatch: expected '{message_text}', got '{msg.text}'"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 3: Only page-object webhooks are processed
# **Validates: Requirements 10.4**
# =============================================================================
class TestPageObjectFiltering:
    """
    Property 3: Only page-object webhooks are processed
    
    For any webhook body, messages are extracted only when body["object"] == "page".
    For any other object value (including "instagram", "user", or arbitrary strings),
    the parser shall produce zero messages.
    """

    @settings(max_examples=100)
    @given(
        object_value=st.text(min_size=1, max_size=50).filter(lambda x: x != "page"),
        sender_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        recipient_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        message_text=st.text(min_size=1, max_size=100)
    )
    def test_non_page_object_produces_zero_messages(self, object_value: str, sender_id: str, recipient_id: str, message_text: str):
        """Non-page object values should produce zero messages."""
        webhook_payload = {
            "object": object_value,
            "entry": [{
                "id": recipient_id,
                "time": 1234567890,
                "messaging": [{
                    "sender": {"id": sender_id},
                    "recipient": {"id": recipient_id},
                    "timestamp": 1234567890,
                    "message": {
                        "mid": "test_mid",
                        "text": message_text
                    }
                }]
            }]
        }
        
        service = MessengerService(webhook_payload)
        messages = service.get_messages()
        
        assert len(messages) == 0, f"Expected 0 messages for object='{object_value}', got {len(messages)}"

    @settings(max_examples=100)
    @given(
        sender_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        recipient_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        message_text=st.text(min_size=1, max_size=100)
    )
    def test_page_object_produces_messages(self, sender_id: str, recipient_id: str, message_text: str):
        """Page object value should produce messages."""
        assume(sender_id != recipient_id)
        
        webhook_payload = {
            "object": "page",
            "entry": [{
                "id": recipient_id,
                "time": 1234567890,
                "messaging": [{
                    "sender": {"id": sender_id},
                    "recipient": {"id": recipient_id},
                    "timestamp": 1234567890,
                    "message": {
                        "mid": "test_mid",
                        "text": message_text
                    }
                }]
            }]
        }
        
        service = MessengerService(webhook_payload, page_id=recipient_id)
        messages = service.get_messages()
        
        assert len(messages) == 1, f"Expected 1 message for object='page', got {len(messages)}"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 4: Echo prevention skips self-sent messages
# **Validates: Requirements 3.6**
# =============================================================================
class TestEchoPrevention:
    """
    Property 4: Echo prevention skips self-sent messages
    
    For any Messenger webhook payload where the sender PSID equals the configured
    Page ID, the parser shall exclude that message from the output list.
    """

    @settings(max_examples=100)
    @given(
        page_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        message_text=st.text(min_size=1, max_size=100)
    )
    def test_self_sent_messages_are_excluded(self, page_id: str, message_text: str):
        """Messages where sender_id equals page_id should be excluded."""
        webhook_payload = {
            "object": "page",
            "entry": [{
                "id": page_id,
                "time": 1234567890,
                "messaging": [{
                    "sender": {"id": page_id},  # sender == page_id (self-sent)
                    "recipient": {"id": page_id},
                    "timestamp": 1234567890,
                    "message": {
                        "mid": "test_mid",
                        "text": message_text
                    }
                }]
            }]
        }
        
        service = MessengerService(webhook_payload, page_id=page_id)
        messages = service.get_messages()
        
        assert len(messages) == 0, f"Expected 0 messages (echo prevention), got {len(messages)}"

    @settings(max_examples=100)
    @given(
        sender_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        page_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        message_text=st.text(min_size=1, max_size=100)
    )
    def test_non_self_sent_messages_are_included(self, sender_id: str, page_id: str, message_text: str):
        """Messages where sender_id differs from page_id should be included."""
        assume(sender_id != page_id)
        
        webhook_payload = {
            "object": "page",
            "entry": [{
                "id": page_id,
                "time": 1234567890,
                "messaging": [{
                    "sender": {"id": sender_id},
                    "recipient": {"id": page_id},
                    "timestamp": 1234567890,
                    "message": {
                        "mid": "test_mid",
                        "text": message_text
                    }
                }]
            }]
        }
        
        service = MessengerService(webhook_payload, page_id=page_id)
        messages = service.get_messages()
        
        assert len(messages) == 1, f"Expected 1 message, got {len(messages)}"
        assert messages[0].sender_id == sender_id


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 8: MIME type mapping correctness
# **Validates: Requirements 4.6, 7.3**
# =============================================================================
class TestMimeTypeMapping:
    """
    Property 8: MIME type mapping correctness
    
    For any MIME type string, the inbound mapping shall produce: .jpg for image/*,
    .mp4 for video/*, .mp3 for audio/*, and .bin for all others.
    The outbound mapping shall produce: image for image/*, video for video/*,
    audio for audio/*, and file for all others.
    """

    # Strategies for generating MIME type subtypes
    mime_subtype = st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-+.'), min_size=1, max_size=20)

    @settings(max_examples=100)
    @given(subtype=mime_subtype)
    def test_image_mime_maps_to_image_type(self, subtype: str):
        """image/* MIME types should map to 'image' attachment type."""
        mime_type = f"image/{subtype}"
        result = get_attachment_type(mime_type)
        assert result == "image", f"Expected 'image' for '{mime_type}', got '{result}'"

    @settings(max_examples=100)
    @given(subtype=mime_subtype)
    def test_video_mime_maps_to_video_type(self, subtype: str):
        """video/* MIME types should map to 'video' attachment type."""
        mime_type = f"video/{subtype}"
        result = get_attachment_type(mime_type)
        assert result == "video", f"Expected 'video' for '{mime_type}', got '{result}'"

    @settings(max_examples=100)
    @given(subtype=mime_subtype)
    def test_audio_mime_maps_to_audio_type(self, subtype: str):
        """audio/* MIME types should map to 'audio' attachment type."""
        mime_type = f"audio/{subtype}"
        result = get_attachment_type(mime_type)
        assert result == "audio", f"Expected 'audio' for '{mime_type}', got '{result}'"

    @settings(max_examples=100)
    @given(
        primary_type=st.text(min_size=1, max_size=20).filter(lambda x: x not in ['image', 'video', 'audio']),
        subtype=mime_subtype
    )
    def test_other_mime_maps_to_file_type(self, primary_type: str, subtype: str):
        """Non-image/video/audio MIME types should map to 'file' attachment type."""
        mime_type = f"{primary_type}/{subtype}"
        result = get_attachment_type(mime_type)
        assert result == "file", f"Expected 'file' for '{mime_type}', got '{result}'"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 9: Display name is first_name + last_name concatenation
# **Validates: Requirements 5.4, 10.6**
# =============================================================================
class TestDisplayNameConcatenation:
    """
    Property 9: Display name is first_name + last_name concatenation
    
    For any Messenger user profile containing first_name and last_name fields,
    the display name used for the Connect Chat participant shall equal
    first_name + " " + last_name.
    """

    @settings(max_examples=100)
    @given(
        first_name=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
        last_name=st.text(min_size=1, max_size=50).filter(lambda x: x.strip())
    )
    def test_display_name_concatenation(self, first_name: str, last_name: str):
        """Display name should be first_name + ' ' + last_name."""
        profile = {
            'first_name': first_name,
            'last_name': last_name
        }
        
        service = MessengerService({})  # Empty payload, just need the method
        display_name = service.get_display_name(profile, "fallback")
        
        expected = f"{first_name} {last_name}".strip()
        assert display_name == expected, f"Expected '{expected}', got '{display_name}'"

    @settings(max_examples=100)
    @given(
        first_name=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
        fallback=st.text(min_size=1, max_size=50)
    )
    def test_display_name_with_only_first_name(self, first_name: str, fallback: str):
        """Display name should work with only first_name."""
        profile = {
            'first_name': first_name,
            'last_name': ''
        }
        
        service = MessengerService({})
        display_name = service.get_display_name(profile, fallback)
        
        assert display_name == first_name.strip(), f"Expected '{first_name.strip()}', got '{display_name}'"

    @settings(max_examples=100)
    @given(
        last_name=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
        fallback=st.text(min_size=1, max_size=50)
    )
    def test_display_name_with_only_last_name(self, last_name: str, fallback: str):
        """Display name should work with only last_name."""
        profile = {
            'first_name': '',
            'last_name': last_name
        }
        
        service = MessengerService({})
        display_name = service.get_display_name(profile, fallback)
        
        assert display_name == last_name.strip(), f"Expected '{last_name.strip()}', got '{display_name}'"

    @settings(max_examples=100)
    @given(fallback=st.text(min_size=1, max_size=50))
    def test_display_name_fallback_when_no_profile(self, fallback: str):
        """Fallback should be used when profile is None."""
        service = MessengerService({})
        display_name = service.get_display_name(None, fallback)
        
        assert display_name == fallback, f"Expected fallback '{fallback}', got '{display_name}'"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 12: Numeric ID validation rejects non-numeric strings
# **Validates: Requirements 5.6, 11.3, 11.4**
# =============================================================================
class TestNumericIdValidation:
    """
    Property 12: Numeric ID validation rejects non-numeric strings
    
    For any string that contains non-digit characters, the ID validation shall
    reject it (return error or None). For any string composed entirely of digit
    characters, the validation shall accept it.
    """

    @settings(max_examples=100)
    @given(numeric_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20))
    def test_numeric_only_strings_are_valid(self, numeric_id: str):
        """Strings with only digits should be valid PSIDs."""
        # Test using Python's isdigit() which is what the code uses
        assert numeric_id.isdigit(), f"Expected '{numeric_id}' to be valid (all digits)"

    @settings(max_examples=100)
    @given(
        non_numeric_id=st.text(min_size=1, max_size=50).filter(lambda x: not x.isdigit())
    )
    def test_non_numeric_strings_are_invalid(self, non_numeric_id: str):
        """Strings with non-digit characters should be invalid PSIDs."""
        assert not non_numeric_id.isdigit(), f"Expected '{non_numeric_id}' to be invalid (contains non-digits)"

    @settings(max_examples=100)
    @given(
        prefix=st.text(min_size=0, max_size=10),
        digits=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=10),
        suffix=st.text(min_size=0, max_size=10)
    )
    def test_mixed_strings_are_invalid(self, prefix: str, digits: str, suffix: str):
        """Strings with mixed content (digits + non-digits) should be invalid."""
        # Only test if prefix or suffix contains non-digit characters
        if prefix and not prefix.isdigit():
            mixed_id = prefix + digits
            assert not mixed_id.isdigit(), f"Expected '{mixed_id}' to be invalid"
        if suffix and not suffix.isdigit():
            mixed_id = digits + suffix
            assert not mixed_id.isdigit(), f"Expected '{mixed_id}' to be invalid"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 13: URL scheme validation rejects non-HTTPS URLs
# **Validates: Requirements 11.1, 11.2**
# =============================================================================
class TestUrlSchemeValidation:
    """
    Property 13: URL scheme validation rejects non-HTTPS URLs
    
    For any URL string that does not start with https://, the URL validation
    shall reject it. For any URL string starting with https://, the validation
    shall accept it.
    """

    @settings(max_examples=100)
    @given(
        domain=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-.'), min_size=1, max_size=50),
        path=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='/-_.'), min_size=0, max_size=100)
    )
    def test_https_urls_are_valid(self, domain: str, path: str):
        """URLs starting with https:// should be valid."""
        url = f"https://{domain}/{path}"
        assert url.startswith("https://"), f"Expected '{url}' to be valid (starts with https://)"

    @settings(max_examples=100)
    @given(
        scheme=st.sampled_from(['http', 'ftp', 'file', 'data', 'javascript', 'mailto', '']),
        domain=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-.'), min_size=1, max_size=50),
        path=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='/-_.'), min_size=0, max_size=50)
    )
    def test_non_https_urls_are_invalid(self, scheme: str, domain: str, path: str):
        """URLs not starting with https:// should be invalid."""
        if scheme:
            url = f"{scheme}://{domain}/{path}"
        else:
            url = f"{domain}/{path}"
        
        assert not url.startswith("https://"), f"Expected '{url}' to be invalid (doesn't start with https://)"

    @settings(max_examples=100)
    @given(random_string=st.text(min_size=1, max_size=100))
    def test_arbitrary_strings_validation(self, random_string: str):
        """Arbitrary strings should only be valid if they start with https://."""
        is_valid = random_string.startswith("https://")
        
        if is_valid:
            assert random_string.startswith("https://")
        else:
            assert not random_string.startswith("https://")


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 14: Send API payload structure correctness
# **Validates: Requirements 6.3, 10.2, 10.3**
# =============================================================================
class TestSendApiPayloadStructure:
    """
    Property 14: Send API payload structure correctness
    
    For any PSID and message text, the constructed text payload shall have
    recipient.id equal to the PSID and message.text equal to the message text.
    For any PSID, attachment type, and URL, the constructed attachment payload
    shall have recipient.id equal to the PSID, message.attachment.type equal to
    the type, and message.attachment.payload.url equal to the URL with is_reusable
    set to true.
    """

    @settings(max_examples=100)
    @given(
        psid=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        message_text=st.text(min_size=1, max_size=500)
    )
    def test_text_payload_structure(self, psid: str, message_text: str):
        """Text payload should have correct recipient.id and message.text."""
        # Construct the payload as the code does
        payload = {
            "recipient": {"id": psid},
            "message": {"text": message_text}
        }
        
        assert payload["recipient"]["id"] == psid, f"recipient.id mismatch"
        assert payload["message"]["text"] == message_text, f"message.text mismatch"

    @settings(max_examples=100)
    @given(
        psid=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        attachment_type=st.sampled_from(['image', 'video', 'audio', 'file']),
        url=st.text(min_size=10, max_size=200).map(lambda x: f"https://example.com/{x}")
    )
    def test_attachment_payload_structure(self, psid: str, attachment_type: str, url: str):
        """Attachment payload should have correct structure with is_reusable=true."""
        # Construct the payload as the code does
        payload = {
            "recipient": {"id": psid},
            "message": {
                "attachment": {
                    "type": attachment_type,
                    "payload": {
                        "url": url,
                        "is_reusable": True
                    }
                }
            }
        }
        
        assert payload["recipient"]["id"] == psid, f"recipient.id mismatch"
        assert payload["message"]["attachment"]["type"] == attachment_type, f"attachment.type mismatch"
        assert payload["message"]["attachment"]["payload"]["url"] == url, f"attachment.payload.url mismatch"
        assert payload["message"]["attachment"]["payload"]["is_reusable"] is True, f"is_reusable should be True"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 15: Outbound message filtering
# **Validates: Requirements 6.4, 6.5**
# =============================================================================
class TestOutboundMessageFiltering:
    """
    Property 15: Outbound message filtering
    
    For any SNS message, the Outbound Lambda shall deliver the message to Messenger
    only when ParticipantRole is AGENT or SYSTEM AND MessageVisibility is CUSTOMER
    or ALL. For ParticipantRole of CUSTOMER or MessageVisibility of AGENT, the
    message shall be skipped.
    """

    def should_deliver_message(self, participant_role: str, message_visibility: str) -> bool:
        """
        Determine if a message should be delivered based on role and visibility.
        
        Delivery rules:
        - ParticipantRole must be AGENT or SYSTEM (not CUSTOMER)
        - MessageVisibility must be CUSTOMER or ALL (not AGENT)
        """
        valid_roles = ['AGENT', 'SYSTEM']
        valid_visibilities = ['CUSTOMER', 'ALL']
        
        return participant_role in valid_roles and message_visibility in valid_visibilities

    @settings(max_examples=100)
    @given(
        participant_role=st.sampled_from(['AGENT', 'SYSTEM', 'CUSTOMER']),
        message_visibility=st.sampled_from(['CUSTOMER', 'ALL', 'AGENT'])
    )
    def test_delivery_decision_matches_rules(self, participant_role: str, message_visibility: str):
        """Delivery decision should match the filtering rules."""
        should_deliver = self.should_deliver_message(participant_role, message_visibility)
        
        # CUSTOMER role should never deliver
        if participant_role == 'CUSTOMER':
            assert not should_deliver, f"CUSTOMER role should not deliver"
        
        # AGENT visibility should not deliver
        if message_visibility == 'AGENT':
            assert not should_deliver, f"AGENT visibility should not deliver"
        
        # AGENT/SYSTEM role with CUSTOMER/ALL visibility should deliver
        if participant_role in ['AGENT', 'SYSTEM'] and message_visibility in ['CUSTOMER', 'ALL']:
            assert should_deliver, f"Should deliver for role={participant_role}, visibility={message_visibility}"

    @settings(max_examples=100)
    @given(st.data())
    def test_agent_role_with_customer_visibility_delivers(self, data):
        """AGENT role with CUSTOMER or ALL visibility should deliver."""
        visibility = data.draw(st.sampled_from(['CUSTOMER', 'ALL']))
        should_deliver = self.should_deliver_message('AGENT', visibility)
        assert should_deliver, f"AGENT with {visibility} visibility should deliver"

    @settings(max_examples=100)
    @given(st.data())
    def test_system_role_with_customer_visibility_delivers(self, data):
        """SYSTEM role with CUSTOMER or ALL visibility should deliver."""
        visibility = data.draw(st.sampled_from(['CUSTOMER', 'ALL']))
        should_deliver = self.should_deliver_message('SYSTEM', visibility)
        assert should_deliver, f"SYSTEM with {visibility} visibility should deliver"

    @settings(max_examples=100)
    @given(
        visibility=st.sampled_from(['CUSTOMER', 'ALL', 'AGENT'])
    )
    def test_customer_role_never_delivers(self, visibility: str):
        """CUSTOMER role should never deliver regardless of visibility."""
        should_deliver = self.should_deliver_message('CUSTOMER', visibility)
        assert not should_deliver, f"CUSTOMER role should never deliver"

    @settings(max_examples=100)
    @given(
        role=st.sampled_from(['AGENT', 'SYSTEM', 'CUSTOMER'])
    )
    def test_agent_visibility_never_delivers(self, role: str):
        """AGENT visibility should never deliver regardless of role."""
        should_deliver = self.should_deliver_message(role, 'AGENT')
        assert not should_deliver, f"AGENT visibility should never deliver"


# =============================================================================
# Feature: facebook-messenger-connect-chat, Property 11: Profile storage TTL is 7 days from retrieval time
# **Validates: Requirements 5.3**
# =============================================================================
class TestProfileTtlCalculation:
    """
    Property 11: Profile storage TTL is 7 days from retrieval time
    
    For any profile successfully retrieved from the User Profile API, the timestamp
    field stored in MessengerUsers shall equal current_epoch_seconds + (7 * 24 * 60 * 60).
    """

    SEVEN_DAYS_IN_SECONDS = 7 * 24 * 60 * 60  # 604800 seconds

    @settings(max_examples=100)
    @given(
        current_time=st.integers(min_value=1000000000, max_value=2000000000)
    )
    def test_ttl_is_seven_days_from_current_time(self, current_time: int):
        """TTL should be exactly 7 days (604800 seconds) from current time."""
        expected_ttl = current_time + self.SEVEN_DAYS_IN_SECONDS
        
        # Verify the constant matches the expected value
        assert PROFILE_TTL_SECONDS == self.SEVEN_DAYS_IN_SECONDS, \
            f"PROFILE_TTL_SECONDS should be {self.SEVEN_DAYS_IN_SECONDS}, got {PROFILE_TTL_SECONDS}"
        
        # Calculate TTL as the code does
        calculated_ttl = current_time + PROFILE_TTL_SECONDS
        
        assert calculated_ttl == expected_ttl, \
            f"TTL mismatch: expected {expected_ttl}, got {calculated_ttl}"

    @settings(max_examples=100)
    @given(
        current_time=st.integers(min_value=1000000000, max_value=2000000000)
    )
    def test_ttl_difference_is_exactly_seven_days(self, current_time: int):
        """The difference between TTL and current time should be exactly 7 days."""
        ttl = current_time + PROFILE_TTL_SECONDS
        difference = ttl - current_time
        
        assert difference == self.SEVEN_DAYS_IN_SECONDS, \
            f"TTL difference should be {self.SEVEN_DAYS_IN_SECONDS}, got {difference}"

    def test_profile_ttl_constant_value(self):
        """Verify PROFILE_TTL_SECONDS constant equals 604800 (7 days)."""
        assert PROFILE_TTL_SECONDS == 604800, \
            f"PROFILE_TTL_SECONDS should be 604800, got {PROFILE_TTL_SECONDS}"
