# AI Sugarcane Quality Detection at Dump Station

## Overview

**AI Sugarcane Quality Detection at Dump Station** เป็นโครงการประยุกต์ใช้ **Artificial Intelligence (AI) และ Computer Vision** เพื่อยกระดับการวิเคราะห์คุณภาพอ้อย ณ จุดดั้ม (Dump Station) ของโรงงานน้ำตาล โดยมุ่งเน้นการตรวจจับและประเมิน **สัดส่วนอ้อย ดิน และสิ่งสกปรก** ในสภาพการทำงานจริงที่อ้อยมีการเคลื่อนที่ด้วยความเร็วสูง

โครงการนี้ถูกออกแบบมาเพื่อแก้ไขข้อจำกัดของการประเมินคุณภาพอ้อยแบบดั้งเดิม และรองรับการทำงานร่วมกับระบบ Smart Factory ในระยะยาว

---

## Objectives

* วิเคราะห์คุณภาพอ้อย **ขณะดรั้มจริง (Real Dumping Condition)**
* ตรวจจับดินและสิ่งสกปรกที่ปนมากับอ้อยอย่างแม่นยำ
* สร้าง Dataset ภาพคุณภาพสูงสำหรับ Training / Validation AI Model
* เพิ่มความโปร่งใสและความถูกต้องในการประเมินคุณภาพวัตถุดิบ
* รองรับการขยายผลไปยังหลายโรงงานในอนาคต

---

## Scope of Work

* ใช้ **High Speed Camera (IP Cameras)** สำหรับจับภาพวัตถุที่เคลื่อนที่เร็ว
* ประมวลผลภาพด้วย AI Computer Vision (YOLO)
* ทำงานร่วมกับ Edge Computing และระบบโรงงาน
* รองรับการพัฒนาและปรับปรุงโมเดล AI อย่างต่อเนื่อง

---

## System Architecture (High Level)

1. **Image Acquisition**
   * IP Camera ติดตั้งบริเวณ Dump Station (ช่อง 1, 3, 5, ... สำหรับ LPR และ 2, 4, 6, ... สำหรับ Sugarcane)
   * เก็บภาพอ้อยขณะดรั้มและตรวจจับแผ่นป้ายทะเบียน

2. **Data Processing**
   * Image Pre-processing
   * Frame Selection / Filtering

3. **AI Inference**
   * Sugarcane Quality Classification
   * Dirt / Trash Detection / LPR

4. **Output & Integration**
   * Quality Indicators
   * Dataset สำหรับ Model Improvement
   * Integration กับระบบ AI / Smart Factory

---

## Repository Structure

```bash
.
├── models/             # Trained AI models (YOLO .pt files)
├── source/             # Core source code
│   ├── orchestration/  # Orchestration logic & UI
│   ├── utils/          # Utility functions
│   ├── run_realtime.py # Main entry point for real-time detection
│   ├── realtime_worker.py # Backend processing worker
│   └── database.py     # Database management (SQLite)
├── config.template.txt # Configuration template
├── setup.bat           # Environment setup script
├── update.bat          # Automated update script
└── README.md
```

---

## Technologies

* **Language:** Python
* **Vision:** OpenCV, YOLO (Ultralytics)
* **OCR:** EasyOCR
* **Database:** SQLite
* **Stream:** RTSP (TCP)

---

## Use Cases

* วิเคราะห์คุณภาพอ้อยแบบ Real-time / Near Real-time
* ลดข้อโต้แย้งด้านคุณภาพอ้อย
* สนับสนุนการตัดสินใจของฝ่ายผลิตและประกันคุณภาพ
* ใช้เป็นฐานข้อมูลภาพสำหรับ AI Governance และ Model Improvement

---

## Future Roadmap

* เพิ่ม Object Segmentation (อ้อย / ดิน / สิ่งสกปรก)
* เชื่อมต่อ Dashboard และระบบรายงานผล
* ขยายการใช้งานไปยังหลาย Dump Station และหลายโรงงาน
* เชื่อมต่อข้อมูลกับระบบ Yield และ Cost Optimization

---

## Disclaimer

This repository is intended for **internal use and research purposes**.
All data, models, and outputs are subject to company data governance and security policies.
