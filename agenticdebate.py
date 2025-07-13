import streamlit as st
import asyncio
import sys
import time
import json
import requests
from semantic_kernel.agents import Agent, ChatCompletionAgent, GroupChatOrchestration, RoundRobinGroupChatManager,ConcurrentOrchestration
from semantic_kernel.agents.orchestration.group_chat import BooleanResult, GroupChatManager, MessageResult, StringResult
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.functions import kernel_function
from typing import Dict, Any, Union
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent
from semantic_kernel.functions import KernelArguments
from semantic_kernel.kernel import Kernel
from semantic_kernel.prompt_template import KernelPromptTemplate, PromptTemplateConfig

if sys.version_info >= (3, 12):
    from typing import override  # pragma: no cover
else:
    from typing_extensions import override  # pragma: no cover

       

# --- AGENT SETUP (same as your original code) ---
def get_agents(deployment_name, api_key, endpoint) -> list[Agent]:
    azure_service = AzureChatCompletion(
        deployment_name=deployment_name,
        api_key=api_key,
        endpoint=endpoint,
    )
    
    projectmanager = ChatCompletionAgent(
        name="ProjectManager",
        description="Oversees the entire project lifecycle, ensuring alignment with timelines, scope, and stakeholder expectations.",
        instructions=(
           "Prioritize project delivery, risk management, and stakeholder communication."
           "Evaluate feasibility, resource allocation, and dependencies."
           "Ask clarifying questions to ensure alignment across all agents."
           "Summarize progress and flag potential blockers."
           "Reference inputs from all agents to maintain a holistic view."

        ),
        service=azure_service,
        
    )
    
    
    saphanaconsultant = ChatCompletionAgent(
        name="SAPS4HANAConsultant",
        description="Provides deep expertise in SAP S/4HANA modules, configurations, and best practices for implementation.",
        instructions=(
            "Focus on SAP-specific capabilities, limitations, and integration points "
            "Recommend relevant SAP modules and configurations based on business needs. "
            "Validate technical feasibility of proposed solutions from other agents. "
            "Ensure compliance with SAP standards and upgrade paths."
            "Build on the Business Analyst’s requirements and Solution Architect’s design."
            
        ),
        service=azure_service,
    )
    solutionarchitect = ChatCompletionAgent(
        name="SolutionArchitect",
        description="Designs the end-to-end technical solution, ensuring scalability, integration, and alignment with enterprise architecture.",
        instructions=(
            "Translate business requirements into technical architecture. "
            "Evaluate integration points between SAP and other systems."
            "Collaborate with the SAP Consultant to ensure architectural compatibility. "
            "Consider security, performance, and maintainability."
            "Respond to the Project Manager’s concerns about feasibility and risk."
            
        ),
        service=azure_service,
    )
    businessanalyst = ChatCompletionAgent(
        name="BusinessAnalyst",
        description="Gathers, analyzes, and documents business requirements, ensuring alignment with business goals.",
        instructions=(
            "Elicit detailed requirements from a business perspective. "
            "Translate business needs into functional specifications."
            "Validate assumptions with the Finance Manager and IT Leader."
            "Provide context and justification for each requirement."
            "Ensure traceability between business goals and technical solutions."
            
        ),
        service=azure_service,
    )
    financemanager = ChatCompletionAgent(
        name="FinanceManager",
        description="Ensures financial viability, budget alignment, and compliance with financial regulations.",
        instructions=(
            "Evaluate cost implications of proposed solutions. "
            "Ensure ROI, TCO, and budget adherence."
            "Raise concerns about financial risk or inefficiencies."
            "Collaborate with the Business Analyst to validate financial assumptions."
            "Provide input on financial reporting and compliance needs."
            
        ),
        service=azure_service,
    )
    itstrategicleader = ChatCompletionAgent(
        name="ITStrategicLeader",
        description="Ensures financial viability, budget alignment, and compliance with financial regulations.",
        instructions=(
            "Ensure alignment with enterprise IT strategy and digital transformation goals. "
            "Evaluate long-term scalability, vendor lock-in, and innovation potential"
            "Challenge short-term decisions that may conflict with strategic goals."
            "Collaborate with the Solution Architect and Project Manager to ensure sustainability."
            "Reference industry trends and benchmarks to support recommendations."
            
        ),
        service=azure_service,
    )
    
    return [
        projectmanager,
        saphanaconsultant,
        solutionarchitect,
        businessanalyst,
        financemanager,
        itstrategicleader,
    ]
    
    
class ChatCompletionGroupChatManager(GroupChatManager):
    """A simple chat completion base group chat manager.

    This chat completion service requires a model that supports structured output.
    """

    service: ChatCompletionClientBase

    topic: str

    termination_prompt: str = (
        "You are mediator that guides a discussion on the topic of '{{$topic}}'. "
        "You must ensure that multiple participants are involved in the discussion. "
        "You need to determine if the discussion has reached a conclusion. "
        "Ensure that all participants have had a chance to speak. "
        "Here are the names and descriptions of the participants: "
        "{{$participants}}\n"
        "If you would like to end the discussion, please respond with True. Otherwise, respond with False."
    )

    selection_prompt: str = (
        "You are mediator that guides a discussion on the topic of '{{$topic}}'. "
        "You need to select the next participant to speak. "
        "Please ensure all agents have had a chance to speak "
        "Here are the names and descriptions of the participants: "
        "{{$participants}}\n"
        "Please respond with only the name of the participant you would like to select."
    )

    result_filter_prompt: str = (
        "You are mediator that guides a discussion on the topic of '{{$topic}}'. "
        "You have just concluded the discussion. "
        "Please summarize the discussion and provide a closing statement."
    )

    def __init__(self, topic: str, service: ChatCompletionClientBase, **kwargs) -> None:
        """Initialize the group chat manager."""
        super().__init__(topic=topic, service=service, **kwargs)

    async def _render_prompt(self, prompt: str, arguments: KernelArguments) -> str:
        """Helper to render a prompt with arguments."""
        prompt_template_config = PromptTemplateConfig(template=prompt)
        prompt_template = KernelPromptTemplate(prompt_template_config=prompt_template_config)
        return await prompt_template.render(Kernel(), arguments=arguments)

    @override
    async def should_request_user_input(self, chat_history: ChatHistory) -> BooleanResult:
        """Provide concrete implementation for determining if user input is needed.

        The manager will check if input from human is needed after each agent message.
        """
        return BooleanResult(
            result=False,
            reason="This group chat manager does not require user input.",
        )

    @override
    async def should_terminate(self, chat_history: ChatHistory) -> BooleanResult:
        """Provide concrete implementation for determining if the discussion should end.

        The manager will check if the conversation should be terminated after each agent message
        or human input (if applicable).
        """
        should_terminate = await super().should_terminate(chat_history)
        if should_terminate.result:
            return should_terminate

        chat_history.messages.insert(
            0,
            ChatMessageContent(
                role=AuthorRole.SYSTEM,
                content=await self._render_prompt(
                    self.termination_prompt,
                    KernelArguments(topic=self.topic),
                ),
            ),
        )
        chat_history.add_message(
            ChatMessageContent(role=AuthorRole.USER, content="Determine if the discussion should end."),
        )

        response = await self.service.get_chat_message_content(
            chat_history,
            settings=PromptExecutionSettings(response_format=BooleanResult),
        )

        termination_with_reason = BooleanResult.model_validate_json(response.content)

        print("*********************")
        print(f"Should terminate: {termination_with_reason.result}\nReason: {termination_with_reason.reason}.")
        print("*********************")

        return termination_with_reason

    @override
    async def select_next_agent(
        self,
        chat_history: ChatHistory,
        participant_descriptions: dict[str, str],
    ) -> StringResult:
        """Provide concrete implementation for selecting the next agent to speak.

        The manager will select the next agent to speak after each agent message
        or human input (if applicable) if the conversation is not terminated.
        """
        chat_history.messages.insert(
            0,
            ChatMessageContent(
                role=AuthorRole.SYSTEM,
                content=await self._render_prompt(
                    self.selection_prompt,
                    KernelArguments(
                        topic=self.topic,
                        participants="\n".join([f"{k}: {v}" for k, v in participant_descriptions.items()]),
                    ),
                ),
            ),
        )
        chat_history.add_message(
            ChatMessageContent(role=AuthorRole.USER, content="Now select the next participant to speak."),
        )

        response = await self.service.get_chat_message_content(
            chat_history,
            settings=PromptExecutionSettings(response_format=StringResult),
        )

        participant_name_with_reason = StringResult.model_validate_json(response.content)

        print("*********************")
        print(
            f"Next participant: {participant_name_with_reason.result}\nReason: {participant_name_with_reason.reason}."
        )
        print("*********************")

        if participant_name_with_reason.result in participant_descriptions:
            return participant_name_with_reason

        raise RuntimeError(f"Unknown participant selected: {response.content}.")

    @override
    async def filter_results(
        self,
        chat_history: ChatHistory,
    ) -> MessageResult:
        """Provide concrete implementation for filtering the results of the discussion.

        The manager will filter the results of the conversation after the conversation is terminated.
        """
        if not chat_history.messages:
            raise RuntimeError("No messages in the chat history.")

        chat_history.messages.insert(
            0,
            ChatMessageContent(
                role=AuthorRole.SYSTEM,
                content=await self._render_prompt(
                    self.result_filter_prompt,
                    KernelArguments(topic=self.topic),
                ),
            ),
        )
        chat_history.add_message(
            ChatMessageContent(role=AuthorRole.USER, content="Please summarize the discussion."),
        )

        response = await self.service.get_chat_message_content(
            chat_history,
            settings=PromptExecutionSettings(response_format=StringResult),
        )
        string_with_reason = StringResult.model_validate_json(response.content)

        return MessageResult(
            result=ChatMessageContent(role=AuthorRole.ASSISTANT, content=string_with_reason.result),
            reason=string_with_reason.reason,
        )
    

# --- STREAMLIT UI ---


# Azure OpenAI configuration inputs
with st.sidebar:
    deployment_name = st.text_input("Azure Deployment Name", value="Azure AI deployment name")
    api_key = st.text_input("Azure API Key", type="password", value="")
    endpoint = st.text_input("Azure Endpoint", value="Endpoint URL")

st.title("Strategic Discussion with Multiple Agents")
st.write("This demo runs a group chat between agents to iteratively refine the output for a task")

# User input for the task
task = st.text_area("Enter your task for the group:", "We are going to make SAP MDG as our global master data hub. What is your view with respect to onboarding SAP Master Data Integration?")

# Button to run the orchestration
if st.button("Run the analysis"):
    conversation = []
    conversation_placeholder = st.empty()  # For streaming conversation

    def agent_response_callback(message: ChatMessageContent):
        # Animate the message word by word
        display_message = f"**{message.name}**: "
        words = message.content.split()
        animated = display_message
        for word in words:
            animated += word + " "
            conversation_placeholder.markdown("\n\n".join(conversation + [animated]))
            time.sleep(0.01)  # Adjust speed as desired
        # Add the full message to the conversation history
        conversation.append(f"**{message.name}**: {message.content}")
        conversation_placeholder.markdown("\n\n".join(conversation))

    async def run_orchestration():
        agents = get_agents(deployment_name, api_key, endpoint)
        # group_chat_orchestration = GroupChatOrchestration(
        #     members=agents,
        #     manager=RoundRobinGroupChatManager(max_rounds=6),
        #     agent_response_callback=agent_response_callback,
        # )
        azure_service = AzureChatCompletion(
        deployment_name=deployment_name,
        api_key=api_key,
        endpoint=endpoint,
        )
        group_chat_orchestration = GroupChatOrchestration(
        members=agents,
        manager=ChatCompletionGroupChatManager(
            topic=task,
            service=azure_service,
            max_rounds=15,
        ),
        agent_response_callback=agent_response_callback,
        )
        #concurrent_orchestration = ConcurrentOrchestration(members=agents,agent_response_callback=agent_response_callback)
        runtime = InProcessRuntime()
        runtime.start()
        orchestration_result = await group_chat_orchestration.invoke(
            task=task,
            runtime=runtime,
        )
        value = await orchestration_result.get()
        await runtime.stop_when_idle()
        return value

    # Run the async orchestration
    result = asyncio.run(run_orchestration())

    # Final conversation display (in case any last message was missed)
    conversation_placeholder.markdown("\n\n".join(conversation))

    st.subheader("Final Result")
    st.success(result)
