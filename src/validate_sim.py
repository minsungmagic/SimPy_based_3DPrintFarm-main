import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

import simpy

import config_SimPy as config
from base_Customer import Customer
from log_SimPy import Logger
from manager import Manager


def _job_cycle_time(job) -> Optional[float]:
    history = getattr(job, "processing_history", []) or []
    starts = [s.get("start_time") for s in history if s.get("start_time") is not None]
    ends = [s.get("end_time") for s in history if s.get("end_time") is not None]
    if not starts or not ends:
        return None
    return max(ends) - min(starts)


def _process_capacity(proc) -> int:
    if proc is None:
        return 0
    total = 0
    for processor in getattr(proc, "list_processors", []):
        if getattr(processor, "type_processor", "") == "Machine":
            total += int(getattr(processor, "capacity_jobs", 1))
        else:
            total += 1
    return total


def compute_kpis(manager: Manager, logger: Logger, sim_time: float) -> Dict[str, Any]:
    processes = manager.get_processes()
    all_jobs = []
    for proc in processes.values():
        if proc:
            all_jobs.extend(proc.completed_jobs)

    unique_jobs = list({job.id_job: job for job in all_jobs}.values())
    uv_jobs = getattr(manager.proc_uv, "completed_jobs", []) if manager.proc_uv else []

    cycle_times = [ct for job in uv_jobs if (ct := _job_cycle_time(job)) is not None]
    avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else None

    order_events = [e for e in logger.web_events if e.get("type") == "order"]
    orders_created = len([e for e in order_events if e.get("stage") == "created"])

    busy_by_process: Dict[str, float] = {}
    transport_time = 0.0
    transport_moves = 0
    for job in unique_jobs:
        history = getattr(job, "processing_history", []) or []
        for step in history:
            end = step.get("end_time")
            start = step.get("start_time")
            if end is None or start is None:
                continue
            duration = float(end - start)
            proc_name = step.get("process") or "Unknown"
            busy_by_process[proc_name] = busy_by_process.get(proc_name, 0.0) + duration
            if proc_name == "Transport":
                transport_time += duration
                transport_moves += 1

    process_utilization = {}
    for proc_name, proc in processes.items():
        capacity = _process_capacity(proc)
        busy = busy_by_process.get(getattr(proc, "name_process", proc_name), 0.0)
        if capacity > 0 and sim_time > 0:
            process_utilization[proc_name] = busy / (capacity * sim_time)
        else:
            process_utilization[proc_name] = None

    move_mode = str(getattr(config, "MOVE_MODE", "AMR")).upper()
    mover_count = (
        getattr(config, "NUM_AMR", 1)
        if move_mode == "AMR"
        else getattr(config, "NUM_MANUAL_MOVERS", 1)
    )
    amr_util = (
        transport_time / (mover_count * sim_time)
        if sim_time > 0 and mover_count > 0
        else None
    )

    throughput_days = sim_time / (24 * 60) if sim_time > 0 else 0
    jobs_per_day = len(uv_jobs) / throughput_days if throughput_days > 0 else None
    items_per_day = manager.final_storage.total_items / throughput_days if throughput_days > 0 else None

    return {
        "orders_created": orders_created,
        "uv_completed_jobs": len(uv_jobs),
        "final_items": manager.final_storage.total_items,
        "avg_cycle_time_min": avg_cycle,
        "jobs_per_day": jobs_per_day,
        "items_per_day": items_per_day,
        "transport_utilization": amr_util,
        "transport_moves": transport_moves,
        "process_utilization": process_utilization,
    }


def _check_kpis(kpis: Dict[str, Any]) -> List[str]:
    issues = []
    for key in ("orders_created", "uv_completed_jobs", "final_items", "transport_moves"):
        value = kpis.get(key)
        if value is None:
            issues.append(f"KPI {key} is None")
        elif value < 0:
            issues.append(f"KPI {key} is negative: {value}")

    for key in ("avg_cycle_time_min", "jobs_per_day", "items_per_day", "transport_utilization"):
        value = kpis.get(key)
        if value is not None and value < 0:
            issues.append(f"KPI {key} is negative: {value}")

    process_util = kpis.get("process_utilization", {})
    if isinstance(process_util, dict):
        for proc_name, util in process_util.items():
            if util is None:
                continue
            if util < 0 or util > 1.5:
                issues.append(f"Process utilization {proc_name} out of range: {util}")
    else:
        issues.append("KPI process_utilization is not a dict")

    return issues


def _check_event_schema(events: List[Dict[str, Any]]) -> List[str]:
    issues = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            issues.append(f"Event[{idx}] is not a dict")
            continue

        if "time" not in ev:
            issues.append(f"Event[{idx}] missing time")
        elif not isinstance(ev.get("time"), (int, float)):
            issues.append(f"Event[{idx}] time is not numeric: {ev.get('time')}")

        ev_type = ev.get("type")
        if ev_type is None:
            issues.append(f"Event[{idx}] missing type")
            continue

        if ev_type == "order":
            for field in ("order_id", "stage"):
                if field not in ev:
                    issues.append(f"Order event[{idx}] missing {field}")
        elif ev_type == "job":
            for field in ("job_id", "stage"):
                if field not in ev:
                    issues.append(f"Job event[{idx}] missing {field}")
        elif ev_type == "plate":
            for field in ("plate_id", "state"):
                if field not in ev:
                    issues.append(f"Plate event[{idx}] missing {field}")
        elif ev_type == "final":
            for field in ("job_id", "num_items", "total_items"):
                if field not in ev:
                    issues.append(f"Final event[{idx}] missing {field}")

    return issues


def _check_order_timeline(events: List[Dict[str, Any]]) -> List[str]:
    issues = []
    order_events: Dict[Any, List[Tuple[float, str]]] = {}
    for ev in events:
        if ev.get("type") != "order":
            continue
        order_id = ev.get("order_id")
        stage = ev.get("stage")
        time = ev.get("time", 0.0)
        order_events.setdefault(order_id, []).append((float(time), str(stage)))

    for order_id, stages in order_events.items():
        stages.sort()
        stage_names = [s for _, s in stages]
        if "sent_to_manager" in stage_names and "created" not in stage_names:
            issues.append(f"Order {order_id} sent_to_manager without created")
        if stage_names.count("created") > 1:
            issues.append(f"Order {order_id} has multiple created events")

    return issues


def _check_plate_transitions(events: List[Dict[str, Any]]) -> List[str]:
    issues = []
    allowed = {
        "empty": {"loaded"},
        "loaded": {"built"},
        "built": {"empty"},
    }
    plate_events: Dict[Any, List[Tuple[float, str]]] = {}
    for ev in events:
        if ev.get("type") != "plate":
            continue
        plate_id = ev.get("plate_id")
        state = str(ev.get("state"))
        time = float(ev.get("time", 0.0))
        plate_events.setdefault(plate_id, []).append((time, state))

    for plate_id, states in plate_events.items():
        states.sort()
        for (_, prev), (t_curr, curr) in zip(states, states[1:]):
            if prev == curr:
                continue
            if prev not in allowed or curr not in allowed.get(prev, set()):
                issues.append(
                    f"Plate {plate_id} invalid transition {prev} -> {curr} at {t_curr}"
                )
    return issues


def _check_job_events_vs_history(
    events: List[Dict[str, Any]], processes: Dict[str, Any]
) -> List[str]:
    issues = []
    job_histories: Dict[Any, List[Tuple[float, float]]] = {}
    for proc in processes.values():
        if not proc:
            continue
        for job in getattr(proc, "completed_jobs", []):
            history = getattr(job, "processing_history", []) or []
            spans = []
            for step in history:
                s = step.get("start_time")
                e = step.get("end_time")
                if s is None or e is None:
                    continue
                spans.append((float(s), float(e)))
            if spans:
                job_histories[job.id_job] = spans

    for ev in events:
        if ev.get("type") != "job":
            continue
        stage = ev.get("stage")
        if stage not in (
            "build_completed",
            "plate_disassembled_at_inspect",
            "box_created",
            "rework_created",
        ):
            continue
        job_id = ev.get("job_id")
        spans = job_histories.get(job_id)
        if not spans and stage in ("build_completed", "plate_disassembled_at_inspect"):
            issues.append(f"Job event for unknown job history: job_id={job_id}, stage={stage}")

    return issues


def run_validation(sim_time: float, seed: int) -> int:
    env = simpy.Environment()
    logger = Logger(env)
    manager = Manager(env, logger=logger)
    Customer(env, manager, logger)

    env.run(until=sim_time)

    kpis = compute_kpis(manager, logger, sim_time)
    processes = manager.get_processes()
    events = list(logger.web_events)

    issues: List[str] = []
    issues.extend(_check_kpis(kpis))
    issues.extend(_check_event_schema(events))
    issues.extend(_check_order_timeline(events))
    issues.extend(_check_plate_transitions(events))
    issues.extend(_check_job_events_vs_history(events, processes))

    print("Validation summary")
    print(f"  sim_time: {sim_time}")
    print(f"  seed: {seed}")
    print(f"  events: {len(events)}")
    print(f"  issues: {len(issues)}")

    if issues:
        print("\nIssues")
        for issue in issues:
            print(f"- {issue}")

    print("\nRESULT: OK" if not issues else "\nRESULT: FAIL (see issues above)")

    return 1 if issues else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate KPIs and event calendar.")
    parser.add_argument("--sim-time", type=float, default=float(config.SIM_TIME))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fail-exit", action="store_true")
    parser.add_argument("--config-overrides", type=str, default="")
    args = parser.parse_args()

    if args.config_overrides:
        overrides = json.loads(args.config_overrides)
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

    exit_code = run_validation(args.sim_time, args.seed)
    if args.fail_exit:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
