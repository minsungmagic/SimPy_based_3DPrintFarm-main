
import simpy
from base_Job import Job
from config_SimPy import *
from specialized_Process import (
    Proc_Build,
    Proc_Wash,
    Proc_Dry,
    Proc_Inspect,
    Proc_SupportRemoval,
    Proc_UV,
)
from base_Customer import OrderReceiver


class BuildPlate:
    """
    Represents an individual build plate.

    state:
      - 'empty'   : idle, no job assigned (in stacker)
      - 'loaded'  : job assigned, ready to build
      - 'built'   : build complete, waiting for support removal (post-build stacker)

    In this modular layout, the "Stacker" is the physical space where:
      - pre-build idle/loaded plates
      - post-build built plates
    reside.
    """

    def __init__(self, plate_id: int):
        self.id = plate_id
        self.state = "empty"  # 'empty' / 'loaded' / 'built'
        self.current_job_id = None
        # Physical location (simple model): 'stacker' / 'printer' / 'support', etc.
        self.location = "stacker"


class Stacker:
    """
    Stacker: build plate storage.
    - Not a separate SimPy Resource; state is managed via
      BuildPlate state/location.

    Usage categories:
      - pre-build assigned state (job assigned)
      - idle waiting state (ready to build)
      - built state waiting to move to Wash1

    Represented by state values:
      - state='empty'  -> idle (pre-build stacker)
      - state='loaded' -> build job assigned (pre-build stacker)
      - state='built'  -> build complete (post-build stacker)
    """

    def __init__(self, plates):
        # BuildPlate list (created by Manager)
        self.plates = plates

    # ===== Query helpers =====
    def get_idle_plates(self):
        return [p for p in self.plates if p.state == "empty"]

    def get_prebuild_loaded_plates(self):
        return [p for p in self.plates if p.state == "loaded"]

    def get_postbuild_plates(self):
        return [p for p in self.plates if p.state == "built"]


class FinalStorage:
    """
    Final storage after UV.
    - Stores jobs and accumulates item counts.
    """

    def __init__(self, env, logger=None):
        self.env = env
        self.logger = logger
        self.stored_jobs = []
        self.total_items = 0

    def store_job(self, job):
        """Store a job completed at UV and accumulate item counts."""
        self.stored_jobs.append(job)
        num_items = len(getattr(job, "list_items", []))
        self.total_items += num_items

        if self.logger:
            self.logger.log_event(
                "FinalStorage",
                f"Received job {job.id_job} with {num_items} items "
                f"(total stored items={self.total_items})",
            )

        try:
            if hasattr(self.logger, "log_web_event"):
                self.logger.log_web_event(
                    "final",
                    {
                        "time": float(self.env.now),
                        "job_id": job.id_job,
                        "num_items": num_items,
                        "total_items": self.total_items,
                    },
                )
        except Exception:
            pass

class GlobalAMRTransport:
    """
    Global transport manager for AMR (or other movers).

    - Inter-process moves:
        Send Proc_X -> Proc_Y directly or enqueue as (Job, from, to) tasks.

    - Plate return after support removal:
        release_plate_after_support enqueues AMR return to stacker.
    """

    def __init__(self, env, logger=None, manager=None):
        self.env = env
        self.logger = logger
        self.manager = manager

        # Transport task queue (job moves / plate returns)
        self.queue = simpy.Store(env)

        # AMR resource (capacity = NUM_AMR)
        self.resource = simpy.Resource(env, capacity=NUM_AMR)

        # Start main loop
        self.process = env.process(self.run())

    def request_job_move(self, job, src_process, dst_process):
        """Enqueue a task to move a job from src -> dst."""
        task = {
            "type": "job",
            "job": job,
            "src": src_process,
            "dst": dst_process,
        }
        self.queue.put(task)

        if self.logger:
            self.logger.log_event(
                "Transport",
                f"Enqueue AMR job move: job {job.id_job} "
                f"{src_process.name_process} -> {dst_process.name_process}",
            )

    def request_plate_return(self, plate, from_process_name="Proc_SupportRemoval"):
        """Enqueue a task to return a plate to the stacker after support removal."""
        task = {
            "type": "plate",
            "plate": plate,
            "from": from_process_name,
        }
        self.queue.put(task)

        if self.logger:
            self.logger.log_event(
                "Transport",
                f"Enqueue AMR plate return: plate {plate.id} "
                f"from {from_process_name} -> stacker",
            )

    def _wait_until_process_ready(self, proc):
        """Wait until the next process is empty (no queued or active jobs)."""
        if proc is None or not hasattr(self.manager, "_is_process_empty"):
            return self.env.event().succeed()

        def _waiter(env, manager, process):
            while not manager._is_process_empty(process):
                yield env.timeout(1)
            return True

        return self.env.process(_waiter(self.env, self.manager, proc))

    def run(self):
        """AMR main loop: pull tasks from the queue and execute them."""
        while True:
            task = yield self.queue.get()

            kind = task.get("type")

            # Wait until the next process is free (do not hold AMR resources)
            if kind == "job":
                to_proc = task["dst"]
                yield self._wait_until_process_ready(to_proc)

            # Acquire AMR resource (held during travel)
            with self.resource.request() as req:
                yield req
                # Travel time
                yield self.env.timeout(PROC_TIME_MOVE_AMR)

            # Handle move completion
            if kind == "job":
                dst = task["dst"]
                job = task["job"]
                if self.logger:
                    self.logger.log_event(
                        "Transport",
                        f"AMR delivered job {job.id_job} to {dst.name_process}",
                    )
                dst.add_to_queue(job)

            elif kind == "plate":
                plate = task["plate"]
                if self.manager is not None:
                    try:
                        self.manager._complete_plate_return(plate)
                    except AttributeError:
                        pass


class Manager(OrderReceiver):
    def __init__(self, env, logger=None):
        self.env = env
        self.logger = logger

        # Job ID
        self.next_job_id = 1

        # Plate / stacker state counters
        self.pre_build_plate_count = INITIAL_NUM_BUILD_PLATES
        self.in_build_plate_count = 0
        self.post_build_plate_count = 0
        self.total_plate_count = INITIAL_NUM_BUILD_PLATES

        # Create BuildPlate list
        self.build_plates = [BuildPlate(i + 1) for i in range(INITIAL_NUM_BUILD_PLATES)]

        # Create Stacker (for build plate state queries)
        self.stacker = Stacker(self.build_plates)

        # Initial state: record all plates as IDLE (empty) at time=0
        for plate in self.build_plates:
            self._log_plate_state(plate)

        # Pending build jobs when plates are unavailable
        self.pending_build_jobs = []

        # AMR transport for process moves (priority/downstream wait support)
        self.amr_transport = GlobalAMRTransportV2(
            env=self.env,
            logger=self.logger,
            manager=self,
            num_amr=NUM_AMR,
        )
        # Align transport alias to the same object
        self.transport = self.amr_transport

        # Final storage (stores items after UV and accumulates counts)
        self.final_storage = FinalStorage(self.env, self.logger)

        # Create and connect processes
        self.setup_processes(manager=self)

        # Completed orders
        self.completed_orders = []

        # Bind transport to each process
        for proc in [
            self.proc_build,
            self.proc_wash1,
            self.proc_dry1,
            self.proc_support,
            self.proc_inspect,
            self.proc_wash2,
            self.proc_dry2,
            self.proc_uv,
        ]:
            if proc is not None:
                proc.transport = self.amr_transport

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------
    def _log_plate_state(self, plate: BuildPlate):
        if self.logger is None:
            return
        self.logger.log_web_event(
            "plate",
            {
                "plate_id": plate.id,
                "state": plate.state,  # 'empty' / 'loaded' / 'built'
                "current_job_id": plate.current_job_id,
                "location": plate.location,  # 'stacker' / 'support', etc.
            },
        )

    # ------------------------------------------------------------------
    # Build plate management (including stacker)
    # ------------------------------------------------------------------
    def assign_plate_to_job(self, job: Job) -> bool:
        """
        Assign a build plate to a job for the build process.
        Assign immediately if a plate is available; otherwise return False.
        """
        for plate in self.build_plates:
            if plate.state == "empty":
                # Assign plate (LOADED, located in stacker)
                plate.state = "loaded"
                plate.current_job_id = job.id_job
                plate.location = "stacker"
                job.build_plate_id = plate.id

                # Update counters
                if self.pre_build_plate_count > 0:
                    self.pre_build_plate_count -= 1
                self.in_build_plate_count += 1

                self._log_plate_state(plate)

                if self.logger is not None:
                    try:
                        self.logger.log_web_event(
                            "job",
                            {
                                "job_id": job.id_job,
                                "job_type": getattr(job, "job_type", "plate"),
                                "stage": "assigned_to_plate",
                                "plate_id": plate.id,
                                "time": float(self.env.now),
                            },
                        )
                    except AttributeError:
                        pass

                return True

        # No available plate
        return False

    def on_build_complete(self, jobs):
        """
        Handle build completion:
        - Mark plate as 'built' and place it in the post-build stacker.
        - Update counters.
        """
        for job in jobs:
            pid = getattr(job, "build_plate_id", None)
            if pid is None:
                continue
            for plate in self.build_plates:
                if plate.id == pid and plate.state in ("loaded", "printing"):
                    plate.state = "built"
                    plate.location = "stacker"  # post-build stacker
                    if self.in_build_plate_count > 0:
                        self.in_build_plate_count -= 1
                    if self.post_build_plate_count < MAX_POST_BUILD_PLATES:
                        self.post_build_plate_count += 1
                    self._log_plate_state(plate)
                    break

    def release_plate_after_support(self, jobs):
        """
        After support removal:
        - Request AMR to return the plate to the stacker.
        - State/counter updates occur when AMR return completes in _complete_plate_return.
        """
        for job in jobs:
            pid = getattr(job, "build_plate_id", None)
            if pid is None:
                continue

            for plate in self.build_plates:
                if plate.id == pid:
                    # Detach job from plate
                    job.build_plate_id = None

                    # Plate stays at support process
                    plate.location = "support"
                    self._log_plate_state(plate)

                    # Request AMR plate return
                    if getattr(self, "transport", None) is not None:
                        try:
                            from_proc = getattr(self, "proc_support", None)
                            if from_proc is None:
                                from_proc = self
                            self.transport.request_plate_return(
                                plate, from_process=from_proc
                            )
                        except Exception:
                            # On error, immediately return to stacker
                            self._complete_plate_return(plate)

    def _complete_plate_return(self, plate: BuildPlate):
        """Return the plate to the stacker after AMR move completes."""
        if plate.state != "empty":
            plate.state = "empty"
        plate.current_job_id = None
        plate.location = "stacker"

        if self.post_build_plate_count > 0:
            self.post_build_plate_count -= 1
        if self.pre_build_plate_count < MAX_PRE_BUILD_PLATES:
            self.pre_build_plate_count += 1

        self._log_plate_state(plate)

        # Plate is available, try pending build jobs again
        self._try_dispatch_pending_build_jobs()

    def _try_dispatch_pending_build_jobs(self):
        """
        While pre_build_plate_count has capacity, assign pending_build_jobs
        to plates and enqueue them to the build process.
        """
        while self.pending_build_jobs and self.pre_build_plate_count > 0:
            job = self.pending_build_jobs.pop(0)
            assigned = self.assign_plate_to_job(job)
            if not assigned:
                self.pending_build_jobs.insert(0, job)
                break

            if self.logger:
                self.logger.log_event(
                    "Manager",
                    f"Dispatching pending build job {job.id_job} to Proc_Build "
                    f"(plate {job.build_plate_id})",
                )
            self.proc_build.add_to_queue(job)

    def collect_build_plate_status(self):
        """Return a list of plate status entries."""
        status = []
        for plate in self.build_plates:
            status.append(
                {
                    "plate_id": f"PLATE-{plate.id}",
                    "state": plate.state,
                    "location": plate.location,
                    "job": f"JOB-{plate.current_job_id}" if plate.current_job_id is not None else None,
                }
            )
        return status

    # ------------------------------------------------------------------
    # Process setup (using global AMR)
    # ------------------------------------------------------------------
    def setup_processes(self, manager=None):
        """Create and connect all processes"""

        self.proc_build = Proc_Build(
            self.env, manager, self.logger, transport_manager=self.transport
        )

        self.proc_wash1 = Proc_Wash(
            self.env, stage=1, logger=self.logger, transport_manager=self.transport
        )
        self.proc_dry1 = Proc_Dry(
            self.env, stage=1, logger=self.logger, transport_manager=self.transport
        )

        self.proc_support = Proc_SupportRemoval(
            self.env, manager, self.logger, transport_manager=self.transport
        )
        self.proc_inspect = Proc_Inspect(
            self.env, manager, self.logger, transport_manager=self.transport
        )

        self.proc_wash2 = Proc_Wash(
            self.env, stage=2, logger=self.logger, transport_manager=self.transport
        )
        self.proc_dry2 = Proc_Dry(
            self.env, stage=2, logger=self.logger, transport_manager=self.transport
        )

        self.proc_uv = Proc_UV(
            self.env, manager=self, logger=self.logger, transport_manager=self.transport
        )

        # Connect processes
        self.proc_build.connect_to_next_process(self.proc_wash1)
        self.proc_wash1.connect_to_next_process(self.proc_dry1)
        self.proc_dry1.connect_to_next_process(self.proc_support)
        self.proc_support.connect_to_next_process(self.proc_inspect)
        self.proc_inspect.connect_to_next_process(self.proc_wash2)
        self.proc_wash2.connect_to_next_process(self.proc_dry2)
        self.proc_dry2.connect_to_next_process(self.proc_uv)

        if self.logger:
            self.logger.log_event(
                "Manager",
                "Processes created and connected with GLOBAL AMR transport: "
                "Build -> Wash1 -> Dry1 -> Support -> Inspect -> Wash2 -> Dry2 -> UV",
            )
    def receive_order(self, order):
        """Start handling an order sent from Customer to Manager"""
        if self.logger:
            self.logger.log_event(
                "Order",
                f"Received Order {order.id_order} with {order.num_patients} patients",
            )

        order.time_start = self.env.now
        self.create_jobs_for_proc_build(order)
        return order

    # ------------------------------------------------------------------
    # Order -> build job creation
    # ------------------------------------------------------------------
    def _enqueue_build_job(self, job: Job):
        """
        Common routine to send a job to the build process:
        - If a plate is available, assign immediately and enqueue to build
        - Otherwise append to pending_build_jobs
        """
        assigned = self.assign_plate_to_job(job)
        if assigned:
            if self.logger:
                self.logger.log_event(
                    "Manager",
                    f"Enqueue job {job.id_job} to Proc_Build "
                    f"(plate {job.build_plate_id})",
                )
            self.proc_build.add_to_queue(job)
        else:
            self.pending_build_jobs.append(job)
            if self.logger:
                self.logger.log_event(
                    "Manager",
                    "No free plate. Job "
                    f"{job.id_job} is waiting in pending_build_jobs "
                    f"(len={len(self.pending_build_jobs)})",
                )
                try:
                    self.logger.log_web_event(
                        "job",
                        {
                            "job_id": job.id_job,
                            "job_type": getattr(job, "job_type", "plate"),
                            "stage": "waiting_for_plate",
                            "time": float(self.env.now),
                        },
                    )
                except AttributeError:
                    pass

    def create_jobs_for_proc_build(self, order):
        """Convert an order into build jobs (POLICY_ORDER_TO_JOB applied)"""
        all_patients = order.list_patients

        for patient in all_patients:
            patient_items = patient.list_items

            # 1) One job if patient items <= PALLET_SIZE_LIMIT
            if len(patient_items) <= PALLET_SIZE_LIMIT:
                job = Job(self.next_job_id, patient_items)
                self.next_job_id += 1

                if self.logger:
                    self.logger.log_event(
                        "Manager",
                        f"Created job {job.id_job} for patient {patient.id_patient} "
                        f"with {len(patient_items)} items",
                    )

                self._enqueue_build_job(job)

            # 2) If exceeded, split into multiple jobs
            else:
                if POLICY_ORDER_TO_JOB == "MAX_PER_JOB":
                    items_per_job = PALLET_SIZE_LIMIT
                    for i in range(0, len(patient_items), items_per_job):
                        job_items = patient_items[i : i + items_per_job]
                        job = Job(self.next_job_id, job_items)
                        self.next_job_id += 1

                        if self.logger:
                            self.logger.log_event(
                                "Manager",
                                f"Created job {job.id_job} for patient "
                                f"{patient.id_patient} with {len(job_items)} items (split job)",
                            )

                        self._enqueue_build_job(job)

    # ------------------------------------------------------------------
    # Inspect defects -> rework job creation
    # ------------------------------------------------------------------
    def create_job_for_defects(self):
        """Create a rework job from defective items"""
        defective_items = self.proc_inspect.defective_items

        if not defective_items:
            return

        if len(defective_items) >= POLICY_NUM_DEFECT_PER_JOB:
            items_for_job = defective_items[:POLICY_NUM_DEFECT_PER_JOB]

            job = Job(self.next_job_id, items_for_job, job_type="rework")
            job.is_reprocess = True
            self.next_job_id += 1

            self.proc_inspect.defective_items = defective_items[POLICY_NUM_DEFECT_PER_JOB:]

            self._enqueue_build_job(job)

            if self.logger:
                self.logger.log_event(
                    "Manager",
                    f"Created rework job {job.id_job} with "
                    f"{len(items_for_job)} defective items (added to build queue)",
                )
                self.logger.log_event(
                    "Manager",
                    "Remaining defective items: "
                    f"{len(self.proc_inspect.defective_items)}",
                )

                try:
                    self.logger.log_web_event(
                        "job",
                        {
                            "job_id": job.id_job,
                            "job_type": "rework",
                            "stage": "rework_created",
                            "time": float(self.env.now),
                            "num_items": len(items_for_job),
                        },
                    )
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Stats / queries
    # ------------------------------------------------------------------
    def get_processes(self):
        """Return process dict for stats collection"""
        return {
            "build": self.proc_build,
            "wash1": self.proc_wash1,
            "dry1": self.proc_dry1,
            "support": self.proc_support,
            "inspect": self.proc_inspect,
            "wash2": self.proc_wash2,
            "dry2": self.proc_dry2,
            "uv": self.proc_uv,
        }

    def collect_statistics(self):
        """Collect basic statistics"""
        stats = {}

        stats["build_completed"] = len(self.proc_build.completed_jobs)
        stats["wash1_completed"] = len(self.proc_wash1.completed_jobs)
        stats["dry1_completed"] = len(self.proc_dry1.completed_jobs)
        stats["support_completed"] = len(self.proc_support.completed_jobs)
        stats["inspect_completed"] = len(self.proc_inspect.completed_jobs)
        stats["wash2_completed"] = len(self.proc_wash2.completed_jobs)
        stats["dry2_completed"] = len(self.proc_dry2.completed_jobs)
        stats["uv_completed"] = len(self.proc_uv.completed_jobs)

        stats["build_queue"] = self.proc_build.job_store.size
        stats["wash1_queue"] = self.proc_wash1.job_store.size
        stats["dry1_queue"] = self.proc_dry1.job_store.size
        stats["support_queue"] = self.proc_support.job_store.size
        stats["inspect_queue"] = self.proc_inspect.job_store.size
        stats["wash2_queue"] = self.proc_wash2.job_store.size
        stats["dry2_queue"] = self.proc_dry2.job_store.size
        stats["uv_queue"] = self.proc_uv.job_store.size

        stats["defective_items"] = len(self.proc_inspect.defective_items)

        if hasattr(self.proc_inspect, "buffer_good_items"):
            stats["inspect_good_buffer_items"] = len(self.proc_inspect.buffer_good_items)
        else:
            stats["inspect_good_buffer_items"] = None

        stats["pre_build_plates"] = self.pre_build_plate_count
        stats["post_build_plates"] = self.post_build_plate_count
        stats["in_build_plates"] = self.in_build_plate_count

        stats["plate_status"] = self.collect_build_plate_status()

        stats["final_items"] = getattr(self.final_storage, "total_items", 0)

        return stats

    def _is_process_empty(self, proc):
        """Check whether a process queue and resources are empty"""
        if proc is None:
            return True
        if not proc.job_store.is_empty:
            return False
        for res in proc.processor_resources.values():
            try:
                current_jobs = res.get_jobs()
            except Exception:
                current_jobs = []
            # Treat processing_started as busy as well
            if getattr(res, "processing_started", False):
                return False
            if current_jobs:
                return False
        return True

    def is_wash1_empty(self):
        """Check whether Wash1 is empty at the build completion point"""
        return self._is_process_empty(self.proc_wash1)


# ==============================
# Second global AMR transport (process movement)
# ==============================
class GlobalAMRTransportV2:
    """
    AMR responsible for process movement.

    - job_move: normal from_proc -> to_proc move
    - build_to_stacker: Build -> Stacker (physical move only, no processing)
    - stacker_to_wash1: Stacker -> Wash1 (job push)
    - plate_return / final_storage follow existing logic
    """

    def __init__(self, env, logger, manager, num_amr=1):
        self.env = env
        self.logger = logger
        self.manager = manager
        self.num_amr = num_amr

        # AMR resource
        self.resource = simpy.Resource(env, capacity=num_amr)
        # Destination reservation locks (avoid multiple moves into same process)
        self.dest_locks = {}

        # Task queue with priority
        # priority 0: build_to_stacker (highest: clear printer)
        # priority 1: stacker_to_wash1 (stacker to wash)
        # priority 2: other moves
        self.task_store = simpy.PriorityStore(env)
        self._task_seq = 0  # tie-breaker for same priority

        # Run main loop
        self.env.process(self.run())

    def _try_lock_destination(self, proc):
        """
        Lock the destination if it is empty and not already reserved.
        Return False if the lock cannot be acquired.
        """
        if proc is None or not hasattr(self.manager, "_is_process_empty"):
            return True
        if self.dest_locks.get(id(proc), False):
            return False
        if not self.manager._is_process_empty(proc):
            return False
        # Lock destination
        self.dest_locks[id(proc)] = True
        return True

    # ---------- External API ----------

    def request_job_move(self, job, from_process, to_process):
        """Process -> process move (e.g., Wash1 -> Dry1)"""
        if self.logger:
            self.logger.log_event(
                "Transport",
                f"Enqueue AMR job move: job {job.id_job} "
                f"{from_process.name_process} -> {to_process.name_process}",
            )
            self.logger.log_event(
                "Process Flow",
                f"Request AMR move for job {job.id_job} from "
                f"{from_process.name_process} to {to_process.name_process}",
            )

        done = self.env.event()

        # Restore priority: normal process move is 2
        self._task_seq += 1
        self.task_store.put((
            2,
            self._task_seq,
            {
                "kind": "job_move",
                "job": job,
                "from": from_process,
                "to": to_process,
                "done_event": done,
            },
        ))
        return done

    def request_build_exit(self, job, from_process, to_process_wash1):
        """
        Move from Build to the next stage.
        - Always move Build -> Stacker to clear the printer (priority 0)
        - Stacker -> Wash1 waits until Wash1 is empty while AMR is held (priority 1)
        """
        # Build -> Stacker
        done_to_stacker = self.env.event()
        done_to_wash = self.env.event()

        # Step 1: Build -> Stacker (highest priority: clear printer)
        if self.logger:
            self.logger.log_event(
                "Transport",
                f"Enqueue AMR job move (Build->Stacker): "
                f"job {job.id_job} {from_process.name_process} -> Stacker",
            )
            self.logger.log_event(
                "Process Flow",
                f"Request AMR move for job {job.id_job} from "
                f"{from_process.name_process} to Stacker",
            )

        plate_id = getattr(job, "build_plate_id", None)

        self._task_seq += 1
        self.task_store.put((
            0,
            self._task_seq,
            {
                "kind": "build_to_stacker",
                "job": job,
                "from": from_process,
                "plate_id": plate_id,
                "done_event": done_to_stacker,
            },
        ))

        # Step 2: Stacker -> Wash1 (hold AMR until Wash1 is empty)
        self._task_seq += 1
        self.task_store.put((
            1,
            self._task_seq,
            {
                "kind": "stacker_to_wash1",
                "job": job,
                "to": to_process_wash1,
                "done_event": done_to_wash,
            },
        ))

        return done_to_stacker

    def request_plate_return(self, plate, from_process):
        """Return plate to stacker after support removal"""
        if self.logger:
            self.logger.log_event(
                "Transport",
                f"Enqueue AMR plate return: plate {plate.id} "
                f"from {from_process.name_process} -> stacker",
            )
        done = self.env.event()
        self._task_seq += 1
        self.task_store.put((
            3,  # Plate return is lower priority
            self._task_seq,
            {
                "kind": "plate_return",
                "plate": plate,
                "from": from_process,
                "done_event": done,
            },
        ))
        return done

    def request_final_storage(self, job, from_process):
        """Move to final storage after UV"""
        if self.logger:
            self.logger.log_event(
                "Transport",
                f"Enqueue AMR final storage move: job {job.id_job} "
                f"from {from_process.name_process} -> FinalStorage",
            )
        done = self.env.event()
        self._task_seq += 1
        self.task_store.put((
            4,  # Final storage is the lowest priority
            self._task_seq,
            {
                "kind": "final_storage",
                "job": job,
                "from": from_process,
                "done_event": done,
            },
        ))
        return done

    # ---------- Internal helper: AMR Gantt recording ----------

    def _record_amr_gantt(self, job, start_time, end_time, amr_index=1):
        """
        Record AMR travel in job.processing_history
        -> log_SimPy.visualize_gantt() shows a bar on the 'AMR_1' row
        """
        if job is None:
            return

        if not hasattr(job, "processing_history"):
            job.processing_history = []

        job.processing_history.append({
            "process": "Transport",          # get_all_resources uses process='Transport'
            "resource_type": "Worker",
            "resource_id": amr_index,
            "resource_name": f"AMR_{amr_index}",
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
        })

    def _wait_until_process_ready(self, proc):
        """Wait until the next process is empty and unreserved, then lock it."""
        if proc is None or not hasattr(self.manager, "_is_process_empty"):
            return self.env.event().succeed()

        def _waiter(env, manager, process):
            while self.dest_locks.get(id(process), False) or not manager._is_process_empty(process):
                yield env.timeout(1)
            # Set reservation lock (released in _release_destination_when_empty)
            self.dest_locks[id(process)] = True
            return True

        return self.env.process(_waiter(self.env, self.manager, proc))

    def _release_destination_when_empty(self, proc):
        """Release lock when the destination becomes empty again"""
        if proc is None:
            return

        def _wait_clear(env, manager, process):
            while not manager._is_process_empty(process):
                yield env.timeout(1)
            self.dest_locks[id(process)] = False

        self.env.process(_wait_clear(self.env, self.manager, proc))

    # ---------- Main loop ----------

    def run(self):
        """Process AMR task queue in order"""
        while True:
            pending = []
            priority, seq, task = yield self.task_store.get()

            # Defer locked tasks until a runnable task is found
            while True:
                kind = task.get("kind")
                job = task.get("job", None)
                done_event = task.get("done_event")

                if kind in ("job_move", "stacker_to_wash1"):
                    to_proc = task["to"]
                    if not self._try_lock_destination(to_proc):
                        pending.append((priority, seq, task))
                        # If the queue is empty, wait briefly and requeue pending tasks
                        if len(self.task_store.items) == 0:
                            for item in pending:
                                self.task_store.put(item)
                            pending = []
                            yield self.env.timeout(1)
                        priority, seq, task = yield self.task_store.get()
                        continue
                break

            # Requeue deferred tasks
            for item in pending:
                self.task_store.put(item)

            # Acquire AMR (only during travel)
            with self.resource.request() as req:
                yield req

                start = self.env.now
                # Time for one move
                yield self.env.timeout(PROC_TIME_MOVE_AMR)
                end = self.env.now

                # Record AMR bar in Gantt chart
                self._record_amr_gantt(job, start, end, amr_index=1)

                # --- Task-type-specific behavior ---
                if kind == "job_move":
                    to_proc = task["to"]
                    if self.logger:
                        self.logger.log_event(
                            "Transport",
                            f"AMR delivered job {job.id_job} to {to_proc.name_process}",
                        )
                    to_proc.add_to_queue(job)
                    self._release_destination_when_empty(to_proc)
                    if done_event:
                        done_event.succeed()

                elif kind == "build_to_stacker":
                    plate_id = task.get("plate_id")
                    if self.logger:
                        self.logger.log_event(
                            "Transport",
                            f"AMR moved job {job.id_job} (plate {plate_id}) "
                            f"from Proc_Build to Stacker",
                        )
                    # Plate/stacker state is handled in Manager.on_build_complete()
                    if done_event:
                        done_event.succeed()

                elif kind == "stacker_to_wash1":
                    to_proc = task["to"]
                    if self.logger:
                        self.logger.log_event(
                            "Transport",
                            f"AMR picked job {job.id_job} from Stacker "
                            f"and delivered to {to_proc.name_process}",
                        )
                    to_proc.add_to_queue(job)
                    self._release_destination_when_empty(to_proc)
                    if done_event:
                        done_event.succeed()

                elif kind == "plate_return":
                    plate = task["plate"]
                    # Prefer Manager hook; fallback to default plate return handling
                    if hasattr(self.manager, "on_plate_returned"):
                        self.manager.on_plate_returned(plate)
                    elif hasattr(self.manager, "_complete_plate_return"):
                        self.manager._complete_plate_return(plate)

                    if self.logger:
                        self.logger.log_event(
                            "Transport",
                            f"AMR delivered plate {plate.id} to stacker",
                           )
                    if done_event:
                        done_event.succeed()

                elif kind == "final_storage":
                    job = task["job"]
                    if hasattr(self.manager, "final_storage"):
                        try:
                            self.manager.final_storage.store_job(job)
                        except AttributeError:
                            pass

                    if self.logger:
                        self.logger.log_event(
                            "Transport",
                            f"AMR delivered job {job.id_job} to FinalStorage",
                        )
                    if done_event:
                        done_event.succeed()
