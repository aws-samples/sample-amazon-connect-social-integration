# Social Media Integration with Amazon Connect - Use Cases & Code Samples

This repository provides code samples and patterns for integrating social media messaging platforms with Amazon Connect Chat. Each use case demonstrates common integration patterns with complete implementations using AWS CDK.

## Use Cases

| Use Case | Description | Type |
|----------|-------------|------|
| **[Facebook Messenger Integration](./facebook-messenger-connect-chat/README.md)** | Bidirectional messaging between Facebook Messenger and Amazon Connect Chat. Handles inbound customer messages and outbound agent responses with session management and attachment support. | CDK Python |
| **[Instagram DM Integration](./instagram-dm-connect-chat/README.md)** | Bidirectional messaging between Instagram Direct Messages and Amazon Connect Chat. Handles inbound customer messages and outbound agent responses with session management and attachment support. | CDK Python |
| **[X (Twitter) DM Integration](./x-dm-connect-chat/README.md)** | Bidirectional messaging between X (Twitter) Direct Messages and Amazon Connect Chat. Handles inbound customer DMs and outbound agent responses with session management and attachment support. | CDK Python |


## General Deployment Instructions

If you want to deploy any of these use cases, unless stated otherwise, follow this [General Guide](general_cdk_deploy.md) to deploy using CDK.

## General Prerequisites

If you want to test these use cases, unless stated otherwise, follow this guide: [General Prerequisites for Amazon Connect](general_connect.md)

## Platform Setup Guides

- [Facebook Setup Guide](facebook_setup.md)
- [Instagram Setup Guide](instagram_setup.md)
- [X (Twitter) Setup Guide](x_setup.md)

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

## Contributing

Please refer to the [CONTRIBUTING](CONTRIBUTING.md) document for further details on contributing to this repository.
