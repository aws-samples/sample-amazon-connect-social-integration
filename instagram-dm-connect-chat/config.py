
INSTAGRAM_WEBHOOK_PARAM_NAME = "/meta/instagram/webhook/url"

INSTAGRAM_CONFIG_PARAM_NAME = "/meta/instagram/config"
INSTAGRAM_CONFIG_PARAM_CONTENT = {
        "instance_id": "YOUR_INSTANCE_ID", 
        "contact_flow_id": "YOUR_CONTACT_FLOW_ID",
        "INSTAGRAM_VERIFICATION_TOKEN": "CREATE_ONE",
        "instagram_account_id": "YOUR_INSTAGRAM_ACC_ID"
}

META_API_VERSION = "v23.0"

SECRET_NAME = "instagram-token"  # nosec B105 - this is the secret name/identifier, not a hardcoded credential