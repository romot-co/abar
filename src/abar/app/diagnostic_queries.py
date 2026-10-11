"""Observational diagnosis views; never expose a sealed A/B assignment."""

from dataclasses import asdict
from typing import cast

from abar.app.repository import WorkspaceRepository
from abar.app.state import ABARState
from abar.app.views import EntityView, FlagView, SymptomSummaryView
from abar.foundation.json_types import JSONValue


def symptom_summaries(state: ABARState) -> tuple[SymptomSummaryView, ...]:
    return tuple(
        SymptomSummaryView(
            id=symptom.id,
            title=symptom.title,
            status=symptom.status,
            listen_count=sum(
                session.symptom_id == symptom.id
                and state.compare.session_runtime[session.core_session_id].status == "ended"
                for session in state.research.project_sessions.values()
            ),
        )
        for symptom in state.research.symptoms.values()
    )


def current_best_flags(state: ABARState) -> tuple[FlagView, ...]:
    return tuple(
        FlagView(
            symptom_id=flag.symptom_id,
            title=state.research.symptoms[flag.symptom_id].title,
            session_id=flag.session_id,
            reason=flag.reason,
            variant_id=flag.variant_id,
        )
        for flag in state.research.current_best_flags
    )


def symptom_view(repository: WorkspaceRepository, symptom_id: str) -> EntityView:
    symptom = repository.state().research.symptoms[symptom_id]
    return EntityView(entity_id=symptom_id, kind="symptom", document=asdict(symptom))


def symptom_list(repository: WorkspaceRepository) -> EntityView:
    return EntityView(
        entity_id="symptoms",
        kind="symptom_list",
        document={
            "symptoms": [
                item.model_dump(mode="json") for item in symptom_summaries(repository.state())
            ]
        },
    )


def verification_documents(state: ABARState) -> dict[str, dict[str, JSONValue]]:
    return {
        key: cast(dict[str, JSONValue], report.model_dump(mode="json"))
        for key, report in state.research.verifications.items()
    }
