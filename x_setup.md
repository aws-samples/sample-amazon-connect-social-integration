# X (Twitter) Platform Setup

> **Note:** This guide was built as a best effort to compile a working tutorial with the information available as of April 2026. X's platform, APIs, and processes may change at any time. Always check [X's official and up-to-date documentation](https://docs.x.com/) before proceeding.

## Overview

Step-by-step guide to set up the X (Twitter) platform side of the integration, including creating an X Developer App, generating OAuth 1.0a credentials, configuring the Account Activity API v2 webhook, and subscribing your account to receive Direct Message events.

## Prerequisites

- ✅ An **X (Twitter) account** that will act as the business account receiving DMs
- ✅ A **payment method** for the Pay-Per-Use tier
- ✅ An HTTPS endpoint for webhooks (your deployed API Gateway URL — deploy the CDK stack first)

## Step 1: Create an X Developer Account

### 1.1 Sign Up for the Developer Portal

1. Navigate to the [X Developer Portal](https://developer.x.com/)
2. Click **"Sign Up"** and log in with the X account that will be your business account
3. Complete the developer registration process — you'll need to describe your intended use case
4. Accept the Developer Agreement and Policy

### 1.2 Select the Pay-Per-Use Tier

The **Pay-Per-Use** tier is required for Account Activity API access and DM read/write capabilities. The free tier does not include webhook-based DM delivery.

1. In the [Developer Portal](https://developer.x.com/), navigate to the pricing section
2. Select the **Pay-Per-Use** plan
3. Add a payment method and confirm

> **Important:** The Pay-Per-Use tier is credit-based. Review [X API pricing](https://developer.x.com/#pricing) for current costs. The Account Activity API on Pay-Per-Use supports up to 3 unique subscriptions and 1 webhook.

**Reference**: [Getting Access](https://docs.x.com/x-api/getting-started/getting-access)

## Step 2: Create an App

### 2.1 Create a New App

1. Go to the [X Developer Console](https://console.x.com/)
2. On the left panel under **"Your Apps"**, click **"Create App"**
3. Give it a descriptive name (e.g., "Connect Chat DM Integration")
4. The app will appear under **"Your Apps"** with an **ACTIVE** badge and an App ID

### 2.2 Configure App Permissions (Critical)

This is the most important step — the app needs DM permissions. Without this, the webhook will not receive `direct_message_events`.

1. Click on your app name to open the app details panel
2. Under **"OAuth 2.0 Keys"**, click **"Edit settings"**
3. In the permissions section, make sure **"Direct Messages"** is enabled (Read, Write, and Direct Messages)
4. Set the Type of App to **"Web App, Automated App or Bot"**
5. Fill in the required Callback URL and Website URL (these can be your API Gateway URL or your company website — they're required by the form but not used by the webhook flow)
6. Save the settings

> **Critical:** If the Access Token section shows only **"Read and write"** without mentioning Direct Messages, the permissions are wrong. Fix them via "Edit settings" under OAuth 2.0 Keys, then **regenerate** the Access Token — permissions are baked into the token at generation time.

**Reference**: [API Key and Secret](https://docs.x.com/fundamentals/authentication/oauth-1-0a/api-key-and-secret)

## Step 3: Generate API Credentials

You need four credentials for OAuth 1.0a authentication. All four are stored together in AWS Secrets Manager. The app details panel has three sections:

### 3.1 App-Only Authentication — Bearer Token

At the top of the app details panel:

1. Find the **"Bearer Token"** section under **"App-Only Authentication"**
2. Click **"Regenerate"** (or copy if already generated)
3. Save this value — you'll need it for webhook registration (Step 5)

### 3.2 OAuth 1.0 Keys — Consumer Key and Consumer Secret

In the middle section:

1. Find **"OAuth 1.0 Keys"**
2. **Consumer Key** — click **"Show"** to reveal it, then copy
3. **Consumer Secret** — click **"Regenerate"** if needed, then copy

> **Warning:** The Consumer Secret is only shown once after regeneration. Copy it immediately.

### 3.3 OAuth 1.0 Keys — Access Token and Access Token Secret

Still in the **"OAuth 1.0 Keys"** section:

1. Find the **"Access Token"** row — it shows which account it's for (e.g., "For @youraccount") and the current permission level
2. **Verify the permission level says "Read, write, and Direct Messages"** — if it only says "Read and write", go back to Step 2.2 and fix the permissions first
3. Click **"Generate"** (or **"Regenerate"** if tokens already exist)
4. Copy both the **Access Token** and **Access Token Secret**

> **Important:** If you changed permissions after generating tokens, you MUST regenerate them. The old tokens still carry the old permission scope.

### 3.4 Summary of Credentials

| Credential | Where in Console | Used For |
|---|---|---|
| Bearer Token | App-Only Authentication section | Webhook registration (app-level operations) |
| Consumer Key | OAuth 1.0 Keys section | OAuth 1.0a signing, Tweepy client, CRC validation |
| Consumer Secret | OAuth 1.0 Keys section | OAuth 1.0a signing, CRC validation |
| Access Token | OAuth 1.0 Keys section | Acting as the business account |
| Access Token Secret | OAuth 1.0 Keys section | Acting as the business account |

### 3.5 Verify Credentials Are Ready

At this point you should have all five credentials saved somewhere secure:
- Bearer Token
- Consumer Key
- Consumer Secret
- Access Token (with "Read, write, and Direct Messages" permission)
- Access Token Secret

You'll verify they work in Step 4.2 after storing them in AWS Secrets Manager.

## Step 4: Store Credentials in AWS

### 4.1 Update the X API Credentials in Secrets Manager

The CDK stack creates a Secrets Manager secret named `x-dm-credentials` with placeholder values. Update it with your actual credentials:

```bash
aws secretsmanager put-secret-value \
  --secret-id x-dm-credentials \
  --secret-string '{
    "consumer_key": "YOUR_CONSUMER_KEY",
    "consumer_secret": "YOUR_CONSUMER_SECRET",
    "access_token": "YOUR_ACCESS_TOKEN",
    "access_token_secret": "YOUR_ACCESS_TOKEN_SECRET"
  }'
```

Or update via the [AWS Secrets Manager Console](https://console.aws.amazon.com/secretsmanager/secret?name=x-dm-credentials).

### 4.2 Update the SSM Configuration Parameter

First, get your numeric X account ID by verifying the credentials you just stored:

```bash
cd x-dm-connect-chat
python test_x_credentials.py
```

**Expected output:**
```
Retrieving credentials from Secrets Manager...
  ✓ consumer_key found
  ✓ consumer_secret found
  ✓ access_token found
  ✓ access_token_secret found

Authenticating with X API...

  ID:       40876567
  Name:     Your Business Name
  Username: @yourbusiness

Use this as your x_account_id in /x/dm/config: 40876567
```

If any credential shows as missing or placeholder, go back to Step 3 and regenerate it.

Now update the SSM parameter `/x/dm/config` using the ID from the output above:

```bash
aws ssm put-parameter \
  --name "/x/dm/config" \
  --type "String" \
  --overwrite \
  --value '{
    "instance_id": "YOUR_CONNECT_INSTANCE_ID",
    "contact_flow_id": "YOUR_CONTACT_FLOW_ID",
    "x_account_id": "YOUR_NUMERIC_X_ACCOUNT_ID"
  }'
```

| Parameter | How to Find It |
|---|---|
| `instance_id` | Amazon Connect console → Your instance → Instance ARN (the UUID after `instance/`) |
| `contact_flow_id` | Amazon Connect console → Contact flows → Your flow → Show additional flow information → Contact Flow ID |
| `x_account_id` | From `test_x_credentials.py` output above — the `ID` value |


## Step 5: Register the Webhook

Now that your credentials are stored and the CDK stack is deployed, register your webhook URL with X.

### 5.1 Get Your Webhook URL

Find your deployed webhook URL in the SSM parameter:

```bash
aws ssm get-parameter --name "/x/dm/webhook/url" --query "Parameter.Value" --output text
```

It will look something like: `https://abc123xyz.execute-api.us-west-2.amazonaws.com/prod/webhooks`

### 5.2 Register the Webhook with X

Use the V2 Webhooks API to register your URL. This requires the **Bearer Token** (app-only auth):

```bash
curl --request POST \
  --url 'https://api.x.com/2/webhooks' \
  --header 'Authorization: Bearer YOUR_BEARER_TOKEN' \
  --header 'Content-Type: application/json' \
  --data '{
    "url": "YOUR_WEBHOOK_URL"
  }'
```

**Success Response (200 OK):**
```json
{
  "data": {
    "id": "1234567890",
    "url": "https://abc123xyz.execute-api.us-west-2.amazonaws.com/prod/webhooks",
    "valid": true,
    "created_at": "2026-04-01T12:00:00.000Z"
  }
}
```

> **What happens behind the scenes:** When you make this request, X immediately sends a CRC challenge (GET request with `crc_token`) to your webhook URL. The Inbound Handler Lambda computes the HMAC-SHA256 response automatically. If the CRC passes, the webhook is registered with `valid: true`.

Save the webhook `id` from the response — you'll need it for the next step.

### 5.3 Troubleshooting Registration Failures

| Error | Cause | Fix |
|---|---|---|
| `CrcValidationFailed` | Lambda didn't respond correctly to CRC | Verify `consumer_secret` in Secrets Manager. Check Lambda CloudWatch logs. |
| `UrlValidationFailed` | URL format is invalid | Ensure HTTPS, no port number |
| `DuplicateUrlFailed` | URL already registered | Use `GET /2/webhooks` to list, delete old one first |
| `WebhookLimitExceeded` | Max webhooks for your tier | Pay-Per-Use allows 1 webhook. Delete unused ones. |

### 5.4 Verify the Webhook is Registered

```bash
curl --request GET \
  --url 'https://api.x.com/2/webhooks' \
  --header 'Authorization: Bearer YOUR_BEARER_TOKEN'
```

Confirm `valid` is `true` in the response.

**Reference**: [V2 Webhooks API Quickstart](https://docs.x.com/x-api/webhooks/quickstart)

## Step 6: Subscribe Your Account to the Webhook

Registering the webhook only sets up the endpoint. You must also subscribe your business account so X delivers events (including DMs) to it.

### 6.1 Create a Subscription

Use the provided helper script which pulls credentials from Secrets Manager and handles everything:

```bash
cd x-dm-connect-chat
python subscribe_webhook.py
```

**Expected output:**
```
Retrieving credentials from Secrets Manager...
Getting Bearer Token...
Looking up registered webhooks...
  Webhook ID:  1234567890
  URL:         https://abc123xyz.execute-api.us-west-2.amazonaws.com/prod/webhooks
  Valid:       True
Subscribing to webhook 1234567890...
  ✓ Subscription created successfully
```

### 6.2 Verify the Subscription

Check that the subscription is active:

```bash
curl --request GET \
  --url 'https://api.x.com/2/account_activity/webhooks/WEBHOOK_ID/subscriptions/all/list' \
  --header 'Authorization: Bearer YOUR_BEARER_TOKEN'
```

You should see your account's user ID listed in the subscriptions.

> **Important:** If you change app permissions (e.g., adding Direct Messages), X may revoke the subscription. You'll see a `user_event` with `revoke` in the Lambda logs. Re-run `python subscribe_webhook.py` after any permission change.

**Reference**: [Account Activity API — Create Subscription](https://docs.x.com/x-api/account-activity/create-subscription)

## Step 7: Test the Integration

### 7.1 Test CRC Validation

Manually trigger a CRC re-validation:

```bash
curl --request PUT \
  --url 'https://api.x.com/2/webhooks/WEBHOOK_ID' \
  --header 'Authorization: Bearer YOUR_BEARER_TOKEN'
```

**Success Response:** `{"data":{"valid":true}}`

### 7.2 Send a Test DM

1. Open X (web or mobile) from a **different account** (not the business account)
2. Send a Direct Message to your business account
3. Check your Amazon Connect agent workspace — the message should appear as a new chat contact
4. Reply from the agent workspace and verify the response arrives as a DM on X


### 7.4 Common Test Issues

| Issue | Likely Cause | Fix |
|---|---|---|
| DM not appearing in Connect | Webhook not receiving events | Verify subscription is active (Step 6.2). Check app permissions include "Direct Messages". |
| CRC failing periodically | Credentials changed | Ensure `consumer_secret` in Secrets Manager matches Console |
| Agent reply not delivered | Outbound Lambda error | Check Outbound Handler logs. Verify Access Token has DM permissions. |
| Echo messages | `x_account_id` wrong | Verify SSM config has correct numeric X account ID |
| Some users' DMs not received | XChat encrypted conversation | See "Known Limitation" below. Not fixable on our side. |

## Known Limitation: XChat Encrypted Conversations

As of early 2026, X has been rolling out **"XChat"** — an upgraded encrypted DM system. This is the most common reason DMs from some users don't trigger webhook events while others work fine.

Key facts ([confirmed by X staff](https://devcommunity.x.com/t/activity-api-chat-webhooks-not-received/256906/4), Feb 2026):

- Conversations can be **silently auto-upgraded** to encrypted XChat, especially between verified/premium accounts
- There is often **no visible lock icon** — the conversation looks normal on x.com
- The X API (including webhooks) is **completely blind** to encrypted conversations — no event, no error, just silence
- X staff confirmed: *"X Chat encrypted DM conversations are currently not supported by the X API. We are exploring ways to bring X Chat support very soon."*
- This affects the DM Events endpoint, Account Activity API webhooks, and DM lookup endpoints equally

**Workaround (not guaranteed):** Have the affected user delete the existing conversation and start a brand new one. Sometimes the new conversation won't be auto-upgraded.

**Tracking:** Monitor the [X Developer Community](https://devcommunity.x.com/) for updates on XChat API support.

## Important Considerations

### Credential Rotation

If you regenerate any credential in the Developer Console:
1. Update the Secrets Manager secret immediately
2. If you regenerated the Consumer Secret, CRC validation will fail until updated
3. If you regenerated the Access Token/Secret, outbound DMs will fail until updated
4. After any permission change, re-run `python subscribe_webhook.py`
5. The Bearer Token is only used for webhook management — not by the Lambda functions

### Pay-Per-Use Tier Limits

| Resource | Pay-Per-Use Limit |
|---|---|
| Webhooks | 1 |
| Unique Subscriptions | 3 |
| DM send rate | 200 per 15 min per user |

### Monitor Webhook Health

X re-sends CRC challenges approximately every hour. If CRC fails, the webhook is marked invalid and stops receiving events.

```bash
# Check webhook status
curl --request GET \
  --url 'https://api.x.com/2/webhooks' \
  --header 'Authorization: Bearer YOUR_BEARER_TOKEN'

# Re-validate if needed
curl --request PUT \
  --url 'https://api.x.com/2/webhooks/WEBHOOK_ID' \
  --header 'Authorization: Bearer YOUR_BEARER_TOKEN'
```

## Additional Resources

### Official X Documentation

- 🔗 [X Developer Portal](https://developer.x.com/) — Main developer hub
- 🔗 [X Developer Console](https://console.x.com/) — Manage apps and credentials
- 🔗 [Getting Access](https://docs.x.com/x-api/getting-started/getting-access) — Account and app setup
- 🔗 [V2 Webhooks API](https://docs.x.com/x-api/webhooks/introduction) — Webhook management
- 🔗 [Webhooks Quickstart](https://docs.x.com/x-api/webhooks/quickstart) — CRC setup and registration guide
- 🔗 [V2 Account Activity API](https://docs.x.com/x-api/account-activity/introduction) — Subscription management and event types
- 🔗 [Direct Messages API](https://docs.x.com/x-api/direct-messages/introduction) — DM endpoints reference
- 🔗 [OAuth 1.0a](https://docs.x.com/fundamentals/authentication/oauth-1-0a/api-key-and-secret) — API Key and Secret guide
- 🔗 [Rate Limits](https://docs.x.com/x-api/fundamentals/rate-limits) — Complete rate limit reference

### Tools

- 🔗 [Tweepy](https://docs.tweepy.org/) — Python SDK for the X API


### Helper Scripts (included in this project)

- `x-dm-connect-chat/test_x_credentials.py` — Verify credentials from Secrets Manager and get your numeric account ID
- `x-dm-connect-chat/subscribe_webhook.py` — Subscribe your account to the registered webhook

*This guide is based on X API documentation and Developer Console UI as of April 2026. Always refer to the [X Developer Documentation](https://docs.x.com/) for the most up-to-date information.*

