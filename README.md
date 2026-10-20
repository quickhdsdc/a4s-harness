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

## Use cases

### AAS Creation for machine integration

Discover an asset, create its AAS from a blueprint, and enrich it with structured
information extracted from documents. The AAS keeps machine data and interface
bindings available to connected applications and agents.

[![AAS Creation demo preview](docs/videos/aas-creation-machine-integration.jpg)](docs/videos/aas-creation-machine-integration.mp4)

[▶ Watch the AAS Creation demo (2:39)](docs/videos/aas-creation-machine-integration.mp4)

### Agentic Shopfloor Management

An agent combines live OPC UA observations with AAS and MES context to
investigate a shopfloor event, explain its evidence, and prepare a reviewed
maintenance and production response.

[![Agentic Shopfloor Management demo preview](docs/videos/agentic-shopfloor-management.jpg)](docs/videos/agentic-shopfloor-management.mp4)

[▶ Watch the Agentic Shopfloor Management demo (1:55)](docs/videos/agentic-shopfloor-management.mp4)

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

## License

**Non-commercial research use only. Commercial use is prohibited.**

Original contributions controlled by the project licensors are offered under
the [Dachuan Shi Non-Commercial Research License 1.0](LICENSE)
(`LicenseRef-Dachuan-Shi-NC-1.0`). This includes a prohibition on commercial products,
paid services, customer projects, internal business use, commercial R&D and
commercial model training. A separate prior written authorization is required
for commercial use; this license grants none.

Third-party software, assets, datasets and previously granted rights retain
their applicable terms. See the repository's `LICENSING.md` for scope and
licensing history. This is source-available software, not OSI-approved
open-source software.
