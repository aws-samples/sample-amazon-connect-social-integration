import os
import json
import logging
import boto3
from strands.models import BedrockModel
from strands import Agent
from botocore.config import Config
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

logger = logging.getLogger()


class SocialMediaPostAnalysis(BaseModel):
    """Social media post analysis result."""
    message: str = Field(description="Core reformulated message to be processed by the brand")
    requires_intervention: bool = Field(description="This post is a customer issue that requires customer contact or response")
    priority: int = Field(description="Priority from 1 to 5: 1=highest (bad experience like lost bag), 2=delayed flight, 5=Q&A response")
    recommended_action: str = Field(description="Recommended action to take for this post")


DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

DEFAULT_SYSTEM_PROMPT = """You are a social media customer service analyst for an airline brand. Your task is to analyze social media posts (Instagram, Twitter, Facebook, etc.) and determine the appropriate response strategy.

For each post, analyze the following:

1. MESSAGE REFORMULATION:
   - Extract the core message or concern from the post
   - Reformulate it in a clear, professional manner suitable for internal processing
   - Include relevant context (location, sentiment, specific issues mentioned)

2. INTERVENTION ASSESSMENT:
   - Determine if this requires direct customer contact or response
   - Consider: complaints, service issues, questions, safety concerns, lost items
   - Positive feedback or general comments may not require intervention

3. PRIORITY LEVEL (1-5):
   - Priority 1: Critical issues (lost baggage, safety concerns, severe service failures, stranded passengers)
   - Priority 2: Significant issues (flight delays, cancellations, booking problems, service complaints)
   - Priority 3: Moderate issues (minor service issues, general complaints, refund requests)
   - Priority 4: Low priority (general questions, feedback, suggestions)
   - Priority 5: Minimal priority (positive feedback, general comments, Q&A responses)

4. RECOMMENDED ACTION:
   - Provide specific, actionable recommendation
   - Examples: "Contact customer immediately via DM", "Escalate to baggage services", "Respond with flight status", "Monitor only", "Thank customer for positive feedback"

Analyze the post objectively and provide structured output that enables efficient customer service response."""


def get_ssm_parameter(parameter_name: str) -> Dict[str, Any]:
    """
    Retrieve and parse SSM parameter value.
    
    Args:
        parameter_name: Name of the SSM parameter
        
    Returns:
        Dict containing the parsed JSON configuration
    """
    if not parameter_name:
        raise ValueError("Parameter name cannot be empty")
    
    try:
        ssm_client = boto3.client('ssm')
        logger.info(f"Retrieving SSM parameter: {parameter_name}")
        
        response = ssm_client.get_parameter(
            Name=parameter_name,
            WithDecryption=True
        )
        
        parameter_value = response['Parameter']['Value']
        config = json.loads(parameter_value)
        logger.info(f"Successfully parsed SSM parameter: {parameter_name}")
        return config
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in SSM parameter {parameter_name}: {str(e)}")
        raise ValueError(f"SSM parameter contains invalid JSON: {str(e)}")
        
    except Exception as e:
        logger.error(f"Failed to retrieve SSM parameter {parameter_name}: {str(e)}")
        raise


class AgentService:
    def __init__(
        self,   
        model_id: str = DEFAULT_MODEL_ID,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT
    ):
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.model = BedrockModel(
            boto_client_config=DEFAULT_CONFIG, 
            model_id=self.model_id, 
            max_tokens=4096
        )
        self.agent = Agent(model=self.model, system_prompt=self.system_prompt)
        logger.info(f"AgentService initialized with model: {self.model_id}")

    def invoke(self, query: str) -> SocialMediaPostAnalysis:
        """
        Analyze a social media post and return structured analysis.
        
        Args:
            query: The social media post content to analyze
            
        Returns:
            SocialMediaPostAnalysis with message, intervention flag, priority, and action
        """
        logger.info("Invoking agent for social media post analysis")
        return self.agent.structured_output(SocialMediaPostAnalysis, query)


def create_agent_service_from_config() -> Optional[AgentService]:
    """
    Create AgentService instance from SSM configuration.
    
    Returns:
        AgentService instance if bedrock is enabled, None otherwise
    """
    try:
        param_name = os.environ.get('PROCESS_CONFIG_PARAM_NAME')
        if not param_name:
            logger.warning("PROCESS_CONFIG_PARAM_NAME not set, using default configuration")
            return AgentService()
        
        config = get_ssm_parameter(param_name)
        bedrock_config = config.get('bedrock_config', {})
        
        if not bedrock_config.get('enabled', False):
            logger.info("Bedrock is not enabled in configuration")
            return None
        
        model_id = bedrock_config.get('model_id', DEFAULT_MODEL_ID)
        prompt = bedrock_config.get('prompt', DEFAULT_SYSTEM_PROMPT)
        
        logger.info(f"Creating AgentService with config - Model: {model_id}")
        return AgentService(model_id=model_id, system_prompt=prompt)
        
    except Exception as e:
        logger.error(f"Failed to create AgentService from config: {str(e)}")
        logger.info("Falling back to default AgentService configuration")
        return AgentService()
    

