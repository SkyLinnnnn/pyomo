#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and 
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain 
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________

from pyomo.core.base import Constraint, Block, value
from pyomo.kernel import ComponentSet, ComponentMap
from pyomo.dae.set_utils import (is_explicitly_indexed_by, get_index_set_except,
        is_in_block_indexed_by)


def index_warning(name, index):
    return 'WARNING: %s has no index %s' % (name, index)


def deactivate_model_at(b, cset, pts, allow_skip=True, suppress_warnings=False):
    """
    Finds any block or constraint in block b, indexed explicitly (and not 
    implicitly) by cset, and deactivates it at points specified. 
    Implicitly indexed components are excluded because one of their parent 
    blocks will be deactivated, so deactivating them too would be redundant.

    Args:
        b : Block to search
        cset : ContinuousSet of interest
        pts : Value or list of values, in ContinuousSet, to deactivate at

    Returns:
        A dictionary mapping points in pts to lists of
        component data that have been deactivated there
    """
    if type(pts) is not list:
        pts = [pts]
    for pt in pts:
        if pt not in cset:
            msg = str(pt) + ' is not in ContinuousSet ' + cset.name
            raise ValueError(msg)
    deactivated = {pt: [] for pt in pts}

    visited = set()
    for comp in b.component_objects([Block, Constraint], active=True):
        # Record components that have been visited in case component_objects
        # contains duplicates (due to references)
        if id(comp) in visited:
            continue
        visited.add(id(comp))

        if (is_explicitly_indexed_by(comp, cset) and
                not is_in_block_indexed_by(comp, cset)):
            info = get_index_set_except(comp, cset)
            non_cset_set = info['set_except']
            index_getter = info['index_getter']

            for non_cset_index in non_cset_set:
                for pt in pts:
                    index = index_getter(non_cset_index, pt)
                    try:
                        comp[index].deactivate()
                        deactivated[pt].append(comp[index])
                    except KeyError:
                        # except KeyError to allow Constraint/Block.Skip
                        if not suppress_warnings:
                            print(index_warning(comp.name, index))
                        if not allow_skip:
                            raise
                        continue

    return deactivated


def get_inconsistent_initial_conditions(model, time, tol=1e-8, t0=None, 
        allow_skip=True, suppress_warnings=False):
    """Finds constraints of the model that are implicitly or explicitly
    indexed by time and checks if they consistent to within a tolerance
    at the initial value of time.

    Args:
        model: Model whose constraints to check
        time: Set whose initial condition will be checked
        tol: Maximum constraint violation
        t0: Point in time at which to check constraints

    Returns:
        List of constraint data objects that were found to be inconsistent.
    """
    if t0 is None:
        t0 = time.first()

    inconsistent = ComponentSet()
    for con in model.component_objects(Constraint, active=True):
        if not is_explicitly_indexed_by(con, time):
            continue
        if is_in_block_indexed_by(con, time):
            continue
        info = get_index_set_except(con, time)
        non_time_set = info['set_except']
        index_getter = info['index_getter']
        for non_time_index in non_time_set:
            index = index_getter(non_time_index, t0)
            try:
                condata = con[index]
            except KeyError:
                # To allow Constraint.Skip
                if not suppress_warnings:
                    print(index_warning(con.name, index))
                if not allow_skip:
                    raise
                continue
            if (value(condata.body) - value(condata.upper) > tol or
                value(condata.lower) - value(condata.body) > tol):
                inconsistent.add(condata)

    for blk in model.component_objects(Block, active=True):
        # What if there are time-indexed blocks at multiple levels
        # of a hierarchy?
        # My preferred convention is to only check the first (highest-
        # level) time index, but distinguishing between different-level
        # time indices is an expensive operation.
        if not is_explicitly_indexed_by(blk, time):
            continue
        if is_in_block_indexed_by(blk, time):
            continue
        info = get_index_set_except(blk, time)
        non_time_set = info['set_except']
        index_getter = info['index_getter']
        for non_time_index in non_time_set:
            index = index_getter(non_time_index, t0)
            blkdata = blk[index]
            for condata in blkdata.component_data_objects(Constraint,
                    active=True):
                if (value(condata.body) - value(condata.upper) > tol or
                    value(condata.lower) - value(condata.body) > tol):
                    if condata in inconsistent:
                        raise ValueError(
                            '%s has already been visited. The only way this '
                            'should happen is if the model has nested time-'
                            'indexed blocks, which is not supported.')
                    inconsistent.add(condata)

    return list(inconsistent)


def solve_consistent_initial_conditions(model, time, solver):
    """
    Solves a model with all Constraints and Blocks deactivated except
    at the initial value of the Set time. Reactivates Constraints and
    Blocks that got deactivated.

    Args:
        model: Model that will be solved
        time: Set whose initial conditions will remain active for solve
        solver: Something that implements an solve method that accepts
                a model as an argument

    Returns:
        The object returned by the solver's solve method
    """
    # Need to deactivate discretization equations, wrt time, at t == 0
    # This is challenging as the only way (to my knowledge) to do this
    # is to identify_variables in the expression, find the (assume only one?)
    # DerivativeVar, and access its get_continuousset_list
    # I would like a get_continuousset_list for discretization equations.
    # Possibly as a ComponentMap, possibly as an attribute of some new 
    # DiscEquation subclass of Constraint
    # Until I have this, this function will only work for backward
    # discretization schemes

    # Also, would like to be able to check for zero degrees of freedom here

    scheme = time.get_discretization_info()['scheme']
    if scheme != 'LAGRANGE-RADAU' and scheme != 'BACKWARD Difference':
        raise NotImplementedError(
            '%s discretization scheme is not supported' % scheme)

    t0 = time.first()
    timelist = list(time)[1:]
    deactivated_dict = deactivate_model_at(model, time, timelist)

    result = solver.solve(model)

    for t in timelist:
        for comp in deactivated_dict[t]:
            comp.activate()

    return result

