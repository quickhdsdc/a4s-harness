# A4S Harness

A4S is an agentic active AAS harness for connecting an AI agent to industrial
assets and business systems through explicit, reviewable interfaces. The AAS
describes assets, capabilities and bindings; OPC UA supplies live signals and
accepts configured operations; a MES adapter provides production and
maintenance context. The harness coordinates these systems, records its work,
and gates consequential actions through policy and approval.

The repository includes a web interface, command line tools, AAS discovery and
editing, OPC UA clients, MES integration points, and an Operations view with a
local simulation for trying the workflow without connecting equipment.

## Start locally

See [the tutorial](docs/tutorial.md) for setup. In brief, install the Python
package and frontend dependencies, configure the local services, then run
`start.cmd` on Windows. The Operations page can use its built-in simulation;
no physical OPC UA server is needed to explore that workflow.

## Connect an OPC UA server

Copy an AAS blueprint to a local JSON file and set the endpoint and node IDs in
its interface bindings. For readable properties, use a `valueSource` qualifier;
for callable operations, use an `invocationDelegation` qualifier. The format is
`opc.tcp://HOST:PORT#NODE_ID`, for example:

```json
{
  "type": "valueSource",
  "value": "opc.tcp://opc.example.org:4840#ns=2;s=Line1.Temperature"
}
```

Use the OPC UA Browse command or your server's address-space browser to get the
node IDs, then edit the copied blueprint and import it into your AAS repository.
Keep server addresses and credentials in your local configuration. See
[OPC UA connection setup](docs/opc-connection.md) for details and an operation
example.

## Project map

- `a4s/`: agent runtime, AAS and OPC UA clients, MES adapters, server API
- `frontend/`: web interface, including Operations and simulation
- `BaSyxMinimal/`: local AAS repository configuration and example blueprints
- `docs/`: setup, interface configuration, and repository layout
- `tests/`: automated checks

## Security and scope

Do not commit local `.env` files, access tokens, certificates, server addresses,
or exported production data. Use example hostnames in shared blueprints and put
deployment-specific values in local configuration. Simulation demonstrates
software behavior only; it does not validate or authorize physical equipment
actions.
