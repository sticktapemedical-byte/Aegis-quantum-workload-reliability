# IBM Quantum Bridge Setup

The IBM bridge is optional. The core AEGIS simulator remains runnable with the Python standard library.

## Security Boundary

Do not commit IBM Quantum tokens. The repository ignores `.env` and generated IBM bridge result files.

Recommended local token setup:

1. Copy `.env.example` to `.env`.
2. Put your token in `.env` as `IBM_QUANTUM_TOKEN=...`.
3. If IBM Quantum shows an instance CRN or service name, put it in `.env` as `IBM_QUANTUM_INSTANCE=...`.
4. Run `python examples/ibm_bridge.py --save-account`.

The save step reads the token and optional instance from local environment storage and calls `QiskitRuntimeService.save_account(...)`.

## Install Optional Dependencies

`python -m pip install -r requirements-qiskit.txt`

## Local Hardware-Realistic Smoke Test

Run the fake IBM backend first. It does not use cloud queue time:

`python examples/ibm_bridge.py --shots 256 --output ibm_bridge_fake_result.json`

Expected output includes:

- backend name such as `fake_osaka`
- counts histogram
- raw GHZ error rate
- AEGIS `q_conf`
- governance states
- 176-bit `.QOM` compact payload
- Merkle root

## Real Hardware Run

Real hardware jobs can wait in IBM's public queue. Start small:

`python examples/ibm_bridge.py --real --shots 1024 --output ibm_bridge_result.json`

Optional backend pin:

`python examples/ibm_bridge.py --real --backend ibm_brisbane --shots 1024`

Optional idle-delay stress test:

`python examples/ibm_bridge.py --real --backend ibm_marrakesh --shots 128 --delay-ms 1 --output ibm_marrakesh_128_delay.json`

If no backend is specified, the bridge requests the least busy operational non-simulator backend with at least four qubits.

## What To Watch

- Queue wait may take minutes or longer.
- Keep `--shots` modest for first runs.
- Do not run real hardware from the live monitor loop unless the bridge is moved to an async job queue.
- Treat all hardware metrics as external readout telemetry mapped into the simulation framework, not as proof of production deployment.
