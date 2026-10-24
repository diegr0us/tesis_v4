---
category: academic_notes
tags:
  - thesis
---
See [[Robust Dual Dynamic Programing (RDDP)]], [[Uncertainty Set RDDP thesis (PCA + FM)]], [[Notation RDDP thesis]], [[Deterministic Formulation thesis]]

**Assumptions**

The uncertainty vector is $\xi=(\tilde{\tau}_{j,w},\tilde{P}_{w,h,d}^r,\tilde{D}_{h,d})$. The operational stages use only $\mathbf{\xi}=(\tilde{P}_{w,h,d}^r,\tilde{D}_{h,d})$. Here $\tilde{P}_{w,h,d}^r$ is the total wind-farm power before maintenance availability is applied; its admissible realizations already satisfy the physical wind-power limits. Consequently, dispatch has only the uncertainty-dependent wind upper bound, with no separate rated-power row or associated dual multiplier.

$x_1=(v^r,m^r,a^r,c)$ are first-stage decisions, whereas dispatch $x_d=\{y^r_d,y^{nr}_d,\pi^+_d,\pi^-_d,SOC_d\}$

### Aggregated operational state

Maintenance decisions remain turbine-indexed in the first stage. Define the derived availability of each wind farm by
$$
A_{w,d}=|\mathcal G_w^r|-|\mathcal J_w^r|
+\sum_{j\in\mathcal J_w^r}a_{j,w,d}^r,
\qquad w\in\mathcal W,\ d\in\mathcal T.
$$
Thus $A_{w,d}$ is a **number of available turbines**, not a fraction; $A_{w,d}/|\mathcal G_w^r|$ is the available fraction. $A$ is determined by the maintenance plan, not a new independent operational decision.

Use the carried state $\mathbf{x}_t=(A,SOC_d)$, where $d=t-1$ and $SOC_d$ is the end-of-day battery SOC vector. The incoming root state is $\mathbf{x}_1=(A,SOC^{\mathrm{init}})$. The complete matrix $A\in\mathbb R^{|\mathcal W|\times T}$ is carried unchanged through the operational stages; only its column $d$ affects current dispatch, but the remaining-day columns affect continuation. Past columns may be omitted in a consistently reduced implementation, but availability for the current day alone is not a sufficient state.

This aggregation is valid for the present formulation because all turbines within a farm contribute identically to its available-power factor, operational uncertainty is farm-indexed, and no other operational constraint or future cost depends on turbine identity. Plans with the same $A$ therefore have the same operational recourse value at a given SOC, although their first-stage maintenance costs may differ. Turbine-specific operational limits or uncertainty would require revisiting this reduction.

In scalar products, $A$ denotes its vectorization: $\kappa_A^{\mathsf T}A=\sum_{d\in\mathcal T}\sum_{w\in\mathcal W}\kappa_{A,w,d}A_{w,d}$. Thus availability slopes and envelope multipliers have one component per farm and day, not per turbine. The dispatch coefficient matrix $A_t$ used later in the compact dual formulation is a different object from the availability profile $A$.

Bold notation distinguishes the carried state $\mathbf{x}$ and effective operational uncertainty $\mathbf{\xi}$ from the full decision vector $x$. The cost products $q_1^{\mathsf T}x_1$ and $q_t^{\mathsf T}x_t$ use the full decision vectors, not only the state. In the implementation, `availability[w, d]` stores $A_{w,d}$; Python `stage = 0,...,T-1` corresponds to physical day $d=1,...,T$ and decision stage $t=d+1$. Flattened cut vectors use SOC first, followed by $A$ ordered by day and then farm; the mathematical tuple $(A,SOC)$ denotes the same state with a different display order.

Using robust version of dynamic robust function we can modelate the problem as multistage problem using the nested formulation:

$$
\begin{aligned}
\text{minimize}\quad & q_1^{\mathsf T}x_1 + Q_2(\mathbf{x}_1)\\
\text{subject to}\quad & W_1x_1 \ge h_1(\mathbf{\xi}),\\
& x_1 \in \mathbb{R}^{n_1}.
\end{aligned}
$$

where
$$
W_1x_1 \ge h_1(\mathbf{\xi}) \: = \: \left\{ 
\begin{aligned}
& \sum_{t=1}^{T-Y+1}v_{j,w,t}^r=1,
\qquad \forall w\in\mathcal{W},\ j\in\mathcal{J}_w^r \\
& v_{j,w,t}^r=0,
\qquad \forall t\in\mathcal{T}:t>T-Y+1,\ w\in\mathcal{W},\ j\in\mathcal{J}_w^r \\
& m_{j,w,t}^r=\sum_{k=0}^{\min\{t-1,Y-1\}}v_{j,w,t-k}^r,
\qquad \forall t\in\mathcal{T},\ w\in\mathcal{W},\ j\in\mathcal{J}_w^r\\
& a_{j,w,t}^r=
\begin{cases}
1-m_{j,w,t}^r, & t<\underline{\tau}_{j,w},\\[2pt]
\displaystyle\sum_{k=1}^{t}v_{j,w,k}^r-m_{j,w,t}^r, & t\geq \underline{\tau}_{j,w},
\end{cases}
\quad \forall t\in\mathcal{T},\ w\in\mathcal{W},\ j\in\mathcal{J}_w^r \\
& \sum_{j\in\mathcal{J}_w^r}m_{j,w,t}^r
\leq\overline{N^{\mathrm{cw}}}\,c_{w,t},
\qquad \forall t\in\mathcal{T},\ w\in\mathcal{W}.\\
& \sum_{w\in\mathcal{W}}c_{w,t}
\leq\overline{M^{\mathrm{cw}}},
\qquad \forall t\in\mathcal{T}.
\end{aligned}
\right. 
$$
The vector $q_1$ contains the first-stage cost coefficients, ordered consistently with $x_1=(v^r,m^r,a^r,c)$. Its scalar product with $x_1$ is the total maintenance and crew assignment cost:

$$

q_1^{\mathsf T}x_1
={}\overbrace{
\sum_{t\in\mathcal{T}}\sum_{w\in\mathcal{W}}\sum_{j\in\mathcal{J}_w^r}
\alpha_{j,w,t}\,v_{j,w,t}^r
}^{\text{Maintenance cost}}
+\overbrace{
\sum_{t\in\mathcal{T}}\sum_{w\in\mathcal{W}}
C_w^{\mathrm{cw}}\,c_{w,t}
}^{\text{Crew assignment cost}}.
$$

Here, $\alpha_{j,w,t}$ is the precomputed robust maintenance cost coefficient. The variables $m^r$ and $a^r$ have no direct objective cost.

$$
Q_t(\mathbf{x}_{t-1};\mathbf{\xi}_t)
=
\left\{
\begin{aligned}
\text{minimize}\quad & q_t^{\mathsf T}x_t + \mathcal{Q}_{t+1}(\mathbf{x}_t)\\
\text{subject to}\quad & T_t(\mathbf{\xi}_t)\mathbf{x}_{t-1} + W_tx_t \ge h_t(\mathbf{\xi}_t),\\
& x_t \in \mathbb{R}^{n_t}
\end{aligned}
\right.,
\qquad t=2,\ldots,T+1.
$$

To distinguish operational days from decision stages, stage $1$ contains the maintenance plan, while stage $t=2,\ldots,T+1$ corresponds to operational day $d=t-1$. Each operational stage contains all hours $h\in\mathcal{H}$ of that day.

The current-stage cost is

$$
q_t^{\mathsf T}x_t
=\overbrace{
\sum_{h\in\mathcal{H}}\sum_{i\in\mathcal{G}^{nr}}
CV_i\,y_{i,h,d}^{nr}
}^{\text{Conventional generation cost on day }d},
\qquad d=t-1.
$$

Thus, the recourse function can be written explicitly as

$$
Q_t(\mathbf{x}_{t-1};\mathbf{\xi}_t)
=\min_{x_t\in\mathcal{F}_t(\mathbf{x}_{t-1},\mathbf{\xi}_t)}\quad
\Biggl[\overbrace{
\sum_{h\in\mathcal{H}}\sum_{i\in\mathcal{G}^{nr}}
CV_i\,y_{i,h,d}^{nr}
}^{\text{Current-day dispatch cost}}
+\overbrace{
\mathcal{Q}_{t+1}(\mathbf{x}_t)
}^{\text{Worst-case future operational cost}}
\Biggr],
\qquad d=t-1.
$$

Here, $\mathcal{F}_t(\mathbf{x}_{t-1},\mathbf{\xi}_t)$ is the feasible set for hourly dispatch on day $d$. It includes wind generation limits conditional on the fixed maintenance availability and the observed wind profile, conventional generation bounds, demand coverage, battery SOC dynamics and bounds, and charging/discharging power limits. The previous day's terminal SOC is the incoming battery state; on day $1$, it is replaced by $SOC_b^{\mathrm{init}}$. The terminal SOC requirement is imposed only on day $T$. Maintenance availability is carried from the first-stage plan.

Explicitly, let $d=t-1$ and write the incoming state as $\mathbf{x}_{t-1}=(A,S^{\mathrm{in}})$, where $S_b^{\mathrm{in}}$ is battery $b$'s SOC before the first hour of day $d$. At stage $t=2$, $S_b^{\mathrm{in}}=SOC_b^{\mathrm{init}}$; at subsequent stages, it is the previous day's terminal SOC.

The effective uncertainty $\mathbf{\xi}_t$ supplies the hourly wind and demand realizations $(\tilde{P}_{w,h,d}^r,\tilde{D}_{h,d})$ for that day. The operational feasible set is

$$
\mathcal{F}_t(\mathbf{x}_{t-1},\mathbf{\xi}_t)
=\left\{x_t:\;
\begin{aligned}
&0\leq y_{w,h,d}^r
\leq\tilde{P}_{w,h,d}^r\,
\frac{A_{w,d}}{|\mathcal{G}_w^r|},
&&\forall w\in\mathcal{W},\ h\in\mathcal{H},\\[4pt]
&0\leq y_{i,h,d}^{nr}\leq\overline{P_i^{nr}},
&&\forall i\in\mathcal{G}^{nr},\ h\in\mathcal{H},\\[4pt]
&\sum_{i\in\mathcal{G}^{nr}}y_{i,h,d}^{nr}
+\sum_{w\in\mathcal{W}}y_{w,h,d}^r
+\sum_{b\in\mathcal{B}}(\pi_{b,h,d}^--\pi_{b,h,d}^+)
\geq\tilde{D}_{h,d},
&&\forall h\in\mathcal{H},\\[4pt]
&SOC_{b,1,d}=S_b^{\mathrm{in}}
+\eta_b\pi_{b,1,d}^+
-\frac{\pi_{b,1,d}^-}{\eta_b},
&&\forall b\in\mathcal{B},\\[4pt]
&SOC_{b,h,d}=SOC_{b,h-1,d}
+\eta_b\pi_{b,h,d}^+
-\frac{\pi_{b,h,d}^-}{\eta_b},
&&\forall b\in\mathcal{B},\ h\in\mathcal{H}\setminus\{1\},\\[4pt]
&\underline{E_b^{soc}}\leq SOC_{b,h,d}\leq\overline{E_b^{soc}},
&&\forall b\in\mathcal{B},\ h\in\mathcal{H},\\[4pt]
&0\leq\pi_{b,h,d}^+\leq\overline{P_b^{ch}},
&&\forall b\in\mathcal{B},\ h\in\mathcal{H},\\[4pt]
&0\leq\pi_{b,h,d}^-\leq\overline{P_b^{dch}},
&&\forall b\in\mathcal{B},\ h\in\mathcal{H},\\[4pt]
&SOC_{b,h,d}\geq0,
&&\forall b\in\mathcal{B},\ h\in\mathcal{H},\\[4pt]
&SOC_{b,|\mathcal{H}|,d}\geq SOC_b^{\mathrm{final}},
&&\forall b\in\mathcal{B},\ \text{only if }d=T.
\end{aligned}
\right\},
\qquad t=2,\ldots,T+1.
$$

The outgoing state used in the continuation value is obtained from the dispatch solution as

$$
\mathbf{x}_t=
\left(A,\left(SOC_{b,|\mathcal{H}|,d}\right)_{b\in\mathcal{B}}\right).
$$


The continuation value $\mathcal{Q}_{t+1}$ accounts for future admissible operational uncertainty, whereas $Q_t$ conditions on the current realization $\mathbf{\xi}_t$. Its exact uncertainty-set definition must follow [[Uncertainty Set RDDP thesis (PCA + FM)]]. After the last operational day, no further cost remains:
$$
\mathcal{Q}_{T+2}(\mathbf{x}_{T+1})=0.
$$
### 4.b Backward pass: Affine cut for $\underline{\mathcal{Q}}_t(s)$
$$
\ell_t^k =
\min_{x_t \in \mathcal{F}_t(
    \underline{\mathbf{x}}_{t-1}^k,
    \mathbf{\xi}_t^{\mathrm{bw},k})}
\left\{
    \sum_{h\in\mathcal{H}}
    \sum_{i\in\mathcal{G}^{nr}}
    CV_i y_{i,h,d}^{nr}
    + \underline{\mathcal{Q}}_{t+1}(\mathbf{x}_t)
\right\},
\qquad d=t-1.
$$
$$
\boxed{
\begin{aligned}
c_t^k(A,S^{\mathrm{in}})
={}& \ell_t^k \\
&+ \sum_{\tau\in\mathcal{T}}
   \sum_{w\in\mathcal{W}}
   g_{A,w,\tau}^{t,k}
   \left(
       A_{w,\tau}
       - \underline{A}_{w,\tau}^{k}
   \right) \\
&+ \sum_{b\in\mathcal{B}}
   g_{S,b}^{t,k}
   \left(
       S_b^{\mathrm{in}}
       - \underline{S}_b^{\mathrm{in},k}
   \right).
\end{aligned}
}
$$
Note the fixed values per iteration:
$$
c_t^k(A,S^{\mathrm{in}})
=
\underbrace{\ell_t^k}_{\text{fijo}}
+
\underbrace{(g_A^{t,k})^\top}_{\text{fijo}}
\left(
A-\underbrace{\underline{A}^k}_{\text{fijo}}
\right)
+
\underbrace{(g_S^{t,k})^\top}_{\text{fijo}}
\left(
S^{\mathrm{in}}
-\underbrace{\underline{S}^{\mathrm{in},k}}_{\text{fijo}}
\right).

$$


$$
\boxed{
\begin{aligned}
g_{A,w,\tau}^{t,k}
={}&
-\mathbf{1}_{\{\tau=d\}}
\sum_{h\in\mathcal{H}}
\left[
    \frac{\tilde{P}_{w,h,d}^{r,\mathrm{bw},k}}
         {|\mathcal{G}_w^r|}
    \nu_{w,h}^{t,k}
\right] \\
&+
\sum_{p\in\mathcal{C}_{t+1}}
\lambda_p^{t,k}\,
\beta_{A,t+1,w,\tau}^{p},
\qquad d=t-1.
\end{aligned}
}

\boxed{
g_{S,b}^{t,k}=\rho_b^{t,k},
\qquad b\in\mathcal{B}.
}
$$



#### Meaning of the cut coefficients

The coefficients are computed at the visited state in backward iteration $k$, with the current realization fixed at $\mathbf{\xi}_t^{\mathrm{bw},k}$. They remain fixed once the cut is stored.

| Symbol                               | Meaning                                                                                                                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| $t$, $d=t-1$                         | Decision stage and corresponding operational day.                                                                                                                         |
| $k$                                  | RDDP iteration in which the cut is generated.                                                                                                                             |
| $w,\tau$                           | Wind farm and day of the aggregated availability component $A_{w,\tau}$. The index $\tau$ can differ from the current day $d$.                               |
| $g_{A,w,\tau}^{t,k}$               | Slope of the new stage-$t$ lower cut with respect to $A_{w,\tau}$.                                                                                                    |
| $\mathbf{1}_{\{\tau=d\}}$            | Indicator equal to one if $\tau=d$, and zero otherwise. Only current-day availability enters the current-day wind limits directly.                                        |
| $h\in\mathcal H$                     | Hour within the current operational day.                                                                                                                                  |
| $\tilde P_{w,h,d}^{r,\mathrm{bw},k}$ | Realized wind-power parameter selected for the current day in the backward pass of iteration $k$.                                                                         |
| $\lvert\mathcal G_w^r\rvert$         | Total number of wind units at farm $w$. Thus, $\tilde P_{w,h,d}^{r,\mathrm{bw},k}/\lvert\mathcal G_w^r\rvert$ is the availability coefficient in the realized-wind limit. |
| $\nu_{w,h}^{t,k}\ge0$                | Optimal Lagrangian multiplier of the realized-wind upper limit, also written as generation minus capacity $\le0$.                                                         |
| $\mathcal C_{t+1}$                   | Set of lower cuts used to represent the continuation function $\underline{\mathcal Q}_{t+1}$ in this subproblem.                                                          |
| $p$                                  | Index of a stored continuation cut; it is not necessarily an iteration index.                                                                                             |
| $\lambda_p^{t,k}\ge0$                | Optimal Lagrangian multiplier of continuation cut $p$, with the sign convention below.                                                                                    |
| $\beta_{A,t+1,w,\tau}^{p}$         | Stored slope of continuation cut $p$ with respect to availability component $A_{w,\tau}$.                                                                             |
| $g_{S,b}^{t,k}$                      | Slope of the new cut with respect to battery $b$'s incoming SOC.                                                                                                          |
| $\rho_b^{t,k}\in\mathbb R$           | Optimal Lagrangian multiplier of the first-hour SOC equality, with the orientation specified below.                                                                       |

The two contributions to the availability coefficient are
$$
g_{A,w,\tau}^{t,k}
=
\underbrace{
-\mathbf{1}_{\{\tau=d\}}
\sum_{h\in\mathcal H}
\left[
\frac{\tilde P_{w,h,d}^{r,\mathrm{bw},k}}{|\mathcal G_w^r|}
\nu_{w,h}^{t,k}
\right]
}_{\text{current-day wind-capacity effect}}
+
\underbrace{
\sum_{p\in\mathcal C_{t+1}}
\lambda_p^{t,k}\beta_{A,t+1,w,\tau}^{p}
}_{\text{effect transmitted by continuation cuts}}.
$$
 
**Multiplier sign conventions.** There is one wind upper-limit multiplier per farm and hour:
$$
y_{w,h,d}^r
-\frac{\tilde P_{w,h,d}^{r,\mathrm{bw},k}}{|\mathcal G_w^r|}A_{w,d}\le0,
\qquad [\nu_{w,h}^{t,k}\ge0].
$$
There is no separate rated-power multiplier. Nonnegativity of wind dispatch is a variable bound, not a second capacity row.
The continuation-cut multipliers correspond to
$$
\alpha_{t+1}^{p}
+(\beta_{A,t+1}^{p})^\top A
+(\beta_{S,t+1}^{p})^\top SOC_d
-\theta_{t+1}\le0,
\qquad [\lambda_p^{t,k}],
\quad p\in\mathcal C_{t+1},
$$
where $SOC_d=(SOC_{b,|\mathcal H|,d})_{b\in\mathcal B}$ and $\theta_{t+1}$ is the epigraph variable for the lower continuation approximation. The SOC multiplier corresponds to
$$
S_b^{\mathrm{in}}
+\eta_b\pi_{b,1,d}^{+}
-\frac{\pi_{b,1,d}^{-}}{\eta_b}
-SOC_{b,1,d}=0,
\qquad [\rho_b^{t,k}].
$$
With this equality orientation, $g_{S,b}^{t,k}=\rho_b^{t,k}$. Reversing the equality reverses the multiplier sign; solver-reported duals must be interpreted consistently with these Lagrangian conventions.

**Fixed plan during operation.** In iteration $k$, operational subproblems evaluate $A=\underline A^k$; they do not choose a new maintenance plan. Nevertheless, the cut records sensitivity to that parameter, so it can be evaluated for other plans in later iterations. The availability effect on continuation is already transmitted by the continuation cuts; it must not be counted again if using an equivalent state-copy/linking-dual formulation.

At the first-stage master, evaluate each root cut using the derived $A(a^r)$ and fixed $SOC^{\mathrm{init}}$. A term $\beta_{A,w,d}A_{w,d}$ can equivalently be expanded as
$$
\beta_{A,w,d}\bigl(|\mathcal G_w^r|-|\mathcal J_w^r|\bigr)
+\sum_{j\in\mathcal J_w^r}\beta_{A,w,d}a_{j,w,d}^r.
$$
The constant term must be retained if cuts are expressed directly in turbine-level master variables; every turbine in the same farm/day receives the same aggregated slope. No turbine-level availability variables are needed in the operational subproblems.

At the final operational stage $t=T+1$, the continuation is zero, so the continuation contribution vanishes.

## Upper-bound bilinear subproblem and fixed-realization LP

This section distinguishes (i) the robust subproblem that selects a worst-case daily realization using the **upper** continuation approximation and (ii) the fixed-realization LP used to obtain an operational decision and a **lower** cut. Let the incoming state at iteration $k$ be fixed at
$$
\bar{\mathbf{x}}_{t-1}^k=(\bar A^k,\bar S^{\mathrm{in},k}),
\qquad d=t-1.
$$
All availability components in the current-day dispatch are therefore data in these subproblems.

### Stored-point representation and its dual

For each operational stage $r=2,\ldots,T+1$, let the stored upper points be
$$
\mathcal P_r^k=
\left\{(A^p,S^{\mathrm{in},p},u_r^p):p\in J_r^k\right\},
\qquad u_r^p = \overline{\mathcal{Q}}_r (A^p,S^{\mathrm{in},p}) \geq\mathcal Q_r(A^p,S^{\mathrm{in},p}).
$$
For any state in their convex hull, the upper approximation is the LP
$$
\begin{aligned}
\overline{\mathcal Q}_{r}^k(A,S)
=\min_{\lambda\geq0}\quad
&\sum_{p\in J_{r}^k}u_{r}^p\lambda_p\\
\text{s.t.}\quad
&\sum_p\lambda_p=1,\qquad
\sum_p\lambda_p A^p=A,\qquad
\sum_p\lambda_p S^{\mathrm{in},p}=S.
\end{aligned}
\tag{U-env-P}
$$
Its LP dual is
$$
\begin{aligned}
\overline{\mathcal Q}_{r}^k(A,S)
=\max_{\kappa_0,\kappa_A,\kappa_S}\quad
&\kappa_0+\kappa_A^{\mathsf T}A+\kappa_S^{\mathsf T}S\\
\text{s.t.}\quad
&\kappa_0+(\kappa_A)^{\mathsf T}A^p
+(\kappa_S)^{\mathsf T}S^{\mathrm{in},p}\leq u_{r}^p,
&&p\in J_{r}^k.
\end{aligned}
\tag{U-env-D}
$$
The multipliers $\kappa_0,\kappa_A,\kappa_S$ are free. This is the dualization of the convex envelope; the point inequalities are essential and must be included in the bilinear subproblem. The representation is finite only where the state lies in the convex hull of the stored state points (or where a valid initial upper approximation supplies coverage). Here $A$ contains aggregated turbine counts, not binary turbine indicators. Different turbine-level plans with the same $A$ share the same operational state. Nevertheless, a new aggregated state is covered only if it belongs to the convex hull of the stored $(A^p,S^{\mathrm{in},p})$ points (or a valid initial upper approximation provides coverage). Aggregation does not remove this requirement. All points and cuts must use the same aggregated coordinates; the resulting finite-point envelope need not coincide with an envelope constructed in turbine-level coordinates.
For (UB-primal) with current stage $t$, use this representation at $r=t+1$; the same formula at $r=2$ is the upper approximation evaluated by the first-stage master-plan UB calculation.

### 1. Robust upper-value problem (the bilinear problem)

For $t=2,\ldots,T$, the primal max-min problem at the visited state is
$$
\boxed{
\begin{aligned}
\overline Q_t^k(\bar{\mathbf{x}}_{t-1}^k)
=\max_{\mathbf\xi_t\in\Xi_t}\quad\min_{x_t,\lambda}\quad
&q_t^{\mathsf T}x_t+
\sum_{p\in J_{t+1}^k}u_{t+1}^p\lambda_p\\
\text{s.t.}\quad
&x_t\in\mathcal F_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t),\\
&\sum_p\lambda_p=1,\qquad \lambda_p\geq0,\\
&\sum_p\lambda_p A^p=\bar A^k,\\
&\sum_p\lambda_p S^{\mathrm{in},p}
=R_t x_t,
\end{aligned}}
\tag{UB-primal}
$$
where $R_tx_t=(SOC_{b,|\mathcal H|,d})_{b\in\mathcal B}$ selects the outgoing terminal SOC. The last two constraints make the envelope state equal to $\mathbf x_t=(\bar A^k,R_tx_t)$. The feasible set $\mathcal F_t$ is exactly the hourly dispatch system defined above, including the final-SOC constraint when $d=T$.

To show the bilinear reformulation, write that dispatch system, after moving variable bounds into its rows, as
$$
\mathcal F_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t)
=\{x_t:A_tx_t\geq b_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t),\;
E_tx_t=e_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t)\}.
$$
Use $\mu_t\geq0$ for the $A_tx_t\geq b_t$ rows, $\nu_t$ free for the equalities, and $\kappa_0,\kappa_A,\kappa_S$ free for the three envelope-state equalities. Dualizing the inner LP in (UB-primal) gives the single-level problem
$$
\boxed{
\begin{aligned}
\overline Q_t^k(\bar{\mathbf{x}}_{t-1}^k)
=\max_{\mathbf\xi_t,\mu_t,\nu_t,\kappa_0,\kappa_A,\kappa_S}\quad
&b_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t)^{\mathsf T}\mu_t
+e_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t)^{\mathsf T}\nu_t
+\kappa_0+(\kappa_A)^{\mathsf T}\bar A^k\\
\text{s.t.}\quad
&A_t^{\mathsf T}\mu_t+E_t^{\mathsf T}\nu_t-R_t^{\mathsf T}\kappa_S=q_t,\\
&\kappa_0+(\kappa_A)^{\mathsf T}A^p
+(\kappa_S)^{\mathsf T}S^{\mathrm{in},p}\leq u_{t+1}^p,
&&p\in J_{t+1}^k,\\
&\mu_t\geq0,\qquad \mathbf\xi_t\in\Xi_t.
\end{aligned}}
\tag{UB-dual}
$$
For the dispatch formulation here, after fixing $(\bar A^k,\bar S^{\mathrm{in},k})$, the uncertain wind and demand values enter the right-hand sides, not the dispatch matrix. Hence $A_t,E_t$ are fixed, while $b_t,e_t$ are affine in $\mathbf\xi_t$; the products of uncertainty coordinates and dual multipliers in the objective make (UB-dual) bilinear. If a different algebraic reformulation puts uncertainty in $A_t$ or $E_t$, its dual-feasibility equations would also contain products.

In particular, write the single wind upper limit with the sign convention used in the cut section, and write demand coverage as $\tilde D_{h,d}-\sum_i y_{i,h,d}^{nr}-\sum_w y_{w,h,d}^{r}-\sum_b(\pi^-_{b,h,d}-\pi^+_{b,h,d})\leq0$. Their contributions to the dual objective are
$$
-\sum_{w,h}\frac{\tilde P_{w,h,d}^{r}}{|\mathcal G_w^r|}
\bar A_{w,d}^{k}\nu_{w,h}^t
+\sum_h\tilde D_{h,d}\delta_h^t,
$$
where $\nu^t,\delta^t\geq0$ are the multipliers of these $\leq0$ rows in a minimization Lagrangian. The wind-dispatch column gives $-\nu_{w,h}^t+\delta_h^t\leq0$, with no rated-power multiplier. Other objective terms come from the remaining dispatch right-hand sides, notably incoming SOC and operational bounds, and are included in the compact $b_t^{\mathsf T}\mu_t+e_t^{\mathsf T}\nu_t$ expression. In that compact notation $\mu_t$ denotes all inequality multipliers and $\nu_t$ the free equality multipliers; these vector symbols are distinct from the wind-specific scalar $\nu_{w,h}^t$.

**Uncertainty set pending.** $\mathbf\xi_t\in\Xi_t$ remains a symbolic requirement here; this revision does not define its inequalities, budgets, or PCA reconstruction. The bilinear implementation reserves a commented block for the user to add the daily uncertainty set and link it to `pwind[w, h]` and `demand[h]`. Admissible wind power will already satisfy its physical limits, so no separate rated-power dispatch constraint is needed. Without completing the uncertainty-set block, the implemented robust maximization can be unbounded and is not yet a complete worst-case oracle.

<!-- USER: add Xi_t and the reconstruction/linking equations for uncertain farm power and demand here. -->

At $t=T+1$ (last operational day), use $\overline{\mathcal Q}_{T+2}=0$: omit $\lambda$ and all $\kappa$ variables/constraints. The upper problem is then the same dualization of the one-day dispatch LP without a continuation term.

### 2. Fixed-realization operational LP

After (UB-dual) returns a worst-case realization $\mathbf\xi_t^{\mathrm{bw},k}$ (or $\mathbf\xi_t^{\mathrm{fw},k}$ in the forward pass), solve the LP used by RDDP to obtain the dispatch trajectory and, in the backward pass, the duals for the lower cut:
$$
\boxed{
\begin{aligned}
\underline Q_t(\bar{\mathbf{x}}_{t-1}^k;\mathbf\xi_t^k)
=\min_{x_t,\theta_{t+1}}\quad
&\sum_{h\in\mathcal H}\sum_{i\in\mathcal G^{nr}}
CV_i y_{i,h,d}^{nr}+\theta_{t+1}\\
\text{s.t.}\quad
&x_t\in\mathcal F_t(\bar{\mathbf{x}}_{t-1}^k,\mathbf\xi_t^k),\\
&\theta_{t+1}\geq\alpha_{t+1}^{p}
+(\beta_{A,t+1}^{p})^{\mathsf T}\bar A^k
+(\beta_{S,t+1}^{p})^{\mathsf T}R_tx_t,
&&p\in\mathcal C_{t+1}.
\end{aligned}}
\tag{FIXED-LP}
$$
Here $\mathcal C_{t+1}$ contains the stored **lower** affine cuts; include the initialized lower bound as a cut if needed. Since $\mathbf\xi_t^k$ is fixed, this is an LP. Its optimal duals yield the stage-$t$ lower cut described in Section 4.b.

If instead the aim is to recover the primal minimizer defining the upper value at the selected $\mathbf\xi_t^k$, solve (UB-primal) with $\mathbf\xi_t=\mathbf\xi_t^k$ fixed; that is also an LP, but it uses the $\lambda$-based upper envelope, not the lower cuts in (FIXED-LP). Thus the two LPs have different roles: (UB-primal) evaluates the upper recourse value, while (FIXED-LP) supplies the forward/backward decision and lower cut. For the first-stage plan $x_1^k$ returned by the lower-bound master, the global upper-bound update is
$$
UB^k=\min\left\{UB^{k-1},\;q_1^{\mathsf T}x_1^k+
\overline{\mathcal Q}_2^k(A^k,SOC^{\mathrm{init}})\right\}.
$$
Keep $x_1^k$ fixed when evaluating this expression; do not re-optimize the first-stage plan with $\overline{\mathcal Q}_2$. This update is valid only if the upper approximation is finite and valid at the root state; the stored-point hull alone may fail to cover a new aggregated availability/SOC state, so a valid initialization/coverage mechanism is needed.
