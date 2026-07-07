"""Research protocol registry, trial ledger, and provenance gates."""

from src.research_protocol.acceptance import AcceptanceError, AcceptedResult, validate_accepted_result
from src.research_protocol.field_provenance import ProtocolFieldProvenance
from src.research_protocol.hashing import compute_protocol_hash
from src.research_protocol.ledger import TrialLedger, record_protocol_field_confirmation
from src.research_protocol.model import (
    BenchmarkSpec,
    CostModelSpec,
    DataSetContract,
    EvaluationPlan,
    ExecutionAssumptions,
    FilterSpec,
    ResearchProtocol,
    SplitSpec,
    UniverseSpec,
)
from src.research_protocol.protocol_review import ProtocolReview, review_protocol_for_registration
from src.research_protocol.registry import (
    ProtocolImmutableError,
    ProtocolRegistrationError,
    ProtocolRegistry,
    RegisteredProtocol,
    protocol_hash,
    register_protocol,
)
from src.research_protocol.trial import TrialEvent, TrialEventType

__all__ = [
    "AcceptanceError",
    "AcceptedResult",
    "BenchmarkSpec",
    "CostModelSpec",
    "DataSetContract",
    "EvaluationPlan",
    "ExecutionAssumptions",
    "FilterSpec",
    "ProtocolFieldProvenance",
    "ProtocolImmutableError",
    "ProtocolRegistrationError",
    "ProtocolRegistry",
    "ProtocolReview",
    "RegisteredProtocol",
    "ResearchProtocol",
    "SplitSpec",
    "TrialEvent",
    "TrialEventType",
    "TrialLedger",
    "UniverseSpec",
    "compute_protocol_hash",
    "protocol_hash",
    "record_protocol_field_confirmation",
    "register_protocol",
    "review_protocol_for_registration",
    "validate_accepted_result",
]
