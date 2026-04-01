# Setup First - AI Roadmap

## Goal
Prioritize a stable and winning setup before enabling AI influence on live decisions.

## Rule 0
No AI model should force entries while setup validation is not approved.

## Priority Order
1. Strategy robustness (IS/OOS/walk-forward)
2. Risk and governance stability
3. Operational consistency (paper vs expected behavior)
4. AI layer activation

## Current AI Policy
- AI remains comparative/support mode.
- Analytical and risk/governance hard blocks always win.
- AI cannot override blocked operational state.

## Activation Phases

### Phase 1 - Shadow Mode
- AI runs on every closed candle.
- AI outputs are logged only:
  - `ai_signal`
  - `ai_confidence`
  - `ai_edge` (optional)
- No impact on final action.

Exit criteria:
- Stable calibration over enough sample (minimum trade/signals threshold).
- No evidence of degradation by regime.

### Phase 2 - Assist Mode
- AI can adjust scenario score with strict limits.
- Example: score adjustment cap = +/- 1.0 point.
- AI still cannot create new direction by itself.

Exit criteria:
- Better or equal OOS expectancy vs baseline.
- No increase in destructive drawdown behavior.

### Phase 3 - Gated Mode
- AI may veto low-quality entries under strict confidence thresholds.
- AI still cannot bypass hard blocks.
- Reversal against strong regime remains blocked.

Exit criteria:
- Persistent edge by regime and setup type.
- Stable paper alignment.

## Setup Approval Checklist (before AI influence)
- Positive OOS return and acceptable drawdown
- Profit factor above minimum threshold
- Consistent behavior by regime
- Healthy approval/block distribution (no extreme over-blocking)
- Paper-trade alignment acceptable

## Non-Negotiables
- Closed candles only (no lookahead).
- Real market data only for runtime analysis.
- Hard blocks/risk engine/governance always have final authority.

## Operational Decision Rule
Until setup approval is confirmed:
- Keep AI influence disabled (`ENABLE_AI_SIGNAL_INFLUENCE=false`).
- Use AI outputs only for audit and diagnostics.
