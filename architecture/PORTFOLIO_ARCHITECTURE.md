# Portfolio architecture

```mermaid
flowchart LR
  subgraph DATA["DATA · local / controlled"]
    C["3,346 RADCURE clinical records<br/>observed clinical provenance"]
    W["45,588 synthetic workflow events"]
    G["3,346 synthetic gold states"]
    F["Synthetic-only Bedrock fixture"]
  end

  subgraph LOCAL["IMPLEMENTED LOCALLY"]
    U["Patient + as-of selection"]
    X["run_analysis()"]
    T["Five deterministic M3 tools"]
    V["Validated AnalysisBundle"]
    I["PatientInsights assembler<br/>evidence + scope validation"]
    P["Insights top panel +<br/>existing four-panel UI"]
    U --> X --> T --> V --> I --> P
  end

  subgraph LIVE["LIVE BEDROCK VERIFIED · synthetic fixture only"]
    Q["Agent request<br/>patient + question"] --> S["Strands Agent"]
    S --> B["Amazon Bedrock<br/>Claude Haiku 4.5"]
    B --> S
    S --> T
    V --> A4["Pydantic validation +<br/>deterministic Python agent-response assembly"]
  end

  subgraph PREP["AGENTCORE PREPARED · NOT DEPLOYED"]
    A["BedrockAgentCoreApp<br/>POST /invocations · GET /ping"]
    D["Synthetic deployment provider"]
    R["Planned AgentCore Runtime"]
    A --> D
    A -. future deployment .-> R
  end

  C --> T
  W --> T
  G -. evaluation only .-> T
  F --> S
```

## Status legend

- **Implemented locally:** data ingestion, synthetic workflow generation, five
  deterministic intelligence tools, validated Patient Insights assembly, evaluation,
  and the Streamlit insights plus four-panel UI.
- **Live Bedrock verified:** exactly one bounded synthetic-fixture Strands invocation.
- **AgentCore prepared but not deployed:** compatible app entrypoint, providers,
  packaging, readiness analysis, and local tests exist; no cloud runtime exists.

Observed clinical data and synthetic workflow data remain separate. Gold labels are
evaluation-only and are not visible to production intelligence tools or the agent.
