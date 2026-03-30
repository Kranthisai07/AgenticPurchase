# Agent Timeout Reference
| Agent    | Timeout (s) | Notes                          |
|----------|-------------|--------------------------------|
| Vision   | 15          | Image inference via API        |
| Intent   | 10          | Fast structured extraction     |
| Sourcing | 20          | Parallel marketplace API calls |
| Trust    | 20          | Two-session LLM evaluation     |
| Ranking  | 10          | Local scoring formula          |
| Checkout | 30          | Payment API + webhook wait     |
| **Saga** | **120**     | Global bound across all agents |

Paper note: the range is 10-30s per agent. The paper will be corrected to state "10-30 seconds" instead of "20-30 seconds".
