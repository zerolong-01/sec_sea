from __future__ import annotations

from fastapi import FastAPI, HTTPException, status

from .config import Settings
from .models import EvaluationUpdate, RunRequest, RunResponse, RunTrace
from .repository import (
    ArtifactNotFound,
    ArtifactValidationError,
    ExperimentRepository,
    RepositoryError,
    RunTraceStore,
)
from .service import (
    RunService,
    TraceableRunError,
    UnsupportedDefenseMode,
    build_provider,
)
from .shared_variables import KEYS, SchemaVersion


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    repository = ExperimentRepository(settings.data_dir)
    trace_store = RunTraceStore(settings.runs_dir)
    service = RunService(settings, repository, trace_store, build_provider(settings))

    app = FastAPI(
        title="LLM Defense Trade-off Lab API",
        version="0.2.0",
        description="RAG·이메일, D1/D2·적용 위치·평가·계측 실행 API",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            KEYS["STATUS"]: "ok",
            KEYS["SCHEMA_VERSION"]: SchemaVersion.EXECUTION,
            "model_provider": settings.model_provider,
        }

    @app.put("/api/v1/runs/{run_id}/evaluation", response_model=RunTrace)
    def put_evaluation(run_id: str, update: EvaluationUpdate) -> RunTrace:
        try:
            return service.update_evaluation(run_id, update)
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_EVALUATION", "message": str(exc)}) from exc

    @app.post(
        "/api/v1/runs",
        response_model=RunResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_run(request: RunRequest) -> RunResponse:
        try:
            trace = service.execute(request)
        except UnsupportedDefenseMode as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DEFENSE_MODE_NOT_IMPLEMENTED", "message": str(exc)},
            ) from exc
        except TraceableRunError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={
                    "code": exc.error_code,
                    "message": str(exc),
                    KEYS["RUN_ID"]: exc.trace.run_id,
                },
            ) from exc
        except ArtifactNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": str(exc)},
            ) from exc
        except (ArtifactValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INVALID_EXPERIMENT_INPUT", "message": str(exc)},
            ) from exc

        return RunResponse(
            run_id=trace.run_id,
            status=trace.status,
            trace=trace,
        )

    @app.get("/api/v1/runs/{run_id}", response_model=RunTrace)
    def get_run(run_id: str) -> RunTrace:
        try:
            return service.get_trace(run_id)
        except ArtifactNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "RUN_NOT_FOUND", "message": str(exc)},
            ) from exc
        except RepositoryError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "INVALID_TRACE", "message": str(exc)},
            ) from exc

    return app


app = create_app()
