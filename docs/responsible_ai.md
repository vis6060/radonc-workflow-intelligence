# Responsible AI and operational boundary

This prototype is limited to descriptive operational workflow intelligence. It
must not diagnose disease, recommend treatment or radiation dose, predict toxicity
or clinical outcomes, or issue autonomous clinical decisions. Outputs require
qualified human review and must link back to inspectable evidence.

Observed clinical data and synthetic operational events are separate data classes.
Every source-bearing model explicitly labels one of those provenance types.
Synthetic content must never be presented as observed fact, and observed fields
must never be invented to complete a record. Gold evaluation labels remain outside
agent-visible inputs.

Deterministic code owns workflow reconstruction, similarity calculations,
statistics, point-in-time filtering, and evidence retrieval. Foundation models may
orchestrate tools and synthesize narratives, but they are not the source of
numerical truth. Patient identifiers must be handled consistently, cross-patient
information leakage must be prevented, and future information must be excluded
from point-in-time views.

Credentials and restricted patient records must not be committed, published, or
silently uploaded. AWS activity requires an explicit later milestone and approved
configuration. M0 makes no network or AWS service calls at runtime.
