"""Relatório operacional da inicialização, sem impressão de traceback."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Callable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from websensors_flow_rag.config import RAGSettings
from websensors_flow_rag.healthchecks import CheckResult, HealthChecker, HealthReport


@contextmanager
def _mute_probe_logs():
    """Evita duplicar eventos HTTP enquanto o relatório visual está ativo."""
    names = ("websensors_flow_rag.startup", "httpx")
    loggers = [logging.getLogger(name) for name in names]
    previous = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.CRITICAL)
        yield
    finally:
        for logger, level in zip(loggers, previous):
            logger.setLevel(level)


def _recommendations(check: CheckResult, settings: RAGSettings) -> list[str]:
    name = check.name
    detail = check.detail.lower()
    if name == "elasticsearch":
        url = settings.services.elasticsearch.endpoint.rstrip("/")
        if "red" in detail:
            return [
                "Cluster em estado red. Identifique shards primários não atribuídos antes de iniciar a API.",
                f"curl -s '{url}/_cluster/health?pretty'",
                f"curl -s '{url}/_cat/shards?v'",
                f"curl -s -X POST '{url}/_cluster/allocation/explain?pretty' -H 'Content-Type: application/json' -d '{{}}'",
            ]
        if "401" in detail or "403" in detail:
            return ["Verifique services.elasticsearch.username, password ou api_key e suas permissões no cluster."]
        return [f"Verifique a conectividade e os logs do Elasticsearch em {url}."]
    if name == "minio":
        if any(word in detail for word in ("invalidaccesskeyid", "signaturedoesnotmatch", "accessdenied")):
            return [
                "Credenciais do MinIO inválidas ou sem permissão. Confira services.minio.access_key e secret_key no YAML.",
                "Confira se services.minio.endpoint aponta para a instância MinIO esperada.",
            ]
        if "bucket" in detail:
            return ["Confira os buckets Bronze e Silver e as permissões para consultar seus nomes."]
        return ["Confira services.minio.endpoint e a conectividade com o servidor MinIO."]
    if name == "docling":
        url = settings.services.docling.endpoint.rstrip("/")
        return [f"Verifique {url}/health e {url}/ready."]
    if name == "embeddings":
        return ["Verifique o endpoint, o modelo e a dimensionalidade em services.embeddings no YAML."]
    if name == "mlflow":
        return ["Verifique observability.mlflow.tracking_uri e a permissão de gravação no experimento."]
    if name == "graylog":
        return ["Verifique observability.graylog.host, port e o protocolo configurado no servidor."]
    return ["Verifique os dados do serviço no YAML e seus logs."]


def render_health_report(report: HealthReport, settings: RAGSettings, *, console: Console | None = None) -> None:
    output = console or Console()
    enabled = [check for check in report.checks if check.enabled]
    ok_count = sum(check.ok for check in enabled)
    failures = [check for check in enabled if not check.ok]
    disabled = sum(not check.enabled for check in report.checks)

    labels = {
        "elasticsearch": "Elasticsearch",
        "minio": "MinIO",
        "docling": "Docling",
        "embeddings": "Embeddings",
        "mlflow": "MLflow",
        "graylog": "Graylog",
    }

    def short_description(check: CheckResult) -> str:
        if not check.enabled:
            return ""
        low = check.detail.lower()
        if not check.ok and check.name == "elasticsearch" and "red" in low:
            return "Cluster red"
        if not check.ok and check.name == "minio" and "invalidaccesskeyid" in low:
            return "Credencial inválida"
        return check.detail.removeprefix("RuntimeError ")[:65]

    table = Table(
        title="Diagnóstico de infraestrutura",
        title_style="bold cyan",
        box=box.ROUNDED,
        show_lines=True,
        expand=True,
    )
    table.add_column("Serviço", style="bold", min_width=14, no_wrap=True)
    table.add_column("Estado", justify="center", min_width=9, no_wrap=True)
    table.add_column("Tempo", justify="right", no_wrap=True)
    table.add_column("Tent.", justify="center", no_wrap=True)
    table.add_column("Resultado", overflow="fold")
    for check in report.checks:
        if not check.enabled:
            state = Text("DESATIVADO", style="dim")
        elif check.ok:
            state = Text("OK", style="bold green")
        else:
            state = Text("FALHOU", style="bold red")
        table.add_row(
            labels.get(check.name, check.name),
            state,
            f"{check.duration_seconds:.2f}s" if check.enabled else "",
            str(check.attempts) if check.enabled else "",
            short_description(check),
        )
    output.print()
    output.print(table)

    if failures:
        message = (
            f"[bold red]INICIALIZAÇÃO INTERROMPIDA[/bold red]\n"
            f"Disponíveis {ok_count}/{len(enabled)}    Falhas {len(failures)}    "
            f"Desativados {disabled}    Duração {report.duration_seconds:.2f}s\n"
            "Os índices não serão modificados e a API não será iniciada."
        )
        output.print(Panel(message, border_style="red", title="Resumo", expand=True))
        for check in failures:
            guidance = "\n".join(f"{i}. {tip}" for i, tip in enumerate(_recommendations(check, settings), 1))
            output.print(Panel(
                f"[bold]Motivo[/bold]  {check.detail}\n\n{guidance}",
                title=f"Ação recomendada  {labels.get(check.name, check.name)}",
                border_style="yellow", expand=True,
            ))
        output.print("[dim]Após as correções, execute websensors-flow-rag-health com o mesmo YAML.[/dim]")
    else:
        message = (
            f"[bold green]INFRAESTRUTURA DISPONÍVEL[/bold green]\n"
            f"Disponíveis {ok_count}/{len(enabled)}    Desativados {disabled}    "
            f"Duração {report.duration_seconds:.2f}s    ETA 0s"
        )
        output.print(Panel(message, border_style="green", title="Resumo", expand=True))


def run_health_preflight(
    settings: RAGSettings,
    *,
    console: Console | None = None,
    checker_factory: Callable[[RAGSettings], HealthChecker] = HealthChecker,
) -> HealthReport:
    """Verifica serviços, exibe progresso/ETA e apresenta relatório resumido."""
    output = console or Console()
    output.print(Panel(
        f"[bold]WebSensors Flow RAG[/bold]\n"
        f"Ambiente  {settings.environment.name}\n"
        f"Configuração  {settings.project.name}",
        title="Verificação de inicialização",
        border_style="cyan",
    ))
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.fields[service]}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
        console=output,
        transient=True,
        disable=not output.is_terminal,
    ) as progress:
        task_id = progress.add_task("Verificando serviços", total=1, service="Preparando")

        def on_progress(event: str, name: str, completed: int, total: int, attempt: int) -> None:
            label = name.replace("_", " ")
            if event == "retry":
                label = f"{label}  tentativa {attempt}"
            elif event == "finished":
                label = f"Concluído {label}"
            progress.update(task_id, total=max(total, 1), completed=completed, service=label)

        with _mute_probe_logs():
            report = checker_factory(settings).check_all(
                strict=False,
                probe_mlflow_write=True,
                on_progress=on_progress,
            )
    render_health_report(report, settings, console=output)
    return report


def render_startup_error(message: str, *, console: Console | None = None, stage: str = "Inicialização") -> None:
    output = console or Console()
    output.print(Panel(
        f"[bold red]FALHA[/bold red]\n{message}\n"
        "A API não foi iniciada. Corrija o problema e execute novamente.",
        title=stage,
        border_style="red",
    ))
