from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.ibm_bridge import env_instance, load_dotenv_if_available, require_runtime


def discover_backends(channel: str, instance: str | None = None) -> dict[str, object]:
    qiskit_runtime_service, _, _ = require_runtime()
    service = qiskit_runtime_service(channel=channel, instance=instance)
    rows = []
    for backend in service.backends(simulator=False, operational=True, instance=instance):
        status = backend.status()
        rows.append(
            {
                "name": backend.name,
                "num_qubits": getattr(backend, "num_qubits", None),
                "pending_jobs": status.pending_jobs,
                "operational": status.operational,
                "status_msg": status.status_msg,
            }
        )
    rows.sort(key=lambda item: (item["pending_jobs"], item["name"]))
    active_instance = service.active_instance() if hasattr(service, "active_instance") else None
    return {"channel": channel, "active_instance": active_instance, "instance_configured": bool(instance), "backends": rows}


def main() -> None:
    load_dotenv_if_available()
    parser = argparse.ArgumentParser(description="Discover accessible IBM Quantum backends for AEGIS.")
    parser.add_argument("--channel", default=os.environ.get("IBM_QUANTUM_CHANNEL", "ibm_quantum_platform"))
    parser.add_argument("--instance", default=env_instance(), help="Optional IBM Quantum Runtime instance CRN or service name.")
    parser.add_argument("--output", type=Path, default=Path("ibm_backend_inventory.json"))
    args = parser.parse_args()
    payload = discover_backends(args.channel, args.instance)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
