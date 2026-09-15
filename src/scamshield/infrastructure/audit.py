import json
import logging
from datetime import datetime, timezone

from ..domain.models import Decision

logger = logging.getLogger("scamshield.audit")
logger.setLevel(logging.INFO)


def record(request_id: str, partner_id: str, decision: Decision, latency_ms: float) -> None:
    # Allowlist explícita; nunca receber o documento ou o objeto de requisição aqui.
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "partner_id": partner_id,
                "status": decision.status.value,
                "score": decision.score,
                "signals": [s.code for s in decision.signals if s.weight],
                "latency_ms": round(latency_ms, 2),
            },
            ensure_ascii=False,
        )
    )
