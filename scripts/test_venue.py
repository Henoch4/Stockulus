"""Offline unit checks for the cross-venue divergence guard (no network)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent.data_integrity import DataIntegrityGate, Severity

g = DataIntegrityGate(staleness_threshold_s=30.0)

# 1. Agreement -> OK
r = g.check_venue_divergence("AAPLx", {"xstocks": 337.24, "bitget": 337.30}, 100.0)
assert r.severity == Severity.OK, r.reasons
print("agree OK:", r.reasons)

# 2. Live-like spread (~60bps) -> SOFT warning, not a block
r = g.check_venue_divergence("AAPLx", {"xstocks": 337.24, "bitget": 335.10}, 100.0)
assert r.severity == Severity.SOFT_WARNING and not r.blocks_trading, r.reasons
print("soft warn:", r.reasons)

# 3. Wide disagreement -> HARD BLOCK
r = g.check_venue_divergence("AAPLx", {"xstocks": 337.24, "bitget": 320.00}, 100.0)
assert r.severity == Severity.HARD_BLOCK and r.blocks_trading, r.reasons
print("hard block:", r.reasons)

# 4. Missing second opinion -> OK, never a block (fail-open)
r = g.check_venue_divergence("AAPLx", {"xstocks": 337.24, "bitget": None}, 100.0)
assert r.severity == Severity.OK and not r.blocks_trading, r.reasons
print("missing OK:", r.reasons)

# 5. combine(): worst severity wins, reasons preserved
a = g.check_venue_divergence("AAPLx", {"xstocks": 337.24, "bitget": 335.10}, 100.0)
b = g.check_market_data({}, 0.0)
c = g.combine(b, a)
assert c.severity == Severity.SOFT_WARNING and len(c.reasons) == len(a.reasons)
print("combine OK")
print("ALL VENUE CHECKS PASSED")
