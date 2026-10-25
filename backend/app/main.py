from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, status, Response
from fastapi.responses import JSONResponse

from .batch import BatchRunner
from .batch_analysis import aggregate, report_csv
from .batch_models import BatchFilters, BatchReport, BatchReview, BatchSummary
from .research_models import ResearchFilters, ResearchReport
from .research_reports import available_sources, research_report, research_csv

from .config import Settings
from .storage import ConcurrentWriterError
from .experiment_models import EXPERIMENT_ID_PATTERN, ExperimentReport, ExperimentSummary
from .experiment_reports import experiment_csv, experiment_report
from .experiments import ExperimentRunner
from .models import (RUN_ID_PATTERN, DetectorGoldUpdate, DetectorReport, DetectorReportRequest,
                     EvaluationUpdate, RunRequest, RunResponse, RunTrace)
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
from .shared_variables import BATCH_API_PATHS, RESEARCH_API_PATHS, KEYS, SchemaVersion

RunId = Annotated[str, Path(pattern=RUN_ID_PATTERN)]
ExperimentId = Annotated[str, Path(pattern=EXPERIMENT_ID_PATTERN)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    repository = ExperimentRepository(settings.data_dir)
    trace_store = RunTraceStore(settings.runs_dir)
    service = RunService(settings, repository, trace_store, build_provider(settings))

    app = FastAPI(
        title="LLM Defense Trade-off Lab API",
        version="0.4.0",
        description="RAG·이메일, D1/D2·적용 위치·평가·계측 실행 API",
    )

    # Batch execution stays in the local CLI. These read/review endpoints never
    # cause a paid model invocation, including report/export refreshes.
    batch_runner = BatchRunner(settings)
    experiment_runner = ExperimentRunner(settings.project_root, settings.runs_dir)

    @app.exception_handler(ConcurrentWriterError)
    async def concurrent_writer(_request, _exc):
        return JSONResponse(status_code=409, content={"detail": {"code": "CONCURRENT_WRITE"}})

    @app.exception_handler(ArtifactValidationError)
    async def invalid_trace(_request, _exc):
        # Never include raw validation input, private evidence or file contents
        # in an error response. The same rule applies to review/report routes.
        return JSONResponse(status_code=500, content={"detail": {"code": "INVALID_TRACE"}})

    def read_experiment(action):
        try:
            return action()
        except ArtifactNotFound as exc:
            raise HTTPException(404, detail={"code": "MODEL_EXPERIMENT_NOT_FOUND"}) from exc
        except (RepositoryError, ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_MODEL_EXPERIMENT"}) from exc

    @app.get("/api/v1/model-experiments", response_model=list[ExperimentSummary])
    def list_model_experiments():
        return read_experiment(experiment_runner.list)

    @app.get("/api/v1/model-experiments/{experiment_id}", response_model=ExperimentSummary)
    def get_model_experiment(experiment_id: ExperimentId):
        return read_experiment(lambda: experiment_runner.summary(experiment_id))

    @app.post("/api/v1/model-experiments/{experiment_id}/report", response_model=ExperimentReport)
    def get_model_experiment_report(experiment_id: ExperimentId, filters: BatchFilters):
        return read_experiment(lambda: experiment_report(settings.project_root, settings.runs_dir,
                                                        experiment_id, filters))

    @app.post("/api/v1/model-experiments/{experiment_id}/export.csv")
    def get_model_experiment_csv(experiment_id: ExperimentId, filters: BatchFilters):
        report = get_model_experiment_report(experiment_id, filters)
        return Response(experiment_csv(report), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="model-comparison.csv"',
                     "X-Report-SHA256": report.report_sha256, "X-Report-Version": report.report_version})

    @app.get(RESEARCH_API_PATHS["SOURCES"])
    def evaluation_sources(batch_id: str):
        try:
            result = available_sources(batch_id)
            if not result["research"]["available"]:
                batch_runner.store.get(batch_id)
            return result
        except ArtifactNotFound as exc:
            raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND"}) from exc
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_RESEARCH_EVIDENCE"}) from exc

    @app.post(RESEARCH_API_PATHS["REPORT"], response_model=ResearchReport)
    def get_research_report(batch_id: str, filters: ResearchFilters):
        try:
            return research_report(batch_id, filters)
        except ArtifactNotFound as exc:
            raise HTTPException(404, detail={"code": "RESEARCH_OVERLAY_NOT_FOUND"}) from exc
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_RESEARCH_EVIDENCE"}) from exc

    @app.post(RESEARCH_API_PATHS["CSV"])
    def get_research_csv(batch_id: str, filters: ResearchFilters):
        report = get_research_report(batch_id, filters)
        return Response(research_csv(report), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="research-metrics.csv"',
                                 "X-Report-SHA256": report.report_sha256,
                                 "X-Report-Version": report.report_version,
                                 "X-Evaluation-Source": report.evaluation_source})

    @app.get(BATCH_API_PATHS["LIST"], response_model=list[BatchSummary])
    def list_batches():
        try:
            return batch_runner.store.list()
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_BATCH_LIST"}) from exc

    @app.get(BATCH_API_PATHS["GET"], response_model=BatchSummary)
    def get_batch(batch_id: str):
        try:
            return batch_runner.store.summary(batch_runner.store.get(batch_id))
        except ArtifactNotFound as exc:
            raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND"}) from exc
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_BATCH"}) from exc

    @app.post(BATCH_API_PATHS["REPORT"], response_model=BatchReport)
    def batch_report(batch_id: str, filters: BatchFilters):
        try:
            return aggregate(settings.runs_dir, batch_id, filters)
        except ArtifactNotFound as exc:
            raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND"}) from exc
        except (ValueError, OSError, ArtifactValidationError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_BATCH_REPORT"}) from exc

    @app.post(BATCH_API_PATHS["CSV"])
    def batch_csv(batch_id: str, filters: BatchFilters):
        report = batch_report(batch_id, filters)
        return Response(report_csv(report), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="batch-metrics.csv"',
                                 "X-Report-SHA256": report.provenance["report_sha256"],
                                 "X-Report-Version": report.report_version,
                                 "X-Evaluation-Source": report.provenance["evaluation_source"]})

    @app.put(BATCH_API_PATHS["REVIEW"])
    def batch_review(batch_id: str, run_id: RunId, review: BatchReview):
        try:
            return batch_runner.review(batch_id, run_id, review)
        except ArtifactNotFound as exc:
            raise HTTPException(404, detail={"code": "BATCH_OR_RUN_NOT_FOUND"}) from exc
        except ConcurrentWriterError:
            raise
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "INVALID_BATCH_REVIEW"}) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            KEYS["STATUS"]: "ok",
            KEYS["SCHEMA_VERSION"]: SchemaVersion.EXECUTION,
            "model_provider": settings.model_provider,
        }

    @app.put("/api/v1/runs/{run_id}/detector-gold", response_model=RunTrace)
    def put_detector_gold(run_id: RunId, update: DetectorGoldUpdate) -> RunTrace:
        try:
            return service.update_detector_gold(run_id, update)
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": str(exc)}) from exc
        except ConcurrentWriterError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_DETECTOR_GOLD", "message": str(exc)}) from exc

    @app.post("/api/v1/detector-report", response_model=DetectorReport)
    def detector_report(request: DetectorReportRequest) -> DetectorReport:
        try:
            return service.detector_report(request.run_ids)
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": str(exc)}) from exc

    @app.put("/api/v1/runs/{run_id}/evaluation", response_model=RunTrace)
    def put_evaluation(run_id: RunId, update: EvaluationUpdate) -> RunTrace:
        try:
            return service.update_evaluation(run_id, update)
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": str(exc)}) from exc
        except ConcurrentWriterError:
            raise
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
    def get_run(run_id: RunId) -> RunTrace:
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
