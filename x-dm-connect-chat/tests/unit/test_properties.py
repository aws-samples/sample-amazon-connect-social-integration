import sys
import os
import hmac
import hashlib
import base64
from unittest.mock import MagicMock

# Add messages_in directory to sys.path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambdas', 'code', 'messages_in'))

# Mock boto3 and table_service before importing x_service to avoid AWS dependency
sys.modules['boto3'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()
sys.modules['botocore.config'] = MagicMock()
sys.modules['boto3.dynamodb'] = MagicMock()
sys.modules['boto3.dynamodb.conditions'] = MagicMock()

# Set env vars to prevent issues (won't actually connect)
os.environ.setdefault('TABLE_NAME', 'test-active-connections-table')
os.environ.setdefault('USERS_TABLE_NAME', 'test-users-table')

from hypothesis import given, settings
from hypothesis import strategies as st

from utils import compute_crc_response
from x_service import XMessage, XService


# Feature: x-dm-connect-chat, Property 1: CRC response is correct HMAC-SHA256
# **Validates: Requirements 2.1, 2.2**
@given(
    crc_token=st.text(),
    consumer_secret=st.text()
)
@settings(max_examples=100)
def test_crc_response_is_correct_hmac_sha256(crc_token, consumer_secret):
    """
    For any crc_token and consumer_secret, compute_crc_response() must return
    a dict with response_token equal to sha256=<base64(HMAC-SHA256(consumer_secret, crc_token))>.
    """
    result = compute_crc_response(crc_token, consumer_secret)

    # Independent computation
    expected_digest = hmac.new(
        consumer_secret.encode('utf-8'),
        crc_token.encode('utf-8'),
        hashlib.sha256
    ).digest()
    expected_hash = base64.b64encode(expected_digest).decode('utf-8')
    expected = {"response_token": f"sha256={expected_hash}"}

    assert result == expected, f"Expected {expected}, got {result}"


# --- Strategies for X DM event generation ---

def x_dm_event_strategy():
    """Strategy to generate a single valid X DM event dict."""
    return st.fixed_dictionaries({
        'type': st.just('message_create'),
        'id': st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
        'created_timestamp': st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=15),
        'message_create': st.fixed_dictionaries({
            'target': st.fixed_dictionaries({
                'recipient_id': st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20)
            }),
            'sender_id': st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20),
            'message_data': st.fixed_dictionaries({
                'text': st.text(min_size=1, max_size=280),
                'entities': st.just({})
            })
        })
    })


# Feature: x-dm-connect-chat, Property 2: DM event parsing extracts correct fields
# **Validates: Requirements 3.1**
@given(
    events=st.lists(x_dm_event_strategy(), min_size=1, max_size=10)
)
@settings(max_examples=100)
def test_dm_event_parsing_extracts_correct_fields(events):
    """
    For any valid direct_message_events payload, the parser shall extract
    a list of messages where each message's sender_id, text, and created_timestamp
    match the corresponding values in the original payload.
    """
    payload = {
        'for_user_id': '000000',
        'direct_message_events': events
    }

    # Use XService without echo prevention (no x_account_id)
    service = XService(event_body=payload)
    parsed_messages = service.get_messages()

    assert len(parsed_messages) == len(events)

    for i, msg in enumerate(parsed_messages):
        original = events[i]
        assert msg.sender_id == original['message_create']['sender_id'], \
            f"sender_id mismatch at index {i}"
        assert msg.text == original['message_create']['message_data']['text'], \
            f"text mismatch at index {i}"
        assert msg.created_timestamp == original['created_timestamp'], \
            f"created_timestamp mismatch at index {i}"


# Feature: x-dm-connect-chat, Property 3: Echo prevention filters own-account messages
# **Validates: Requirements 3.2**
@given(
    events=st.lists(x_dm_event_strategy(), min_size=1, max_size=10),
    x_account_id=st.text(alphabet=st.characters(whitelist_categories=('Nd',)), min_size=1, max_size=20)
)
@settings(max_examples=100)
def test_echo_prevention_filters_own_account_messages(events, x_account_id):
    """
    For any list of DM events and any configured x_account_id, the parsed message
    list shall exclude all events where sender_id equals x_account_id, and include
    all events where sender_id does not equal x_account_id.
    """
    # Inject some events with sender_id matching x_account_id
    modified_events = []
    for event in events:
        modified_events.append(event)
    # Also add an echo event explicitly
    echo_event = {
        'type': 'message_create',
        'id': '999',
        'created_timestamp': '1234567890',
        'message_create': {
            'target': {'recipient_id': 'someone'},
            'sender_id': x_account_id,
            'message_data': {'text': 'echo message', 'entities': {}}
        }
    }
    modified_events.append(echo_event)

    payload = {
        'for_user_id': x_account_id,
        'direct_message_events': modified_events
    }

    service = XService(event_body=payload, x_account_id=x_account_id)
    parsed_messages = service.get_messages()

    # Count expected non-echo messages
    expected_count = sum(
        1 for e in modified_events
        if e['message_create']['sender_id'] != x_account_id
    )

    assert len(parsed_messages) == expected_count, \
        f"Expected {expected_count} messages after echo filtering, got {len(parsed_messages)}"

    # Verify no message has sender_id == x_account_id
    for msg in parsed_messages:
        assert msg.sender_id != x_account_id, \
            f"Echo message not filtered: sender_id={msg.sender_id}"


# Feature: x-dm-connect-chat, Property 6: Display name derived from profile
# **Validates: Requirements 6.3, 6.4**
@given(
    profile=st.one_of(
        st.none(),
        st.fixed_dictionaries({}),
        st.fixed_dictionaries({'username': st.text(min_size=1, max_size=50)}),
        st.fixed_dictionaries({'name': st.just('')}),
        st.fixed_dictionaries({'name': st.text(min_size=1, max_size=100)}),
        st.fixed_dictionaries({
            'name': st.text(min_size=1, max_size=100),
            'username': st.text(min_size=1, max_size=50)
        }),
    ),
    fallback=st.text(min_size=1, max_size=50)
)
@settings(max_examples=100)
def test_display_name_derived_from_profile(profile, fallback):
    """
    For any X user profile containing a name field, the display name shall equal
    the profile's name value. If the profile is None or missing the name field,
    the display name shall fall back to the X user ID.
    """
    result = XService.get_display_name(profile, fallback)

    if profile and profile.get('name'):
        assert result == profile['name'], \
            f"Expected profile name '{profile['name']}', got '{result}'"
    else:
        assert result == fallback, \
            f"Expected fallback '{fallback}', got '{result}'"


# --- Strategy for non-DM payloads ---

def non_dm_payload_strategy():
    """Strategy to generate random dict payloads that do NOT contain 'direct_message_events' key."""
    return st.dictionaries(
        keys=st.text(min_size=1, max_size=30).filter(lambda k: k != 'direct_message_events'),
        values=st.one_of(
            st.text(max_size=50),
            st.integers(),
            st.booleans(),
            st.none(),
        ),
        min_size=0,
        max_size=5,
    )


# Feature: x-dm-connect-chat, Property 7: Non-DM payloads are accepted without processing
# **Validates: Requirements 9.1**
@given(
    payload=non_dm_payload_strategy()
)
@settings(max_examples=100)
def test_non_dm_payloads_accepted_without_processing(payload):
    """
    For any webhook POST payload that does not contain a direct_message_events key,
    the inbound handler shall return HTTP 200 and produce zero parsed messages.
    """
    # Part 1: XService produces zero messages
    service = XService(event_body=payload)
    assert service.get_message_count() == 0, \
        f"Expected 0 messages for non-DM payload, got {service.get_message_count()}"

    # Part 2: lambda_handler returns HTTP 200
    from unittest.mock import patch
    import json as json_mod

    # Ensure required env vars are set
    os.environ.setdefault('CONFIG_PARAM_NAME', '/x/dm/config')
    os.environ.setdefault('SECRET_ARN', 'arn:aws:secretsmanager:us-east-1:123456789:secret:test')

    event = {
        'httpMethod': 'POST',
        'body': json_mod.dumps(payload),
    }

    mock_config = {
        'instance_id': 'test-instance',
        'contact_flow_id': 'test-flow',
        'x_account_id': '12345',
    }

    with patch('lambda_function.get_ssm_parameter', return_value=mock_config):
        from lambda_function import lambda_handler
        result = lambda_handler(event, None)

    assert result['statusCode'] == 200, \
        f"Expected HTTP 200, got {result['statusCode']}"


# --- Outbound Handler Property Tests ---
# Import the outbound lambda_function module with mocked dependencies.
# The outbound lambda_function.py has module-level initialization that calls
# get_secret_value(), TableService(), and boto3.client(). We mock these before importing.

import json as _json
import importlib as _importlib
from unittest.mock import patch as _patch, MagicMock as _MagicMock

_messages_out_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'lambdas', 'code', 'messages_out')

# Ensure SECRET_ARN is set before importing outbound lambda_function (it accesses os.environ["SECRET_ARN"] at module level)
os.environ.setdefault('SECRET_ARN', 'arn:aws:secretsmanager:us-east-1:123456789:secret:test')

_mock_credentials = {
    "consumer_key": "test-consumer-key",
    "consumer_secret": "test-consumer-secret",
    "access_token": "test-access-token",
    "access_token_secret": "test-access-token-secret",
}


def _import_outbound_lambda():
    """Import the outbound lambda_function with mocked module-level dependencies."""
    # Save current state
    saved_path = sys.path[:]
    saved_modules = {}
    for mod_name in ['config_service', 'table_service', 'x_sender', 'lambda_function']:
        if mod_name in sys.modules:
            saved_modules[mod_name] = sys.modules.pop(mod_name)

    # Prepend messages_out to sys.path so its modules are found first
    sys.path.insert(0, _messages_out_dir)

    # Create mock modules for the outbound handler's dependencies
    mock_config_service = _MagicMock()
    mock_config_service.get_secret_value = _MagicMock(return_value=_mock_credentials)
    sys.modules['config_service'] = mock_config_service

    mock_table_module = _MagicMock()
    sys.modules['table_service'] = mock_table_module

    mock_x_sender = _MagicMock()
    sys.modules['x_sender'] = mock_x_sender

    # Import the outbound lambda_function
    import lambda_function as outbound_lambda

    # Restore state
    sys.path[:] = saved_path
    for mod_name in ['config_service', 'table_service', 'x_sender', 'lambda_function']:
        sys.modules.pop(mod_name, None)
    for mod_name, mod in saved_modules.items():
        sys.modules[mod_name] = mod

    return outbound_lambda, mock_x_sender, mock_table_module


_outbound_lambda, _mock_x_sender, _mock_table_module = _import_outbound_lambda()


# Feature: x-dm-connect-chat, Property 4: Outbound message routing by participant role
# **Validates: Requirements 4.1, 4.3**
@given(
    participant_role=st.sampled_from(["AGENT", "SYSTEM", "CUSTOMER"]),
    message_visibility=st.sampled_from(["CUSTOMER", "ALL", "AGENT"]),
    content=st.text(min_size=1, max_size=200),
    contact_id=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Nd')), min_size=1, max_size=30),
)
@settings(max_examples=100)
def test_outbound_message_routing_by_participant_role(participant_role, message_visibility, content, contact_id):
    """
    For any SNS message record, the outbound handler shall process the message
    (look up contact and send DM) if and only if ParticipantRole is not CUSTOMER
    and MessageVisibility is CUSTOMER or ALL.
    """
    record = {
        "Sns": {
            "Message": _json.dumps({
                "Type": "MESSAGE",
                "ParticipantRole": participant_role,
                "Content": content,
                "ContactId": contact_id,
                "InitialContactId": contact_id,
            }),
            "MessageAttributes": {
                "MessageVisibility": {"Value": message_visibility},
                "ContentType": {"Value": "text/plain"},
            }
        }
    }

    # Mock send_x_text on the outbound lambda module and get_contact
    mock_send = _MagicMock()
    mock_get_contact = _MagicMock(return_value={"userId": "user-123", "connectionToken": "tok-123"})

    with _patch.object(_outbound_lambda, 'send_x_text', mock_send), \
         _patch.object(_outbound_lambda, 'get_contact', mock_get_contact):
        _outbound_lambda.process_record(_mock_credentials, record)

    should_process = (participant_role != "CUSTOMER") and (message_visibility in ("CUSTOMER", "ALL"))

    if should_process:
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][1] == content, f"Expected content '{content}', got '{call_args[0][1]}'"
    else:
        mock_send.assert_not_called()


# Feature: x-dm-connect-chat, Property 5: Session cleanup on disconnect events
# **Validates: Requirements 5.1, 5.2**
@given(
    content_type=st.sampled_from([
        "application/vnd.amazonaws.connect.event.participant.left",
        "application/vnd.amazonaws.connect.event.chat.ended",
    ]),
    initial_contact_id=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Nd')), min_size=1, max_size=40),
)
@settings(max_examples=100)
def test_session_cleanup_on_disconnect_events(content_type, initial_contact_id):
    """
    For any SNS EVENT record with disconnect content types (participant.left, chat.ended)
    and random InitialContactId, the outbound handler shall delete the session record
    from the Active Connections table using the InitialContactId.
    """
    message = {
        "Type": "EVENT",
        "ParticipantRole": "AGENT",
        "InitialContactId": initial_contact_id,
        "ContactId": initial_contact_id,
        "Content": "",
    }
    message_attributes = {
        "MessageVisibility": {"Value": "ALL"},
        "ContentType": {"Value": content_type},
    }

    # Mock the table_service.delete_item on the outbound lambda module
    mock_delete = _MagicMock()
    _outbound_lambda.table_service.delete_item = mock_delete

    _outbound_lambda.process_event(message_attributes, message)

    mock_delete.assert_called_once_with(key={"contactId": initial_contact_id})

