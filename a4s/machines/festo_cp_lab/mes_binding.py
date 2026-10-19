"""Resolve the single Festo production resource and its current MES order.

AAS contains static service/resource references; MES owns orders and schedules.
"""
from ...mesctl.client import MesError


def resolve_line(context, mes):
    if context.get("MESBaseUrl", "").rstrip("/") != mes.config.endpoint:
        raise MesError("ProductionContext does not reference the configured trusted MES")
    code = context.get("MESLineCode")
    if not code:
        raise MesError("ProductionContext requires a MES line code")
    matches = [line for line in mes.rows("/api/v1/lines") if line.get("code") == code]
    if len(matches) != 1:
        raise MesError(f"Expected one OpenMES line with code {code!r}; found {len(matches)}")
    return matches[0]


def current_demo_orders(mes, line):
    """One current demo order on the real equipment; never select a backup pair."""
    orders = [order for order in mes.rows("/api/v1/work-orders")
              if int(order.get("line_id") or 0) == int(line["id"])
              and str(order.get("order_no", "")).startswith("A4S-")]
    if len(orders) != 1:
        raise MesError("Expected one A4S production order on Cell 1; reset the demo MES")
    return tuple(orders)
