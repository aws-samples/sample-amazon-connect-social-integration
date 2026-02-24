RAW_TABLE_PARAM_NAME = "/table/raw"
PROCESSED_TABLE_PARAM_NAME = "/table/processed"
API_CONFIG_PARAM_NAME = "/config/api"
CONNECT_CONFIG_PARAM_NAME = "/config/connect"
CONNECT_CONFIG_CONTENT = {
    "connect_config": {
        "instance_id": "INSTANCE_ID",
        "contact_flow_id": "CONTACT_FLOW_ID",
    },
    "task_mapping": {
        "name_field": "id",
        "description_field": "comment",
        "reference_field": "id",
    },
}

API_CONFIG_CONTENT = {
    "url": "https://api.walls.io/v1/posts",
    "method": "GET",
    "headers": {},
    "params": {
        "access_token": "OWN_ACCESS_TOKEN",
        "limit": 10,
        "after": None,
        "before": None,
        "fields": "id,comment,cta,text,url,language,type,external_post_id,external_image,external_name,external_fullname,external_user_id,post_image,post_image_cdn,post_video,post_video_cdn,permalink,post_link,post_link_wallsio,is_pinned,sentiment,status,created,created_timestamp,modified,modified_timestamp,userlink,location,latitude,longitude,album_hash",
        "types": "wallsio,direct_post,facebook,flickr,instagram,linkedin,messenger,pinterest,reddit,rss,tumblr,vimeo,youtube",
        "media_types": "text,image,video",
        "languages": None,
        "pinned_only": 0,
        "include_inactive": 0,
        "include_source": 1,
        "sort": "-id",
    },
    "body": {},
}

WALLSIO_SECRET_NAME = "wallsio-secret"  # nosec B105 - secret name reference, not a password

PROCESS_CONFIG_PARAM_NAME = "/config/process"

PROCESS_CONFIG_CONTENT = {
    "bedrock_config": {
        "enabled": True,
        "prompt": """You are a social media customer service analyst for an airline brand. Your task is to analyze social media posts (Instagram, Twitter, Facebook, etc.) and determine the appropriate response strategy.

For each post, analyze the following:

1. MESSAGE REFORMULATION:
   - Extract the core message or concern from the post
   - Reformulate it in a clear, professional manner suitable for internal processing
   - Include relevant context (location, sentiment, specific issues mentioned)

2. INTERVENTION ASSESSMENT:
   - Determine if this requires direct customer contact or response
   - Consider: complaints, service issues, questions, safety concerns, lost items
   - Positive feedback or general comments may not require intervention

3. PRIORITY LEVEL (1-5):
   - Priority 1: Critical issues (lost baggage, safety concerns, severe service failures, stranded passengers)
   - Priority 2: Significant issues (flight delays, cancellations, booking problems, service complaints)
   - Priority 3: Moderate issues (minor service issues, general complaints, refund requests)
   - Priority 4: Low priority (general questions, feedback, suggestions)
   - Priority 5: Minimal priority (positive feedback, general comments, Q&A responses)

4. RECOMMENDED ACTION:
   - Provide specific, actionable recommendation
   - Examples: "Contact customer immediately via DM", "Escalate to baggage services", "Respond with flight status", "Monitor only", "Thank customer for positive feedback"

Analyze the post objectively and provide structured output that enables efficient customer service response.""",
        "model_id": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    }
}
