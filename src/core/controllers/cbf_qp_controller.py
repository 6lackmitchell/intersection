import jax.numpy as jnp
from nptyping import NDArray
from typing import Callable, List
from scipy.linalg import block_diag
from core.solve_cvxopt import solve_qp_cvxopt
from models.model import Model
from core.controllers.controller import Controller

from core.cbfs.cbf import Cbf


class CbfQpController(Controller):

    _stochastic = False
    _generate_cbf_condition = None
    _dt = None

    def __init__(
        self,
        model: Model,
        nominal_controller: Controller,
        objective_function: Callable,
        cbfs_individual: List,
        cbfs_pairwise: List,
        n_agents: int = 1,
        ignore: List = None,
    ):
        super().__init__()
        self.model = model
        self.nominal_controller = nominal_controller
        self.objective = objective_function
        self.cbfs_individual = cbfs_individual
        self.cbfs_pairwise = cbfs_pairwise
        self.ignored_agents = ignore
        self.code = 0
        self.status = "Initialized"

        # parameters
        self.n_states = model.n_states
        self.n_controls = model.n_controls
        self.n_agents = n_agents
        self.n_dec_vars = 1
        self.desired_class_k = 0.1
        self.max_class_k = 1e6
        self.u_max = model.u_max

        # cbf parameters
        self.cbf_vals = jnp.zeros(
            (len(cbfs_individual) + (self.n_agents - 1) * len(cbfs_pairwise)),
        )
        self.dhdt = jnp.zeros((self.cbf_vals.shape[0],))
        self.dhdx = jnp.zeros((self.cbf_vals.shape[0], 5))
        self.d2hdtdx = jnp.zeros((self.cbf_vals.shape[0], 5))
        self.d2hdx2 = jnp.zeros((self.cbf_vals.shape[0], 5, 5))

        # Define individual input constraints
        self.au = block_diag(*self.n_controls * [jnp.array([[1, -1]]).T])
        self.bu = jnp.tile(jnp.array(self.u_max).reshape(self.n_controls, 1), 2).flatten()

    def _compute_control(
        self, t: float, z: NDArray, cascaded: bool = False
    ) -> (NDArray, NDArray, int, str, float):
        """Computes the vehicle's control input based on a cascaded approach: first, the CBF constraints attempt to
        filter out unsafe inputs on the first level. If no safe control exists, then all control inputs are eligible
        for safety filtering.

        INPUTS
        ------
        t: time (in sec)
        z: full state vector for all vehicles
        extras: anything else

        OUTPUTS
        ------
        u_act: actual control input used in the system
        u_nom: nominal input used if safety not considered
        code: error/success code
        status: more info on error/success

        """
        code = 0
        status = "Incomplete"

        # Ignore agent if necessary (i.e. if comparing controllers for given initial conditions)
        ego = self.ego_id
        if self.ignored_agents is not None:
            self.ignored_agents.sort(reverse=True)
            for ignore in self.ignored_agents:
                z = jnp.delete(z, ignore, 0)
                if ego > ignore:
                    ego = ego - 1

        # Partition state into ego and other
        ze = z[ego, :]
        zo = jnp.vstack([z[:ego, :], z[ego + 1 :, :]])

        # Compute nominal control input for ego only -- assume others are zero
        z_copy_nom = z.copy()
        z_copy_nom[self.ego_id] = z[ego]
        u_nom = jnp.zeros((len(z), self.model.n_controls))
        u0, code_nom, status_nom = self.nominal_controller.compute_control(t, z_copy_nom)
        if self.u_nom is None:
            self.u_nom = u0
        u_nom = u_nom.at[ego, :].set(u0)
        self.u_nom = u_nom[ego, :]

        tuning_nominal = False
        if tuning_nominal:
            self.u = self.u_nom
            print(self.u)
            return self.u, 1, "Optimal"

        if not cascaded:
            # Get matrices and vectors for QP controller
            Q, p, A, b, G, h = self.formulate_qp(t, ze, zo, u_nom, ego)

            # Solve QP
            sol = solve_qp_cvxopt(Q, p, A, b, G, h)

            # Check solution
            if "code" in sol.keys():
                code = sol["code"]
                status = sol["status"]
                self.assign_control(sol, ego)
                if abs(self.u[0]) > 1e-3:
                    pass
            else:
                status = "Divide by Zero"
                self.u = jnp.zeros((self.n_controls,))

        else:
            pass

            # # Get matrices and vectors for QP controller
            # Q, p, A, b, G, h = self.formulate_qp(t, ze, zo, u_nom, ego, cascade=cascaded)
            #
            # # Solve QP
            # sol = solve_qp_cvxopt(Q, p, A, b, G, h)
            #
            # # Check solution
            # if 'code' in sol.keys():
            #     code = sol['code']
            #     status = sol['status']
            #
            #     if not code:
            #         if cascaded:
            #             Q, p, A, b, G, h = self.formulate_qp(t, ze, zo, u_nom, ego)
            #             sol = solve_qp_cvxopt(Q, p, A, b, G, h)
            #             if not sol['code']:
            #                 self.u = jnp.zeros((self.n_controls,))
            #             else:
            #                 self.assign_control(sol, ego)
            #         else:
            #             self.u = jnp.zeros((self.n_controls,))
            #     else:
            #         alf = jnp.array(sol['x'])[-1]
            #         self.assign_control(sol, ego)
            #
            # else:
            #     code = 0
            #     status = 'Divide by Zero'
            #     self.u = jnp.zeros((self.n_controls,))

        if not code:
            print(A[-1, :])
            print(b[-1])
            print("wtf")

        return self.u, code, status

    def formulate_qp(
        self, t: float, ze: NDArray, zr: NDArray, u_nom: NDArray, ego: int, cascade: bool = False
    ) -> (NDArray, NDArray, NDArray, NDArray, NDArray, NDArray, float):
        """Configures the Quadratic Program parameters (Q, p for objective function, A, b for inequality constraints,
        G, h for equality constraints).

        """
        # Parameters
        na = 1 + len(zr)
        ns = len(ze)
        self.safety = True

        # Configure QP Matrices
        # Q, p: objective function
        # Au, bu: input constraints
        if self.n_dec_vars > 0:
            alpha_nom = 1.0
            Q, p = self.objective(jnp.append(u_nom.flatten(), alpha_nom))
            Au = block_diag(*(na + self.n_dec_vars) * [self.au])[:-2, :-1]
            bu = jnp.append(jnp.array(na * [self.bu]).flatten(), self.n_dec_vars * [100, 0])
        else:
            Q, p = self.objective(u_nom.flatten())
            Au = block_diag(*(na) * [self.au])
            bu = jnp.array(na * [self.bu]).flatten()

        # Initialize inequality constraints
        lci = len(self.cbfs_individual)
        Ai = jnp.zeros((lci + len(zr), self.n_controls * na + self.n_dec_vars))
        bi = jnp.zeros((lci + len(zr),))

        # Iterate over individual CBF constraints
        for cc, cbf in enumerate(self.cbfs_individual):
            h0 = cbf.h0(ze)
            h = cbf.h(ze)
            dhdx = cbf.dhdx(ze)

            # Stochastic Term -- 0 for deterministic systems
            if jnp.trace(sigma(ze).T @ sigma(ze)) > 0 and self._stochastic:
                d2hdx2 = cbf.d2hdx2(ze)
                stoch = 0.5 * jnp.trace(sigma(ze).T @ d2hdx2 @ sigma(ze))
            else:
                stoch = 0.0

            # Get CBF Lie Derivatives
            Lfh = dhdx @ f(ze) + stoch
            Lgh = jnp.zeros((self.n_controls * na,))
            Lgh[self.n_controls * ego : (ego + 1) * self.n_controls] = dhdx @ g(
                ze
            )  # Only assign ego control
            if cascade:
                Lgh[self.n_controls * ego] = 0.0

            # Ai[cc, :], bi[cc] = self.generate_cbf_condition(cbf, h, Lfh, Lgh, cc, adaptive=True)
            Ai[cc, :], bi[cc] = self.generate_cbf_condition(cbf, h, Lfh, Lgh, cc)
            self.cbf_vals[cc] = h
            if h0 < 0:
                self.safety = False

        # Iterate over pairwise CBF constraints
        for cc, cbf in enumerate(self.cbfs_pairwise):

            # Iterate over all other vehicles
            for ii, zo in enumerate(zr):
                idx = ii + (ii >= ego)

                h0 = cbf.h0(ze, zo)
                h = cbf.h(ze, zo)
                dhdx = cbf.dhdx(ze, zo)

                # Stochastic Term -- 0 for deterministic systems
                if jnp.trace(sigma(ze).T @ sigma(ze)) > 0 and self._stochastic:
                    d2hdx2 = cbf.d2hdx2(ze, zo)
                    stoch = 0.5 * (
                        jnp.trace(sigma(ze).T @ d2hdx2[:ns, :ns] @ sigma(ze))
                        + jnp.trace(sigma(zo).T @ d2hdx2[ns:, ns:] @ sigma(zo))
                    )
                else:
                    stoch = 0.0

                # Get CBF Lie Derivatives
                Lfh = dhdx[:ns] @ f(ze) + dhdx[ns:] @ f(zo) + stoch
                Lgh = jnp.zeros((self.n_controls * na,))
                Lgh[self.n_controls * ego : (ego + 1) * self.n_controls] = dhdx[:ns] @ g(ze)
                if cascade:
                    Lgh[self.n_controls * ego] = 0.0
                # Lgh[self.n_controls * idx:(idx + 1) * self.n_controls] = dhdx[ns:] @ g(zo)  # Only allow ego to compensate for safety

                if h0 < 0:
                    print(
                        "{} SAFETY VIOLATION: {:.2f}".format(
                            str(self.__class__).split(".")[-1], -h0
                        )
                    )
                    self.safety = False

                update_idx = lci + cc * zr.shape[0] + ii
                Ai[update_idx, :], bi[update_idx] = self.generate_cbf_condition(
                    cbf, h, Lfh, Lgh, update_idx, adaptive=True
                )
                self.cbf_vals[update_idx] = h

        A = jnp.vstack([Au, Ai])
        b = jnp.hstack([bu, bi])

        return Q, p, A, b, None, None

    def generate_cbf_condition(
        self, cbf: Cbf, h: float, Lfh: float, Lgh: NDArray, idx: int, adaptive: bool = False
    ) -> (NDArray, float):
        """Calls the child _generate_cbf_condition method."""
        if self._generate_cbf_condition is not None:
            return self._generate_cbf_condition(cbf, h, Lfh, Lgh, idx, adaptive)
        else:
            return cbf.generate_cbf_condition(h, Lfh, Lgh, adaptive)

    def assign_control(self, solution: dict, ego: int) -> None:
        """Assigns the control solution to the appropriate agent."""
        if solution["status"] == "violates_constraints":
            u = self.u
        else:
            u = jnp.array(
                solution["x"][self.n_controls * ego : self.n_controls * (ego + 1)]
            ).flatten()
        self.u = u
        if u is not None:
            self.u = jnp.clip(u, -self.u_max, self.u_max)
        else:
            self.u = jnp.array([0, 0])
        self.nominal_controller.u_actual = self.u
        # Assign other agents' controls if this is a centralized node
        if hasattr(self, "centralized_agents"):
            for agent in self.centralized_agents:
                agent.u = jnp.array(
                    solution["x"][agent.nu * agent.id : self.n_controls * (agent.id + 1)]
                ).flatten()
