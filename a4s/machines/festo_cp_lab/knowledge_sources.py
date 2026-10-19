"""Reviewed sources for three generated PDFs; never a retrieval fallback."""

TECHNICAL_DOCUMENTS = [
    {"id": "hardware-layout", "title": "CP Lab modules: pressing and turning over",
     "origin": "REFERENCE", "source": "Anleitung - Festo CP Lab.pptx, slides 4-6; Festo CP & Module.pptx, slide 1",
     "text": "The CP Lab has two connected application modules: a press and a gripper that turns "
     "the workpiece over by 180 degrees. Turning means reorientation, not lathe machining. "
     "Conveyors, carrier stoppers, RFID and position sensors support transport. The press "
     "application uses a Revolution Pi; the turning-over module uses a microcontroller. "
     "Both communicate with a Siemens PLC. These references describe the equipment, not a "
     "current connectivity test. The work center is one asset with several interfaces; its "
     "OPC servers are interfaces of that asset, not separately owned equipment instances."},
    {"id": "opc-evidence", "title": "OPC interfaces, signal ownership and observation limits",
     "origin": "PROJECT_CONTRACT", "source": "Commissioning references; a4s/machines/festo_cp_lab/model.py; reviewed AAS blueprint",
     "text": "Commissioned external interfaces are Turning PLC at opc.tcp://opc.example.org:4041, "
     "Press PLC at port 4042 and Press RevPi at port 4043. Resolve current bindings through "
     "the selected AAS instance's OperationalData and UA server submodels. PLC module "
     "signals xReady, xBusy, xError and iRetCode are separate from the collective alarm "
     "dbVar.Err.xSF and conveyor outputs xQA1_A1/xQA1_A2. Readiness is not operating "
     "permission, and module activity is not a complete physical-motion observation. "
     "Press RevPi supplies Pressure_1/2 and Flow_1/2 (namespace 1); the integration exposes "
     "them as Press.Pressure1/2 and Press.Flow1/2. They are uncalibrated raw readings: "
     "sensor locations, physical scaling and engineering units remain unverified. Do not "
     "convert counts into bar or litres/minute using the simulation profile. A connection "
     "timeout means unavailable evidence, not a physical stop or a diagnosis. Inspect "
     "quality, timestamps, endpoint and node bindings before interpreting a sample. "
     "Fault-specific meanings and their validation status belong to the Fault and "
     "Maintenance Manual, not this interface reference."},
    {"id": "readiness-reference", "title": "Commissioning readiness and application communication",
     "origin": "REFERENCE", "source": "Anleitung - Festo CP Lab.pptx, slides 8-9 and 17-18",
     "text": "The commissioning reference mentions compressed-air supply and application "
     "communication readiness. At power-up the PLC may initially lack a connection to "
     "the RevPi or microcontroller. A qualified operator assesses readiness using approved "
     "site procedures. These are possible checks, not proof of an air leak or permission "
     "for an agent to reset, start or change physical equipment. Assess each interface "
     "separately: successful PLC reads do not prove that the RevPi OPC server is reachable. "
     "Maintain static interface and document references in AAS; obtain changing values "
     "from the commissioned OPC source. The technical reference is instance-independent "
     "and does not contain a copied equipment state."},
]

PRODUCTION_DOCUMENTS = [
    {"id": "phone-housing-route", "title": "Exhibition production route and asset-to-MES references",
     "origin": "DEMO_FICTION", "source": "A4S authored exhibition scenario; current ProductionContext contract",
     "text": "The Festo installation is one real device with Press and Turning stations in a single production route. Both stations belong to Cell 1, MESLineCode A4S-FESTO. There is no Cell 2 or alternate production resource. The demonstration uses one accepted, unstarted 90-piece phone housing order with a 45-minute planned duration. ProductionContext stores the trusted MES endpoint and stable resource/product codes, never numeric order IDs or current status. Resolve the resource in MES and read its single current order. A planned order is not evidence of a running batch or finished parts."},
    {"id": "maintenance-business-planning", "title": "Maintenance intervals and approved production rescheduling",
     "origin": "PROJECT_CONTRACT", "source": "a4s/skills/fault-maintenance/SKILL.md; OpenMES maintenance and schedule action contracts",
     "text": "Retrieve the applicable fault assessment and task-duration estimate from the "
     "Fault and Maintenance Manual (task estimates on page 4). Preserve the event, affected "
     "asset, observation source and current operational impact. Create a corrective "
     "Maintenance Event only when assessment establishes a need. Resolve its resource "
     "through ProductionContext, and propose exact planned start and end timestamps "
     "relative to the current clock. The demonstration reserves at least 180 minutes on the next local day when configured in ProductionContext. This includes planning allowance, separate from the task inspection estimate; it is not measured repair time. Record scheduled_at and scheduled_end_at; planned "
     "duration is their difference. For a configured recovery policy, preview one "
     "integrated plan containing the interval and each existing order's exact target "
     "line, start and end. Approval covers this whole plan once. Create maintenance, "
     "verify its ID and both persisted timestamps, then automatically execute the "
     "listed order moves without another approval. Use the persisted maintenance end plus the configured 120-minute demo production planning allowance. Production on "
     "the affected resource must start at or after that end, also respecting the current "
     "clock, routing and capacity; the existing order stays on Cell 1. Change its schedule immediately after interval read-back while maintenance is still pending. No wait for actual maintenance completion or physical recovery is needed to plan future production. Verify every order and the planner change list. Changed orders, "
     "expired slots, resource references or capacity require a fresh plan and approval. "
     "Stop on partial or uncertain writes; never replay successful steps. An explicit "
     "maintenance-only choice excludes automatic moves; an existing event is reused, "
     "not recreated. Rescheduling modifies existing orders; it does not "
     "create replacement orders. Maintenance creation does not automatically block an "
     "order or alter its schedule. Planned production times and delivery due dates are "
     "separate: assess both, and never claim that changing the schedule changed a due date."},
    {"id": "recovery-boundaries", "title": "MES ownership, recovery verification and a fresh demo plan",
     "origin": "PROJECT_CONTRACT", "source": "A4S MES action contracts; production reset and demo-session workflow",
     "text": "MES owns orders, issues, maintenance state and schedules. AAS holds static "
     "semantic references; current equipment evidence comes from OPC. PLC interlocks "
     "remain authoritative for physical safety. An OpenMES record is not proof of "
     "physical repair. A blocking TOOL_FAILURE issue is a separate business action "
     "requiring a confirmed need and approval, not a mandatory action for every fault. "
     "Resolving a blocking issue recalculates order status and may return an accepted "
     "no-batch order to PENDING; inspect order_after rather than blindly resuming. "
     "Timeouts can have unknown effects: read before retrying. A stopped monitor is "
     "not proof of device recovery. For a new local demonstration, Reset demo MES "
     "previews the scope and exact future slots, backs up PostgreSQL, archives the "
     "previous demo orders and maintenance, and creates one accepted 90-piece order "
     "in a 45-minute slot. The initial start is the next local whole hour "
     "with at least 15 minutes of lead time, not a fixed presentation date. Only the "
     "approved timestamps are executed. Backend restart clears disposable UI and "
     "monitor history while preserving the audit ledger and current MES business "
     "data; it does not itself reset MES or change equipment."},
]
