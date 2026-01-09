# log_SimPy.py
import pandas as pd
import plotly.express as px
import plotly.figure_factory as ff
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np
from config_SimPy import *


class Logger:
    def __init__(self, env):
        # Logger stores only env and does not depend on manager
        self.env = env
        self.event_logs = []  # Event log store

        # Event log for web visualization
        self.web_events = []

    def log_web_event(self, event_type, payload: dict):
        """
        Event log for web visualization.
        event_type: 'order', 'job', 'plate', etc.
        payload: free-form dict (time, id, stage, job_type, plate_state, etc.)
        """
        rec = {
            "time": float(self.env.now),
            "type": event_type,
            **payload,
        }
        self.web_events.append(rec)

    def log_event(self, event_type, message):
        """Log an event with a timestamp"""
        if EVENT_LOGGING:
            current_time = self.env.now  # minutes (float)
            days = int(current_time // (24 * 60))
            hours = int((current_time % (24 * 60)) // 60)
            minutes = int(current_time % 60)
            # Convert fractional minutes to seconds
            seconds = int((current_time - int(current_time)) * 60)

            timestamp = f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
            print(f"[{timestamp}] [{current_time:.2f}] | {event_type}: {message}")

    def collect_statistics(self, processes):
        """Collect statistics from the simulation

        Args:
            processes: Dictionary containing all process objects
                (e.g., {'build': proc_build, 'wash1': proc_wash1, ...})
        """
        stats = {}

        # Extract processes (keys must match Manager.get_processes())
        proc_build = processes.get("build")
        proc_wash1 = processes.get("wash1")
        proc_dry1 = processes.get("dry1")
        proc_support = processes.get("support")
        proc_inspect = processes.get("inspect")
        proc_wash2 = processes.get("wash2")
        proc_dry2 = processes.get("dry2")
        proc_uv = processes.get("uv")

        # Available processes for statistics
        available_processes = []
        for proc_name, proc in processes.items():
            if proc:
                available_processes.append(proc)

        # Completed jobs
        completed_jobs = []
        for proc in available_processes:
            completed_jobs.extend(proc.completed_jobs)

        # Remove duplicates by job ID
        unique_jobs = {}
        for job in completed_jobs:
            unique_jobs[job.id_job] = job

        completed_jobs = list(unique_jobs.values())

        # Basic statistics
        stats["total_completed_jobs"] = len(completed_jobs)

        # Process specific statistics
        process_ids = [proc.name_process for proc in available_processes]
        process_jobs = {proc_id: [] for proc_id in process_ids}

        for job in completed_jobs:
            process_id = job.workstation.get("Process")
            if process_id in process_jobs:
                process_jobs[process_id].append(job)

        # Analyze waiting and processing times
        for process_id, jobs in process_jobs.items():
            if jobs:
                # Waiting time statistics
                waiting_times = [
                    (job.time_waiting_end - job.time_waiting_start)
                    for job in jobs
                    if job.time_waiting_end is not None and job.time_waiting_start is not None
                ]

                if waiting_times:
                    stats[f"{process_id}_waiting_time_avg"] = sum(waiting_times) / len(waiting_times)
                    stats[f"{process_id}_waiting_time_std"] = (
                        np.std(waiting_times) if len(waiting_times) > 1 else 0
                    )

                # Processing time statistics
                processing_times = [
                    (job.time_processing_end - job.time_processing_start)
                    for job in jobs
                    if job.time_processing_end is not None and job.time_processing_start is not None
                ]

                if processing_times:
                    stats[f"{process_id}_processing_time_avg"] = sum(processing_times) / len(processing_times)
                    stats[f"{process_id}_processing_time_std"] = (
                        np.std(processing_times) if len(processing_times) > 1 else 0
                    )

        # Queue length statistics
        for proc in available_processes:
            if hasattr(proc, "job_store") and hasattr(proc.job_store, "queue_length_history"):
                if proc.job_store.queue_length_history:
                    # Calculate average queue length
                    times = [t for t, _ in proc.job_store.queue_length_history]
                    lengths = [l for _, l in proc.job_store.queue_length_history]

                    if times and lengths:
                        # Add final point if needed
                        if times[-1] < self.env.now:
                            times.append(self.env.now)
                            lengths.append(lengths[-1])

                        # Calculate time-weighted average
                        weighted_sum = 0
                        for i in range(1, len(times)):
                            weighted_sum += lengths[i - 1] * (times[i] - times[i - 1])

                        avg_length = weighted_sum / self.env.now if self.env.now > 0 else 0
                        stats[f"{proc.name_process}_avg_queue_length"] = avg_length

        # Count defective items if inspection process exists
        if proc_inspect and hasattr(proc_inspect, "defective_items"):
            stats["total_defects"] = len(proc_inspect.defective_items)

        return stats

    def visualize_statistics(self, stats, processes):
        """
        Visualization:
          - Modified to show only the Gantt chart as requested
        """
        figures = {}

        if GANTT_CHART_ENABLED:
            figures["gantt"] = self.visualize_gantt(processes)

        # Show only Gantt
        for name, fig in figures.items():
            if fig is not None:
                fig.show()

        return figures

    # The next two functions are currently unused but kept for possible future use
    def visualize_process_statistics(self, stats, stat_type):
        """(Currently unused) Visualize process statistics (waiting time, processing time)"""
        if not VIS_STAT_ENABLED:
            return None

        # Find all processes in stats
        processes = set()
        for key in stats.keys():
            if f"_{stat_type}_avg" in key:
                proc_name = key.split("_")[0]
                processes.add(proc_name)

        processes = sorted(list(processes))

        # Extract relevant statistics
        avg_values = []
        std_values = []

        for process in processes:
            avg_key = f"{process}_{stat_type}_avg"
            std_key = f"{process}_{stat_type}_std"

            if avg_key in stats:
                avg_values.append(stats[avg_key])
                std_values.append(stats.get(std_key, 0))
            else:
                avg_values.append(0)
                std_values.append(0)

        # Create bar chart with error bars
        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                x=processes,
                y=avg_values,
                error_y=dict(type="data", array=std_values, visible=True),
                name="Average",
            )
        )

        fig.update_layout(
            title=f"Process {stat_type.replace('_', ' ').title()}",
            xaxis_title="Process",
            yaxis_title=f"{stat_type.replace('_', ' ').title()} (minutes)",
        )

        return fig

    def visualize_queue_lengths(self, processes):
        """(Currently unused) Visualize queue lengths over time"""
        if not VIS_STAT_ENABLED:
            return None

        fig = go.Figure()

        for proc_name, proc in processes.items():
            if proc and hasattr(proc, "job_store") and hasattr(proc.job_store, "queue_length_history"):
                if proc.job_store.queue_length_history:
                    # Keep times in minutes for x-axis
                    times = [t for t, _ in proc.job_store.queue_length_history]
                    lengths = [l for _, l in proc.job_store.queue_length_history]

                    fig.add_trace(
                        go.Scatter(x=times, y=lengths, mode="lines", name=proc.name_process)
                    )

        fig.update_layout(
            title="Queue Lengths Over Time",
            xaxis_title="Simulation Time (minutes)",
            yaxis_title="Queue Length",
            legend_title="Process",
        )

        return fig

    def visualize_gantt(self, processes):
        """Create slot-based Gantt chart - maintaining job slot consistency"""
        if not GANTT_CHART_ENABLED:
            return None

        # === 1) Collect resource list ===
        all_resources = self.get_all_resources(processes)
        resource_names = [r["name"] for r in all_resources]

        # === 2) Determine process order by resource name prefix ===
        def get_proc_order_by_name(name: str) -> int:
            if name.startswith("3DPrinter"):
                return 0
            if name.startswith("Washer1"):
                return 1
            if name.startswith("Dryer1"):
                return 2
            if name.startswith("SupportRemover"):
                return 3
            if name.startswith("Inspector"):
                return 4
            if name.startswith("Washer2"):
                return 5
            if name.startswith("Dryer2"):
                return 6
            if name.startswith("UV"):
                return 7
            if name.startswith("AMR_"):
                return 8
            if name.startswith("Mover_"):
                return 8
            return 99  # Others go last

        resource_names_sorted = sorted(resource_names, key=get_proc_order_by_name)
        resource_names = list(reversed(resource_names_sorted))

        # === 3) Build slot mapping info ===
        slot_mapping = {}
        for r in all_resources:
            if r["original_name"] not in slot_mapping:
                slot_mapping[r["original_name"]] = []
            slot_mapping[r["original_name"]].append((r["name"], r["slot"]))

        fig = go.Figure()

        resources_with_jobs = set()
        trace_keys = {}

        # Job assignment status tracking
        slot_assignment = {name: [] for name in resource_names}
        job_machine_slot = {}  # {(job_id, machine_name): assigned_slot_name}

        # ===== 4) Collect all completed jobs =====
        completed_jobs = []
        for proc_name, proc in processes.items():
            if proc:
                completed_jobs.extend(proc.completed_jobs)

        # Index by type (plate / rework / box)
        type_counters = {"plate": 0, "rework": 0, "box": 0}
        type_index_map = {}  # {job_id: index_for_its_type}

        for job in completed_jobs:
            job_type = getattr(job, "job_type", "plate")
            if job.id_job not in type_index_map:
                if job_type not in type_counters:
                    type_counters[job_type] = 0
                type_counters[job_type] += 1
                type_index_map[job.id_job] = type_counters[job_type]

        # ===== 5) Draw Gantt bars =====
        for proc_name, proc in processes.items():
            if not proc:
                continue

            for job in proc.completed_jobs:
                job_id = job.id_job
                job_type = getattr(job, "job_type", "plate")

                # Hide item-level jobs in Gantt
                if job_type == "item":
                    continue

                idx = type_index_map.get(job_id, 0)

                # Label
                if job_type == "plate":
                    label = f"Job {idx}"
                elif job_type == "rework":
                    label = f"Rework Job {idx}"
                elif job_type == "box":
                    label = f"Box {idx}"
                else:
                    label = f"Job? {job_id}"

                # Item count in job
                num_items = len(getattr(job, "list_items", []))

                job_color = self.get_color_for_job(job_id)

                if not hasattr(job, "processing_history") or not job.processing_history:
                    continue

                for step in job.processing_history:
                    if step["end_time"] is None:
                        continue

                    orig_resource = step["resource_name"]
                    start_min = step["start_time"]
                    end_min = step["end_time"]
                    duration_min = end_min - start_min
                    if duration_min <= 0:
                        continue

                    resource_type = step.get("resource_type", "Worker")

                    # Assign slots for machines
                    if resource_type == "Machine" and orig_resource in slot_mapping:
                        job_machine_key = (job_id, orig_resource)

                        if job_machine_key in job_machine_slot:
                            assigned_slot = job_machine_slot[job_machine_key]
                        else:
                            slots = slot_mapping[orig_resource]
                            assigned_slot = None

                            for slot_name, slot_index in slots:
                                conflict = False
                                for existing_start, existing_end, existing_job_id in slot_assignment[slot_name]:
                                    if existing_job_id == job_id:
                                        continue
                                    if not (end_min <= existing_start or start_min >= existing_end):
                                        conflict = True
                                        break
                                if not conflict:
                                    assigned_slot = slot_name
                                    job_machine_slot[job_machine_key] = assigned_slot
                                    break

                            if assigned_slot is None:
                                assigned_slot = slots[0][0]
                                job_machine_slot[job_machine_key] = assigned_slot

                        slot_assignment[assigned_slot].append((start_min, end_min, job_id))
                        resource_name = assigned_slot
                    else:
                        resource_name = orig_resource

                    resources_with_jobs.add(resource_name)

                    trace_key = f"{job_type}_{idx}"
                    show_legend = trace_key not in trace_keys
                    if show_legend:
                        trace_keys[trace_key] = True

                    # Use hovertemplate to remove default (x,y) and show item count
                    hovertemplate = (
                        f"{label}<br>"
                        f"Process: {step['process']}<br>"
                        f"Items in Job: {num_items}<br>"
                        f"Duration: {duration_min:.0f} min"
                        "<extra></extra>"
                    )

                    fig.add_trace(
                        go.Bar(
                            y=[resource_name],
                            x=[duration_min],
                            base=start_min,
                            orientation="h",
                            name=label,
                            marker_color=job_color,
                            text=label,
                            hovertemplate=hovertemplate,
                            showlegend=show_legend,
                            legendgroup=trace_key,
                        )
                    )

        # ===== 6) Add dummy traces so idle resources appear on axis =====
        for resource in resource_names:
            if resource not in resources_with_jobs:
                fig.add_trace(
                    go.Bar(
                        y=[resource],
                        x=[0.001],
                        base=0,
                        orientation="h",
                        marker_color="rgba(0,0,0,0)",
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )

        fig.update_layout(
            title="Job / Rework / Box Processing Gantt Chart",
            barmode="overlay",
            xaxis_title="Simulation Time (minutes)",
            yaxis_title="Resource",
            yaxis=dict(categoryorder="array", categoryarray=resource_names),
            legend_title="Job Types",
            height=max(600, len(resource_names) * 30),
            showlegend=True,
        )

        return fig

    def get_all_resources(self, processes):
        """Create resource list split into slots based on machine capacity"""
        resources = []

        # Keys based on Manager.get_processes():
        #  build, wash1, dry1, support, inspect, wash2, dry2, uv
        proc_build = processes.get("build")
        proc_wash1 = processes.get("wash1")
        proc_wash2 = processes.get("wash2")
        proc_dry1 = processes.get("dry1")
        proc_dry2 = processes.get("dry2")
        proc_support = processes.get("support")
        proc_inspect = processes.get("inspect")
        proc_uv = processes.get("uv")

        # Build
        if proc_build:
            for machine in proc_build.list_processors:
                if hasattr(machine, "capacity_jobs") and machine.capacity_jobs > 1:
                    for slot in range(machine.capacity_jobs):
                        resources.append(
                            {
                                "name": f"{machine.name_machine}_Slot{slot+1}",
                                "original_name": machine.name_machine,
                                "slot": slot,
                                "type": "Machine",
                                "process": "Proc_Build",
                            }
                        )
                else:
                    resources.append(
                        {
                            "name": machine.name_machine,
                            "original_name": machine.name_machine,
                            "slot": 0,
                            "type": "Machine",
                            "process": "Proc_Build",
                        }
                    )

        # Wash1 / Wash2
        for proc_wash, proc_label in [(proc_wash1, "Proc_Wash1"), (proc_wash2, "Proc_Wash2")]:
            if proc_wash:
                for machine in proc_wash.list_processors:
                    if hasattr(machine, "capacity_jobs") and machine.capacity_jobs > 1:
                        for slot in range(machine.capacity_jobs):
                            resources.append(
                                {
                                    "name": f"{machine.name_machine}_Slot{slot+1}",
                                    "original_name": machine.name_machine,
                                    "slot": slot,
                                    "type": "Machine",
                                    "process": proc_label,
                                }
                            )
                    else:
                        resources.append(
                            {
                                "name": machine.name_machine,
                                "original_name": machine.name_machine,
                                "slot": 0,
                                "type": "Machine",
                                "process": proc_label,
                            }
                        )

        # Dry1 / Dry2
        for proc_dry, proc_label in [(proc_dry1, "Proc_Dry1"), (proc_dry2, "Proc_Dry2")]:
            if proc_dry:
                for machine in proc_dry.list_processors:
                    if hasattr(machine, "capacity_jobs") and machine.capacity_jobs > 1:
                        for slot in range(machine.capacity_jobs):
                            resources.append(
                                {
                                    "name": f"{machine.name_machine}_Slot{slot+1}",
                                    "original_name": machine.name_machine,
                                    "slot": slot,
                                    "type": "Machine",
                                    "process": proc_label,
                                }
                            )
                    else:
                        resources.append(
                            {
                                "name": machine.name_machine,
                                "original_name": machine.name_machine,
                                "slot": 0,
                                "type": "Machine",
                                "process": proc_label,
                            }
                        )

        # SupportRemoval (workers)
        if proc_support:
            for worker in proc_support.list_processors:
                resources.append(
                    {
                        "name": worker.name_worker,  # e.g., "SupportRemover_1"
                        "original_name": worker.name_worker,
                        "slot": 0,
                        "type": "Worker",
                        "process": "Proc_SupportRemoval",
                    }
                )

        # Inspect (workers)
        if proc_inspect:
            for worker in proc_inspect.list_processors:
                resources.append(
                    {
                        "name": worker.name_worker,
                        "original_name": worker.name_worker,
                        "slot": 0,
                        "type": "Worker",
                        "process": "Proc_Inspect",
                    }
                )

        # UV
        if proc_uv:
            for machine in proc_uv.list_processors:
                if hasattr(machine, "capacity_jobs") and machine.capacity_jobs > 1:
                    for slot in range(machine.capacity_jobs):
                        resources.append(
                            {
                                "name": f"{machine.name_machine}_Slot{slot+1}",
                                "original_name": machine.name_machine,
                                "slot": slot,
                                "type": "Machine",
                                "process": "Proc_UV",
                            }
                        )
                else:
                    resources.append(
                        {
                            "name": machine.name_machine,
                            "original_name": machine.name_machine,
                            "slot": 0,
                            "type": "Machine",
                            "process": "Proc_UV",
                        }
                    )

        # ==== Add transport workers (AMR / Mover) as resources ====
        if MOVE_MODE == "AMR":
            for i in range(NUM_AMR):
                name = f"AMR_{i+1}"
                resources.append(
                    {
                        "name": name,
                        "original_name": name,
                        "slot": 0,
                        "type": "Worker",
                        "process": "Transport",
                    }
                )
        elif MOVE_MODE == "MANUAL":
            for i in range(NUM_MANUAL_MOVERS):
                name = f"Mover_{i+1}"
                resources.append(
                    {
                        "name": name,
                        "original_name": name,
                        "slot": 0,
                        "type": "Worker",
                        "process": "Transport",
                    }
                )

        return resources

    def get_color_for_job(self, job_id):
        """Return a color based on the job ID"""
        colors = [
            "rgba(31, 119, 180, 0.8)",  # Blue
            "rgba(255, 127, 14, 0.8)",  # Orange
            "rgba(44, 160, 44, 0.8)",  # Green
            "rgba(214, 39, 40, 0.8)",  # Red
            "rgba(148, 103, 189, 0.8)",  # Purple
            "rgba(140, 86, 75, 0.8)",  # Brown
            "rgba(227, 119, 194, 0.8)",  # Pink
            "rgba(127, 127, 127, 0.8)",  # Gray
            "rgba(188, 189, 34, 0.8)",  # Olive
            "rgba(23, 190, 207, 0.8)",  # Cyan
        ]
        return colors[job_id % len(colors)]
