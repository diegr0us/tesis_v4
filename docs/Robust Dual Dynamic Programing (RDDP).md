---
tags:
  - robust-optimization
category: academic_concepts
---
RDDP is a algorithm proposed by ([[Robust Dual Dynamic Programming - 2019 - Georghiou|Georghiou et al., 2019]]) for multistage robust optimization problems:
$$
\begin{align}
\min_{\xi \in \Xi}\;
\max \quad
& \sum_{t=1}^{T} q_t(\xi_t)^\top x_t(\xi^t)
\\
\text{subject to} \quad
& W_1(\xi_1)x_1(\xi^1) \geq h_1(\xi_1),
&& \forall \xi \in \Xi,
\\
& T_t(\xi_t)x_{t-1}(\xi^{t-1})
+ W_t(\xi_t)x_t(\xi^t)
\geq h_t(\xi_t),
&& \forall \xi \in \Xi,\quad \forall t=2,\ldots,T,
\\
& x_t(\xi^t)\in\mathbb{R}^{n_t},
&& \xi\in\Xi,\quad t=1,\ldots,T.
\end{align} \tag{1}
$$
(1) We assume that $ξ_1$ is deterministic, and hence $x_1$ is a here-and-now decision ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=2&selection=29,2,40,26|Georghiou et al., 2019]])
(2) Ξ be stage-wise rectangular ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=2&selection=6,13,6,37|Georghiou et al., 2019]])

Similar to the popular stochastic dual dynamic programming (SDDP) ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=4&selection=13,0,13,65|Georghiou et al., 2019]])
Decouples problem (1) into $T$ two stage subproblems which approximate the costs arising in future stages through bounds on the cost to-go functions

Maintains both lower and upper bounds on these cost to-go functions ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=4&selection=20,74,28,42|Georghiou et al., 2019]]) Each forward pass determines an approximate worst-case realization of the parameters ξ and the associated recourse decisions $x_1(ξ^1), . . . , x_T (ξ^T )$. ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=4&selection=33,49,55,2|Georghiou et al., 2019]])

The subsequent backward pass refines the upper and lower cost to-go approximations along the selected decision ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=4&selection=61,9,62,27|Georghiou et al., 2019]])

Assumptions
(A1) **Boundedness**. The feasible region of problem (1) is bounded, that is, any feasible solution satisfies $‖x_t(ξ_t)‖ ≤ M \:$ for all $\: ξ ∈ Ξ \:$ and $t = 1, . . . , T$ , where $M$ is a sufficiently large number.

(A2) **Relatively Complete Recourse**. Problem (1) has a relatively complete recourse, that is, any partial solution $x_1, . . . , x_t$ satisfying the constraints up to time period t can be extended to a complete solution $x_1, . . . , x_T$ that satisfies all constraints for every realization ξ ∈ Ξ.

(A3) **Uncertainty Set**. The uncertainty set is bounded, polyhedral and stage-wise rectangular, that is, $Ξ = ×^T_{t=1} Ξ_t$ for bounded sets $Ξ_t = {ξ_t ∈ R_{kt} : F_tξ_t ≤ g_t}\: | \: F_t ∈ R_{lt}×_{kt} \: |\: gt ∈ Rlt$. 

(A4) **Uncertain Parameters**. The objective coefficients $q_t ∈ R^{n_t}$ and the recourse matrices $W_t ∈ R^{m_t×n_t}$ are deterministic, while $T_t \: : \: Ξ_t → R^{m_t×n_{t−1}}$ and $h_t : Ξ_t → R^{m_t}$ are affine in $ξ_t$.

If Right-Hand Sides have follow a form $h_t(ξ_t) = h^0_t + H_{tτ} ξ_τ$

RDDP can be extend without the assumptions (A1)-(A2) ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=1&annotation=819R|Georghiou et al., 2019]])

# Nested Formulation

Under (A3), problem (1) has the equivalent nester formulation([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=1&annotation=819R|Georghiou et al., 2019]]):
$$
\begin{aligned}
\text{minimize}\quad & q_1^{\mathsf T}x_1 + Q_2(x_1)\\
\text{subject to}\quad & W_1x_1 \ge h_1,\\
& x_1 \in \mathbb{R}^{n_1}.
\end{aligned}
$$
where we omit the dependence of $W_1$ and $h_1$ on the deterministic parameters $ξ_1$, and where the stage-t worst-case cost to-go function $\mathcal{Q}_t$ is defined as $\mathcal{Q}_t(x_{t−1}) = max\{Q_t(x_{t−1}; ξ_t) : ξ_t ∈ Ξ_t\}$ with ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=7&selection=225,0,282,4|Georghiou et al., 2019, p.7]]):
$$
Q_t(x_{t-1};\xi_t)
=
\left[
\begin{aligned}
\text{minimize}\quad & q_t^{\mathsf T}x_t + \mathcal{Q}_{t+1}(x_t)\\
\text{subject to}\quad & T_t(\xi_t)x_{t-1} + W_tx_t \ge h_t(\xi_t),\\
& x_t \in \mathbb{R}^{n_t}
\end{aligned}
\right.,
\qquad t=2,\ldots,T.
$$

and $\mathcal{Q}_{T +1}(x_T ) = 0$ for all $x_T ∈ R^{n_T}$$ . In the following, we refer to $Q_t$ as the stage-t nominal cost to-go problem.  ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=7&selection=378,0,411,2|Georghiou et al., 2019, p.7]])

Note: $\mathcal{Q}_t(x_{t-1})$ is the exact worst-case cost-to-go, while $Q_t(x_{t-1};\xi_t)$ is the exact nominal cost-to-go for a fixed realization $\xi_t$. The approximations are the underlined and overlined functions introduced below.  

(A1)-(A3) preclute infeasible or unbounded values. $Q_t$ always attains finite values on the real line. ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=8&selection=9,0,12,45&color=yellow|Georghiou et al., 2019, p.8]])

$\mathcal{Q_t}$ is convex and piecewise affine for $t = 2, . . . , T$ ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=8&selection=18,0,28,1|Georghiou et al., 2019, p.8]])

 $Q_t(x_{t−1}; ·)$ is convex in the realization $ξ_t$  ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=8&selection=33,0,49,28|Georghiou et al., 2019, p.8]])

$Q_{(x_{t−1})}$ is strongly NP-hard  ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=8&selection=69,0,78,20|Georghiou et al., 2019, p.8]])

In general, state variables are the components that affect the cost-to-go function, while the remaining components are control variables. Although the formulation links each stage only to the preceding decision vector $x_{t-1}$, a first-stage decision $z$ that affects the entire horizon can be included as a persistent component of the state. This is done by setting $z_1=z$ and imposing $z_t=z_{t-1}$ for $t=2,\ldots,T$. Thus, $z$ is chosen in the first stage and carried forward unchanged, rather than re-optimized at each subsequent stage. The RDDP algorithm retains its structure, but its cost-to-go approximations are defined over the augmented state.

# Robust Dual Dynamic Programming

$\mathcal{Q}_{t+1}$ is itself unknown for $t < T$. In what follows, we iteratively construct lower and upper bounds, $\underline{\mathcal{Q}}_t$ and $\overline{\mathcal{Q}}_t$, respectively, for each worst-case cost-to-go function $\mathcal{Q_t}$, where $t = 2, \ldots, T$. 

These bounds satisfy
$$\underline{\mathcal{Q}}(x_{t-1}) \leq \mathcal{Q}(x_{t-1}) \leq \overline{\mathcal{Q}}_t(x_{t-1}) \quad \text{for all } x_{t-1} \in \mathbb{R}^{n_{t-1}}
$$

Given an upper bound $\overline{\mathcal{Q}}_{t+1}$ and a point $x_{t-1}$, we can obtain an upper bound on $\mathcal{Q}(x_{t-1})$ by solving:
$$
\overline{Q}_t(x_{t-1})
=
\max_{\xi_t \in \Xi_t}
\left\{
\begin{aligned}
\min_{x_t \in \mathbb{R}^{n_t}} \quad
    & q_t^\top x_t + \overline{\mathcal{Q}}_{t+1}(x_t) \\
\text{sujeto a} \quad
    & T_t(\xi_t)x_{t-1} + W_t x_t \ge h_t(\xi_t)
\end{aligned}
\right\}.
\tag{2}

$$

If the upper bound $\overline{\mathcal{Q_{t+1}}}$ is convex and piecewise affine we can solve (2) as a mixed-integred lineal program or via vertex enumeration.

Similarly, we can bound $\mathcal{Q}(x_{t−1})$ from below by fixing any realization $ξ_t ∈ Ξ_t$ and solving:
$$
\underline{Q}_t(x_{t-1})
=

\left\{
\begin{aligned}
\min_{x_t \in \mathbb{R}^{n_t}} \quad
    & q_t^\top x_t + \underline{\mathcal{Q}}_{t+1}(x_t) \\
\text{sujeto a} \quad
    & T_t(\xi_t)x_{t-1} + W_t x_t \ge h_t(\xi_t)
\end{aligned}
\right\}
\tag{3}

$$

Contrary to the upper bound problem $\overline{\mathcal{Q}}_{t+1}(x_{t-1})$, the problem (2) bound $\mathcal{Q_{t}}(x_{t-1})$ from below since it only considers a single realization $ξ_t ∈ Ξ_t$ and employs the lower bound $\underline{\mathcal{Q}}_{t+1}$.

If the under bound $\overline{\mathcal{Q}}_{t+1}$ is convex and piecewise affine we can solve (3) as a linear program.

The idea is bound the stage-$t$ worst-stage cost $\overline{\mathcal{Q}}_{t+1}$ from below through supporting hyperplanes of $

We can show that for a fixed parameter realization $ξ_t ∈ Ξ_t$, the optimal solution $π_t$ of the dual problem provides the supporting hyperplane:
$$
x_{t-1}
\mapsto
\bigl[h_t(\xi_t)-T_t(\xi_t)x_{t-1}\bigr]^\top \pi_t
-
\underline{\mathcal{Q}}_{t+1}^{*}\!\left(W_t^\top \pi_t-q_t\right)
$$
where $\underline{\mathcal{Q}}_{t+1}^{*}$ is the conjugate or _Legendre-Fenchel transformation_. This hyperplane touches $\underline{Q}_t(·; ξ_t)$ at $x_{t−1}$ 

RDDP scheme iteratively refines lower and upper bounds on the worst-case cost to-go functions $\mathcal{Q}_t$

We have a _forward passes (fw)_ in which generate sequences worst-case parameter realization $\xi_t^{fw}$ and the associated recourse decision $\underline{x}_t$. On the other hand, we have a _backward passes_ in which refine the lower and upper bound $\underline{\mathcal{Q}}_t$ and $\overline{\mathcal{Q}}_t$ along these decisions $\underline{x}_{t}$.

Intuitively speaking, we can regard the nested problem formulation (1’) as a $T$-stage zero-sum game between a decision maker aiming to minimize the overall costs and an adversary attempting to maximize these costs. Once we have determined a strategy pair $(ξ, x)$ for the adversary and the decision maker such that the upper and lower bounds in each stage $t$ coincide at $x_t$, both strategies are optimal and we have found a worst-case parameter realization $ξ$ and a worst-case optimal decision $x$. ([[Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=10&selection=221,0,243,1|Georghiou et al., 2019, p.10]])

**The adversary uses upper bounds; the decision maker uses lower bounds.**

"Una vez encontramos se solución para el adversirio el par ($x$,$\xi$) en la cual su cota inferior y superior coinciden para cada una de las etapa $t$ en $x_t$, ambas estrategias son optimzas y correponden al peor caso de $\xi$ y al peor caso de la decision óptima $x$"

## RDDP scheme

The following is the scheme in Section 3.1, under assumptions (A1)-(A4). Source: [[attachments/zotero_pdf/Robust Dual Dynamic Programming - 2019 - Georghiou, Angelos.pdf#page=10|Georghiou et al., 2019, pp. 10-13]].

### Notation

| Notation                       | Meaning                                                      | Computation or representation                                                                                                   |
| ------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| $\mathcal{Q}_t(s)$             | **Exact worst-case** cost-to-go at incoming state $s$        | $\max_{\xi_t\in\Xi_t}Q_t(s;\xi_t)$                                                                                              |
| $Q_t(s;\xi_t)$                 | **Exact nominal** cost-to-go for a fixed realization $\xi_t$ | Minimization subproblem using the exact future cost $\mathcal{Q}_{t+1}$                                                         |
| $\underline{\mathcal{Q}}_t(s)$ | **Stored lower approximation** of $\mathcal{Q}_t(s)$         | Maximum of the affine cuts added so far                                                                                         |
| $\overline{\mathcal{Q}}_t(s)$  | **Stored upper approximation** of $\mathcal{Q}_t(s)$         | Lower convex envelope incorporating points with computed upper-bound values                                                     |
| $\underline{Q}_t(s;\xi_t)$     | Approximate nominal subproblem value for a fixed realization | Minimization using $\underline{\mathcal{Q}}_{t+1}$; provides a lower bound on $\mathcal{Q}_t(s)$                                |
| $\overline{Q}_t(s)$            | Approximate worst-case subproblem value                      | Maximization over $\xi_t$ of a minimization using $\overline{\mathcal{Q}}_{t+1}$; provides an upper bound on $\mathcal{Q}_t(s)$ |
| $s\in\mathbb{R}^{n_{t-1}}$     | **Generic state** at stage $t$                               | Argument of the functions; feasible or reachable states are relevant during execution                                           |
| $\underline{x}_{t-1}$          | **Specific state visited** by the algorithm                  | Decision obtained from the first-stage problem or the forward pass                                                              |

### 1. Initialization

For $t=2,\ldots,T$, initialize
$$
\underline{\mathcal{Q}}_t(s)=LB_t^{\mathrm{init}},
\qquad
\overline{\mathcal{Q}}_t(s)=UB_t^{\mathrm{init}}.
$$
Here $LB^{init}$ and $UB_{init}$ are valid initial stage-specific bound satisfying $LB_t^{\mathrm{init}}\le\mathcal{Q}_t(s)<UB_t^{init}$ for every relevant state $s$.

Set
$$
UB = UB_2^{init}, \quad LB=LB_2^{init}
$$

Set the terminal functions to zero:
$$
\underline{\mathcal{Q}}_{T+1}(x_T)
=\overline{\mathcal{Q}}_{T+1}(x_T)=0.
$$

### 2. First-stage problem and stopping test

Solve the lower-bound first-stage problem:
$$
\underline{x}_1\in\arg\min_{x_1}
\left\{q_1^\top x_1+\underline{\mathcal{Q}}_2(x_1):W_1x_1\ge h_1\right\}.
$$
At this decision, define bounds on the worst-case future cost:
$$
LB=\underline{\mathcal{Q}}_2(\underline{x}_1),
\qquad
UB=\overline{\mathcal{Q}}_2(\underline{x}_1),
\qquad LB\le\mathcal{Q}_2(\underline{x}_1)\le UB.
$$
If $\underline{\mathcal{Q}}_2(\underline{x}_1)=\overline{\mathcal{Q}}_2(\underline{x}_1)$, stop: $\underline{x}_1$ is optimal. 

### 3. Forward pass: explore a decision trajectory

For $t=2,\ldots,T-1$:

1. Solve $\overline{Q}_t(\underline{x}_{t-1})$ and select an optimal outer maximizer $\xi_t^{\mathrm{fw}}$.
2. Fix $\xi_t^{\mathrm{fw}}$ and solve $\underline{Q}_t(\underline{x}_{t-1};\xi_t^{\mathrm{fw}})$; store an optimal recourse decision $\underline{x}_t$.
### 4. Backward pass: refine both bounds

For $t=T,T-1,\ldots,2$, using the already updated stage-$(t+1)$ approximations:

**(a) Upper-bound update.** Solve $\overline{Q}_t(\underline{x}_{t-1})$, obtaining its value and an optimal realization $\xi_t^{\mathrm{bw}}$. If $\overline{Q}_t<\overline{\mathcal{Q}}_t(\underline{x}_{t-1})$, update
$$
\overline{\mathcal{Q}}_t(s)\leftarrow
\operatorname{env}\!\left(
\min\left\{\overline{\mathcal{Q}}_t(s),
\overline{Q}_t(\underline{x}_{t-1})+\delta_{\{\underline{x}_{t-1}\}}(s)\right\}
\right).
$$
Here $\operatorname{env}$ is the lower convex envelope and the indicator $\delta_{\{\underline{x}_{t-1}\}}$ is zero at the visited state and $+\infty$ elsewhere. 

**(b) Lower-bound update.** Solve $\underline{Q}_t(\underline{x}_{t-1};\xi_t^{\mathrm{bw}})$ and obtain an optimal dual multiplier $\pi_t\ge0$ for the linking constraints. Let its value be $\ell_t$ = $\underline{Q}_t(\underline{x}_{t-1};\xi_t^{\mathrm{bw}})$ and define the affine cut
$$
 c_t(s)=\ell_t-
 \bigl[T_t(\xi_t^{\mathrm{bw}})^\top\pi_t\bigr]^\top
 (s-\underline{x}_{t-1}).
$$
Equivalently, by strong duality,
$$
c_t(s)=
\bigl[h_t(\xi_t^{\mathrm{bw}})-T_t(\xi_t^{\mathrm{bw}})s\bigr]^\top\pi_t
-\underline{\mathcal{Q}}_{t+1}^{*}(W_t^\top\pi_t-q_t).
$$
If $\ell_t>\underline{\mathcal{Q}}_t(\underline{x}_{t-1})$, update
$$
\underline{\mathcal{Q}}_t(s)\leftarrow
\max\left\{\underline{\mathcal{Q}}_t(s),c_t(s)\right\}.
$$
The cut touches the lower-bound nominal value function at the visited state; it need not touch the exact worst-case function. After updating all stages, return to Step 2.

---

At stage $T$, the terminal cost is exact, so the backward update closes the local gap at $\underline{x}_{T-1}$. Earlier-stage updates propagate this information backward. Throughout the algorithm,
$$
\underline{\mathcal{Q}}_t(s)\le\mathcal{Q}_t(s)\le\overline{\mathcal{Q}}_t(s).
$$

### Explicit convex-envelope formulation in the subproblems

Only the **upper approximation** $\overline{\mathcal{Q}}_t$ is represented by a convex envelope of stored points; the exact function $\mathcal{Q}_t$ is not explicitly available. The lower approximation is represented by affine cuts.

For each stage $t$, store the finite upper-bound points
$$
\mathcal{P}_t=\{(s_t^j,u_t^j):j\in J_t\},
\qquad u_t^j\ge\mathcal{Q}_t(s_t^j),
$$
where $s_t^j$ is an incoming state at stage $t$ (a visited decision from stage $t-1$). With the paper's $+\infty$ initialization, the resulting upper approximation is
$$
\overline{\mathcal{Q}}_t(s)
=\min_{\lambda\ge0}
\left\{\sum_{j\in J_t}\lambda_j u_t^j:
\sum_{j\in J_t}\lambda_j s_t^j=s,\quad
\sum_{j\in J_t}\lambda_j=1\right\}.
$$
This is the **convex-combination formulation**, or *lambda method*.