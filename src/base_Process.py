from base_Job import JobStore
from base_Processor import ProcessorResource


class Process:
    """
    Base manufacturing process class for SimPy simulation

    Attributes:
        name_process (str): Process identifier
        env (simpy.Environment): Simulation environment
        logger (Logger): Event logger
        list_processors (list): List of processors (Machines, Workers)
        job_store (JobStore): Job queue management
        processor_resources (dict): Processor resources (Machine, Worker)
        completed_jobs (list): List of completed jobs
        next_process (Process): Next process in the flow
        resource_trigger (simpy.Event): Resource trigger event
        job_added_trigger (simpy.Event): Job added trigger event
        process (simpy.Process): Main process execution
        transport_manager: Global AMR / transport manager (delegates inter-process moves)
    """

    def __init__(self, name_process, env, logger=None, transport_manager=None):
        self.name_process = name_process
        self.env = env
        self.logger = logger
        self.transport_manager = transport_manager  # Global AMR manager (optional)
        self.list_processors = []  # Processor list

        # Implement queue with JobStore (Inherits SimPy Store)
        self.job_store = JobStore(env, f"{name_process}_JobStore")

        # Processor resource management
        self.processor_resources = {}  # {processor_id: ProcessorResource}

        # Track completed jobs
        self.completed_jobs = []

        # Next process
        self.next_process = None

        # Add new events
        self.resource_trigger = env.event()
        self.job_added_trigger = env.event()

        # Start simulation process
        self.process = env.process(self.run())

    def connect_to_next_process(self, next_process):
        """Connect directly to next process. Used for process initialization."""
        self.next_process = next_process

    def register_processor(self, processor):
        """Register processor (Machine or Worker). Used for process initialization."""
        # Add to processor list
        self.list_processors.append(processor)

        # Create ProcessorResource (integrated resource management)
        processor_resource = ProcessorResource(self.env, processor)

        # Determine id based on processor type
        if processor.type_processor == "Machine":
            processor_id = f"Machine_{processor.id_machine}"
        else:  # Worker
            processor_id = f"Worker_{processor.id_worker}"

        # Store resource
        self.processor_resources[processor_id] = processor_resource

    def add_to_queue(self, job):
        """Add job to queue"""
        job.time_waiting_start = self.env.now
        job.workstation["Process"] = self.name_process

        # Add job to JobStore
        self.job_store.put(job)

        # Trigger job added event
        self.job_added_trigger.succeed()
        # Create new trigger immediately
        self.job_added_trigger = self.env.event()

        if self.logger:
            self.logger.log_event(
                "Queue",
                f"Added job {job.id_job} to {self.name_process} queue. "
                f"Queue length: {self.job_store.size}",
            )

    def run(self):
        """Event-based process execution"""
        # Initial check: if queue already has jobs at start
        if not self.job_store.is_empty:
            yield self.env.process(self.seize_resources())

        while True:
            # Wait for events: until job is added or resource is released
            yield self.job_added_trigger | self.resource_trigger

            # If there are jobs in queue, attempt to allocate resources
            if not self.job_store.is_empty:
                yield self.env.process(self.seize_resources())

    def seize_resources(self):
        """
        Allocate available resources (machines or workers) to jobs in queue
        """
        # Find available processors
        available_processors = [
            res for res in self.processor_resources.values() if res.is_available
        ]

        # If queue is empty or no available processors, stop
        if self.job_store.is_empty or not available_processors:
            return

        # List of jobs assigned to each processor
        processor_assignments = []

        # Try processing with all processors
        for processor_resource in available_processors:
            remaining_capacity = processor_resource.capacity - processor_resource.count
            jobs_to_assign = []

            # Assign jobs
            try:
                for i in range(min(remaining_capacity, self.job_store.size)):
                    if not self.job_store.is_empty:
                        job = yield self.job_store.get()
                        jobs_to_assign.append(job)
            except Exception as e:
                # Continue if unable to get job from JobStore
                print(f"[ERROR] {self.name_process}: failed to get job: {e}")

            # Assign jobs to processor
            if jobs_to_assign:
                processor_assignments.append(
                    (processor_resource, jobs_to_assign)
                )

        # Process jobs with assigned processors in parallel
        for processor_resource, jobs in processor_assignments:
            self.env.process(self.delay_resources(processor_resource, jobs))

    def delay_resources(self, processor_resource, jobs):
        """
        Process jobs with processor (integrated for Machine, Worker)
        Takes processing time into account
        """
        move_events = []  # downstream transport completion events

        # Record time and register resources for all jobs
        for job in jobs:
            job.time_waiting_end = self.env.now

            # Register job with processor
            processor_resource.start_job(job)

            if self.logger:
                self.logger.log_event(
                    "Processing",
                    f"Assigning job {job.id_job} to {processor_resource.name}",
                )

            # Record job start time
            job.time_processing_start = self.env.now

            # Record job processing history
            process_step = self.create_process_step(job, processor_resource)
            if not hasattr(job, "processing_history"):
                job.processing_history = []
            job.processing_history.append(process_step)

        # Request processor resource
        request = processor_resource.request()
        yield request

        # Calculate and wait for processing time
        processing_time = processor_resource.processing_time
        yield self.env.timeout(processing_time)

        # Special processing (if needed)
        if hasattr(self, "apply_special_processing"):
            self.apply_special_processing(processor_resource.processor, jobs)

        # Process job completion
        for job in jobs:
            job.time_processing_end = self.env.now

            # Update job history
            for step in job.processing_history:
                if step["process"] == self.name_process and step["end_time"] is None:
                    step["end_time"] = self.env.now
                    step["duration"] = self.env.now - step["start_time"]

            # Track completed jobs
            self.completed_jobs.append(job)

            # Log record
            if self.logger:
                self.logger.log_event(
                    "Processing",
                    f"Completed processing job {job.id_job} on {processor_resource.name}",
                )

            # Send job to next process (or request AMR move)
            ev = self.send_job_to_next(job)
            if ev is not None and hasattr(ev, "callbacks"):
                move_events.append(ev)

        # Wait while holding current resource until downstream transfer completes
        for ev in move_events:
            try:
                yield ev
            except Exception:
                pass

        # Release resources
        self.release_resources(processor_resource, request)

    def release_resources(self, processor_resource, request):
        """
        Release processor resources and process job completion
        """
        # Release processor resource
        processor_resource.release(request)
        processor_resource.finish_jobs()

        # Trigger resource release event (for event-based approach)
        if hasattr(self, "resource_trigger"):
            self.resource_trigger.succeed()
            # Create new trigger immediately
            self.resource_trigger = self.env.event()

        if self.logger:
            self.logger.log_event(
                "Resource",
                f"Released {processor_resource.name} in {self.name_process}",
            )

    def create_process_step(self, job, processor_resource):
        """Create process step for job history"""
        return {
            "process": self.name_process,
            "resource_type": processor_resource.processor_type,
            "resource_id": processor_resource.id,
            "resource_name": processor_resource.name,
            "start_time": job.time_processing_start,
            "end_time": None,
            "duration": None,
        }

    def send_job_to_next(self, job):
        """
        Send job to next process.
        - If an AMR transport is configured, delegate the move to it.
        - Otherwise, push directly into next_process.
        """
        transport = getattr(self, "transport", None)

        # If transport is available, hand off movement to AMR
        if self.next_process and transport is not None:
            if self.name_process == "Proc_Build":
                # Build uses a Build->Stacker->Wash1 two-step move
                return transport.request_build_exit(
                    job=job,
                    from_process=self,
                    to_process_wash1=self.next_process,
                )
            else:
                # Standard inter-process move
                return transport.request_job_move(
                    job=job,
                    from_process=self,
                    to_process=self.next_process,
                )

        # If no AMR transport, move directly to the next process
        if self.next_process:
            if self.logger:
                self.logger.log_event(
                    "Process Flow",
                    f"Moving job {job.id_job} from {self.name_process} to {self.next_process.name_process}",
                )
            self.next_process.add_to_queue(job)
            return None

        # Final process
        if self.logger:
            self.logger.log_event(
                "Process Flow",
                f"Job {job.id_job} completed at {self.name_process} (final process)",
            )
        return None
