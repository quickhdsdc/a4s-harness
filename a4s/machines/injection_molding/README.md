# Simulated injection moulding machine

An edge node the harness can actually drive. There is no injection moulding
machine on this desk, and the parts of the design that only matter when
something physical is on the other end — Operation delegation, the approval
gate, provenance for a value that came off a machine rather than out of a
document — need one that behaves like the real thing.

Brought in from `EmbodiedTwin/MachineAgent` and rebuilt for this architecture.
The original exposed its capabilities over MCP with an OPC UA server behind it;
here they are HTTP endpoints that AAS Operations delegate to, because the AAS
is the interface this harness reaches assets through. The separation the
original was built around is unchanged: **the machine offers capabilities, and
no agent logic lives here.**

## What makes it a simulation rather than a stub

It replays a real production run — 1,167 consecutive shots, each with its
process parameters and the weight of the part it produced, cycling on a clock.
Reading `MaxInjectionPressure` twice a second apart gives two different numbers
because they are two different shots, and they covary the way a real process
does because they came from one.

Three behaviours that a constant-returning stub would get wrong:

- **A setpoint is approached, not granted.** Commanding a barrel temperature of
  250 °C does not make the next reading 250 °C; the value moves towards it over
  the following shots, the way a heater does. An agent that sets a value and
  reads it straight back sees a machine still moving.
- **Measured readings cannot be commanded.** Asking to set `PartWeight` is
  refused with the list of what *is* settable. A machine that pretends to obey
  is worse than one that says no.
- **Setpoints have an operating envelope.** 4000 °C is refused. A simulator that
  accepts anything teaches an agent that the machine accepts anything.

Quality is *predicted*, by a ridge regression fitted on the run at startup —
not looked up from the row the parameters came from. So "what would happen if I
raised the injection pressure" gets an answer that is wrong the way a model is
wrong. `R² ≈ 0.43`, `RMSE ≈ 0.036 g` on a part weighing about 59 g, and the
service reports both, so nobody has to guess how far to trust it.

Ridge rather than the source paper's gradient-boosted ensemble: the point is a
defensible answer, not a competitive benchmark score, and ridge is a dozen
lines of numpy whose coefficients can be read.

## Running it

```bash
# the machine
python -m a4s.machines.injection_molding.service          # http://localhost:5080

# model it in the AAS repository: one Operation per endpoint,
# each with an invocationDelegation qualifier pointing back at it
python -m a4s.machines.injection_molding.onboard --replace --sync

# then it is reachable like any other asset
aas op ls   https://example.com/ids/sm/imm_sim/Capability
aas op invoke https://example.com/ids/sm/imm_sim/Capability Read --arg name=MaxInjectionPressure
aas op invoke https://example.com/ids/sm/imm_sim/Capability PredictQuality
aas op invoke https://example.com/ids/sm/imm_sim/Capability Setpoint \
    --arg name=BarrelZone3 --arg value=255
```

`--seconds-per-shot` sets the clock; `--stopped` starts it idle.

## What it models in the AAS

| Submodel | Contents |
|---|---|
| `OperationalData` | 21 Properties, one per reading, each with its unit |
| `Capability` | 8 Operations, one per endpoint, each with `invocationDelegation` |

The Operations' declared input variables are **generated from the service's own
published contract** (`GET /openapi.json`), not written by hand. A declared
signature drifting from the service it delegates to is a defect this repository
already contains — `ProcessClassifyDefect` declares `laser_power` where its
service wants `power` — and generating one from the other is how that is not
repeated here.

Four Operations carry `Qualifier/type = "movesMachine"`: `Start`, `Stop`,
`Setpoint`, `SetpointClear`. That is not part of any IDTA template. It exists so
an approval gate reads a property of the *modelled capability* rather than
guessing from a name, which is the kind of thing that works until it does not.

## Two things found by building this

**An Operation invocation is an RPC, so it POSTs.** The first version served
`/status` and `/model` on `GET` alone — they read nothing — and `aas op invoke`
could not call them. The service was wrong, not the CLI: an Operation is a
procedure call, not a REST resource. Every endpoint now answers `POST`, and the
read-only ones also answer `GET` so a person with a browser can look.

**`/predict-quality` became the idShort `Predict-quality`,** which AASd-002
forbids. Caught by running `aas validate` against the harness's own generated
output — the validator earning its place on something this repository produced
rather than something it was handed.

## Data

Two scalar files of the published dataset are vendored here (≈600 KB). The
time-series companions (24–41 MB each) and the HDF5 (88 MB) are not: nothing in
this simulation reads them.

> Bogedale, L.; Doerfel, S.; Schrodt, A.; Heim, H.-P. *Online Prediction of
> Molded Part Quality in the Injection Molding Process Using High-Resolution
> Time Series.* Polymers 2023, 15, 978.
> <https://doi.org/10.3390/polym15040978>

Licensed CC-BY 4.0. See [`data/SOURCE.md`](data/SOURCE.md).

Column names in the source are German; `machine.COLUMNS` maps them to English
idShorts, because AASd-002 restricts an idShort to `[A-Za-z][A-Za-z0-9_]*` and
an agent reading `zylinderheizzone_1` learns less than one reading
`BarrelZone1`.
