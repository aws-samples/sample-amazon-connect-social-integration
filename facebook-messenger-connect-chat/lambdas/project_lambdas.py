from aws_cdk import Duration, aws_lambda
from constructs import Construct

LAMBDA_TIMEOUT = 30

BASE_LAMBDA_CONFIG = dict(
    timeout=Duration.seconds(LAMBDA_TIMEOUT),
    memory_size=128,
    runtime=aws_lambda.Runtime.PYTHON_3_14,
    tracing=aws_lambda.Tracing.ACTIVE,
)


class Lambdas(Construct):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.messages_in = aws_lambda.Function(
            self,
            "MsgIN",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/messages_in"),
            **BASE_LAMBDA_CONFIG  # type: ignore
        )

        self.messages_out = aws_lambda.Function(
            self,
            "MsgOut",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/messages_out"),
            **BASE_LAMBDA_CONFIG  # type: ignore
        )
