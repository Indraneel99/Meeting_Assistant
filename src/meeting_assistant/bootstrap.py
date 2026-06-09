import httpx
from openai import OpenAI

from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.db.session import SessionLocal, initialize_database
from meeting_assistant.repositories import Repository
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.asr import BatchASRAdapter, LocalAudioSourceResolver, OpenAIHostedASRClient
from meeting_assistant.services.context import ContextLoader
from meeting_assistant.services.embeddings import build_embedding_index
from meeting_assistant.services.jobs import InProcessBatchJobQueue, SyncBatchJobQueue, build_batch_job_queue
from meeting_assistant.services.normalizer import TranscriptNormalizer
from meeting_assistant.services.orchestrator import BatchOrchestrator
from meeting_assistant.services.planner import HeuristicPlanner, OpenAIPlanner, PlannerRouter
from meeting_assistant.services.query import QueryService
from meeting_assistant.services.queue import build_transcript_queue
from meeting_assistant.services.tools import ToolExecutor, ToolValidator


def bootstrap_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    initialize_database()

    repository = Repository(SessionLocal)
    queue = build_transcript_queue(queue_provider=settings.queue_provider, redis_url=settings.redis_url)
    job_queue = build_batch_job_queue(
        batch_processing_mode=settings.batch_processing_mode,
        job_queue_provider=settings.job_queue_provider,
        redis_url=settings.redis_url,
    )
    embedding_index = build_embedding_index(settings)
    asr_http_client = httpx.Client(timeout=settings.asr_openai_timeout_seconds)
    source_resolver = LocalAudioSourceResolver(asr_http_client)
    hosted_asr = OpenAIHostedASRClient(
        api_key=settings.asr_openai_api_key,
        base_url=settings.asr_openai_base_url,
        model_name=settings.asr_openai_model,
        language=settings.asr_openai_language,
        chunking_strategy=settings.asr_openai_chunking_strategy,
        http_client=asr_http_client,
    )
    asr = BatchASRAdapter(source_resolver=source_resolver, hosted_client=hosted_asr)
    normalizer = TranscriptNormalizer(settings.chunk_size_words)
    heuristic_planner = HeuristicPlanner()
    if settings.llm_provider == "openai" and settings.llm_openai_api_key:
        llm_client = OpenAI(
            api_key=settings.llm_openai_api_key,
            base_url=settings.llm_openai_base_url,
            timeout=settings.llm_openai_timeout_seconds,
        )
        planner = PlannerRouter(
            primary=OpenAIPlanner(
                model_name=settings.llm_openai_model,
                client=llm_client,
            ),
            fallback=heuristic_planner if settings.llm_fallback_provider == "heuristic" else None,
        )
    else:
        planner = heuristic_planner
    context_loader = ContextLoader(repository, embedding_index)
    tool_validator = ToolValidator()
    tool_executor = ToolExecutor(
        repository,
        max_retries=settings.tool_execution_max_retries,
        backoff_seconds=settings.tool_execution_backoff_seconds,
    )
    agent_runtime = AgentRuntime(
        repository=repository,
        planner=planner,
        tool_validator=tool_validator,
        tool_executor=tool_executor,
        max_iterations=settings.max_tool_calls_per_session,
    )

    orchestrator = BatchOrchestrator(
        repository=repository,
        queue=queue,
        asr=asr,
        normalizer=normalizer,
        context_loader=context_loader,
        embedding_index=embedding_index,
        agent_runtime=agent_runtime,
        job_queue=job_queue,
        batch_processing_mode=settings.batch_processing_mode,
    )
    if isinstance(job_queue, (SyncBatchJobQueue, InProcessBatchJobQueue)):
        job_queue.bind(orchestrator.run_batch_workflow)

    query_service = QueryService(repository, embedding_index)

    return Container(
        settings=settings,
        repository=repository,
        agent_runtime=agent_runtime,
        orchestrator=orchestrator,
        query_service=query_service,
    )
