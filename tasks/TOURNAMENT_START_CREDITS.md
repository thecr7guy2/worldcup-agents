# Tournament Starting Credits (OpenRouter)

The exact OpenRouter balance the World Cup tournament begins with, captured after the
final pre-tournament dry run on 2026-06-11. This is the canonical starting bankroll of
real credits for the whole competition.

## Starting balance = **$86.984367008**

Source: `GET https://openrouter.ai/api/v1/credits`

| moment | total_credits | total_usage | remaining |
|---|---|---|---|
| before final dry run | 100.0 | 12.479068233 | 87.520931767 |
| **after final dry run (TOURNAMENT START)** | **100.0** | **13.015632992** | **86.984367008** |

Total spent on final dry run + diagnostics: **$0.536564759**
(one failed briefing, raw-error reproduction, the full 7-model single-match dry run,
and a DeepSeek-V4-Pro predict re-validation after the retry fix).

Remaining = total_credits − total_usage = 100 − 13.015632992 = **86.984367008**.
