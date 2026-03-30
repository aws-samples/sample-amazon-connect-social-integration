# Facebook Messenger – Amazon Connect Chat

Bidirectional messaging between Facebook Messenger and Amazon Connect Chat. Handles inbound customer messages and outbound agent responses with session management and attachment support.

![Architecture Diagram](<!-- TODO: add architecture diagram -->)

## How It Works

The solution bridges Facebook Messenger and Amazon Connect Chat through two event-driven paths connected by a shared DynamoDB connections table and an SNS topic.

### Inbound: Messenger → Amazon Connect

When a customer sends a message on Facebook Messenger:

1. **Meta Webhooks** sends the event to API Gateway (`/messages` endpoint).
2. The **Inbound Handler** Lambda validates the webhook and parses the message using the Messenger Platform API.
3. It checks the connections table for an existing chat session:
   - **Existing session** — sends the message to Amazon Connect using the stored `connectionToken`. If the token is expired, it creates a new chat session automatically.
   - **No session** — calls `StartChatContact` to create a new chat, starts contact streaming to the SNS topic, creates a participant connection, and stores the session in DynamoDB.
4. The sender's Messenger profile is retrieved via the Graph API — including `first_name`, `last_name`, and `profile_pic`. The code stores these profiles in a user database (a DynamoDB Messenger Users table) and checks it before calling the Graph API; only re-fetching when the cached profile is stale or missing, reducing API calls and latency on repeat conversations.
5. **Attachments** (images, videos, audio) are downloaded from Messenger's CDN and uploaded to the Connect chat via the Participant API.

### Outbound: Amazon Connect → Messenger

When an agent (human or AI) replies in Amazon Connect:

1. **Contact streaming** publishes the outbound message to the SNS topic (`messages_out`).
2. The **Outbound Handler** Lambda receives the SNS record.
3. It looks up the customer's Page-Scoped ID (PSID) from the connections table using the `contactId`.
4. It sends the reply back to Messenger through the Send API (`/me/messages`).
5. **Attachments** from the agent are fetched via a signed URL and forwarded as Messenger media messages (image, video, audio, or file).
6. On chat disconnect events, the connection record is deleted from DynamoDB.

### Session Management

A DynamoDB table (`active_connections`) tracks every open conversation:

| Field | Purpose |
|---|---|
| `contactId` (PK) | Amazon Connect contact identifier |
| `userId` (GSI) | Page-Scoped ID (PSID), used for lookups on inbound messages |
| `connectionToken` | Participant connection token for sending messages and attachments |
| `participantToken` | Token used to create the participant connection |
| `pageId` | Facebook Page ID used for outbound replies |
| `userName` | Customer display name from Messenger profile |
| `senderProfile` | Sender's Messenger public profile |

When a chat session expires or the participant leaves, the connection is cleaned up so the next inbound message starts a fresh session.

### Message Types Supported

| Direction | Text | Images | Videos | Audio | Files |
|---|---|---|---|---|---|
| Inbound (customer → agent) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Outbound (agent → customer) | ✅ | ✅ | ✅ | ✅ | ✅ |

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

## Deployment

### Prerequisites

These are **not** created by this stack — you need them before deploying:

1. **Facebook Page Access Token** — from a Facebook Page configured with the Messenger Platform. See the [Facebook Setup Guide](../facebook_setup.md).
2. **Amazon Connect Instance ID** (`INSTANCE_ID`) — an existing Amazon Connect instance. See [Amazon Connect Prerequisites](../general_connect.md).
3. **Chat Inbound Contact Flow ID** (`CONTACT_FLOW_ID`) — a contact flow configured for chat in that instance. See [Amazon Connect Prerequisites](../general_connect.md).

### Deploy using CDK

1. Clone the repository and navigate to the project folder

```bash
git clone https://github.com/aws-samples/sample-amazon-connect-social-integration
cd facebook-messenger-connect-chat
```

2. Follow the [CDK Deployment Guide](../general_cdk_deploy.md) for environment setup and deployment commands.

## After Deployment Configuration

### 1. Update the Page Access Token in Secrets Manager

The stack creates a Secrets Manager secret named [`messenger-page-token`](https://console.aws.amazon.com/secretsmanager/secret?name=messenger-page-token) with a placeholder value. Update it with your actual non-expiring Page Access Token (see [Facebook Setup Guide — Step 5](../facebook_setup.md#step-5-generate-a-long-lived-page-access-token)).

### 2. Update the SSM Configuration Parameter

After deployment, go to [AWS Systems Manager — Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) and update the SSM parameter `/meta/messenger/config` with your Amazon Connect and Facebook details:

| Parameter | Description |
|---|---|
| `instance_id` | Amazon Connect instance ID (from the instance ARN) |
| `contact_flow_id` | Inbound contact flow ID (from the flow ARN) |
| `MESSENGER_VERIFICATION_TOKEN` | A secret string you choose — must match what you enter in the Meta webhook config |
| `page_id` | Your Facebook Page ID (from the App Dashboard → Messenger → Settings → Access Tokens) |

### 3. Configure the Webhook in Meta App Dashboard

1. Go to your Meta App Dashboard → Messenger → Settings → Webhooks
2. Set the **Callback URL** to the API Gateway URL. You can find it in the [SSM parameter](https://console.aws.amazon.com/systems-manager/parameters) `/meta/messenger/webhook/url`.
3. Set the **Verify Token** to the same value you used for `MESSENGER_VERIFICATION_TOKEN` above.
4. Subscribe to the `messages` webhook field (at minimum).

For full details, see [Facebook Setup Guide — Step 4](../facebook_setup.md#step-4-configure-webhooks).

## Testing

1. Open the CCP or Agent Workspace in your Amazon Connect instance.
2. Send a message to your Facebook Page from another Facebook account (or the same account if testing in development mode).
3. The message should appear in the CCP as a new chat contact.
4. Reply from the CCP and verify the response arrives in Messenger.
5. Try sending images and attachments in both directions.

<!-- TODO: edit demo video -->

### Verify Webhook Delivery

Check your Lambda logs in CloudWatch to confirm webhook events are being received:

```bash
aws logs tail /aws/lambda/FB-CONNECT-CHAT-L-MsgIN --follow
```

### Test Webhook Verification

```bash
curl -s "https://YOUR_API_URL/messages?hub.mode=subscribe&hub.verify_token=YOUR_VERIFY_TOKEN&hub.challenge=test123"
```

Should return: `test123`

## Important Considerations

### 24-Hour Messaging Window

Facebook Messenger has a **24-hour standard messaging window**:
- After a user sends a message, your Page has 24 hours to respond.
- Outside this window, you can only send messages using [Message Tags](https://developers.facebook.com/docs/messenger-platform/send-messages/message-tags) (limited use cases).
- Each new user message reopens the 24-hour window.

### Rate Limits

- Messenger Platform has rate limits based on your app's usage tier.
- Monitor API response headers for rate limit information.
- Implement exponential backoff for retries.

### App Review

- In **development mode**, your app can only receive messages from accounts with a role on the app (Admin, Developer, Tester).
- For production use with real customers, you need to submit for [App Review](https://developers.facebook.com/docs/app-review) and request **Advanced Access** for `pages_messaging`.
