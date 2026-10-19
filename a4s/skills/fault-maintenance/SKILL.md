---
name: fault-maintenance
description: Investigate station fault evidence, retrieve asset knowledge, and prepare approved MES maintenance and scheduling actions
triggers: maintenance investigation, fault transition detected, maintenance plan, maintenance event, 故障分析, 维护计划
---

# Fault investigation and maintenance planning

Follow this procedure for a fault notification and subsequent approval/follow-up.
Do not infer root cause from an alarm bit or from the wording of the notification.
Equipment actions are outside this workflow.

1. **Resolve the notified asset and evidence.** Use the exact AAS repository and
   asset ID in the notification. Read its referenced OperationalData,
   MaintenanceInstructions and ProductionContext, not similarly named templates.
   The read-only helper is:
   `python -m a4s.machines.festo_cp_lab.fault_context --asset ASSET_ID --endpoint AAS_URL`
   It returns source submodel IDs and contents, not a diagnosis. Alternatively use
   `aas shell show` and AAS read commands (inspect `aas --help`). Missing models or
   references are blockers to unsupported actions, not permission to invent IDs.
2. **Interpret the transition using those semantics.** Compare before/after,
   units and quality. A communication failure is not a device fault or recovery.
   Apply only documentation and alarm mappings for the observed asset and source.
   Read the document's validation status before attributing a cause. A monitoring
   condition is an observation requiring investigation, not a root-cause diagnosis.
3. **Retrieve documents before diagnosing.** Use the asset's knowledge service;
   the local helper is `python -m a4s.machines.festo_cp_lab.knowledge`.
   Construct its `--query` from the actual observed tags, code values and operator
   symptoms. Do not send a literal placeholder or assume a cause in the query.
   Read returned PDF passages; cite filename/page in the assessment. Follow the
   retrieved document's scope and provenance. If evidence is insufficient, run a
   narrower query or ask the operator. Distinguish observations, likely cause,
   alternatives and confirmation needed. Do not present a hypothesis as a repair.
4. **Assess business impact.** Compare the ProductionContext MES endpoint with the
   configured trusted MES. Resolve its stable `MESLineCode` against current MES
   lines, then read current orders whose MES `line_id` matches that line. The demo has one Festo resource and one current production order on Cell 1. Use `mes auth whoami`,
   `mes line show CODE`, `mes order ls --line CODE`, and `mes order show ID` for
   live values. Never infer an order ID from the AAS or copy MES state into it.
   For the reverse lookup, compare the order's MES `line_id` with the resolved
   line and then match that line's `code` to an instance's `MESLineCode`.
   Inspect existing `mes maintenance ls --line ID` records for this event ID before proposing a new
   one. A previously approved/created event must not be created again.
5. **Prepare the appropriate documented response.** Determine from the current
   evidence and applicable manual whether operator assessment, maintenance or
   engineering review is warranted. An anomaly notification does not itself
   require a MES maintenance event. If maintenance is warranted, state the inspection scope, qualified
   operator requirement, priority, proposed start and end with timezone, and
   estimated duration from the applicable manual. Cite the PDF/page and its
   estimate basis. Duration equals end minus start; compute end from the chosen
   start and duration. A planning estimate is not measured repair experience or
   guaranteed recovery. If ProductionContext specifies DemoMaintenanceWindowMinutes, use that
   authored demo reservation (currently at least 180 minutes) for the planned event; distinguish it
   from the manual inspection estimate and explain the included planning allowance.
   It is not a repair estimate. DemoMaintenanceStartDayOffset=1 defaults the event to
   the next MES local day after the later of the original production date and today,
   retaining the original production start time. DemoProductionReleaseBufferMinutes=1440
   places production one day (24 hours) after the persisted maintenance end. Use the exact
   timestamps returned by recovery prepare; it computes these static demo defaults. If the applicable task has no estimate, ask the operator
   for one before creating an event. Query current time and MES timezone; never
   use historical demonstration dates. Preview:
   `mes maintenance create --title TITLE --event-type corrective --line LINE_ID --scheduled-at START_ISO --scheduled-end-at END_ISO --description DESCRIPTION --trace-id EVENT_ID --dry-run`
   Include AAS ID, event ID, evidence citations, task/maintenance level, estimated
   duration and estimate basis in description. Do not invent a separate duration
   field or employee ID. Both timestamps are required and checked by the CLI.
   If ProductionContext contains ReplanningPolicy, use the integrated recovery
   workflow as the default complete response, not a maintenance-only action. Prepare the maintenance window AND exact production moves
   before approval, in one read-only command:
   `mes recovery prepare --asset ASSET_ID --aas-endpoint AAS_URL --title TITLE --description DESCRIPTION --start START_ISO --end END_ISO --trace-id EVENT_ID`
   This resolves current orders and returns plan_id, expiry, the maintenance
   interval, each order's current/proposed line and exact start/end, and one
   apply_command. Use the returned interval and moves, including the configured demo
   reservation, as the exact combined approval proposal; do not silently add other allowances. Explain the inspection estimate, production impact and all exact
   times together. State that approving this plan includes automatic rescheduling
   after maintenance read-back. Execute the returned `mes recovery apply PLAN_ID
   --trace-id EVENT_ID` through the approval gate. The gate asks ONCE for the
   combined plan; do not add a duplicate ask_user confirmation, then stop at
   maintenance creation, or request a second approval for its listed moves.
   Approval is limited to this immutable plan, not arbitrary later MES changes.
   Expired plans, changed orders/references or unavailable capacity require a
   refreshed proposal and approval, never silently changed timestamps.
   Run one MES command per shell call. Quote text arguments and use plain text
   without shell operators (especially semicolons, pipes, ampersands or newlines)
   inside descriptions: the conservative command gate rejects those too.
6. **Complete the approved recovery plan automatically.** recovery apply creates
   the event once (or reuses the explicitly selected existing event), reads back
   its ID, status, scheduled_at and persisted scheduled_end_at, then executes the
   approved existing-order moves sequentially and verifies their read-back and
   planner change list. Production on the affected resource cannot precede that
   confirmed end; there is no alternate production resource in this demo. Update the existing order immediately after maintenance timestamp read-back, while the event is still pending. Do not wait for completion or physical recovery to change a future schedule.
   The planned end is a scheduling boundary, not proof of physical recovery.
   Never create replacement orders, assume a 60-minute duration, add an
   undocumented release buffer, resume equipment or change PLC values.
   Report what was actually verified. If creation or a move is uncertain, the
   coordinator stops and records partial progress. Inspect existing records;
   never replay a used plan or successfully completed steps. If maintenance
   overruns or remains unresolved, reassess before proposing another plan.
   Do not finish at maintenance creation while approved order moves are pending.
   Do not ask the user to type reschedule or wait for a fault-clear signal.
   Ordinary maintenance create alone does not implement this recovery workflow.
   Apply the same workflow to live and simulated observations.
7. **Respect an explicit maintenance-only choice or existing maintenance.** If
   the operator specifically approves maintenance ONLY, use the ordinary create
   command without --dry-run, verify both timestamps and stop before order
   changes; do not interpret that choice as combined approval. If an event was
   already created for the fault, NEVER create a duplicate. Prepare the remaining
   recovery with `mes recovery prepare --asset ASSET_ID --aas-endpoint AAS_URL
   --maintenance-id ID --trace-id EVENT_ID`, explain its exact moves and execute
   the returned apply_command through one approval gate. An old approval of
   maintenance alone does not retroactively approve moves. Without a configured
   ReplanningPolicy or a feasible integrated plan, explain the concrete blocker;
   a separately scoped, previewed MES action remains possible. The read-only
   replanning helper supports inspection with --maintenance-id ID and always uses
   persisted scheduled_end_at. Legacy events missing an end require a documented
   estimate, approved update and read-back first. Zero available hours do not
   prove missing calendar configuration or unsupported scheduling. Report the
   returned capacity and which data need checking.

Communicate the investigation as it happens, not only after a business write:
- With the first read calls, give one short assistant sentence stating the
  observed change and that you are checking asset information and manuals.
- After retrieving evidence, give a short assistant update alongside the next
  tool calls: observed pressure/flow changes, likely cause versus uncertainty,
  and the supporting manual page. Do not expose private reasoning or raw JSON.
- Before approval, explain the proposed inspection and production impact in
  plain language. Let the combined approval gate present the exact plan; use ask_user only for missing task information or an explicit scope choice.
- Use finish.summary for the final user-facing outcome: what happened, likely
  cause, what was actually done, what remains blocked and the next operator step.
  Do not emit a long final assistant report and then repeat it in finish.
Keep trace IDs, execution IDs, hashes and chunk identifiers in tool evidence and
MES records, not normal chat prose. A maintenance ID and PDF/page citation are
useful to the operator. Respect simulation provenance, but do not repeatedly
prefix every finding with test/disclaimer wording. Never imply physical repair.
