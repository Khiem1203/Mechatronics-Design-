# ============================================================
#  GP2Y0A41SK0F calibration  -  V  vs  1/L
# ------------------------------------------------------------
#  The three readings are shown as scattered points only
#  (no connecting lines - the sensor was not measured
#  continuously between distances).
#  A single straight line is drawn: the least-squares fit
#  through the three mean values.
#
#  Run:
#     python calibration_plot.py
# ============================================================

import numpy as np
import matplotlib.pyplot as plt

# ----------------------------------------------------------------
#  Measured data
# ----------------------------------------------------------------
L_cm = np.array([5.0, 8.0, 12.0])          # distance L (cm)
inv_L = 1.0 / L_cm                          # 1/L (1/cm)

readings = {
    "Reading 1": np.array([2.326, 1.621, 1.164]),
    "Reading 2": np.array([2.360, 1.614, 1.174]),
    "Reading 3": np.array([2.368, 1.622, 1.193]),
}
mean_V = np.array([2.3513, 1.6190, 1.1770])

# sort everything by ascending 1/L
order = np.argsort(inv_L)
inv_L, L_cm, mean_V = inv_L[order], L_cm[order], mean_V[order]
readings = {k: v[order] for k, v in readings.items()}

styles = {
    "Reading 1": dict(color="tab:blue",   marker="o"),
    "Reading 2": dict(color="tab:orange", marker="s"),
    "Reading 3": dict(color="tab:green",  marker="^"),
}

# ----------------------------------------------------------------
#  Least-squares fit  V = a*(1/L) + b   (through the 3 mean points)
# ----------------------------------------------------------------
a, b = np.polyfit(inv_L, mean_V, 1)
y_pred = a * inv_L + b
ss_res = np.sum((mean_V - y_pred) ** 2)
ss_tot = np.sum((mean_V - np.mean(mean_V)) ** 2)
r2 = 1.0 - ss_res / ss_tot

xf = np.linspace(inv_L.min() * 0.85, inv_L.max() * 1.08, 100)
yf = a * xf + b

sign = "+" if b >= 0 else "-"
fit_label = f"Fit:  V = {a:.3f}·(1/L) {sign} {abs(b):.3f}   (R² = {r2:.4f})"
print(f"Fit:  V = {a:.4f} * (1/L) {sign} {abs(b):.4f}    R^2 = {r2:.4f}")

# ----------------------------------------------------------------
#  Plot
# ----------------------------------------------------------------
plt.rcParams["figure.figsize"] = (8.5, 5.5)
fig, ax = plt.subplots()

# fitted line first, so the data points sit on top
ax.plot(xf, yf, "k-", linewidth=2.0, zorder=2, label=fit_label)

# scattered reading points (no connecting lines)
for name, v in readings.items():
    ax.plot(inv_L, v, linestyle="none", markersize=7, zorder=3,
            markeredgecolor="white", markeredgewidth=0.6,
            label=name, **styles[name])

ax.set_xlabel("1 / L  (cm$^{-1}$)")
ax.set_ylabel("Output voltage  V  (V)")
ax.set_title("GP2Y0A41SK0F  —  V against 1/L  with fitted line")
ax.grid(True, alpha=0.35)
ax.legend(frameon=True, fontsize=9)

# label each distance near the top axis
for x, L in zip(inv_L, L_cm):
    ax.annotate(f"L = {L:.0f} cm", xy=(x, ax.get_ylim()[1]),
                xytext=(0, -12), textcoords="offset points",
                ha="center", va="top", fontsize=8, color="0.4")

fig.tight_layout()
out = "calibration_V_vs_invL.png"
fig.savefig(out, dpi=150)
print(f"Saved: {out}")
plt.show()
