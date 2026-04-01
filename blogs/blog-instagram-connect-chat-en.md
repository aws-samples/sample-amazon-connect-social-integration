# Instagram DMs to Amazon Connect Chat — Bidirectional Messaging Integration

| | |
|---|---|
| _Learn how to bridge Instagram Direct Messages and Amazon Connect Chat for seamless customer service. This step-by-step guide covers the full architecture using AWS CDK, AWS Lambda, Amazon API Gateway, Amazon DynamoDB, and Amazon Connect. From receiving customer DMs to routing them to agents, forwarding agent replies back to Instagram, and handling attachments in both directions — all with automatic session management and user profile caching._ | ![Demo](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/instagram-dm-connect-chat/demo_instagram_connect_chat.gif) |


Your customers are already on Instagram. They browse your products, check your stories, and when they have a question — they send a DM. If your support team has to switch between Instagram and their contact center tool, you're losing time and context.

In this blog, you'll learn how to connect Instagram Direct Messages directly to Amazon Connect Chat, so your agents can handle Instagram conversations from the same workspace they use for every other channel. No app switching, no copy-pasting, no lost messages.

Check out the code at [Github](https://github.com/aws-samples/sample-amazon-connect-social-integration)


## What you'll build

A bidirectional messaging bridge between Instagram DMs and Amazon Connect that:

1. Receives incoming Instagram DMs via Meta webhooks and routes them to Amazon Connect Chat
2. Forwards agent replies from Amazon Connect back to Instagram through the Graph API
3. Manages chat sessions automatically — creating new ones, reusing active ones, and cleaning up expired ones
4. Caches Instagram user profiles (name, username, profile picture, follower count) in DynamoDB to reduce API calls
5. Handles attachments in both directions — images from customers, and images and documents from agents

The end result: agents see Instagram conversations as regular chat contacts in their Amazon Connect workspace, complete with the customer's Instagram name and profile information.

## Architecture

![Architecture Diagram](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/instagram-dm-connect-chat/instagram-connect-chat.svg)

Here's how it flows:

1. A customer sends a DM on Instagram. Meta delivers the webhook event to an API Gateway endpoint
2. The Inbound Handler Lambda validates the webhook, parses the message, and looks up or creates an Amazon Connect Chat session
3. The customer's Instagram profile is fetched via the Graph API and cached in DynamoDB
4. Text messages and attachments are forwarded into the Connect Chat session via the Participant API
5. When an agent replies, Amazon Connect publishes the event to an SNS topic via contact streaming
6. The Outbound Handler Lambda picks up the SNS event, looks up the customer's Instagram ID, and sends the reply back through the Instagram Graph API

## Inbound: Instagram → Amazon Connect

When a customer sends a DM to your Instagram Business account, the inbound path handles everything from webhook validation to message delivery.

### 1. Webhook Validation and Message Parsing

Meta sends webhook events to your API Gateway `/messages` endpoint. The Lambda first handles GET requests for webhook verification — Meta sends a challenge token that must be echoed back with the correct verification token.

For POST requests (actual messages), the `InstagramService` class parses the webhook payload. Instagram webhooks arrive with `object: "instagram"` and contain entries with messaging data:

```python
class InstagramMessage:
    def __init__(self, messaging_data):
        self.sender_id = messaging_data.get('sender', {}).get('id')
        self.recipient_id = messaging_data.get('recipient', {}).get('id')
        self.timestamp = messaging_data.get('timestamp')
        
        message_data = messaging_data.get('message', {})
        self.message_id = message_data.get('mid')
        self.text = message_data.get('text')
        self.attachments = message_data.get('attachments', [])
        
        if self.text:
            self.message_type = 'text'
        elif len(self.attachments):
            self.message_type = 'attachment'
        else:
            self.message_type = 'unknown'
```

The service also filters out echo messages — messages sent by your own Instagram account — to prevent infinite loops.

### 2. User Profile Retrieval and Caching

Before routing the message to Connect, the handler fetches the sender's Instagram profile using the Graph API. This provides the agent with context about who they're talking to:

```python
def get_user_profile(self, instagram_scoped_id, fields=None):
    # Check in-memory cache first
    if instagram_scoped_id in self.user_profiles:
        return self.user_profiles[instagram_scoped_id]

    # Check DynamoDB users table
    if USERS_TABLE_NAME:
        users_table = TableService(table_name=USERS_TABLE_NAME)
        db_profile = users_table.get_item({"id": instagram_scoped_id})
        if db_profile:
            return db_profile

    # Fetch from Graph API as last resort
    params = {'fields': ','.join(fields), 'access_token': self.access_token}
    url = f"https://graph.instagram.com/v24.0/{instagram_scoped_id}?{urlencode(params)}"
    # ... fetch and cache
```

The profile includes fields like `name`, `username`, `profile_pic`, `follower_count`, `is_user_follow_business`, and `is_verified_user`. Profiles are cached in a DynamoDB table with a 7-day TTL, so repeat conversations skip the API call entirely.

### 3. Session Management

The handler checks DynamoDB for an existing chat session using the sender's Instagram-scoped ID:

- If a session exists, it sends the message using the stored `connectionToken`. If the token is expired (AccessDeniedException), it automatically creates a new session.
- If no session exists, it calls `StartChatContact` to create a new Amazon Connect Chat, starts contact streaming to the SNS topic, creates a participant connection, and stores everything in DynamoDB.


### 4. Attachment Handling (Inbound)

When a customer sends an image, the handler downloads it from Instagram's CDN and uploads it to the Connect Chat session using the Participant API's three-step attachment flow:

1. `start_attachment_upload` — creates an upload slot with a pre-signed URL
2. `PUT` to the pre-signed URL — uploads the binary content
3. `complete_attachment_upload` — finalizes the upload

If the download or upload fails, the handler falls back to sending the attachment URL as a text message so the agent still has access to the content.

## Outbound: Amazon Connect → Instagram

When an agent replies from the Amazon Connect workspace, the outbound path delivers the message back to Instagram.

### 1. Streaming Events via SNS

Amazon Connect publishes chat streaming events to an SNS topic. The Outbound Handler Lambda subscribes to this topic and processes three event types:

- `MESSAGE` — text messages from the agent
- `ATTACHMENT` — file attachments sent by the agent
- `EVENT` — participant join/leave and chat ended events

Messages from the `CUSTOMER` role are skipped to avoid echo loops.

### 2. Sending Text Messages

For text messages with `CUSTOMER` or `ALL` visibility, the handler looks up the customer's Instagram-scoped ID and the Instagram Business Account ID from DynamoDB, then sends the reply via the Graph API:

```python
def send_instagram_text(access_token, text_message, recipient_id, instagram_account_id):
    url = f"https://graph.instagram.com/v24.0/{instagram_account_id}/messages"
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message},
        "access_token": access_token,
    }
    # POST to Instagram Graph API
```

### 3. Sending Attachments

When an agent sends a file from the Connect Chat widget, the handler retrieves a signed URL for the attachment and forwards it to Instagram as a media message. The MIME type determines the Instagram message type:

| MIME prefix | Instagram type |
|---|---|
| `image/*` | `image` |
| `video/*` | `video` |
| `audio/*` | `audio` |
| everything else | `file` |

### 4. Session Cleanup

When a participant leaves or the chat ends, the handler deletes the connection record from DynamoDB so the next inbound message starts a fresh session.

## Message Types Supported

| Direction | Text | Images | Documents |
|---|---|---|---|
| Inbound (customer → agent) | ✅ | ✅ | — |
| Outbound (agent → customer) | ✅ | ✅ | ✅ |

Sending documents from the Instagram user app is not currently possible (instagram app limitations), but customers can receive documents sent by agents from Amazon Connect.

## What Gets Deployed

| Resource | Service | Purpose |
|---|---|---|
| `/messages` endpoint (GET & POST) | API Gateway | Receives Meta webhook verification and inbound messages |
| Inbound Handler | Lambda | Processes Instagram messages and routes them to Amazon Connect Chat |
| Outbound Handler | Lambda | Sends agent replies back to Instagram via the Graph API |
| Active Connections table | DynamoDB | Tracks open chat sessions (`contactId` PK, `userId` GSI) |
| Instagram Users table | DynamoDB | Caches Instagram user profiles (TTL-based expiry) |
| `messages_out` topic | SNS | Delivers Amazon Connect streaming events to the Outbound Handler |
| `instagram-token` | Secrets Manager | Stores the Instagram User Access Token |
| `/meta/instagram/config` | SSM Parameter Store | Holds Connect instance ID, contact flow ID, verification token, and Instagram account ID |
| `/meta/instagram/webhook/url` | SSM Parameter Store | Stores the deployed API Gateway callback URL |


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

### Instagram Business Account and Meta App

You need an Instagram Business or Creator account connected to a Meta App with the Instagram API configured. The main steps are:

1. Have or create a Meta Business Account
2. Create a Meta App and add the Instagram product
3. Configure Instagram Login and generate an Instagram User Access Token
4. Make sure your Instagram account is a Business or Creator account (personal accounts don't support the Messaging API)

See the [Instagram Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md) for detailed step-by-step instructions.

⚠️ Important: In development mode, your app can only receive messages from Instagram accounts with a role on the Meta App.

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
cd sample-amazon-connect-social-integration/instagram-dm-connect-chat
```

### 2. Deploy with CDK

Follow the instructions in the [CDK Deployment Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_cdk_deploy.md) for environment setup and deployment commands.

## Post-deployment Configuration

### Step 1: Update the Instagram Access Token in Secrets Manager

The stack creates a Secrets Manager secret named [`instagram-token`](https://console.aws.amazon.com/secretsmanager/secret?name=instagram-token) with a placeholder value. Update it with your actual Instagram User Access Token.

See the [Instagram Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md) for how to generate this token.

### Step 2: Update the SSM Configuration Parameter

After deployment,  go to [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) and update the SSM parameter  `/meta/instagram/config` with your Amazon Connect and Instagram details:


| Parameter | Description |
|---|---|
| `instance_id` | Your Amazon Connect Instance ID |
| `contact_flow_id` | The ID of the Inbound Contact Flow for chat |
| `INSTAGRAM_VERIFICATION_TOKEN` | A secret string you choose — must match what you enter in the Meta webhook config |
| `instagram_account_id` | Your Instagram Business Account ID (see note below) |

To find your `instagram_account_id`:


- In your Meta App Dashboard → Instagram → API Setup with Instagram Login → expand "1. Generate access tokens" → the ID is underneath the linked Instagram account
- Or call the Graph API:

```bash
curl -X GET "https://graph.instagram.com/me?fields=id,username,account_type,user_id&access_token=YOUR_IG_ACCESS_TOKEN"
```

The `user_id` field in the response is your `instagram_account_id`.


### Step 3: Configure the Webhook in Meta App Dashboard

1. Go to your Meta App Dashboard → Instagram → API Setup with Instagram Login → Webhooks
2. Set the **Callback URL** to the API Gateway URL. You can find it in the SSM parameter `/meta/instagram/webhook/url`
3. Set the **Verify Token** to the same value you used for `INSTAGRAM_VERIFICATION_TOKEN` above
4. Subscribe to the `messages` webhook field

For full details, see the [Instagram Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md).

## Testing

Go to your Amazon Connect instance and [open the Contact Control Panel (CCP)](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

<div align="center">
<video src="https://github.com/user-attachments/assets/5f6d988b-5340-4b32-ac1b-ec85114adb2b" width="540" controls></video>
</div>

Try these scenarios:

- Send a DM to your Instagram Business account from another Instagram account — it should appear as a new chat contact in the CCP
- Reply from the CCP — the response should arrive in the customer's Instagram DMs
- Send an image from Instagram — it should appear as an image attachment in the agent's chat
- From the agent side, send an image or document — it should appear in the customer's Instagram DMs


## Important Considerations around Instagram

### 24-Hour Messaging Window

Instagram has a **24-hour standard messaging window**:
- After a user sends a message, your account has 24 hours to respond
- Outside this window, messaging is restricted
- Each new user message reopens the 24-hour window

### Human Agent Messaging Window

Instagram provides a **7-day human agent messaging window** for conversations that are escalated to a human agent. This extended window allows agents more time to resolve complex issues.

### App Review

- In **development mode**, your app can only receive messages from Instagram accounts with a role on the Meta App (Admin, Developer, Tester)
- For production use with real customers, you need to submit for [App Review](https://developers.facebook.com/docs/app-review) and request the required permissions

### Rate Limits

- The Instagram Messaging API has rate limits based on your app's usage tier
- Monitor API response headers for rate limit information

## Next Steps

This solution handles the core Instagram-to-Connect messaging flow. Some ideas to extend it:

- Add support for Instagram Stories mentions and replies
- Use Amazon Bedrock to analyze inbound images and provide agents with context before they respond
- Combine with the [Facebook Messenger integration](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/facebook-messenger-connect-chat) to handle both Meta channels from a single Amazon Connect instance

## Resources

- [Project Repository](https://github.com/aws-samples/sample-amazon-connect-social-integration)
- [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Instagram Messaging API — Overview](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api)
- [Instagram Graph API — User Profile](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/api-reference)
- [Meta Webhooks — Getting Started](https://developers.facebook.com/docs/graph-api/webhooks/getting-started)
- [Instagram Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md)
