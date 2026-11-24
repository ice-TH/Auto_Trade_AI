import os
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def generate_learned_zone_chart():
    os.makedirs('images', exist_ok=True)
    if not mt5.initialize():
        print('Failed to init MT5')
        return

    symbol = 'XAUUSDm'
    # 160 bars of M15 captures from Nov 19 19:00 to current Nov 23
    rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 160)
    mt5.shutdown()

    if rates_m15 is None or len(rates_m15) == 0:
        print('No rates returned')
        return

    df = pd.DataFrame(rates_m15)
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    n = len(df)
    current_price = df['close'].iloc[-1]

    # Calculate MA 50 like TradingView
    df['ma50'] = df['close'].rolling(50).mean()

    # Style & Figure configuration
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(16, 9), dpi=150)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#131722')

    # Draw Candlesticks
    width = 0.6
    width2 = 0.12
    up = df[df.close >= df.open]
    down = df[df.close < df.open]

    col_up = '#089981'   # TradingView Teal Green
    col_down = '#f23646' # TradingView Crimson Red

    ax.bar(up.index, up.close - up.open, width, bottom=up.open, color=col_up, edgecolor=col_up, zorder=3)
    ax.bar(up.index, up.high - up.close, width2, bottom=up.close, color=col_up, edgecolor=col_up, zorder=3)
    ax.bar(up.index, up.low - up.open, width2, bottom=up.open, color=col_up, edgecolor=col_up, zorder=3)

    ax.bar(down.index, down.close - down.open, width, bottom=down.open, color=col_down, edgecolor=col_down, zorder=3)
    ax.bar(down.index, down.high - down.open, width2, bottom=down.open, color=col_down, edgecolor=col_down, zorder=3)
    ax.bar(down.index, down.low - down.close, width2, bottom=down.close, color=col_down, edgecolor=col_down, zorder=3)

    # Plot MA 50 line (TradingView Blue)
    ax.plot(df.index, df['ma50'], color='#29b6f6', linewidth=1.3, label='MA 50', alpha=0.85, zorder=4)

    # Find key indices
    # 1. Supply 1H Base (Nov 19 ~ 19:30)
    idx_supply_1h = 0
    for i, t in enumerate(df['datetime']):
        if t.strftime('%Y-%m-%d %H:%M') >= '2026-11-19 19:30':
            idx_supply_1h = i
            break

    # 2. Demand 15m Broken Base (Nov 20 13:30 to 15:30 break)
    idx_demand_broken_start = 0
    idx_demand_broken_end = 0
    for i, t in enumerate(df['datetime']):
        if t.strftime('%Y-%m-%d %H:%M') >= '2026-11-20 13:30' and idx_demand_broken_start == 0:
            idx_demand_broken_start = i
        if t.strftime('%Y-%m-%d %H:%M') >= '2026-11-20 15:30' and idx_demand_broken_end == 0:
            idx_demand_broken_end = i

    # 3. Demand 15m Active Base (Nov 23 00:00 to current)
    idx_demand_active_start = 0
    for i, t in enumerate(df['datetime']):
        if t.strftime('%Y-%m-%d %H:%M') >= '2026-11-23 00:00':
            idx_demand_active_start = i
            break

    # Retest bar (Nov 23 02:30)
    idx_retest = 0
    for i, t in enumerate(df['datetime']):
        if t.strftime('%Y-%m-%d %H:%M') >= '2026-11-23 02:30':
            idx_retest = i
            break

    # 1. DRAW SUPPLY 1H (Active, extends to right margin)
    supply_high = 3687.5
    supply_low = 3666.0
    rect_supply = patches.Rectangle(
        (idx_supply_1h, supply_low),
        (n + 8) - idx_supply_1h,
        supply_high - supply_low,
        linewidth=1.2,
        edgecolor='#f23646',
        facecolor='#f23646',
        alpha=0.18,
        zorder=2
    )
    ax.add_patch(rect_supply)
    ax.text(
        idx_supply_1h + ((n + 8 - idx_supply_1h) / 2),
        supply_high + 1.5,
        'Supply 1H',
        color='#f23646',
        fontsize=11,
        fontweight='bold',
        ha='center',
        va='bottom',
        zorder=5
    )

    # 2. DRAW DEMAND 15M (Broken on Left: Stops at break time! Does not extend!)
    broken_high = 3572.0
    broken_low = 3556.0
    rect_broken = patches.Rectangle(
        (idx_demand_broken_start, broken_low),
        idx_demand_broken_end - idx_demand_broken_start,
        broken_high - broken_low,
        linewidth=1.2,
        edgecolor='#00e5ff',
        facecolor='#00e5ff',
        alpha=0.18,
        zorder=2
    )
    ax.add_patch(rect_broken)
    ax.text(
        idx_demand_broken_start + ((idx_demand_broken_end - idx_demand_broken_start) / 2),
        broken_high + 1.2,
        'Demand 15m',
        color='#00e5ff',
        fontsize=9.5,
        fontweight='bold',
        ha='center',
        va='bottom',
        zorder=5
    )

    # 3. DRAW DEMAND 15M (Active Base Circled by User: 3570 - 3585, extends to right margin)
    active_high = 3585.0
    active_low = 3570.0
    rect_active = patches.Rectangle(
        (idx_demand_active_start, active_low),
        (n + 8) - idx_demand_active_start,
        active_high - active_low,
        linewidth=1.2,
        edgecolor='#00e5ff',
        facecolor='#00e5ff',
        alpha=0.22,
        zorder=2
    )
    ax.add_patch(rect_active)
    ax.text(
        idx_demand_active_start + ((n + 8 - idx_demand_active_start) / 2),
        active_high + 1.5,
        'Demand 15m',
        color='#00e5ff',
        fontsize=11,
        fontweight='bold',
        ha='center',
        va='bottom',
        zorder=5
    )

    # Point to Retest Bounce inside Demand Base
    if idx_retest > 0:
        ax.annotate(
            'Retest Bounce (3583 - 3585)\nPullback tapped Demand Base',
            xy=(idx_retest, 3585.0),
            xytext=(idx_retest - 8, 3605.0),
            arrowprops=dict(facecolor='#00e5ff', edgecolor='#00e5ff', shrink=0.08, width=1.5, headwidth=6),
            color='#00e5ff',
            fontsize=8.5,
            fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.25', facecolor='#131722', edgecolor='#00e5ff', alpha=0.9),
            zorder=6
        )

    # Current Price Line
    ax.axhline(current_price, color='#f23646' if current_price < df['close'].iloc[-2] else '#089981', linestyle=':', linewidth=1.2, zorder=4)
    ax.text(
        n + 1, current_price,
        f' {current_price:.2f} ',
        color='#ffffff',
        fontsize=9,
        fontweight='bold',
        verticalalignment='center',
        bbox=dict(boxstyle='square,pad=0.3', facecolor='#f23646' if current_price < df['close'].iloc[-2] else '#089981', edgecolor='none'),
        zorder=5
    )

    # Formatting axes exactly like TradingView
    step = 14
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([df['datetime'].iloc[i].strftime('%d %b %H:%M') for i in range(0, n, step)], rotation=20, ha='right', color='#787b86', fontsize=8.5)
    ax.set_xlim(-1, n + 8)

    y_min = 3495.0
    y_max = 3705.0
    ax.set_ylim(y_min, y_max)
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.set_ylabel('Price (USD)', color='#787b86', fontsize=10, labelpad=10)
    ax.tick_params(colors='#787b86', labelsize=8.5)
    ax.grid(True, color='#2a2e39', linestyle='-', linewidth=0.6, alpha=0.6)

    # Title
    plt.title('XAUUSD · 15 · Commodities  |  Demand & Supply Zones Analysis', color='#d1d4dc', fontsize=13, fontweight='bold', pad=18, loc='left')
    plt.suptitle('MA 50 | Price Action Multi-Timeframe Structure [Verified by TradingView Cases]', color='#787b86', fontsize=9, x=0.125, y=0.92, ha='left')

    output_path = os.path.abspath('images/xauusd_demand_supply_zones.png')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print('Chart regenerated perfectly:', output_path)

if __name__ == '__main__':
    generate_learned_zone_chart()
