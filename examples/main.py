"""main simulation file with customizable settings"""
# package imports
import jax.numpy as jnp

# generic simulation imports
from core.agent import Agent
from core.simulate import simulate

# settings for simulation
from models.bicycle import DynamicBicycleModel
from models.bicycle.nominal_controllers import LqrController, ZeroController
from models.bicycle.cbfs.obstacle_avoidance import cbfs as cbfs_obstacle_avoidance
from models.bicycle.cbfs.speed_limit import cbfs as cbfs_speed
from models.bicycle.cbfs.slip_limit import cbfs as cbfs_slip
from models.bicycle.cbfs.reach_target import cbfs as cbfs_reach
from core.controllers.consolidated_cbf_controller_autograd import ConsolidatedCbfController
from core.controllers.objective_functions import minimum_deviation

# save location
save_file = (
    "/home/6lackmitchell/Documents/git/ccbf-control/data/bicycle/dynamic/toy_example/test.pkl"
)
# save_file = "/Users/mblack/Documents/git/ccbf-control/data/bicycle/dynamic/toy_example/test.pkl"
# save_file = "/home/ccbf-control/data/bicycle/dynamic/toy_example/test.pkl"

# time params
tf = 10.0
dt = 1e-2

# bicycle dynamics model
u_max = jnp.array([jnp.pi / 2, 1.0])
goal_state = jnp.array([2.0, 2.0, 0.0, 0.0, 0.0])
xi = -1.0
yi = 0.0
psii = jnp.arctan2(goal_state[1] - yi + 0.1, goal_state[0] - xi)
vi = 0.5
x0 = jnp.array([xi, yi, psii, vi, 0.0])
bicycle_model = DynamicBicycleModel(initial_state=x0, u_max=u_max, dt=dt, tf=tf)

# consolidated cbf controller
nominal_controller = LqrController(xg=goal_state, model=bicycle_model)
# nominal_controller = ZeroController()
objective = minimum_deviation
cbfs_individual = cbfs_obstacle_avoidance + cbfs_reach + cbfs_speed + cbfs_slip
cbfs_pairwise = []
ccbf_controller = ConsolidatedCbfController(
    model=bicycle_model,
    nominal_controller=nominal_controller,
    objective_function=minimum_deviation,
    cbfs_individual=cbfs_individual,
    cbfs_pairwise=cbfs_pairwise,
)
agents = [
    Agent(
        model=bicycle_model,
        controller=ccbf_controller,
        save_file=save_file,
    ),
]

# set agent identifiers
for aa, agent in enumerate(agents):
    agent.set_id(aa)


success = simulate(tf, dt, agents)
