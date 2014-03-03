# Copyright (c) 2012, GPy authors (see AUTHORS.txt).
# Licensed under the BSD 3-clause license (see LICENSE.txt)

from transformations import Transformation, Logexp, NegativeLogexp, Logistic, __fixed__, FIXED, UNFIXED
import numpy as np

__updated__ = '2013-12-16'

class HierarchyError(Exception):
    """
    Gets thrown when something is wrong with the parameter hierarchy
    """

def adjust_name_for_printing(name):
    if name is not None:
        return name.replace(" ", "_").replace(".", "_").replace("-", "").replace("+", "").replace("!", "").replace("*", "").replace("/", "")
    return ''

class Observable(object):
    _updated = True
    def __init__(self, *args, **kwargs):
        self._observer_callables_ = []

    def add_observer(self, observer, callble, priority=0):
        self._insert_sorted(priority, observer, callble)
    
    def remove_observer(self, observer, callble=None):
        to_remove = []
        for p, obs, clble in self._observer_callables_:
            if callble is not None:
                if (obs == observer) and (callble == clble):
                    to_remove.append((p, obs, clble))
            else:
                if obs is observer:
                    to_remove.append((p, obs, clble))
        for r in to_remove:
            self._observer_callables_.remove(r)
                
    def _notify_observers(self, which=None, min_priority=None):
        """
        Notifies all observers. Which is the element, which kicked off this 
        notification loop.
        
        NOTE: notifies only observers with priority p > min_priority!
                                                    ^^^^^^^^^^^^^^^^
        
        :param which: object, which started this notification loop
        :param min_priority: only notify observers with priority > min_priority
                             if min_priority is None, notify all observers in order
        """
        if which is None:
            which = self
        if min_priority is None:
            [callble(which) for _, _, callble in self._observer_callables_]
        else:
            for p, _, callble in self._observer_callables_:
                if p <= min_priority:
                    break
                callble(which)

    def _insert_sorted(self, p, o, c):
        ins = 0
        for pr, _, _ in self._observer_callables_:
            if p > pr:
                break
            ins += 1
        self._observer_callables_.insert(ins, (p, o, c))
        
class Pickleable(object):
    def _getstate(self):
        """
        Returns the state of this class in a memento pattern.
        The state must be a list-like structure of all the fields
        this class needs to run.

        See python doc "pickling" (`__getstate__` and `__setstate__`) for details.
        """
        raise NotImplementedError, "To be able to use pickling you need to implement this method"
    def _setstate(self, state):
        """
        Set the state (memento pattern) of this class to the given state.
        Usually this is just the counterpart to _getstate, such that
        an object is a copy of another when calling

            copy = <classname>.__new__(*args,**kw)._setstate(<to_be_copied>._getstate())

        See python doc "pickling" (`__getstate__` and `__setstate__`) for details.
        """
        raise NotImplementedError, "To be able to use pickling you need to implement this method"

#===============================================================================
# Foundation framework for parameterized and param objects:
#===============================================================================

class Parentable(object):
    _direct_parent_ = None
    _parent_index_ = None
        
    def has_parent(self):
        return self._direct_parent_ is not None

    def _notify_parent_change(self):
        for p in self._parameters_:
            p._parent_changed(self)

    def _parent_changed(self):
        raise NotImplementedError, "shouldnt happen, Parentable objects need to be able to change their parent"

    @property
    def _highest_parent_(self):
        if self._direct_parent_ is None:
            return self
        return self._direct_parent_._highest_parent_

    def _notify_parameters_changed(self):
        raise NotImplementedError, "shouldnt happen, abstract superclass"
        
class Nameable(Parentable):
    def __init__(self, name, *a, **kw):
        super(Nameable, self).__init__(*a, **kw)
        self._name = name or self.__class__.__name__

    @property
    def name(self):
        return self._name
    @name.setter
    def name(self, name):
        from_name = self.name
        assert isinstance(name, str)
        self._name = name
        if self.has_parent():
            self._direct_parent_._name_changed(self, from_name)
    def hierarchy_name(self, adjust_for_printing=True):
        if adjust_for_printing: adjust = lambda x: adjust_name_for_printing(x)
        else: adjust = lambda x: x
        if self.has_parent():
            return self._direct_parent_.hierarchy_name() + "." + adjust(self.name)
        return adjust(self.name)


class Gradcheckable(Parentable):
    def __init__(self, *a, **kw):
        super(Gradcheckable, self).__init__(*a, **kw)
    def checkgrad(self, verbose=0, step=1e-6, tolerance=1e-3):
        if self.has_parent():
            return self._highest_parent_._checkgrad(self, verbose=verbose, step=step, tolerance=tolerance)
        return self._checkgrad(self[''], verbose=verbose, step=step, tolerance=tolerance)
    def _checkgrad(self, param):
        raise NotImplementedError, "Need log likelihood to check gradient against"


class Indexable(object):
    def _raveled_index(self):
        raise NotImplementedError, "Need to be able to get the raveled Index"
        
    def _internal_offset(self):
        return 0
    
    def _offset_for(self, param):
        raise NotImplementedError, "shouldnt happen, offset required from non parameterization object?"
    
    def _raveled_index_for(self, param):
        """
        get the raveled index for a param
        that is an int array, containing the indexes for the flattened
        param inside this parameterized logic.
        """
        raise NotImplementedError, "shouldnt happen, raveld index transformation required from non parameterization object?"        
        

class Constrainable(Nameable, Indexable):
    def __init__(self, name, default_constraint=None, *a, **kw):
        super(Constrainable, self).__init__(name=name, *a, **kw)
        self._default_constraint_ = default_constraint
        from index_operations import ParameterIndexOperations
        self.constraints = ParameterIndexOperations()
        self.priors = ParameterIndexOperations()
        if self._default_constraint_ is not None:
            self.constrain(self._default_constraint_)
    
    def _disconnect_parent(self, constr=None):
        if constr is None:
            constr = self.constraints.copy()
        self.constraints.clear()
        self.constraints = constr
        self._direct_parent_ = None
        self._parent_index_ = None
        self._connect_fixes()
        self._notify_parent_change()
        
    #===========================================================================
    # Fixing Parameters:
    #===========================================================================
    def constrain_fixed(self, value=None, warning=True, trigger_parent=True):
        """
        Constrain this paramter to be fixed to the current value it carries.

        :param warning: print a warning for overwriting constraints.
        """
        if value is not None:
            self[:] = value
        self.constrain(__fixed__, warning=warning, trigger_parent=trigger_parent)
        rav_i = self._highest_parent_._raveled_index_for(self)
        self._highest_parent_._set_fixed(rav_i)
    fix = constrain_fixed
    
    def unconstrain_fixed(self):
        """
        This parameter will no longer be fixed.
        """
        unconstrained = self.unconstrain(__fixed__)
        self._highest_parent_._set_unfixed(unconstrained)    
    unfix = unconstrain_fixed
    
    def _set_fixed(self, index):
        if not self._has_fixes(): self._fixes_ = np.ones(self.size, dtype=bool)
        self._fixes_[index] = FIXED
        if np.all(self._fixes_): self._fixes_ = None  # ==UNFIXED
    
    def _set_unfixed(self, index):
        if not self._has_fixes(): self._fixes_ = np.ones(self.size, dtype=bool)
        # rav_i = self._raveled_index_for(param)[index]
        self._fixes_[index] = UNFIXED
        if np.all(self._fixes_): self._fixes_ = None  # ==UNFIXED

    def _connect_fixes(self):
        fixed_indices = self.constraints[__fixed__]
        if fixed_indices.size > 0:
            self._fixes_ = np.ones(self.size, dtype=bool) * UNFIXED
            self._fixes_[fixed_indices] = FIXED
        else:
            self._fixes_ = None
    
    def _has_fixes(self):
        return hasattr(self, "_fixes_") and self._fixes_ is not None

    #===========================================================================
    # Prior Operations
    #===========================================================================
    def set_prior(self, prior, warning=True, trigger_parent=True):
        repriorized = self.unset_priors()
        self._add_to_index_operations(self.priors, repriorized, prior, warning)
    
    def unset_priors(self, *priors):
        return self._remove_from_index_operations(self.priors, priors)
    
    def log_prior(self):
        """evaluate the prior"""
        if self.priors.size > 0:
            x = self._get_params()
            return reduce(lambda a, b: a + b, [p.lnpdf(x[ind]).sum() for p, ind in self.priors.iteritems()], 0)
        return 0.
    
    def _log_prior_gradients(self):
        """evaluate the gradients of the priors"""
        if self.priors.size > 0:
            x = self._get_params()
            ret = np.zeros(x.size)
            [np.put(ret, ind, p.lnpdf_grad(x[ind])) for p, ind in self.priors.iteritems()]
            return ret
        return 0.
        
    #===========================================================================
    # Constrain operations -> done
    #===========================================================================

    def constrain(self, transform, warning=True, trigger_parent=True):
        """
        :param transform: the :py:class:`GPy.core.transformations.Transformation`
                          to constrain the this parameter to.
        :param warning: print a warning if re-constraining parameters.

        Constrain the parameter to the given
        :py:class:`GPy.core.transformations.Transformation`.
        """
        if isinstance(transform, Transformation):
            self._set_params(transform.initialize(self._get_params()), trigger_parent=trigger_parent)
        reconstrained = self.unconstrain()
        self._add_to_index_operations(self.constraints, reconstrained, transform, warning)

    def unconstrain(self, *transforms):
        """
        :param transforms: The transformations to unconstrain from.

        remove all :py:class:`GPy.core.transformations.Transformation`
        transformats of this parameter object.
        """
        return self._remove_from_index_operations(self.constraints, transforms)
    
    def constrain_positive(self, warning=True, trigger_parent=True):
        """
        :param warning: print a warning if re-constraining parameters.

        Constrain this parameter to the default positive constraint.
        """
        self.constrain(Logexp(), warning=warning, trigger_parent=trigger_parent)

    def constrain_negative(self, warning=True, trigger_parent=True):
        """
        :param warning: print a warning if re-constraining parameters.

        Constrain this parameter to the default negative constraint.
        """
        self.constrain(NegativeLogexp(), warning=warning, trigger_parent=trigger_parent)

    def constrain_bounded(self, lower, upper, warning=True, trigger_parent=True):
        """
        :param lower, upper: the limits to bound this parameter to
        :param warning: print a warning if re-constraining parameters.

        Constrain this parameter to lie within the given range.
        """
        self.constrain(Logistic(lower, upper), warning=warning, trigger_parent=trigger_parent)

    def unconstrain_positive(self):
        """
        Remove positive constraint of this parameter.
        """
        self.unconstrain(Logexp())

    def unconstrain_negative(self):
        """
        Remove negative constraint of this parameter.
        """
        self.unconstrain(NegativeLogexp())

    def unconstrain_bounded(self, lower, upper):
        """
        :param lower, upper: the limits to unbound this parameter from

        Remove (lower, upper) bounded constrain from this parameter/
        """
        self.unconstrain(Logistic(lower, upper))
    
    def _parent_changed(self, parent):
        from index_operations import ParameterIndexOperationsView
        self.constraints = ParameterIndexOperationsView(parent.constraints, parent._offset_for(self), self.size)
        self.priors = ParameterIndexOperationsView(parent.priors, parent._offset_for(self), self.size)
        self._fixes_ = None
        for p in self._parameters_:
            p._parent_changed(parent)

    def _add_to_index_operations(self, which, reconstrained, transform, warning):
        if warning and reconstrained.size > 0:
            # TODO: figure out which parameters have changed and only print those
            print "WARNING: reconstraining parameters {}".format(self.parameter_names() or self.name)
        which.add(transform, self._raveled_index())

    def _remove_from_index_operations(self, which, transforms):
        if len(transforms) == 0:
            transforms = which.properties()
        removed = np.empty((0,), dtype=int)
        for t in transforms:
            unconstrained = which.remove(t, self._raveled_index())
            removed = np.union1d(removed, unconstrained)
            if t is __fixed__:
                self._highest_parent_._set_unfixed(unconstrained)
        
        return removed

class OptimizationHandlable(Constrainable, Observable):
    def _get_params_transformed(self):
        # transformed parameters (apply transformation rules)
        p = self._get_params()
        [np.put(p, ind, c.finv(p[ind])) for c, ind in self.constraints.iteritems() if c != __fixed__]
        if self._has_fixes():
            return p[self._fixes_]
        return p
    
    def _set_params_transformed(self, p):
        # inverse apply transformations for parameters and set the resulting parameters
        self._set_params(self._untransform_params(p))
    
    def _size_transformed(self):
        return self.size - self.constraints[__fixed__].size
    
    def _untransform_params(self, p):
        p = p.copy()
        if self._has_fixes(): tmp = self._get_params(); tmp[self._fixes_] = p; p = tmp; del tmp
        [np.put(p, ind, c.f(p[ind])) for c, ind in self.constraints.iteritems() if c != __fixed__]
        return p
    
    def _get_params(self):
        # don't overwrite this anymore!
        if not self.size:
            return np.empty(shape=(0,), dtype=np.float64)
        return np.hstack([x._get_params() for x in self._parameters_ if x.size > 0])

    def _set_params(self, params, trigger_parent=True):
        # don't overwrite this anymore!
        raise NotImplementedError, "This needs to be implemented in Param and Parametrizable"
    
    #===========================================================================
    # Optimization handles:
    #===========================================================================
    def _get_param_names(self):
        n = np.array([p.hierarchy_name() + '[' + str(i) + ']' for p in self.flattened_parameters for i in p._indices()])
        return n
    def _get_param_names_transformed(self):
        n = self._get_param_names()
        if self._has_fixes():
            return n[self._fixes_]
        return n

    #===========================================================================
    # Randomizeable
    #===========================================================================
    def randomize(self):
        """
        Randomize the model.
        Make this draw from the prior if one exists, else draw from N(0,1)
        """
        # first take care of all parameters (from N(0,1))
        # x = self._get_params_transformed()
        x = np.random.randn(self._size_transformed())
        x = self._untransform_params(x)
        # now draw from prior where possible
        [np.put(x, ind, p.rvs(ind.size)) for p, ind in self.priors.iteritems() if not p is None]
        self._set_params(x)
        # self._set_params_transformed(self._get_params_transformed()) # makes sure all of the tied parameters get the same init (since there's only one prior object...)

class Parameterizable(OptimizationHandlable):
    def __init__(self, *args, **kwargs):
        super(Parameterizable, self).__init__(*args, **kwargs)
        from GPy.core.parameterization.lists_and_dicts import ArrayList
        _parameters_ = ArrayList()
        self._added_names_ = set()
    
    def parameter_names(self, add_self=False, adjust_for_printing=False, recursive=True):
        if adjust_for_printing: adjust = lambda x: adjust_name_for_printing(x)
        else: adjust = lambda x: x
        if recursive: names = [xi for x in self._parameters_ for xi in x.parameter_names(add_self=True, adjust_for_printing=adjust_for_printing)]
        else: names = [adjust(x.name) for x in self._parameters_]
        if add_self: names = map(lambda x: adjust(self.name) + "." + x, names)
        return names
    
    @property
    def num_params(self):
        return len(self._parameters_)
    
    def _add_parameter_name(self, param):
        pname = adjust_name_for_printing(param.name)
        # and makes sure to not delete programmatically added parameters
        if pname in self.__dict__:
            if not (param is self.__dict__[pname]):
                if pname in self._added_names_:
                    del self.__dict__[pname]
                    self._add_parameter_name(param)
        elif pname not in dir(self):
            self.__dict__[pname] = param
            self._added_names_.add(pname)
            
    def _remove_parameter_name(self, param=None, pname=None):
        assert param is None or pname is None, "can only delete either param by name, or the name of a param"
        pname = adjust_name_for_printing(pname) or adjust_name_for_printing(param.name)
        if pname in self._added_names_:
            del self.__dict__[pname]
            self._added_names_.remove(pname)
        self._connect_parameters()

    def _name_changed(self, param, old_name):
        self._remove_parameter_name(None, old_name)
        self._add_parameter_name(param)
            
    def _collect_gradient(self, target):
        import itertools
        [p._collect_gradient(target[s]) for p, s in itertools.izip(self._parameters_, self._param_slices_)]

    def _set_params(self, params, trigger_parent=True):
        import itertools
        [p._set_params(params[s], trigger_parent=False) for p, s in itertools.izip(self._parameters_, self._param_slices_)]
        if trigger_parent: min_priority = None
        else: min_priority = -np.inf
        self._notify_observers(None, min_priority)

    def _set_gradient(self, g):
        import itertools
        [p._set_gradient(g[s]) for p, s in itertools.izip(self._parameters_, self._param_slices_)]
        
    def add_parameter(self, param, index=None):
        """
        :param parameters:  the parameters to add
        :type parameters:   list of or one :py:class:`GPy.core.param.Param`
        :param [index]:     index of where to put parameters


        Add all parameters to this param class, you can insert parameters
        at any given index using the :func:`list.insert` syntax
        """
        # if param.has_parent():
        #    raise AttributeError, "parameter {} already in another model, create new object (or copy) for adding".format(param._short())
        if param in self._parameters_ and index is not None:
            self.remove_parameter(param)
            self.add_parameter(param, index)
        elif param not in self._parameters_:
            if param.has_parent():
                parent = param._direct_parent_
                while parent is not None:
                    if parent is self:
                        raise HierarchyError, "You cannot add a parameter twice into the hirarchy"
                    parent = parent._direct_parent_
                param._direct_parent_.remove_parameter(param)
            # make sure the size is set
            if index is None:
                self.constraints.update(param.constraints, self.size)
                self.priors.update(param.priors, self.size)
                self._parameters_.append(param)
            else:
                start = sum(p.size for p in self._parameters_[:index])
                self.constraints.shift_right(start, param.size)
                self.priors.shift_right(start, param.size)
                self.constraints.update(param.constraints, start)
                self.priors.update(param.priors, start)
                self._parameters_.insert(index, param)
            
            param.add_observer(self, self._pass_through_notify_observers, -np.inf)
            
            self.size += param.size

            self._connect_parameters()
            self._notify_parent_change()
            self._connect_fixes()
        else:
            raise RuntimeError, """Parameter exists already added and no copy made"""


    def add_parameters(self, *parameters):
        """
        convenience method for adding several
        parameters without gradient specification
        """
        [self.add_parameter(p) for p in parameters]

    def remove_parameter(self, param):
        """
        :param param: param object to remove from being a parameter of this parameterized object.
        """
        if not param in self._parameters_:
            raise RuntimeError, "Parameter {} does not belong to this object, remove parameters directly from their respective parents".format(param._short())
        
        start = sum([p.size for p in self._parameters_[:param._parent_index_]])
        self._remove_parameter_name(param)
        self.size -= param.size
        del self._parameters_[param._parent_index_]
        
        param._disconnect_parent()
        param.remove_observer(self, self._pass_through_notify_observers)
        self.constraints.shift_left(start, param.size)
        
        self._connect_fixes()
        self._connect_parameters()
        self._notify_parent_change()
        
        parent = self._direct_parent_
        while parent is not None:
            parent._connect_fixes()
            parent._connect_parameters()
            parent._notify_parent_change()
            parent = parent._direct_parent_
        
    def _connect_parameters(self):
        # connect parameterlist to this parameterized object
        # This just sets up the right connection for the params objects
        # to be used as parameters
        # it also sets the constraints for each parameter to the constraints 
        # of their respective parents 
        if not hasattr(self, "_parameters_") or len(self._parameters_) < 1:
            # no parameters for this class
            return
        sizes = [0]
        self._param_slices_ = []
        for i, p in enumerate(self._parameters_):
            p._direct_parent_ = self
            p._parent_index_ = i
            sizes.append(p.size + sizes[-1])
            self._param_slices_.append(slice(sizes[-2], sizes[-1]))
            self._add_parameter_name(p)

    #===========================================================================
    # notification system
    #===========================================================================
    def _parameters_changed_notification(self, which):
        self.parameters_changed()
    def _pass_through_notify_observers(self, which):
        self._notify_observers(which)
    
    #===========================================================================
    # TODO: not working yet
    #===========================================================================
    def copy(self):
        """Returns a (deep) copy of the current model"""
        import copy
        from .index_operations import ParameterIndexOperations, ParameterIndexOperationsView
        from .lists_and_dicts import ArrayList

        dc = dict()
        for k, v in self.__dict__.iteritems():
            if k not in ['_direct_parent_', '_parameters_', '_parent_index_', '_observer_callables_'] + self.parameter_names():
                if isinstance(v, (Constrainable, ParameterIndexOperations, ParameterIndexOperationsView)):
                    dc[k] = v.copy()
                else:
                    dc[k] = copy.deepcopy(v)
            if k == '_parameters_':
                params = [p.copy() for p in v]
            
        dc['_direct_parent_'] = None
        dc['_parent_index_'] = None
        dc['_observer_callables_'] = []
        dc['_parameters_'] = ArrayList()
        dc['constraints'].clear()
        dc['priors'].clear()
        dc['size'] = 0

        s = self.__new__(self.__class__)
        s.__dict__ = dc
        
        for p in params:
            import ipdb;ipdb.set_trace()
            s.add_parameter(p)
        
        return s
        
    def parameters_changed(self):
        """
        This method gets called when parameters have changed.
        Another way of listening to param changes is to
        add self as a listener to the param, such that
        updates get passed through. See :py:function:``GPy.core.param.Observable.add_observer``
        """
        pass

