# Los puntos son de la forma (a_j, S_j, u_j)
            a_j = points[0]
            Sin_j = points[1]
            u_j = points[2]
            model = self.model
            W = self.system.wind.n_parks
            T = self.system.horizon
            J_r = self.system.wind.J_r(T)
            dimension = len(points[0])
            if self.convex_hull_variables is not None:
                model.remove(self.convex_hull_variables)
            # Se agrega un lambda_j para cada punto
            self.convex_hull_variables = model.addVars(len(points), lb=0.0, ub = 1.0, name="lambda_convex_hull")
            if self.convex_hull_lambda is not None:
                model.remove(self.convex_hull_lambda)
            # La suma de todos los lambda_j debe ser 1
            self.convex_hull_lambda = model.addConstr(
                gp.quicksum(self.convex_hull_variables) == 1.0,
                name="convex_hull_lambda_sum",
            )
            if self.convex_hull_a is not None:
                model.remove(self.convex_hull_a)
            # suma de todos los lambda_j * a_j debe ser igual a la disponibilidad para todos los parques todas las turbinas, todo el horizonte
            self.convex_hull_a = model.addConstr(
                (gp.quicksum(self.convex_hull_variables[p] * a_j[p][j][w][tau] for p in range(dimension)) == availability[w][tau] for w in range(W) for tau in range(T) for j in range(J_r)),
                name="convex_hull_a_sum",
            )
            if self.convex_hull_S is not None:
                model.remove(self.convex_hull_S)
            # suma de todos los lambda_j * S_j debe ser igual a la disponibilidad para todos los parques todas las turbinas, todo el horizonte
            self.convex_hull_S = model.addConstr(
                (gp.quicksum(self.convex_hull_variables[p] * Sin_j[p][b] for p in range(dimension)) == availability[b] for b in range(B)),
                name="convex_hull_S_sum",
            )
                
            if self.convex_hull_restrictions:
                for restriction in self.convex_hull_restrictions:
                    model.remove(restriction)
                self.convex_hull_restrictions = []
            
        else:
            # Dual de min sum_j lambda_j u_j + M mu:
            # sum_j lambda_j s_j + z = s_out, sum_j lambda_j + mu = 1,
            # mu lb <= z <= mu ub. Cada punto nuevo añade nu·s_j + omega <= u_j.
            dimension = future.dimension
            nu = model.addVars(dimension, lb=-gp.GRB.INFINITY, name="nu")
            kappa_hi = model.addVars(dimension, lb=0.0, name="kappa_hi")
            kappa_lo = model.addVars(dimension, lb=0.0, name="kappa_lo")
            omega = model.addVar(lb=-gp.GRB.INFINITY, name="omega")
            model.addConstrs(
                (nu[k] - kappa_hi[k] + kappa_lo[k] == 0.0 for k in range(dimension)),
                name="future_residual",
            )
            model.addConstr(
                gp.quicksum(float(future.ub[k]) * kappa_hi[k] - float(future.lb[k]) * kappa_lo[k]
                            for k in range(dimension)) + omega <= future.big_m,
                name="future_box",
            )
            # ν entra con el signo de la igualdad z + Σ λ x = soc: el multiplicador
            # resta en la columna del SOC terminal.
            model.addConstrs(
                (
                    lambda_soc[b, H - 1]
                    + lambda_soc_min[b, H - 1]
                    - lambda_soc_max[b, H - 1]
                    - nu[b]
                    == 0.0
                    for b in range(B)
                ),
                name="soc_dual_future",
            )