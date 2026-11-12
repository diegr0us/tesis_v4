---
kind: business_term
name: Business Glossary
category: business_term
scope:
    - '**'
---

### soporte
- Definition：The axis-aligned uncertainty box in PCA coordinates (center c, radii a) that bounds the central 80 % of each principal component; when mapped back to MW it becomes the interval hull of the parallelepiped used as the robust dispatch's support set.
- Aliases：support set

### presupuesto
- Definition：Bertsimas–Sim-style budget constraints calibrated on training scores: Phi = 90th percentile of L1-norm B and Psi = 90th percentile of the sum of the two largest absolute scores among the first s components C. They cap the total deviation budget and the pairwise/Gamma-style concentration budget respectively.
- Aliases：budgets、Phi、Psi

### componentes pares
- Definition：The leading-s subset (s ≤ r) of retained PCA modes selected so that they capture at least 90 % of the already-retained variance; these are the components over which the pairwise budget C is computed.
- Aliases：s、leading components
