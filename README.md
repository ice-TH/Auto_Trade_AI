# AutoTrade - US Equities Analysis & MT5 CFD Trading System (Modern Fintech Light / Dime Style)

ระบบเว็บแดชบอร์ดสำหรับวิเคราะห์หุ้นสหรัฐฯ (AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA) บริหารความเสี่ยงเชิงปริมาณ และเชื่อมต่อการซื้อขาย CFD ผ่าน MetaTrader 5 (Exness Demo) ออกแบบด้วยสไตล์ **Modern Fintech Light (Dime Style)** ทำงานแบบสแตนด์อโลนบนเครื่องส่วนตัว (Localhost) ปลอดภัย ตรวจสอบย้อนหลังได้ 100% และมาพร้อมระบบความจำการเรียนรู้ต่อเนื่องของ **Antigravity AI (Continuous Learning Memory)**

---

## สรุปสถานะระบบล่าสุด (Current Capabilities & Enhancements)

| หมวดหมู่ | รายละเอียดความสามารถ | สถานะ |
| :--- | :--- | :--- |
| **สินทรัพย์ที่รองรับ** | • หุ้นสหรัฐฯ 7 ตัว (AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA)<br>• โหมดทดลองเล่น **BTCUSDm (Bitcoin)** กรอบ 1m Fast Scalper<br>• โหมดวิเคราะห์และเทรดกลยุทธ์ **XAUUSDm / XAUUSDc (Gold)** Price Action Multi-TF Demand/Supply + Multi-Swing ZigZag Fibonacci | ✅ พร้อมใช้งานครบ |
| **Feed เริ่มต้น (Default Feed)** | ปรับให้เชื่อมต่อสดกับ **Exness MT5 (Live Feed)** เป็นค่าเริ่มต้นทันทีที่เปิดเว็บ พร้อมดึง Balance จริงจากพอร์ตอัตโนมัติ (รองรับทั้ง USD บัญชี Demo และ USC บัญชี Real Cent) | ✅ อัปเดตล่าสุด |
| **Real-Time Polling** | แท็บ *MT5 Orders & Positions* อัปเดตราคา, Floating P/L, Balance และ Margin สดทุก 3 วินาทีอัตโนมัติ | ✅ พร้อมใช้งาน |
| **กลยุทธ์ทองคำ XAU/USD (Gold Strategy)** | • **Multi-TF Base Structure:** ตรวจจับ Base สะสมจริง (DBR, RBR, RBD, DBD) บน M15 และ H1 (*ห้ามใช้ Order Block/OB เด็ดขาด*)<br>• **Multi-Swing ZigZag Fibonacci (PineScript V3):** ตรวจจับ Swing ด้วย ZigZag Pivot (`pivot_legs=8`, `min_deviation_pct=0.8%`) แยก Major และ Minor Swing พร้อมวิเคราะห์ Golden Zone 0.618 - 0.650 (OTE) - 0.786 และจุด Double Confluence<br>• **Dynamic Downside Headroom Guard:** ป้องกันการ Sell ใส่แนวรับหรือ Low of Day หากระยะห่าง < 1.5x ATR (`REJECTED_NEAR_SUPPORT_HEADROOM`)<br>• **Decoupled Limit / Pullback Entry:** หากราคาเด้งห่างฐานเกิน $0.4\times\text{ATR}$ หรืออยู่ในช่วงตลาดเอเชีย สลับเป็น Buy/Sell Limit ดักย่อที่ Fibo 65% OTE ทันที ไม่ไล่ราคาที่ยอดเด้ง<br>• **Automatic Breakeven Engine:** ตรวจสอบตำแหน่งเปิดสดทุก 3 วินาที เลื่อน SL มาล็อกหน้าทุน (`Entry + Spread + 0.10`) ทันทีเมื่อกำไรลอยตัว $\ge +1.0\times R$ การันตี Free Trade<br>• **Tight Base Boundaries:** บีบกรอบ Base กว้างสูงสุดไม่เกิน $1.5\times \text{ATR}$ (`clamp_zone_size`) ไม่ตีกล่องบวม<br>• **Zone Fusion:** รวมโซน M15 และ H1 ที่ทับซ้อนเป็น High Confluence Zone เดียว (`combine_overlapping_zones`)<br>• **Broken Zone Lifespan:** ตัดจบโซนทันทีที่ถูกทำลาย ไม่ลากยืดข้ามมาผ่ากราฟปัจจุบัน<br>• **Rejection Wick Filter:** ต้องมีไส้เทียนปฏิเสธราคา $\ge 25\%$ หรือแท่งกลับตัวชัดเจน ไม่เข้าสวนมีดตก (`REJECTED_FALLING_KNIFE` / `REJECTED_ROCKET_SURGE`)<br>• **Session Overlap:** ดักจังหวะทองช่วง **London × New York Overlap (20:00 - 23:00 น. BKK)**<br>• **Hard SL Cap:** จำกัดระยะ SL ไม่เกิน $6.00 USD พร้อม Moat Buffer และห้ามถือข้ามวัน (No Overnight) | ✅ ผ่านเกณฑ์ทดสอบ 100% |
| **โครงข่ายความจำ 3 ชั้น (3-Tier AI Memory)** | • SQLite `trade_history` (Tier 1)<br>• แฟ้มกรณีศึกษาถอดบทเรียน `memory/cases/` (Tier 2)<br>• **Modular Playbook System:** แยกคู่มือเฉพาะสินทรัพย์ใน `memory/playbooks/` (`xauusd_gold.md`, `us_equities.md`) บันทึกกฎ [XAU-RULE-10], [XAU-RULE-16], [XAU-RULE-18], [XAU-RULE-19], [XAU-RULE-20], และ [XAU-RULE-21] สถาปัตยกรรม Breakeven & Anti-Chasing แล้วคอมไพล์รวมศูนย์สู่ `memory/playbook.md` (Tier 3) | ✅ อัปเกรดแบบโมดูลาร์ |
| **ระบบความปลอดภัยเข้มงวด** | • ล็อกการส่งคำสั่ง BTC / XAU ไว้เฉพาะพอร์ต Demo `#434552387` และ พอร์ต Real Cent `#160219615` (คู่เงิน `XAUUSDc` เท่านั้น ล็อก Volume คงที่ 0.06 Lot)<br>• **Single-Position Rule:** 1 สินทรัพย์ต่อ 1 ออเดอร์ ห้ามเปิดไม้ซ้อน และห้าม Hedging (Buy ชน Sell) เด็ดขาด<br>• **Live Spread Guard:** ระงับคำสั่งทันทีหากสเปรดทองคำ $> 0.50 \text{ USD}$ (50 จุด)<br>• บังคับใส่ Hard Stop Loss ทุกไม้ และ R:R ต้อง $\ge 1.50$ เสมอ | ✅ รัดกุม 100% |
| **การคำนวณ TP/SL เชิงรุก** | • **Front-Running TP:** ร่นระยะ TP ลงมาดักหน้าขอบแนวต้านเพื่อชิงทำกำไรก่อนคนอื่น<br>• **Moat-Buffered SL:** คำนวณ SL หลบใต้แนวรับด้วยระยะ `ATR Buffer + Live Broker Spread` ป้องกันโดนกวาด Stop Hunt | ✅ คำนวณสด |
| **Pro Trading Journal (Gallery)** | ภาพ Snapshot กราฟความละเอียดสูง มีแกนเวลา (BKK Time), สเกลราคาและตาราง Grid, ปริมาณการซื้อขาย (Volume), เส้น **MA(50) & MA(200)**, และโซนแนวรับ-แนวต้าน | ✅ ปรับปรุงใหม่ |

---

## ฟังก์ชันเด่นบนหน้า Web Dashboard (9 แท็บครบวงจร)

1. **Overview (ภาพรวมระบบ):** แสดงสถานะการเชื่อมต่อ, พอร์ตที่ผูกอยู่, ยอดเงินทุนจริงจาก MT5, และตารางสเปกสินทรัพย์
2. **Interactive Charts (กราฟเทคนิคัลสด):** กราฟแท่งเทียนความเร็วสูง (Lightweight Charts Offline) สลับ Timeframe M1/M15/DAY/WEEK, เปิด/ปิด EMA และโซน S/R ได้อิสระ
3. **⚡ Plans & AI Analysis (แผนการเทรดและบทวิเคราะห์ AI ภาษาไทย):**
   - การ์ดแผนการเทรดแบบ Dime Card แสดงราคาเข้า (Entry), ตัดขาดทุน (SL), ทำกำไร (TP), และขนาด Lot
   - บทวิเคราะห์ตลาด 4 มิติจาก AI (Macro Week, Day Structure, Headroom Guard, Actionable Verdict)
   - ปุ่มลัด: *⚡ สแกนแผนหุ้น 7 ตัว*, *📋 คัดลอกข้อมูลให้ Antigravity*, *⚡ วิเคราะห์ BTC 1m (โหมดซิ่ง)*, *⚡ วิเคราะห์ XAU/USD (ทองคำ)*
   - สมุดบันทึกเหตุผลที่ไม่เข้าเทรด (**Non-Entry Reasons Journal**)
4. **💼 MT5 Orders & Positions (จัดการออเดอร์สด):**
   - แสดงสถานะ Balance, Equity, Free Margin และกำไร/ขาดทุนสดทุก 3 วินาที
   - ปุ่มปิดออเดอร์รายไม้ และปุ่ม Emergency Kill Switch ฉุกเฉิน
   - หน้าต่าง **Two-Step Order Confirmation Modal** ตรวจทานความเสี่ยงก่อนส่งคำสั่ง
5. **📈 Backtest & Analytics (ทดสอบย้อนหลัง):**
   - เปรียบเทียบผลงาน **In-Sample (70%) vs Out-of-Sample (30%)**
   - กราฟเส้นการเติบโตของพอร์ต (**Portfolio Equity Curve**) และสถิติ Win Rate %, Profit Factor, Max Drawdown
6. **S/R Zones & Tools (โซนแนวรับ-แนวต้าน):** ตรวจจับโซนอัตโนมัติจาก Fractal Pivot พร้อมเครื่องมือกำหนด/ล็อกโซนด้วยตนเอง
7. **Journal & Gallery (สมุดภาพบันทึกกราฟระดับ Pro):** เก็บภาพ Snapshot การเทรดแบบคมชัด พร้อมเส้น MA 50, MA 200, Volume, วันเวลา, และข้อมูล Metadata
8. **🧠 AI Memory & Playbook (โครงข่ายความจำและการเรียนรู้ของ AI ภาษาไทย):**
   - **ฝั่งซ้าย:** กฎเหล็กสั่งการที่กลั่นกรองแล้วใน [memory/playbook.md](file:///d:/Antigavity/Auto_Trade/memory/playbook.md) (แบ่งหมวด Core Safety, ทองคำ XAU, บิตคอยน์ BTC, และหุ้นสหรัฐฯ ชัดเจน)
   - **ฝั่งขวา:** แฟ้มบทเรียนและสาเหตุรายไม้ (**Case Studies**) วิเคราะห์สาเหตุแท้จริง (Root Cause) เมื่อแพ้หรือชนะ
   - ปุ่มลัด: *🔄 ดึงประวัติไม้ที่ปิดจาก MT5 (Sync History)*, *📄 โหลดกฎ Playbook ใหม่*, และ *🔨 Compile Playbook*
9. **Settings & Safety (การตั้งค่าและความปลอดภัย):** ควบคุมสิทธิ์ความเสี่ยง, สวิตช์เปิด/ปิด Auto-Execution, และปุ่มหยุดระบบชั่วคราว

---

## โครงสร้างโฟลเดอร์สำคัญ (Project Architecture)

```text
Auto_Trade/
├── config/
│   ├── settings.py           # การตั้งค่าระบบหลักและพาธไฟล์
│   └── symbols.yaml          # สเปกหุ้น 7 ตัว + BTCUSDm + XAUUSDm
├── data_store/
│   └── autotrade.db          # ฐานข้อมูล SQLite (zones, plans, audit_logs, trade_history)
├── memory/                   # 🧠 โครงข่ายความจำของ Antigravity AI
│   ├── playbook.md           # กฎสั่งการแม่บทที่รวมศูนย์จากการคอมไพล์ (Tier 3)
│   ├── playbooks/            # 📁 โมดูลกฎเฉพาะสินทรัพย์ (Modular Playbooks)
│   │   ├── us_equities.md    # กฎการเทรดหุ้นสหรัฐฯ 7 ตัว
│   │   └── xauusd_gold.md    # กฎการเทรดทองคำ XAU/USD (S/D, Sessions, Rejection)
│   └── cases/                # แฟ้มกรณีศึกษาถอดบทเรียนรายไม้ (Tier 2)
├── screenshots/              # คลังภาพกราฟ Snapshot ความละเอียดสูงจัดตาม วันที่/คู่เงิน/TF
├── src/
│   ├── analysis/
│   │   ├── ai_analyzer.py    # เครื่องมือวิเคราะห์ตลาด 4 มิติ
│   │   ├── btc_scalper.py    # โหมดซิ่ง BTC 1m Fast Scalper
│   │   ├── gold_strategy.py  # โหมดกลยุทธ์ทองคำ XAU/USD (Price Action S&D, Sessions)
│   │   ├── indicators.py     # คำนวณ EMA, ATR, RSI, Volume MA
│   │   ├── playbook_compiler.py # ตัวรวบรวมโมดูลกฎเข้าสู่ memory/playbook.md
│   │   ├── trade_reviewer.py # ดึงประวัติไม้ปิด MT5 และวิเคราะห์ Root Cause
│   │   └── zones.py          # ตรวจจับ Fractal Support & Resistance
│   ├── capture/
│   │   └── screenshot_service.py # เรนเดอร์กราฟ Pro Matplotlib (MA50/200, Volume, Grid)
│   ├── data/                 # MT5 Live IPC Adapter & Mock Adapter
│   ├── execution/
│   │   ├── agent_bridge.py   # CLI Bridge สำหรับให้ Antigravity สั่งงาน
│   │   ├── crypto_scalp_bridge.py # ตัวคำนวณ Spread-aware & Buffered TP/SL
│   │   └── mt5_client.py     # ตัวส่งคำสั่ง MT5 + Single Position Guard + Account Guard
│   └── web/                  # FastAPI Backend + Fintech Dashboard UI
├── ไฟล์ไว้เรียนรู้/           # เอกสารความรู้และภาพตัวอย่างการเทรดจากหน้างานจริง
│   ├── Demand_Supply/        # ภาพเคสตัวอย่าง Base และ Pine Script S&D
│   └── XAUUSD_LEARNING_SUMMARY.txt # สรุปบทเรียนทองคำฉบับสมบูรณ์
├── run.py                    # ไฟล์เริ่มเปิดระบบ Dashboard
├── prompt_current.txt        # บริบทระบบฉบับปัจจุบันสำหรับ Antigravity AI
├── prompt_BTC.txt            # บริบทและกฎการทำงานสำหรับโหมด Sandbox (BTC & Gold)
├── trading_rules_and_ai_guide.txt # คู่มือกฎการเทรดและขั้นตอนวิเคราะห์ของ AI
├── sandbox_rules_for_fun.txt # กฎการทดลองเทรดในบัญชี Demo Sandbox
└── HOW_ANTIGRAVITY_ANALYZES_AND_EXECUTES.txt # กลไกการวิเคราะห์และการตัดสินใจของ AI
```

---

## คำสั่ง CLI สำหรับ Antigravity AI (Agent Bridge)

สามารถสั่งงานระบบผ่าน CLI ในเทอร์มินัลได้ทันที:

```bash
# 1. สแกนและวิเคราะห์ทองคำ XAU/USD ตามกลยุทธ์ Price Action & Demand/Supply
python -m src.execution.agent_bridge gold-strategy

# 2. สแกนหาจังหวะซิ่ง BTC/USD กรอบ 1 นาที
python -m src.execution.agent_bridge btc-scalp

# 3. สแกนและสร้างแผนหุ้นสหรัฐฯ 7 ตัว
python -m src.execution.agent_bridge scan --symbol AAPL

# 4. ตรวจสอบสถานะบัญชี พอร์ต และออเดอร์ที่เปิดค้างอยู่
python -m src.execution.agent_bridge account

# 5. ซิงค์ประวัติการเทรดที่ปิดแล้วจาก MT5 เข้าสู่ฐานข้อมูลเพื่อถอดบทเรียน
python -m src.analysis.trade_reviewer

# 6. คอมไพล์โมดูลคู่มือจาก memory/playbooks/ เป็น memory/playbook.md
python -m src.analysis.playbook_compiler
```

---

## วิธีติดตั้งและเริ่มใช้งาน

### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 2. รันโปรแกรม Web Dashboard
```bash
python run.py
```
เปิดเบราว์เซอร์ไปที่: **[http://127.0.0.1:8000](http://127.0.0.1:8000)** (ระบบจะเชื่อมต่อดึงยอดเงินและราคาจริงจากพอร์ต Exness MT5 ให้ทันที)

---

## การทดสอบระบบ (Automated Tests)
รันชุดทดสอบด้วย `pytest`:
```bash
pytest
```
ครอบคลุมการทดสอบครบถ้วน (Indicators, Fractal S/R, Headroom Guard, Backtest 70/30, MT5 Client Bridge, Single Position Guard, Gold Strategy Multi-TF D&S, Playbook Compiler, และ Capture Service) **ผ่าน 100% (50/50 passed)**
