# US Equities Strategy Playbook (คู่มือการเทรดหุ้นสหรัฐฯ 7 ตัว)
*AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA*
*สเปกสัญญา: MT5 Equity CFDs (Day / Swing Trading System)*

---

## 1. แนวทางการวิเคราะห์ทิศทางและโครงสร้างรอบสัปดาห์
- **[EQ-RULE-01] Multi-Timeframe Alignment (Week Bullish + Day Bounce)**
  - ต้องมีทิศทางสอดคล้องกัน: ภาพใหญ่ระดับสัปดาห์ (Week) หรือรายวัน (Day) ต้องเป็นขาขึ้น Bullish (EMA20 >= EMA50) และกราฟมีการย่อพักตัวแล้วเด้ง (Bounce)
  - ห้ามเทรดสวนแนวโน้มใหญ่ระดับสัปดาห์เด็ดขาด

---

## 2. การควบคุมเลเวอเรจและความปลอดภัยเงินทุน
- **[EQ-RULE-02] Leverage Cap <= 1:5 บนฐานทุนจริงของพอร์ต MT5**
  - ขนาด Notional รวมของสถานะหุ้นต้องไม่เกิน 5 เท่าของ Balance จริงในพอร์ต
  - คำนวณความเสี่ยงต่อไม้ไม่เกิน 1.5% - 2.0% ของยอดเงินปัจจุบัน

---

## 3. ระบบยืนยันคำสั่งสองขั้นตอน
- **[EQ-RULE-03] Two-Step Approval Required**
  - บอทไม่ส่งคำสั่งเทรดหุ้นโดยตรงเข้าตลาดแบบอัตโนมัติ
  - ต้องส่งสัญญาณเข้าสู่สถานะรอการอนุมัติ (Pending Approval) และได้รับการกดยืนยันจากผู้ใช้ผ่านหน้าเว็บ Dashboard ก่อนส่งคำสั่งจริงเสมอ

---

## 4. กลยุทธ์ Price Action Demand/Supply และ Swing Holding
- **[EQ-RULE-04] Day/H4 Demand Base Retest Protocol**
  - ค้นหาโซนฐานราคา (Drop-Base-Rally - DBR) บน Timeframe Day หรือ H4 ซึ่งเป็นระดับราคาที่กองทุนสถาบันใช้สะสมหุ้น
  - ซื้อเฉพาะจังหวะที่ราคาย่อตัวกลับมาทดสอบฐาน (Pullback Retest) ในระดับส่วนลด (Discount Price) ห้ามไล่ราคาตอนหุ้น Breakout พุ่งกระชาก
- **[EQ-RULE-05] Equity Headroom Guard (< 1.5x Day ATR)**
  - ห้ามเข้าซื้อเด็ดขาด หากระยะทางไปยังแนวต้านสำคัญระดับ Day (Major Supply หรือ All-Time High) เหลือน้อยกว่า $1.5\times \text{ATR}_\text{Day}$
- **[EQ-RULE-06] Dynamic ATR Stop Loss & Swing Holding Policy**
  - **ห้ามใช้ Hard SL คงที่แบบทองคำ ($6.00):** ให้คำนวณระยะ Stop Loss อิงตามความผันผวนของหุ้นตัวนั้นๆ ($\text{SL} = \text{Base Low} - 0.50\times \text{ATR}_\text{Day}$)
  - **อนุญาตให้ถือข้ามวันได้ (Swing Holding Allowed):** เพื่อเก็บกำไรจากรอบแนวโน้มและ Gap การเปิดตลาดข้ามคืน (ถือครองเฉลี่ย 2 วัน - 3 สัปดาห์)
- **[EQ-RULE-07] Earnings Blackout Window (48h Buffer)**
  - ห้ามเปิดสถานะ Swing Trade ในหุ้นที่มีกำหนดการประกาศงบการเงิน (Quarterly Earnings) ภายใน 48 ชั่วโมง (2 วัน) ทั้งก่อนและหลังประกาศงบ เพื่อตัดความเสี่ยง Gap ลบ 10-20% ที่ไม่สามารถตัดขาดทุนได้ทัน
