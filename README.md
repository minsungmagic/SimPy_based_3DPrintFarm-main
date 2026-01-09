# SimPy based 3D Print Farm

## How to Run
### 1) Run the full simulation
```bash
cd src
python main_SimPy.py
```

### 2) Test only order generation
```bash
cd src
python main_Customer.py
```

### 3) Run the web simulator
```bash
cd src
python run_app.py
```
Open `http://127.0.0.1:8000` in a browser.

## Default Settings
Configuration lives in `src/config_SimPy.py`.
- Simulation time: `SIM_TIME`
- Machine counts/capacity: `NUM_MACHINES_*`, `CAPACITY_MACHINE_*`
- Process times: `PROC_TIME_*`
- Defect rate: `DEFECT_RATE_PROC_BUILD`
- Movement (AMR/manual): `MOVE_MODE`, `NUM_AMR`, `NUM_MANUAL_MOVERS`
- Order generation: `ORDER_ARRIVAL_MODE`, `ORDER_INTERVAL`, `ORDER_COUNT`
- Plate/box policies: `PALLET_SIZE_LIMIT`, `BOX_SIZE`, `POLICY_*`

When using the web UI, only the parameters whitelisted in `web_sim.py` can be overridden.

## File Roles
### Core logic
- `src/manager.py` : Orchestration, plates/AMR management, statistics
- `src/base_Process.py` : Base process (queueing, resource allocation, flow)
- `src/base_Processor.py` : Machine/Worker models and SimPy Resource wrapper
- `src/base_Job.py` : Job and JobStore definitions
- `src/specialized_Process.py` : Process-specific logic (Build/Wash/Dry/Inspect/UV)
- `src/specialized_Processor.py` : Machine/worker classes per process
- `src/base_Customer.py` : Customer/Order/Patient/Item models and order generation

### Execution and visualization
- `src/main_SimPy.py` : Full simulation entry point
- `src/main_Customer.py` : Order-generation test script
- `src/main_Process.py` : Basic process validation script
- `src/log_SimPy.py` : Logging, statistics, Gantt visualization
- `src/web_sim.py` : FastAPI web simulator
- `src/run_app.py` : Web server entry point
- `src/web_template.html` : Web UI template
- `src/viz_trace.py` : Simple animation trace generator

## Required Modules
Full set for `src/web_sim.py`:
- simpy
- fastapi
- uvicorn
- pydantic
- pandas
- numpy
- plotly

Install example:
```bash
pip install simpy fastapi uvicorn pydantic pandas numpy plotly
```

## Notes
- Process flow: Build -> Wash1 -> Dry1 -> Support -> Inspect -> Wash2 -> Dry2 -> UV
- Inspect collects good items into box jobs; defects generate rework jobs
- AMR moves are handled by a global priority transport manager
- Statistics and Gantt charts are driven by `log_SimPy.py`

## Operation scenario
```mermaid
sequenceDiagram
    participant C as Customer
    participant M as Manager
    participant P as 3D Printers
    participant WM as Washing Machines
    participant DM as Drying Machines
    participant IW as Inspect Workers

    %% Process: Order to Job Creation
    autonumber
    C->>M: Creates and sends order
    M->>P: Converts order into job and sends to 3D Printers

    %% Process 1: Printing Process
    P-->>P: Builds the object

    %% Process 2: Washing Process
    P->>WM: Sends job to Washing Machines
    WM-->>WM: Performs washing

    %% Process 3: Drying Process
    WM->>DM: Sends job to Drying Machines
    DM-->>DM: Performs air-drying

    %% Process 4: Inspection Process
    DM->>IW: Sends job to Inspect Workers
    loop Each Item in Job
        IW-->>IW: Inspects item for defects
        alt Defect Found
            IW->>P: Creates new job for defective items and sends to 3D Printers
            Note right of P: Restart from 3D Printers
        else Good Item
            IW-->>IW: Keeps item as completed
        end
    end
```
