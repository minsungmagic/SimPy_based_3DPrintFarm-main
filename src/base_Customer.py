from config_SimPy import *


class Item:
    """
    Class representing an item in the system.

    Attributes:
        id_order: ID of the order this item belongs to
        id_patient: ID of the patient this item belongs to
        id_item: ID of this item
        type_item: Type of item (e.g., aligner, retainer)
        is_completed: Flag indicating if the manufacturing of the item is completed
        is_defect: Flag indicating if the item is defective
    """

    def __init__(self, id_order, id_patient, id_item):
        self.id_order = id_order
        self.id_patient = id_patient
        self.id_item = id_item
        self.type_item = "aligner"  # default
        self.is_completed = False
        self.is_defect = False


class Patient:
    """
    Class representing a patient in the system.

    Attributes:
        id_order: ID of the order this patient belongs to
        id_patient: ID of this patient
        num_items: Number of items for this patient
        list_items: List of items for this patient
        is_completed: Flag indicating if the manufacturing of all items for this patient is completed
        item_counter: Counter for item IDs
    """

    def __init__(self, id_order, id_patient):
        """
        Create a patient with the given IDs.

        Args:
            id_order: ID of the order this patient belongs to
            id_patient: ID of this patient
        """
        self.id_order = id_order
        self.id_patient = id_patient
        self.num_items = NUM_ITEMS_PER_PATIENT()
        self.list_items = []
        self.is_completed = False
        self.item_counter = 1

        # Create items for this patient using the provided function
        self.list_items = self._create_items_for_patient(
            self.id_order, self.id_patient, self.num_items)

    def _create_items_for_patient(self, id_order, id_patient, num_items):
        """Create items for a patient"""
        items = []
        for _ in range(num_items):
            item_id = self._get_next_item_id()
            items.append(Item(id_order, id_patient, item_id))
        return items

    def _get_next_item_id(self):
        """Get next item ID and increment counter"""
        item_id = self.item_counter
        self.item_counter += 1
        return item_id

    def check_completion(self):
        """Check if all items for this patient are completed"""
        if all(item.is_completed for item in self.list_items):
            self.is_completed = True
        return self.is_completed


class Order:
    """
    Class representing an order in the system.

    Attributes:
        id_order: ID of this order
        num_patients: Number of patients for this order
        list_patients: List of patients for this order
        due_date: Due date of this order
        time_start: Start time of this order
        time_end: End time of this order
        patient_counter: Counter for patient IDs

    """

    def __init__(self, id_order):
        """
        Create an order with the given ID.

        Args:
            id_order: ID of this order 
        """
        self.id_order = id_order
        self.num_patients = NUM_PATIENTS_PER_ORDER()
        self.list_patients = []
        self.due_date = ORDER_DUE_DATE
        self.time_start = None
        self.time_end = None
        self.patient_counter = 1

        # Create patients for this order using the provided function
        self.list_patients = self._create_patients_for_order(
            self.id_order, self.num_patients)

    def _create_patients_for_order(self, id_order, num_patients):
        """Create patients for an order"""
        patients = []
        for _ in range(num_patients):
            patient_id = self._get_next_patient_id()
            patients.append(Patient(id_order, patient_id))
        return patients

    def _get_next_patient_id(self):
        """Get next patient ID and increment counter"""
        patient_id = self.patient_counter
        self.patient_counter += 1
        return patient_id

    def check_completion(self):
        """Check if all patients in this order are completed"""
        if all(patient.check_completion() for patient in self.list_patients):
            return True
        return False


class Customer:
    """
    Class representing a customer in the system.
    """

    def __init__(self, env, order_receiver, logger):
        self.env = env
        self.order_receiver = order_receiver
        self.logger = logger

        # Initialize ID counters
        self.order_counter = 1

        # Automatically start the process when the Customer is created
        self.processing = env.process(self.create_order())

    def get_next_order_id(self):
        """Get next order ID and increment counter"""
        order_id = self.order_counter
        self.order_counter += 1
        return order_id

    def _has_idle_plate(self):
        receiver = self.order_receiver
        if receiver is None:
            return False
        stacker = getattr(receiver, 'stacker', None)
        if stacker is not None and hasattr(stacker, 'get_idle_plates'):
            try:
                return len(stacker.get_idle_plates()) > 0
            except Exception:
                pass
        if hasattr(receiver, 'pre_build_plate_count'):
            try:
                return receiver.pre_build_plate_count > 0
            except Exception:
                return False
        return False


    def create_order(self):
        """Create orders periodically"""
        mode = str(ORDER_ARRIVAL_MODE).lower()
        order_interval = ORDER_INTERVAL if ORDER_INTERVAL is not None else CUST_ORDER_CYCLE
        max_orders = ORDER_COUNT if ORDER_COUNT is not None else 0
        check_interval = getattr(
            __import__("config_SimPy"),
            "ORDER_CONTINUOUS_CHECK_INTERVAL",
            1,
        )
        created = 0

        if mode == "count" and max_orders <= 0:
            return

        while True:
            if mode == "continuous" and not self._has_idle_plate():
                yield self.env.timeout(check_interval)
                continue

            # 1) Create a new order
            order_id = self.get_next_order_id()
            order = Order(order_id)
            order.time_start = self.env.now

            # 2) Web event log: order created
            if self.logger is not None:
                total_items = sum(len(p.list_items) for p in order.list_patients)
                try:
                    self.logger.log_web_event(
                        "order",
                        {
                            "order_id": order.id_order,
                            "stage": "created",
                            "time": float(self.env.now),
                            "num_patients": order.num_patients,
                            "num_items": total_items,
                        },
                    )
                except AttributeError:
                    # Ignore if log_web_event is unavailable
                    pass

            # 3) Send the order
            self.send_order(order)

            # 4) Update created count
            created += 1

            if mode == "count" and created >= max_orders:
                return

            if mode in ("interval", "count"):
                yield self.env.timeout(order_interval)
            elif mode == "continuous":
                yield self.env.timeout(0)
            else:
                yield self.env.timeout(CUST_ORDER_CYCLE)

    def send_order(self, order):
        """Send the order to the receiver"""
        # Web event log: when the order is handed to Manager (production line)
        if self.logger is not None:
            total_items = sum(len(p.list_items) for p in order.list_patients)
            try:
                self.logger.log_web_event(
                    "order",
                    {
                        "order_id": order.id_order,
                            "stage": "sent_to_manager",
                            "time": float(self.env.now),
                            "num_patients": order.num_patients,
                            "num_items": total_items,
                    },
                )
            except AttributeError:
                pass

        # Pass through to Manager as before
        self.order_receiver.receive_order(order)



class OrderReceiver:
    """Interface for order receiving objects"""

    def receive_order(self, order):
        """Method to process orders (implemented by subclasses)"""
        pass


class SimpleOrderReceiver(OrderReceiver):
    """Simple order receiver for testing"""

    def __init__(self, env, logger=None):
        self.env = env
        self.logger = logger
        self.received_orders = []

    def receive_order(self, order):
        """Receive order and log it"""
        self.received_orders.append(order)
        self.logger.log_event(
            "Order", f"OrderReceiver recevied Order {order.id_order} (Patients: {order.num_patients}, Total items: {sum(len(patient.list_items) for patient in order.list_patients)})")
