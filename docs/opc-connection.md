# Connect an OPC UA server

An AAS describes which OPC UA nodes represent readable values and callable
operations. The harness reads these bindings from the AAS, so a user can
connect a server by copying a blueprint, changing its bindings, and importing
the edited AAS into the configured repository.

## 1. Get the endpoint and node IDs

Use the endpoint URL and security mode configured by your server administrator.
Browse the server address space to find each node ID. A node ID may look like
`ns=2;s=Line1.Temperature` or `ns=3;i=42`. The server must be reachable from
the machine or container running the A4S backend.

## 2. Edit the AAS bindings

For a readable Property, add or change the `valueSource` qualifier. For an
Operation, add or change the `invocationDelegation` qualifier. In both cases,
the value combines the OPC UA endpoint and the node ID after `#`:

```json
{
  "type": "valueSource",
  "value": "opc.tcp://opc.example.org:4840#ns=2;s=Line1.Temperature"
}
```

An Operation uses the same value shape:

```json
{
  "type": "invocationDelegation",
  "value": "opc.tcp://opc.example.org:4840#ns=2;s=Line1.Start"
}
```

Keep the endpoint and node ID in the qualifier value. Do not put credentials in
the AAS. If multiple servers provide values, each element can name its own
endpoint and node ID.

## 3. Import and verify

Import the edited blueprint/AAS into your configured AAS repository and select
the resulting asset in A4S. Use OPC Browse and Read to check connectivity and
confirm that the selected nodes have the expected data types and values. Test
operations only against a simulation or an explicitly approved test target.

## Network and security

The OPC UA endpoint must be reachable from the backend runtime, not merely from
the user's browser. For Docker deployments, configure routing/firewall access
from the backend container to the server. Follow the server's authentication,
certificate and signing requirements. Store secrets and certificates in local
runtime configuration, restrict their filesystem permissions, and never commit
them or embed them in a shared blueprint.
