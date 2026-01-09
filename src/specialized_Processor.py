from base_Processor import Worker, Machine
from config_SimPy import *



class Worker_Inspect(Worker):
    def __init__(self, id_worker):
        super().__init__(
            id_worker, f"Inspector_{id_worker}", PROC_TIME_INSPECT)


class Worker_Support(Worker):
    def __init__(self, id_worker):
        super().__init__(
            id_worker, f"SupportRemover_{id_worker}", PROC_TIME_SUPPORT
        )

class Mach_3DPrint(Machine):
    def __init__(self, id_machine):
        super().__init__(id_machine, "Proc_Build",
                         f"3DPrinter_{id_machine}", PROC_TIME_BUILD, CAPACITY_MACHINE_BUILD)


class Mach_Wash1(Machine):
    def __init__(self, id_machine):
        super().__init__(
            id_machine,
            "Proc_Wash1",
            f"Washer1_{id_machine}",
            PROC_TIME_WASH1,
            CAPACITY_MACHINE_WASH1,
        )

class Mach_Wash2(Machine):
    def __init__(self, id_machine):
        super().__init__(
            id_machine,
            "Proc_Wash2",
            f"Washer2_{id_machine}",
            PROC_TIME_WASH2,
            CAPACITY_MACHINE_WASH2,
        )

class Mach_Dry1(Machine):
    def __init__(self, id_machine):
        super().__init__(
            id_machine,
            "Proc_Dry1",
            f"Dryer1_{id_machine}",
            PROC_TIME_DRY1,
            CAPACITY_MACHINE_DRY1,
        )

class Mach_Dry2(Machine):
    def __init__(self, id_machine):
        super().__init__(
            id_machine,
            "Proc_Dry2",
            f"Dryer2_{id_machine}",
            PROC_TIME_DRY2,
            CAPACITY_MACHINE_DRY2,
        )

class Mach_UV(Machine):
    def __init__(self, id_machine):
        super().__init__(
            id_machine, "Proc_UV", 
            f"UV_{id_machine}", PROC_TIME_UV, CAPACITY_MACHINE_UV
        )

class Worker_AMR(Worker):
    def __init__(self, id_worker):
        super().__init__(
            id_worker,
            f"AMR_{id_worker}",
            PROC_TIME_MOVE_AMR,
        )
        self.mode = "AMR"


class Worker_Mover(Worker):
    def __init__(self, id_worker):
        super().__init__(
            id_worker,
            f"Mover_{id_worker}",
            PROC_TIME_MOVE_MANUAL,
        )
        self.mode = "MANUAL"