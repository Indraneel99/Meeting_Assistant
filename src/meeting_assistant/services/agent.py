from __future__ import annotations

import json
from dataclasses import dataclass

from meeting_assistant.db.models import WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import PlanResult, PlannedDecision, PlannedTask, ToolCall
from meeting_assistant.services.context import ContextBundle
from meeting_assistant.services.planner import Planner, PlannerHistoryEntry, PlannerRuntimeState
from meeting_assistant.services.tools import ToolExecutionOutcome, ToolExecutor, ToolValidator


def _task_key(task: PlannedTask) -> tuple[str, str]:
    return (task.assignee.strip().lower(), task.action.strip().lower())


def _decision_key(decision: PlannedDecision) -> tuple[str, str]:
    return (decision.topic.strip().lower(), decision.decision_text.strip().lower())


@dataclass(slots=True)
class AgentRunResult:
    status: str
    summary: str
    tasks: list[PlannedTask]
    decisions: list[PlannedDecision]
    tool_executions: list[dict[str, object]]
    iterations_used: int


@dataclass(slots=True)
class AgentRuntime:
    repository: Repository
    planner: Planner
    tool_validator: ToolValidator
    tool_executor: ToolExecutor
    max_iterations: int = 10

    def run(
        self,
        *,
        workflow_run_id: int,
        title: str,
        transcript_text: str,
        context: ContextBundle,
    ) -> AgentRunResult:
        return self._run_loop(
            workflow_run_id=workflow_run_id,
            title=title,
            transcript_text=transcript_text,
            context=context,
            start_iteration=1,
            history=[],
            summary="",
            task_map={},
            decision_map={},
            tool_execution_records=[],
            seen_signatures=set(),
        )

    def resume(
        self,
        *,
        workflow_run_id: int,
        title: str,
        transcript_text: str,
        context: ContextBundle,
    ) -> AgentRunResult:
        workflow_run = self.repository.get_workflow_run(workflow_run_id)
        if workflow_run is None:
            raise ValueError(f"Workflow run {workflow_run_id} not found")

        steps = self.repository.list_agent_steps(workflow_run_id)
        executions = self.repository.list_tool_executions(workflow_run_id)

        history = self._history_from_steps(steps)
        summary, task_map, decision_map = self._state_from_steps(steps)
        tool_execution_records = [self._execution_record(execution) for execution in executions]
        seen_signatures = {
            (execution.tool_name, execution.payload)
            for execution in executions
            if execution.status.value in {"executed", "approval_required", "skipped"}
        }

        return self._run_loop(
            workflow_run_id=workflow_run_id,
            title=title,
            transcript_text=transcript_text,
            context=context,
            start_iteration=workflow_run.iteration_count + 1,
            history=history,
            summary=summary,
            task_map=task_map,
            decision_map=decision_map,
            tool_execution_records=tool_execution_records,
            seen_signatures=seen_signatures,
        )

    def _run_loop(
        self,
        *,
        workflow_run_id: int,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        start_iteration: int,
        history: list[PlannerHistoryEntry],
        summary: str,
        task_map: dict[tuple[str, str], PlannedTask],
        decision_map: dict[tuple[str, str], PlannedDecision],
        tool_execution_records: list[dict[str, object]],
        seen_signatures: set[tuple[str, str]],
    ) -> AgentRunResult:
        final_status = WorkflowStatus.DONE.value
        iterations_used = max(0, start_iteration - 1)

        for iteration in range(start_iteration, self.max_iterations + 1):
            iterations_used = iteration
            runtime_state = PlannerRuntimeState(
                iteration=iteration,
                max_iterations=self.max_iterations,
                history=list(history),
            )
            plan = self.planner.plan(title, transcript_text, context, runtime_state)
            self._record_planner_step(workflow_run_id, iteration, plan)
            self.repository.update_workflow_iteration_count(workflow_run_id, iteration)

            summary = plan.summary or summary
            for task in plan.tasks:
                task_map[_task_key(task)] = task
            for decision in plan.decisions:
                decision_map[_decision_key(decision)] = decision

            validated_tool_calls = self.tool_validator.validate(plan.tool_calls, self.max_iterations)
            if not validated_tool_calls:
                history.append(
                    PlannerHistoryEntry(
                        iteration=iteration,
                        step_kind="planner",
                        status="complete",
                        detail="No further tool calls requested.",
                    )
                )
                final_status = WorkflowStatus.DONE.value
                break

            progress_made = False
            for tool_call in validated_tool_calls:
                payload_blob = json.dumps(tool_call.payload, sort_keys=True)
                signature = (tool_call.tool_name, payload_blob)
                if signature in seen_signatures:
                    continue

                outcome = self.tool_executor.execute(workflow_run_id, tool_call)
                seen_signatures.add(signature)
                progress_made = progress_made or not outcome.reused
                record = self._tool_record(tool_call.tool_name, outcome)
                if not outcome.reused:
                    tool_execution_records.append(record)
                self.repository.create_agent_step(
                    workflow_run_id=workflow_run_id,
                    iteration=iteration,
                    step_kind="tool",
                    status=outcome.status,
                    payload_json=json.dumps(
                        {"tool_name": tool_call.tool_name, "payload": tool_call.payload},
                        sort_keys=True,
                    ),
                    result_json=json.dumps(outcome.result, sort_keys=True),
                )
                history.append(
                    PlannerHistoryEntry(
                        iteration=iteration,
                        step_kind=tool_call.tool_name,
                        status=outcome.status,
                        detail=self._history_detail(outcome),
                    )
                )
                if outcome.status == "approval_required":
                    final_status = WorkflowStatus.AWAITING_APPROVAL.value
                    return AgentRunResult(
                        status=final_status,
                        summary=summary,
                        tasks=list(task_map.values()),
                        decisions=list(decision_map.values()),
                        tool_executions=tool_execution_records,
                        iterations_used=iterations_used,
                    )

            if not progress_made:
                history.append(
                    PlannerHistoryEntry(
                        iteration=iteration,
                        step_kind="planner",
                        status="loop_guard",
                        detail="No new progress made; stopping to avoid repeated calls.",
                    )
                )
                final_status = WorkflowStatus.DONE.value
                break
        else:
            final_status = WorkflowStatus.FAILED.value

        return AgentRunResult(
            status=final_status,
            summary=summary,
            tasks=list(task_map.values()),
            decisions=list(decision_map.values()),
            tool_executions=tool_execution_records,
            iterations_used=iterations_used,
        )

    def _history_from_steps(self, steps: list) -> list[PlannerHistoryEntry]:
        history: list[PlannerHistoryEntry] = []
        for step in steps:
            if step.step_kind == "tool":
                payload = json.loads(step.payload_json)
                tool_name = payload["tool_name"]
                history.append(
                    PlannerHistoryEntry(
                        iteration=step.iteration,
                        step_kind=tool_name,
                        status=step.status,
                        detail=self._history_detail_from_status(step.status),
                    )
                )
            elif step.status == "loop_guard":
                history.append(
                    PlannerHistoryEntry(
                        iteration=step.iteration,
                        step_kind="planner",
                        status=step.status,
                        detail="No new progress made; stopping to avoid repeated calls.",
                    )
                )
        return history

    def _state_from_steps(
        self,
        steps: list,
    ) -> tuple[str, dict[tuple[str, str], PlannedTask], dict[tuple[str, str], PlannedDecision]]:
        planner_steps = [step for step in steps if step.step_kind == "planner"]
        if not planner_steps:
            return "", {}, {}

        last_plan = PlanResult.model_validate_json(planner_steps[-1].result_json)
        task_map = {_task_key(task): task for task in last_plan.tasks}
        decision_map = {_decision_key(decision): decision for decision in last_plan.decisions}
        return last_plan.summary, task_map, decision_map

    def _execution_record(self, execution) -> dict[str, object]:
        return {
            "tool_name": execution.tool_name,
            "status": execution.status.value,
            "attempts": self.repository.count_tool_execution_attempts(execution.id),
            "idempotency_key": execution.idempotency_key,
            "result": json.loads(execution.result) if execution.result else None,
            "reused": True,
        }

    def _record_planner_step(self, workflow_run_id: int, iteration: int, plan: PlanResult) -> None:
        self.repository.create_agent_step(
            workflow_run_id=workflow_run_id,
            iteration=iteration,
            step_kind="planner",
            status="planned",
            payload_json=json.dumps({"iteration": iteration}, sort_keys=True),
            result_json=plan.model_dump_json(),
        )

    def _tool_record(self, tool_name: str, outcome: ToolExecutionOutcome) -> dict[str, object]:
        return {
            "tool_name": tool_name,
            "status": outcome.status,
            "attempts": outcome.attempts,
            "idempotency_key": outcome.idempotency_key,
            "result": outcome.result,
            "reused": outcome.reused,
        }

    def _history_detail(self, outcome: ToolExecutionOutcome) -> str:
        if outcome.status == "approval_required":
            return "Awaiting human approval."
        if outcome.status == "failed":
            return str(outcome.result.get("error", "Tool failed."))
        if outcome.status == "skipped":
            return str(outcome.result.get("message", "Tool skipped."))
        return str(outcome.result.get("message", "Tool executed."))

    def _history_detail_from_status(self, status: str) -> str:
        if status == "approval_required":
            return "Awaiting human approval."
        if status == "failed":
            return "Tool failed."
        if status == "skipped":
            return "Tool skipped after rejection."
        return "Tool executed."
