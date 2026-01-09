# web_sim.py
"""
FastAPI + SimPy 3D Print Farm Web Visualization
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import json
import random
import simpy

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config_SimPy as config
from base_Customer import Customer
from manager import Manager
from log_SimPy import Logger
from config_SimPy import SIM_TIME
import base_Customer as base_customer
import manager as manager_mod
import specialized_Process as specialized_process
import specialized_Processor as specialized_processor
import log_SimPy as log_simpy


app = FastAPI(
    title="3D Print Farm WebSim",
    version="1.4.0",
    description="SimPy 기반 3D 프린팅 팜 웹 시각화",
)

ALLOWED_OVERRIDES = {
    "NUM_MACHINES_BUILD",
    "NUM_MACHINES_WASH1",
    "NUM_MACHINES_WASH2",
    "NUM_MACHINES_DRY1",
    "NUM_MACHINES_DRY2",
    "NUM_MACHINES_UV",
    "NUM_WORKERS_SUPPORT",
    "NUM_WORKERS_IN_INSPECT",
    "CAPACITY_MACHINE_BUILD",
    "CAPACITY_MACHINE_WASH1",
    "CAPACITY_MACHINE_WASH2",
    "CAPACITY_MACHINE_DRY1",
    "CAPACITY_MACHINE_DRY2",
    "CAPACITY_MACHINE_UV",
    "PROC_TIME_BUILD",
    "PROC_TIME_WASH1",
    "PROC_TIME_WASH2",
    "PROC_TIME_DRY1",
    "PROC_TIME_DRY2",
    "PROC_TIME_SUPPORT",
    "PROC_TIME_INSPECT",
    "PROC_TIME_UV",
    "DEFECT_RATE_PROC_BUILD",
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
    "ORDER_ARRIVAL_MODE",
    "CUST_ORDER_CYCLE",
    "ORDER_INTERVAL",
    "ORDER_COUNT",
    "ORDER_CONTINUOUS_CHECK_INTERVAL",
    "ORDER_NUM_PATIENTS_MIN",
    "ORDER_NUM_PATIENTS_MAX",
    "ORDER_NUM_ITEMS_MIN",
    "ORDER_NUM_ITEMS_MAX",
}

CONFIG_DEFAULTS = {key: getattr(config, key) for key in ALLOWED_OVERRIDES}
UI_DEFAULTS = {**CONFIG_DEFAULTS, "SIM_TIME": SIM_TIME}

MODULES_WITH_CONFIG = [
    config,
    base_customer,
    manager_mod,
    specialized_process,
    specialized_processor,
    log_simpy,
]


def _set_module_attr(module, key, value) -> None:
    if hasattr(module, key):
        setattr(module, key, value)


def reset_config_defaults() -> None:
    for key, value in CONFIG_DEFAULTS.items():
        for module in MODULES_WITH_CONFIG:
            _set_module_attr(module, key, value)


def apply_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
    reset_config_defaults()
    sanitized = {}

    for key, value in (overrides or {}).items():
        if key not in ALLOWED_OVERRIDES:
            continue
        sanitized[key] = value
        for module in MODULES_WITH_CONFIG:
            _set_module_attr(module, key, value)

    dist = getattr(config, "DIST_BETWEEN_STATIONS")
    speed_amr = getattr(config, "SPEED_AMR_M_PER_MIN")
    speed_worker = getattr(config, "SPEED_WORKER_M_PER_MIN")
    if speed_amr:
        new_amr_time = dist / speed_amr
        for module in MODULES_WITH_CONFIG:
            _set_module_attr(module, "PROC_TIME_MOVE_AMR", new_amr_time)
    if speed_worker:
        new_manual_time = dist / speed_worker
        for module in MODULES_WITH_CONFIG:
            _set_module_attr(module, "PROC_TIME_MOVE_MANUAL", new_manual_time)

    return sanitized


def get_config_snapshot() -> Dict[str, Any]:
    return {key: getattr(config, key) for key in CONFIG_DEFAULTS}


class SimRequest(BaseModel):
    sim_time: float = SIM_TIME
    seed: int = 42
    overrides: Dict[str, Any] = {}


def build_job_trace(processes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build a trace list for web animation from each process's completed_jobs.
    """
    trace: List[Dict[str, Any]] = []

    for proc_name, proc in processes.items():
        completed_jobs = getattr(proc, "completed_jobs", [])
        for job in completed_jobs:
            job_id = getattr(job, "id_job", None) or getattr(job, "job_id", None)
            if job_id is None:
                continue

            job_label = f"JOB-{job_id}"
            job_type = getattr(job, "job_type", None)
            plate_id = getattr(job, "build_plate_id", None)
            history = getattr(job, "processing_history", [])

            for step in history:
                s = step.get("start_time")
                e = step.get("end_time")
                if s is None or e is None:
                    continue

                stage = step.get("process", proc_name)
                resource = step.get("resource_name") or step.get("resource", None)

                trace.append(
                    {
                        "id": job_label,
                        "stage": stage,
                        "resource": resource,
                        "t0": float(s),
                        "t1": float(e),
                        "job_type": job_type,
                        "plate_id": plate_id,
                    }
                )

    trace.sort(key=lambda x: (x["id"], x["t0"]))
    return trace


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
    mover_count = getattr(config, "NUM_AMR", 1) if move_mode == "AMR" else getattr(config, "NUM_MANUAL_MOVERS", 1)
    amr_util = transport_time / (mover_count * sim_time) if sim_time > 0 and mover_count > 0 else None

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


def run_sim_3dfarm(sim_duration: float, seed: int = 42, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    applied_overrides = apply_overrides(overrides or {})
    random.seed(seed)

    env = simpy.Environment()
    logger = Logger(env)
    manager = Manager(env, logger=logger)

    Customer(env, manager, logger)
    env.run(until=sim_duration)

    stats = manager.collect_statistics()
    processes = manager.get_processes()
    job_trace = build_job_trace(processes)
    plate_events = [e for e in logger.web_events if e.get("type") == "plate"]
    order_events = [e for e in logger.web_events if e.get("type") == "order"]
    job_events = [e for e in logger.web_events if e.get("type") == "job"]
    kpis = compute_kpis(manager, logger, sim_duration)

    return {
        "stats": stats,
        "kpis": kpis,
        "config_used": get_config_snapshot(),
        "overrides": applied_overrides,
        "job_trace": job_trace,
        "plate_events": plate_events,
        "order_events": order_events,
        "job_events": job_events,
        "sim_time": sim_duration,
        "seed": seed,
    }


HTML_TEMPLATE = Path(__file__).with_name("web_template.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    defaults_json = json.dumps(UI_DEFAULTS)
    html = HTML_TEMPLATE.replace("__DEFAULTS_JSON__", defaults_json)
    return HTMLResponse(html)


@app.post("/simulate")
async def simulate(req: SimRequest):
    out = run_sim_3dfarm(req.sim_time, req.seed, req.overrides)
    return JSONResponse({"ok": True, "results": out})
