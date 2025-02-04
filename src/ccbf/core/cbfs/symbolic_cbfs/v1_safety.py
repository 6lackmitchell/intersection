import builtins
import numpy as np
import symengine as se
from importlib import import_module
from core.cbfs.cbf_wrappers import symbolic_cbf_wrapper_singleagent

vehicle = builtins.PROBLEM_CONFIG["vehicle"]
control_level = builtins.PROBLEM_CONFIG["control_level"]
mod = "models." + vehicle + "." + control_level + ".models"

# Programmatic import
try:
    module = import_module(mod)
    globals().update({"f": getattr(module, "f")})
    globals().update({"ss": getattr(module, "sym_state")})
except ModuleNotFoundError as e:
    print("No module named '{}' -- exiting.".format(mod))
    raise e

# Defining Physical Params
speed_limit = 1.0
gain = 5.0

# Speed CBF Symbolic
h_speed_symbolic = gain * (speed_limit - ss[2]) * (ss[2] + speed_limit)
dhdx_speed_symbolic = (
    se.DenseMatrix([h_speed_symbolic]).jacobian(se.DenseMatrix(ss))
).T
d2hdx2_speed_symbolic = dhdx_speed_symbolic.jacobian(se.DenseMatrix(ss))
h_speed_func = symbolic_cbf_wrapper_singleagent(h_speed_symbolic, ss)
dhdx_speed_func = symbolic_cbf_wrapper_singleagent(dhdx_speed_symbolic, ss)
d2hdx2_speed_func = symbolic_cbf_wrapper_singleagent(d2hdx2_speed_symbolic, ss)


def h_speed1(ego):
    return h_speed_func(ego)


def dhdx_speed1(ego):
    ret = dhdx_speed_func(ego)

    return np.squeeze(np.array(ret).astype(np.float64))


def d2hdx2_speed1(ego):
    ret = d2hdx2_speed_func(ego)

    return np.squeeze(np.array(ret).astype(np.float64))


if __name__ == "__main__":
    # This is a unit test
    pass
