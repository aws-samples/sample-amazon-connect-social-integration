"""
Quick script to verify X API credentials stored in AWS Secrets Manager
and retrieve your numeric X account ID.

Usage:
    python test_x_credentials.py
"""
import json
import boto3
import tweepy

SECRET_NAME = "x-dm-credentials"


def get_credentials():
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(response["SecretString"])


def main():
    print("Retrieving credentials from Secrets Manager...")
    creds = get_credentials()

    required_keys = ["consumer_key", "consumer_secret", "access_token", "access_token_secret"]
    for key in required_keys:
        if not creds.get(key) or creds[key].startswith("YOUR_"):
            print(f"  ✗ {key} is missing or still a placeholder")
            return
        print(f"  ✓ {key} found")

    print("\nAuthenticating with X API...")
    client = tweepy.Client(
        consumer_key=creds["consumer_key"],
        consumer_secret=creds["consumer_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
    )

    me = client.get_me()
    print(f"\n  ID:       {me.data.id}")
    print(f"  Name:     {me.data.name}")
    print(f"  Username: @{me.data.username}")
    print(f"\nUse this as your x_account_id in /x/dm/config: {me.data.id}")


if __name__ == "__main__":
    main()
