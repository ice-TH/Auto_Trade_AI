# XAU/USD (Gold) Strategy Playbook (คู่มือการเทรดทองคำ)
*สเปกสัญญา 1 Lot = 100 Troy Oz (0.01 Lot = 1 Oz)*
*เรียนรู้จาก Price Action, Smart Money Concepts (เฉพาะ Support/Resistance, Role Reversal, Demand/Supply, Session Overlap -- ไม่ใช้ Order Block)*

---

## 1. โครงสร้าง Demand & Supply Zones (Price Action Base Structure)
- **[XAU-RULE-05] Demand & Supply Zone [ไม่ใช้ Order Block]**
  - **Demand Zone (โซนแรงซื้อหนาแน่น):** เกิดจากแพตเทิร์น **Drop-Base-Rally (DBR)** หรือ **Rally-Base-Rally (RBR)**
    - กลยุทธ์: รอราคาย่อตัวกลับมาแตะโซน Base แล้วมองหาแรงซื้อผลักดันเพื่อเปิด **BUY** โดยวาง SL ใต้ขอบล่างของ Base
  - **Supply Zone (โซนแรงขายหนาแน่น):** เกิดจากแพตเทิร์น **Rally-Base-Drop (RBD)** หรือ **Drop-Base-Drop (DBD)**
    - กลยุทธ์: รอราคาเด้งตัวขึ้นมาแตะโซน Base แล้วมองหาแรงขายกดดันเพื่อเปิด **SELL** โดยวาง SL เหนือขอบบนของ Base
  - **หมายเหตุ:** ไม่ใช้โครงสร้าง Order Block (OB) เข้ามาปะปน เน้นการประเมิน Demand/Supply โครงสร้าง Base และ S/R Role Reversal ตามสเปกที่กำหนด

- **[XAU-RULE-13] Multi-Timeframe Demand & Supply Base Structure (เรียนรู้จากเคสและภาพตัวอย่างจริง)**
  - **1. Base Identification & Tight Boundaries (การระบุกรอบ Base ที่ถูกต้อง):**
    - โซน Demand/Supply ต้องเริ่มจาก **"แท่ง Base สะสมจริง"** ไม่ลากย้อนอดีตไปก่อนที่ Base จะเกิดขึ้น
    - ความสูงของกล่องต้องจำกัดเฉพาะ High-Low ของกลุ่มแท่ง Base เท่านั้น (เช่น เคสแท่ง 00:00-00:45 น. กรอบคือ **$3,570.00 – $3,585.00** กว้าง ~15 USD) ห้ามตีกล่องกว้างเกินจริงไปถึง $3,595 เพราะจะกินเนื้อแท่ง Impulse หรือ Retest เข้าไป
    - **Demand Zone (DBR, RBR):** วัดกรอบจาก High-Low ของกลุ่มแท่ง Base ก่อนเกิดแท่ง Big Momentum พุ่งทะลุ
    - **Supply Zone (RBD, DBD):** วัดกรอบจาก High-Low ของกลุ่มแท่ง Base ก่อนเกิดแท่ง Big Momentum ทิ้งตัวดิ่ง
  - **2. No Fake Zones in Choppy / Sideway Ranges (ห้ามยัดเยียดโซนในดง Sideway ย่อย):**
    - ในช่วงราคาที่แกว่งตัว Sideway ทั่วไป (เช่น โซน $3,615 – $3,635) **ห้ามสร้างหรือตีกล่อง Supply/Demand ย่อยเด็ดขาด** เพราะไม่มีแรงระเบิดราคาออกจาก Base (No Imbalance) และราคาตัดผ่านขึ้นลงหลายรอบ (Chopped through)
    - โซน Supply จริงของรอบนี้มีเพียง **Supply 1H ($3,665.00 – $3,688.00)** ด้านบนเท่านั้น ซึ่งเป็นจุดกำเนิดการทิ้งตัวใหญ่
  - **3. Retest-Only Entry & Clear Confirmation:**
    - สังเกตการ Retest: เมื่อราคาหลุด Base พุ่งขึ้นไป แล้วย่อตัวกลับมาสัมผัส **"ขอบบนของ Demand Base ($3,583 – $3,585)"** แล้วเกิดแท่ง Rejection Wick ดีดตัวขึ้นต่อ นั่นคือจังหวะเข้าเทรด Buy ที่ได้เปรียบสูงสุด
    - วาง SL หลบใต้ขอบล่างของ Demand Base ($3,570 หรือ $3,568) ระยะบัฟเฟอร์ 5-10 pips + Spread เสมอ

- **[XAU-RULE-14] Pine Script (Flux Charts S&D) Integration & Dual-Engine Safeguards**
  - **1. จุดเด่นที่ผสานเข้าโค้ด:**
    - **Dynamic Clamping (`clamp_zone_size`):** ล็อกขนาดกล่องความกว้างสูงสุดไม่เกิน $1.5\times \text{ATR}$ เพื่อป้องกันปัญหาโซนบวม
    - **Zone Fusion (`combine_overlapping_zones`):** ผสานรวมโซน M15 กับ H1 ที่ทับซ้อนกันให้เป็นโซนแข็งแกร่ง (High Confluence) เพียงโซนเดียว ไม่ตีกล่องทับซ้อน
  - **2. จุดตรวจจับแก้ทางสัญญาณหลอก (AI Safeguards):**
    - **`REJECTED_FALLING_KNIFE`:** แม้ราคาจะแตะโดน Demand แต่หากแท่งเทียนที่ตกลงมามีเนื้อเทียนแดงตัน $\ge 70\%$ และความยาวแท่ง $\ge 1.8\times \text{ATR}$ ห้าม Buy เด็ดขาด ต้องรอแท่ง Rejection Wick ยืนยัน
    - **`REJECTED_ROCKET_SURGE`:** แม้ราคาจะแตะโดน Supply แต่หากแท่งเทียนกำลังพุ่งขึ้นเป็นเขียวตัน $\ge 70\%$ และความยาวแท่ง $\ge 1.8\times \text{ATR}$ ห้าม Sell สวนเด็ดขาด
    - **Chop Range Filter:** ตัดสัญญาณที่เกิดจากแท่งแกว่งตัวธรรมดา 4 แท่งใน Sideway ออก บังคับให้ต้องมี Impulsive Departure จริง ($\ge 1.5\times \text{Avg Body}$) เท่านั้น

- **[XAU-RULE-15] Zone Lifecycle & Broken Zone Termination (กฎการตัดจบโซนที่ถูกทำลาย)**
  - **1. Broken Zone Lifespan (ตัดจบกล่องทันทีที่ Invalidate):**
    - เมื่อราคาปิดทะลุขอบล่างของ Demand (`Close < Zone Low`) หรือทะลุขอบบนของ Supply (`Close > Zone High`) โซนนั้นจะสิ้นสุดอายุทันที ณ แท่งที่ Break
    - **ห้ามลากยืดกล่องที่ตายแล้ว (Broken Zone) ข้ามมาในปัจจุบัน** เพราะจะผ่ากลางแท่งเทียนใหม่ ทำให้กราฟรกและวิเคราะห์ผิดเพี้ยน
  - **2. Active Zones Focus:**
    - หน้ากราฟและอัลกอริทึมต้องโฟกัสเฉพาะโซนที่ยัง **Active (ไม่ถูก Break)** เท่านั้น เช่น `Supply 1H ($3,665 – $3,688)` ด้านบน และ `Demand 15m ($3,570 – $3,585)` ที่กำลังทำหน้าที่รับราคาในปัจจุบัน
  - **3. True Structural Low (การมองฐานล่างสุดจริง):**
    - หากต้องวิเคราะห์ฐานล่างสุดของรอบ ให้มองที่ **จุดกำเนิดการกลับตัวใหญ่ (Major Reversal Foundation เช่น ฐาน Double Bottom $3,502 – $3,515)** ไม่นำฐานย่อยที่แตกพ่ายระหว่างทางมาเข้าใจผิดว่าเป็น Demand ล่างสุด

---

## 2. การสลับบทบาทของแนวรับ–แนวต้าน (Role Reversal)
- **[XAU-RULE-04] Role Reversal Retest Strategy**
  - เมื่อ **แนวต้าน (Resistance)** ถูกทำลายทะลุผ่านไป จะสลับบทบาทกลายมาเป็น **แนวรับ (Support)** ทันที
  - เมื่อ **แนวรับ (Support)** ถูกทำลายหลุดร่วงลงมา จะสลับบทบาทกลายมาเป็น **แนวต้าน (Resistance)** ทันที
  - **กลยุทธ์เข้าทำ:** "ห้ามไล่ราคาตอนเพิ่งเบรก" ให้รอราคาย้อนกลับมาทดสอบโซน (Role Reversal Retest) แล้วเกิดแท่งเทียนปฏิเสธราคา (Rejection Wick) จึงเข้าออเดอร์

---

## 3. ช่วงเวลาการเทรด (Trading Sessions & Overlap)
- **[XAU-RULE-03] Trading Sessions และ London × New York Overlap (เวลาไทย BKK UTC+7)**
  - **Sydney (05:00 - 14:00 น.):** สภาพคล่องต่ำ ราคามัก Sideway กรอบแคบ ไม่เหมาะกับการ Follow Breakout
  - **Tokyo (06:00 - 15:00 น.):** วิ่งตามแรงเอเชีย ความผันผวนปานกลาง
  - **London (15:00 - 23:00 น. / หน้าหนาว):** ปริมาณการซื้อขายเริ่มหนาแน่น ทองคำเริ่มสร้างทิศทาง
  - **New York (20:00 - 04:00 น. / หน้าหนาว):** สภาพคล่องสูงมาก วิ่งตอบสนองตัวเลขเศรษฐกิจสหรัฐฯ
  - **🔥 ช่วงทองคำ: London × New York Overlap (20:00 - 23:00 น. BKK):**
    - เป็นช่วงที่ Volume และ Liquidity สูงที่สุดในรอบวัน เหมาะแก่การเทรดทำกำไรที่สุด
    - ความผันผวนสูงมาก: ต้องขยายระยะ Stop Loss หลบไส้เทียน (Moat Buffer = 1.5x - 2.0x ATR + Spread) และห้ามเปิดไม้ตอนมีข่าวแรงทันทีโดยไม่มีแท่งคอนเฟิร์ม

---

## 4. การจัดการ Stop Loss / Take Profit และ Headroom Guard
- **[XAU-RULE-01] กรองระยะวิ่ง (Headroom Guard) ห้าม Buy ชนแนวต้าน Day**
  - ทองคำมักตอบสนองต่อแนวรับแนวต้านระดับ Day อย่างรุนแรง หากระยะเหลือไม่ถึง 2x ATR ไม่คุ้มที่จะเปิด Long
- **[XAU-RULE-09] Dynamic Intraday Session Focus & No-Overnight Rule**
  - **ไม่ถือข้ามวัน (No Overnight for Gold):** เล่นจบในรอบวันหรือรอบ Session เพื่อตัดความเสี่ยงข่าวข้ามคืนและ Gap กระโดด
  - **Dynamic TP/SL ตามโครงสร้างจริงที่เน้น Winrate & Realistic Execution:**
    - **SL:** วางหลบหลัง Swing High/Low หรือขอบ Demand/Supply Zone ที่ใกล้ที่สุด พร้อมบวก Moat Buffer ($3.50 – $8.00 ห้ามกว้างเกิน $8.00)
    - **TP:** วางเป้าหมายตามแนวรับ/แนวต้านถัดไปที่ราคาจะวิ่งไปถึงจริงในรอบวัน (Front-running Target) โดยคำนึงถึง **Realistic Winrate Balance**:
      - ไม่วาง TP ไกลเกินโครงสร้างรอบวัน หากโซนถัดไปอยู่ห่างเกิน $16 USD ระบบจะ Cap TP ให้อยู่ในกรอบ R:R 1:1.5 ถึง 1:2.5 (ประมาณ $8 - $16 USD) เพื่อให้ราคาจบงานได้จริงใน Session
      - ป้องกันปัญหากำไรทิพย์ (R:R สูงแต่แตะไม่ถึงแล้ววกกลับมาโดน SL)
- **[XAU-RULE-10] Strict Anti-Resistance-Buying & Dynamic Downside Headroom Guard on Gold**
  - **ฝั่ง BUY:** หาก Headroom ไปยัง Supply ถัดไปเหลือน้อยกว่า $1.0\times \text{ATR}$ $\rightarrow$ **สั่ง REJECTED_NEAR_RESISTANCE ทันที**
  - **ฝั่ง SELL (กฎข้อ 1 ใหม่):** หากระยะห่างจากจุด Sell ไปยังแนวรับ Demand หรือ Low ของวัน เหลือน้อยกว่า **$1.5\times \text{ATR}$** $\rightarrow$ **สั่ง REJECTED_NEAR_SUPPORT_HEADROOM ทันที** ป้องกันการ Sell ปลายคลื่นก้นเหวเด็ดขาด

- **[XAU-RULE-18] Multi-Swing Hierarchy & ZigZag Fibonacci Selection Engine (Inspired by PineScript V3)**
  - **1. โครงสร้าง ZigZag Engine (Pivot Legs = 8, Deviation >= 0.8%):**
    - แก้ปัญหาสวิงย่อย/สัญญาณรบกวน โดยระบบจะไม่นับสวิงใหม่หากการกลับตัวน้อยกว่า 0.8% (~$25 - $30 USD บนทองคำ)
    - ขยาย Pivot Legs ซ้าย/ขวาเป็น 8 แท่ง เพื่อให้ได้คลื่นสวิงที่มีนัยสำคัญระดับสถาบัน
  - **2. การแยกแยะลำดับสวิง (Major vs Minor Swings):**
    - **Major Swing Leg (คลื่นแม่บท):** คลื่นใหญ่ระดับ Day / H1 ที่มีระยะวิ่ง $\ge 4.0\times \text{ATR}$ คุมทิศทางภาพใหญ่
    - **Minor Swing Leg (คลื่นย่อย):** คลื่นย่อยล่าสุดใน M15 ที่มีระยะวิ่ง $\ge 2.0\times \text{ATR}$
  - **3. Smart Swing Selector & Confluence:**
    - คัดเลือกสวิงที่ระดับ Golden Zone (61.8% – 65% OTE – 78.6%) ซ้อนทับตรงกับ Demand/Supply Base ที่ยัง Active เป็นอันดับแรก
    - **⭐⭐ A++ Double Confluence Setup:** หาก Golden Zone ของทั้งสวิงแม่บท (Major) และสวิงย่อย (Minor) ชี้เป้าซ้อนทับที่ราคาเดียวกัน จะถือเป็นจุดเข้าที่มีความแม่นยำสูงสุดในรอบวัน
  - **4. Optimal Trade Entry (OTE 65.0%):**
    - ให้ระบบ `gold_limit_manager` เล็งวาง Pending Limit Order ที่ระดับ Fibo 65.0% (จุดกึ่งกลาง Optimal Trade Entry) เพื่อให้ได้ต้นทุนที่ดีที่สุดและระยะ SL แคบมาก

- **[XAU-RULE-12] Hard SL Cap (<= $8.00 USD)**
  - สำหรับการเล่นทองคำรอบวัน หากระยะห่างของ SL ที่ต้องวางใต้ฐานโซนลึกเกิน $8.00 USD ห้ามเข้าออเดอร์เด็ดขาด (`REJECTED_SL_TOO_WIDE`) เพื่อปกป้องเงินทุน

---

## 5. การวิเคราะห์ Multi-Timeframe และ Trigger ใน M5
- **[XAU-RULE-06] Top-Down Execution & Smart Entry Trigger (TF M5/M15)**
  - **H4/D1:** กำหนด Macro Trend และ Key S/R หลัก
  - **H1/M15:** หาโครงสร้างการพักตัว (Market Structure) และระบุโซน Base
  - **M5/M15:** ใช้เป็นจุดลั่นไก (Execution Trigger) เพื่อดักต้นทุนระดับส่วนลดลึก (Discount Zone)
  - **Tight Zone Proximity Rule ($\le 0.35\times \text{ATR}$):**
    - ราคาต้องเข้าเนื้อหรือสัมผัสขอบโซนจริง (Demand: `price <= zone_high + 0.35 * ATR`, Supply: `price >= zone_low - 0.35 * ATR`) ไม่อนุญาตให้ดักล่วงหน้าห่างเกิน $0.35\times \text{ATR}$
  - **Rejection Wick Confirmation Filter ($\ge 25\%$):**
    - ต้องมีไส้เทียนปฏิเสธราคา (Rejection Wick) $\ge 25\%$ ของแท่งเทียน (`lower_wick / candle_range >= 0.25` สำหรับ Buy, `upper_wick / candle_range >= 0.25` สำหรับ Sell) หรือแท่งกลับตัวชัดเจน (Bullish/Bearish Close พ้นกึ่งกลางโซน `zone_mid`)
    - หากราคาสัมผัสโซนแต่ยังไม่พบ Rejection Wick ระบบจะตั้งสถานะเป็น `WAITING_FOR_REJECTION` (Direction: `NEUTRAL`) ห้ามเข้าออเดอร์สวนมีดบินเด็ดขาด
  - **เกณฑ์ตัวเลขเชิงปริมาณสำหรับ Falling Knife / Rocket Surge Guard:**
    - ห้ามเข้าเด็ดขาด หากแท่งเทียนเนื้อตัน $\ge 70\%$ และความยาวแท่ง $\ge 1.8\times \text{ATR}$ (`REJECTED_FALLING_KNIFE` / `REJECTED_ROCKET_SURGE`)

- **[XAU-RULE-16] Smart Limit Order & Dead Man's Switch Protocol**
  - **แก้ปัญหาตกรถแบบไม่ไล่ราคา:** หากราคาเริ่มย่อเข้าใกล้โซน และกำลังรอแท่งกลับตัว (`WAITING_FOR_REJECTION`) อนุญาตให้ส่งคำสั่ง Buy/Sell Limit ลึก 50% ของโซน (`zone_mid`) เพื่อให้ได้ต้นทุนส่วนลดและระยะ SL แคบมาก
  - **Server-side Dead Man's Switch (TTL 10 นาที):** ทุกคำสั่ง Limit ต้องส่ง `type_time = ORDER_TIME_SPECIFIED` พร้อม Expiry เสมอ หากเซิร์ฟเวอร์บอทดับ โบรกเกอร์จะลบทิ้งเองอัตโนมัติ ป้องกัน Order Ghost 100%
  - **Lease Renewal & Lifetime Cap:** Antigravity มีสิทธิ์ต่อเวลา Expiry ออกไปรอบละ 10 นาทีตราบใดที่โครงสร้างราคายังดี แต่จำกัดสูงสุดไม่เกิน 5 ครั้ง (`Max Renewals <= 5`) ป้องกันการแช่ออเดอร์ในโซนเก่าที่หมดแรง
  - **Auto-Cancellation:** สั่ง Cancel ทันทีเมื่อ (1) ราคาวิ่งหนีโซนเกิน $1.5\times \text{ATR}$ (2) เสียทรง Base (3) ตรวจพบข่าวแรง

- **[XAU-RULE-17] US News Blackout Window & Spread Guard**
  - **หน้าต่างเวลางดเทรดช่วงมีข่าวแรง (News Blackout):** บังคับงดตั้ง Pending Order และสั่ง Cancel ออเดอร์ที่ค้างทั้งหมดช่วง 15 นาทีก่อนและหลังข่าวสำคัญสหรัฐฯ:
    - 19:15 - 20:45 น. (CPI, NFP, PPI, GDP, Retail Sales)
    - 20:45 - 22:15 น. (ISM Manufacturing/PMI)
    - 00:45 - 02:30 น. (FOMC Fed Decision)
  - **Spread Expansion Filter:** ตรวจสอบสเปรดแบบ Real-time ก่อนวางหรือต่ออายุ Limit เสมอ หากสเปรดถ่างเกิน $0.40 USD ให้ระงับหรือยกเลิกทันทีเพื่อป้องกัน Slippage

---

## 6. บทเรียน Post-Mortem จากเคสจริง
- **[XAU-RULE-19] Post-Mortem เคสจริง 24 พ.ย. 2026 (Ticket #4772799315 / Deal #4331381214) — กับดักการ Sell ก้นเหวชิดแนวรับวัน**
  - **Trade Summary:** 
    - เปิดสถานะ: **SELL XAUUSDc** 0.06 Lot ที่ `$3,629.52` (เวลา 04:24 UTC / 11:24 BKK)
    - ปิดสถานะ: ชน Stop Loss ที่ `$3,635.50` (เวลา 04:46 UTC / 11:46 BKK) ถือครอง ~22 นาที
    - ผลขาดทุนสุทธิ: **-35.90 USC** (คิดเป็นเงินจริงเพียง -$0.36 USD หรือ **-12.56 บาท**) พอร์ตยุบเพียง **2.39%** จาก 1,500 USC
  - **สิ่งที่ทำได้ถูกต้องตาม Risk Control:**
    - มี **Hard Stop Loss** ล็อกเด็ดขาดที่ $3,635.50 (ระยะ $5.98 USD อยู่ในเพดาน $6.00 พอดี)
    - ระบบเงินทุน Cent ปกป้องเงินจริงได้อย่างยอดเยี่ยม ขาดทุนเพียง 12 บาท ไม่กระทบกระเป๋าเงินจริง
  - **Root Cause Analysis (ข้อผิดพลาดเชิงโครงสร้างที่เกิดขึ้นจริง):**
    - **1. Selling into Support / Low of Day Trap:** 
      - บอทมองเห็นแท่ง M15 หลุดเบรกฐาน $3,629 จึงมองเป็น Role Reversal Retest แล้วกด Sell ตามน้ำ
      - แต่ **มองข้ามไปว่าข้างล่างที่ระดับ $3,624 – $3,626 คือ Low ของวันและแนวรับใหญ่** ทำให้มีระยะวิ่งเหลือเพียง $3 – $4 ดอลลาร์ (แคบกว่า $1.5\times \text{ATR}$)
      - ทันทีที่ราคาลงไปแตะ Low ของวัน ($3,624.17) ก็เกิดแรง **Technical Bounce ดีดกลับรวดเดียวขึ้นมาแตะ $3,637** ลากกิน Stop Loss ของเราทันทีตามที่คุณสังเกตไว้เป๊ะ!
    - **2. ขาดการยืนยันด้วย Fibonacci Retracement:**
      - การ Sell ที่ $3,629 เป็นการ Sell ที่ปลายคลื่นขาลง (ราคาได้ทิ้งตัวมาจากยอดเช้า $3,678 ลงมาถึง $3,624 แล้วกว่า $54 ดอลลาร์) ถือเป็นจุดขายที่ "ขายของถูก (Deep Discount)" ซึ่งเสียเปรียบสถิติอย่างรุนแรง
  - **มาตรการป้องกันถาวรที่ติดตั้งแล้ว (Permanent Countermeasures):**
    - ติดตั้ง **`[XAU-RULE-10]` (Dynamic Downside Headroom Guard):** ห้าม Sell เด็ดขาดถ้าระยะห่างจากแนวรับหรือ Low วัน $< 1.5\times \text{ATR}$
    - ติดตั้ง **`[XAU-RULE-18]` (Multi-Swing Fibonacci Hierarchy):** บังคับให้การ Sell ต้องเกิดที่ระดับย่อเด้งใน **Golden Zone (61.8% – 65% OTE – 78.6%)** ของคลื่นสวิงหลักเท่านั้น ห้ามไล่ Sell ที่ปลายคลื่นเด็ดขาด

- **[XAU-RULE-20] Post-Mortem เคสจริง 24 พ.ย. 2026 (Ticket #4773545612 / Deal #4332120699) — ดัก Buy ไม้แรกช่วงตลาดเอเชีย โดนกวาด Liquidity Sweep ก่อนดีดจรวด $18+**
  - **Trade Summary:**
    - เปิดสถานะ: **BUY XAUUSDc** 0.06 Lot ที่ `$3,623.75` (เวลา 06:08 UTC / 13:08 BKK)
    - เป้าหมายกำไร (TP): `$3,639.32` | จุดตัดขาดทุน (SL): `$3,617.62` (ระยะ $6.13 USD)
    - ปิดสถานะ: ชน Stop Loss ที่ `$3,617.62` (เวลา 06:28 UTC / 13:28 BKK) ถือครอง ~20 นาที
    - ผลขาดทุนสุทธิ: **-36.80 USC** (คิดเป็นเงินจริงเพียง -$0.37 USD หรือ **-12.88 บาท**) พอร์ตปลอดภัย ไร้ความเสียหายหนัก
  - **พฤติกรรมราคาที่เกิดขึ้นจริง (Price Action Timeline):**
    1. **13:05 - 13:08 น.:** ราคาทิ้งตัวลงมาจาก $3,633 ลงมาทำ Low ที่ $3,618.67 แล้วเกิดแท่งไส้ยาวเด้งกลับขึ้นมา $3,623.75 บอทตรวจพบ Rejection Wick ในโซนแนวรับจึงเข้า BUY
    2. **13:08 - 13:11 น.:** ราคาวิ่งขึ้นไปตามแผนจริงๆ! พุ่งขึ้นแตะ **$3,630.62** (บวกกำไรลอยตัว **+$6.87 USD** หรือ **+41.22 USC** คิดเป็น **+1.12x R**)
    3. **13:15 - 13:28 น.:** เนื่องจากระบบยังไม่มีฟังก์ชัน Lock Breakeven หรือ Partial TP เมื่อบวกเกิน 1R ราคาวนกลับลงมาทดสอบก้นเหวอีกครั้ง (Double Bottom Retest)
    4. **13:28 น. (Stop Hunt / Liquidity Sweep):** ตลาดเอเชียช่วงบ่าย (13:00-13:30 น.) สภาพคล่องเบาบาง มักเกิดการ "รูดทะลุ Low เดิมเพื่อกวาดสภาพคล่อง (Sweep Equal Lows)" ราคารูดทะลุ $3,618 ลงไปแตะ $3,616.99 กิน SL ของเราที่ $3,617.62 ไปพอดี!
    5. **13:37 - 13:50 น. (The Rocket Rally):** หลังจากราคาลงไปกวาด Liquidity จุดต่ำสุดที่ $3,613.66 เสร็จสิ้น ราคากลับตัวรูปตัว V วิ่งพุ่งจรวดขึ้นรวดเดียว **+$18.00** กลับขึ้นไปถึง **$3,632.00+** ทันที!
  - **สิ่งที่ทำได้ดี (Risk Management Success):**
    - ทิศทางวิเคราะห์โครงสร้างแนวรับและจังหวะเด้งของราคาถูกต้อง (ราคาบวกไปจริงถึง +1.12x R)
    - คุมขนาด Lot 0.06 บนพอร์ต Cent ได้อย่างแม่นยำ ขาดทุนเพียง 12 บาท ไม่สะเทือนเงินทุนหลัก
  - **บทเรียนและกฎเหล็กที่สกัดได้ (Actionable Rules & Upgrades):**
    - **1. กฎเลื่อน Stop Loss บังหน้าทุนเมื่อได้กำไร +1.0x R (Breakeven Lock Guard):**
      - เมื่อออเดอร์มีกำไรลอยตัวแตะ $\ge +1.0\times R$ (ในเคสนี้คือบวกเกิน $6.13 USD ซึ่งราคาไปถึง +$6.87) ระบบต้อง **ย้าย SL ขึ้นมาบังหน้าทุนทันที (Entry + Broker Spread)** เพื่อการันตีว่า "ไม้ที่กำไรแล้ว จะต้องไม่มีวันกลับมาขาดทุนเต็มไม้เด็ดขาด"
    - **2. หลีกเลี่ยงการรับมีดขาแรกช่วงตลาดเอเชีย (Asian Liquidity Sweep Delay):**
      - ช่วงตลาดเอเชีย (10:00 - 14:00 น. BKK) ความผันผวนมักเป็นการเคลียร์สภาพคล่อง ห้าม Buy รับมีดที่เด้งขึ้นมาครั้งแรก (1st Leg) ให้รอสร้างฐาน **Higher Low (ขาที่ 2 ของรูปตัว W)** บน M5 หรือรอให้เกิด Liquidity Sweep หลุด Low เดิมแล้วแท่งเทียนดึงกลับปิดเหนือขอบ (Reclaim) จึงจะปลอดภัยสูงสุด

- **[XAU-RULE-21] สถาปัตยกรรมระบบการเทรดระยะยาว: Breakeven Engine & Decoupled Limit Execution (Anti-Overfitting)**
  - **1. Automatic Breakeven Guard (ล็อกทุนอัตโนมัติเมื่อแตะ $\ge +1.0\times R$):**
    - ติดตั้งระบบเฝ้าระวังตำแหน่งเปิดแบบเรียลไทม์ผ่าน `check_and_apply_breakeven_locks(min_r_multiple=1.0)`
    - เมื่อออเดอร์มีกำไรลอยตัว $\ge +1.0\times R$ (คำนวณจากระยะห่างจุดเข้าถึง SL เริ่มต้น) ระบบจะส่งคำสั่ง `TRADE_ACTION_SLTP` ปรับ SL มาที่ `Entry Price ± (Live Spread + 0.10 USD)` ทันที
    - เปลี่ยนสถานะออเดอร์ให้เป็น **Free Trade** คุ้มครองเงินทุน 100% ป้องกันกำไรกลับกลายเป็นขาดทุน
  - **2. Decoupled Limit/Pullback Execution (ห้ามไล่ราคาที่ยอดเด้ง):**
    - หากราคาเด้งออกจากฐาน Demand หรือร่วงจาก Supply เกิน $0.40\times\text{ATR}$ $\rightarrow$ บล็อกการส่งคำสั่ง Market Order ทันที
    - ระบบจะสลับเป็นโหมด `ACTIONABLE_BUY_LIMIT` หรือ `ACTIONABLE_SELL_LIMIT` ดักที่ระดับ **Fibonacci 65.0% OTE หรือกึ่งกลางโซนแนวรับ/ต้าน** เพื่อให้ได้ต้นทุนที่ได้เปรียบสถิติและคุม SL ไม่เกินเพดาน $6.00 USD
  - **3. Asian Session Liquidity Filter (10:00 – 14:00 น. BKK):**
    - ช่วงเวลาตลาดเอเชียที่มีสภาพคล่องเบาบาง บังคับใช้โหมด Limit Order ดักย่อลึกเท่านั้น ห้ามเข้า Market BUY ไม้แรกที่ราคาเพิ่งแตะ Day Low เพื่อหลบเลี่ยงกับดัก Equal Lows Liquidity Sweep อย่างเด็ดขาด

- **[XAU-RULE-11] Lessons จากเคสจริง 23 พ.ย. 2026 (Case #5109763771 & #5111695765)**
  - **Case 1 (Sell สวนเทรนด์ & บัฟเฟอร์หลุด):** ตั๋ว #5109763771 โดนลาก SL -55.82 USD เนื่องจากเปิด Sell สวนโมเมนตัมช่วง London Session $\rightarrow$ *ล็อกตัวคูณ ATR และ Max SL ไม่เกิน $6.00 USD เสมอ พร้อมตรวจเทรนด์ M15/H1*
  - **Case 2 (Buy ยอดดอยติดแนวต้าน Supply):** ตั๋ว #5111695765 เปิด Buy ที่ $3,633.93 ชนเพดานต้าน M15 พอดี $\rightarrow$ *บังคับใช้ Headroom Guard < 1.0x ATR ห้าม Buy เด็ดขาด*
  - **Case 3 (TP ไกลเกินจริง vs Realistic Winrate):** ตั๋ว #5116365530 (24 พ.ย. 2026) ขายที่ $3,671.24 ตั้ง TP ลึกที่ $3,634.51 (R:R 1:5.7) $\rightarrow$ *เก็บเป็นเคสศึกษาดูพฤติกรรมราคา แต่รอบถัดไปต้องเน้นความเป็นไปได้จริง (Realistic Winrate & Advantageous Exit) ดักเก็บกำไรหน้าแนวรับที่ใกล้ที่สุด ไม่ข้ามโซน และคุม R:R อยู่ที่ 1:1.5 ถึง 1:2.5*

- **[XAU-RULE-22] Multi-Timeframe M5 Sniper Trigger & Structural Stop Loss Workflow**
  - **1. โครงสร้าง 3 Timeframes (Top-Down Architecture):**
    - **1H / 15m:** กำหนดแนวรับ-แนวต้านหลัก และกล่อง Base ของ Demand/Supply (DBR, RBR, RBD, DBD) พร้อมคำนวณคลื่น Fibonacci Swings
    - **M5:** ทำหน้าที่เป็น **Execution Sniper Trigger** ดักตรวจจับแท่งเทียนกลับตัว (Rejection Wick $\ge 25\%$) เมื่อราคาเดินทางเข้าสู่เนื้อโซนของ 15m/1H
  - **2. การรักษา Stop Loss เชิงโครงสร้าง (Structural SL Protection):**
    - **ห้ามบีบ SL ให้แคบเกินธรรมชาติเด็ดขาด:** เพื่อป้องกันไม่ให้ถูกสเปรดหรือไส้เทียนกวาดกินฟรี (Stop-Hunt Noise)
    - **จุด SL ฝั่ง BUY:** วางใต้ขอบล่างของ Demand 15m/1H ลบด้วย Moat Buffer ($0.75\times\text{ATR}$ + Spread)
    - **จุด SL ฝั่ง SELL:** วางเหนือขอบบนของ Supply 15m/1H บวกด้วย Moat Buffer ($0.75\times\text{ATR}$ + Spread)
  - **3. เพดานจำกัดความเสี่ยงและการถอยไปใช้ Pending Limit (Hard SL Cap $\le \$8.00$):**
    - หากสภาวะตลาดมีความผันผวนสูงจนระยะ SL เชิงโครงสร้างกว้างเกิน $8.00 USD ระบบจะระงับการเข้า Market Order ทันที
    - ระบบจะสลับไปแนะนำโหมด `ACTIONABLE_BUY_LIMIT` หรือ `ACTIONABLE_SELL_LIMIT` ดักรอที่ระดับ **Fibonacci 65.0% OTE หรือกึ่งกลางโซน** เพื่อลดระยะ SL ให้อยู่ในกรอบปลอดภัย

- **[XAU-RULE-23] Dynamic Limit Order Lifecycle Management (วงจรบริหารจัดการคำสั่ง Limit อัตโนมัติ)**
  - **1. การวาง Pending Limit ล่วงหน้าที่จุดได้เปรียบ (Strategic Pre-placement):**
    - วาง Buy Limit / Sell Limit ดักล่วงหน้าที่ระดับ Fibonacci 65.0% OTE หรือกึ่งกลางโซน Base (Discount 50%) พร้อมตั้ง SL ($\le \$8.00$) และ TP ($R:R \ge 1.50$) ในตัวเสมอ
    - ไม่ต้องเสียเวลารอแท่งเทียนปิด ช่วยให้ไม่ตกรถตอนตลาดสะบัดไส้กวาดสภาพคล่อง (Fast Wick Match)
  - **2. วงจรการตรวจสอบในแต่ละลูป (Reconciliation in 60s - 90s Schedule Loop):**
    - ในแต่ละรอบที่บอทประมวลผล จะตรวจสอบคำสั่ง Limit ที่ค้างอยู่ 4 ประการ:
      - (1) **CANCEL ทันที** หากมีข่าวแรง (News Blackout) หรือ Spread ขยายเกิน $0.40 USD
      - (2) **CANCEL ทันที** หากเกิดแท่งเทียนทิ้งตัวรุนแรง (Falling Knife สำหรับ Buy Limit หรือ Rocket Surge สำหรับ Sell Limit) เพื่อไม่ให้โดนทับ
      - (3) **CANCEL ทันที** หากโครงสร้างโซนถูกทำลาย (ราคาหลุดทะลุแนวรับ/ต้านหลัก)
      - (4) **CANCEL ทันที** หากราคาวิ่งหนีโซนออกไปเกิน $1.5\times\text{ATR}$ หรือครบอายุต่อเวลา 5 ครั้ง (`Max Renewals <= 5`)
  - **3. การส่งมอบไม้ไปยัง Position Manager:**
    - ทันทีที่ออเดอร์ Limit ถูกเกี่ยว (Filled) ระบบ Position Manager จะเข้ามารับช่วงต่อทันที เพื่อเลื่อน SL บังทุน (Breakeven Lock) เมื่อกำไรแตะ $+1.0\times R$

- **[XAU-RULE-24] Post-Mortem เคสจริง 24 พ.ย. 2026 (Ticket #4776526473 / Deal #4334936583) — รับมีดตกช่วง London-NY Overlap หลังทิ้งตัว $25+ ดอลลาร์รวดเดียว**
  - **Trade Summary:**
    - เปิดสถานะ: **BUY XAUUSDc** 0.06 Lot ที่ `$3,622.43` (เวลา 13:39:44 UTC / 20:39:44 BKK)
    - เป้าหมายกำไร (TP): `$3,636.62` | จุดตัดขาดทุน (SL): `$3,613.86` (ระยะ $8.57 USD)
    - ปิดสถานะ: ชน Stop Loss ที่ `$3,613.86` (เวลา 14:00:02 UTC / 21:00:02 BKK) ถือครอง ~20 นาที
    - ผลขาดทุนสุทธิ: **-51.40 USC** (คิดเป็นเงินจริงเพียง -$0.514 USD หรือ **-17.99 บาท**)
  - **พฤติกรรมราคาที่เกิดขึ้นจริง (Price Action Timeline):**
    1. **19:00 - 19:45 น. (NY Pre-Market Spike):** ราคาทองพุ่งขึ้นไปทำ New High ประจำวันที่ **$3,646.80**
    2. **20:20 - 20:39 น. (Heavy Cascading Drop):** ทันทีที่เข้าช่วง London × NY Overlap เกิดแรงเทขายทิ้งตัวรวดเดียว 4 แท่ง M5 ติดกัน จาก $3,646 ร่วงลงมาแตะ $3,619 (-$27 ดอลลาร์)
    3. **20:39 น. (Entry Trap):** บอทตรวจพบราคาแตะโซนแนวรับเดิมที่เคยเด้งช่วงกลางวัน ($3,620 - $3,623) และเริ่มมีไส้กระตุกสั้น จึงเข้า BUY ที่ $3,622.43
    4. **20:40 - 21:00 น. (Second Leg Flush / Waterfall):** แท่งเทียนยังคงเป็น Bearish Momentum ไหลรูดลงต่อเนื่อง แท่ง 20:55 - 21:00 น. เทขายกดราคาหลุดลงไปทำ Low ที่ $3,613.23 กิน SL ของเราที่ $3,613.86 ไปพอดี
    5. **หลัง 21:00 น. (Bounce after SL Hit):** เมื่อราคาแตะ $3,613.23 (กวาดสภาพคล่องขอบล่างสมบูรณ์) แท่ง 21:00-21:30 น. ก็ดีดตัวรูปตัว V ทันทีกลับขึ้นมาแตะ $3,621+
  - **Root Cause Analysis (วิเคราะห์สาเหตุแท้จริง):**
    1. **Falling Knife ในช่วง Overlap High Volatility:** การเข้า Buy สวนแรงทิ้งตัวลงมา -$25 USD รวดเดียวโดยที่แท่ง M5 ยังไม่มีการปิดเขียวยืนยัน หรือยังไม่มีโครงสร้างสะสมฐาน (Base Absorption) ถือเป็นการ "รับมีดบิน (Catching a Falling Knife)"
    2. **SL กว้างแตะ $8.57 USD:** ระยะ SL $8.57 USD เกินเพดานปลอดภัยของ Hard SL Cap ($8.00) เล็กน้อย ทำให้เสี่ยงขาดทุนมากกว่าปกติ
    3. **False Support Memory:** โซน $3,622 ที่เคยรับอยู่ตอนบ่าย ไม่สามารถนำมาเป็นแนวรับที่แข็งแรงได้ในช่วง NY Session ที่มีปริมาณการซื้อขายมหาศาลทะลุเข้ามา
  - **มาตรการป้องกันถาวร (Actionable Safeguards):**
    1. **Strict Waterfall/Cascade Filter:** หากราคาในแท่ง M5 ร่วงติดต่อกัน $\ge 3$ แท่ง ด้วยระยะรวม $\ge 2.5\times\text{ATR}$ ห้ามเข้า Buy ทันทีเด็ดขาด ต้องรอให้มีแท่ง Bullish M5 ปิดเต็มตัวอย่างน้อย 1 แท่งเพื่อยืนยันการหยุดไหลของโมเมนตัม
    2. **NY Overlap Liquidity Sweep Patience:** ช่วงเวลา 20:00 - 22:30 น. หากราคาทิ้งตัวลงมาทดสอบ Low กลางวัน มักจะมีการ Flush หลุด Low เดิม 5-10 USD เสมอ ให้ตั้งรับด้วย Buy Limit ลึกกว่า Low เดิม หรือรอ Reclaim ปิดยืนเหนือ Low เดิมเท่านั้น


