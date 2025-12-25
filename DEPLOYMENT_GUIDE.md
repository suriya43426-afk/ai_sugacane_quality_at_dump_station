# AI Sugarcane System - Deployment & Operations Guide

เอกสารฉบับนี้อธิบายมาตราฐานการปฏิบัติงาน (SOP) สำหรับ Software Engineer ในการติดตั้ง, อัพเดท, และจัดการ Version ของระบบที่หน้างานโรงงาน โดยเปลี่ยนจากระบบ Manual Upload เป็น Git Automation

---

## 1. การติดตั้งที่โรงงาน (New Installation)
*สำหรับเครื่องใหม่ที่ไม่เคยลงระบบมาก่อน*

### สิ่งที่ต้องเตรียม (Prerequisites)
1.  **Internet Access:** เครื่องต้องออกเน็ตได้ (เพื่อดึงโค้ด)
2.  **Git for Windows:** ติดตั้งโปรแกรม Git ก่อน (โหลดได้ที่ [git-scm.com](https://git-scm.com/download/win))
3.  **Python 3.10+:** ติดตั้ง Python (แนะนำ 3.10 หรือ 3.11) และติ๊กช่อง `Add Python to PATH` ตอนติดตั้งด้วย



## 2. การอัพเดทโค้ด (Updating Code)
*ทำเมื่อมีการแก้ไขโค้ดจากส่วนกลาง และต้องการนำไปใช้ที่หน้างาน*

### ขั้นตอน
1.  ที่หน้า Desktop โรงงาน (หรือใน Folder โปรเจกต์)
2.  ดับเบิ้ลคลิกไฟล์ **`update.bat`**
3.  ระบบจะทำการ:
    *   ดึงโค้ดล่าสุดจาก GitHub (Version ล่าสุด)
    *   ถ้ามีการแก้ Library มันอาจจะต้องรัน `setup.bat` ซ้ำ (ถ้าจำเป็น) แต่โดยปกติ `update.bat` จะคุยกับ Git อย่างเดียว

*หมายเหตุ: ถ้า `update.bat` ฟ้อง Error เรื่อง Local Changes (มีการแก้ไฟล์ในเครื่องโรงงาน) ให้ลองลบไฟล์ที่แจ้งเตือน (ยกเว้น config.txt) แล้วกด update ใหม่ หรือใช้คำสั่ง `git stash`*

---

## 3. การจัดการ Version (Versioning)
*เพื่อให้ทราบว่าตอนนี้โรงงานใช้ Software รุ่นไหนอยู่*

### Workflow ของ Developer (ตัวคุณ)
ทุกครั้งที่มีการแก้ไขงานให้ทำดังนี้:

1.  **แก้ไขเลข Version:**
    *   เปิดไฟล์ `source/orchestration/ui_app.py`
    *   แก้ไขบรรทัด `APP_VERSION = "1.xx.xx"` ให้เป็นเลขใหม่

2.  **บันทึกและส่งขึ้น Cloud:**
    *   เปิด Terminal ในเครื่องคุณ
    *   พิมพ์คำสั่ง:
        ```bash
        git add .
        git commit -m "Update version to 1.xx.xx: รายละเอียดการแก้..."
        git push
        ```

3.  **ที่เครื่องโรงงาน:**
    *   กด `update.bat`
    *   เปิดโปรแกรม -> **ดูที่มุมขวาบน** จะเห็นเลข Version ใหม่ทันที

---

### Q&A (ปัญหาที่พบบ่อย)
*   **Q: แก้ config.txt ที่โรงงานแล้ว พอ update มันจะหายไหม?**
    *   A: **ไม่หาย** เพราะเราตั้งค่า `.gitignore` ไว้แล้ว Git จะไม่ไปยุ่งกับไฟล์ config.txt ของเรา
*   **Q: เน็ตโรงงานหลุดตอน Update ทำไง?**
    *   A: กด `update.bat` ใหม่ได้เลย มันจะโหลดต่อเฉพาะส่วนที่ขาด

---

## 6. Release Strategy (Standard & Testing)
*แผนการปล่อย Version สำหรับ 60 โรงงาน*

### แผนการอัพเดท (Rollout Plan)
1.  **Testing (3 Sites):** ใช้ Branch `beta`
    *   ลงโค้ดใหม่ที่นี่ก่อนเสมอ เพื่อทดสอบหน้างานจริง
    *   วิธีตั้งค่าเครื่อง Test: เปิด CMD แล้วพิมพ์ `git checkout beta`
2.  **Staging (8 Sites):** ใช้ Branch `beta` (หรือ `staging`)
    *   ขยายผลการทดสอบไปยังโรงงานที่มีความหลากหลาย
3.  **Production (60 Sites):** ใช้ Branch `main`
    *   เมื่อ `beta` นิ่งแล้ว -> ทำการ Merge `beta` เข้า `main`
    *   โรงงานทั้ง 60 แห่งจะได้รับอัพเดทพร้อมกันผ่าน `update.bat`

### วิธีสลับ Branch (สำหรับ Admin/Developer)
หากต้องการเปลี่ยนเครื่องโรงงานให้เป็นเครื่อง Test หรือกลับเป็น Production:
```cmd
cd ai_sugarcane_installer
# เปลี่ยนเป็นโหมด Test
git fetch
git checkout beta
git pull origin beta

# เปลี่ยนกลับเป็น Production
git checkout main
git pull origin main
```
*หลังจากสลับ Branch แล้ว `update.bat` จะจำค่า Branch นั้นๆ ตลอดไป*

---

## 4. Troubleshooting (ปัญหาที่พบบ่อย)

### WinError 1114 (DLL initialization routine failed)
**อาการ:** โปรแกรมเปิดไม่ขึ้น และขึ้น Error แบบนี้ใน Log:
```text
OSError: [WinError 1114] A dynamic link library (DLL) initialization routine failed. 
Error loading "...\torch\lib\c10.dll"
```

**สาเหตุ:** เครื่องคอมพิวเตอร์ขาดไฟล์ **Microsoft Visual C++ Redistributable** ซึ่งจำเป็นสำหรับ PyTorch (AI Library) ปัญหานี้มักเกิดกับเครื่องที่เพิ่งลง Windows ใหม่

**วิธีแก้ไข:**
1.  **ต้องติดตั้ง Visual C++ Redistributable**
2.  ไปที่ลิงก์นี้เพื่อดาวน์โหลด: [Latest Supported Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) (เลือก x64)
3.  รันตัวติดตั้ง (`vc_redist.x64.exe`)
4.  **Restart เครื่อง 1 ครั้ง** (สำคัญมาก)
5.  ลองเปิดโปรแกรมใหม่

