# Facebook Messenger & Amazon Connect Chat

<table>
<tr>
<td width="50%">

_Learn how to bridge Facebook Messenger and Amazon Connect Chat for seamless customer service. This step-by-step guide covers the full architecture using AWS CDK, AWS Lambda, Amazon API Gateway, Amazon DynamoDB, and Amazon Connect. From receiving customer messages to routing them to agents, forwarding agent replies back to Messenger, and handling attachments in both directions — all with automatic session management, echo prevention, and user profile caching via the Graph API._

</td>
<td width="50%">

![Demo](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/facebook-messenger-connect-chat/demo_messenger_connect_chat.gif)

</td>
</tr>
</table>


Facebook Messenger has over a billion active users. Many of them are already messaging your Facebook Page with questions about products, order status, or support requests. If your agents have to juggle between the Meta Business Suite and their contact center, context gets lost and response times suffer.

In this blog, you'll learn how to connect Facebook Messenger directly to Amazon Connect Chat, so your agents handle Messenger conversations from the same workspace they use for every other channel. Messages flow in both directions — including images, documents, and files — with automatic session management and user profile enrichment.

Check out the code at [Github](https://github.com/aws-samples/sample-amazon-connect-social-integration)


## What you'll build

A bidirectional messaging bridge between Facebook Messenger and Amazon Connect that:

1. Receives incoming Messenger messages via Meta webhooks and routes them to Amazon Connect Chat
2. Forwards agent replies from Amazon Connect back to Messenger through the Send API
3. Manages chat sessions automatically — creating new ones, reusing active ones, and cleaning up expired ones
4. Fetches and caches Messenger user profiles (first name, last name, profile picture) via the Graph API
5. Handles attachments in both directions — images and files from customers, and images and files from agents
6. Prevents echo loops by filtering out messages sent by your own Page

The end result: agents see Messenger conversations as regular chat contacts in their Amazon Connect workspace, with the customer's real name displayed.

## Architecture

![Architecture Diagram](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/facebook-messenger-connect-chat/facebook-messengar-chat.svg)

Here's how it flows:

1. A customer sends a message on Facebook Messenger. Meta delivers the webhook event to an API Gateway endpoint
2. The Inbound Handler Lambda validates the webhook, parses the message, and looks up or creates an Amazon Connect Chat session
3. The customer's Messenger profile is fetched via the Graph API and cached in DynamoDB
4. Text messages and attachments are forwarded into the Connect Chat session via the Participant API
5. When an agent replies, Amazon Connect publishes the event to an SNS topic via contact streaming
6. The Outbound Handler Lambda picks up the SNS event, looks up the customer's Page-Scoped ID (PSID), and sends the reply back through the Messenger Send API

## Inbound: Messenger → Amazon Connect

When a customer sends a message to your Facebook Page, the inbound path handles everything from webhook validation to message delivery.

### 1. Webhook Validation and Message Parsing

Meta sends webhook events to your API Gateway `/messages` endpoint. The Lambda handles GET requests for webhook verification — Meta sends `hub.mode`, `hub.verify_token`, and `hub.challenge` parameters that must be validated and echoed back.

For POST requests, the `MessengerService` class parses the webhook payload. Messenger webhooks arrive with `object: "page"` and contain entries with messaging data:

```python
class MessengerMessage:
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

The service filters out messages sent by your own Page ID to prevent echo loops — when your Page sends a reply, Meta also delivers it as a webhook event, and without this filter you'd get an infinite cycle.

### 2. User Profile Retrieval and Caching

Before routing the message to Connect, the handler fetches the sender's Messenger profile using the Graph API. Unlike Instagram (which returns a single `name` field), Messenger provides `first_name` and `last_name` separately:

```python
def get_user_profile(self, psid, fields=None):
    # Check in-memory cache first
    if psid in self.user_profiles:
        return self.user_profiles[psid]

    # Check DynamoDB users table
    if USERS_TABLE_NAME:
        users_table = TableService(table_name=USERS_TABLE_NAME)
        db_profile = users_table.get_item({"id": psid})
        if db_profile:
            return db_profile

    # Fetch from Graph API
    if fields is None:
        fields = ['first_name', 'last_name', 'profile_pic']
    
    params = {'fields': ','.join(fields), 'access_token': self.access_token}
    url = f"https://graph.facebook.com/v24.0/{psid}?{urlencode(params)}"
    # ... fetch and cache in DynamoDB with 7-day TTL
```

The display name is built by concatenating `first_name` and `last_name`, and this is what the agent sees in the Connect Chat widget.

### 3. Session Management

The handler checks DynamoDB for an existing chat session using the sender's PSID (Page-Scoped ID):

- If a session exists, it sends the message using the stored `connectionToken`. If the token is expired (AccessDeniedException), it automatically creates a new session and cleans up the old record.
- If no session exists, it calls `StartChatContact` to create a new Amazon Connect Chat, starts contact streaming to the SNS topic, creates a participant connection, and stores everything in DynamoDB.

The contact attributes include the channel name ("Messenger"), the customer ID (PSID), and the customer's display name — making it easy to identify the source channel in Contact Flows and agent routing.

```python
attributes = {
    "Channel": "Messenger",
    "customerId": userId,
    "customerName": userName,
}

start_chat_response = self.connect.start_chat_contact(
    InstanceId=self.instance_id,
    ContactFlowId=self.contact_flow_id,
    Attributes=attributes,
    ParticipantDetails={"DisplayName": userName},
    InitialMessage={"ContentType": "text/plain", "Content": message},
    ChatDurationInMinutes=self.chat_duration_minutes,
)
```

### 4. Attachment Handling (Inbound)

When a customer sends an image, video, audio, or file on Messenger, the attachment data includes a `type` and a `payload.url` pointing to Meta's CDN. The handler downloads the file content and uploads it to the Connect Chat session:

```python
def attachment_message_handler(message, connect_chat_service, table_service, user_name, sender_profile):
    # Ensure a chat session exists (create one if needed)
    # ...
    
    for attachment in message.attachments:
        att_url = attachment.get('payload', {}).get('url')
        
        # Download from Messenger CDN
        file_bytes, content_type = download_attachment(att_url)
        
        # Upload to Connect Chat via Participant API
        attachment_id, error = connect_chat_service.attach_file(
            fileContents=file_bytes,
            fileName=get_attachment_filename(attachment),
            fileType=content_type,
            ConnectionToken=connection_token
        )
```

The upload uses the same three-step Participant API flow: `start_attachment_upload` → PUT to pre-signed URL → `complete_attachment_upload`. If anything fails, the handler falls back to sending the CDN URL as a text message.

## Outbound: Amazon Connect → Messenger

When an agent replies from the Amazon Connect workspace, the outbound path delivers the message back to Messenger.

### 1. Streaming Events via SNS

Amazon Connect publishes chat streaming events to an SNS topic. The Outbound Handler Lambda subscribes to this topic and processes three event types:

- `MESSAGE` — text messages from the agent
- `ATTACHMENT` — file attachments sent by the agent
- `EVENT` — participant join/leave and chat ended events

Messages from the `CUSTOMER` role are skipped to avoid processing the customer's own messages again.

### 2. Sending Text Messages

For text messages with `CUSTOMER` or `ALL` visibility, the handler looks up the customer's PSID from DynamoDB and sends the reply via the Messenger Send API:

```python
def send_messenger_text(access_token, text_message, recipient_id):
    url = f"https://graph.facebook.com/v24.0/me/messages"
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message},
    }
    
    url_with_token = f"{url}?access_token={quote(access_token)}"
    # POST to Messenger Send API
```

### 3. Sending Attachments

When an agent sends a file from the Connect Chat widget, the handler retrieves a signed URL for the attachment and forwards it to Messenger as a media message. The MIME type determines the Messenger attachment type:

| MIME prefix | Messenger type |
|---|---|
| `image/*` | `image` |
| `video/*` | `video` |
| `audio/*` | `audio` |
| everything else | `file` |

```python
def send_messenger_attachment(access_token, attachment_url, mime_type, recipient_id):
    attachment_type = get_attachment_type(mime_type)  # image, video, audio, or file
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": attachment_type,
                "payload": {"url": attachment_url, "is_reusable": True}
            }
        },
    }
    # POST to Messenger Send API
```

The `is_reusable: True` flag tells Meta to cache the attachment, which can speed up delivery if the same file is sent to multiple recipients.

### 4. Session Cleanup

When a participant leaves or the chat ends, the handler deletes the connection record from DynamoDB so the next inbound message starts a fresh session.

## Message Types Supported

| Direction | Text | Images | Videos | Audio | Files |
|---|---|---|---|---|---|
| Inbound (customer → agent) | ✅ | ✅ | — | — | ✅ |
| Outbound (agent → customer) | ✅ | ✅ | — | — | ✅ |


## What Gets Deployed

| Resource | Service | Purpose |
|---|---|---|
| `/messages` endpoint (GET & POST) | API Gateway | Receives Meta webhook verification and inbound messages |
| Inbound Handler | Lambda | Processes Messenger messages and routes them to Amazon Connect Chat |
| Outbound Handler | Lambda | Sends agent replies back to Messenger via the Send API |
| Active Connections table | DynamoDB | Tracks open chat sessions (`contactId` PK, `userId` GSI) |
| Messenger Users table | DynamoDB | Caches Messenger user profiles (TTL-based expiry) |
| `messages_out` topic | SNS | Delivers Amazon Connect streaming events to the Outbound Handler |
| `messenger-page-token` | Secrets Manager | Stores the Facebook Page Access Token |
| `/meta/messenger/config` | SSM Parameter Store | Holds Connect instance ID, contact flow ID, verification token, and Page ID |
| `/meta/messenger/webhook/url` | SSM Parameter Store | Stores the deployed API Gateway callback URL |

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

### Facebook Page and Meta App

You need a Facebook Page and a Meta App configured with the Messenger Platform. The main steps are:

1. Have or create a Meta Business Account
2. Create a Meta App and add the Messenger product
3. Connect your Facebook Page and generate a Page Access Token
4. Generate a non-expiring Page Access Token (short-lived tokens expire in ~1-2 hours)

See the [Facebook Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md) for detailed step-by-step instructions, including the token exchange flow to get a non-expiring token.

⚠️ Important: In development mode, your app can only receive messages from Facebook accounts with a role on the Meta App (Admin, Developer, Tester). For production use, you need App Review with Advanced Access for `pages_messaging`.

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
cd sample-amazon-connect-social-integration/facebook-messenger-connect-chat
```

### 2. Deploy with CDK

Follow the instructions in the [CDK Deployment Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_cdk_deploy.md) for environment setup and deployment commands.

## Post-deployment Configuration

### Step 1: Update the Page Access Token in Secrets Manager

The stack creates a Secrets Manager secret named [`messenger-page-token`](https://console.aws.amazon.com/secretsmanager/secret?name=messenger-page-token) with a placeholder value. Update it with your actual non-expiring Page Access Token.

See [Facebook Setup Guide — Step 5](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md#step-5-generate-a-long-lived-page-access-token) for how to generate a non-expiring token.

### Step 2: Update the SSM Configuration Parameter

After deployment, go to [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) and update the SSM parameter `/meta/messenger/config` with your Amazon Connect and Facebook details:


| Parameter | Description |
|---|---|
| `instance_id` | Your Amazon Connect Instance ID |
| `contact_flow_id` | The ID of the Inbound Contact Flow for chat |
| `MESSENGER_VERIFICATION_TOKEN` | A secret string you choose — must match what you enter in the Meta webhook config |

### Step 3: Configure the Webhook in Meta App Dashboard

1. Go to your Meta App Dashboard → Messenger → Settings → Webhooks
2. Set the **Callback URL** to the API Gateway URL. You can find it in the SSM parameter `/meta/messenger/webhook/url` in [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters)
3. Set the **Verify Token** to the same value you used for `MESSENGER_VERIFICATION_TOKEN` above
4. Subscribe to the `messages` webhook field (at minimum)
5. Subscribe your Page to the app so it receives webhook events

For full details, see [Facebook Setup Guide — Step 4](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md#step-4-configure-webhooks).

## Testing

Go to your Amazon Connect instance and [open the Contact Control Panel (CCP)](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

<div align="center">
<video src="https://github.com/user-attachments/assets/27ff5980-91cc-4db6-8c4b-88e82cd0def0" width="540" controls></video>
</div>

Try these scenarios:

- Send a message to your Facebook Page from another Facebook account — it should appear as a new chat contact in the CCP
- Reply from the CCP — the response should arrive in the customer's Messenger chat
- Send an image from Messenger — it should appear as an image attachment in the agent's chat
- Send a file (PDF, document) from Messenger — it should appear as a file attachment
- From the agent side, send an image or document — it should appear in the customer's Messenger chat

## Important Considerations around Facebook Messenger

### 24-Hour Messaging Window

Facebook Messenger has a **24-hour standard messaging window**:
- After a user sends a message, your Page has 24 hours to respond
- Outside this window, you can only send messages using [Message Tags](https://developers.facebook.com/docs/messenger-platform/send-messages/message-tags) (limited use cases)
- Each new user message reopens the 24-hour window

### Rate Limits

- Messenger Platform has rate limits based on your app's usage tier
- Monitor API response headers for rate limit information
- Implement exponential backoff for retries

### App Review

- In **development mode**, your app can only receive messages from accounts with a role on the app (Admin, Developer, Tester)
- For production use with real customers, you need to submit for [App Review](https://developers.facebook.com/docs/app-review) and request **Advanced Access** for `pages_messaging`

### Page Access Token Security

- The Page Access Token grants full messaging access to your Page — treat it like a password
- Store it in AWS Secrets Manager (as this solution does), never in code or environment variables
- Use the non-expiring token flow described in the [Facebook Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md) to avoid token rotation issues

## Next Steps

This solution handles the core Messenger-to-Connect messaging flow. Some ideas to extend it:

- 
- Use Amazon Bedrock to analyze inbound images and provide agents with context
- Combine with the [Instagram DM integration](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/instagram-dm-connect-chat) to handle both Meta channels from a single Amazon Connect instance

### Leverage Amazon Connect Customer Profiles

This solution already fetches Messenger profile data (first name, last name, profile picture) and passes it as contact attributes. You can take this further by integrating with [Amazon Connect Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles.html) to give agents a unified view of the customer across channels. Then in your Contact Flow, use the [Customer Profiles block](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles-block.html) to retrieve the profile and display it in the agent workspace. The agent sees the customer's name, previous interaction history, and data from other channels — all before they even type a reply.

## Resources

- [Project Repository](https://github.com/aws-samples/sample-amazon-connect-social-integration)
- [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Facebook Setup Guide](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md)
