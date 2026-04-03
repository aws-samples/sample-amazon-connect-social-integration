# X (Twitter) DMs & Amazon Connect Chat

<table>
<tr>
<td width="50%">

_Learn how to bridge X (Twitter) Direct Messages and Amazon Connect Chat for seamless customer service. This step-by-step guide covers the full architecture using AWS CDK, AWS Lambda, Amazon API Gateway, Amazon DynamoDB, and Amazon Connect. From receiving customer DMs to routing them to agents, forwarding agent replies back to X, and handling attachments in both directions — all with automatic session management, CRC webhook validation, and user profile caching via the Tweepy SDK._

</td>
<td width="50%">

![Demo](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/x-dm-connect-chat/x-connect-chat.gif)

</td>
</tr>
</table>

Your customers are already on X. They follow your brand, engage with your posts, and when they need help — they send a DM. If your support team has to switch between X and their contact center tool, you're losing time and context.

In this blog, you'll learn how to connect X Direct Messages directly to Amazon Connect Chat, so your agents can handle X conversations from the same workspace they use for every other channel. No app switching, no copy-pasting, no lost messages.

Check out the code at [Github](https://github.com/aws-samples/sample-amazon-connect-social-integration)

## What you'll build

A bidirectional messaging bridge between X DMs and Amazon Connect that:

1. Receives incoming X DMs via the Account Activity API webhook and routes them to Amazon Connect Chat
2. Forwards agent replies from Amazon Connect back to X through the Tweepy SDK
3. Manages chat sessions automatically — creating new ones, reusing active ones, and cleaning up expired ones
4. Caches X user profiles (name, username, profile image) in DynamoDB to reduce API calls
5. Handles attachments in both directions — images, videos, and GIFs from customers, and images and videos from agents
6. Prevents echo loops by filtering out messages sent by your own X account

The end result: agents see X conversations as regular chat contacts in their Amazon Connect workspace, complete with the customer's X display name and profile information.

## Architecture

![Architecture Diagram](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/x-dm-connect-chat/x-connect-chat.svg)

Here's how it flows:

1. A customer sends a DM on X. The Account Activity API delivers the webhook event to an API Gateway endpoint
2. The Inbound Handler Lambda validates the webhook (CRC challenge), parses the message, and looks up or creates an Amazon Connect Chat session
3. The customer's X profile is fetched via the Tweepy SDK and cached in DynamoDB
4. Text messages and attachments are forwarded into the Connect Chat session via the Participant API
5. When an agent replies, Amazon Connect publishes the event to an SNS topic via contact streaming
6. The Outbound Handler Lambda picks up the SNS event, looks up the customer's X user ID, and sends the reply back as a DM through the Tweepy SDK

## Inbound: X → Amazon Connect

When a customer sends a DM to your business X account, the inbound path handles everything from webhook validation to message delivery.

### 1. CRC Webhook Validation

X uses a Challenge-Response Check (CRC) to verify webhook ownership — this is fundamentally different from Meta's approach used in the Instagram and Facebook Messenger integrations. Instead of comparing a shared secret string, X sends a `crc_token` that must be hashed with your Consumer Secret using HMAC-SHA256:

```python
def compute_crc_response(crc_token, consumer_secret):
    digest = hmac.new(
        consumer_secret.encode('utf-8'),
        crc_token.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    encoded_hash = base64.b64encode(digest).decode('utf-8')
    return {"response_token": f"sha256={encoded_hash}"}
```

X sends this challenge both during initial webhook registration and periodically afterward to re-validate. The Lambda handles it automatically on every GET request.

### 2. Message Parsing and Echo Prevention

For POST requests (actual DM events), the `XService` class parses the `direct_message_events` payload. Each event contains the sender ID, recipient ID, text content, and any media attachments:

```python
class XMessage:
    def __init__(self, event_data):
        message_create = event_data.get('message_create', {})
        message_data = message_create.get('message_data', {})
        self.sender_id = message_create.get('sender_id')
        self.text = message_data.get('text')
        self.recipient_id = message_create.get('target', {}).get('recipient_id')
        
        # Parse attachment if present
        self.attachment = message_data.get('attachment')
        if self.attachment and self.attachment.get('type') == 'media':
            media = self.attachment.get('media', {})
            self.attachment_url = media.get('media_url_https')
            self.attachment_type = media.get('type')  # photo, animated_gif, video
```

The service filters out messages sent by your own X account ID to prevent echo loops — when your account sends a reply, X also delivers it as a webhook event.

### 3. User Profile Retrieval and Caching

X webhook payloads include inline user profile data in a `users` dictionary, which the service extracts first. For any missing profiles, it falls back to a three-tier lookup:

```python
def get_user_profile(self, user_id):
    # Check in-memory cache first
    if user_id in self.user_profiles:
        return self.user_profiles[user_id]

    # Check DynamoDB users table
    if USERS_TABLE_NAME:
        users_table = TableService(table_name=USERS_TABLE_NAME)
        db_profile = users_table.get_item({"id": user_id})
        if db_profile:
            return db_profile

    # Fetch from X API via Tweepy as last resort
    client = tweepy.Client(
        consumer_key=credentials.get('consumer_key'),
        consumer_secret=credentials.get('consumer_secret'),
        access_token=credentials.get('access_token'),
        access_token_secret=credentials.get('access_token_secret')
    )
    response = client.get_user(id=user_id, user_fields=['name', 'username', 'profile_image_url'])
    # ... cache in DynamoDB with 7-day TTL
```

The profile includes `name`, `username`, and `profile_image_url`. Profiles are cached in a DynamoDB table with a 7-day TTL, so repeat conversations skip the API call entirely.

### 4. Session Management

The handler checks DynamoDB for an existing chat session using the sender's X user ID:

- If a session exists, it sends the message using the stored `connectionToken`. If the token is expired (AccessDeniedException), it automatically creates a new session.
- If no session exists, it calls `StartChatContact` to create a new Amazon Connect Chat, starts contact streaming to the SNS topic, creates a participant connection, and stores everything in DynamoDB.

The contact attributes include the channel name ("X"), the customer ID, and the customer's display name — making it easy to identify the source channel in Contact Flows and agent routing.

### 5. Attachment Handling (Inbound)

When a customer sends an image, GIF, or video, the handler downloads it from X's CDN and uploads it to the Connect Chat session. X media URLs come in two flavors:

- `pbs.twimg.com` — publicly accessible, downloaded directly
- `ton.twitter.com` — requires OAuth 1.0a authentication via Tweepy

The upload uses the three-step Participant API flow: `start_attachment_upload` → PUT to pre-signed URL → `complete_attachment_upload`. If anything fails, the handler falls back to sending the media URL as a text message.

For attachments that include a caption, the text is cleaned up by stripping the auto-appended `t.co` media link that X adds to the message body.

## Outbound: Amazon Connect → X

When an agent replies from the Amazon Connect workspace, the outbound path delivers the message back to X.

### 1. Streaming Events via SNS

Amazon Connect publishes chat streaming events to an SNS topic. The Outbound Handler Lambda subscribes to this topic and processes three event types:

- `MESSAGE` — text messages from the agent
- `ATTACHMENT` — file attachments sent by the agent
- `EVENT` — participant join/leave and chat ended events

Messages from the `CUSTOMER` role are skipped to avoid processing the customer's own messages again.

### 2. Sending Text Messages

For text messages with `CUSTOMER` or `ALL` visibility, the handler looks up the customer's X user ID from DynamoDB and sends the reply via the Tweepy v2 API:

```python
def send_x_text(credentials, text, recipient_id):
    client = tweepy.Client(
        consumer_key=credentials["consumer_key"],
        consumer_secret=credentials["consumer_secret"],
        access_token=credentials["access_token"],
        access_token_secret=credentials["access_token_secret"],
    )
    response = client.create_direct_message(
        participant_id=recipient_id,
        text=text,
    )
    return response
```

### 3. Sending Attachments

When an agent sends a file from the Connect Chat widget, the handler retrieves a signed URL for the attachment, downloads it, and uploads it to X via the v1.1 media upload endpoint (OAuth 1.0a). The media ID is then used to send a DM with the attachment:

| MIME type | X media category | Upload method |
|---|---|---|
| `image/jpeg`, `image/png`, `image/webp` | `dm_image` | `media_upload` |
| `image/gif` | `dm_gif` | `chunked_upload` |
| `video/mp4` | `dm_video` | `chunked_upload` |
| everything else | — | Sent as plain-text link |

X DMs only support images and videos as native media. Unsupported types (PDFs, documents, etc.) are sent as plain-text URLs so the customer still has access to the content.

### 4. Session Cleanup

When a participant leaves or the chat ends, the handler deletes the connection record from DynamoDB so the next inbound message starts a fresh session.

## Message Types Supported

| Direction | Text | Images | Videos | GIFs |
|---|---|---|---|---|
| Inbound (customer → agent) | ✅ | ✅ | ✅ | ✅ |
| Outbound (agent → customer) | ✅ | ✅ | ✅ | ✅ |

Unsupported media types (PDFs, documents, etc.) are sent as plain-text links in the outbound direction.

## What Gets Deployed

| Resource | Service | Purpose |
|---|---|---|
| `/webhooks` endpoint (GET & POST) | API Gateway | Receives X CRC challenges (GET) and inbound DM events (POST) |
| Inbound Handler | Lambda | Processes X DM events and routes them to Amazon Connect Chat |
| Outbound Handler | Lambda | Sends agent replies back to X as DMs via the Tweepy SDK |
| Active Connections table | DynamoDB | Tracks open chat sessions (`contactId` PK, `userId` GSI) |
| X Users table | DynamoDB | Caches X user profiles (TTL-based expiry, 7 days) |
| `messages_out` topic | SNS | Delivers Amazon Connect streaming events to the Outbound Handler |
| `x-dm-credentials` | Secrets Manager | Stores X API OAuth 1.0a credentials (Consumer Key, Consumer Secret, Access Token, Access Token Secret) |
| `/x/dm/config` | SSM Parameter Store | Holds Connect instance ID, contact flow ID, and X account ID |
| `/x/dm/webhook/url` | SSM Parameter Store | Stores the deployed API Gateway callback URL |

## Cost Estimation

Example scenario: 1,000 conversations per month, averaging 10 messages each (5 inbound + 5 outbound), totaling 10,000 messages.

| Component | Estimated Monthly Cost | Notes |
|---|---|---|
| Infrastructure (API GW, Lambda, DynamoDB, SNS, Secrets Manager) | ~$0.71 | Negligible at this scale |
| Amazon Connect Chat (Inbound) | $20.00 | 5,000 msgs × $0.004/msg |
| Amazon Connect Chat (Outbound) | $20.00 | 5,000 msgs × $0.004/msg |
| **Total** | **~$40.71** | |

The infrastructure cost is minimal — Amazon Connect Chat messaging is the primary cost driver at $0.004 per message in each direction. See [Amazon Connect pricing](https://aws.amazon.com/connect/pricing/) for current rates.

To reduce Connect Chat costs on high-volume conversations, consider adding a [message buffering layer](https://github.com/aws-samples/sample-whatsapp-end-user-messaging-connect-chat/tree/main/whatsapp-eum-connect-chat) to aggregate rapid consecutive messages.

## Deployment Prerequisites

Before getting started you'll need:

### X Developer Account and API Credentials

You need an X Developer Account with at least the Pay-Per-Use tier. The main steps are:

1. Go to the [X Developer Portal](https://developer.x.com/) and sign up or log in
2. Create a new Project and App (or use an existing one)
3. Select the **Pay-Per-Use** tier (required for Account Activity API access and DM read/write)
4. Enable **Read and Write** permissions and **Direct Messages** access
5. Generate all four OAuth 1.0a credentials: Consumer Key, Consumer Secret, Access Token, and Access Token Secret

See the [X Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/x_setup.md) for detailed step-by-step instructions.

⚠️ Important: The free tier does not include webhook-based DM delivery. You need the Pay-Per-Use tier.

### An Amazon Connect Instance

You need an Amazon Connect instance. If you don't have one yet, you can [follow this guide](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-instances.html) to create one.

You'll need the **INSTANCE_ID** of your instance. You can find it in the Amazon Connect console or in the instance ARN:

`arn:aws:connect:<region>:<account_id>:instance/INSTANCE_ID`

### A Chat Flow to Handle Messages

Create or have ready the contact flow that defines the user experience. [Follow this guide](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html) to create an Inbound Contact Flow. The simplest one will work.

Remember to publish the flow.

![Simple Flow](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/flow_simple.png)

Take note of the **INSTANCE_ID** and **CONTACT_FLOW_ID** from the Details tab. The values are in the flow ARN:

`arn:aws:connect:<region>:<account_id>:instance/INSTANCE_ID/contact-flow/CONTACT_FLOW_ID`

(see the [Amazon Connect Prerequisites](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_connect.md) for more details)


## Deploying with AWS CDK

⚠️ Deploy in the same region where your Amazon Connect instance is configured.

### 1. Clone the repository and navigate to the project

```bash
git clone https://github.com/aws-samples/sample-amazon-connect-social-integration.git
cd sample-amazon-connect-social-integration/x-dm-connect-chat
```

### 2. Deploy with CDK

Follow the instructions in the [CDK Deployment Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_cdk_deploy.md) for environment setup and deployment commands.

## Post-deployment Configuration

### Step 1: Update the X API Credentials in Secrets Manager

The stack creates a Secrets Manager secret named [`x-dm-credentials`](https://console.aws.amazon.com/secretsmanager/secret?name=x-dm-credentials) with placeholder values. Update it with your actual X API credentials as a JSON object:

```json
{
  "consumer_key": "YOUR_CONSUMER_KEY",
  "consumer_secret": "YOUR_CONSUMER_SECRET",
  "access_token": "YOUR_ACCESS_TOKEN",
  "access_token_secret": "YOUR_ACCESS_TOKEN_SECRET"
}
```

### Step 2: Update the SSM Configuration Parameter

After deployment, go to [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) and update the SSM parameter `/x/dm/config` with your Amazon Connect and X details:

| Parameter | Description |
|---|---|
| `instance_id` | Your Amazon Connect Instance ID |
| `contact_flow_id` | The ID of the Inbound Contact Flow for chat |
| `x_account_id` | Your X account's numeric user ID (the business account that will receive DMs) |

To find your `x_account_id`:

```bash
curl -X GET "https://api.x.com/2/users/by/username/YOUR_X_HANDLE" \
  -H "Authorization: Bearer YOUR_BEARER_TOKEN"
```

Or use a third-party lookup tool — search for "X/Twitter user ID lookup" to find your numeric ID from your @handle.

### Step 3: Register the Webhook with X Account Activity API

1. Find your deployed webhook URL in the [SSM parameter](https://console.aws.amazon.com/systems-manager/parameters) `/x/dm/webhook/url`
2. Register the webhook URL with the X Account Activity API v2:

```bash
curl -X POST "https://api.x.com/1.1/account_activity/all/YOUR_ENV_NAME/webhooks.json?url=YOUR_WEBHOOK_URL" \
  -H "Authorization: OAuth ..."
```

3. X will immediately send a CRC challenge (GET request) to your webhook URL. The Inbound Handler will respond with the HMAC-SHA256 hash automatically
4. Subscribe your app user to the webhook:

```bash
curl -X POST "https://api.x.com/1.1/account_activity/all/YOUR_ENV_NAME/subscriptions.json" \
  -H "Authorization: OAuth ..."
```

> **Tip:** You can use [Tweepy](https://docs.tweepy.org/) or [Postman](https://www.postman.com/) to simplify OAuth 1.0a signed requests for webhook registration.

## Testing

Go to your Amazon Connect instance and [open the Contact Control Panel (CCP)](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

<div align="center">
<video src="https://github.com/user-attachments/assets/3fe667d9-1887-4acb-8ccf-3596d5c562a4" width="540" controls></video>
</div>

Try these scenarios:

- Send a DM to your business X account from another X account — it should appear as a new chat contact in the CCP
- Reply from the CCP — the response should arrive in the customer's X DMs
- Send an image from X — it should appear as an image attachment in the agent's chat
- From the agent side, send an image — it should appear in the customer's X DMs
- Try sending a document from the agent side — it should arrive as a link in the customer's DMs

## Important Considerations around X

### Encrypted DMs

X supports end-to-end encrypted (E2EE) Direct Messages. However, **encrypted DMs are not accessible via the X API**. This integration only processes standard (non-encrypted) DMs. If a conversation is encrypted, the webhook will not receive those message events.

### Pay-Per-Use Tier

- The **Pay-Per-Use** tier is required for Account Activity API access. The free tier does not include webhook-based DM delivery.
- Review [X API pricing](https://developer.x.com/en/products/twitter-api) for current tier details and costs.

### CRC Re-validation

- X periodically re-sends CRC challenges to verify your webhook is still valid. The Inbound Handler handles this automatically, but ensure the Secrets Manager credentials remain valid and the Lambda function stays deployed.

### OAuth 1.0a Credentials

- All four credentials (Consumer Key, Consumer Secret, Access Token, Access Token Secret) must remain valid. If you regenerate any credential in the X Developer Portal, update the Secrets Manager secret immediately.
- The Access Token and Access Token Secret are tied to the specific X user account that owns the app. Ensure this is the business account that should receive and send DMs.

### Rate Limits

- The X API enforces rate limits on DM endpoints. The Account Activity API has its own limits on webhook registrations and CRC validations.
- Monitor your usage in the [X Developer Portal](https://developer.x.com/) dashboard.

## Next Steps

This solution handles the core X DM-to-Connect messaging flow. Some ideas to extend it:

- Use Amazon Bedrock to analyze inbound images and provide agents with context before they respond
- Use [Amazon Connect AI Agents](https://docs.aws.amazon.com/connect/latest/adminguide/agentic-self-service.html) for agentic self-service, letting customers resolve common issues without waiting for a human agent
- Combine with the [Instagram DM integration](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/instagram-dm-connect-chat) and [Facebook Messenger integration](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/facebook-messenger-connect-chat) to handle all social channels from a single Amazon Connect instance

### Leverage Amazon Connect Customer Profiles

This solution already fetches X profile data (name, username, profile image) and passes it as contact attributes. You can take this further by integrating with [Amazon Connect Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles.html) to give agents a unified view of the customer across channels. Then in your Contact Flow, use the [Customer Profiles block](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles-block.html) to retrieve the profile and display it in the agent workspace. The agent sees the customer's name, X handle, and any previous interaction history — all before they even type a reply.

## Resources

- [Project Repository](https://github.com/aws-samples/sample-amazon-connect-social-integration)
- [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [X API Documentation](https://developer.x.com/en/docs)
- [X Account Activity API](https://developer.x.com/en/docs/twitter-api/enterprise/account-activity-api/overview)
- [Tweepy Documentation](https://docs.tweepy.org/)
- [X Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/x_setup.md)
