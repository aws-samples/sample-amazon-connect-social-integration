"""
Subscribe the business X account to the registered webhook for Account Activity events.

Pulls credentials from Secrets Manager, fetches the webhook ID from X API,
and creates the subscription.

Usage:
    python subscribe_webhook.py
"""
import json
import boto3
import requests
from requests_oauthlib import OAuth1

SECRET_NAME = "x-dm-credentials"  # nosec B105 — not a password, this is a Secrets Manager key name


def get_credentials():
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(response["SecretString"])


def get_bearer_token(creds):
    """Derive a Bearer Token using OAuth 2.0 Client Credentials (app-only)."""
    resp = requests.post(
        "https://api.x.com/oauth2/token",
        auth=(creds["consumer_key"], creds["consumer_secret"]),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_webhook_id(bearer_token):
    """List registered webhooks and return the first webhook ID."""
    resp = requests.get(
        "https://api.x.com/2/webhooks",
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        print("No webhooks registered. Register one first (see x_setup.md Step 5).")
        return None
    webhook = data[0]
    print(f"  Webhook ID:  {webhook['id']}")
    print(f"  URL:         {webhook['url']}")
    print(f"  Valid:       {webhook['valid']}")
    return webhook["id"]


def subscribe(creds, webhook_id):
    """Subscribe the authenticated user to the webhook."""
    oauth = OAuth1(
        creds["consumer_key"],
        creds["consumer_secret"],
        creds["access_token"],
        creds["access_token_secret"],
    )
    url = f"https://api.x.com/2/account_activity/webhooks/{webhook_id}/subscriptions/all"
    resp = requests.post(url, auth=oauth, timeout=30)
    resp.raise_for_status()
    return resp


def main():
    print("Retrieving credentials from Secrets Manager...")
    creds = get_credentials()

    print("Getting Bearer Token...")
    bearer_token = get_bearer_token(creds)

    print("Looking up registered webhooks...")
    webhook_id = get_webhook_id(bearer_token)
    if not webhook_id:
        return

    print(f"\nSubscribing to webhook {webhook_id}...")
    try:
        resp = subscribe(creds, webhook_id)
        if resp.status_code in (200, 204):
            print("  ✓ Subscription created successfully")
            if resp.text:
                print(f"    {resp.text}")
        elif resp.status_code == 409:
            print("  ✓ Already subscribed")
    except requests.exceptions.HTTPError as e:
        resp = e.response
        if resp is not None and resp.status_code == 409:
            print("  ✓ Already subscribed")
        else:
            print(f"  ✗ Failed — HTTP {resp.status_code if resp is not None else 'unknown'}")
            print(f"    {resp.text if resp is not None else str(e)}")


if __name__ == "__main__":
    main()
