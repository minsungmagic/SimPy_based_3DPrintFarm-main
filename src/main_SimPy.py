# main.py
import simpy
import random
from base_Customer import Customer
from manager import Manager
from log_SimPy import Logger
from config_SimPy import *


def run_simulation(sim_duration=SIM_TIME):
    """Run the manufacturing simulation"""
    print("================ Manufacturing Process Simulation ================")

    # Setup simulation environment
    env = simpy.Environment()

    # Create logger with env
    logger = Logger(env)

    # Create manager and provide logger
    manager = Manager(env, logger)

    # Create customer to generate orders
    Customer(env, manager, logger)

    # Run simulation
    print("\nStarting simulation...")
    print(f"Simulation will run for {sim_duration} minutes")

    # Run simulation
    env.run(until=sim_duration)

    # Collect and display results
    print("\n================ Simulation Results ================")

    # Get basic statistics from manager
    manager_stats = manager.collect_statistics()

    # Basic results
    print(f"Completed jobs by process:")
    print(f"  Build:   {manager_stats['build_completed']}")
    print(f"  Wash1:   {manager_stats['wash1_completed']}")
    print(f"  Dry1:    {manager_stats['dry1_completed']}")
    print(f"  Support: {manager_stats['support_completed']}")
    print(f"  Inspect: {manager_stats['inspect_completed']}")
    print(f"  Wash2:   {manager_stats['wash2_completed']}")
    print(f"  Dry2:    {manager_stats['dry2_completed']}")
    print(f"  UV:      {manager_stats['uv_completed']}")

    print(f"\nRemaining defective items: {manager_stats['defective_items']}")

    print("\nFinal queue lengths:")
    print(f"  Build queue:   {manager_stats['build_queue']}")
    print(f"  Wash1 queue:   {manager_stats['wash1_queue']}")
    print(f"  Dry1 queue:    {manager_stats['dry1_queue']}")
    print(f"  Support queue: {manager_stats['support_queue']}")
    print(f"  Inspect queue: {manager_stats['inspect_queue']}")
    print(f"  Wash2 queue:   {manager_stats['wash2_queue']}")
    print(f"  Dry2 queue:    {manager_stats['dry2_queue']}")
    print(f"  UV queue:      {manager_stats['uv_queue']}")

    print("\nPlate / Stacker status:")
    print(f"  Pre-build plates : {manager_stats['pre_build_plates']}")
    print(f"  Post-build plates: {manager_stats['post_build_plates']}")

    # Collect detailed statistics and visualize if enabled
    if DETAILED_STATS_ENABLED or GANTT_CHART_ENABLED or VIS_STAT_ENABLED:
        print("\nCollecting detailed statistics...")
        processes = manager.get_processes()
        stats = logger.collect_statistics(processes)

        # Visualize results if enabled
        if GANTT_CHART_ENABLED or VIS_STAT_ENABLED:
            logger.visualize_statistics(stats, processes)

    print("\n================ Simulation Ended ================")


if __name__ == "__main__":
    # Set random seed for reproducibility
    random.seed(42)

    # Run the simulation
    run_simulation()
