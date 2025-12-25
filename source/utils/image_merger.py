import cv2
import numpy as np
import os
from datetime import datetime

def merge_production_images(images: list, metadata: dict) -> np.ndarray:
    """
    images: List of 4 images (BGR arrays). Some might be None.
    metadata: {datetime, factory, milling, dump, lpr}
    """
    # 1. Standardize size for the 4 slots
    slot_w, slot_h = 640, 480
    processed_imgs = []
    
    placeholder = np.zeros((slot_h, slot_w, 3), dtype=np.uint8)
    cv2.putText(placeholder, "IMAGE MISSING (INCOMPLETE)", (50, 240), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)

    for i in range(4):
        if i < len(images) and images[i] is not None:
            processed_imgs.append(cv2.resize(images[i], (slot_w, slot_h)))
        else:
            processed_imgs.append(placeholder.copy())

    # 2. Create Grid
    row1 = np.hstack([processed_imgs[0], processed_imgs[1]])
    row2 = np.hstack([processed_imgs[2], processed_imgs[3]])
    grid = np.vstack([row1, row2])

    # 3. Add Header
    header_h = 100
    canvas_w = slot_w * 2
    canvas_h = (slot_h * 2) + header_h
    
    final_img = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    # Fill header with dark blue/grey
    final_img[0:header_h, :] = (40, 40, 40)
    
    # 4. Header Text
    # Format: Datetime | FACTORY | MILLING PROCESS | DUMP | LPR
    header_text = f"{metadata.get('datetime', '')} | {metadata.get('factory', '')} | {metadata.get('milling', '')} | {metadata.get('dump', '')} | {metadata.get('lpr', 'UNKNOWN')}"
    
    cv2.putText(final_img, header_text, (20, 60), 
               cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
    
    # Add labels to images
    labels = ["IMAGE 1: LPR", "IMAGE 2: 100%", "IMAGE 3: 50%", "IMAGE 4: 25%"]
    for i in range(4):
        x = (i % 2) * slot_w + 10
        y = header_h + (i // 2) * slot_h + 30
        cv2.putText(final_img, labels[i], (x, y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Place grid onto canvas
    final_img[header_h:, :] = grid
    
    return final_img
