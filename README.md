# AI Sugarcane Quality Detection at Dump Station

This is a production-ready edge AI system for multi-station sugarcane dump monitoring.

## System Architecture

The system uses a state-based approach to monitor 8 dump stations using 16 camera channels (Front & Top views).

### Core Components
- **FSM State Machine**: Strict 8-state transition logic requiring synchronized detections from both Front (Truck) and Top (Cane) cameras.
- **Dual Model Inference**: 
  - `objectdetection.pt`: Truck & License Plate (Front View)
  - `classification.pt`: Sugarcane quality & status (Top View)
- **SQLite Configuration**: All cameras and site metadata are loaded dynamically from a local database (`sugarcane_v2.db`).
- **Reporting**: Automatically generates a 2x2 merged image for every completed dump session.

## State Machine & Capture Rules

| State | Name | Logic | Capture Trigger |
| :--- | :--- | :--- | :--- |
| 1 | EMPTY_IDLE | No Truck + No Cane | - |
| 2 | TRUCK_IN | Truck + Cane | **Image 1**: LPR + Timestamp |
| 3 | DUMP_LIFT | Lifting + Cane 100% | **Image 2**: Sugarcane 100% |
| 4 | DUMPING_ACTIVE| Lift Max + Dumping | **Image 3 & 4**: ~50% / ~25% |
| 5 | DUMPING_EMPTY | Lift Max + No Cane | - |
| 6 | DUMP_DOWN | Lowering + No Cane | - |
| 7 | TRUCK_OUT | Truck Present + No Cane | - |
| 8 | EMPTY_RESET | No Truck + No Cane | Session Finalized |

## Database Schema (SQLite)
The system uses 8 standardized tables:
1. `factory_master`: Site configuration.
2. `dump_master`: Dump station definitions.
3. `camera_master`: RTSP URLs and view types.
4. `dump_camera_map`: Binding cameras to dumps.
5. `dump_session`: UUID-based session tracking.
6. `dump_images`: Individual capture metadata.
7. `dump_state_log`: Audit trail for transitions.
8. `system_config`: Key-Value settings.

## Installation & Running

1. **Setup**: Run `setup.bat` to create the virtual environment and install dependencies.
2. **Configuration**: Edit the SQLite database directly for camera URL changes.
3. **Execution**: Run `run_realtime.bat` to start the monitoring dashboard.
4. **Updates**: Run `update.bat` to pull changes and update the environment.

## Output Structure
Filtered reports are saved to the `results/` directory as high-resolution merged images with standardized headers for full traceability.
