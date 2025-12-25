import os
import cv2
import logging
from datetime import datetime
from source.utils.image_merger import merge_production_images

class RealtimeWorker:
    """
    Worker class to handle unified inference and post-processing tasks.
    In the production refactor, it provides static or instance methods
    to perform standardized operations like merging and final logging.
    """
    def __init__(self, db, lpr_engine, cls_engine, logger=None):
        self.db = db
        self.lpr_engine = lpr_engine
        self.cls_engine = cls_engine
        self.log = logger or logging.getLogger("RealtimeWorker")

    def finalize_dump_session(self, session_uuid, dump_id, images_dict, plate_number):
        """
        Final post-processing for a completed or timed-out session.
        - Merge 4 images
        - Update DB
        - Save report
        """
        self.log.info(f"Finalizing Session {session_uuid} via Worker")
        
        # Check image availability
        captured = [images_dict.get('IMAGE_1'), images_dict.get('IMAGE_2'), 
                    images_dict.get('IMAGE_3'), images_dict.get('IMAGE_4')]
        
        all_captured = all(v is not None for v in captured)
        status = 'COMPLETE' if all_captured else 'INCOMPLETE'
        
        # Get Site Metadata
        factory_info = self.db.get_factory_info()
        meta = {
            'datetime': datetime.now().strftime("%d%m%Y-%H:%M:%S"),
            'factory': factory_info.get('factory_id', 'NA'),
            'milling': factory_info.get('milling_process', 'NA'),
            'dump': dump_id,
            'lpr': plate_number
        }
        
        # Merge
        merged_img = merge_production_images(captured, meta)
        
        # Save Result
        res_dir = "results"
        os.makedirs(res_dir, exist_ok=True)
        filename = f"PROD_{dump_id}_{session_uuid[:8]}.jpg"
        filepath = os.path.join(res_dir, filename)
        cv2.imwrite(filepath, merged_img)
        
        # DB Update
        self.db.update_session(session_uuid, 
                              end_time=datetime.now(),
                              merged_image_path=filepath,
                              status=status)
        
        return filepath
