#Copyright (c) 2008 Erik Tollerud (etolleru@uci.edu) 

"""
This module contains objects and functions for generating catalogs of objects
where derived quantities are dynamically updated as they are changed.

The basic idea is a tree/DAG with the root typically a Catalog object

TODO: modules to also dynamically update via a web server.
"""

from __future__ import division
from math import pi
import numpy as np

try:
    #requires Python 2.6
    from abc import ABCMeta
    from abc import abstractmethod
    from abc import abstractproperty
    from collections import Sequence,MutableSequence
except ImportError: #support for earlier versions
    abstractmethod = lambda x:x
    abstractproperty = property
    ABCMeta = type
    class MutableSequence(object):
        __slots__=('__weakref__',) #support for weakrefs as necessary
    class Sequence(object):
        __slots__=('__weakref__',) #support for weakrefs as necessary
        
class CycleError(Exception):
    """
    This exception indicates a cycle was detected in some graph-like structure
    """
    def __init__(self,message):
        super(CycleError,self).__init__(message)
        
class SourceDataError(Exception):
    """
    This exception indicates a problem occured while trying to retrieve 
    external Source-related data
    """
    def __init__(self,message):
        super(SourceDataError,self).__init__(message)



#<-------------------------Node/Graph objects and functions-------------------->
class CatalogNode(object):
    """
    This Object is the superclass for all elements/nodes of a catalog.  
    This is an abstract class that must have its initializer overriden.
    
    Subclasses must call super(Subclass,self).__init__(parent) in their __init__
    """
    
    __metaclass__ = ABCMeta
    __slots__=('_parent','_children','__weakref__')
    
    @abstractmethod
    def __init__(self,parent):
        self._children = []
        self._parent = None
        
        if parent is not None:
            self.parent = parent
            
    def __getstate__(self):
        return {'_parent':self._parent,'_children':self._children}
    def __setstate__(self,d):
        self._parent = d['_parent']
        self._children = d['_children']
        
    def _cycleCheck(self,source):
        """
        call this from a child object with the child as the Source to check 
        for cycles in the graph
        """
        if source is self:
            raise CycleError('cycle detected in graph assignment attempt')
        if self._parent is None:
            return None
        else:
            return self.parent._cycleCheck(source)
            
    def _getParent(self):
        return self._parent
    def _setParent(self,val):
        
        if val is not None:
            val._cycleCheck(self) #TODO:test performance effect/make disablable
            val._children.append(self)
            
        if self._parent is not None:
            self._parent._children.remove(self)
        self._parent = val
        
    parent=property(_getParent,_setParent)
    
    
    @property
    def children(self):
        return tuple(self._children)
    
    def reorderChildren(self,neworder):
        """
        Change the order pf the children
        
        neworder can be either a sequence of  indecies (e.g. to reorder
        [a,b,c] to [c,a,b], neworder would be [2,0,1]), the string
        'reverse', or a function like the cmp keyword as would appear
        in the sorted builtin (can be None to do default sorting). 
        """
        if neworder == 'reverse':
            self._children.reverse()
        elif callable(neworder):
            self._children.sort(cmp=neworder)
        else: #TODO:faster way to do this if necessary?
            if len(neworder) != len(self._children):
                raise ValueError('input sequence does not have correct number of elements')
            
            added = np.zeros(len(self._children),dtype=bool)
            newl = []
            for i in neworder:
                if added[i]:
                    raise ValueError('input sequence has repeats')
                newl.append(self._children[i])
                added[i] = True
                
    @property
    def nnodes(self):
        """
        this gives the number of total nodes at this point in the tree
        (including self - e.g. a leaf in the tree returns 1)
        """
        return sum([c.nnodes for c in self._children],1)
        
    
    def visit(self,func,traversal='postorder',filter=False):
        """
        This function walks through the object and all its children, 
        executing func(CatalogNode)
        
        traversal is the traversal order of the tree - can be:
        *'preorder',
        *'postorder'
        *an integer indicating at which index the root should 
        be evaluated (pre/post are 0/-1)
        * a float between -1 and 1 indicating where the root should 
        be evaluated as a fraction
        *'level'/'breathfirst' 
        
        filter can be:
        *False: process and return all values
        *a callable: is called as g(node) and if it returns False, the
        node will not be processed nor put in the (also ignores anything 
        that returns None)
        *any other: if the node returns this value on processing, it will
                    not be returned
        """
        if callable(filter):
            func = lambda *args,**kwargs:func(*args,**kwargs) if filter(args[0]) else None
            filter = None
        
        if type(traversal) is int:
            retvals = []
            doroot = True
            for i,c in enumerate(self._children):
                if i == traversal:
                    retvals.append(func(self))
                    doroot = False
                retvals.extend(c.visit(func,traversal))
            if doroot:
                retvals.append(func(self))
        elif type(traversal) is float:
            retvals = []
            doroot = True
            travi = int(traversal*self._children)
            for i,c in enumerate(self._children):
                if i == travi:
                    retvals.append(func(self))
                    doroot = False
                retvals.extend(c.visit(func,traversal))
            if doroot:
                retvals.append(func(self))
        elif traversal is None: #None means postorder
            retvals = []
            for c in self._children:
                retvals.extend(c.visit(func,traversal))
            retvals.append(func(self))    
        elif traversal == 'postorder':
            retvals = self.visit(func,None)
        elif traversal == 'preorder':
            retvals = self.visit(func,0)
        elif traversal == 'level' or traversal == 'breadthfirst':
            from collections import deque
            
            retvals=[]
            q = deque()
            q.append(self)
            while len(q)>0:
                elem = q.popleft()
                retvals.append(func(elem))
                q.extend(elem._children)
        else:
            raise ValueError('unrecognized traversal type')
        
        if filter is not False:
            retvals = [v for v in retvals if v is not filter]
        return retvals
    
    def save(self,file,savechildren=True):
        """
        save the file name or file-like object
        
        savechildren means the children of this node will be saved
        
        Note that the parent and everything above this point will NOT be
        saved (when reloaded the parent will be None)
        """
        import cPickle
        
        oldpar = self._parent
        self._parent = None
        
        oldchildren = self._children
        if not savechildren:
            self._children = []
            
        try:
            if isinstance(file,basestring):
                #filename
                with open(file,'w') as f:
                    return cPickle.dump(self,f)
            else:
                return cPickle.load(file)
        finally:
            self._parent = oldpar
            self._children = oldchildren
        
    
    @staticmethod
    def load(file):
        """
        load the file name or file-like object
        """
        import cPickle
        if isinstance(file,basestring):
            #filename
            with open(file,'r') as f:
                return cPickle.load(f)
        else:
            return cPickle.load(file)
    
class FieldNode(CatalogNode,Sequence):
    """
    A node in the catalog that has Fields.  This is an abstract class that 
    must have its initializer overriden.
    
    Note that for these subclasses, attribute access (e.g. node.fieldname) 
    accesses the Field object, while mapping or sequence-style access 
    (e.g node['fieldname'] or node[1])  directly accesses the current value
    of the field (or None if there is no value).  This means that 
    iterating over the object will also give values.  To iterate over
    the Field objects, use the fields() method.
    """
    __slots__=('_fieldnames',)
    
    @abstractmethod
    def __init__(self,parent):
        super(FieldNode,self).__init__(parent)
        self._fieldnames = []
        
    def __getstate__(self):
        d = super(FieldNode,self).__getstate__()
        d['_fieldnames'] = self._fieldnames
        for n in self._fieldnames:
            val = getattr(self,n)
            if isinstance(val,DerivedValue):
                from warnings import warn
                warn("cannot pickle derived values that aren't part of a structure - skipping %s"%val._str)
            else:
                d[n] = val
        return d
    def __setstate__(self,d):
        super(FieldNode,self).__setstate__(d)
        self._fieldnames = d['_fieldnames']
        for n in self._fieldnames:
            fi = d[n]
            setattr(self,n,fi)
            fi.node = self
            
    def addField(self,field):
        if not isinstance(field,Field):
            raise ValueError('input value is not a Field')
        if field.name in self._fieldnames:
            raise ValueError('Field name "%s" already present'%field.name)
        setattr(self,field.name,field)
        if field.node is not None:
            raise ValueError('a Field can only reside in one Node')
        field.node = self
        self._fieldnames.append(field.name)
        
    def delField(self,fieldname):
        try:
            self._fieldnames.remove(fieldname)
            if hasattr(self.__class__,fieldname):
                setattr(self,fieldname,None)
            else:
                delattr(self,fieldname)
        except ValueError:
            raise KeyError('Field "%s" not found'%fieldname)
        
    def fields(self):
        """
        this yields an iterator over all of the Field objects (rather than 
        their values, as regular sequence access does)
        """
        for n in self._fieldnames:
            yield getattr(self,n)
            
    def __str__(self):
        return 'FieldNode with fields %s'%self._fieldnames
        
    def __cmp__(self,other):
        try:
            return cmp(list(self),list(other))
        except TypeError:
            return 1
        
    def __len__(self):
        return len(self._fieldnames)
    
    def __contains__(self,key):
        return key in self._fieldnames
        
    def __getitem__(self,key):
        if key not in self._fieldnames:
            try:
                key = self._fieldnames[key]
            except (IndexError,TypeError):
                raise IndexError('Field "%s" not found'%key)
        try:
            return getattr(self,key)()
        except IndexError: #field empty
            return None
    
    def __setitem__(self,key,val):
        if key not in self._fieldnames:
            try:
                key = self._fieldnames[key]
            except (IndexError,TypeError):
                raise IndexError('Field "%s" not found'%key)
        field = getattr(self,key)
        field.currentobj = val
    
    def __delitem__(self,key):
        self.delField(key)
        
    @property
    def fieldnames(self):
        return tuple(self._fieldnames)
    
    def extractField(self,*args,**kwargs):
        """
        walk through the tree starting from this object
        
        see FieldNode.extractFieldFromNode for arguments
        """
        return FieldNode.extractFieldAtNode(self,*args,**kwargs)
    
    @staticmethod
    def extractFieldAtNode(node,fieldname,traversal='postorder',missing=False,dtype=None):
        """
        this will walk through the tree starting from the Node in the first
        argument and generate an array of the values for the 
        specified fieldname
        
        missing determines the behavior in the event that a field is not 
        present (or a non FieldNode is encounterd) it can be:
        *'exception': raise a KeyError if the field is missing or a 
        TypeError if  
        *'skip': do not include this object in the final array
        *'0'/False: 
        
        traversal is of an argument like that for CatalogNode.visit
        """
        #TODO: optimize with array size knowledge ?
        if missing == 'exception':
            filter = False
            def vfunc(node):
                return node[fieldname]
        elif missing == 'skip':
            filter = None
            def vfunc(node):
                try:
                    return node[fieldname]
                except (KeyError,IndexError,TypeError):
                    return None
        elif not missing:
            filter = False
            def vfunc(node):
                try:
                    return node[fieldname]
                except (KeyError,IndexError,TypeError):
                    return None
        else:
            raise ValueError('Unrecognized value for what to do with missing fields')
            
        lst = node.visit(vfunc,traversal=traversal,filter=filter)
        
        if dtype is None:
            try:
                #TODO: test this or be smarter
                return np.array(lst,dtype=node.type)
            except:
                pass
        
        return np.array(lst,dtype=dtype) 

def generate_pydot_graph(node,graphfields=True):
    """
    this function will generate a pydot.Dot object representing the supplied 
    node and its children.  Note that the pydot package must be installed
    installed for this to work
    
    graphfields includes the fields as a record style graphviz graph
    """
    import pydot
    
    nodeidtopdnode={}
    def visitfunc(node):
        pdnode = pydot.Node(id(node),label=str(node))
        if isinstance(node,FieldNode):
            if graphfields:
                pdnode.set_shape('record')
                fieldstr = '|'.join([f.strCurr().replace(':',':') for f in node.fields()])
                pdnode.set_label('"{%s| | %s}"'%(node,fieldstr))
            else:
                pdnode.set_shape('box')
        nodeidtopdnode[id(node)] = pdnode
        try:
            edge = pydot.Edge(nodeidtopdnode[id(node.parent)],pdnode)
        except KeyError:
            edge = None
        return pdnode,edge
    nelist = node.visit(visitfunc,traversal='preorder')
    
    g = pydot.Dot()
    g.add_node(nelist[0][0])
    for node,edge in nelist[1:]:
        g.add_node(node)
        g.add_edge(edge)
        
    return g

#<----------------------------node attribute types----------------------------->    
 
class Field(MutableSequence):
    """
    This class represents an attribute/characteristic/property of the
    FieldNode it is associated with.  It stores the current value
    as well as all the other possible values.

    The values, sources, and default properties will return the actual values 
    contained in the FieldValues, while currentobj and iterating 
    over the Field will return FieldValue objects.  Calling the 
    Field (no arguments) will return the current value
    
    usedef specified if the default should be set -- if True, defaultval will 
    be used, if None, a None defaultval will be ignored but any other
    will be recognizd, and if False, no default will be set
    """
    __slots__=('_name','_type','_vals','_nodewr','_notifywrs')
    
    def __init__(self,name,type=None,defaultval=None,usedef=None):
        """
        The field must have a name, and can optionally be given a type
        """        
        self._name = name
        self._vals = []
        self._type = type
        self._notifywrs = None
        self._nodewr = None
        
        if usedef or (usedef is None and defaultval is not None):
            self.default = defaultval
            
    def __getstate__(self):
        return {'_name':self._name,'_type':self._type,'_vals':self._vals}
    def __setstate__(self,d):
        self._name = d['_name']
        self._type = d['_type']
        self._vals = d['_vals']
        self._notifywrs = None
        self._nodewr = None
        #notifiers should late-attach when values are first accessed, and  
        #the Node does it's own attaching
        
    def __call__(self):
        return self.currentobj.value
    def __len__(self):
        return len(self._vals)
    def __contains__(self,val):
        #TODO: optimize!
        try:
            self[val]
            return True
        except (KeyError,IndexError):
            return False
    
    def __str__(self):
        return 'Field %s:[%s]'%(self._name,', '.join([str(v) for v in self._vals]))
    
    def strCurr(self):
        """
        returns a string with the current value instead of the list of 
        values (the behavior of str(Field_obj)
        """
        try:
            return 'Field %s: %s'%(self.name,self())
        except IndexError:
            return 'Field %s empty'%self.name
    
    def _checkConvInVal(self,val,dosrccheck=True):
        """
        auto-converts tuples to ObservedValues
        #TODO: auto-convert callables with necessary information to derivedvalues
        
        dosrccheck = True -> check if source is present
        dosrccheck = string/Source -> ensure that value matches specified 
        string/Source
        dosrcchecj = False -> do nothing but convert
        """
        
        if isinstance(val,tuple) and self.type is not tuple:
            val = ObservedValue(*val)   
        
        if not (isinstance(val,FieldValue) or (hasattr(val,'source') and hasattr(val,'value'))):
            raise TypeError('Input %s not FieldValue-compatible'%str(val))
        
        if dosrccheck:
            if isinstance(dosrccheck,Source):
                s = dosrccheck
                if val.source != s:
                    raise ValueError('Input %s does not match expected %s' %(val.source,s))
            elif isinstance(dosrccheck,basestring):
                s = Source(dosrccheck)
                if val.source != s:
                    raise ValueError('Input %s does not match expected %s' %(val.source,s))
            else:
                s = None
                for v in self._vals:
                    if v.source == val.source:
                        raise ValueError('value with %s already present in Field'%v.source)
        
        val.checkType(self.type)
        
        if isinstance(val,DerivedValue):
            if val.field is not None:
                raise ValueError('DerivedValues can only reside in a single field for dependencies')
            val.field = self
        return val
    
    def notifyValueChange(self,oldval=None,newval=None):
        """
        notifies all registered functions that the value in this 
        field has changed
        
        (see registerNotifier)
        """
        #TODO: optimize better
        if self._notifywrs is not None:
            deadrefs=[]
            for i,wr in enumerate(self._notifywrs):
                callobj = wr()
                if callobj is None:
                    deadrefs.append(i)
                else:
                    callobj(oldval,newval)
            
            if len(deadrefs) == len(self._notifywrs):
                self._notifywrs = None
            else:
                for i in reversed(deadrefs):
                    del self._notifywrs[i]
    
    def registerNotifier(self,notifier,checkargs=True):
        """
        this registers a function to be called when the value changes or is 
        otherwise rendered invalid.  The notifier will be called as
        notifier(oldvalobj,newvalobj) BEFORE the value change is finalized.
        """
        from weakref import ref
        
        if not callable(notifier):
            raise TypeError('notifier not a callable')
        if checkargs:
            import inspect
            if len(inspect.getargspec(notifier)[0]) == 2:
                raise TypeError('notifier does not have 2 arguments')
        if self._notifywrs is None:
            self._notifywrs = []
        self._notifywrs.append(ref(notifier))
    
    def __getitem__(self,key):
        if type(key) is int:
            return self._vals[key]
        else:
            if key is None:
                key = Source(None)
            elif isinstance(key,basestring):
                if 'derived' in key:
                    #TODO: replace with only 1 if too slow?
                    key = key.replace('derived','')
                    if key == '':
                        der = 0
                    else:
                        der = int(key)
                    ders = [v for v in self._vals if isinstance(v,DerivedValue)]
                    if len(ders) <= der:
                        raise IndexError('field has only %i DerivedValues' % len(ders))
                    return ders[der]
                key = Source(key)
            if isinstance(key,Source):
                for v in self._vals:
                    if v.source == key:
                        return v
                raise KeyError('Field does not have %s'%key)
            else:
                raise TypeError('key not a Source key or index')
            
    def __setitem__(self,key,val):
        if type(key) is int or key in self:
            i = key if type(key) is int else self._vals.index(self[key])
            val = self._checkConvInVal(val,self._vals[i].source)
            if i == 0:
                self.notifyValueChange(self._vals[0],val)
            self._vals[i] = val
        else:
            if isinstance(key,Source):
                s = key
            elif isinstance(key,basestring):
                s = Source(key)
            elif key is None:
                s = None
            else:
                raise TypeError('specified key not a recognized Source')
            val = self._checkConvInVal(val if s is None else ObservedValue(val,s))
            self._vals.append(val)
        
    def __delitem__(self,key):
        if type(key) is int: 
            i = key
        else:
            i = self._vals.index(self[key])
            
        if i == 0 and self._notifywrs is not None:
            self.notifyValueChange(self._vals[0],self._vals[1] if len(self._vals)>1 else None)
        del self._vals[i]
            
    def insert(self,key,val):
        val = self._checkConvInVal(val)
        
        if type(key) is int:
            i = key
        else:
            i = self._vals.index(self[key])
        if i == 0 and self._notifywrs is not None:
            self.notifyValueChange(val,self._vals[0] if len(self._vals)>0 else None)
        self._vals.insert(i,val)
        
    @property
    def name(self):
        return self._name
    
    def _getNode(self):
        return None if self._nodewr is None else self._nodewr()
    def _setNode(self,val):
        if val is None:
            self._nodewr = None
        else:
            from weakref import ref
            self._nodewr = ref(val)
        for d in self.derived:
            d.sourcenode = val
    node = property(_getNode,_setNode,doc='the node to which this Field belongs')
    
    def _getType(self):
        return self._type
    def _setType(self,newtype):
        if newtype is None:
            self._type = None
        else:
            for v in self._vals:
                v.checkType(newtype)
            self._type = newtype
    type = property(_getType,_setType,doc="""
    Selects the type to enforce for this field.  
    if None, no type-checking will be performed
    if a numpy dtype, the value must be an array matching the dtype
    can also be a sequence of types (accepts all) or a function
    that will be called directly on the function that returns True if
    the type is valid
    """)
    #TODO:default should be Catalog-level?    
    def _getDefault(self):
        return self[None].value
    def _setDefault(self,val):
        self[None] = ObservedValue(val,None)
    def _delDefault(self):
        del self[None]
    default = property(_getDefault,_setDefault,_delDefault,"""
    The default value is the FieldValue that has a
    the None Source
    """)
    
    def _getCurr(self):
        try:
            return self._vals[0]
        except IndexError:
            raise IndexError('Field %s empty'%self._name)
    def _setCurr(self,val):
        oldcurr = self._vals[0] if len(self._vals)>0 else None
        try:
            i = self._vals.index(self[val])
            valobj = self._vals.pop(i)
        except (KeyError,IndexError,TypeError):
            valobj = self._checkConvInVal(val)
        self.notifyValueChange(oldcurr,valobj)
        self._vals.insert(0,valobj)
    currentobj = property(_getCurr,_setCurr)
    
    @property
    def values(self):
        return [v() for v in self._vals]
    
    @property
    def sources(self):
        return [v.source for v in self._vals]
    
    @property
    def sourcenames(self):
        return [str(v.source) for v in self._vals]
    
    @property
    def observed(self):
        """
        returns a list of all the ObservedValue objects except the default
        """
        return [o for o in self if (isinstance(o,ObservedValue) and o.source._str != 'None')]
        
    @property
    def derived(self):
        """
        returns a list of all the DerivedValue objects
        """
        return [o for o in self if isinstance(o,DerivedValue)]
    
class SEDField(Field):
    """
    This field represents the Spectral Energy Distribution of this object - 
    e.g. a collection of Spectra or Photometric measurements
    """
    
    
    __slots__ = ['_maskedsedvals','_unit']
    
    def __init__(self,name='SED',unit='angstroms',type=None,defaultval=None, usedef=None):
        from .spec import Spectrum,HasSpecUnits
        from .phot import PhotObservation
        
        super(SEDField,self).__init__(name)
        
        
        
        self._type = tuple((Spectrum,PhotObservation))
        self._maskedsedvals = set()
        unittuple = HasSpecUnits.strToUnit(unit)
        self._unit = unittuple[0]+'-'+unittuple[1]
        
        if type is not None and set(type) != set(self._type):
            raise ValueError("SEDFields only accept Spectrum and PhotObservation objects - can't set type")
        
        if defaultval:
            self[None] = defaultval
        
        
    def __getstate__(self):
        d = super(SEDField,self).__getstate__()
        d['_maskedsedvals'] = self._maskedsedvals
        d['_unit'] = self._unit
        return d
    
    def __setstate__(self,d):
        super(SEDField,self).__setstate__(d)
        self._maskedsedvals = d['_maskedsedvals']
        self._unit = d['_unit']
        
    def __call__(self):
        return self.getFullSED()
    
    def __setitem__(self,key,val):
        """
        allow self['source'] = (bands,values) syntax
        """
        from .phot import PhotObservation
        
        if isinstance(val,tuple) and len(val) == 2:
            return super(SEDField,self).__setitem__(key,PhotObservation(*val))
        else:
            return super(SEDField,self).__setitem__(key,val)
        
    @property
    def type(self):
        return self._type
    
    @property
    def default(self):
        return self()
    
    @property
    def specs(self):
        from .spec import Spectrum
        return [o for i,o in enumerate(self.values) if isinstance(o,Spectrum) if i not in self._maskedsedvals]
    @property
    def specsources(self):
        from .spec import Spectrum
        return [self.sources[i] for i,o in enumerate(self.values) if isinstance(o,Spectrum) if i not in self._maskedsedvals]
    
    @property
    def phots(self):
        from .phot import PhotObservation
        return [o for i,o in enumerate(self.values) if isinstance(o,PhotObservation) if i not in self._maskedsedvals] 
    @property
    def photsources(self):
        from .phot import PhotObservation
        return [self.sources[i] for i,o in enumerate(self.values) if isinstance(o,PhotObservation) if i not in self._maskedsedvals] 
    
    def _getUnit(self):
        return self._unit
    def _setUnit(self,val):
        from .spec import HasSpecUnits
        #this checks to make sure the unit is valid
        val = HasSpecUnits.strToUnit(val)
        val = val[0]+'-'+val[1]
        
        oldu = self._unit
        try:
            for obj in self:
                if hasattr(obj,'unit'):
                    obj.unit = val
            self._unit = val
        except:
            for obj in self:
                obj.unit = oldu
            raise
    unit = property(_getUnit,_setUnit,doc="""
    The units to use in the objects of this SED - see 
    astropysics.spec.HasSpecUnits for valid units
    """)
    
    def getMasked(self):
        """
        return a copy of the values masked from the full SED
        """
        return tuple(sorted(self._maskedsedvals))
    def mask(self,val):
        """
        mask the value (either index or source name) to not appear in the
        full SED
        """
        if isinstance(val,int):
            self._maskedsedvals.add(val)
        else:
            self._maskedsedvals.add(self.index(val))
    def unmask(self,val):
        """
        unmask the value (either index or source name) to appear in the
        full SED
        """
        if isinstance(val,int):
            self._maskedsedvals.remove(val)
        else:
            self._maskedsedvals.remove(self.index(val))
    def unmaskAll(self):
        """
        unmask all values (all appear in full SED)
        """
        self._maskedsedvals.clear()
        
    def getBand(self,bands,asflux=False,asdict=False):
        """
        determines the magnitude or flux in the requested band.
        
        The first photometric measurement in this SEDField that has
        the band will be used - if not present, it will be computed 
        from  the first Spectrum with appropriate overlap.  If none
        of these are found, a ValueError will be raised
        
        if asflux is True, the result will be returned as a flux - 
        otherwise, a magnitude is returned.
        
        asdict returns a dictionary of results - otherwise, a sequence will
        be returned (or a scalar if only one band is requested)
        """
        from .phot import str_to_bands
        print bands
        bands = str_to_bands(bands)
        vals = []
        for b,bn in zip(bands,[b.name for b in bands]):
            v = None
            for p in self.phots:
                if bn in p.bandnames:
                    i = p.bandnames.index(bn)
                    v = p.flux[i] if asflux else p.mag[i]
                    break
            if v is None:
                for s in self.specs:
                    if b.isOverlapped(s):
                        v = b.computeFlux(s) if asflux else b.computeMag(s)
                        break
            if v is None:
                raise ValueError('could not locate value for band '%bn)
            vals.append(v)
        
        if asdict:
            return dict([(b.name,v) for b,v in zip(bands,vals)])
        elif len(vals)==1:
            return vals[0]
        else:
            return vals
    
    def getFullSED(self):
        """
        the generates a astropysics.spec.Spectrum object that represents all 
        the information contained in this SEDField
        """
        from .spec import Spectrum
        
        x = np.array([])
        f = np.array([])
        e = np.array([])
        for s in self.specs:
            x = np.r_[x,s.x]
            f = np.r_[f,s.flux]
            e = np.r_[e,s.err]
        
        for p in self.phots:
            pf,pe = p.flux,p.err
            px,pw = p.getBandInfo()
            px = np.tile(px/pw,np.prod(px.shape)/len(p))
            px = px.reshape((len(p),np.prod(px.shape)/len(p)))
            pf = pf.reshape((len(p),np.prod(pf.shape)/len(p)))
            pe = pe.reshape((len(p),np.prod(pe.shape)/len(p)))
            x = np.r_[x,px]
            f = np.r_[f,pf]
            e = np.r_[e,pe]
            
        return Spectrum(x,f,e,unit=self.unit)
        
    def plotSED(self,specerrs=True,photerrs=True,plotbands=True,colors=('b','g','r','r','k'),log='',clf=True):
        """
        Generates a plot of the SED of this object.
        
        colors is a tuple of colors as (spec,phot,specerr,photerr,other)
        """       
        from matplotlib import pyplot as plt
        from .spec import HasSpecUnits
        
        specs = self.specs
        phots = self.phots
        
        mxy1 = np.max([np.max(s.flux) for s in specs]) if len(specs) > 0 else None
        mxy2 = np.max([np.max(p.getFluxDensity(self.unit)[0]) for p in phots]) if len(phots) > 0 else None
        mxy = max(mxy1,mxy2)
        mny1 = np.min([np.min(s.flux) for s in self.specs]) if len(specs) > 0 else None
        mny2 = np.min([np.min(p.getFluxDensity(self.unit)[0]) for p in self.phots]) if len(phots) > 0 else None
        if mny1 is None:
            mny = mny2
        elif mny2 is None:
            mny = mny1
        else:
            mny = min(mny1,mny2)
        mxx1 = np.max([np.max(s.x) for s in self.specs]) if len(specs) > 0 else None
        mxx2 = np.max([np.max(p.getBandInfo(self.unit)[0]) for p in self.phots]) if len(phots) > 0 else None
        mxx = max(mxx1,mxx2)
        mnx1 = np.min([np.min(s.x) for s in self.specs]) if len(specs) > 0 else None
        mnx2 = np.min([np.min(p.getBandInfo(self.unit)[0]) for p in self.phots]) if len(phots) > 0 else None
        if mnx1 is None:
            mnx = mnx2
        elif mnx2 is None:
            mnx = mnx1
        else:
            mny = min(mnx1,mnx2)
        
        preint = plt.isinteractive()
        try:
            plt.interactive(False)

            if clf:
                plt.clf()
                
            if 'x' in log and 'y' in log:
                plt.loglog()
            elif 'x' in log:
                plt.semilogx()
            elif 'y' in log:
                plt.semilogy()
            
            c = (colors[0],colors[2],colors[4],colors[4])
            for s in specs:
                s.plot(fmt='-',ploterrs=specerrs,colors=c,clf=False)
                
            lss = ('--',':','-.','-')
            for i,p in enumerate(phots):
                if plotbands:
                    if plotbands is True:
                        plotbands = {'bandscaling':(mxy - mny)*0.5,'bandoffset':mny}
                    plotbands['ls'] = lss[i%len(lss)]
                p.plot(includebands=plotbands,fluxtype='fluxden',unit=self.unit,clf=False,fmt='o',c=colors[1],ecolor=colors[3])
                
            rngx,rngy=mxx-mnx,mxy-mny
            plt.xlim(mnx-rngx*0.1,mxx+rngx*0.1)
            plt.ylim(mny-rngy*0.1,mxy+rngy*0.1)
            
            xl = '-'.join(HasSpecUnits.strToUnit(self.unit)[:2])
            xl = xl.replace('wavelength','\\lambda')
            xl = xl.replace('frequency','\\nu')
            xl = xl.replace('energy','E')
            xl = xl.replace('angstrom','\\AA')
            xl = xl.replace('micron','\\mu m')
            xl = tuple(xl.split('-'))
            plt.xlabel('$%s/{\\rm %s}$'%xl)
            
            plt.ylabel('$ {\\rm Flux}/({\\rm erg}\\, {\\rm s}^{-1}\\, {\\rm cm}^{-2} {\\rm %s}^{-1})$'%xl[1])
            
            plt.show()
            plt.draw()
        finally:
            plt.interactive(preint)
    
class _SourceMeta(type):
    def __call__(cls,*args,**kwargs):
        obj = type.__call__(cls,*args,**kwargs)
        if obj._str in Source._singdict:
            singobj = Source._singdict[obj._str]
            ol = obj.location
            sl = singobj.location
            if ol is not None and ol != sl:
                from warnings import warn
                warn('overwriting location %s with %s in %s'%(sl,ol,singobj))
                singobj._adscode = obj._adscode
        else:
            Source._singdict[obj._str] = obj
            
        return Source._singdict[obj._str]

class Source(object):
    """
    A source for an observation/measurement/value.  Note that there is always 
    only one instance if a source at a given time - any two Sources with the
    same source string are the same object
    
    The source can optionally include a URL location to look up metadata 
    like authors, publication date, etc (location property)
    
    the constructor string can be of the form 'str/loc' in which case
    loc will be interpreted as the location, if it is not specified
    in the argument.  If it is 'str//loc', the loc will not be validated
    (e.g. it is assumed to be a correct ADS abstract code)
    """
    __metaclass__ = _SourceMeta
    __slots__=['_str','_adscode','__weakref__']
    
    from weakref import WeakValueDictionary
    _singdict = WeakValueDictionary()
    del WeakValueDictionary
    
    def __init__(self,src,location=None):
        src = str(src)
        
        if location is None and '/' in src:
            srcsp = src.split('/')
            
            if srcsp[-2] == '': #don't do checking for // case
                self._str = '/'.join(srcsp[:-2]).strip()
                self._adscode = srcsp[-1].strip()

            else:
                self._str = '/'.join(srcsp[:-1]).strip()
                self.location = srcsp[-1].strip()
        else:
            self._str = src
            self.location = location
        
    def __reduce__(self):
        return (Source,(self._str+('' if self._adscode is None else ('//'+self._adscode)),))
        
    def __str__(self):
        return 'Source '+self._str + ((' @' + self.location) if self._adscode is not None else '')
    
    adsurl = 'adsabs.harvard.edu'
    
    def _getLoc(self):
        return self._adscode
    def _setLoc(self,val):
        if val is not None:
            if val == '':
                val = None
            else:
                val = self._findADScode(val)
        self._adscode = val
    location = property(_getLoc,_setLoc)
    
    @staticmethod
    def _findADScode(loc):
        from urllib2 import urlopen,HTTPError
        from contextlib import closing


        lloc = loc.lower()
        if 'arxiv' in lloc:
            url = 'http://%s/abs/arXiv:%s'%(Source.adsurl,lloc.replace('arxiv:','').replace('arxiv','').strip())
        elif 'astro-ph' in lloc:
            url = 'http://%s/abs/arXiv:%s'%(Source.adsurl,lloc.replace('astro-ph:','').replace('astro-ph','').strip())
        elif 'doi' in lloc: #TODO:check if doi is case-sensitive
            url = 'http://%s/doi/%s'%(Source.adsurl,lloc.replace('doi:','').replace('doi',''))
        elif 'http' in lloc:
            url = loc
        else: #assume ADS abstract code
            url = 'http://%s/abs/%s'%(Source.adsurl,loc)
            
        url += '?data_type=PLAINTEXT'
        try:
            with closing(urlopen(url)) as page: #raises exceptions if url DNE
                for l in page:
                    if 'Bibliographic Code:' in l: 
                        return l.replace('Bibliographic Code:','').strip()
        except HTTPError:
            raise SourceDataError('Requested location %s does not exist at url %s'%(loc,url))
        raise SourceDataError('Bibliographic entry for the location %s had no ADS code, or parsing problem'%loc)
    
    
    _adsxmlcache = {}
    
    @staticmethod
    def clearADSCache(adscode=None, disable=False):
        """
        this clears the cache of the specified adscode, or everything, if 
        the adscode is None
        """
        if adscode is None:
            Source._adsxmlcache.clear()
        else:
            del Source._adsxmlcache[abscode]
    
    @staticmethod
    def useADSCache(enable=True):
        """
        This is used to disable or enable the cache for ADS lookups - if the 
        enable argument is True, the cache is enable (or unaltered if it
        is already active)) and if it is False, it will be disabled
        
        note that if the cache is disabled, all entries are lost
        """
        if enable:
            if Source._adsxmlcache is None:
                Source._adsxmlcache = {}
        else:
            Source._adsxmlcache = None
            
    def _getADSXMLRec(self):
        adscode = self._adscode
        if adscode is None:
            raise SourceDataError('No location provided for additional source data')
        
        if Source._adsxmlcache is not None and adscode in Source._adsxmlcache:
            xmlrec = Source._adsxmlcache[adscode]
        else:
            from urllib2 import urlopen
            from contextlib import closing
            from xml.dom.minidom import parseString
            
            with closing(urlopen('http://%s/abs/%s>data_type=XML'%(Source.adsurl,adscode))) as f:
                xmld = parseString(f.read())
            
            recs = xmld.getElementsByTagName('record')
            if len(recs) > 1:
                raise SourceDataError('Multiple matching ADS records for code %s'%adscode)
            
            xmlrec = recs[0]
            if Source._adsxmlcache is not None: 
                Source._adsxmlcache[adscode] = xmlrec
        
        return xmlrec
        
    def getBibEntry(self):
        """
        returns a string with the BibTeX formatted entry for this source, retrieved from ADS
        (requires network connection)
        """
        from urllib2 import urlopen
        
        if self._adscode is None:
            raise SourceDataError('No location provided for additional source data')
        
        with closing(urllib2.urlopen('http://%s/abs/%s>data_type=BIBTEX'%(Source.adsurl,self._adscode))) as xf:
            return xf.read()
        
    @property
    def authors(self):
        """
        The author list for this Source as a list of strings
        """
        rec = self._getADSXMLRec()
        return [e.firstChild.nodeValue for e in rec.getElementsByTagName('author')]
    
    @property
    def title(self):
        """
        The publication title for this Source
        """
        rec = self._getADSXMLRec()
        es = rec.getElementsByTagName('title')
        if len(es) != 1:
            raise SourceDataError('Title not found for %s'%self)
        return es[0].firstChild.nodeValue
    
    @property
    def abstract(self):
        """
        The abstract for this Source
        """
        rec = self._getADSXMLRec()
        es = rec.getElementsByTagName('abstract')
        if len(es) != 1:
            raise SourceDataError('Abstract not found for %s'%self)
        return es[0].firstChild.nodeValue
    
    @property
    def date(self):
        """
        The publication date of this Source
        """
        rec = self._getADSXMLRec()
        es = rec.getElementsByTagName('pubdate')
        if len(es) != 1:
            raise SourceDataError('Publication date not found for %s'%self)
        return es[0].firstChild.nodeValue
    
    @property
    def adsabs(self):
        """
        The URL for the ADS abstract of this Source
        """
        rec = self._getADSXMLRec()
        for e in rec.getElementsByTagName('link'):
            if e.attributes['type'].value == 'ABSTRACT':
                urlnodes = e.getElementsByTagName('url')
                if len(urlnodes)==1:
                    return urlnodes[0].firstChild.nodeValue
                else:
                    return [n.firstChild.nodeValue for n in urlnodes]
        raise SourceDataError('Abstract URL not found for %s'%self)
    
    @property
    def keywords(self):
        """
        The keywords for this source, and the type of the keywords, if 
        present
        """
        rec = self._getADSXMLRec()
        kwn = rec.getElementsByTagName('keywords')[0]
        kws = [n.firstChild.nodeValue for n in kwn.getElementsByTagName('keyword')]
        try:
            type = kwn.attributes['type'].value
        except KeyError:
            type = None
        return kws,type
    
class FieldValue(object):
    __metaclass__ = ABCMeta
    __slots__ = ('_source')
    
    @abstractmethod
    def __init__(self):
        self._source = None
    
    def __getstate__(self):
        return {'_source':self._source}
    def __setstate__(self,d):
        self._source = d['_source']
    
    value = abstractproperty()
    
    def _getSource(self):
        return self._source
    def _setSource(self,val):
        if not (val is None or isinstance(val,Source)):
            try:
                val = Source(val)
            except: 
                raise TypeError('Input source is not convertable to a Source object')
        self._source = val 
    source=property(_getSource,_setSource)
    
    def checkType(self,typetocheck):
        """
        ensure that the value of this FieldValue is of the requested Type
        (or None to accept anything).  Any mismatches will throw
        a TypeError
        """
        if typetocheck is not None:
            from operator import isSequenceType
            if isinstance(typetocheck,type):
                self._doTypeCheck((typetocheck,),self.value)
            elif callable(typetocheck):
                if not typetocheck(self.value):
                    raise TypeError('custom function type-checking failed')
            elif isSequenceType(typetocheck):
                self._doTypeCheck(typetocheck,self.value)
            else:
                raise ValueError('invalid type to check')
        
    def _doTypeCheck(self,types,val):
        """
        handles interpretation of types - subclasses
        should call this with the val that should be checked
        if it is not the regular value
        """
        if val is not None:
            err = 'Type checking problem'
            for type in types:
                if isinstance(type,np.dtype):
                    if not isinstance(val,np.ndarray):
                        err = 'Value %s not a numpy array'%val
                        continue
                    if self.value.dtype != type:
                        err = 'Array %s does not match dtype %s'%(val,type)
                        continue
                elif not isinstance(val,type):
                    err = 'Value %s is not of type %s'%(val,type)
                    continue
                return
            raise TypeError(err)
    
    def __call__(self):
        return self.value
    
    def __str__(self):
        return 'Value %s'%self.value
    
class ObservedValue(FieldValue):
    """
    This value is a observed or otherwise measured value for the field
    with the associated Source.
    """
    __slots__=('_value')
    def __init__(self,value,source):
        super(ObservedValue,self).__init__()
        if not isinstance(source,Source):
            source = Source(source)
        self.source = source
        self._value = value
        
    def __getstate__(self):
        d = super(ObservedValue,self).__getstate__()
        d['_value'] = self._value
        return d
    def __setstate__(self,d):
        super(ObservedValue,self).__setstate__(d)
        self._value = d['_value']
        
    def __str__(self):
        return 'Value %s:%s'%(self.value,self.source)
    
    @property    
    def value(self):
        return self._value
        
class DerivedValue(FieldValue):
    """
    A FieldValue that derives its value from a function of other FieldValues
    
    the values to use as arguments to the function are initially set through 
    the default values of the function, and can be either references to 
    fields or strings used to locate the dependencies in the catalog tree, 
    using the sourcenode argument as the current source (see DependentSource 
    for details of how dependent values are derefernced)
    
    Alternatively, the initializer argument ``flinkdict`` may 
    be a dictionary of link values that overrides the defaults 
    from the function
    
    
    The class attribute ``failedvalueaction`` determines the action to take if a
    problem is encountered in deriving the value and can be:
    *'raise':raise an exception (or pass one along)
    *'warn': issue a warning when it occurs, but continue execution with the 
    value returned as None
    *'skip':the value will be returned as None but the value
    will be left invalid
    *'ignore':the value will be returned as None and will be marked valid
    """
    __slots__=('_f','_value','_valid','_fieldwr')
    #TODO: auto-reassign nodepath from source if Field moves
    failedvalueaction = 'raise' 
    
    def __init__(self,f,sourcenode=None,flinkdict=None):
        import inspect
        
        if callable(f):
            self._f = f
            args, varargs, varkw, defaults = inspect.getargspec(f)
            
            if varargs or varkw:
                raise TypeError('DerivedValue function cannot have variable numbers of args or kwargs')
            if flinkdict is not None and len(flinkdict) > 0:
                #populate any function defaults if not given already
                if defaults is not None:
                    for a,d in zip(reversed(args),defaults):
                        if a not in flinkdict:
                            flinkdict[a] = d
                defaults = [flinkdict[a] for a in args if a in flinkdict]
                
            if defaults is None or len(args) != len(defaults) :
                raise TypeError('DerivedValue does not have enought initial linkage items')
        else:
            raise TypeError('attempted to initialize a DerivedValue with a non-callable')
        
        self._valid = False
        self._value = None
        
        self._fieldwr = None
        self._source = DependentSource(defaults,sourcenode,self._invalidateNotifier)
        
    def __getstate__(self):
        d = super(DerivedValue,self).__getstate__()
        d['_value'] = self._value
        from pickle import PicklingError
        raise PicklingError("DerivedValue can't be pickled because it depends on a function")
        d['_f'] = self._f #TODO: find some way to work around the function pickling issue?
        return d
    def __setstate__(self,d):
        super(DerivedValue,self).__setstate__(d)
        self._value = d['_value']
        self._valid = False
        self._fieldwr = None
        self._f = d['_f'] #TODO: find some way to work around this?
        
    def __str__(self):
        try:
            return 'Derived value: %s'%self.value
        except:
            return 'Derived value: Underivable'
    
    @property
    def source(self):
        return self._source
    
    @property
    def flinkdict(self):
        from inspect import getargspec
        
        args = getargspec(self._f)[0]
        return dict([t for t in zip(args,self.source.depstrs)])
    
    def _getNode(self):
        return self._source.pathnode
    def _setNode(self,val):
        self._source.pathnode = val
    sourcenode=property(_getNode,_setNode,doc='The current location in the Catalog tree')
    
    def _getField(self):
        return None if self._fieldwr is None else self._fieldwr()
    def _setField(self,val):
        if val is None:
            self._notifierwr = None
        else:
            from weakref import ref
            self._fieldwr = ref(val)
    field=property(_getField,_setField,doc='A function like Field.notifyValueChange')

    
    def checkType(self,typetocheck):
        oldaction = DerivedValue.failedvalueaction
        try:
            DerivedValue.failedvalueaction = 'skip'
            super(DerivedValue,self).checkType(typetocheck)
        finally:
            DerivedValue.failedvalueaction = oldaction
    checkType.__doc__ = FieldValue.checkType.__doc__
    
    def _invalidateNotifier(self,oldval,newval):
        return self.invalidate()
    
    
    __invcycleinitiator = None
    def invalidate(self):
        """
        This marks this derivedValue as incorrect
        """
        try:
            if DerivedValue.__invcycleinitiator is None:
                DerivedValue.__invcycleinitiator = self
            elif DerivedValue.__invcycleinitiator is self:
                raise CycleError('attempting to set a DerivedValue that results in a cycle')
            self._valid = False
            if self.field is not None:
                self.field.notifyValueChange(self,self)
        finally:
            DerivedValue.__invcycleinitiator = None
    
    @property
    def value(self):
        if self._valid:
            return self._value
        else:
            try:
                self._value = self._f(*self._source.getDeps())
                self._valid = True
            except (ValueError,IndexError),e:
                if self.failedvalueaction == 'raise':
                    if len(e.args) == 2 and isinstance(e.args[1],list):
                        fields = [self._f.func_code.co_varnames[i] for i in e.args[1]]
                        raise ValueError('Could not get dependent values for field%s %s'%('s' if len(fields)>1 else '',fields))
                    else:
                        raise
                elif self.failedvalueaction == 'warn':
                    from warnings import warn
                    if len(e.args) == 2 and isinstance(e.args[1],list):
                        fields = [self._f.func_code.co_varnames[i] for i in e.args[1]]
                        warn('Problem getting dependent values for field%s %s'%('s' if len(fields)>1 else '',fields))
                    else:
                        warn('Problem encountered while deriving value '+str(e))
                    self._value = None
                    self._valid = False
                elif self.failedvalueaction == 'skip':
                    self._value = None
                    self._valid = False
                elif self.failedvalueaction == 'ignore':
                    self._value = None
                    self._valid = True
                else:
                    raise ValueError('invalid failedvalueaction')
            
            return self._value

class DependentSource(Source):
    """
    This class holds weak references to the Field's that are
    necessary to generate values such as in DerivedValue. 
    
    This source must know the Node that it is expected to inhabit to properly
    interpret string codes for fields.  Otherwise, the input fields must be
    Field objects
    """
    
    __slots__ = ('depfieldrefs','depstrs','_pathnoderef','notifierfunc')
    _instcount = 0
    
    
    #depfieldrefs: weakrefs to FieldValue objects 
    #depstrs: strings that should be used to locate FieldValue objects 
    #_pathnoderef: weakref to the CatalogNode used to dereference 
    
    def __new__(cls,*args,**kwargs):
        obj = super(DependentSource,cls).__new__(cls)
        DependentSource._instcount += 1
        return obj
    
    def __noneer(self):
        return None
    
    def __init__(self,depfields,pathnode,notifierfunc=None):
        from weakref import ref
        
        self._str = 'dependent%i'%DependentSource._instcount
        self.depfieldrefs = depfieldrefs = []
        self.depstrs = depstrs = []
        self.pathnode = pathnode
        self.notifierfunc = notifierfunc
        
        for f in depfields:
            if isinstance(f,basestring):
                depstrs.append(f)
                depfieldrefs.append(self.__noneer)
            elif isinstance(f,Field):
                depstrs.append(None)
                depfieldrefs.append(ref(f))
                if notifierfunc is not None:
                    f.registerNotifier(notifierfunc)
            elif f is None:
                depstrs.append(None)
                depfieldsrefs.append(self.__noneer)
            else:
                raise ValueError('Unrecognized field code %s'%str(f))
    
    def __reduce__(self):
        #Only thing guaranteed are the strings
        return (DependentSource,(self.depstrs,None))
        
    def __len__(self):
        return len(self.depfieldrefs)
    
    @property
    def location(self):
        return None
    
    def _getPathnode(self):
        return self._pathnoderef()
    def _setPathnode(self,val):
        from weakref import ref
        
        if val is None:
            self._pathnoderef = self.__noneer
        else:
            if not isinstance(val,CatalogNode):
                raise TypeError('attemted to set pathnode that is not a CatalogNode')
            self._pathnoderef = ref(val)
        #invalidadte weakrefs that are dereferenced
        for i,s in enumerate(self.depstrs):
            if s is None:
                self.depfieldrefs[i] = self.__noneer
    pathnode = property(_getPathnode,_setPathnode,doc='The CatalogNode for dereferencing source names')
    
    @staticmethod
    def _locatestr(s,node):
        """
        this method translates from a string and a location to the actual
        targretted Field
        
        ^^^ means up that elements in the catalog, while ... means down 
        ^(name) means go up until name is found 
        """
#        if s in node.fieldnames:
#            return getattr(node,s)
#        else:
#            raise ValueError('Linked node does not have requested field "%s"'%self.depstrs[i])
        
        #TODO:optimize
        upd = {}
        for i,c in enumerate(s):
            if c is '^':
                d[i] = True
            if c is '.':
                d[i] = False
        if len(upd) == 0:
            return getattr(node,s)
        if len(s)-1 in upd:
            raise ValueError('Improperly formatted field string - no field name')
        
        pairs = []
        sortk = sorted(upd.keys())
        lasti = sortk[0]
        for i in sortk[1:]:
            pairs.append((lasti,i))
            lasti = i
        if len(pairs) == 0:
            pairs.append((sortk[0]-1,sortk[0]))
            
        for i1,i2 in pairs:
            if i2-i1 == 1:
                if upd[i1]:
                    node = node.parent
                else:
                    node = node.children[0]
            else:
                subs = s[i1:i2]
                if upd[i1]:
                    try:
                        node = node.parent
                        while node.__class__!=substr and node['name']!=substr:
                            node = node.parent
                    except AttributeError:
                        raise ValueError('No parrent matching "%s" found'%substr)
                else:
                    try:
                        nchild = int(subs)
                        node = node.children[nchild]
                    except ValueError:
                        startnode = node
                        for n in node.children:
                            if node.__class__==substr or node['name']==substr:
                                node = n
                                break
                        if node is startnode:
                            raise ValueError('No child matching "%s" found'%substr)
        
    
    def populateFieldRefs(self):
        """
        this relinks all dead weakrefs using the dependancy strings and returns 
        all of the references or raises a ValueError if any of the strings
        cannot be dereferenced
        """
        from weakref import ref
        
        if self.pathnode is None:
            refs = [wr() for wr in self.depfieldrefs]
            if None in refs:
                raise ValueError('Missing/dead field(s) cannot be dereferenced without a catalog location',[i for i,r in enumerate(refs) if r is None])
        else:
            if not hasattr(self.pathnode,'fieldnames'):
                raise ValueError('Linked pathnode has no fields or does not exist')
            
            refs = []
            
            for i,wrf in enumerate(self.depfieldrefs):
                if wrf() is None:
                    f = self._locatestr(self.depstrs[i],self.pathnode)
                    refs.append(f)
                    self.depfieldrefs[i] = ref(f)
                    if self.notifierfunc is not None:
                            f.registerNotifier(self.notifierfunc)
                else:
                    refs.append(wrf())
        
        return refs
        
    def getDeps(self):
        """
        get the values of the dependent fields
        """
        fieldvals = [wr() for wr in self.depfieldrefs]    
        if None in fieldvals:
            fieldvals = self.populateFieldRefs()
        return [fi() for fi in fieldvals]
    
#<------------------------------Node types------------------------------------->
class Catalog(CatalogNode):
    """
    This class represents a catalog of objects or catalogs.
    
    A Catalog is essentially a node in the object tree that 
    must act as a root.
    """    
    def __init__(self,name='default Catalog'):
        super(Catalog,self).__init__(parent=None)
        self.name = name
        
    def __str__(self):
        return 'Catalog %s'%self.name 
    
    @property
    def parent(self):
        return None    
    
    #these methods allow support for doing uniform mapping-like lookups over a catalog
    def __contains__(self,key):
        return hasattr(self,key)
    def __getitem__(self,key):
        return getattr(self,key)
    
class _StructuredFieldNodeMeta(ABCMeta):
    #Metaclass is used to check at class creation-time that fields all match names
    def __new__(mcs,name,bases,dct):
        cls = super(_StructuredFieldNodeMeta,mcs).__new__(mcs,name,bases,dct)
        for k,v in dct.iteritems():
            if isinstance(v,Field) and k != v.name:
                raise ValueError('StructuredFieldNode class %s has conficting field names - Node attribute:%s, Field.name:%s'%(name,k,v.name))
        return cls

class StructuredFieldNode(FieldNode):
    """
    This class represents a FieldNode in the catalog that follows a particular
    data structure (i.e. a consistent set of Fields).  It is meant to be
    subclassed to define generic types of objects in the catalog.
    
    The fields and names are inferred from the class definition and 
    hence the class attribute name must match the field name.  Any 
    FieldValues present in the class objects will be ignored
    """
    __metaclass__ = _StructuredFieldNodeMeta
    
    @staticmethod
    def __fieldInstanceCheck(x):
        return isinstance(x,Field) or (isinstance(x,tuple) and len(x) == 2 and isinstance(x[0],DerivedValue))
    
    def __init__(self,parent):
        import inspect
        
        super(StructuredFieldNode,self).__init__(parent)
        self._altered = False
       
        dvs=[]  #derived values to apply to fields as (derivedvalue,field)
        #apply Fields from class into new object as new Fields
        for k,v in inspect.getmembers(self.__class__,self.__fieldInstanceCheck):
            if isinstance(v,tuple):
                dv,fi = v
            else:
                fi = v
                dv = None

            if None in fi:
                fobj = fi.__class__(fi.name,type=fi.type,defaultval=fi.default, usedef=True)
            else:
                fobj = fi.__class__(fi.name,type=fi.type)
            setattr(self,k,fobj)
            fobj.node = self
            
            if dv is not None:
                dvs.append((dv,fobj))
            
            self._fieldnames.append(k)
            
        for dv,fobj in dvs:
            fobj.insert(0,DerivedValue(dv._f,self,dv.flinkdict))
            
    def __getstate__(self):
        import inspect
        
        currderind = {}
        for k,v in inspect.getmembers(self.__class__,self.__fieldInstanceCheck):
            if isinstance(v,tuple):
                n = v[1].name
                if n in self._fieldnames:
                    fi = getattr(self,n)
                    while 'derived' in fi:
                        dv = fi['derived']
                        if dv._f is v[0]._f:
                            currderind[n] = fi.index(dv)
                        del fi[dv._source._str]
                    
        d = super(StructuredFieldNode,self).__getstate__()
        d['_altered'] = self._altered
        d['currderind'] = currderind
        return d
    def __setstate__(self,d):
        import inspect
        
        self._altered = d['_altered']
        super(StructuredFieldNode,self).__setstate__(d)
        for k,v in inspect.getmembers(self.__class__,self.__fieldInstanceCheck):
            if isinstance(v,tuple):
                n = v[1].name
                if n in self._fieldnames:
                    fi = getattr(self,n)
                    try:
                        ind = d['currderind'][n]
                    except KeyError:
                        from warnings import warn
                        warn('missing current index for structured derived value "%s" - assuming as default'%n)
                        ind = 0
                    if ind > len(fi):
                        ind = len(fi)
                    fi.insert(ind,DerivedValue(v[0]._f,self,v[0].flinkdict))
    
    @property
    def alteredstruct(self):
        """
        If True, the object no longer matches the specification given by the 
        class.  Note that this will remain True even if the offending fields
        are returned to their correct state.
        """
        return self._altered
    
    def revert(self):
        """
        Revert this object back to the standard Fields for  the class.
        Any deleted fields will be populated with the class Default Value
        any attributes that match the names of deleted Fields will be 
        overwritten
        
        TODO:test
        """
        import inspect,types
        
        dvs=[]  #derived values to apply to fields as (derivedvalue,field)
        #replace any deleted Fields with defaults and keep track of which should be kept
        fields=[]
        for k,v in inspect.getmembers(self.__class__,self.__fieldInstanceCheck):
            if isinstance(v,tuple):
                dv,fi = v
            else:
                fi = v
                dv = None
                
            fields.append(k)
            if not hasattr(self,k) or not isinstance(getattr(self,k),Field):
                if None in fi:
                    fobj = fi.__class__(fi.name,fi.type,fi.default, True)
                else:
                    fobj = fi.__class__(fi.name,fi.type)
                setattr(self,k,fobj)
                fobj.node = self
                
                if dv is not None:
                    dvs.append((dv,fobj))
        for k,v in inspect.getmembers(self,lambda x:isinstance(x,Field)):
            if k not in fields:
                delattr(self,k)
        
        self._fieldnames = fields
        
        for dv,fobj in dvs:
            fobj.insert(0,DerivedValue(dv._f,self,dv.flinkdict))
        
        self._altered = False
        self.addField = types.MethodType(StructuredFieldNode.addField,self,StructuredFieldNode)
        self.delField = types.MethodType(StructuredFieldNode.delField,self,StructuredFieldNode)
    
    def addField(self,field):
        self._altered = True
        self.addField = super(StructuredFieldNode,self).addField
        self.addField(field)
        
    def delField(self,fieldname):
        self._altered = True
        self.delField = super(StructuredFieldNode,self).delField
        self.delField(fieldname)
    
    @staticmethod
    def derivedFieldFunc(f=None,name=None,type=None,defaultval=None,usedef=None,**kwargs):
        """
        this method is to be used as a function decorator to generate a 
        field with a name matching that of the function.  Note that the
        function should NOT have self as the leading argument
        
        Arguments are the same as for the Field constructor, except that 
        leftover kwargs are passed in as links that override the 
        defaults of the function
        """
        if f is None: #allow for decorator arguments
            return lambda f:StructuredFieldNode.derivedFieldFunc(f,name,type,defaultval,usedef,**kwargs)
        else: #do actual operation
            if name is None:
                name = f.__name__
            fi = Field(name=name,type=type,defaultval=defaultval,usedef=usedef)
            dv = DerivedValue(f,None,kwargs)
            return dv,fi
        
        
#<--------------------builtin catalog types------------------------------------>

class AstronomicalObject(StructuredFieldNode):
    from .coords import AngularPosition
    
    def __init__(self,parent=None,name='default Name'):
        super(AstronomicalObject,self).__init__(parent)
        self.name.default=name
        
    def __str__(self):
        return 'Object %s'%self.name()
        
    _fieldorder = ('name','loc')
    name = Field('name',basestring)
    loc = Field('loc',AngularPosition)
    sed = SEDField('sed')

class Test1(AstronomicalObject):
    num = Field('num',float,4.2)
    
    @StructuredFieldNode.derivedFieldFunc(defaultval='f')
    def f(num='num'):
        return num+1
    
class Test2(AstronomicalObject):
    num = Field('num',float,4.2)
    
    @StructuredFieldNode.derivedFieldFunc(num='num')
    def f(num):
        return num+1
    
def test_cat():
    c=Catalog()
    ao=AstronomicalObject(c,'group')
    t1=Test1(ao)
    t12=Test1(ao)
    t13=Test1(ao)
    t13.sed['src'] = ('BVRI',[12,11.5,11.3,11.2])
    
    
    return c,locals()

def test_sed():
    from numpy.random import randn,rand
    from numpy import linspace
    from .spec import Spectrum
    from .phot import PhotObservation
    from .models import BlackbodyModel
    
    f = SEDField()
    scale = 1e-9
    
    f['s1'] = Spectrum(linspace(3000,8000,1024),scale*(randn(1024)/4+2.2),scale*rand(1024)/12)
    m = BlackbodyModel(T=3300)
    m.peak = 2.2
    x2 = linspace(7500,10000,512)
    err = randn(512)/12
    f['s2'] = Spectrum(x2,scale*(m(x2)+err),scale*err)
    
    f['o1'] = PhotObservation('BVRI',[13,12.1,11.8,11.5],.153)
    f['o2'] = PhotObservation('ugriz',randn(5,12)+12,rand(5,12)/3)
    
    return f

    
del ABCMeta,abstractmethod,abstractproperty,Sequence,MutableSequence,pi,division #clean up namespace
  
