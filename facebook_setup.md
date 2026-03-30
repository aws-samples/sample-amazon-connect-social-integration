# Facebook Messenger Setup

> **Note:** This guide was built as a best effort to compile a working tutorial with the information available as of March 2026. Meta's platform, APIs, and processes may change at any time. Always check [Meta's official and up-to-date documentation](https://developers.facebook.com/docs/messenger-platform/) before proceeding.

## Overview

Step-by-step guide to set up Facebook Messenger Platform integration, including creating a Meta App, configuring webhooks, generating a Page Access Token, and subscribing your Page to receive messages.

## Prerequisites

- ✅ A **Facebook Page** (Business or personal Page you admin)
- ✅ A **Facebook account** with admin access to the Page
- ✅ An HTTPS endpoint for webhooks (your deployed API Gateway URL)

## Step 1: Create a Meta App

### 1.1 Register as a Meta Developer

1. Navigate to [Meta for Developers](https://developers.facebook.com/)
2. Log in with your Facebook account
3. Complete the developer registration process if you haven't already ([register as a Meta Developer](https://developers.facebook.com/docs/development/register))

### 1.2 Create Your App

1. Go to [Meta for Developers Apps](https://developers.facebook.com/apps/)
2. Click **"Create App"**
3. Choose **"Business"** as the app type
4. Fill in your app details:
   - **App Name**: Choose a descriptive name (e.g., "Messenger Connect Chat")
   - **App Contact Email**: Your business email
   - **Business Account**: Select or create your Meta Business Account
5. Click **"Create App"**

**Reference**: [Create an App](https://developers.facebook.com/docs/development/create-an-app)

## Step 2: Add the Messenger Product

### 2.1 Add Messenger to Your App

1. In your App Dashboard, scroll to **"Add products to your app"**
2. Find **"Messenger"** and click **"Set Up"**
3. You will be taken to the Messenger Settings page

**Reference**: [Messenger Platform App Setup](https://developers.facebook.com/docs/messenger-platform/getting-started/app-setup)

## Step 3: Connect Your Facebook Page

### 3.1 Generate a Page Access Token

1. In the App Dashboard, go to **Messenger** > **Settings**
2. In the **"Access Tokens"** section, click **"Add or Remove Pages"**
3. Log in with your Facebook account and select the Page you want to connect
4. Grant the requested permissions (`pages_messaging`, `pages_manage_metadata`)
5. Once the Page is added, click **"Generate Token"** next to your Page
6. Copy the **Page Access Token** — you will store this in AWS Secrets Manager

> **Important**: The token generated here is a short-lived token. See Step 5 for generating a long-lived (non-expiring) Page Access Token.

### 3.2 Note Your Page ID

The Page ID is displayed next to your Page name in the Access Tokens section. Copy it — you will need it for the SSM config parameter.

### 3.3 Test Your Page Access Token

Verify your token works:

```bash
curl -X GET "https://graph.facebook.com/v24.0/me?access_token={YOUR_PAGE_ACCESS_TOKEN}"
```

**Success Response**:
```json
{
  "name": "Your Page Name",
  "id": "123456789012345"
}
```

You can also use the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) to inspect your token's permissions and expiration.

## Step 4: Configure Webhooks

### 4.1 Understanding Webhook Requests

Your endpoint must handle two types of requests:

#### A. Verification Requests (GET)

When you configure webhooks, Meta sends a GET request with `hub.mode`, `hub.verify_token`, and `hub.challenge` query parameters. Your endpoint must return the `hub.challenge` value if the verify token matches.

#### B. Event Notifications (POST)

When a message is received, Meta sends a POST request with a JSON payload containing the message data.

### 4.2 Configure Webhooks in App Dashboard

1. In your App Dashboard, go to **Messenger** > **Settings**
2. Scroll to the **"Webhooks"** section
3. Click **"Add Callback URL"** (or **"Edit Callback URL"** if already configured)
4. Enter your webhook configuration:
   - **Callback URL**: Your deployed API Gateway URL (e.g., `https://ko9oe59kv4.execute-api.us-west-2.amazonaws.com/prod/messages`)
   - **Verify Token**: The value you set in your SSM parameter `/meta/messenger/config` under `MESSENGER_VERIFICATION_TOKEN` (default: `CREATE_ONE`)
5. Click **"Verify and Save"**

Meta will immediately send a GET request to verify your endpoint. If successful, you'll see a confirmation.

### 4.3 Subscribe to Webhook Fields

After successful verification, subscribe to the following fields:

- ✅ **messages** — Receive incoming messages (text and attachments)
- ✅ **messaging_postbacks** — Receive postback events (button clicks)
- ✅ **message_deliveries** — Receive delivery confirmations
- ✅ **message_reads** — Receive read receipts

At minimum, you need **messages** subscribed for the integration to work.

### 4.4 Subscribe Your Page to the App

After configuring webhooks, you must subscribe your Page to the app so it receives webhook events:

1. In the **Webhooks** section, under your Page, click **"Subscribe"** (or toggle on the subscription)
2. Alternatively, use the API:

```bash
curl -i -X POST "https://graph.facebook.com/{PAGE_ID}/subscribed_apps?subscribed_fields=messages&access_token={PAGE_ACCESS_TOKEN}"
```

**Success Response**:
```json
{
  "success": true
}
```

**Reference**: [Messenger Webhooks](https://developers.facebook.com/docs/messenger-platform/getting-started/app-setup)

## Step 5: Generate a Long-Lived Page Access Token

The token from Step 3 is short-lived (expires in ~1-2 hours). For production, you need a non-expiring Page Access Token.

### 5.1 Get a Long-Lived User Access Token

Exchange your short-lived User Access Token for a long-lived one (~60 days):

```bash
curl -i -X GET "https://graph.facebook.com/v24.0/oauth/access_token?grant_type=fb_exchange_token&client_id={APP_ID}&client_secret={APP_SECRET}&fb_exchange_token={SHORT_LIVED_USER_TOKEN}"
```

**Where to find these values**:
- `{APP_ID}`: App Dashboard > Settings > Basic > App ID
- `{APP_SECRET}`: App Dashboard > Settings > Basic > App Secret (click "Show")
- `{SHORT_LIVED_USER_TOKEN}`: Get from [Graph API Explorer](https://developers.facebook.com/tools/explorer/) by selecting your app and generating a User Access Token with `pages_show_list` and `pages_messaging` permissions

**Response**:
```json
{
  "access_token": "{LONG_LIVED_USER_TOKEN}",
  "token_type": "bearer",
  "expires_in": 5183944
}
```

### 5.2 Get a Non-Expiring Page Access Token

Use the long-lived User Access Token to request a Page Access Token (which does not expire):

```bash
curl -i -X GET "https://graph.facebook.com/v24.0/me/accounts?access_token={LONG_LIVED_USER_TOKEN}"
```

**Response**:
```json
{
  "data": [
    {
      "access_token": "{NEVER_EXPIRING_PAGE_TOKEN}",
      "category": "Brand",
      "name": "Your Page Name",
      "id": "123456789012345",
      "tasks": ["ADVERTISE", "ANALYZE", "CREATE_CONTENT", "MESSAGING", "MODERATE", "MANAGE"]
    }
  ]
}
```

### 5.3 Verify the Token Does Not Expire

Use the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) to confirm:
- **Expires**: Should show **"Never"**
- **Valid**: Should show **"True"**
- **Scopes**: Should include `pages_messaging`

### 5.4 Summary of Token Flow

```
Short-lived User Token (1-2 hours)
    ↓ exchange with App ID + App Secret
Long-lived User Token (~60 days)
    ↓ request /me/accounts
Non-expiring Page Access Token (never expires)
```

**Reference**: [Get Long-Lived Tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived)

## Step 6: Store Credentials in AWS

### 6.1 Update the Page Access Token in Secrets Manager

Store your non-expiring Page Access Token in the deployed secret:

```bash
aws secretsmanager put-secret-value \
  --secret-id messenger-page-token \
  --secret-string "{YOUR_NEVER_EXPIRING_PAGE_TOKEN}"
```

### 6.2 Update the SSM Config Parameter

Update the config parameter with your actual values:

```bash
aws ssm put-parameter \
  --name "/meta/messenger/config" \
  --type "String" \
  --overwrite \
  --value '{
    "instance_id": "YOUR_CONNECT_INSTANCE_ID",
    "contact_flow_id": "YOUR_CONTACT_FLOW_ID",
    "MESSENGER_VERIFICATION_TOKEN": "YOUR_SECURE_VERIFY_TOKEN",
    "page_id": "YOUR_PAGE_ID"
  }'
```

**Where to find these values**:
- `instance_id`: Amazon Connect console > Your instance > Instance ARN (the UUID after `instance/`)
- `contact_flow_id`: Amazon Connect console > Contact flows > Your flow > Show additional flow information > Contact Flow ID
- `MESSENGER_VERIFICATION_TOKEN`: A secure random string you choose (must match what you entered in the Meta webhook config)
- `page_id`: From Step 3.2

## Step 7: App Review and Publishing

### 7.1 Understanding Access Levels

- **Standard Access**: Works only for people with roles on your app (Admin, Developer, Tester). Good for testing.
- **Advanced Access**: Required for production use with real customers. Requires App Review.

### 7.2 Testing in Development Mode

During development (Standard Access), your app can only receive messages from:
- Facebook accounts that have a role on your app (Admin, Developer, Tester)
- You can add testers in **App Roles** > **Roles** in your App Dashboard

### 7.3 Requesting Advanced Access

For production use, you need to submit your app for App Review:

1. Go to **App Review** > **Permissions and Features** in your App Dashboard
2. Request **Advanced Access** for:
   - `pages_messaging` — Send and receive messages
   - `pages_manage_metadata` — Subscribe to webhooks
3. Provide a detailed description of your use case
4. Submit a screencast showing how your app uses Messenger
5. Wait for Meta's review (typically 1-5 business days)

**Reference**: [App Review](https://developers.facebook.com/docs/app-review)

## Step 8: Test the Integration

### 8.1 Send a Test Message

1. Open Facebook Messenger (web or mobile)
2. Search for your Facebook Page
3. Send a message to your Page
4. Check your Amazon Connect agent workspace — the message should appear as a new chat

### 8.2 Verify Webhook Delivery

Check your Lambda logs in CloudWatch to confirm webhook events are being received:

```bash
aws logs tail /aws/lambda/FB-CONNECT-CHAT-L-MsgIN --follow
```

### 8.3 Test Webhook Verification

```bash
curl -s "https://YOUR_API_URL/messages?hub.mode=subscribe&hub.verify_token=YOUR_VERIFY_TOKEN&hub.challenge=test123"
```

Should return: `test123`

## Important Considerations

### 24-Hour Messaging Window

Facebook Messenger has a **24-hour standard messaging window**:
- After a user sends a message, your Page has **24 hours** to respond
- Outside this window, you can only send messages using Message Tags (limited use cases)
- Each new user message reopens the 24-hour window

### Rate Limits

- Messenger Platform has rate limits based on your app's usage tier
- Monitor API response headers for rate limit information
- Implement exponential backoff for retries

### Supported Message Types

- ✅ Text messages
- ✅ Images (JPEG, PNG, GIF)
- ✅ Videos (MP4)
- ✅ Audio files (MP3)
- ✅ Files (PDF, DOC, etc.)
- ✅ Templates (generic, button, receipt)
- ✅ Quick replies
- ✅ Sender actions (typing indicators)

### Webhook Payload Signature Validation

Meta signs all webhook payloads with SHA256 using your App Secret. While optional, it's recommended to validate the `X-Hub-Signature-256` header to ensure payloads are genuine.

## Additional Resources

### Official Meta Documentation

- 🔗 [Messenger Platform Overview](https://developers.facebook.com/docs/messenger-platform/) — Main documentation
- 🔗 [Messenger Platform Get Started](https://developers.facebook.com/docs/messenger-platform/get-started/) — Quick start guide
- 🔗 [App Setup](https://developers.facebook.com/docs/messenger-platform/getting-started/app-setup) — Webhook and app configuration
- 🔗 [Send API Reference](https://developers.facebook.com/docs/messenger-platform/reference/send-api/) — Sending messages
- 🔗 [Webhook Events Reference](https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/) — Webhook payload formats
- 🔗 [Page Access Tokens](https://developers.facebook.com/docs/pages/access-tokens) — Token management
- 🔗 [Long-Lived Tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived) — Token exchange guide

### Tools

- 🔗 [Graph API Explorer](https://developers.facebook.com/tools/explorer/) — Test API calls interactively
- 🔗 [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) — Inspect and debug tokens
- 🔗 [Webhooks Test Tool](https://developers.facebook.com/tools/debug/webhooks/) — Test webhook delivery

*This guide is based on Meta documentation for the Messenger Platform as of March 2026. Always refer to the [Meta for Developers documentation](https://developers.facebook.com/docs/messenger-platform/) for the most up-to-date information.*
