# Instagram Messaging Setup

> **Note:** This guide was built as a best effort to compile a working tutorial with the information available as of March 2026. Meta's platform, APIs, and processes may change at any time. Always check [Meta's official and up-to-date documentation](https://developers.facebook.com/docs/instagram-platform/) before proceeding.

## Overview

Step-by-step guide to set up Instagram Direct Messaging using Meta's **Instagram API with Instagram Login** 

## Prerequisites

- ✅ An **Instagram Business account** (not a Professional/Creator account — it must be a Business account specifically)
- ✅ A **Meta account linked to your Instagram Business account** (required to generate access tokens via Business Login)
- ✅ An HTTPS endpoint for webhooks

> **Important**: The Instagram API with Instagram Login requires a **Business account**, not a Professional (Creator) account. If your account is currently a Creator account, you must switch it to a Business account in Instagram Settings > Account type and tools > Switch to Business account. Additionally, your Instagram Business account must be linked to a Meta account. See [Business Login for Instagram](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login) for details.

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
   - **App Name**: Choose a descriptive name for your integration
   - **App Contact Email**: Your business email
   - **Business Account**: Select or create your Meta Business Account
5. Click **"Create App"**


**Reference**: [Create an App](https://developers.facebook.com/docs/development/create-an-app)


## Step 2: Add Instagram Product with Instagram Login

### 2.1 Add Instagram to Your App

1. In your App Dashboard, scroll to **"Add products to your app"**
2. Find **"Instagram"** and click **"Set Up"**
3. You'll see two API setup options, Click **"API setup with Instagram login"**

**Reference**: [Create an Instagram App](https://developers.facebook.com/docs/instagram-platform/create-an-instagram-app)

---

## Step 3: Link Your Instagram Business Account

### 3.1 Add Your Instagram Account for Testing

1. In the App Dashboard, go to **Instagram** > **API Setup with Instagram Login**
2. Scroll to **"Instagram accounts"** section
3. Click **"Add Instagram Account"**
**Important Requirements**:
- Account must be set to **Public** (at least during testing)
- Account must be an **Instagram Business account** (not a Creator/Professional account)
- Your Instagram Business account must be **linked to a Meta account** — this is required to generate access tokens via Business Login

**Reference**: [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)
- Account must be an **Instagram Business** or **Creator** account (Professional account)

**Reference**: [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login)


## Step 4: Configure Webhooks

### 4.1 Understanding Webhook Requests

Your endpoint must handle two types of requests:

#### A. Verification Requests (GET)

When you configure webhooks, Meta sends a GET request to verify your endpoint

#### B. Event Notifications (POST)

When a message is received, Meta sends a POST request with JSON payload

### 4.2 Configure Webhooks in App Dashboard

1. In your App Dashboard, go to **Instagram** > **API Setup with Instagram Login**
2. Scroll to the **"Webhooks"** section
3. Click **"Configure"**
4. Enter your webhook configuration:
   - **Callback URL**: `https://your-endpoint.com/webhook` 
   - **Verify Token**: Choose or create a secure string (e.g., `my_secure_verify_token_2026`)
   
   **Important**: This verify token is YOUR choice. Remember it - you'll use it in your webhook verification logic (Only known by you and meta)

5. Click **"Save"**

Meta will immediately send a GET request to verify your endpoint. If successful, you'll see a success message.

### 4.3 Subscribe to Webhook Fields

After successful verification, subscribe to messaging-related fields:

- ✅ **messages** - Receive incoming messages
- ✅ **messaging_postbacks** - Receive postback events (button clicks)
- ✅ **messaging_optins** - Receive opt-in events
- ✅ **message_reactions** - Receive message reactions (likes, hearts)
- ✅ **messaging_seen** - Receive read receipts
- ✅ **messaging_referrals** - Receive referral events

The new Instagram API with Instagram Login automatically subscribes you to all available webhooks by default.

**Reference**: 
- [Webhooks - Instagram Platform](https://developers.facebook.com/docs/instagram-platform/webhooks/)
- [Messenger Platform Webhooks](https://developers.facebook.com/docs/messenger-platform/webhooks)


## Step 5: Generate Instagram User Access Token

### 5.1 Understanding Access Tokens

For the **Instagram API with Instagram Login**, you need an **Instagram User Access Token** (not a Page Access Token).

### 5.2 Required Permissions

Your access token must have the following permissions (scopes):
### 5.3 Generate a Test Token from the App Dashboard

1. Go to [Meta Developer Portal](https://developers.facebook.com/) → select your app
2. In the left menu, navigate to **Instagram** > **API setup with Instagram business login**
3. Next to your Instagram account, click **"Generate token"**
4. Log in with your Instagram account and authorize the app
5. Copy the generated token

> **Note**: This generates a short-lived token for testing. For production use, implement the full [Business Login flow](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login) to obtain long-lived tokens.

> **Troubleshooting**: If you cannot generate a token, make sure your Instagram Business account has a Meta account linked. You can link it at [https://accountscenter.instagram.com/](https://accountscenter.instagram.com/) under **Accounts** > **Add account** > add your Meta account. This is a prerequisite for token generation via Business Login.


### 5.4 Test Your Access Token

Verify your token and get account info:

```bash
curl -X GET \
  "https://graph.instagram.com/me
    ?fields=id,username,account_type
    &access_token={YOUR_ACCESS_TOKEN}"
```

**Success Response**:
```json
{
  "id": "17841400008...",
  "username": "yourbusiness",
  "account_type": "BUSINESS"
}
```

**Reference**: 
- [Access Token - Instagram Platform](https://developers.facebook.com/docs/instagram-platform/reference/access_token/)
- [Get Started - Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started)


## Step 6: App Review and Publishing

### 6.1 Understanding Access Levels

- **Standard Access**: Works for accounts you own/manage or have added as testers. Limited functionality.
- **Advanced Access**: Required for production use with accounts you don't own. Full functionality.

**Reference**: [App Review - Instagram Platform](https://developers.facebook.com/docs/instagram-platform/app-review)


### 6.2 Testing in Development Mode

During development (Standard Access), your app can only interact with:
- Instagram accounts added as testers in your App Dashboard
- People who have roles on your app (Admin, Developer, Tester)

**To add testers**:
1. Go to **App Roles** > **Roles** in your App Dashboard
2. Add Instagram accounts as testers
3. Testers must accept the invitation



## Step 7: Sending Messages with Instagram API


### 7.1 Send a Text Message

```bash
curl -X POST \
  "https://graph.instagram.com/v23.0/{IG_USER_ID}/messages" \
  -H "Authorization: Bearer {ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": {
      "id": "{IGSID}"
    },
    "message": {
      "text": "Hello!"
    }
  }'
```

**Parameters**:
- `{IG_USER_ID}`: Your Instagram Business Account ID
- `{IGSID}`: Instagram-Scoped ID of the recipient (from webhook)
- `{ACCESS_TOKEN}`: Your Instagram User Access Token

**Success Response**:
```json
{
  "recipient_id": "1254477777772919",
  "message_id": "mid.1234567890"
}
```

### 7.2 Send an Image

```bash
curl -X POST \
  "https://graph.instagram.com/v23.0/{IG_USER_ID}/messages" \
  -H "Authorization: Bearer {ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": {
      "id": "{IGSID}"
    },
    "message": {
      "attachment": {
        "type": "image",
        "payload": {
          "url": "https://example.com/image.jpg"
        }
      }
    }
  }'
```

### 7.3 Send Quick Replies

```bash
curl -X POST \
  "https://graph.instagram.com/v21.0/{IG_USER_ID}/messages" \
  -H "Authorization: Bearer {ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": {
      "id": "{IGSID}"
    },
    "message": {
      "text": "How can we help you?",
      "quick_replies": [
        {
          "content_type": "text",
          "title": "Track Order",
          "payload": "TRACK_ORDER"
        },
        {
          "content_type": "text",
          "title": "Contact Support",
          "payload": "CONTACT_SUPPORT"
        }
      ]
    }
  }'
```

**Reference**: [Messaging - Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/)


## Important Considerations

### 24-Hour Messaging Window

Instagram Messaging has a **24-hour standard messaging window**:
- After a user sends a message, you have **24 hours** to respond
- Outside this window, you cannot send messages (unless using Human Agent tag)
- Each new user message reopens the 24-hour window

**Human Agent Tag**:
- Allows responses up to **7 days** after initial message
- Use when human agent needs more time to respond
- Must be explicitly tagged in API request

### Rate Limits

- **200 requests per hour** per Instagram User ID
- Monitor rate limit headers in API responses
- Implement exponential backoff for retries

### Supported Message Types

- ✅ Text messages
- ✅ Images (JPEG, PNG)
- ✅ Videos (MP4)
- ✅ Audio files
- ✅ Generic templates (carousels)
- ✅ Button templates
- ✅ Quick replies
- ✅ Reactions (heart, like)
- ✅ Ice breakers
- ❌ Stories (send via separate API)

## Additional Resources

### Official Meta Documentation

- 🔗 [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/) - Main documentation
- 🔗 [Instagram Messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/) - Messaging-specific guide
- 🔗 [Webhooks - Instagram Platform](https://developers.facebook.com/docs/instagram-platform/webhooks/) - Webhook setup
- 🔗 [Create an Instagram App](https://developers.facebook.com/docs/instagram-platform/create-an-instagram-app) - App creation guide
- 🔗 [Instagram Platform Overview](https://developers.facebook.com/docs/instagram-platform/overview/) - Architecture and concepts
- 🔗 [Blog: Introducing Instagram API with Instagram Login](https://developers.facebook.com/blog/post/2024/07/30/instagram-api-with-instagram-login/) - Official announcement

### Tools

- 🔗 [Graph API Explorer](https://developers.facebook.com/tools/explorer/) - Test API calls
- 🔗 [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) - Debug tokens



*This guide is based on Meta documentation for Instagram API with Instagram Login, introduced in July 2024. This approach does NOT require a Facebook Page. Always refer to the [Meta for Developers documentation](https://developers.facebook.com/docs/instagram-platform/) for the most up-to-date information.*
