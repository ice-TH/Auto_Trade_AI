# BTC/USD (Bitcoin) Strategy Playbook (คู่มือการเทรดบิตคอยน์)
*สเปกสัญญา: Exness BTCUSD (Fixed Volume 0.01 BTC)*
*สไตล์การเทรด: M5 Top-Down Execution Scalper (อัปเกรดจาก 1m เพื่อลด Noise และสเปรด)*

---

## 1. การลั่นไกและการควบคุมโมเมนตัม (M5 Execution)
- **[BTC-RULE-00] กฎเหล็ก 1 ไม้ต่อ 1 พอร์ต (Single-Position Rule)**
  - ห้ามเปิดออเดอร์ซ้อน (No Stacking) และห้ามเปิดไม้สวนทางกันเอง (No Hedging)
  - ต้องรอให้ไม้ BTC เดิมปิดสถานะเรียบร้อยก่อนจึงจะอนุญาตให้ออกคำสั่งใหม่ได้
- **[BTC-RULE-02] Macro Trend Alignment (H1/Day Filter)**
  - ตรวจสอบเทรนด์ใหญ่ผ่าน EMA 50 หากราคาภาพใหญ่อยู่ในฝั่งขาลง (Bearish) ระบบจะสั่งบล็อกคำสั่ง Buy ทันที (`REJECTED_MACRO_BEARISH`) เพื่อป้องกันการรับมีดตก
- **[BTC-RULE-03] การลั่นไกใน M5 และ Rejection Confirmation**
  - ไม่เล่นบน M1 เพื่อลดสัญญาณหลอก (False Break) โดยใช้ M5 เป็นไกตัดสินใจ
  - ต้องมีแท่ง Rejection Wick (ไส้เทียนล่าง $\ge 30\%$ ของความยาวแท่ง) เด้งจาก Demand Zone ก่อนเข้าทำ
- **[BTC-RULE-04] Fixed Volume 0.01 Lot เท่านั้น**
  - ล็อกขนาดพอร์ตที่ 0.01 Lot (0.01 BTC) เสมอเพื่อความปลอดภัยของพอร์ต

---

## 2. สูตรคำนวณระยะ TP/SL แบบรวมสเปรด
- **[BTC-RULE-01] Front-Running TP & Moat-Buffered SL**
  - **ห้ามตั้ง TP บนเส้นแนวต้านพอดี:** ให้ร่นระยะ TP ถอยลงมาด้านหน้าอย่างน้อย `0.35x ATR + Live Spread` เพื่อชิงทำกำไรก่อนโดนเทขาย
  - **ห้ามตั้ง SL บนเส้นแนวรับพอดี:** ต้องวาง SL หลบไส้เทียนลึกลงไปใต้ขอบล่างของ Demand Zone อย่างน้อย `0.8x ATR + Live Spread ของ Exness` เพื่อป้องกันการโดนกวาด Stop Hunt

---

## 3. บทเรียน Post-Mortem จากเคสจริง (BTC Case Studies)
- **[BTC-RULE-05] Trend-Holding & Psychological TP Execution (เรียนรู้จากเคสไม้ชนะล่าสุด #5106631710 / Deal #4513914822)**
  - **Trade Summary:** เข้าซื้อ BUY BTCUSDm 0.01 Lot ที่ $61,285.96 USD ถือครองข้ามวัน ~25.5 ชั่วโมง ชน Take Profit ที่ $63,000.00 USD (`[tp 63000.00000]`) ฟันกำไรสุทธิ **+$17.14 USD** (~**+599.90 THB**) Realized R:R `1 : 1.33+`
  - **Patience on Valid Structural Entry (วินัยในการถือครองตามแผน):** เมื่อเข้าออเดอร์ตามโครงสร้างแนวรับที่มี Hard Stop Loss ชัดเจนใต้แนวรับสำคัญ ($60,000) และภาพใหญ่ยังคงเป็น Macro Bullish ให้รักษาวินัยถือครองตามแผน ไม่ปิดทำกำไรก่อนเวลา (No Premature Close) เพื่อเปิดโอกาสให้กำไรวิ่งชนเป้าหมายเต็มเม็ดเต็มหน่วย
  - **Psychological Round Numbers Target (การตั้งเป้าตัวเลขกลม):** ระดับราคาจิตวิทยา เช่น $63,000 มักมีสภาพคล่องหนาแน่น การตั้งเป้า Take Profit ชนระดับดังกล่าวส่งผลให้คำสั่งจับคู่ได้แม่นยำและรวดเร็ว
  - **Validation of Single-Position Rule:** การถือครองเพียง 1 ไม้ตลอด 25 ชั่วโมง ช่วยป้องกันพอร์ตจาก Margin Drawdown และควบคุมอารมณ์ในการเทรดได้อย่างสมบูรณ์แบบ
