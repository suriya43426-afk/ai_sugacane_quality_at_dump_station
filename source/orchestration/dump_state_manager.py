import time
import logging
from enum import Enum

class DumpState(Enum):
    EMPTY_IDLE = 1
    TRUCK_IN = 2
    DUMP_LIFT = 3
    DUMPING_ACTIVE = 4
    DUMPING_EMPTY = 5
    DUMP_DOWN = 6
    TRUCK_OUT = 7
    EMPTY_RESET = 8

class StateManager:
    def __init__(self, dump_id, logger=None):
        self.dump_id = dump_id
        self.state = DumpState.EMPTY_IDLE
        self.log = logger or logging.getLogger(f"StateManager_{dump_id}")
        self.last_state_change = time.time()
        self.session_uuid = None
        self.captured_images = []
        
        # Debounce settings
        self.debounce_time = 2.0 # Seconds to stay in state before transitioning again

    def update(self, front_data, top_data):
        """
        front_data (CH101): truck_detected, lifting, lift_max, lowering
        top_data (CH201): cane_detected, cane_percentage, dumping
        """
        now = time.time()
        if now - self.last_state_change < self.debounce_time:
            return False

        old_state = self.state
        
        # --- Strict AND Logic Transitions ---
        
        # 1 -> 2: Truck (Front) + Cane (Top)
        if self.state == DumpState.EMPTY_IDLE:
            if front_data.get('truck_detected') and top_data.get('cane_detected'):
                self.transition_to(DumpState.TRUCK_IN)
                
        # 2 -> 3: Lifting (Front) + Cane 100% (Top)
        elif self.state == DumpState.TRUCK_IN:
            if front_data.get('lifting') and top_data.get('cane_percentage', 0) >= 90:
                self.transition_to(DumpState.DUMP_LIFT)
                
        # 3 -> 4: Lift Max (Front) + Dumping (Top)
        elif self.state == DumpState.DUMP_LIFT:
            if front_data.get('lift_max') and top_data.get('dumping'):
                self.transition_to(DumpState.DUMPING_ACTIVE)
                
        # 4 -> 5: Lift Max (Front) + No Cane (Top)
        elif self.state == DumpState.DUMPING_ACTIVE:
            # Need to wait for some images to be captured before moving to EMPTY?
            # Or trust the "No Cane" detection.
            if front_data.get('lift_max') and not top_data.get('cane_detected'):
                self.transition_to(DumpState.DUMPING_EMPTY)
                
        # 5 -> 6: Lowering (Front) + No Cane (Top)
        elif self.state == DumpState.DUMPING_EMPTY:
            if front_data.get('lowering') and not top_data.get('cane_detected'):
                self.transition_to(DumpState.DUMP_DOWN)
                
        # 6 -> 7: Truck Present (Front) + No Cane (Top)
        elif self.state == DumpState.DUMP_DOWN:
            if front_data.get('truck_detected') and not top_data.get('cane_detected'):
                self.transition_to(DumpState.TRUCK_OUT)
                
        # 7 -> 8: No Truck (Front) + No Cane (Top)
        elif self.state == DumpState.TRUCK_OUT:
            if not front_data.get('truck_detected') and not top_data.get('cane_detected'):
                self.transition_to(DumpState.EMPTY_RESET)
                
        # 8 -> 1: Auto-Reset or wait for clear
        elif self.state == DumpState.EMPTY_RESET:
            self.transition_to(DumpState.EMPTY_IDLE)

        return self.state != old_state

    def transition_to(self, new_state):
        self.state = new_state
        self.last_state_change = time.time()
        # Reset local capture list if we moved back to IDLE
        if new_state == DumpState.EMPTY_IDLE:
            self.captured_images = []

    def get_capture_trigger(self):
        """Returns IMAGE_X name if current state requirements for capture are met."""
        # IMAGE 1: State 2 (TRUCK_IN)
        if self.state == DumpState.TRUCK_IN and "IMAGE_1" not in self.captured_images:
            return "IMAGE_1"
            
        # IMAGE 2: State 3 (DUMP_LIFT)
        if self.state == DumpState.DUMP_LIFT and "IMAGE_2" not in self.captured_images:
            return "IMAGE_2"
            
        # IMAGE 3 & 4: State 4 (DUMPING_ACTIVE)
        if self.state == DumpState.DUMPING_ACTIVE:
            if "IMAGE_3" not in self.captured_images:
                return "IMAGE_3"
            
            # Image 4 selected via time/area heuristic
            time_in_active = time.time() - self.last_state_change
            if "IMAGE_4" not in self.captured_images and time_in_active > 6.0:
                return "IMAGE_4"
                
        return None

    def mark_captured(self, image_type):
        self.captured_images.append(image_type)
