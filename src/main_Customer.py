import simpy
import time
import random
from config_SimPy import *
from base_Customer import Customer, SimpleOrderReceiver


class SimpleLogger:
    """Class providing simple logging functionality"""

    def __init__(self, env):
        self.env = env

    def log_event(self, event_type, message):
        """Log events with timestamp"""
        current_time = self.env.now
        days = int(current_time // (24 * 60))
        hours = int((current_time % (24 * 60)) // 60)
        minutes = int(current_time % 60)
        timestamp = f"{days:02d}:{hours:02d}:{minutes:02d}"
        print(f"[{timestamp}] {event_type}: {message}")


def run_customer_simulation(seed=None):
    """
    Simulate only the Customer order generation process.

    Args:
        seed (int, optional): Random seed for reproducibility

    Returns:
        SimpleOrderReceiver: Order receiver object with collected orders
    """
    # Set random seed if provided
    if seed is not None:
        random.seed(seed)

    # Create simulation environment
    env = simpy.Environment()

    # Create simple logger
    logger = SimpleLogger(env)

    # Create order receiver
    order_receiver = SimpleOrderReceiver(env, logger)

    # Create and start customer
    Customer(env, order_receiver, logger)

    # Start time measurement
    start_time = time.time()

    # Run simulation
    env.run(until=SIM_TIME)

    # End time measurement
    end_time = time.time()
    run_time = end_time - start_time
    print(f"\nSimulation completed (Runtime: {run_time:.2f} seconds)")

    # Basic summary statistics
    print("\n========================================")
    print("Simulation Summary:")
    print(f"Total orders created: {len(order_receiver.received_orders)}")
    print(
        f"Total patients: {sum(order.num_patients for order in order_receiver.received_orders)}")

    # Calculate total items
    total_items = 0
    for order in order_receiver.received_orders:
        for patient in order.list_patients:
            total_items += len(patient.list_items)
    print(f"Total items: {total_items}")

    # Calculate average patients per order
    if order_receiver.received_orders:
        avg_patients = sum(order.num_patients for order in order_receiver.received_orders) / \
            len(order_receiver.received_orders)
        print(f"Average patients per order: {avg_patients:.2f}")

    # Calculate average items per order
    if total_items > 0 and order_receiver.received_orders:
        avg_items_per_order = total_items / len(order_receiver.received_orders)
        print(f"Average items per order: {avg_items_per_order:.2f}")

    return order_receiver


if __name__ == "__main__":
    # Set random seed for reproducibility
    RANDOM_SEED = 42

    # Run simulation
    print(
        f"\nStarting simulation (Duration: {SIM_TIME} minutes, {SIM_TIME/60/24:.1f} days)")
    order_receiver = run_customer_simulation(seed=RANDOM_SEED)

    # Print order details
    print("\nGenerated Order Details:")
    for i, order in enumerate(order_receiver.received_orders, 1):
        total_patient_items = sum(len(patient.list_items)
                                  for patient in order.list_patients)
        print(
            f"Order {order.id_order}: {order.num_patients} patients, {total_patient_items} items")

        # Show only first 5 orders in detail if there are too many
        if i >= 5 and len(order_receiver.received_orders) > 10:
            print(
                f"... and {len(order_receiver.received_orders) - 5} more orders")
            break
