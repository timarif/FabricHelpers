"""AI-based notebook auditor.

Optional subpackage that adds a Microsoft Fabric AI Functions-driven
auditor on top of the existing `fabric_scanner` pipeline. Uses the same
workspace-GUID-from-path extraction, attached-lakehouse-from-metadata
extraction, and `ws_dated` layout enumeration as the rule-based scanner,
so AI scores can be JOINed against rule-based findings on
`(workspace_id, source_dated_partition, display_name)`.

Lakehouse-only in v1; API-mode AI audit is a v2 feature.

    >>> from fabric_scanner import ScannerConfig
    >>> from fabric_scanner.ai import AIAuditOptions, run_ai_audit
    >>> cfg = ScannerConfig(source_mode="lakehouse",
    ...                     source_layout="ws_dated")
    >>> opts = AIAuditOptions(ai_output_table="my_ai_scores")
    >>> result = run_ai_audit(cfg, opts, spark)
    >>> print(result.notebooks_count, result.chunks_total)
"""
from .prompt import (
    AI_AUDIT_PROMPT,
    AI_AUDIT_RESPONSE_FORMAT,
    PROMPT_VERSION,
)
from .runner import (
    AIAuditOptions,
    AIAuditResult,
    BudgetExceededError,
    ensure_ai_functions_available,
    run_ai_audit,
)
from .schema import (
    AI_CHUNK_COLUMNS,
    AI_RESULT_COLUMNS,
    ai_chunk_schema,
    ai_result_schema,
)

__all__ = [
    "AIAuditOptions",
    "AIAuditResult",
    "BudgetExceededError",
    "AI_AUDIT_PROMPT",
    "AI_AUDIT_RESPONSE_FORMAT",
    "PROMPT_VERSION",
    "AI_CHUNK_COLUMNS",
    "AI_RESULT_COLUMNS",
    "ai_chunk_schema",
    "ai_result_schema",
    "ensure_ai_functions_available",
    "run_ai_audit",
]
