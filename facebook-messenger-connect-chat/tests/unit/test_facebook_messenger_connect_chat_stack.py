import aws_cdk as core
import aws_cdk.assertions as assertions

from facebook_messenger_connect_chat.facebook_messenger_connect_chat_stack import FacebookMessengerConnectChatStack

# example tests. To run these tests, uncomment this file along with the example
# resource in facebook_messenger_connect_chat/facebook_messenger_connect_chat_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = FacebookMessengerConnectChatStack(app, "facebook-messenger-connect-chat")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
