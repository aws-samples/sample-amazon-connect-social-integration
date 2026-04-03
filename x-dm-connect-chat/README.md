# X (Twitter) DMs – Amazon Connect Chat

Bidirectional messaging between X (Twitter) Direct Messages and Amazon Connect Chat. Handles inbound customer DMs and outbound agent responses with session management and attachment support.

> **Encrypted DM Limitation:** End-to-end encrypted DMs are not accessible via the X API. This integration only processes non-encrypted (standard) DMs. If a user has E2EE enabled for a conversation, those messages will not be delivered to the webhook. This a X API known limitation.

## Architecture

![Architecture Diagram](x-connect-chat.svg)

## How It Works

The solution bridges X Direct Messages and Amazon Connect Chat through two event-driven paths connected by a shared DynamoDB connections table and an SNS topic.

### Inbound: X → Amazon Connect

When a customer sends a DM to the business X account:

1. **X Account Activity API v2** sends the event to API Gateway (`/webhooks` endpoint).
2. The **Inbound Handler** Lambda validates the webhook and parses the `direct_message_events` payload.
3. It filters out messages sent by the business's own X account (echo prevention).
4. It checks the connections table for an existing chat session:
   - **Existing session** — sends the message to Amazon Connect using the stored `connectionToken`. If the token is expired, it creates a new chat session automatically.
   - **No session** — calls `StartChatContact` to create a new chat, starts contact streaming to the SNS topic, creates a participant connection, and stores the session in DynamoDB.
5. The sender's X profile is retrieved via the Tweepy SDK (`client.get_user`) — including `name`, `username`, and `profile_image_url`. Profiles are cached in a DynamoDB X Users table with a 7-day TTL, reducing API calls on repeat conversations.

### Outbound: Amazon Connect → X

When an agent (human or AI) replies in Amazon Connect:

1. **Contact streaming** publishes the outbound message to the SNS topic (`messages_out`).
2. The **Outbound Handler** Lambda receives the SNS record.
3. It looks up the customer's X user ID from the connections table using the `contactId`.
4. It sends the reply back to X as a DM using the Tweepy SDK (`client.create_direct_message`).
5. **Attachments** from the agent are fetched via a signed URL, uploaded to X using `API.media_upload()` or `API.chunked_upload()` (OAuth 1.0a) depending on the media type, and sent as a DM with the media attached. Unsupported media types (PDFs, documents) are sent as plain-text links. If the upload fails, the signed URL is sent as plain text.
6. On chat disconnect events, the connection record is deleted from DynamoDB.

### CRC Webhook Validation

X uses a **Challenge-Response Check (CRC)** to verify webhook ownership — this differs from Meta's `hub.verify_token` approach used in the Instagram and Facebook Messenger integrations.

| | X (this project) | Meta (Instagram / Facebook) |
|---|---|---|
| **Method** | HMAC-SHA256 cryptographic challenge | Shared secret string comparison |
| **Flow** | X sends GET with `crc_token` → endpoint computes HMAC-SHA256 hash using Consumer Secret → returns `{"response_token": "sha256=<hash>"}` | Meta sends GET with `hub.verify_token` → endpoint compares against stored token → returns `hub.challenge` |
| **Frequency** | Periodic (X re-validates the webhook regularly) | Once during webhook registration |
| **Security** | Cryptographic proof of secret possession | Shared secret comparison |

### Session Management

A DynamoDB table (`active_connections`) tracks every open conversation:

| Field | Purpose |
|---|---|
| `contactId` (PK) | Amazon Connect contact identifier |
| `userId` (GSI) | X user ID, used for lookups on inbound messages |
| `connectionToken` | Participant connection token for sending messages and attachments |
| `participantToken` | Token used to create the participant connection |
| `xAccountId` | Business X account ID used for outbound routing |
| `userName` | Customer display name from X profile |
| `senderProfile` | Cached X user profile data |

When a chat session expires or the participant leaves, the connection is cleaned up so the next inbound message starts a fresh session.

### Message Types Supported

| Direction | Text | Images | Videos | GIFs |
|---|---|---|---|---|
| Inbound (customer → agent) | ✅ | ✅ | ✅ | ✅ |
| Outbound (agent → customer) | ✅ | ✅ | ✅ | ✅ |

_Unsupported media types (PDFs, documents, etc.) are sent as plain-text links._

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

## Deployment

### Prerequisites

These are **not** created by this stack — you need them before deploying:

1. **X Developer Account with Pay-Per-Use Tier** — You need an X Developer Account with at least the **Pay-Per-Use** (formerly Basic) tier to access the Account Activity API and DM endpoints. See the [X Platform Setup Guide](../x_setup.md) for detailed instructions.
2. **X API Credentials** — Four OAuth 1.0a credentials: Consumer Key (API Key), Consumer Secret (API Secret), Access Token, and Access Token Secret. Generated from the X Developer Portal. See [X Platform Setup Guide — Steps 2 & 3](../x_setup.md#step-2-create-an-app).
3. **Amazon Connect Instance ID** (`INSTANCE_ID`) — an existing Amazon Connect instance. See [Amazon Connect Prerequisites](../general_connect.md).
4. **Chat Inbound Contact Flow ID** (`CONTACT_FLOW_ID`) — a contact flow configured for chat in that instance. See [Amazon Connect Prerequisites](../general_connect.md).

### Deploy using CDK

1. Clone the repository and navigate to the project folder

```bash
git clone https://github.com/aws-samples/sample-amazon-connect-social-integration
cd x-dm-connect-chat
```

2. Follow the [CDK Deployment Guide](../general_cdk_deploy.md) for environment setup and deployment commands.

## After Deployment Configuration

### 1. Update the X API Credentials in Secrets Manager

The stack creates a Secrets Manager secret named [`x-dm-credentials`](https://console.aws.amazon.com/secretsmanager/secret?name=x-dm-credentials) with placeholder values. Update it with your actual X API credentials as a JSON object:

```json
{
  "consumer_key": "YOUR_CONSUMER_KEY",
  "consumer_secret": "YOUR_CONSUMER_SECRET",
  "access_token": "YOUR_ACCESS_TOKEN",
  "access_token_secret": "YOUR_ACCESS_TOKEN_SECRET"
}
```

### 2. Update the SSM Configuration Parameter

After deployment, go to [AWS Systems Manager — Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) and update the SSM parameter `/x/dm/config` with your Amazon Connect and X details:

| Parameter | Description |
|---|---|
| `instance_id` | Amazon Connect instance ID (from the instance ARN) |
| `contact_flow_id` | Inbound contact flow ID (from the flow ARN) |
| `x_account_id` | Your X account's numeric user ID (the business account that will receive DMs) |

**Note:** To find your `x_account_id`, run the included helper script or use the X API. See [X Platform Setup Guide — Step 4.2](../x_setup.md#42-update-the-ssm-configuration-parameter) for details.

### 3. Register the Webhook and Subscribe Your Account

Follow [X Platform Setup Guide — Steps 5 & 6](../x_setup.md#step-5-register-the-webhook) to register your webhook URL with X and subscribe your account to receive DM events. The deployed webhook URL is stored in the SSM parameter `/x/dm/webhook/url`.

The Inbound Handler responds to CRC challenges automatically — no manual configuration needed on the Lambda side.

## Testing

<div align="center">
<video src="https://github.com/user-attachments/assets/3fe667d9-1887-4acb-8ccf-3596d5c562a4" width="540" controls></video>
</div>

1. Open the CCP or Agent Workspace in your Amazon Connect instance.
2. Send a Direct Message to your business X account from another X account.
3. The message should appear in the CCP as a new chat contact.
4. Reply from the CCP and verify the response arrives as a DM on X.
5. Try sending attachments from the Amazon Connect agent and verify they arrive on X.

## Important Considerations

### Encrypted DMs

X supports end-to-end encrypted (E2EE) Direct Messages. However, **encrypted DMs are not accessible via the X API**. This integration only processes standard (non-encrypted) DMs. If a conversation is encrypted, the webhook will not receive those message events.

### X API Rate Limits

- The X API enforces rate limits on DM endpoints. The Account Activity API has its own limits on webhook registrations and CRC validations.
- Monitor your usage in the [X Developer Portal](https://developer.x.com/) dashboard.

### Pay-Per-Use Tier

- The **Pay-Per-Use** tier is required for Account Activity API access. The free tier does not include webhook-based DM delivery.
- Review [X API pricing](https://developer.x.com/en/products/twitter-api) for current tier details and costs.

### CRC Re-validation

- X periodically re-sends CRC challenges to verify your webhook is still valid. The Inbound Handler handles this automatically, but ensure the Secrets Manager credentials remain valid and the Lambda function stays deployed.

### OAuth 1.0a Credentials

- All four credentials (Consumer Key, Consumer Secret, Access Token, Access Token Secret) must remain valid. If you regenerate any credential in the X Developer Portal, update the Secrets Manager secret immediately.
- The Access Token and Access Token Secret are tied to the specific X user account that owns the app. Ensure this is the business account that should receive and send DMs.
