# Evaluation

M7A provides a deterministic offline evaluation framework. Gold labels remain separate
from agent-visible workflow inputs. Run it from the repository root with:

```powershell
python -m evaluation.runner --data-directory data\processed --output evaluation\results
```

The committed reports contain aggregate metrics and sanitized case labels only. Local
patient identifiers are used in memory during evaluation and are never written to the
reviewed result files. Live Bedrock evaluation is disabled and was not run in M7A.
