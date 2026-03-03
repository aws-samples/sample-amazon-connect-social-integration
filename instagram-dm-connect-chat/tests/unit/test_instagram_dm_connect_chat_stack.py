import aws_cdk as core
import aws_cdk.assertions as assertions

from instagram_dm_connect_chat.instagram_dm_connect_chat_stack import InstagramDmConnectChatStack

# example tests. To run these tests, uncomment this file along with the example
# resource in instagram_dm_connect_chat/instagram_dm_connect_chat_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = InstagramDmConnectChatStack(app, "instagram-dm-connect-chat")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
