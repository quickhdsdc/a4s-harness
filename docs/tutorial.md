# Local setup and first run

## Requirements

- Python 3.11–3.14
- Node.js and npm
- Docker Desktop or another Docker Compose installation for local services

## Install

From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[ui,mes,opc,documents,dev]'
Push-Location frontend
npm.cmd ci
Pop-Location
```

Copy `.env.example` to `.env` if you need to override local settings. Put
service URLs, API keys and credentials in this ignored local file; never commit
the populated copy. Do not reuse credentials from another environment.

## Run

On Windows, start the local stack with `start.cmd` and stop it with `stop.cmd`.
Use the URLs printed by the launcher. Open **Operations** and select the local
simulation to explore the agent workflow without connecting to equipment.

The simulation exercises the same event, investigation and review flow used by
the application. It does not send commands to a physical controller or prove
that a deployment is safe for a particular asset.

## Connect your AAS and OPC UA server

The AAS holds the asset description and interface bindings. To connect your
server, copy a blueprint to a local file and edit the endpoint and node IDs in
the relevant elements. The endpoint belongs in the qualifier value, in this
form:

```text
opc.tcp://HOST:PORT#NODE_ID
```

For a readable Property, set its `valueSource` qualifier. For an Operation,
set `invocationDelegation`; the value identifies the endpoint and target node.
Use the node IDs returned by OPC UA Browse. Import the edited AAS/blueprint into
your AAS repository, then select that AAS in the application. Detailed examples
are in [OPC UA connection setup](opc-connection.md).

If your server requires authentication or message signing, configure those
locally and grant only the access the harness needs. Do not put usernames,
passwords, private keys or certificates in a shared blueprint.

## MES integration

The MES adapter reads business context and submits supported business actions
through the configured MES API. Configure the base URL and API credentials in
the local environment. The harness keeps MES business state separate from live
OPC UA observations and AAS metadata. Review the adapter's supported operations
and approval policy before connecting a production MES.

## Development

Install the `dev` extra for Python checks. Frontend scripts are in
`frontend/package.json`. Configure integrations against a local test service or
simulation before pointing them at a shared system.
