#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and 
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain 
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________

"""
Unit Tests for pyomo.dae.init_cond
"""
import os
from os.path import abspath, dirname

from six import StringIO

import pyutilib.th as unittest

from pyomo.environ import *
from pyomo.common.log import LoggingIntercept
from pyomo.dae import *
from pyomo.dae.init_cond import *
from pyomo.core.kernel.component_map import ComponentMap

currdir = dirname(abspath(__file__)) + os.sep

ipopt_available = SolverFactory('ipopt').available()


def make_model():
    m = ConcreteModel()
    m.time = ContinuousSet(bounds=(0, 10))
    m.space = ContinuousSet(bounds=(0, 5))
    m.set1 = Set(initialize=['a', 'b', 'c'])
    m.set2 = Set(initialize=['d', 'e', 'f'])
    m.fs = Block()

    m.fs.v0 = Var(m.space, initialize=1)

    @m.fs.Block()
    def b1(b):
        b.v = Var(m.time, m.space, initialize=1)
        b.dv = DerivativeVar(b.v, wrt=m.time, initialize=0)

        b.con = Constraint(m.time, m.space,
                rule=lambda b, t, x: b.dv[t, x] == 7 - b.v[t, x])
        # Inconsistent

        @b.Block(m.time)
        def b2(b, t):
            b.v = Var(initialize=2)

    @m.fs.Block(m.time, m.space)
    def b2(b, t, x):
        b.v = Var(m.set1, initialize=2)

        @b.Block(m.set1)
        def b3(b, c):
            b.v = Var(m.set2, initialize=3)

            @b.Constraint(m.set2)
            def con(b, s):
                return (5*b.v[s] ==
                        m.fs.b2[m.time.first(), m.space.first()].v[c])
                # inconsistent

    @m.fs.Constraint(m.time)
    def con1(fs, t):
        return fs.b1.v[t, m.space.last()] == 5
    # Will be inconsistent

    @m.fs.Constraint(m.space)
    def con2(fs, x):
        return fs.b1.v[m.time.first(), x] == fs.v0[x]
    # will be consistent

    disc = TransformationFactory('dae.collocation')
    disc.apply_to(m, wrt=m.time, nfe=5, ncp=2, scheme='LAGRANGE-RADAU')
    disc.apply_to(m, wrt=m.space, nfe=5, ncp=2, scheme='LAGRANGE-RADAU')

    return m


class TestDaeInitCond(unittest.TestCase):
    
    # Test explicit/implicit index detection functions
    def test_indexed_by(self):
        m = make_model()

        deactivate_model_at(m, m.time, m.time[2])
        self.assertTrue(m.fs.con1[m.time[1]].active)
        self.assertFalse(m.fs.con1[m.time[2]].active)
        self.assertTrue(m.fs.con2[m.space[1]].active)
        self.assertFalse(m.fs.b1.con[m.time[2], m.space[1]].active)
        self.assertFalse(m.fs.b2[m.time[2], m.space.last()].active)
        self.assertTrue(m.fs.b2[m.time[2], m.space.last()].b3['a'].con['e'].active)

        deactivate_model_at(m, m.time, [m.time[1], m.time[3]])
        # Higher outlvl threshold as will encounter warning trying to deactivate
        # disc equations at time.first()
        self.assertFalse(m.fs.con1[m.time[1]].active)
        self.assertFalse(m.fs.con1[m.time[3]].active)
        self.assertFalse(m.fs.b1.con[m.time[1], m.space[1]].active)
        self.assertFalse(m.fs.b1.con[m.time[3], m.space[1]].active)

        with self.assertRaises(KeyError):
            deactivate_model_at(m, m.time, m.time[1], allow_skip=False,
                    suppress_warnings=True)


    def test_get_inconsistent_initial_conditions(self):
        m = make_model()
        inconsistent = get_inconsistent_initial_conditions(m, m.time)

        self.assertIn(m.fs.b1.con[m.time[1], m.space[1]], inconsistent)
        self.assertIn(m.fs.b2[m.time[1], m.space[1]].b3['a'].con['d'],
                inconsistent)
        self.assertIn(m.fs.con1[m.time[1]], inconsistent)
        self.assertNotIn(m.fs.con2[m.space[1]], inconsistent)


    @unittest.skipIf(not ipopt_available, 'ipopt is not available')
    def test_solve_consistent_initial_conditions(self):
        m = make_model()
        solver = SolverFactory('ipopt')
        solve_consistent_initial_conditions(m, m.time, solver)
        inconsistent = get_inconsistent_initial_conditions(m, m.time)
        self.assertFalse(inconsistent)

        self.assertTrue(m.fs.con1[m.time[1]].active)
        self.assertTrue(m.fs.con1[m.time[3]].active)
        self.assertTrue(m.fs.b1.con[m.time[1], m.space[1]].active)
        self.assertTrue(m.fs.b1.con[m.time[3], m.space[1]].active)


if __name__ == "__main__":
    unittest.main()
