# main_Process.py
import simpy
import random
from base_Customer import Item
from base_Job import Job
from base_Process import Process
from base_Processor import Machine, Worker
from log_SimPy import *


class SimpleLogger:
    def __init__(self):
        self.logs = []

    def log_event(self, event_type, message):
        """Log an event with a timestamp"""
        current_time = env.now if 'env' in globals() else 0
        days = int(current_time // (24 * 60))
        hours = int((current_time % (24 * 60)) // 60)
        minutes = int(current_time % 60)
        timestamp = f"{days:02d}:{hours:02d}:{minutes:02d}"
        total_minutes = int(current_time)
        print(f"[{timestamp}] [{total_minutes}] | {event_type}: {message}")
        self.logs.append((event_type, message))


def generate_jobs(num_jobs, items_per_job, job_id_start=1):
    """Create test jobs"""
    jobs = []
    for i in range(num_jobs):
        job_id = job_id_start + i
        # Create virtual patient ID
        patient_id = f"patient_{job_id}"

        # Item class requires (id_patient, id_item) two parameters. id_order is fixed at 0
        items = [Item(0, patient_id, f"item_{job_id}_{j}")
                 for j in range(items_per_job)]
        job = Job(job_id, items)
        jobs.append(job)
    return jobs


def run_process_validation():
    """Process Class Validation Test Based on Integrated Interface"""
    print("================ Process Class Validation Test Based on Integrated Interface ================")

    # Set up simulation environment
    global env
    env = simpy.Environment()
    logger = SimpleLogger()

    # Create basic processes (just 2)
    process_a = Process("Process_A", env, logger)
    process_b = Process("Process_B", env, logger)

    # Register processors for each process
    machine1 = Machine(1, "Process_A", f"Machine_A{1}", 30, 2)
    process_a.register_processor(machine1)
    machine2 = Machine(2, "Process_A", f"Machine_A{2}", 30, 1)
    process_a.register_processor(machine2)
    worker = Worker(1, f"Worker_B1", 15)
    process_b.register_processor(worker)

    # Set up process connections
    process_a.connect_to_next_process(process_b)

    # Create test jobs and assign to first process
    jobs = generate_jobs(4, 2)  # 4 jobs, 2 items each
    print(f"\n{len(jobs)} test jobs created")

    for job in jobs:
        print(f"Assigned job {job.id_job} to Process A")
        process_a.add_to_queue(job)

    # Run simulation
    print("\nStarting simulation...")
    sim_duration = 500  # Test simulation duration (minutes)
    env.process(run_until(env, sim_duration))
    env.run(until=sim_duration)  # Explicitly add until parameter

    # Check results
    print("\n================ Simulation Results ================")
    print(f"Process A completed jobs: {len(process_a.completed_jobs)}")
    print(f"Process B completed jobs: {len(process_b.completed_jobs)}")

    # Check job history by time
    if process_b.completed_jobs:
        print("\nProcessing time by process for completed jobs:")
        for job in process_b.completed_jobs:
            print(f"\nJob {job.id_job} history:")
            for step in job.processing_history:
                start_time = step['start_time']
                end_time = step['end_time'] if step['end_time'] is not None else 'N/A'
                duration = step['duration'] if step['duration'] is not None else 'N/A'
                print(
                    f"  {step['process']} ({step['resource_name']}): {start_time}min -> {end_time}min (duration: {duration}min)")

    # Check queue length history
    print("\nQueue length changes for each process:")
    for proc, name in [(process_a, "Process A"), (process_b, "Process B")]:
        if proc.job_store.queue_length_history:
            print(f"\n{name} queue length changes:")
            for time, length in proc.job_store.queue_length_history:
                print(f"  Time {time}min: Queue length = {length}")

    print("\n================ Test Ended ================")


def run_until(env, duration):
    """Run simulation until specified time"""
    yield env.timeout(duration)


if __name__ == "__main__":
    # Set random seed (for reproducible results)
    random.seed(42)

    # Directly run generator function
    run_process_validation()
