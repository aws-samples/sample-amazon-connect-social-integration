
MESSENGER_WEBHOOK_PARAM_NAME = "/meta/messenger/webhook/url"

MESSENGER_CONFIG_PARAM_NAME = "/meta/messenger/config"
MESSENGER_CONFIG_PARAM_CONTENT = {
        "instance_id": "YOUR_INSTANCE_ID",
        "contact_flow_id": "YOUR_CONTACT_FLOW_ID",
        "MESSENGER_VERIFICATION_TOKEN": "CREATE_ONE"
}

META_API_VERSION = "v24.0"

SECRET_NAME = "messenger-page-token"  # nosec B105 - this is the secret name/identifier, not a hardcoded credential
