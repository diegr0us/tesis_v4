---
tags:
  - thesis
category: academic_notes
---
# Preliminaries

We consider two types of uncertain: wind generation and electricity demand,
$$
\tilde P_{w,h,d},\qquad \tilde D_{h,d},
\qquad
w=1,\ldots,\mathcal W,\quad
h=1,\ldots,24,\quad
d=2,\ldots,T,
$$
where $\mathcal W$ is the number of wind parks, $h$ denotes the hour, and $d$ denotes the day (decision epoch). Epoch $1$ is excluded from the uncertainty set because it corresponds to the first-stage decision.

Within each day, the uncertainty representation preserves dependencies across hours and, for wind generation, across units. Wind and demand are modeled using separate uncertainty sets because their historical records are not aligned by date and hour. Their independence is therefore only a modeling assumption.

We also assume that uncertainty sets are uncoupled across days. Thus, the multiday sets are defined as Cartesian products of daily sets:
$$
\Xi_{\tilde P}=\prod_{d=2}^{T}\xi_{\tilde P_d},
\qquad
\Xi_{\tilde D}=\prod_{d=2}^{T}\xi_{\tilde D_d}.
$$
The complete uncertainty set is:
$$
\Xi=\Xi_{\tilde P}\times\Xi_{\tilde D}.
$$

For a single day, the numbers of hourly coordinates are:
$$
n_{\tilde P}=24\mathcal W,
\qquad
n_{\tilde D}=24.
$$
The combined daily profile therefore has ambient dimension:
$$
n=n_{\tilde P}+n_{\tilde D}=24(\mathcal W+1).
$$
The objective is to reduce the number of coordinates needed to describe intraday variability using PCA, retaining
$$
r_{\tilde P}\ll n_{\tilde P},
\qquad
r_{\tilde D}\ll n_{\tilde D}.
$$
Uncertainty is represented through hourly forecast errors rather than deviations from each day's realized mean. PCA jointly captures errors in the daily level and in the intraday shape. The foundation-model median and its predictive deviations define an outer support envelope. No separate additive daily mean uncertainty coordinate is introduced.

---
# Foundation model forecasts and historical errors

The foundation model provides an hourly predictive near the median of planning horizon. For group $q$, let $i$ index a physical coordinate: $i=(w,h)$ for wind and $i=h$ for demand. Define:
$$
\widehat u^q_{i,d}=\widehat Q^q_{0.5,i,d},
$$
For each historical target day $k$, define actual-minus-forecast errors:
$$
e^{\tilde P}_{w,h,k}=P^{\mathrm{obs}}_{w,h,k}-\widehat P_{w,h,k},
\qquad
e^{\tilde D}_{h,k}=D^{\mathrm{obs}}_{h,k}-\widehat D_{h,k}.
$$
Historical forecasts must be generated using only information available at their forecast origin, with the same forecasting pipeline and lead times used in operation.

# Daily forecast-error vectors

Wind and demand are treated separately because their historical records are not aligned. Within the wind group, records for all parks must be aligned by target date, hour, and forecast origin.

For wind, stack all parks and hours:
$$
\boldsymbol e^{\tilde P}_k
=\left[
e^{\tilde P}_{1,1,k},\ldots,e^{\tilde P}_{1,24,k},
\ldots,
e^{\tilde P}_{\mathcal W,1,k},\ldots,e^{\tilde P}_{\mathcal W,24,k}
\right]^\top
\in\mathbb R^{24\mathcal W}.
$$
For demand:
$$
\boldsymbol e^{\tilde D}_k
=\left[e^{\tilde D}_{1,k},\ldots,e^{\tilde D}_{24,k}\right]^\top
\in\mathbb R^{24}.
$$
Each observation is a complete daily error trajectory.

# PCA of forecast errors

## Centering and scaling

For each group $q\in\{\tilde P,\tilde D\}$, let $\mathcal T_q$ denote its PCA training days and $N_q^{\mathrm{train}}=|\mathcal T_q|$. Define the historical bias vector:
$$
\boldsymbol b^q
=\frac{1}{N_q^{\mathrm{train}}}
\sum_{k\in\mathcal T_q}\boldsymbol e^q_k,
\qquad
\boldsymbol x^q_k=\boldsymbol e^q_k-\boldsymbol b^q.
$$
This centers each coordinate across training days, not each trajectory across hours. Neither $\boldsymbol b^q$ nor an individual centered daily trajectory is required to have zero hourly sum.

The baseline specification uses errors in MW without coordinate-wise standardization. It therefore prioritizes squared reconstruction error in physical units. Capacity normalization may be evaluated for parks with substantially different capacities, but it changes the PCA objective and must be inverted when reconstructing physical profiles. All formulas below use the unscaled MW specification.

## Basis and scores

Construct $X^q\in\mathbb R^{N_q^{\mathrm{train}}\times n_q}$ with rows $(\boldsymbol x^q_k)^\top$ and compute:
$$
X^q=U^q\Sigma^q(V^q)^\top.
$$
Retain the first $r_q$ right singular vectors:
$$
L^q=V^q_{[:,1:r_q]}\in\mathbb R^{n_q\times r_q},
\qquad (L^q)^\top L^q=I_{r_q}.
$$
For any training, calibration, or test day, obtain scores using the fixed training bias and basis:
$$
\boldsymbol z^q_k=(L^q)^\top(\boldsymbol e^q_k-\boldsymbol b^q).
$$
The exact decomposition is:
$$
\boxed{
\boldsymbol e^q_k=\boldsymbol b^q+L^q\boldsymbol z^q_k+\boldsymbol\eta^q_k,
\qquad
\boldsymbol\eta^q_k=
\left(I-L^q(L^q)^\top\right)(\boldsymbol e^q_k-\boldsymbol b^q).
}
$$
The reduced error model uses the affine subspace:
$$
\mathcal A_q=\boldsymbol b^q+\operatorname{range}(L^q).
$$
Unlike the previous zero-sum shape subspace, this affine subspace can represent both daily level and intraday shape errors. Its loading vectors are not constrained to sum to zero.

## Rank selection and truncation error

Select $r_q$ using temporal validation, considering explained variance together with hourly reconstruction errors, daily mean errors, ramp errors, and extreme forecast errors. 

The reduced formulation below omits $\boldsymbol\eta^q_k$; it does not assert that historical truncation errors are actually zero. Removing the zero-sum condition on hourly forecast errors and omitting the PCA truncation error are different modeling choices.
# Normalized coordinates and budgets

Define day-dependent centers and half-widths:
$$
c^q_{d,j}=\frac{\underline z^q_{d,j}+\overline z^q_{d,j}}{2},
\qquad
a^q_{d,j}=\frac{\overline z^q_{d,j}-\underline z^q_{d,j}}{2},
\qquad
A^q_d=\operatorname{diag}(\boldsymbol a^q_d).
$$
For positive half-widths:
$$
\boxed{
z^q_{d,j}=c^q_{d,j}+a^q_{d,j}\theta^q_{d,j}.
}
$$
Let $\mathcal J_{q,d}=\{j:a^q_{d,j}>0\}$. A component with zero half-width is fixed at $z_j=c^q_{d,j}$; set $\theta_j=0$ as a bookkeeping convention and omit it from budgets. In numerical implementations use an appropriate tolerance.

Let $s_q\leq r_q$ identify the leading components considered for the optional pairwise budget and define:
$$
\mathcal P_{q,d}=\{(i,j):i,j\in\mathcal J_{q,d},\ 1\leq i<j\leq s_q\}.
$$
The complete normalized score set is:
$$
\boxed{
\mathcal U_{q,d}
=\left\{\boldsymbol\theta\in\mathbb R^{r_q}:
\begin{array}{l}
\boldsymbol c^q_d+A^q_d\boldsymbol\theta\in\mathcal Z^{\mathrm{FM}}_{q,d},\\[1mm]
|\theta_j|\leq1\quad(j\in\mathcal J_{q,d}),\qquad
\theta_j=0\quad(j\notin\mathcal J_{q,d}),\\[1mm]
\displaystyle\sum_{j\in\mathcal J_{q,d}}|\theta_j|\leq\Phi_q,\\[1mm]
|\theta_i|+|\theta_j|\leq\Psi_q\quad((i,j)\in\mathcal P_{q,d})
\end{array}
\right\}.
}
$$
# Reconstruction and final uncertainty set

The reduced reconstruction map is:
$$
\boxed{
F^q_d(\boldsymbol\theta)
=\widehat{\boldsymbol u}^q_d+\boldsymbol b^q
+L^q(\boldsymbol c^q_d+A^q_d\boldsymbol\theta).
}
$$
For wind unit $w=1,\ldots,\mathcal W$:
$$
\tilde P_{w,h,d}
=\widehat P_{w,h,d}+b^{\tilde P}_{w,h}
+\sum_{j=1}^{r_{\tilde P}}L^{\tilde P}_{(w,h),j}
\left(c^{\tilde P}_{d,j}+a^{\tilde P}_{d,j}\theta^{\tilde P}_{d,j}\right).
$$
For demand:
$$
\tilde D_{h,d}
=\widehat D_{h,d}+b^{\tilde D}_h
+\sum_{j=1}^{r_{\tilde D}}L^{\tilde D}_{h,j}
\left(c^{\tilde D}_{d,j}+a^{\tilde D}_{d,j}\theta^{\tilde D}_{d,j}\right).
$$
The same scores can modify both daily level and hourly shape; there is no separate additive daily mean coordinate. The bias is included inside the support inequalities and does not shift the foundation-model envelope away from its predictive median.

## Daily and multiday sets

The daily sets are:
$$
\boxed{
\xi_{q_d}
=\left\{F^q_d(\boldsymbol\theta):
\boldsymbol\theta\in\mathcal U_{q,d},\quad
F^q_d(\boldsymbol\theta)\in\mathcal H_{q,d}\right\}.
}
$$
Membership in the foundation-model envelope is already enforced by $\mathcal U_{q,d}$ through the exact substituted support. The complete multiday set is:
$$
\boxed{
\Xi=\Xi_{\tilde P}\times\Xi_{\tilde D},
\qquad
\Xi_q=\prod_{d=2}^{T}\xi_{q_d}.
}
$$
The basis $L^q$ and bias $\boldsymbol b^q$ are fixed across days for each group. Forecast medians, support widths, score extrema, and normalization parameters vary by day. The normalized budget parameters $\Phi_q$ and $\Psi_q$ are shared within each group in this baseline specification. Coordinates are chosen separately for each day: sharing a basis does not couple daily uncertainty realizations.

# Budget calibration

For every calibration target day $k\in\mathcal C_q$, reproduce its historical foundation-model median and predictive bounds using only information available at its forecast origin. Construct $\mathcal Z^{\mathrm{FM}}_{q,k}$ and solve the score-bound linear programs using the fixed training basis and bias. Historical score quantiles are not used as support limits.

Project the observed historical errors to obtain $\boldsymbol z^q_k=(L^q)^\top(\boldsymbol e^q_k-\boldsymbol b^q)$, then normalize using that day's support-derived parameters:
$$
\theta^q_{k,j}=\frac{z^q_{k,j}-c^q_{k,j}}{a^q_{k,j}},
\qquad j\in\mathcal J_{q,k}.
$$
Do not clip these values or discard days that violate the support. A zero-width component is a fixed equality; any mismatch of its observed score is a support violation, not a value to normalize. Empty historical support sets are feasibility failures that must be reported and resolved before this calibration can be completed.

Compute:
$$
B^q_k=\sum_{j\in\mathcal J_{q,k}}|\theta^q_{k,j}|,
\qquad
C^q_k=\max_{(i,j)\in\mathcal P_{q,k}}
\left(|\theta^q_{k,i}|+|\theta^q_{k,j}|\right),
$$
with $C^q_k=0$ when there are no applicable pairs. Set:
$$
\boxed{
\Phi_q=Q_{1-\epsilon_\Phi}\!\left(\{B^q_k\}_{k\in\mathcal C_q}\right),
\qquad
\Psi_q=Q_{1-\epsilon_\Psi}\!\left(\{C^q_k\}_{k\in\mathcal C_q}\right).
}
$$
Empirical quantiles are used only to calibrate budget statistics, not to define individual score limits. These are separate empirical statements about budget exceedances; they do not guarantee joint coverage of the final support-constrained set. Projected scores can violate the coupled support inequalities even if all their individual bounds hold. Increasing a budget cannot recover trajectories excluded by the foundation-model support or the retained subspace.