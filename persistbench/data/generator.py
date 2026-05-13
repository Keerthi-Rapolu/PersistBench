"""Synthetic replay trace generator (SLIS v1).

Design ref: DESIGN_DOC.md section 32.6

Reads a scenario YAML and produces a JSONL replay trace -- one TurnRecord
per line -- that the replay engine feeds to the agent backend.
No LLM calls are made during generation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import yaml

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
PROBES_DIR    = Path(__file__).parent.parent / "probes"
SCENARIOS_DIR = Path(__file__).parent.parent.parent / "scenarios"
TRACES_DIR    = Path(__file__).parent.parent.parent / "results" / "traces"


@dataclass
class TurnRecord:
    session_id:             int
    turn_id:                int
    role:                   str
    content:                str
    content_hash:           str
    is_benign:              bool
    is_trigger:             bool
    is_probe:               bool
    fragment_id:            Optional[str]
    probe_id:               Optional[str]
    expected_memory_effect: Optional[str]   # create | reinforce | none


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def load_scenario(yaml_path: Path) -> dict:
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_templates(domain: str) -> list[str]:
    path = TEMPLATES_DIR / domain / "turns.jsonl"
    contents = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            contents.append(json.loads(line)["content"])
    if len(contents) < 10:
        raise ValueError(
            f"Domain '{domain}' has only {len(contents)} templates -- need >= 10"
        )
    return contents


def _load_probes(domain: str) -> list[dict]:
    path = PROBES_DIR / f"{domain}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    probes = data["probes"]
    if len(probes) < 10:
        raise ValueError(
            f"Domain '{domain}' has only {len(probes)} probes -- need >= 10 for valid BDI"
        )
    return probes


def generate_session(
    scenario: dict,
    session_id: int,
    rng: random.Random,
    templates: list[str],
    probes: list[dict],
) -> list[TurnRecord]:
    turns: list[TurnRecord] = []
    turn_id = 0

    attack = scenario.get("attack") or {}
    fragments_this_session = [
        f for f in attack.get("fragments", []) if f["plant_session"] == session_id
    ]
    trigger = attack.get("trigger") or {}
    is_trigger_session = bool(trigger) and trigger.get("session") == session_id
    is_probe_session = session_id in scenario.get("probe_sessions", [])

    benign_count = scenario.get("benign_turns_per_session", 4)
    pool = list(templates)
    rng.shuffle(pool)
    sampled = pool[:min(benign_count, len(pool))]

    # Benign turns first
    for content in sampled:
        turn_id += 1
        turns.append(TurnRecord(
            session_id=session_id, turn_id=turn_id, role="user",
            content=content, content_hash=_sha256(content),
            is_benign=True, is_trigger=False, is_probe=False,
            fragment_id=None, probe_id=None,
            expected_memory_effect="none",
        ))

    # Adversarial fragment turns (mid-session)
    for frag in fragments_this_session:
        turn_id += 1
        turns.append(TurnRecord(
            session_id=session_id, turn_id=turn_id, role="user",
            content=frag["content"], content_hash=_sha256(frag["content"]),
            is_benign=False, is_trigger=False, is_probe=False,
            fragment_id=frag["id"], probe_id=None,
            expected_memory_effect="create",
        ))

    # Trigger turn (end of attack) — skipped for benign-control scenarios
    if is_trigger_session and trigger:
        turn_id += 1
        turns.append(TurnRecord(
            session_id=session_id, turn_id=turn_id, role="user",
            content=trigger["query"], content_hash=_sha256(trigger["query"]),
            is_benign=False, is_trigger=True, is_probe=False,
            fragment_id=None, probe_id=None,
            expected_memory_effect="none",
        ))

    # Probe turns (always last so they see the session's full memory state)
    if is_probe_session:
        for probe in probes:
            turn_id += 1
            turns.append(TurnRecord(
                session_id=session_id, turn_id=turn_id, role="user",
                content=probe["query"], content_hash=_sha256(probe["query"]),
                is_benign=False, is_trigger=False, is_probe=True,
                fragment_id=None, probe_id=probe["probe_id"],
                expected_memory_effect="none",
            ))

    return turns


def generate_trace(scenario: dict) -> list[TurnRecord]:
    """Generate the full replay trace for a scenario.

    Deterministic: the same scenario YAML always produces the same trace.
    """
    rng = random.Random(scenario["seed"])
    templates = _load_templates(scenario["domain"])
    probes = _load_probes(scenario["domain"])

    all_turns: list[TurnRecord] = []
    for sid in range(1, scenario["session_count"] + 1):
        all_turns.extend(
            generate_session(scenario, sid, rng, templates, probes)
        )
    return all_turns


def write_trace(trace: list[TurnRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for turn in trace:
            f.write(json.dumps(asdict(turn)) + "\n")


def load_trace(trace_path: Path) -> list[TurnRecord]:
    turns = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            turns.append(TurnRecord(**json.loads(line)))
    return turns


def _default_output(scenario: dict, run_id: str) -> Path:
    return TRACES_DIR / scenario["scenario_id"] / f"{run_id}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a PersistBench replay trace from a scenario YAML."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", type=Path,
                       help="Path to a single scenario YAML file")
    group.add_argument("--suite", choices=["SBMP", "TSCC", "CACP"],
                       help="Generate traces for all scenarios in a suite")
    parser.add_argument("--output", type=Path,
                        help="Output JSONL path (single-scenario mode only)")
    parser.add_argument("--output-dir", type=Path, default=TRACES_DIR,
                        help="Output directory (suite mode, default: results/traces/)")
    parser.add_argument("--run-id", default="run-001",
                        help="Run ID embedded in the output filename")
    args = parser.parse_args()

    if args.scenario:
        scenario = load_scenario(args.scenario)
        trace = generate_trace(scenario)
        out = args.output or _default_output(scenario, args.run_id)
        write_trace(trace, out)
        print(f"Wrote {len(trace)} turns -> {out}")
    else:
        suite_dir = SCENARIOS_DIR / args.suite.lower()
        yamls = sorted(suite_dir.glob("*.yaml"))
        if not yamls:
            print(f"No YAML files found in {suite_dir}")
            return
        for yf in yamls:
            scenario = load_scenario(yf)
            trace = generate_trace(scenario)
            out = args.output_dir / scenario["scenario_id"] / f"{args.run_id}.jsonl"
            write_trace(trace, out)
            print(f"  {scenario['scenario_id']}: {len(trace)} turns -> {out}")


if __name__ == "__main__":
    main()
