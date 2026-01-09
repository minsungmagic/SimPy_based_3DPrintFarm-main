import random
from config_SimPy import *
from base_Process import Process
from base_Job import Job
from specialized_Processor import (
    Mach_3DPrint,
    Mach_Wash1,
    Mach_Wash2,
    Mach_Dry1,
    Mach_Dry2,
    Worker_Inspect,
    Mach_UV,
    Worker_AMR,
    Worker_Mover,
    Worker_Support,
)


class Proc_Build(Process):
    """
    3D Printing Process
    """

    def __init__(self, env, manager=None, logger=None, transport_manager=None):
        super().__init__("Proc_Build", env, logger, transport_manager)
        self.manager = manager  # For build plate counts/state

        for i in range(NUM_MACHINES_BUILD):
            self.register_processor(Mach_3DPrint(i + 1))

    def apply_special_processing(self, processor, jobs):
        """
        3D Printing special processing
        - On build completion, update BuildPlate state from printing -> built
        - Set item defect flags
        """
        # 0) Ensure plate job type (default to plate)
        for job in jobs:
            if getattr(job, "job_type", None) is None:
                job.job_type = "plate"

        # 1) Update plate state (Manager handles built + plate event log)
        if self.manager is not None:
            self.manager.on_build_complete(jobs)

        # 2) Keep existing defect-flag logic
        for job in jobs:
            for item in job.list_items:
                if random.random() < DEFECT_RATE_PROC_BUILD:
                    item.is_defect = True
                else:
                    item.is_defect = False

        # 3) Web: build-completed job event log
        if self.logger is not None:
            for job in jobs:
                try:
                    self.logger.log_web_event(
                        "job",
                        {
                            "job_id": job.id_job,
                            "job_type": getattr(job, "job_type", "plate"),
                            "stage": "build_completed",
                            "time": float(self.env.now),
                        },
                    )
                except AttributeError:
                    # Ignore if log_web_event is unavailable
                    pass

        return True


class Proc_SupportRemoval(Process):
    """
    Support removal process
    - Handles jobs on a build plate (plate/rework)
    - After support removal:
        1) Call Manager.release_plate_after_support()
           -> plate is returned to stacker via AMR
        2) Job proceeds to the next process (Inspect)
    """

    def __init__(self, env, manager=None, logger=None, transport_manager=None):
        super().__init__("Proc_SupportRemoval", env, logger, transport_manager)
        self.manager = manager

        for i in range(NUM_WORKERS_SUPPORT):
            self.register_processor(Worker_Support(i + 1))

    def apply_special_processing(self, processor, jobs):
        """
        Only return the plate after support removal.
        Job stays intact -> Inspect process splits into items.
        """
        for job in jobs:
            # 1) Plate state update/return handled by Manager via AMR
            if self.manager is not None:
                try:
                    self.manager.release_plate_after_support([job])
                except Exception as e:
                    if self.logger:
                        self.logger.log_event(
                            "Support",
                            f"release_plate_after_support error for job "
                            f"{job.id_job}: {e}",
                        )

            # 2) Log only (job proceeds to next process)
            if self.logger:
                self.logger.log_event(
                    "Support",
                    f"Job {job.id_job} support removed (plate {getattr(job, 'build_plate_id', None)})",
                )

        # Returning True keeps base_Process flow (move to next process)
        return True


class Proc_Wash(Process):
    def __init__(self, env, stage, logger=None, transport_manager=None):
        name = f"Proc_Wash{stage}"
        super().__init__(name, env, logger, transport_manager)

        if stage == 1:
            for i in range(NUM_MACHINES_WASH1):
                self.register_processor(Mach_Wash1(i + 1))
        else:  # stage == 2
            for i in range(NUM_MACHINES_WASH2):
                self.register_processor(Mach_Wash2(i + 1))


class Proc_Dry(Process):
    def __init__(self, env, stage, logger=None, transport_manager=None):
        name = f"Proc_Dry{stage}"
        super().__init__(name, env, logger, transport_manager)

        if stage == 1:
            for i in range(NUM_MACHINES_DRY1):
                self.register_processor(Mach_Dry1(i + 1))
        else:
            for i in range(NUM_MACHINES_DRY2):
                self.register_processor(Mach_Dry2(i + 1))


class Proc_Inspect(Process):
    """
    Inspection process

    - Input: plate / rework jobs after Support
      (job.list_items contains multiple items)
    - Internal behavior:
        * Classify items via is_defect flag into good / bad
        * bad  -> accumulate in self.defective_items (rework buffer)
        * good -> accumulate in self.buffer_good_items, create box jobs per BOX_SIZE
    - plate / rework jobs are consumed here and do not go to the next process.
      Only the newly created box jobs move forward.
    """

    def __init__(
        self, env, manager=None, logger=None, transport_manager=None
    ):
        super().__init__("Proc_Inspect", env, logger, transport_manager)
        self.manager = manager

        # Inspect workers
        for i in range(NUM_WORKERS_IN_INSPECT):
            self.register_processor(Worker_Inspect(i + 1))

        # Defect / good buffers
        self.defective_items = []  # For rework
        self.buffer_good_items = []  # Waiting for boxing

    # ==========================
    # 1) Customize job forwarding
    # ==========================
    def send_job_to_next(self, job):
        """Do not forward plate/rework jobs consumed at Inspect."""
        if getattr(job, "_consumed_at_inspect", False):
            if self.logger:
                self.logger.log_event(
                    "Process Flow",
                    f"Job {job.id_job} consumed at {self.name_process}; "
                    f"not sent to next process",
                )
            return False  # Stop here (do not go to Wash2)

        # Use base behavior for other types (e.g., box)
        return super().send_job_to_next(job)

    # ==========================
    # 2) Build boxes from good items
    # ==========================
    def _create_boxes_from_buffer(self):
        """Create box jobs from buffer_good_items and send to next process."""
        if self.manager is None:
            return

        while len(self.buffer_good_items) >= BOX_SIZE:
            box_items = self.buffer_good_items[:BOX_SIZE]
            self.buffer_good_items = self.buffer_good_items[BOX_SIZE:]

            # Issue new job ID
            new_job_id = self.manager.next_job_id
            self.manager.next_job_id += 1

            new_job = Job(new_job_id, box_items, job_type="box")

            # Enqueue directly to next process (Wash2)
            if self.next_process is not None:
                self.next_process.add_to_queue(new_job)

            # Web event: box created
            if self.logger is not None:
                try:
                    self.logger.log_web_event(
                        "job",
                        {
                            "job_id": new_job.id_job,
                            "job_type": "box",
                            "stage": "box_created",
                            "time": float(self.env.now),
                            "num_items_in_box": len(new_job.list_items),
                            "remaining_good_items": len(self.buffer_good_items),
                        },
                    )
                except AttributeError:
                    pass

            if self.logger:
                self.logger.log_event(
                    "Inspection",
                    f"BOX job {new_job.id_job} created "
                    f"({len(new_job.list_items)} items, "
                    f"buffer={len(self.buffer_good_items)})",
                )

    # ==========================
    # 3) Core: consume plate/rework jobs and keep only buffers
    # ==========================
    def apply_special_processing(self, processor, jobs):
        """Inspection logic: consume plate/rework jobs and split items into buffers."""
        if not isinstance(processor, Worker_Inspect):
            return True

        for job in jobs:
            good_items = []
            bad_items = []

            for item in job.list_items:
                # Assume is_defect / is_completed set in Build process
                if not getattr(item, "is_completed", False):
                    item.is_completed = True

                if getattr(item, "is_defect", False):
                    bad_items.append(item)
                else:
                    good_items.append(item)

            # 1) Add to defect buffer
            if bad_items:
                self.defective_items.extend(bad_items)
                if self.logger:
                    self.logger.log_event(
                        "Inspection",
                        f"Found {len(bad_items)} defective items in job {job.id_job} "
                        f"(total defect buffer={len(self.defective_items)})",
                    )

            # 2) Add to good buffer
            if good_items:
                self.buffer_good_items.extend(good_items)

            # 3) Mark this job as consumed at Inspect
            job._consumed_at_inspect = True

            # Plate jobs: log plate disassembly event for visualization
            if (
                self.logger is not None
                and getattr(job, "job_type", "plate") == "plate"
            ):
                try:
                    self.logger.log_web_event(
                        "job",
                        {
                            "job_id": job.id_job,
                            "job_type": "plate",
                            "stage": "plate_disassembled_at_inspect",
                            "time": float(self.env.now),
                            "remaining_good_items": len(self.buffer_good_items),
                        },
                    )
                except AttributeError:
                    pass

        # 4) Try creating box jobs from good buffer
        self._create_boxes_from_buffer()

        # 5) Try creating rework job from defects (delegate to Manager)
        if self.manager is not None:
            try:
                self.manager.create_job_for_defects()
            except AttributeError:
                # Ignore if the function is unavailable
                pass

        return True


class Proc_UV(Process):
    """
    UV Curing Process
    UV curing process after Dry.
    - After completion, store finished items in Manager.final_storage
    """

    def __init__(self, env, manager=None, logger=None, transport_manager=None):
        super().__init__("Proc_UV", env, logger, transport_manager)
        self.manager = manager

        # Initialize UV machines
        for i in range(NUM_MACHINES_UV):
            self.register_processor(Mach_UV(i + 1))

    def apply_special_processing(self, processor, jobs):
        """
        Send items to final storage after UV and accumulate counts.
        """
        if self.manager is None:
            return True

        storage = getattr(self.manager, "final_storage", None)
        if storage is None:
            return True

        for job in jobs:
            storage.store_job(job)

        return True


class Proc_Move(Process):
    """
    (Currently unused legacy move process)
    Previously each segment had its own Move process with AMR/workers.
    Now a global AMR (GlobalAMRTransport) is used, so Manager no longer
    creates Proc_Move instances.
    """

    def __init__(self, env, name_process, mode="AMR", logger=None, transport_manager=None):
        super().__init__(name_process, env, logger, transport_manager)
        self.mode = mode.upper()

        if self.mode == "AMR":
            for i in range(NUM_AMR):
                self.register_processor(Worker_AMR(i + 1))
        else:
            for i in range(NUM_MANUAL_MOVERS):
                self.register_processor(Worker_Mover(i + 1))
