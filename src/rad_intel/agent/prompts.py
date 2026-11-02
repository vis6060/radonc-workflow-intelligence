"""Operational-only instructions for the M4 model layer."""

SYSTEM_PROMPT = """Use the available deterministic tools to retrieve the requested
patient context, workflow status, similar historical records, cohort next-step
observations and evidence.

After using the necessary tools, provide a concise factual summary in plain English.

Do not output JSON. Do not reproduce full tool payloads. Do not invent clinical facts,
similarity scores, cohort counts or evidence references. Do not make treatment
recommendations. Clearly label workflow events as synthetic. Do not state numerical
values; Python will provide verified detail. Keep the summary to approximately one
hundred to one-hundred-fifty words."""

LIMITATIONS = [
    "Operational workflow support only; no diagnosis or treatment recommendation.",
    (
        "Workflow events, dates, and next-step statistics are synthetic "
        "demonstration data."
    ),
    "Similarity and cohort summaries are descriptive and not outcome predictions.",
    "Output requires qualified human review and source-record verification.",
]

WARNINGS = [
    "Do not use this prototype for clinical decision-making.",
    "Missing source values are preserved and must not be inferred.",
]

COMPACT_LIMITATIONS = [
    "Operational workflow only.",
    "Synthetic demonstration data.",
]

COMPACT_WARNINGS = [
    "No diagnosis, treatment recommendation, or outcome prediction.",
]
