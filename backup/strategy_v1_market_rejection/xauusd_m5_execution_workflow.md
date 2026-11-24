---
name: xauusd-m5-execution-workflow
description: Workflow การวิเคราะห์โครงสร้าง 3 กรอบเวลา (1H/15m/M5) จุดเข้าทำความแม่นยำสูง M5 Trigger และการรักษา Stop Loss เชิงโครงสร้างที่ปลอดภัยสำหรับทองคำ (XAUUSD / XAUUSDc)
version: 1.1.0
---

# XAU/USD Multi-Timeframe M5 Execution & Structural SL Workflow

Workflow นี้สรุปขั้นตอนการทำงานและผังการตัดสินใจทั้งหมดของระบบ AutoTrade ทองคำ (XAUUSD / XAUUSDc) ตามสถาปัตยกรรม 3 กรอบเวลา (Top-Down Execution):
1. **1H (ชั่วโมง):** คุม Macro Structure, Major Fibonacci Swings, และโซน Base แม่บท
2. **15m (15 นาที):** คำนวณ ATR, แนวโน้ม EMA15/MA50, Headroom Guard, และกรอบแนวรับ-แนวต้านหลัก
3. **M5 (5 นาที):** เป็น **Sniper Execution Trigger** ดักจับแท่งเทียนกลับตัว (Rejection Wick $\ge 25\%$) เมื่อราคาแตะเข้าเนื้อโซน

---

## 1. แผนภาพผังกระบวนการตัดสินใจ (Decision Flowchart)

```mermaid
flowchart TD
    Start["เริ่มต้นรอบสแกน (Round Scan MT5)"] --> FetchData["ดึงข้อมูล Multi-TF: 1H (120 แท่ง), 15m (200 แท่ง), M5 (120 แท่ง)"]
    FetchData --> BaseZone["สร้างโซน Demand & Supply จาก 15m และ 1H (Fusion & Clamping)"]
    BaseZone --> CheckTouch{"ราคาปัจจุบันแตะเนื้อโซน Demand/Supply หรือไม่?"}
    
    CheckTouch -- "ไม่แตะ" --> StateNeutral["สถานะ NEUTRAL (รอราคาเข้าใกล้โซน)"]
    
    CheckTouch -- "แตะโซน Demand (BUY)" --> M5BuyTrigger{"ตรวจแท่งเทียน M5 / 15m: Rejection Wick >= 25% หรือ Bullish Close?"}
    CheckTouch -- "แตะโซน Supply (SELL)" --> M5SellTrigger{"ตรวจแท่งเทียน M5 / 15m: Rejection Wick >= 25% หรือ Bearish Close?"}
    
    subgraph Guard_Evaluation ["การประเมินความปลอดภัย & SL เชิงโครงสร้าง"]
        M5BuyTrigger -- "ไม่พบ / กำลังทุบแรง" --> WaitBuyRejection["WAITING_FOR_REJECTION หรือ REJECTED_FALLING_KNIFE"]
        M5BuyTrigger -- "พบ Rejection" --> StructSLBuy["ตั้ง SL เชิงโครงสร้าง = ฐานล่าง Demand 15m/1H - Moat Buffer (0.75x ATR)"]
        
        M5SellTrigger -- "ไม่พบ / พุ่งแรง" --> WaitSellRejection["WAITING_FOR_REJECTION หรือ REJECTED_ROCKET_SURGE"]
        M5SellTrigger -- "พบ Rejection" --> StructSLSell["ตั้ง SL เชิงโครงสร้าง = ฐานบน Supply 15m/1H + Moat Buffer (0.75x ATR)"]
        
        StructSLBuy --> CheckHeadroomBuy{"Headroom สู่แนวต้านบน >= 1.0x ATR หรือไม่?"}
        CheckHeadroomBuy -- "ไม่ผ่าน" --> RejectNearResist["REJECTED_NEAR_RESISTANCE (ห้ามซื้อติดแนวต้าน)"]
        CheckHeadroomBuy -- "ผ่าน" --> CheckSLBuy{"ระยะ SL เชิงโครงสร้าง <= Hard SL Cap ($8.00) หรือไม่?"}
        
        StructSLSell --> CheckHeadroomSell{"Downside Headroom สู่ Low วัน >= 1.5x ATR หรือไม่?"}
        CheckHeadroomSell -- "ไม่ผ่าน" --> RejectNearSupp["REJECTED_NEAR_SUPPORT_HEADROOM (ห้ามขายก้นเหว)"]
        CheckHeadroomSell -- "ผ่าน" --> CheckSLSell{"ระยะ SL เชิงโครงสร้าง <= Hard SL Cap ($8.00) หรือไม่?"}
    end
    
    CheckSLBuy -- "กว้างเกิน $8.00" --> LimitBuyFallback["สลับเป็น ACTIONABLE_BUY_LIMIT ดักย่อที่ Fibo 65% OTE"]
    CheckSLBuy -- "<= $8.00" --> RRBuy{"Risk:Reward >= 1.50 หรือไม่?"}
    
    CheckSLSell -- "กว้างเกิน $8.00" --> LimitSellFallback["สลับเป็น ACTIONABLE_SELL_LIMIT ดักเด้งที่ Fibo 65% OTE"]
    CheckSLSell -- "<= $8.00" --> RRSell{"Risk:Reward >= 1.50 หรือไม่?"}
    
    RRBuy -- "ผ่าน" --> FireBuy["🚀 ส่งคำสั่ง BUY_DEMAND_ZONE ไปยัง MT5"]
    RRBuy -- "ไม่ผ่าน" --> RejectRRBuy["REJECTED_POOR_RR"]
    
    RRSell -- "ผ่าน" --> FireSell["🚀 ส่งคำสั่ง SELL_SUPPLY_ZONE ไปยัง MT5"]
    RRSell -- "ไม่ผ่าน" --> RejectRRSell["REJECTED_POOR_RR"]
```

---

## 2. กฎหลัก 4 ข้อของ Workflow

### กฎข้อที่ 1: การลั่นไกด้วยแท่งเทียน 5 นาที (M5 Sniper Trigger)
- เมื่อราคาเดินทางเข้าใกล้หรือสัมผัสขอบโซนของ 15m/1H ระบบจะซูมเข้าตรวจแท่งเทียน M5 ล่าสุด
- **ฝั่ง BUY:** ต้องการหางล่าง (Lower Wick) $\ge 25\%$ ของความยาวแท่ง หรือแท่งเขียวปิดพ้นกึ่งกลางฐาน
- **ฝั่ง SELL:** ต้องการหางบน (Upper Wick) $\ge 25\%$ ของความยาวแท่ง หรือแท่งแดงปิดพ้นกึ่งกลางฐาน
- **ข้อดี:** ตรวจพบการกลับตัวได้เร็วกว่าแท่ง 15m ถึง 3 เท่า ได้ราคาต้นทุนชิดฐานแนวรับ/ต้านมากที่สุด

### กฎข้อที่ 2: การรักษา Stop Loss เชิงโครงสร้าง (Structural SL Protection)
- **ห้ามบีบ SL ให้แคบเกินธรรมชาติเด็ดขาด:** เพื่อป้องกันไม่ให้ถูก Spread หรือไส้เทียนของตลาดทองคำกวาดกินฟรี (Stop-Hunt Noise)
- จุด Stop Loss ต้องคำนวณจาก:
  - **ฝั่ง BUY:** $\text{SL} = \text{ขอบล่างของ Demand Zone (15m/1H)} - \text{Moat Buffer}$
  - **ฝั่ง SELL:** $\text{SL} = \text{ขอบบนของ Supply Zone (15m/1H)} + \text{Moat Buffer}$
  - โดยที่ $\text{Moat Buffer} = (0.75 \times \text{ATR}) + \text{Broker Spread}$

### กฎข้อที่ 3: เพดานความเสี่ยงและการถอยไปใช้ Limit Order (Hard SL Cap $\le \$8.00$)
- **เพดานขาดทุนสูงสุด:** ระยะห่างจากจุดเข้าถึง SL ต้อง **ไม่เกิน $8.00 USD (80 pips)**
- **หากความผันผวนสูงจน SL กว้างเกิน $8.00:**
  - ระบบจะปฏิเสธการกด Market Order ทันที
  - และสลับไปแนะนำโหมด **Pending Limit Order** ดักรอที่ระดับ **Fibonacci 65.0% (OTE)** เพื่อดึงระยะ SL ให้แคบลงมาอยู่ในกรอบปลอดภัย

### กฎข้อที่ 4: การตั้งเป้าหมายทำกำไร (Front-Running Take Profit)
- **ไม่ตั้ง TP ลึกเข้าไปในแนวต้าน/แนวรับตรงๆ:** เพราะเสี่ยงที่ราคาจะลงไปไม่ถึงแล้ววกกลับ
- **สูตรคำนวณ:** $\text{TP} = \text{ขอบแนวต้าน/แนวรับถัดไป} \pm (0.35 \times \text{ATR})$
- ป้องกันปัญหากำไรทิพย์ พร้อมล็อกผลตอบแทน Risk:Reward $\ge 1.50$ เสมอ
