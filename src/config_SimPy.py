import random

# ============================================================
# 0. Common simulation settings
# ============================================================
RANDOM_SEED = 42

# Simulation time (minutes) - 1 week
SIM_TIME = 7 * 24 * 60  # (unit: minutes)

# Logging / visualization options
EVENT_LOGGING          = True   # Console logging
GANTT_CHART_ENABLED    = True   # Gantt chart
VIS_STAT_ENABLED       = False  # Queue/time stats chart
DETAILED_STATS_ENABLED = True   # Detailed stats output
SHOW_GANTT_DEBUG       = False  # Gantt debug flag

# String constants (state / type)
IDLE     = "IDLE"
LOADED   = "LOADED"
PRINTING = "PRINTING"

JOB   = "JOB"
PLATE = "PLATE"
BOX   = "BOX"
AMR   = "AMR"
UV    = "UV"
AMR_  = "AMR_"
UV_   = "UV_"
MANUAL = "MANUAL"

ID         = "ID"
QUEUE_LAST = "QUEUE_LAST"
FIFO       = "FIFO"

# ============================================================
# 1. Build / Washer / Dryer / UV equipment settings
# ============================================================
STACKER_CAPACITY = 10  # Store up to 10 plates at once (adjust if needed)

# ---------- 1-1) Build (3D printers) ----------
# Number of printers
NUM_MACHINES_BUILD = 5

# Jobs per printer processed simultaneously
CAPACITY_MACHINE_BUILD = 1

# Build time (minutes) - user-specified
PROC_TIME_BUILD = 500  # Process time for build (unit: minutes)

# Defect rate in build process
DEFECT_RATE_PROC_BUILD = 0.07  # 7% defect rate in build process

# ---------- 1-2) Washer / Dryer / UV ----------
# Number of washers/dryers
# User defined only one wash/dry stage,
# but the model uses Wash1/2 and Dry1/2, so match the values.
NUM_MACHINES_WASH1 = 1
NUM_MACHINES_WASH2 = 1
NUM_MACHINES_DRY1  = 1
NUM_MACHINES_DRY2  = 1

# Number of UV machines
NUM_MACHINES_UV = 1

# Jobs per machine processed simultaneously
# User provided CAPACITY_MACHINE_WASH = 2 and CAPACITY_MACHINE_DRY = 2,
# apply the same values to both stage 1 and stage 2 machines.
CAPACITY_MACHINE_WASH1 = 1
CAPACITY_MACHINE_WASH2 = 1
CAPACITY_MACHINE_DRY1  = 1
CAPACITY_MACHINE_DRY2  = 1
CAPACITY_MACHINE_UV    = 1

# Process times (minutes)
# Apply user-provided PROC_TIME_WASH = 120, PROC_TIME_DRY = 120
# to Wash1/2 and Dry1/2.
PROC_TIME_WASH1 = 120  # Wash stage 1
PROC_TIME_WASH2 = 120  # Wash stage 2
PROC_TIME_DRY1  = 120  # Dry stage 1
PROC_TIME_DRY2  = 120  # Dry stage 2
PROC_TIME_UV    = 20   # UV time (keep default unless adjusted)


# ============================================================
# 2. Support removal / inspection (Inspect)
# ============================================================

# Support removal time (minutes)
PROC_TIME_SUPPORT = 30

# Inspection time (minutes)
# User set PROC_TIME_INSPECT = 30
PROC_TIME_INSPECT = 30  # Process time for inspect per item (unit: minutes)

# Support removal workers
NUM_WORKERS_SUPPORT = 1

# Inspection workers
NUM_WORKERS_IN_INSPECT = 1  # Keep user setting

# ============================================================
# 3. Build plate / box / rework policy
# ============================================================

# Max items per build plate
# User setting: PALLET_SIZE_LIMIT = 50
PALLET_SIZE_LIMIT = 50      # Up to 50 items per build plate

# Items per box (not specified by user, keep default)
BOX_SIZE = 40               # 20 items per box

# Initial build plate count (plates in stacker at time 0)
INITIAL_NUM_BUILD_PLATES = 10

# Pre/post stack caps (adjust if needed)
MAX_PRE_BUILD_PLATES  = INITIAL_NUM_BUILD_PLATES
MAX_POST_BUILD_PLATES = INITIAL_NUM_BUILD_PLATES

# Defective items per rework job
# User setting: POLICY_NUM_DEFECT_PER_JOB = 10
POLICY_NUM_DEFECT_PER_JOB = 10

# Order -> job conversion policy
#   "MAX_PER_JOB": fill up to PALLET_SIZE_LIMIT
POLICY_ORDER_TO_JOB = "MAX_PER_JOB"
MAX_PER_JOB         = "MAX_PER_JOB"

# How to enqueue rework jobs
# User setting: "QUEUE_LAST"
POLICY_REPROC_SEQ_IN_QUEUE = "QUEUE_LAST"

# Dispatch policy for pulling jobs from the queue
# User setting: POLICY_DISPATCH_FROM_QUEUE = "FIFO"
POLICY_DISPATCH_FROM_QUEUE = "FIFO"

# ============================================================
# 4. Transport (AMR / manual movers) settings
# ============================================================

# ======== Transport (STACKER <-> process movement) ========

# Move mode: "AMR" or "MANUAL"
MOVE_MODE = "AMR"   # or "MANUAL"

# Number of AMRs / manual movers
NUM_AMR = 1          # One AMR
NUM_MANUAL_MOVERS = 2       # Example: two manual movers in parallel

# Distance between stations (m)
DIST_BETWEEN_STATIONS = 5.0

# Speed (m/min) - reasonable defaults
SPEED_AMR_M_PER_MIN    = 30.0   # ~0.5 m/s
SPEED_WORKER_M_PER_MIN = 60.0   # ~1.0 m/s

# Travel time (minutes)
PROC_TIME_MOVE_AMR    = DIST_BETWEEN_STATIONS / SPEED_AMR_M_PER_MIN
PROC_TIME_MOVE_MANUAL = DIST_BETWEEN_STATIONS / SPEED_WORKER_M_PER_MIN


# ============================================================
# 5. Customer / order settings
# ============================================================

# Order cycle / due date (default: 7 * 24 * 60)
CUST_ORDER_CYCLE = 7 * 24 * 60  # Customer order cycle (1 week in minutes)
ORDER_DUE_DATE   = 7 * 24 * 60  # Order due date (1 week in minutes)

# Order arrival control
#   - "continuous": create orders when plates are available (check interval below)
#   - "interval": create orders every ORDER_INTERVAL minutes
#   - "count": create ORDER_COUNT orders then stop (uses ORDER_INTERVAL)
ORDER_ARRIVAL_MODE = "count"
ORDER_INTERVAL = None
ORDER_COUNT = None
ORDER_CONTINUOUS_CHECK_INTERVAL = None

ORDER_MODE_DEFAULTS = {
    "continuous": {
        "ORDER_INTERVAL": CUST_ORDER_CYCLE,
        "ORDER_COUNT": 0,
        "ORDER_CONTINUOUS_CHECK_INTERVAL": 1,
    },
    "interval": {
        "ORDER_INTERVAL": 60,
        "ORDER_COUNT": 0,
        "ORDER_CONTINUOUS_CHECK_INTERVAL": 1,
    },
    "count": {
        "ORDER_INTERVAL": 10,
        "ORDER_COUNT": 100,
        "ORDER_CONTINUOUS_CHECK_INTERVAL": 1,
    },
}


def apply_order_mode_defaults():
    mode = str(ORDER_ARRIVAL_MODE).lower()
    defaults = ORDER_MODE_DEFAULTS.get(mode, ORDER_MODE_DEFAULTS["interval"])

    global ORDER_INTERVAL, ORDER_COUNT, ORDER_CONTINUOUS_CHECK_INTERVAL
    if ORDER_INTERVAL is None:
        ORDER_INTERVAL = defaults["ORDER_INTERVAL"]
    if ORDER_COUNT is None:
        ORDER_COUNT = defaults["ORDER_COUNT"]
    if ORDER_CONTINUOUS_CHECK_INTERVAL is None:
        ORDER_CONTINUOUS_CHECK_INTERVAL = defaults["ORDER_CONTINUOUS_CHECK_INTERVAL"]


apply_order_mode_defaults()

# Order size ranges
ORDER_NUM_PATIENTS_MIN = 5
ORDER_NUM_PATIENTS_MAX = 5
ORDER_NUM_ITEMS_MIN = 50
ORDER_NUM_ITEMS_MAX = 70

# Order size helpers

def NUM_PATIENTS_PER_ORDER():
    # User setting: random.randint(5, 5) => always 5
    return random.randint(ORDER_NUM_PATIENTS_MIN, ORDER_NUM_PATIENTS_MAX)

# Items per patient

def NUM_ITEMS_PER_PATIENT():
    # User setting: random.randint(50, 70)
    return random.randint(ORDER_NUM_ITEMS_MIN, ORDER_NUM_ITEMS_MAX)
