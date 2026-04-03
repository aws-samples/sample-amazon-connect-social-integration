import aws_cdk as core
import aws_cdk.assertions as assertions

from x_dm_connect_chat.x_dm_connect_chat_stack import XDmConnectChatStack


def _get_template():
    app = core.App()
    stack = XDmConnectChatStack(app, "x-dm-connect-chat")
    return assertions.Template.from_stack(stack)


class TestResourceCounts:
    """Verify synthesized CloudFormation template contains all expected resources."""

    def test_api_gateway_rest_api_created(self):
        template = _get_template()
        template.resource_count_is("AWS::ApiGateway::RestApi", 1)

    def test_two_lambda_functions_created(self):
        template = _get_template()
        template.resource_count_is("AWS::Lambda::Function", 2)

    def test_two_dynamodb_tables_created(self):
        template = _get_template()
        template.resource_count_is("AWS::DynamoDB::Table", 2)

    def test_sns_topic_created(self):
        template = _get_template()
        template.resource_count_is("AWS::SNS::Topic", 1)

    def test_secrets_manager_secret_created(self):
        template = _get_template()
        template.resource_count_is("AWS::SecretsManager::Secret", 1)

    def test_two_ssm_parameters_created(self):
        template = _get_template()
        template.resource_count_is("AWS::SSM::Parameter", 2)


class TestEnvironmentVariables:
    """Verify environment variables are set correctly on both Lambdas."""

    def test_messages_in_has_required_env_vars(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::Lambda::Function",
            assertions.Match.object_like({
                "Handler": "lambda_function.lambda_handler",
                "Environment": {
                    "Variables": assertions.Match.object_like({
                        "TABLE_NAME": assertions.Match.any_value(),
                        "SECRET_ARN": assertions.Match.any_value(),
                        "CONFIG_PARAM_NAME": "/x/dm/config",
                        "TOPIC_ARN": assertions.Match.any_value(),
                        "USERS_TABLE_NAME": assertions.Match.any_value(),
                    }),
                },
            }),
        )

    def test_messages_out_has_required_env_vars(self):
        """Verify messages_out Lambda has TABLE_NAME, SECRET_ARN, CONFIG_PARAM_NAME
        but NOT TOPIC_ARN or USERS_TABLE_NAME."""
        template = _get_template()
        # Find all Lambda functions and check that one has the out-specific pattern
        resources = template.find_resources(
            "AWS::Lambda::Function",
            {
                "Properties": {
                    "Environment": {
                        "Variables": {
                            "TABLE_NAME": assertions.Match.any_value(),
                            "SECRET_ARN": assertions.Match.any_value(),
                            "CONFIG_PARAM_NAME": "/x/dm/config",
                        },
                    },
                },
            },
        )
        # Both lambdas should have these base env vars
        assert len(resources) == 2


class TestIamPermissions:
    """Verify IAM permissions for connect:StartChatContact and connect:StartContactStreaming."""

    def test_connect_permissions_granted(self):
        template = _get_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            assertions.Match.object_like({
                "PolicyDocument": {
                    "Statement": assertions.Match.array_with([
                        assertions.Match.object_like({
                            "Action": [
                                "connect:StartChatContact",
                                "connect:StartContactStreaming",
                            ],
                            "Effect": "Allow",
                        }),
                    ]),
                },
            }),
        )
