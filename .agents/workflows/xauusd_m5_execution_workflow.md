---
name: xauusd-m5-execution-workflow
description: Workflow การวิเคราะห์โครงสร้าง 3 กรอบเวลา (1H/15m/M5) ระบบวางคำสั่งอัจฉริยะ Dynamic Limit Order Management (Option 2) และการควบคุมความเสี่ยง Stop Loss สูงสุด $8.00 USD สำหรับทองคำ (XAUUSD / XAUUSDc)
version: 2.0.0
---

# XAU/USD Dynamic Limit Order & Structural SL Workflow (V2.0)

Workflow นี้สรุปขั้นตอนการทำงานและผังการตัดสินใจของระบบ AutoTrade ทองคำ (XAUUSD / XAUUSDc) ตามสถาปัตยกรรม **Dynamic Limit Order Management (Option 2)**:
1. **1H (ชั่วโมง):** คุม Macro Structure, Major Fibonacci Swings, และโซน Base แม่บท
2. **15m (15 นาที):** คำนวณ ATR, แนวโน้ม EMA15/MA50, Headroom Guard, และกรอบแนวรับ-แนวต้านหลัก
3. **Dynamic Limit Placement:** วางคำสั่ง **Pending Limit Order (Buy Limit / Sell Limit)** ดักล่วงหน้าที่ระดับ **Fibonacci 65.0% OTE หรือกึ่งกลางโซน Base (Discount 50%)** โดยไม่ต้องรอแท่งเทียนปิด ทำให้ได้ราคาต้นทุนคมที่สุดและระยะ SL แคบลง ($\le \$8.00$)
4. **Order Lifecycle Manager (ลูปตรวจทุก 60-90 วินาที):** บอททำหน้าที่คอยตรวจสอบคำสั่ง Limit ที่ค้างอยู่ หากพบแท่งเทียนทิ้งตัวแรง (Falling Knife) หรือแนวรับแตก จะสั่ง **Cancel / ยกเลิกคำสั่งทันที** เพื่อไม่ให้รับมีดตก

---

## 1. แผนภาพผังกระบวนการตัดสินใจ (Decision Flowchart)

```mermaid
flowchart TD
    Start["เริ่มต้นรอบสแกน (Round Scan MT5 ทุก 60-90 วินาที)"] --> FetchData["ดึงข้อมูล Multi-TF: 1H (120 แท่ง), 15m (200 แท่ง), M5 (120 แท่ง)"]
    FetchData --> CheckNews{"อยู่ในช่วงข่าวแรง (News Blackout) หรือ Spread ถ่างหรือไม่?"}
    
    CheckNews -- "ใช่ (ติดข่าว/สเปรดถ่าง)" --> CancelNews["⚠️ ระงับการวางคำสั่ง / สั่ง Cancel ออเดอร์ Limit ที่ค้างทั้งหมด"]
    CheckNews -- "ไม่ใช่ (ตลาดปกติ)" --> BaseZone["สร้างโซน Demand & Supply จาก 15m และ 1H (Fusion & Clamping)"]
    
    BaseZone --> CheckPending{"มีคำสั่ง Pending Limit เดิมค้างอยู่หรือไม่?"}
    
    subgraph Order_Reconciliation ["การบริหารจัดการคำสั่ง Limit ที่ค้างอยู่ (Reconciliation)"]
        CheckPending -- "มีคำสั่งค้าง" --> CheckSafety{"ตรวจสอบความปลอดภัยของออเดอร์เดิม"}
        CheckSafety -- "เกิด Falling Knife / Rocket Surge" --> CancelViolent["❌ สั่ง CANCEL ทันที (ชักคำสั่งหลบมีดตก)"]
        CheckSafety -- "ราคาหลุดทำลายโครงสร้างโซน" --> CancelBreak["❌ สั่ง CANCEL ทันที (โครงสร้างแนวรับ/ต้านแตก)"]
        CheckSafety -- "ราคาวิ่งหนีโซนเกิน 1.5x ATR" --> CancelDrift["❌ สั่ง CANCEL ทันที (ราคาวิ่งหนีโซน)"]
        CheckSafety -- "โครงสร้างยังดี & ปลอดภัย" --> RenewLease["✅ RENEW LEASE (ต่อเวลาคำสั่งรอบละ 10 นาที)"]
    end
    
    CheckPending -- "ไม่มีคำสั่งค้าง" --> CheckTouch{"ราคาปัจจุบันเข้าใกล้หรืออยู่ในโซน Demand / Supply หรือไม่?"}
    
    subgraph Limit_Evaluation ["การคำนวณและวางคำสั่ง Limit ดักล่วงหน้า (Option 2)"]
        CheckTouch -- "ใกล้ Demand (BUY)" --> CheckKnifeBuy{"เป็นแท่งเทียนทิ้งตัวแรง (Falling Knife) หรือไม่?"}
        CheckKnifeBuy -- "ใช่ (มีดตก)" --> RejectKnife["REJECTED_FALLING_KNIFE (ห้ามวาง Buy Limit สวนมีดตก)"]
        CheckKnifeBuy -- "ไม่ใช่" --> HeadroomBuy{"Headroom สู่แนวต้านบน >= 1.0x ATR หรือไม่?"}
        HeadroomBuy -- "ไม่ผ่าน" --> RejectResist["REJECTED_NEAR_RESISTANCE (ห้ามซื้อติดแนวต้าน)"]
        HeadroomBuy -- "ผ่าน" --> CalcBuyLimit["คำนวณจุดเข้า Fibo 65% OTE / Demand Mid + SL ฐานล่าง (<= $8.00)"]
        
        CheckTouch -- "ใกล้ Supply (SELL)" --> CheckRocketSell{"เป็นแท่งเทียนพุ่งแรง (Rocket Surge) หรือไม่?"}
        CheckRocketSell -- "ใช่ (จรวด)" --> RejectRocket["REJECTED_ROCKET_SURGE (ห้ามวาง Sell Limit สวนจรวด)"]
        CheckRocketSell -- "ไม่ใช่" --> HeadroomSell{"Downside Headroom สู่ Low วัน >= 1.5x ATR หรือไม่?"}
        HeadroomSell -- "ไม่ผ่าน" --> RejectSupp["REJECTED_NEAR_SUPPORT_HEADROOM (ห้ามขายก้นเหว)"]
        HeadroomSell -- "ผ่าน" --> CalcSellLimit["คำนวณจุดเข้า Fibo 65% OTE / Supply Mid + SL ฐานบน (<= $8.00)"]
    end
    
    CalcBuyLimit --> RRBuy{"Risk:Reward >= 1.50 และ SL <= $8.00 หรือไม่?"}
    RRBuy -- "ผ่าน" --> FireBuyLimit["🎯 ส่งคำสั่ง BUY LIMIT ไปยัง MT5 (TTL 10 นาที)"]
    RRBuy -- "ไม่ผ่าน" --> RejectRRBuy["REJECTED_POOR_RR หรือ REJECTED_SL_TOO_WIDE"]
    
    CalcSellLimit --> RRSell{"Risk:Reward >= 1.50 และ SL <= $8.00 หรือไม่?"}
    RRSell -- "ผ่าน" --> FireSellLimit["🎯 ส่งคำสั่ง SELL LIMIT ไปยัง MT5 (TTL 10 นาที)"]
    RRSell -- "ไม่ผ่าน" --> RejectRRSell["REJECTED_POOR_RR หรือ REJECTED_SL_TOO_WIDE"]
    
    FireBuyLimit --> Handover["เมื่อออเดอร์ Match (Filled) ──► ส่งต่อให้ Position Manager ล็อก Breakeven (+1.0R)"]
    FireSellLimit --> Handover
```

---

## 2. กฎหลัก 4 ข้อของระบบ Dynamic Limit (Option 2)

### กฎข้อที่ 1: การวางคำสั่ง Limit ดักล่วงหน้าที่จุดได้เปรียบ (Pre-placement)
- **ไม่ไล่ซื้อ/ขายด้วย Market Order:** เพื่อหลีกเลี่ยงการติดดอยหรือขายก้นเหว
- **จุดเข้าคำสั่ง (Entry):** วางที่ระดับ **Fibonacci 65.0% OTE หรือกึ่งกลางโซน Base (Discount 50%)**
- **จุดตัดขาดทุน (Stop Loss):** วางหลังฐานโซนบวก Moat Buffer ($0.75\times\text{ATR} + \text{Spread}$) โดยระยะห่าง **ต้องไม่เกิน $8.00 USD (80 pips) เสมอ**
- **เป้าหมายทำกำไร (Take Profit):** ดักเก็บกำไรหน้าแนวรับ/ต้านถัดไป ($R:R \ge 1.50$)

### กฎข้อที่ 2: วงจรตรวจสอบและยกเลิกออเดอร์อัตโนมัติ (Zero-Ghost & Knife-Guard)
- คำสั่ง Limit ใน MT5 จะมีอายุเริ่มต้น 10 นาที (Server-side TTL) เพื่อป้องกันคำสั่งค้างหากบอทหยุดทำงาน
- ในแต่ละรอบที่บอทประมวลผล (ทุก 60–90 วินาที) บอทจะตรวจสอบ:
  1. หากมีแท่งแดงทึบดิ่งลงมา (Falling Knife) $\rightarrow$ **สั่งลบ Buy Limit ทิ้งทันที** เพื่อไม่ให้รับมีดตก
  2. หากราคาหลุดทะลุแนวรับ/ต้านหลัก $\rightarrow$ **สั่งลบ Limit ทิ้งทันที**
  3. หากเข้าสู่ช่วงข่าวสหรัฐฯ (News Blackout) หรือสเปรดถ่าง $\rightarrow$ **สั่งลบ Limit ทิ้งทันที**

### กฎข้อที่ 3: การเลื่อนบังทุนอัตโนมัติ (Breakeven Lock)
- ทันทีที่คำสั่ง Limit ถูกเกี่ยว (Filled) และราคาเริ่มวิ่งไปในทิศทางที่ถูกต้องจนมีกำไรลอยตัว $\ge +1.0\times R$
- ระบบจะปรับ Stop Loss ขึ้นมาบังหน้าทุนทันที (`Entry ± (Live Spread + $0.10)`) เพื่อเปลี่ยนสถานะเป็น **Free Trade** คุ้มครองเงินทุน 100%

### กฎข้อที่ 4: การทำงานแบบ Full Auto ในคำสั่งเดียว
- คำสั่งรันผ่าน Bridge CLI:
  ```bash
  python -m src.execution.agent_bridge gold-strategy --symbol XAUUSDc --manage-limits
  ```
  หรือสั่งรันลูปต่อเนื่อง:
  ```bash
  python -m src.execution.agent_bridge gold-loop --interval 60
  ```
