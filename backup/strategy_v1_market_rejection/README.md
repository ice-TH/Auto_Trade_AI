# 📦 Backup: Strategy V1 (Market Order + M5 Rejection Wick)

บันทึกสำรองข้อมูลโครงสร้างกลยุทธ์เวอร์ชันดั้งเดิม (V1) ก่อนการอัปเกรดสู่ระบบ **Dynamic Limit Order Management (V2)**
บันทึกเมื่อ: 24 พฤศจิกายน 2026 (Git Tag: `v1.0-market-rejection`)

---

## 1. แนวคิดดั้งเดิมของ V1 (Original Concept)
* **รูปแบบคำสั่ง:** ใช้ **Market Order** เมื่อราคาเดินทางเข้าสู่ขอบโซน Demand/Supply (M15/1H)
* **ตัวกรองไส้เทียน (Rejection Wick Filter):** บังคับรอแท่งเทียน M5 หรือ 15m มีไส้เทียนกลับตัว >= 25% และไม่เป็นแท่งเทียนทิ้งตัวแบบ Falling Knife / Rocket Surge
* **จุดตัดขาดทุน (Stop Loss):** วางใต้ฐานโซนลบ Moat Buffer (0.75 x ATR + spread) เพดานไม่เกิน $8.00 USD
* **ข้อจำกัดที่พบ:** 
  - เมื่อราคาเคลื่อนไหวรวดเร็วในรอบนาที (Fast Spikes) มักตกรถเพราะแท่งเทียน M5 ยังไม่ปิด
  - เมื่อแท่งเทียนทิ้งตัวลงมาเรื่อยๆ (ไม่มีไส้) ระบบจะไม่เปิดออเดอร์
  - หากราคาอยู่ในโซนก้ำกึ่ง อาจเกิดการประเมินสลับทิศทางระหว่างรอบ

---

## 2. รายชื่อไฟล์ที่สำรองไว้ในโฟลเดอร์นี้
1. `gold_strategy.py` — โค้ดกลยุทธ์หลัก V1
2. `test_gold_strategy.py` — ชุดทดสอบความถูกต้องของกลยุทธ์ V1
3. `xauusd_gold.md` — Playbook กฎการเทรดทองคำ V1
4. `xauusd_m5_execution_workflow.md` — แผนผังกระบวนการเทรด V1

---

## 3. วิธีการกู้คืนกลับเป็น V1 หากต้องการยกเลิก V2 (Rollback Command)
หากต้องการยกเลิกแนวคิด Limit Order แล้วกลับมาใช้แนวคิดเดิม V1 เพียงรันคำสั่ง PowerShell ต่อไปนี้:

```powershell
# กู้คืนไฟล์จากโฟลเดอร์ backup
Copy-Item "backup\strategy_v1_market_rejection\gold_strategy.py" "src\analysis\gold_strategy.py" -Force
Copy-Item "backup\strategy_v1_market_rejection\test_gold_strategy.py" "tests\test_gold_strategy.py" -Force
Copy-Item "backup\strategy_v1_market_rejection\xauusd_gold.md" "memory\playbooks\xauusd_gold.md" -Force
Copy-Item "backup\strategy_v1_market_rejection\xauusd_m5_execution_workflow.md" ".agents\workflows\xauusd_m5_execution_workflow.md" -Force
Copy-Item "backup\strategy_v1_market_rejection\xauusd_m5_execution_workflow.md" ".agent\workflows\xauusd_m5_execution_workflow.md" -Force

# หรือกู้คืนจาก Git Tag
git checkout v1.0-market-rejection -- src/analysis/gold_strategy.py tests/test_gold_strategy.py memory/playbooks/xauusd_gold.md

# คอมไพล์ Playbook
python -m src.analysis.playbook_compiler
pytest tests/
```
