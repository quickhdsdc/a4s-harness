"""One approved maintenance window and exact production placements, without PLC actions."""

def register(cmd, opt):
    p = cmd("recovery prepare", "local:recovery", "Preview and store an immutable maintenance and production plan",
            resource="recovery-plans")
    opt(p, "asset", required=True)
    opt(p, "aas-endpoint", required=True)
    opt(p, "maintenance-id", type=int, help="Reuse an existing event; never create a duplicate")
    for flag in ("title", "description", "start", "end"):
        opt(p, flag)
    p = cmd("recovery apply", "local:recovery", "Execute the exact prepared plan once after combined approval",
            "POST", "recovery-plans", target=True,
            effects=("Creates or verifies maintenance, then moves the listed existing orders automatically. No equipment action.",),
            policy_checks=("Immutable exact plan", "Fresh unchanged orders and asset references",
                           "Persisted maintenance end", "One attempt; stop on partial or uncertain writes"))
