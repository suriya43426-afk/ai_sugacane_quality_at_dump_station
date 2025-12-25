import os
import sys
import subprocess
import cv2
import numpy as np
from datetime import datetime

class SystemTester:
    def __init__(self, paths, cfg, logger, factory, total_lanes):
        self.paths = paths
        self.cfg = cfg
        self.logger = logger
        self.factory = factory
        self.total_lanes = total_lanes

    def run_e2e_test(self, trigger_ch, trigger_frame):
        """
        Executes the E2E State Machine Test.
        Returns: (success: bool, logs: list[str])
        """
        logs = []
        try:
            timestamp = datetime.now()
            dt_str = timestamp.strftime("%Y%m%d-%H%M%S") 
            
            logs.append(f"TEST E2E: Starting State Machine Check (Trigger: {trigger_ch})")
            
            # --- Step 1: Generate Images ---
            save_dir = self.cfg.get("images_path", "Images")
            if not os.path.isabs(save_dir):
                save_dir = os.path.join(self.paths.project_root, save_dir)
            os.makedirs(save_dir, exist_ok=True)
            
            generated_files = []
            
            for lane_idx in range(1, self.total_lanes + 1):
                # Calculate camera codes for this lane (formula from run_ai_daily)
                base_cam_idx = (lane_idx - 1) * 4
                cams = [101 + (base_cam_idx*100) + (i*100) for i in range(4)]
                
                for code in cams:
                    fname = f"{dt_str}_{self.factory}_{code}.jpg"
                    fpath = os.path.join(save_dir, fname)
                    
                    img_data = None
                    if str(code) == str(trigger_ch):
                        img_data = trigger_frame 
                    else:
                        # Dummy Black Image
                        img_data = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(img_data, f"L{lane_idx} DUMMY {code}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                        
                    cv2.imwrite(fpath, img_data)
                    generated_files.append(fpath)
            
            logs.append(f"  > Generated {len(generated_files)} test images for {self.total_lanes} Lanes")
            
            # --- Step 2: Run Daily AI Process ---
            logs.append("  > Executing Batch AI Process (run_ai_daily)...")
            script_daily = os.path.join(self.paths.project_root, "source", "run_ai_daily.py")
            
            res_daily = subprocess.run(
                [sys.executable, script_daily],
                capture_output=True,
                text=True
            )
            
            if res_daily.returncode != 0:
                self.logger.error(f"Daily Process Failed: {res_daily.stderr}")
                logs.append(f"ERROR: Batch Process Failed: {res_daily.stderr[:100]}...")
                return False, logs
            
            logs.append("  > Batch Process Complete.")

            # --- Step 3: Verify Output ---
            results_root = self.cfg.get("results_path", "Results")
            if not os.path.isabs(results_root):
                results_root = os.path.join(self.paths.project_root, results_root)
            
            subfolders = sorted([f.path for f in os.scandir(results_root) if f.is_dir()], key=lambda x: os.path.getmtime(x))
            latest_result_dir = subfolders[-1] if subfolders else None
            
            success_verify = False
            report_path = os.path.join(results_root, f"Test_Report_{dt_str}.txt")
            
            with open(report_path, "w", encoding="utf-8") as rpt:
                rpt.write("==========================================\n")
                rpt.write(f"      E2E TEST REPORT: {dt_str}\n")
                rpt.write("==========================================\n")
                rpt.write(f"Trigger Camera: {trigger_ch}\n")
                rpt.write(f"Simulated Lanes: 1 to {self.total_lanes}\n")
                rpt.write(f"Generated Inputs:\n")
                for f in generated_files:
                    rpt.write(f" - {os.path.basename(f)}\n")
                
                rpt.write("\n[Daily AI Process Log]\n")
                rpt.write(res_daily.stderr if res_daily.stderr else "No Errors.\n")
                
                rpt.write("\n[Output Verification]\n")
                if latest_result_dir:
                    ai_images_dir = os.path.join(latest_result_dir, "ai_images")
                    found_imgs = os.listdir(ai_images_dir) if os.path.exists(ai_images_dir) else []
                    matches = [x for x in found_imgs if dt_str in x]
                    
                    if matches:
                        success_verify = True
                        rpt.write(f"SUCCESS: Found {len(matches)} merged outputs:\n")
                        for m in matches:
                             rpt.write(f" - {m}\n")
                             rpt.write(f"   Path: {os.path.join(ai_images_dir, m)}\n")
                    else:
                        rpt.write("FAILED: No output image found matching timestamp.\n")
                else:
                    rpt.write("FAILED: No Results folder found.\n")
                
                rpt.write("\n==========================================\n")
                rpt.write("STATE MACHINE STATUS: " + ("PASS" if success_verify else "FAIL") + "\n")
                rpt.write("==========================================\n")

            logs.append(f"  > Report generated: {os.path.basename(report_path)}")
            
            if success_verify:
                 logs.append("TEST E2E: SUCCESS! State Machine Validated.")
            else:
                 logs.append("WARNING: TEST E2E Verification inconclusive (Check Report)")
                 
            return success_verify, logs

        except Exception as e:
            self.logger.error(f"Test E2E Exception: {e}")
            logs.append(f"ERROR: Test E2E Failed: {e}")
            return False, logs
