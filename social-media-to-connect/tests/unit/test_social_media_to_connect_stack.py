import aws_cdk as core
import aws_cdk.assertions as assertions

from social_media_to_connect.social_media_to_connect_stack import SocialMediaToConnectStack

# example tests. To run these tests, uncomment this file along with the example
# resource in social_media_to_connect/social_media_to_connect_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = SocialMediaToConnectStack(app, "social-media-to-connect")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
