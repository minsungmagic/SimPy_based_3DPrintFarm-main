import simpy


class Job:
    """
    Job class to represent a job in the manufacturing process

    Attributes:
        id_job (int): Unique job identifier
        workstation (dict): Current workstation assignment
        list_items (list): List of items in the job
        job_type (str): Job type such as 'plate', 'box', 'rework'
        build_plate_id (int|None): Build plate ID this job is on
        time_processing_start (float): Time when processing started
        time_processing_end (float): Time when processing ended
        time_waiting_start (float): Time when waiting started
        time_waiting_end (float): Time when waiting ended
        is_reprocess (bool): Flag for reprocessed jobs
        processing_history (list): List of processing history
    """

    def __init__(self, id_job, list_items, workstation=None, job_type="plate"):
        self.id_job = id_job
        self.workstation = {"Process": None, "Machine": None, "Worker": None}
        self.list_items = list_items
        self.job_type = job_type

        # Which build plate this job is on (None if not assigned)
        self.build_plate_id = None

        self.time_processing_start = None
        self.time_processing_end = None
        self.time_waiting_start = None
        self.time_waiting_end = None
        self.is_reprocess = False  # Flag for reprocessed jobs

        # Add processing history to track jobs across all processes
        self.processing_history = []  # Will store each process step details


class JobStore(simpy.Store):
    """
    Job queue management class that inherits SimPy Store

    Attributes:
        env (simpy.Environment): Simulation environment
        name (str): Name of the JobStore
        queue_length_history (list): Queue length
    """

    def __init__(self, env, name="JobStore"):
        super().__init__(env)
        self.name = name
        self.queue_length_history = []  # Track queue length history

    def put(self, item):
        """Add Job to Store (override)"""
        result = super().put(item)
        # Record queue length
        self.queue_length_history.append((self._env.now, len(self.items)))
        return result

    def get(self):
        """Get Job from queue (override)"""
        result = super().get()
        # Record queue length when getting result

        # Use event chain instead of callback
        def process_get(env, result):
            job = yield result
            self.queue_length_history.append((self._env.now, len(self.items)))
            return job

        return self._env.process(process_get(self._env, result))

    @property
    def is_empty(self):
        """Check if queue is empty"""
        return len(self.items) == 0

    @property
    def size(self):
        """Current queue size"""
        return len(self.items)
