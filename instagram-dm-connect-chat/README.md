# Instagram – Amazon Connect Chat

Bidirectional messaging between Instagram Direct Messages and Amazon Connect Chat. Handles inbound customer messages and outbound agent responses with session management and attachment support.



## Architecture

![Architecture Diagram](instagram-connect-chat.svg)

## How It Works

The solution bridges Instagram Messaging and Amazon Connect Chat through two event-driven paths connected by a shared DynamoDB connections table and an SNS topic.

### Inbound: Instagram → Amazon Connect

When a customer sends a message on Instagram:

1. **Instagram Webhooks** sends the event to API Gateway (`/messages` endpoint).
2. The **Inbound Handler** Lambda validates the webhook and parses the message using the Instagram Graph API.
3. It checks the connections table for an existing chat session:
   - **Existing session** — sends the message to Amazon Connect using the stored `connectionToken`. If the token is expired, it creates a new chat session automatically.
   - **No session** — calls `StartChatContact` to create a new chat, starts contact streaming to the SNS topic, creates a participant connection, and stores the session in DynamoDB.
4. The sender's Instagram profile is retrieved via the Graph API — including, among others, `name`, `username`, `profile_pic`, `follower_count`. The code stores these profiles in a user database (e.g., a DynamoDB Instagram profiles table) and checks it before calling the Graph API; only re-fetching when the cached profile is stale or missing, reducing API calls and latency on repeat conversations.

5. **Attachments** (images, documents, audio) are downloaded from Instagram's CDN and uploaded to the Connect chat via the Participant API.

### Outbound: Amazon Connect → Instagram

When an agent (human or AI) replies in Amazon Connect:

1. **Contact streaming** publishes the outbound message to the SNS topic (`messages_out`).
2. The **Outbound Handler** Lambda receives the SNS record.
3. It looks up the customer's Instagram user ID from the connections table using the `contactId`.
4. It sends the reply back to Instagram through the Graph API (`/{instagram_account_id}/messages`).
5. **Attachments** from the agent are fetched via a signed URL and forwarded as Instagram media messages (image, video, audio, or file).
6. On chat disconnect events, the connection record is deleted from DynamoDB.

### Session Management

A DynamoDB table (`active_connections`) tracks every open conversation:

| Field | Purpose |
|---|---|
| `contactId` (PK) | Amazon Connect contact identifier |
| `userId` (GSI) | Instagram-scoped user ID, used for lookups on inbound messages |
| `connectionToken` | Participant connection token for sending messages and attachments |
| `participantToken` | Token used to create the participant connection |
| `instagramAccountId` | Instagram Business Account ID used for outbound replies |
| `userName` | Customer display name from Instagram profile |
| `senderProfile` | Sender's Instagram public profile |

When a chat session expires or the participant leaves, the connection is cleaned up so the next inbound message starts a fresh session.

### Message Types Supported

| Direction | Text | Images | Documents 
|---|---|---|---|
| Inbound (customer → agent) | ✅ | ✅ | - |
| Outbound (agent → customer) | ✅ | ✅ | ✅ | 

_Sending documents from the Instagram user app is not currently possible, but users can receive documents from Amazon Connect attachments._

## What Gets Deployed

| Resource | Service | Purpose |
|---|---|---|
| `/messages` endpoint (GET & POST) | API Gateway | Receives Instagram webhook verification and inbound messages |
| Inbound Handler | Lambda | Processes Instagram messages and routes them to Amazon Connect Chat |
| Outbound Handler | Lambda | Sends agent replies back to Instagram via the Graph API |
| Active Connections table | DynamoDB | Tracks open chat sessions (`contactId` PK, `userId` GSI) |
| Instagram Users table | DynamoDB | Caches Instagram user profiles (TTL-based expiry) |
| `messages_out` topic | SNS | Delivers Amazon Connect streaming events to the Outbound Handler |
| `instagram-token` | Secrets Manager | Stores the Instagram User Access Token |
| `/meta/instagram/config` | SSM Parameter Store | Holds Connect instance ID, contact flow ID, verification token, and Instagram account ID |
| `/meta/instagram/webhook/url` | SSM Parameter Store | Stores the deployed API Gateway callback URL |

## Deployment

### Prerequisites

These are **not** created by this stack — you need them before deploying:

1. **Instagram User Access Token** — from an Instagram Business or Creator account configured with Meta's Instagram API. See the [Instagram Setup Guide](../instagram_setup.md).
2. **Amazon Connect Instance ID** (`INSTANCE_ID`) — an existing Amazon Connect instance. See [Amazon Connect Prerequisites](../general_connect.md).
3. **Chat Inbound Contact Flow ID** (`CONTACT_FLOW_ID`) — a contact flow configured for chat in that instance. See [Amazon Connect Prerequisites](../general_connect.md).

### Deploy using CDK

1. Clone the repository and navigate to the project folder

```bash
git clone https://github.com/aws-samples/sample-amazon-connect-social-integration
cd instagram-dm-connect-chat
```

2. Follow the [CDK Deployment Guide](../general_cdk_deploy.md) for environment setup and deployment commands.

## After Deployment Configuration

### 1. Update the Instagram Access Token

The stack creates a Secrets Manager secret named [`instagram-token`](https://console.aws.amazon.com/secretsmanager/secret?name=instagram-token) with a placeholder value. Update it with your actual Instagram User Access Token (see [Instagram Setup Guide](../instagram_setup.md#step-5-generate-instagram-user-access-token)).

### 2. Update the SSM Configuration Parameter

After deployment, go to [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) and update the SSM parameter `/meta/instagram/config` with your Amazon Connect and Instagram details:

| Parameter | Description |
|---|---|
| `instance_id` | Amazon Connect instance ID (from the instance ARN) |
| `contact_flow_id` | Inbound contact flow ID (from the flow ARN) |
| `INSTAGRAM_VERIFICATION_TOKEN` | A secret string you choose — must match the one configured in Meta's webhook settings |
| `instagram_account_id` | Your Instagram Business Account ID (IG_ID from Meta App Dashboard) |

**Note: To get your instagram_account_id, you have several options:**

(_revisit [Instagram Setup](../instagram_setup.md) for detailed instructions_)

- Value is in your Meta App Dashboard → Instagram → API Setup with instagram Login → expand "1. Generate access tokens" → ID should be underneath the linked instagram account.
- After everything is plugged in, receive a message and look at entry[].messaging.recipient.id (cloudwatch logs or Session DynamoDB Table)

Alternatively, call:
```bash
curl -X GET "https://graph.instagram.com/me?fields=id,username,account_type,user_id&access_token=YOUR_IG_ACCESS_TOKEN"

output:
{
    "id":"SOME_ID",
    "username":"IG_USERNAME",
    "account_type":"BUSINESS",
    "user_id":"instagram_account_id" <- this is the value
} 
```

### 3. Configure the Webhook in Meta App Dashboard

1. Go to your Meta App Dashboard → Instagram → API Setup with Instagram Login → Webhooks
2. Set the **Callback URL** to the API Gateway URL. You can find it in the [SSM parameter](https://console.aws.amazon.com/systems-manager/parameters) `/meta/instagram/webhook/url`.
3. Set the **Verify Token** to the same value you used for `INSTAGRAM_VERIFICATION_TOKEN` above.
4. Subscribe to the `messages` webhook field.

For full details, see [Instagram Setup Guide — Step 4](../instagram_setup.md#step-4-configure-webhooks).

## Testing

<div align="center">
<video src="https://github.com/user-attachments/assets/5f6d988b-5340-4b32-ac1b-ec85114adb2b" width="540" controls></video>
</div>


1. Open the CCP or Agent Workspace in your Amazon Connect instance.
2. Send a Direct Message to your Instagram Business account from another Instagram account.
3. The message should appear in the CCP as a new chat contact.
4. Reply from the CCP and verify the response arrives in Instagram.
5. Try sending images in both directions and files from the Amazon Connect agent.

