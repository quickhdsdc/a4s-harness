"""Authored alarm catalogue. Field observations are not manufacturer mappings."""

LEVELS = (
    "Project maintenance levels: M0 means record/review only; M1 means qualified "
    "onsite operator assessment using approved site procedures; M2 means qualified "
    "maintenance personnel; M3 means controls/process engineering confirmation. "
    "These are local planning categories, not manufacturer or standards-certified levels."
)

PHYSICAL_ROWS = [
    ["Collective alarm", "Press/Turning: dbVar.Err.xSF becomes true. Two Good Boolean samples.",
     "Station alarm; cause unspecified. Field-tested trigger. xSF01 is not a unique cause code.",
     "M1: inspect current HMI and applicable alarm record. M2/M3 if unresolved. No automatic acknowledgement/restart."],
    ["Module code 7", "Press/Turning: ApplicationModule_DB.iRetCode enters 7 after a known baseline; two Good integer samples.",
     "Process intervention observed during operator-reported no-workpiece HMI tests. Field correlation; manufacturer meaning unverified.",
     "M1: confirm current HMI, workpiece presence/position and process step. M3: verify code table if inconsistent. Maintenance need depends on confirmed cause."],
    ["BG8 input", "xG1_KG2_BG8 on both PLCs. Auxiliary: Press xHL_BG8, Turning xGM_BG8.",
     "Changes during normal cycles. No independent alarm condition. Polarity/auxiliary logic unverified.",
     "M0: retain evidence. M1: correlate expected-workpiece state and HMI. M3: validate logic before creating a missing-part rule."],
    ["Safety input", "Press/Turning xSF5 (EmergencyStopCircuit), correlated with station alarms.",
     "Raw safety-circuit evidence. Physical polarity unverified; false does not independently prove emergency stop.",
     "M1: qualified onsite safety/HMI assessment. M2/M3: investigate persistent fault using site procedures. Do not remotely reset."],
    ["Activity status", "ApplicationModule_DB.xBusy and ConveyorForward (xQA1_A1) are different signals.",
     "Busy=false occurred while ConveyorForward=true in this test. Module idle is not proof that the equipment is stopped.",
     "M0: compare module state, actuator output and onsite observation. Do not infer physical motion solely from one status bit."],
]

SIMULATION_ROWS = [
    ["Supply alarm", "UI OPC fault/leak preset: Press.Fault01 / Fault=true; PressureBar=3.8, FlowLMin=48.",
     "Authored profile. Low pressure with FlowLMin above 30 and EmergencyStop=false supports open vent/leak hypothesis.",
     "M1/M2 planning category: inspect air supply, valve state and connections. Cannot distinguish open valve from damaged connector remotely."],
    ["Safety stop", "Runtime simulation only: Safety.EmergencyStop=true and station fault.",
     "Active safety stop in this simulation profile. Do not classify it as leakage.",
     "M1: onsite confirmation. Physical intervention remains under site procedures. Do not reset/start through the agent."],
    ["Low supply", "Assessment alternative: low pressure with low flow. Not a preset UI state.",
     "Investigate upstream supply; this is an alternative to leakage, not a physical calibrated PLC threshold.",
     "M1/M2: assess supply condition. Query current production impact before proposing MES maintenance or rescheduling."],
]

DURATION_ROWS = [
    ["Unspecified station alarm: initial onsite assessment", "30 minutes, assessment only",
     "Initial project estimate, not measured repair history. M1; escalate to M2/M3 if unresolved.",
     "Confirm HMI alarm and inspection scope. Repairs and parts replacement need a revised estimate."],
    ["Module intervention / reported no workpiece: operator assessment", "15 minutes, assessment only",
     "Initial project estimate. M1; code 7 correlation is not a verified manufacturer cause mapping.",
     "Confirm HMI and expected process state. Do not create maintenance if operator assessment alone is sufficient."],
    ["Safety circuit: onsite assessment", "30 minutes, assessment only",
     "Initial project estimate. M1; physical input polarity remains unverified.",
     "Confirm current safety/HMI condition. A persistent safety fault requires qualified escalation and a new estimate."],
    ["Pneumatic supply / vent or leak: initial inspection", "30 minutes, inspection only",
     "Existing authored simulation inspection allowance. M1/M2; physical task estimate needs onsite confirmation.",
     "Assess supply, valve state and connections. Confirm cause and revise duration before booking an actual repair."],
    ["BG8 or activity observation without a confirmed alarm", "No maintenance booking",
     "M0 evidence review; no independent alarm or repair duration is established.",
     "Correlate HMI/process evidence first. No assumed outage or production delay."],
]

MANUAL_DOCUMENTS = [
    {"id": "physical-alarm-catalogue", "title": "Physical Festo alarm codes and observed signal conditions",
     "origin": "FIELD_OBSERVATION", "source": "2026-10-06 OPC capture and operator HMI report; project alarm catalogue",
     "text": "Physical scope: Press PLC port 4042 and Turning PLC port 4041. A confirmed collective alarm and a module return-code condition are independent triggers; trigger logic is deterministic and makes no root-cause assertion. OperationalData exposes Press.ReturnCode and Turning.ReturnCode as Int16. " + LEVELS,
     "table": PHYSICAL_ROWS},
    {"id": "physical-workpiece-code-evidence", "title": "Return code 7: missing-workpiece field correlation and maintenance assessment",
     "origin": "FIELD_OBSERVATION", "source": "HMI photograph and pre-18:00 OPC evidence, 2026-10-06; PROGRESS.md#field-evidence",
     "text": "A module return code of 7 was correlated with operator-reported 'Kein Werkstueck vorhanden !' (no workpiece present), while the sampled collective fault bits stayed clear. The exact manufacturer meaning is unverified: do not diagnose every code 7 as a missing workpiece or treat every nonzero return code alike. The current deterministic monitor observes Press.ReturnCode and Turning.ReturnCode independently. Two consecutive Good integer samples establish a condition; only a fresh onset after a known baseline permits automatic Agent handoff. Baseline conditions, communication gaps and changed bindings do not establish a fresh onset. BG8 alone is not an alarm trigger. The trigger requests investigation without encoding a cause in the prompt. Confirm the current HMI message, expected process step and workpiece presence/position; compare sensor mismatch and other return-code meanings before determining cause. Do not assume that a fault seen at Press originated there; correlate both stations and current onsite observations. Qualified onsite personnel assess the workpiece and sensors under site procedures. The Agent does not command HMI Repeat/Ignore/Abort, acknowledge PLC faults or restart equipment. Operator intervention can be sufficient: maintenance and MES changes require a confirmed operational need, not merely code 7. Escalate repeated or unexplained conditions to qualified maintenance or controls engineering. Maintenance levels are defined on page 1; task estimates are on page 4. Appendix A on page 5 preserves the original observation times and limitations."},
    {"id": "simulation-alarm-catalogue", "title": "Runtime simulation diagnostic matrix and maintenance levels",
     "origin": "ENGINEERING_SCENARIO", "source": "Festo runtime simulation profile; project maintenance classification",
     "text": "Scope: the current isolated UI OPC server at opc.tcp://127.0.0.1:4849/a4s-test/. Normal state is 6.0 bar and 12 litres/minute, with both stations ready and alarm bits clear. Fault/leak changes the OPC preset immediately to 3.8 bar and 48 litres/minute; Press.Ready becomes false while Turning.Ready stays true. Emergency-stop state sets Safety.EmergencyStop and both station faults true, with both Ready bits false. State buttons update the test server; confirm values by OPC read-back. The monitor confirms fault transitions from two Good Boolean samples, not from a pressure ramp or a pressure-duration calculation. Low pressure below 4.8 with flow above 30 and EmergencyStop=false supports an open vent or leak hypothesis in this authored profile; it cannot distinguish an opened valve from a damaged connector. These engineering values are not physical RevPi calibrations, PLC alarm mappings or manufacturer limits. Retrieve the current observation source before applying this matrix. Maintenance levels are defined on page 1 and inspection estimates on page 4; use the Production Playbook for approved MES actions. Historical HTTP ramp behavior is documented separately in Appendix B on page 6.",
     "table": SIMULATION_ROWS},
    {"id": "maintenance-duration-planning", "title": "Maintenance task duration estimates and production release planning",
     "origin": "PROJECT_CONTRACT", "source": "Project planning estimates; existing pneumatic inspection allowance; no measured repair-duration history",
     "text": "Use these initial estimates only for the named assessment/inspection task, not for a guaranteed repair. The authored demo reserves a minimum 180-minute maintenance window on the next local day when configured in ProductionContext, including scheduling allowance beyond the inspection estimate. Keep the original production start time on that next day, using the later of the original production date and current MES local date as the base. Plan the existing production order one day (24 hours) after the persisted maintenance end (DemoProductionReleaseBufferMinutes=1440). This is a demonstration planning reservation, not measured repair history. No measured maintenance durations were collected during the 2026-10-06 tests. M0 observation does not require a maintenance event. Unlisted tasks or confirmed repairs need a qualified operator estimate before booking. Cite this page and task when proposing an interval. Planned scheduled_at/scheduled_end_at define its duration; keep actual lifecycle started_at/completed_at separate. The persisted planned end is the earliest release time for production on the affected resource, not proof of physical recovery. Use the Production Playbook for current-clock scheduling, Cell 1 capacity, preview, approval and interval read-back. Reassess overruns before extending an interval. Record actual elapsed task time and completion notes for future experience-based revisions.",
     "headers": ["Task / scope", "Planned duration", "Estimate basis / level", "Completion / escalation"],
     "table": DURATION_ROWS},
    {"id": "bg8-workpiece-trigger-evidence", "title": "Appendix A: missing-workpiece field-test evidence, 2026-10-06",
     "origin": "FIELD_OBSERVATION", "source": "HMI photograph and pre-18:00 OPC capture; PROGRESS.md#field-evidence",
     "text": "Historical field evidence, not a manufacturer alarm mapping. All times are host observations on 2026-10-06, Europe/Berlin. The operator identified Turning as the probable station for an initial removed-workpiece test. The HMI showed no workpiece present, current state 3, ignore state 4 and abort state 0. HMI states have no confirmed OPC mapping; HMI, PLC and host clocks must not be assumed aligned. A separate collective-fault episode began at 16:27:36 on Turning and 16:27:37 on Press; temporal proximity alone does not establish a missing-workpiece cause. In the later reproduction reported on both stations, iRetCode changed 0 to 7 on Turning at 16:44:51.567, clearing at 16:47:23.868 (152.30 seconds), and on Press at 16:44:55.441, clearing at 16:47:17.467 (142.03 seconds). Sampled xSF, xSF01 and xError remained false. The former Fault-only monitor missed this interaction condition; the current independent return-code monitor is described on page 2. Both PLCs expose ns=3;s=\"xG1_KG2_BG8\"; Turning also exposes ns=3;s=\"xGM_BG8\", and Press ns=3;s=\"xHL_BG8\". BG8 recording began at 16:27:15, so earlier transitions cannot be reconstructed. During two minutes after collective-fault recovery, Turning BG8 changed true/false 67 times each, and Press 73 times each. A fall or false value alone must not trigger a fault investigation; polarity and auxiliary logic are unverified. During the reported return-code intervals BG8 continued changing and both auxiliary signals stayed false. Earlier emergency-stop/leakage tests were reported successful by the operator; that does not identify the cause of this event. Review only the pre-18:00 evidence for this test. Raw provenance is recorded in the linked project field-test report, including capture paths and query results."},
    {"id": "pneumatic-leak-scenario", "title": "Appendix B: historical synthetic HTTP pressure-ramp scenario",
     "origin": "DEMO_FICTION", "source": "A4S scenario v1; a4s/machines/festo_cp_lab/demo_monitor.py; historical demo PDFs",
     "retrieval_scope": "HISTORICAL_ONLY",
     "text": "Historical HTTP generator only: this is not the current UI OPC source or physical equipment behavior. The former synthetic pressure stream started at 6.0 bar. After 8 seconds it fell by 0.13 bar per second, down to 3.8 bar. Warning was below 5.2 bar; a synthetic fault followed pressure below 4.8 bar for 3 seconds. The fictional mechanism was a leaking pneumatic connector; synthetic press readiness fell, turning-over readiness stayed true, and conveyor speed changed from 4 metres/minute to zero in the fault state. These were invented scenario assumptions, not calibrated thresholds, PLC alarms or a measured diagnosis. The HTTP generator retains this behavior for legacy test coverage. Do not use its ramp, conveyor values or thresholds to interpret current UI OPC monitoring: the current simulator has explicit state presets and confirmed Boolean fault transitions, as described on page 3. Earlier scenario documents prescribed an issue-based business demonstration; the current Production Playbook instead requires a confirmed operational need before approving an integrated maintenance and scheduling plan; blocking issues remain separate actions. Task-duration estimates have a single current source on page 4. This appendix preserves historical numerical provenance and does not define the current maintenance or scheduling procedure."},
]
