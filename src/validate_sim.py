import argparse
import importlib
import json
import random
import sys
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
    random.seed(seed)
    if hasattr(config, "RANDOM_SEED"):
        setattr(config, "RANDOM_SEED", seed)

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


_CONFIG_KEYS = [
    "NUM_MACHINES_BUILD",
    "CAPACITY_MACHINE_BUILD",
    "PROC_TIME_BUILD",
    "DEFECT_RATE_PROC_BUILD",
    "NUM_MACHINES_WASH1",
    "NUM_MACHINES_WASH2",
    "NUM_MACHINES_DRY1",
    "NUM_MACHINES_DRY2",
    "NUM_MACHINES_UV",
    "CAPACITY_MACHINE_WASH1",
    "CAPACITY_MACHINE_WASH2",
    "CAPACITY_MACHINE_DRY1",
    "CAPACITY_MACHINE_DRY2",
    "CAPACITY_MACHINE_UV",
    "PROC_TIME_WASH1",
    "PROC_TIME_WASH2",
    "PROC_TIME_DRY1",
    "PROC_TIME_DRY2",
    "PROC_TIME_UV",
    "PROC_TIME_SUPPORT",
    "PROC_TIME_INSPECT",
    "NUM_WORKERS_SUPPORT",
    "NUM_WORKERS_IN_INSPECT",
    "PALLET_SIZE_LIMIT",
    "BOX_SIZE",
    "INITIAL_NUM_BUILD_PLATES",
    "MAX_PRE_BUILD_PLATES",
    "MAX_POST_BUILD_PLATES",
    "POLICY_NUM_DEFECT_PER_JOB",
    "MOVE_MODE",
    "NUM_AMR",
    "NUM_MANUAL_MOVERS",
    "DIST_BETWEEN_STATIONS",
    "SPEED_AMR_M_PER_MIN",
    "SPEED_WORKER_M_PER_MIN",
    "PROC_TIME_MOVE_AMR",
    "PROC_TIME_MOVE_MANUAL",
    "CUST_ORDER_CYCLE",
    "ORDER_DUE_DATE",
    "ORDER_ARRIVAL_MODE",
    "ORDER_INTERVAL",
    "ORDER_COUNT",
    "ORDER_NUM_PATIENTS_MIN",
    "ORDER_NUM_PATIENTS_MAX",
    "ORDER_NUM_ITEMS_MIN",
    "ORDER_NUM_ITEMS_MAX",
]


_PATCH_MODULE_NAMES = [
    "base_Customer",
    "log_SimPy",
    "manager",
    "specialized_Process",
    "specialized_Processor",
]


def _snapshot_config(keys: List[str]) -> Dict[str, Any]:
    snapshot = {}
    for key in keys:
        if hasattr(config, key):
            snapshot[key] = getattr(config, key)
    return snapshot


def _apply_overrides(overrides: Dict[str, Any]) -> None:
    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)

    for mod_name in _PATCH_MODULE_NAMES:
        module = sys.modules.get(mod_name)
        if module is None:
            try:
                module = importlib.import_module(mod_name)
            except Exception:
                continue
        for key, value in overrides.items():
            if hasattr(module, key):
                setattr(module, key, value)


def _generate_random_overrides(rng: random.Random, sim_time: float) -> Dict[str, Any]:
    move_mode = rng.choice(["AMR", "MANUAL"])
    dist = rng.uniform(2.0, 10.0)
    speed_amr = rng.uniform(20.0, 60.0)
    speed_worker = rng.uniform(30.0, 90.0)
    proc_time_move_amr = dist / speed_amr
    proc_time_move_manual = dist / speed_worker

    num_build_plates = rng.randint(5, 20)
    pallet_size = rng.randint(30, 80)
    box_size = rng.randint(20, 60)

    cust_cycle = rng.randint(int(sim_time * 0.5), int(sim_time))
    order_mode = rng.choice(["continuous", "interval", "count"])
    if order_mode == "count":
        order_count = rng.randint(1, 6)
        order_interval = rng.randint(max(1, int(cust_cycle * 0.05)), max(2, int(cust_cycle * 0.2)))
    else:
        order_count = 0
        order_interval = rng.randint(max(1, int(cust_cycle * 0.05)), max(2, int(cust_cycle * 0.5)))

    patients_min = rng.randint(1, 6)
    patients_max = rng.randint(patients_min, max(patients_min, 8))
    items_min = rng.randint(20, 60)
    items_max = rng.randint(items_min, max(items_min, 90))

    overrides = {
        "NUM_MACHINES_BUILD": rng.randint(1, 8),
        "CAPACITY_MACHINE_BUILD": rng.randint(1, 3),
        "PROC_TIME_BUILD": rng.randint(300, 800),
        "DEFECT_RATE_PROC_BUILD": round(rng.uniform(0.0, 0.2), 3),
        "NUM_MACHINES_WASH1": rng.randint(1, 3),
        "NUM_MACHINES_WASH2": rng.randint(1, 3),
        "NUM_MACHINES_DRY1": rng.randint(1, 3),
        "NUM_MACHINES_DRY2": rng.randint(1, 3),
        "NUM_MACHINES_UV": rng.randint(1, 3),
        "CAPACITY_MACHINE_WASH1": rng.randint(1, 3),
        "CAPACITY_MACHINE_WASH2": rng.randint(1, 3),
        "CAPACITY_MACHINE_DRY1": rng.randint(1, 3),
        "CAPACITY_MACHINE_DRY2": rng.randint(1, 3),
        "CAPACITY_MACHINE_UV": rng.randint(1, 3),
        "PROC_TIME_WASH1": rng.randint(60, 180),
        "PROC_TIME_WASH2": rng.randint(60, 180),
        "PROC_TIME_DRY1": rng.randint(60, 180),
        "PROC_TIME_DRY2": rng.randint(60, 180),
        "PROC_TIME_UV": rng.randint(10, 40),
        "PROC_TIME_SUPPORT": rng.randint(15, 60),
        "PROC_TIME_INSPECT": rng.randint(15, 60),
        "NUM_WORKERS_SUPPORT": rng.randint(1, 3),
        "NUM_WORKERS_IN_INSPECT": rng.randint(1, 3),
        "PALLET_SIZE_LIMIT": pallet_size,
        "BOX_SIZE": box_size,
        "INITIAL_NUM_BUILD_PLATES": num_build_plates,
        "MAX_PRE_BUILD_PLATES": num_build_plates,
        "MAX_POST_BUILD_PLATES": num_build_plates,
        "POLICY_NUM_DEFECT_PER_JOB": rng.randint(5, 20),
        "MOVE_MODE": move_mode,
        "NUM_AMR": rng.randint(1, 3),
        "NUM_MANUAL_MOVERS": rng.randint(1, 3),
        "DIST_BETWEEN_STATIONS": round(dist, 2),
        "SPEED_AMR_M_PER_MIN": round(speed_amr, 2),
        "SPEED_WORKER_M_PER_MIN": round(speed_worker, 2),
        "PROC_TIME_MOVE_AMR": proc_time_move_amr,
        "PROC_TIME_MOVE_MANUAL": proc_time_move_manual,
        "CUST_ORDER_CYCLE": cust_cycle,
        "ORDER_DUE_DATE": cust_cycle,
        "ORDER_ARRIVAL_MODE": order_mode,
        "ORDER_INTERVAL": order_interval,
        "ORDER_COUNT": order_count,
        "ORDER_NUM_PATIENTS_MIN": patients_min,
        "ORDER_NUM_PATIENTS_MAX": patients_max,
        "ORDER_NUM_ITEMS_MIN": items_min,
        "ORDER_NUM_ITEMS_MAX": items_max,
    }

    return overrides


def run_validation_suite(sim_time: float, base_seed: int, experiments: int) -> int:
    original = _snapshot_config(_CONFIG_KEYS)
    rng = random.Random(base_seed)
    failures = 0

    for idx in range(experiments):
        overrides = _generate_random_overrides(rng, sim_time)
        run_seed = rng.randint(1, 1_000_000_000)
        _apply_overrides(overrides)

        print("\n========================================")
        print(f"Experiment {idx + 1}/{experiments}")
        print(f"  seed: {run_seed}")
        print(f"  move_mode: {overrides['MOVE_MODE']}")
        print(f"  build: machines={overrides['NUM_MACHINES_BUILD']}, "
              f"capacity={overrides['CAPACITY_MACHINE_BUILD']}, "
              f"time={overrides['PROC_TIME_BUILD']}")
        print(f"  wash/dry/uv machines: "
              f"{overrides['NUM_MACHINES_WASH1']}/"
              f"{overrides['NUM_MACHINES_WASH2']}/"
              f"{overrides['NUM_MACHINES_DRY1']}/"
              f"{overrides['NUM_MACHINES_DRY2']}/"
              f"{overrides['NUM_MACHINES_UV']}")
        print(f"  order: mode={overrides['ORDER_ARRIVAL_MODE']}, "
              f"cycle={overrides['CUST_ORDER_CYCLE']}, "
              f"patients={overrides['ORDER_NUM_PATIENTS_MIN']}-"
              f"{overrides['ORDER_NUM_PATIENTS_MAX']}, "
              f"items={overrides['ORDER_NUM_ITEMS_MIN']}-"
              f"{overrides['ORDER_NUM_ITEMS_MAX']}")

        result = run_validation(sim_time, run_seed)
        if result != 0:
            failures += 1

        _apply_overrides(original)

    print("\n========================================")
    print(f"Experiments: {experiments}")
    print(f"Failures: {failures}")
    print("RESULT: OK" if failures == 0 else "RESULT: FAIL (see per-experiment issues)")

    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate KPIs and event calendar.")
    parser.add_argument("--sim-time", type=float, default=float(config.SIM_TIME))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--experiments", type=int, default=30)
    parser.add_argument("--fail-exit", action="store_true")
    parser.add_argument("--config-overrides", type=str, default="")
    args = parser.parse_args()

    if args.config_overrides:
        overrides = json.loads(args.config_overrides)
        _apply_overrides({key: value for key, value in overrides.items() if hasattr(config, key)})

    if args.experiments > 1:
        exit_code = run_validation_suite(args.sim_time, args.seed, args.experiments)
    else:
        exit_code = run_validation(args.sim_time, args.seed)
    if args.fail_exit:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
